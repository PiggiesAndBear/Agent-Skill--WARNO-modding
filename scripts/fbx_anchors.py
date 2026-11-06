#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fbx_anchors.py — 不依赖 Blender 直接读 FBX 7.x 二进制，校验单位网格的节点与锚点；
另外能读烘焙产物 `.baf` 的节点块表，验证「补的骨骼有没有真的进动画」。

为什么需要它：WARNO 靠「空物体（Null）名字」驱动特效/炮塔/旋翼，缺一个被 NDF 引用的
名字就是 Fatal error / CTD，而这类缺失**编译期不报错**。Blender 打开 FBX 又慢又容易被
导入设置改动。本脚本直接读二进制，秒级给出「有哪些节点、什么类型、父子关系如何」。

⚠ 这是解析 FBX 7.x，不是「导入导出」。查坐标请用 Blender。

用法：
    python fbx_anchors.py dump  <file.fbx> [more.fbx ...]      # 列全部节点 + 层级
    python fbx_anchors.py check <file.fbx> [more.fbx ...]      # 默认规则体检
    python fbx_anchors.py check <file.fbx> --need a,b,c        # 指定必须存在的名字
    python fbx_anchors.py check <file.fbx> --need-file n.txt   # 每行一个名字
    python fbx_anchors.py check <file.fbx> --child helice_ls_1=bloc_moteur_1
    python fbx_anchors.py baf   <file.baf> [more.baf ...]      # 烘焙产物节点块表
    python fbx_anchors.py baf   x.baf --expect-nodes 40 --expect-anim 33
    python fbx_anchors.py baf   x.baf --grep missile_1,fx_moteur

退出码：0 全部命中 / 1 有缺失或规则不符 / 2 文件读不了
多文件时：逐个处理，任一失败则整体 rc=1。

—— `baf` 子命令是干什么的 ——
`.baf` 是 AssetCooker 从动画 FBX 烘出来的**矩阵数组**，引擎不推层级、逐节点读绝对矩阵。
所以「我在绑定里补了 21 项约定骨骼」这件事，**FBX 里有名字 ≠ baf 里有节点块**。
本项目实测：补 21 项骨骼后节点块 19 → 40（+21）。判据就是**节点块数按新增数量上涨**。
⚠ 别用 `count('名字')` 当判据：`.neu3` / `.baf` 的字符串池会用共享前后缀，
   `count('fx_moteur')` 会得 0。用 `--grep` 只是辅助观察，**不作判据**。

