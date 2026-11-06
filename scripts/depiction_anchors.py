#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""depiction_anchors.py — 从 NDF 描绘链正向枚举「模型必须有的节点名」。

为什么需要它：换模型时最容易犯的错是照抄别的模型的骨骼名。正确做法是从单位的
depiction 出发，沿 Operators / SubDepictions 一路把 Anchors、ZAxisNode、YAxisNode、
*BoneName 全部收集起来——这就是 FBX 里必须存在的空物体名全集。手工翻容易漏，
漏一个就是加载时 Fatal error / CTD（编译期不报错）。

用法：
    python depiction_anchors.py <ndf文件> --key SE_SuperDestroyer_US
    python depiction_anchors.py <ndf文件> --object DepictionOperator_HelicopterLanding
    python depiction_anchors.py <目录或文件> --key X --out names.txt
    python depiction_anchors.py <文件> --key X --verbose     # 每个名字标出来源

拿到 names.txt 后直接喂给校验器：
    python fbx_anchors.py check <model.fbx> --need-file names.txt

退出码：0 找到 / 1 没找到块 / 2 参数或文件问题
"""
import sys
import os
import re
import argparse

# 只认这几类字段——它们才是「引擎按名字找节点」的地方。
# 不含 CoatingName / MimeticName 等资源名，那些不是 FBX 节点。
FIELD_RE = re.compile(
    r"""(?P<field>
            Anchors?         |   # Anchors=[...] 复数；Anchor="..." 单数（子描绘 / Action）
            \w*Node           |   # ZAxisNode / YAxisNode / RecoilNode / PitchNode …
            \w*BoneName       |   # HelixBoneName / BladesBoneName …
            SousMobileName    |   # 底盘算子：'chassis'
            SousMobile            # 特效挂点：fx_stress_01
        )
        \s*=\s*
        (?:\[[^\]]*\]|"[^"]*"|'[^']*')     # 列表 / 双引号 / 单引号，三种都要认
    """,
    re.X,
)
QUOTED_RE = re.compile(r"'([^']+)'|\"([^\"]+)\"")

# 描绘链上的下游引用：算子实例（Op_*）、算子类型（DepictionOperator_*）、
# 以及 `$/GFX/...` 形式的路径引用（取最后一段做对象名）。
# 分成两条正则，避免捕获组把 findall 的结果搅乱。
REF_RE = re.compile(
    r"(?:Op_\w+|DepictionOperator_\w+|AllWeaponAlternatives_\w+"
    r"|DepictionAction_\w+|GfxDescriptorChassis_\w+)")
REF_PATH_RE = re.compile(r"[$~][\w/$]*?/(\w+)")

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def strip_comments(text):
    """把 `//` 行注释替换成空格。

    必需，不能省：NDF 的注释里有法文撇号（`d'indices`）和括号，
    会把「跳过字符串」和「括号配平」两条逻辑同时带偏 —— 实测表现为
    找得到 key、却切不出块。
    用空格替换而不是删除，保持字符偏移不变，方便回溯定位。
    """
    out = list(text)
    n = len(text)
    i = 0
    quote = ''          # '' = 不在字符串里；否则是当前定界符
    while i < n:
        c = text[i]
        if c == '\n':
            quote = ''
            i += 1
        elif quote:
            if c == quote:
                quote = ''
            i += 1
        elif c in ("'", '"'):
            quote = c
            i += 1
        elif c == '/' and i + 1 < n and text[i + 1] == '/':
            j = text.find('\n', i)
            if j < 0:
                j = n
            for k in range(i, j):
                out[k] = ' '
            i = j
        else:
            i += 1
    return ''.join(out)


def is_header(line):
    """这一行是不是对象头。

    ⚠ 不能要求行尾只有类型名。单行式定义（`X is Type( A = 'b' )`）把参数写在
    同一行，早期用 `^\\w+\\s+is\\s+\\w+$` 判定会漏认，回溯就跳到**上一个**对象的
    头上 —— 实测把 `Turret_1_HydraulicRecoil` 切成了 `Turret_5_Aim`，
    于是 `canon_01` 这个炮管后座节点整条丢失。
    """
    s = line.strip()
    if re.match(r"^(export\s+\w+\s+is|unnamed)\s", s):
        return True
    return bool(re.match(r"^\w+\s+is\s+\S", s))


def find_block(text, needle):
    """返回包含 needle 的那个对象块文本。

    先定位 needle 所在行：**该行本身就是对象头**（`export X is Type` /
    `X is Type` / `unnamed Type`）就直接用它；否则向上回溯到最近的对象头。
    然后从头部第一个 `(` 起做括号配平，切出整块。

    ⚠ 回溯必须"先看本行再看上一行"。早期版本从上一行开始查，导致
    命中的正是 def 行时反而跳到了**前一个**定义上 —— 实测把
    `DepictionOperator_Heat` 切成了 `..._Propulsion_ContinuousTrack`。
    """
    idx = text.find(needle)
    if idx < 0:
        return None, None
    line_start = text.rfind('\n', 0, idx) + 1
    line_end = text.find('\n', line_start)
    if line_end < 0:
        line_end = len(text)

    head = None
    if is_header(text[line_start:line_end]):
        head = line_start
    else:
        cur = line_start
        for _ in range(300):                  # 最多回溯 300 行，防止跑到文件头
            prev = text.rfind('\n', 0, cur - 1)
            if prev < 0:
                head = 0
                break
            if is_header(text[prev + 1:cur]):
                head = prev + 1
                break
            cur = prev + 1
    if head is None:
        head = line_start

    # 从对象头开始找「块开符」：`(` 或 `[`
    # · 圆括号 = 普通 describe 块（TacticalVehicleDepictionRegistration 等）
    # · 方括号 = `MAP[ ... ]` 形式的 Action 表（MovementFX / Stress / Wrecked 全在这类里）
    head_end = text.find('\n', head)
    if head_end < 0:
        head_end = len(text)
    open_at, opener = -1, ''
    for i in range(head, min(len(text), head_end + 300)):
        c = text[i]
        if c in '([':
            open_at, opener = i, c
            break
    if open_at < 0:
        return text[head:head_end], head
    # ⚠ 若开符之前已经冒出新的对象头，说明当前对象是 `X is A + B` 这类组合定义，
    # 本身没有块；不设这道闸就会一路吞到下一个对象的 MAP[ 里，
    # 实测把 `aileron_d` / `fx_vortex_g` 这类毫不相干的挂点混进锚点集。
    if re.search(r"\n\s*(?:export\s+\w+\s+is|unnamed)\s|\n\w+\s+is\s+[\w$]",
                 text[head:open_at]):
        return text[head:head_end], head

    closer = ')' if opener == '(' else ']'
    depth = 0
    i = open_at
    while i < len(text):
        c = text[i]
        if c in ("'", '"'):                   # 跳过字符串（NDF 两种引号都用）
            j = text.find(c, i + 1)
            if j < 0:
                break
            i = j + 1
            continue
        if c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return text[head:i + 1], head
        i += 1
    return text[head:head + 3000], head


def extract(block, verbose):
    """从块里抽出 (名字, 字段) 二元组。NDF 单双引号都出现过，两种都要认。"""
    out = []
    for m in FIELD_RE.finditer(block):
        field = m.group('field')
        val = m.group(0).split('=', 1)[1]
        for g in QUOTED_RE.findall(val):
            name = (g[0] or g[1]).strip()
            if name and IDENT_RE.match(name):
                out.append((name, field))
    return out


def find_def(texts, name):
    """找 `name` 的**定义**块，返回 (块文本, 路径) 或 (None, None)。

    只认两种定义形式：`export <name> is <Type>` 和 `<name> is <Type>`（共享算子常无 export）。
    **不做模糊查找**——用 `name` 直接 find 会命中别处的**使用**行，进而切到隔壁单位的块，
    实测会把 `Op_A109A_RKT_UK_Weapon1` 的锚点混进来。

    ⚠ 名字与 `is` 之间的空白可能是**多个空格**（原文有对齐排版），
    用固定字符串 `"%s is "` 会漏 —— 实测 `DepictionOperator_Chassis_HeavyTank` 因此整条丢失，
    连带 `chassis` 根节点没进锚点集。
    """
    pat = re.compile(r"^(?:export\s+)?%s\s+is\b" % re.escape(name), re.M)
    for fp, text in texts:
        m = pat.search(text)
        if not m:
            continue
        block, _ = find_block(text, m.group(0))
        if block:
            return block, fp
    return None, None


def collect(texts, start_block, verbose, depth=0, seen_blocks=None, seen_names=None):
    """递归收集。texts 是 [(路径, 文本)]，算子定义可能在另一个文件里。"""
    if seen_blocks is None:
        seen_blocks = set()
    if seen_names is None:
        seen_names = {}          # name -> (field, 出处)
    if depth > 3:
        return seen_names, seen_blocks

    key = start_block.strip()[:120]
    if key in seen_blocks:
        return seen_names, seen_blocks
    seen_blocks.add(key)

    label = "[d%d] %s" % (depth, key.split('\n')[0][:70])

    for name, field in extract(start_block, verbose):
        if name not in seen_names:
            seen_names[name] = (field, label)
        else:
            f0, l0 = seen_names[name]
            if field not in f0:
                seen_names[name] = (f0 + '+' + field, l0)

    # 沿引用继续（同文件或同目录内的算子 / 子描绘定义）
    refs = set(REF_RE.findall(start_block)) | set(REF_PATH_RE.findall(start_block))
    # `X is A + B` 组合定义（如 DepictionAction_Stress_And_Wrecked）：把 `+` 右边
    # 的名字也当引用展开，否则 Stress / Wrecked 里的挂点全丢。find_def 命中不了的自会跳过。
    refs |= set(re.findall(r"\+\s*([A-Za-z_]\w{3,})", start_block))
    for ref in refs:
        if len(ref) < 4:
            continue
        sub, _fp = find_def(texts, ref)
        if sub:
            collect(texts, sub, verbose, depth + 1, seen_blocks, seen_names)

    return seen_names, seen_blocks


OPS_RELPATHS = (
    os.path.join('GameData', 'Gameplay', 'Gfx', 'Units', 'DepictionOperators.ndf'),
    os.path.join('GameData', 'Generated', 'Gameplay', 'Gfx', 'Units', 'DepictionOperators.ndf'),
)


def resolve_files(target):
    """决议要扫哪些文件。

    目录模式：只扫 Depiction 系文件（算子与描绘块都在里面）。UniteDescriptor /
    WeaponDescriptor 动辄几十万行且不含锚点字段，扫了纯属浪费。
    单文件模式：补上同目录的 Depiction 兄弟，再沿父级找 DepictionOperators.ndf ——
    `ZAxisNode` / `YAxisNode` 那批共享算子定义在另一棵树里，不补就漏掉炮塔轴名。
    """
    if os.path.isdir(target):
        hits, allf = [], []
        for root, _, files in os.walk(target):
            for f in files:
                if not f.lower().endswith('.ndf'):
                    continue
                p = os.path.join(root, f)
                allf.append(p)
                fl = f.lower()
                # depiction 系是主战场；GfxDescriptor*（底盘 SousMobileName）与
                # DepictionActions 也在锚点链上，必须一起扫。
                if ('depiction' in fl
                        or 'gfxdescriptor' in fl):
                    hits.append(p)
        return sorted(hits) if hits else sorted(allf)

    files = [target]
    d = os.path.dirname(os.path.abspath(target))
    try:
        for f in sorted(os.listdir(d)):
            if f.lower().endswith('.ndf') and 'depiction' in f.lower():
                p = os.path.join(d, f)
                if p not in files:
                    files.append(p)
    except OSError:
        pass

    cur = d
    for _ in range(6):
        for rel in OPS_RELPATHS:
            p = os.path.join(cur, rel)
            if os.path.exists(p) and p not in files:
                files.append(p)
        nxt = os.path.dirname(cur)
        if nxt == cur:
            break
        cur = nxt
    return files


def main():
    ap = argparse.ArgumentParser(description='从 NDF 描绘链枚举模型锚点名')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--key', help="BlackHoleKey / 单位键，如 SE_SuperDestroyer_US")
    g.add_argument('--object', help='对象名，如 DepictionOperator_HelicopterLanding')
    ap.add_argument('target', help='NDF 文件或目录')
    ap.add_argument('--out', help='把名字写成一行一个，供 fbx_anchors.py --need-file 使用')
    ap.add_argument('--verbose', action='store_true')
    a = ap.parse_args()

    needle = a.object if a.object else a.key
    files = resolve_files(a.target)
    if not files:
        print('[FAIL] 没找到 NDF 文件：%s' % a.target)
        return 2

    texts = []          # 全部候选文件都要留着手，引用解析可能跨文件
    found_in = []
    for fp in files:
        try:
            with open(fp, 'r', encoding='utf-8', errors='replace') as f:
                raw = f.read()
        except OSError as e:
            print('[跳过] %s：%s' % (fp, e))
            continue
        texts.append((fp, strip_comments(raw)))
        if needle in raw:
            found_in.append(fp)

    if not found_in:
        print('[FAIL] 在 %d 个文件里没找到 %r' % (len(files), needle))
        print('       提示：--key 用 BlackHoleKey 的值，--object 用对象名')
        return 1

    hit = None
    for fp in found_in:
        text = dict(texts)[fp]
        if a.object:
            block, _f = find_def(texts, a.object)
        else:
            # ⚠ 必须优先锚定 `BlackHoleKey = 'KEY'` 那一行。
            # 直接拿裸 key 去 find，第一次命中的往往是 `DepictionOperator_<KEY>_Weapon1`
            # 这种**算子定义行**，于是只切出该算子一个块 —— 实测锚点从 20 个掉到 1 个。
            m = re.search(r"BlackHoleKey\s*=\s*'%s'" % re.escape(needle), text)
            block, _h = find_block(text, m.group(0) if m else needle)
        if not block:
            continue
        names, blocks = collect(texts, block, a.verbose)
        if names:
            hit = (fp, names, blocks)
            break

    if not hit:
        print('[FAIL] 定位到 %r 但切不出描绘块（括号或注释结构异常）' % needle)
        return 1

    fp, names, blocks = hit
    print('来源：%s' % fp)
    print('扫过 %d 个关联块（算子 / 子描绘 / 备选外观）' % len(blocks))
    print('\n模型必须存在的节点名（%d 个）：' % len(names))
    for n in sorted(names, key=str.lower):
        field, label = names[n]
        if a.verbose:
            print('  %-26s  %-28s  %s' % (n, field, label))
        else:
            print('  %-26s  %s' % (n, field))

    if a.out:
        with open(a.out, 'w', encoding='utf-8') as f:
            f.write('# 由 depiction_anchors.py 生成，来源 %s\n' % os.path.basename(fp))
            for n in sorted(names, key=str.lower):
                f.write(n + '\n')
        print('\n已写出 %s' % a.out)

    print('\n下一步：python fbx_anchors.py check <model.fbx> --need-file %s'
          % (a.out or '<本清单>'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
