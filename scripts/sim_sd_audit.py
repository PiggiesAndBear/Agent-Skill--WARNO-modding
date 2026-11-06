# -*- coding: utf-8 -*-
"""sim_sd_audit.py — 齐射数 SimultaneousShotsCount 与 WeaponShootData 三处联动审计（只读）。

检查项
  1. 弹药 SimultaneousShotsCount 取值分布（含缺省 = 1）
  2. 每个 TMountedWeaponDescriptor：SD 名数量 == 弹药 Sim？
  3. SD 名尾号 == HandheldEquipmentKey 的 WeaponAlternative 序号？
  4. SD 名的 i 是否严格 0..N-1 升序？
  5. depiction 算子侧 WeaponShootDataPropertyName 的名单长度分布（仅提示，非硬约束）

退出码：0 全部通过 / 1 发现不一致 / 2 输入错误

用法
  python sim_sd_audit.py                     # 默认从当前目录找 GameData/Generated/Gameplay/Gfx
  python sim_sd_audit.py --gfx <dir>         # 指定 Gfx 目录
  python sim_sd_audit.py --unit SE_SuperDestroyer_US   # 只看某个单位（按单位名子串过滤）
  python sim_sd_audit.py --verbose           # 打印全部命中，不只异常
"""
import argparse
import glob
import os
import re
import sys
from collections import Counter, defaultdict


# ---------------- 基础解析 ----------------

def read_text(path):
    """按字节读、统一 \\r\\n → \\n。Ammunition 类是 CRLF，必须归一化再解析。"""
    with open(path, 'rb') as f:
        return f.read().replace(b'\r\n', b'\n').decode('utf-8', 'replace')


def paren_span(text, start):
    """从 start 之后的第一个 '(' 起，返回配对的 ')' 位置（含）。"""
    j = text.find('(', start)
    if j < 0:
        return -1, -1
    depth = 0
    k = j
    while k < len(text):
        c = text[k]
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return j, k
        k += 1
    return j, len(text) - 1


def type_blocks(text, type_name, export_only=False):
    """列出 type_name 的块。export_only=True 只认 `export X is Type`（管理器级）。"""
    out = []
    if export_only:
        pat = r'^export\s+(\S+)\s+is\s+' + re.escape(type_name) + r'\b'
        for m in re.finditer(pat, text, re.M):
            s, e = paren_span(text, m.end())
            if s >= 0:
                out.append((m.group(1), text[s:e + 1], m.start(), e))
    else:
        # 构造式：Type ( ... )  —— 没有名字，用序号
        for i, m in enumerate(re.finditer(re.escape(type_name) + r'\s*\(', text)):
            s, e = paren_span(text, m.end() - 1)
            if s >= 0:
                out.append(('#%d' % i, text[s:e + 1], m.start(), e))
    return out


def field_int(body, name):
    m = re.search(r'^\s*' + re.escape(name) + r'\s*=\s*(-?\d+)\s*$', body, re.M)
    return int(m.group(1)) if m else None


def str_list(body, name):
    i = body.find(name)
    if i < 0:
        return None
    j = body.find('[', i)
    if j < 0:
        return None
    k = body.find(']', j)
    if k < 0:
        return None
    return re.findall(r'"([^"]+)"', body[j + 1:k])


# ---------------- 数据装载 ----------------

def load_ammo_sim(gfx):
    """弹药名 → Sim（缺省按 1）。两个文件的行尾不同，但 read_text 已归一化。"""
    ammo = {}
    files = [os.path.join(gfx, 'Ammunition.ndf'),
             os.path.join(gfx, 'AmmunitionMissiles.ndf')]
    for p in files:
        if not os.path.exists(p):
            continue
        tx = read_text(p)
        for m in re.finditer(r'^(?:export\s+)?(\S+)\s+is\s+TAmmunitionDescriptor', tx, re.M):
            s, e = paren_span(tx, m.end())
            if s < 0:
                continue
            body = tx[s:e + 1]
            sim = field_int(body, 'SimultaneousShotsCount')
            ammo[m.group(1)] = 1 if sim is None else sim
    return ammo