—— 实现要点（踩过的坑，改代码前先读）——
FBX 7400 格式：**同级节点之间没有空记录分隔**。一个节点的 end_offset 指向下一个同级节点，
但**如果该节点有子节点**，end_offset 指向的是它自己那段 13 字节全零终止记录，
必须跳过这 13 字节才能到下一个同级。判据是「end_off 处是否真是 13 字节全 0」，
不能无条件 +13（早期版本无条件跳，解析在第 19338 字节反复错位）。
64 位版本（>=7500）终止记录是 25 字节，头部字段也是 8 字节。
"""
import sys
import os
import struct
import argparse


# ---------------------------------------------------------------- 底层读取

def _u32(b, o):
    return struct.unpack_from('<I', b, o)[0]


def _i32(b, o):
    return struct.unpack_from('<i', b, o)[0]


def _i64(b, o):
    return struct.unpack_from('<q', b, o)[0]


def _read_property(b, o):
    """读一个属性。返回 (新偏移, (类型码, 值))。数组只记录形状不展开。"""
    tc = chr(b[o])
    o += 1
    if tc == 'Y':
        v = struct.unpack_from('<h', b, o)[0]; o += 2
    elif tc == 'C':
        v = b[o]; o += 1
    elif tc == 'I':
        v = _i32(b, o); o += 4
    elif tc == 'F':
        v = struct.unpack_from('<f', b, o)[0]; o += 4
    elif tc == 'D':
        v = struct.unpack_from('<d', b, o)[0]; o += 8
    elif tc == 'L':
        v = _i64(b, o); o += 8
    elif tc == 'R':
        ln = _i32(b, o); o += 4; v = b[o:o + ln]; o += ln
    elif tc == 'S':
        ln = _i32(b, o); o += 4
        v = b[o:o + ln].decode('utf-8', 'replace'); o += ln
    elif tc == 'A':
        at = chr(b[o]); o += 1
        ln = _i32(b, o); o += 4
        enc = _i32(b, o); o += 4
        if enc == 1:
            comp_len = _i32(b, o); o += 4
            o += comp_len
        else:
            sz = {'b': 1, 'c': 1, 'i': 4, 'l': 8, 'f': 4, 'd': 8}.get(at, 0)
            o += ln * sz
        v = ('ARRAY', at, ln, enc)
    else:
        raise ValueError('unknown property type %r at %d' % (tc, o - 1))
    return o, (tc, v)


def _is_null_record(b, off, null_size):
    if off + null_size > len(b):
        return False
    return all(b[off + i] == 0 for i in range(null_size))


def _read_node(b, o, is64):
    """读一个节点。返回 (节点 dict 或 None, 下一个偏移)。"""
    null_size = 25 if is64 else 13
    try:
        if is64:
            end_off = struct.unpack_from('<Q', b, o)[0]; o += 8
            nprops = struct.unpack_from('<Q', b, o)[0]; o += 8
            plist_len = struct.unpack_from('<Q', b, o)[0]; o += 8
        else:
            end_off = _u32(b, o); o += 4
            nprops = _u32(b, o); o += 4
            plist_len = _u32(b, o); o += 4
        nlen = b[o]; o += 1
    except struct.error:
        return None, o

    # 全零 = 子节点列表终止符，先于合法性检查判定
    if nlen == 0 and nprops == 0 and end_off == 0:
        return None, o
    if end_off <= o or end_off > len(b):
        return None, o

    name = b[o:o + nlen].decode('ascii', 'replace'); o += nlen
    props = []
    props_end = o + plist_len
    try:
        while o < props_end and len(props) < nprops:
            o, p = _read_property(b, o)
            props.append(p)
    except Exception:
        pass
    o = props_end        # 无论属性是否读全，偏移都吸附到头部给出的属性区末尾

    children = []
    while o < end_off and o < len(b):
        c, o2 = _read_node(b, o, is64)
        o = o2
        if c is None:
            break
        children.append(c)

    o = end_off + null_size if _is_null_record(b, end_off, null_size) else end_off
    return {'name': name, 'props': props, 'children': children}, o


def parse(fpath):
    with open(fpath, 'rb') as f:
        data = f.read()
    if data[0:21] != b'Kaydara FBX Binary  \x00':
        raise SystemExit('[FAIL] 不是二进制 FBX：%s（ASCII 版或其它格式）' % fpath)
    version = _u32(data, 23)
    is64 = version >= 7500
    nodes = []
    o = 27
    while o < len(data):
        n, o = _read_node(data, o, is64)
        if n is None:
            break
        nodes.append(n)
    return version, nodes


# ---------------------------------------------------------------- 模型收集

def _clean(s):
    return (s or '').split('\x00')[0].strip()


def collect(nodes, models, conns):
    for nd in nodes:
        if nd['name'] == 'Model':
            p = nd['props']
            mid = p[0][1] if len(p) > 0 else None
            mname = _clean(p[1][1]) if len(p) > 1 else ''
            mcls = _clean(p[2][1]) if len(p) > 2 else ''
            models[mid] = (mname, mcls)
        elif nd['name'] == 'C' and len(nd['props']) >= 2:
            rel = nd['props'][0][1]
            child = nd['props'][1][1]
            parent = nd['props'][2][1] if len(nd['props']) > 2 else None
            conns.append((rel, child, parent))
        collect(nd['children'], models, conns)


def hierarchy(models, conns):
    parent_of = {}
    for rel, child, parent in conns:
        if parent is not None and child in models and parent in models:
            parent_of[child] = parent
    return parent_of


def is_mesh(cls):
    return 'Mesh' in cls


# ---------------------------------------------------------------- 默认规则

# 精灵/旋翼型克隆源（本项目 SuperDestroyer 走 Mi-24K）的强制名字。
# 换克隆源时这套会变——必须按克隆源模型的 depiction 字段重新枚举，不能照抄。
DEFAULT_MESH_NAME = 'Chassis'

DEFAULT_RULES = [
    # (类别, 说明)
    ('mesh', 'Chassis 必须是 Mesh 类型（不是 Null）'),
]


def default_must_have():
    """默认只查 Chassis。其余锚点请用 --need 显式列出。

    故意不内置「米-24 十件套」：那套是特定克隆源的，内置会造成误导。
    枚举方法见 references/23-mesh-import.md §3。
    """
    return [DEFAULT_MESH_NAME]


# ---------------------------------------------------------------- .baf 解析

# 节点块 <= 这个字节数就判「静态（无轨道）」。经验阈值：一条通道（位置 xyz 或
# 四元数）在整段帧上就要几十字节，纯粹一个矩阵是 64 字节。这个判据只用来回答
# 「新增骨骼有没有进 baf」，不用于精确语义判断。
BAF_STATIC_MAX = 64


def parse_baf(path):
    """读 .baf 头 + 节点块偏移表。失败抛 ValueError。

    格式（本项目自己逆出来的，WARNO 烘焙产物）：
        [0]  f32  duration 秒
        [4]  u32  packed：低 16 位 = 帧数，高 16 位 = 节点数
        [8]  u32  **语义不明**。原项目脚本把它当 fps，但实测 150 帧 / 5.000 s
                 = 30 fps，此字段为 24 —— 不是帧率。别用它，用 frames/duration。
        [12] u32  secB_off   数据段 B 起始偏移
        [16] u32  secA_size  数据段 A 字节数
        [20] u32  secB_size  数据段 B 字节数
        [24] u32 × nodes     每个节点块的起始偏移
    节点块 i 的范围 = [offs[i], offs[i+1])，最后一块到 secB_off。
    """
    with open(path, "rb") as f:
        b = f.read()
    n = len(b)
    if n < 24:
        raise ValueError("只有 %d 字节，不足 .baf 头长度 24" % n)
    dur = struct.unpack_from("<f", b, 0)[0]
    packed = struct.unpack_from("<I", b, 4)[0]
    frames, nodes = packed & 0xFFFF, packed >> 16
    unknown8 = struct.unpack_from("<I", b, 8)[0]
    secB_off, secA_size, secB_size = struct.unpack_from("<3I", b, 12)
    if nodes <= 0 or nodes > 100000:
        raise ValueError("节点数 %d 不合理（头部可能不是 .baf）" % nodes)
    head_end = 24 + nodes * 4
    if head_end > n:
        raise ValueError("节点偏移表要 %d 字节，文件只有 %d" % (head_end, n))
    offs = list(struct.unpack_from("<%dI" % nodes, b, 24))

    blocks = []
    anim = 0
    for i, off in enumerate(offs):
        end = offs[i + 1] if i + 1 < len(offs) else secB_off
        if end <= off or end > n:
            blocks.append(dict(i=i, offset=off, size=0, anim=False, broken=True))
            continue
        sz = end - off
        is_anim = sz > BAF_STATIC_MAX
        if is_anim:
            anim += 1
        blocks.append(dict(i=i, offset=off, size=sz, anim=is_anim, broken=False))

    return dict(file=os.path.abspath(path), bytes=n, dur=dur, frames=frames,
                nodes=nodes, unknown8=unknown8,
                fps=(frames / dur if dur > 0 else 0.0),
                secB_off=secB_off, secA_size=secA_size,
                secB_size=secB_size, blocks=blocks, anim_blocks=anim, raw=b)


def _grep_baf(raw, words):
    out = {}
    for w in words:
        for enc in ("ascii", "utf-16-le"):
            try:
                cnt = raw.count(w.encode(enc))
            except Exception:
                cnt = 0
            if cnt:
                out[w] = (cnt, enc)
                break
        else:
            out[w] = (0, "")
    return out


def cmd_baf(paths, expect_nodes, expect_anim, greps):
    rc = 0
    summary = []
    for p in paths:
        try:
            d = parse_baf(p)
        except (ValueError, OSError) as e:
            print("[FAIL] %s：%s" % (p, e))
            return 2

        print("=== %s ===" % os.path.basename(p))
        print("时长 %.3f s | 帧数 %d | 节点数 %d | fps %.1f（= 帧数/时长）"
              % (d["dur"], d["frames"], d["nodes"], d["fps"]))
        if abs(d["unknown8"] - d["fps"]) > 0.5:
            print("       [注] 头部 [8] 字段 = %d，**不是 fps**（语义未定，别拿它算时间）"
                  % d["unknown8"])
        print("数据段A [24,%d) = %d 字节 | 数据段B [%d,%d) = %d 字节 | 文件 %d 字节"
              % (d["secB_off"], d["secA_size"], d["secB_off"],
                 d["secB_off"] + d["secB_size"], d["secB_size"], d["bytes"]))
        print("\n %-4s %-9s %-8s %s" % ("#", "offset", "size", "判读"))
        for blk in d["blocks"]:
            if blk["broken"]:
                print(" %-4d %-9d %-8s [!] 偏移异常（越界或与下一块重叠）"
                      % (blk["i"], blk["offset"], "?"))
                continue
            print(" %-4d %-9d %-8d %s"
                  % (blk["i"], blk["offset"], blk["size"],
                     ("含轨道  floats=%d" % (blk["size"] // 4)) if blk["anim"]
                     else "静态（无轨道）"))
        print("\n带轨道节点块数 = %d / %d" % (d["anim_blocks"], d["nodes"]))

        if greps:
            g = _grep_baf(d["raw"], greps)
            print("[grep] 仅作观察，**不作判据**（字符串池用共享前后缀，命中 0 不代表不在）")
            for w, (cnt, enc) in g.items():
                print("   %-24s %d 次%s" % (w, cnt, "" if not cnt else "  (%s)" % enc))

        bad = []
        if expect_nodes is not None and d["nodes"] != expect_nodes:
            bad.append("节点数 %d ≠ 期望 %d" % (d["nodes"], expect_nodes))
        if expect_anim is not None and d["anim_blocks"] != expect_anim:
            bad.append("带轨道块数 %d ≠ 期望 %d" % (d["anim_blocks"], expect_anim))
        broken = [blk["i"] for blk in d["blocks"] if blk["broken"]]
        if broken:
            bad.append("%d 个节点块偏移异常（#%s）"
                       % (len(broken), ",".join(str(x) for x in broken[:8])))
        summary.append((os.path.basename(p), d["nodes"], d["anim_blocks"], bad))
        print()

    if len(summary) > 1:
        print("=== 汇总 ===")
        for nm, nd, an, bad in summary:
            print("  %-30s 节点 %-5d 带轨道 %-5d %s"
                  % (nm, nd, an, "" if not bad else "  [!] " + "; ".join(bad)))
        print()

    fails = [(nm, bad) for nm, _, _, bad in summary if bad]
    if fails:
        print("[FAIL] %d 个文件不合格" % len(fails))
        for nm, bad in fails:
            print("  %s: %s" % (nm, "; ".join(bad)))
        rc = 1
    else:
        print("[OK] %d 个 .baf 结构正常" % len(summary))
    return rc


# ---------------------------------------------------------------- 命令

def cmd_dump(fpath):
    ver, nodes = parse(fpath)
    models, conns = {}, []
    collect(nodes, models, conns)
    parent_of = hierarchy(models, conns)
    children_of = {}
    for c, p in parent_of.items():
        children_of.setdefault(p, []).append(c)

    print('FBX version %d  |  Model 节点 %d  |  连接 %d' % (ver, len(models), len(conns)))
    roots = [m for m in models if m not in parent_of]
    for r in roots:
        _show(models, children_of, r, 0)
    if not roots:
        print('  [警告] 没有根节点——连接表可能不完整')

    meshes = [n for n, (_, c) in models.items() if is_mesh(c)]
    nulls = [n for n, (_, c) in models.items() if not is_mesh(c)]
    print('\n合计：Mesh %d 个，空物体(Null) %d 个' % (len(meshes), len(nulls)))
    return 0


def _show(models, children_of, mid, depth):
    name, cls = models[mid]
    print('  ' * depth + '- %-26s [%s]' % (name or '<未命名>', cls or '?'))
    for ch in children_of.get(mid, []):
        _show(models, children_of, ch, depth + 1)


def cmd_check(fpath, need, pairs):
    ver, nodes = parse(fpath)
    models, conns = {}, []
    collect(nodes, models, conns)
    parent_of = hierarchy(models, conns)

    by_name = {}
    for mid, (nm, cls) in models.items():
        by_name.setdefault(nm.lower(), []).append((mid, nm, cls))

    fail = []

    # 规则 1：主网格名必须是 Chassis 且为 Mesh
    hits = by_name.get(DEFAULT_MESH_NAME.lower(), [])
    if not hits:
        fail.append('主网格缺失：没有任何节点叫 %r（引擎硬规则名）' % DEFAULT_MESH_NAME)
    elif not any(is_mesh(c) for _, _, c in hits):
        fail.append('主网格 %r 存在但不是 Mesh 类型（是 %s）'
                    % (DEFAULT_MESH_NAME, hits[0][2]))

    # 规则 2：所有 --need 名字必须存在
    missing = []
    for nm in need:
        if nm.lower() not in by_name:
            missing.append(nm)
    if missing:
        fail.append('缺 %d 个锚点/骨骼：%s' % (len(missing), ', '.join(missing)))

    # 规则 3：父子关系
    for child, parent in pairs:
        ch = by_name.get(child.lower())
        pa = by_name.get(parent.lower())
        if not ch:
            fail.append('层级检查跳过：%r 不存在' % child)
            continue
        if not pa:
            fail.append('层级检查跳过：父级 %r 不存在' % parent)
            continue
        pid = pa[0][0]
        got = parent_of.get(ch[0][0])
        if got != pid:
            got_name = models[got][0] if got in models else '<root>'
            fail.append('%r 的父级应为 %r，实际是 %r' % (child, parent, got_name))

    meshes = sum(1 for _, (_, c) in models.items() if is_mesh(c))
    nulls = len(models) - meshes
    print('FBX version %d  |  Mesh %d  |  Null %d  |  待查名字 %d 个'
          % (ver, meshes, nulls, len(need)))

    if fail:
        print('\n[FAIL] %d 项不合格：' % len(fail))
        for i, f in enumerate(fail, 1):
            print('  %d. %s' % (i, f))
        return 1

    print('[OK] 主网格 %s 是 Mesh；%d 个名字全部命中；层级检查通过'
          % (DEFAULT_MESH_NAME, len(need)))
    return 0


def main():
    ap = argparse.ArgumentParser(description='FBX 7.x 锚点/节点校验 + .baf 节点块表（都不依赖 Blender）')
    ap.add_argument('cmd', choices=['dump', 'check', 'baf'])
    ap.add_argument('files', nargs='+', metavar='file',
                    help='dump/check 给 .fbx；baf 给 .baf。可给多个，逐个处理')
    ap.add_argument('--need', default='', help='逗号分隔的必须存在的名字')
    ap.add_argument('--need-file', default='', help='每行一个名字的文本文件')
    ap.add_argument('--child', action='append', default=[],
                    help='父子约束，形如 子=父，可重复')
    ap.add_argument('--expect-nodes', type=int, default=None,
                    help='baf：期望节点块数（补骨骼后应等于旧值+新增数）')
    ap.add_argument('--expect-anim', type=int, default=None,
                    help='baf：期望带轨道块数')
    ap.add_argument('--grep', default='',
                    help='baf：逗号分隔的字符串，仅作观察（字符串池会漏，不作判据）')
    a = ap.parse_args()

    for f in a.files:
        if not os.path.exists(f):
            print('[FAIL] 文件不存在：%s' % f)
            return 2

    if a.cmd == 'baf':
        greps = [x.strip() for x in a.grep.split(',') if x.strip()]
        return cmd_baf(a.files, a.expect_nodes, a.expect_anim, greps)

    if a.cmd == 'dump':
        rc = 0
        for i, f in enumerate(a.files):
            if len(a.files) > 1:
                print('\n########## %s ##########' % os.path.basename(f))
            rc = max(rc, cmd_dump(f))
        return rc

    need = [x.strip() for x in a.need.split(',') if x.strip()]
    if a.need_file:
        with open(a.need_file, encoding='utf-8') as f:
            need += [ln.strip() for ln in f if ln.strip() and not ln.startswith('#')]
    pairs = []
    for spec in a.child:
        if '=' not in spec:
            print('[FAIL] --child 需要 子=父 形式：%r' % spec)
            return 2
        c, p = spec.split('=', 1)
        pairs.append((c.strip(), p.strip()))

    rc = 0
    for f in a.files:
        if len(a.files) > 1:
            print('\n########## %s ##########' % os.path.basename(f))
        rc = max(rc, cmd_check(f, need, pairs))
    return rc


if __name__ == '__main__':
    sys.exit(main())