def load_mounted_slots(gfx):
    """返回每个 TMountedWeaponDescriptor 的 (武器管理器名, 弹药名, AmmoBoxIndex, 武器号, SD名单)。"""
    p = os.path.join(gfx, 'WeaponDescriptor.ndf')
    if not os.path.exists(p):
        raise SystemExit('找不到 %s' % p)
    tx = read_text(p)

    # 武器管理器边界
    heads = [(m.start(), m.group(1)) for m in
             re.finditer(r'^export\s+(\S+)\s+is\s+TWeaponManagerModuleDescriptor', tx, re.M)]
    rows = []
    for idx, (start, name) in enumerate(heads):
        end = heads[idx + 1][0] if idx + 1 < len(heads) else len(tx)
        wd = tx[start:end]
        for _unused, mb, _s, _e in type_blocks(wd, 'TMountedWeaponDescriptor'):
            am = re.search(r'Ammunition\s*=\s*\$?/?GFX/Weapon/(\w+)', mb)
            key = re.search(r'HandheldEquipmentKey\s*=\s*"WeaponAlternative_(\d+)"', mb)
            rows.append(dict(
                wd=name,
                ammo=am.group(1) if am else None,
                box=field_int(mb, 'AmmoBoxIndex'),
                weapon_no=int(key.group(1)) if key else None,
                sd=str_list(mb, 'WeaponShootDataPropertyName') or [],
            ))
    return rows


def load_depiction_names(gfx):
    """depiction 侧所有 WeaponShootDataPropertyName 名单（仅用于分布提示）。"""
    pats = [os.path.join(gfx, 'Depictions', '*.ndf'),
            os.path.join(gfx, '..', 'Gfx', 'DepictionResources', '*.ndf')]
    files = []
    for p in pats:
        files.extend(sorted(glob.glob(p)))
    out = []
    for f in files:
        tx = read_text(f)
        for m in re.finditer(r'WeaponShootDataPropertyName\s*=\s*\n?\s*\[', tx):
            k = tx.find(']', m.end())
            if k < 0:
                continue
            # 注意：depiction 侧用单引号 ['WeaponShootData_0_1']，武器槽侧用双引号
            names = re.findall(r'[\'"](WeaponShootData_\d+_\d+)[\'"]', tx[m.end():k])
            out.append((os.path.basename(f), names))
    return out


# ---------------- 主流程 ----------------

def main():
    ap = argparse.ArgumentParser(description='齐射数 Sim 与 WeaponShootData 三处联动审计（只读）')
    ap.add_argument('--gfx', default=os.path.join('GameData', 'Generated', 'Gameplay', 'Gfx'),
                    help='Gfx 目录（默认 GameData/Generated/Gameplay/Gfx）')
    ap.add_argument('--unit', default=None, help='只统计武器管理器名含该子串的条目')
    ap.add_argument('--verbose', action='store_true', help='打印全部命中明细')
    args = ap.parse_args()

    if not os.path.isdir(args.gfx):
        print('[ERR] 不是目录：%s' % args.gfx)
        return 2

    ammo = load_ammo_sim(args.gfx)
    rows = load_mounted_slots(args.gfx)
    if args.unit:
        rows = [r for r in rows if args.unit.lower() in r['wd'].lower()]

    print('=' * 66)
    print('弹药对象 %d 个，挂载槽 %d 个' % (len(ammo), len(rows)))
    print('=' * 66)

    print('\n[1] 弹药 SimultaneousShotsCount 分布（缺省记为 1）')
    ac = Counter(ammo.values())
    for k in sorted(ac):
        print('    Sim=%-3d  %4d 个弹药对象' % (k, ac[k]))
    mx = max(ac) if ac else 0
    if mx > 6:
        print('    ⚠ 存在 > 6 的 Sim —— 全库实测上限为 6，超出会实例化期 CTD')

    print('\n[2] 弹药 Sim × 武器槽 SD 名数量')
    cross = Counter()
    offenders = []
    for r in rows:
        sim = ammo.get(r['ammo'])
        n = len(r['sd'])
        cross[(sim, n)] += 1
        if sim is not None and sim != n:
            offenders.append((r, sim, n))
    sims = sorted({k[0] for k in cross if k[0] is not None})
    nmax = max((k[1] for k in cross), default=0)
    print('    ' + 'Sim\\名数'.ljust(9) + ' '.join('%-5d' % n for n in range(nmax + 1)))
    for s in sims:
        cells = ' '.join('%-5s' % (cross.get((s, n)) or '') for n in range(nmax + 1))
        print('    %-9s%s' % (s, cells))

    print('\n[3] SD 名尾号 vs 武器号（HandheldEquipmentKey = WeaponAlternative_N）')
    tail_bad = []
    for r in rows:
        for x in r['sd']:
            tail = int(x.split('_')[2])
            if r['weapon_no'] is not None and tail != r['weapon_no']:
                tail_bad.append((r['wd'], tail, r['weapon_no'], r['sd']))
    print('    尾号 ≠ 武器号：%d 例' % len(tail_bad))
    for t in tail_bad[:10]:
        print('      %-44s 尾号=%s 武器号=%s %s' % (t[0][:42], t[1], t[2], t[3]))

    print('\n[4] SD 名 i 是否严格 0..N-1 升序')
    seq_bad = [r for r in rows
               if [int(x.split('_')[1]) for x in r['sd']] != list(range(len(r['sd'])))]
    print('    不连续/不升序：%d 例' % len(seq_bad))
    for r in seq_bad[:10]:
        print('      %-44s %s' % (r['wd'][:42], r['sd']))

    print('\n[5] depiction 侧 SD 名单长度分布（参考项：只登记需要显示开火特效的武器，总数少于武器槽）')
    dep = load_depiction_names(args.gfx)
    if dep:
        dc = Counter(len(n) for _f, n in dep)
        print('    ' + '  '.join('%d 名:%d' % (k, v) for k, v in sorted(dc.items())))
        print('    总登记位置 %d 处' % len(dep))
    else:
        print('    （未找到 depiction 目录）')

    print('\n' + '=' * 66)
    if offenders:
        print('✗ Sim ≠ SD 名数：%d 例' % len(offenders))
        for r, sim, n in offenders:
            print('    %-44s ammo=%-34s Sim=%d 名数=%d %s'
                  % (r['wd'][:42], (r['ammo'] or '?')[:32], sim, n, r['sd']))
        print('\n  名数 < Sim → 引擎按发序号 i 直接索引，越界读到相邻槽 → 串位（别的炮塔跟着亮）')
        print('  名数 > Sim → 不报错，但对不上账（多出的名字永远等不到事件）')
        print('  修法：把该槽 WeaponShootDataPropertyName 补齐/裁到恰好 Sim 个，尾号不动')
        rc = 1
    else:
        print('✓ 全部挂载槽 SD 名数 == 弹药 Sim')
        rc = 0

    if tail_bad or seq_bad:
        print('✗ 命名规范另有 %d 处异常（尾号）/%d 处（i 序列）' % (len(tail_bad), len(seq_bad)))
        rc = 1

    if args.verbose:
        print('\n=== 明细（槽 / Sim / 名数 / 名单）===')
        for r in rows:
            sim = ammo.get(r['ammo'])
            print('  %-46s box=%-3s 武器号=%-3s Sim=%-3s 名数=%-2d %s'
                  % (r['wd'][:44], r['box'], r['weapon_no'], sim, len(r['sd']), r['sd']))

    return rc


if __name__ == '__main__':
    sys.exit(main())
