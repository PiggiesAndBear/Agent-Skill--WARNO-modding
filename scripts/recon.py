#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Eugen NDF Mod 数据勘查脚本
用法:
  python recon.py                          # 用默认路径
  python recon.py "D:\\path\\to\\Mods"      # 指定 Mods 根目录
  python recon.py "D:\\path\\to\\Mods" MyMod   # 指定 Mods 根 + 目标 mod 名

注意: 不要用 `python -c` 内联执行本逻辑 —— 本机 bash 会吞反斜杠。
始终把脚本落盘再执行。
"""

import os
import re
import sys
import collections

DEFAULT_ROOT = r"D:\Steam\steamapps\common\WARNO\Mods"
DEFAULT_MOD = "MyMod"

MODE_ROOT = DIRS = None
MOD = None


def banner(t):
    print()
    print("#" * 78)
    print("# " + t)
    print("#" * 78)


def walk_ndf(root, skip_fx=True):
    """产出 (绝对路径, 相对 root 的路径, 字节数)。默认跳过巨大的 Fx 目录。"""
    for dp, dn, fn in os.walk(root):
        if skip_fx and (os.sep + "Fx" + os.sep) in dp + os.sep:
            continue
        for f in fn:
            if f.lower().endswith(".ndf"):
                fp = os.path.join(dp, f)
                try:
                    yield fp, os.path.relpath(fp, root), os.path.getsize(fp)
                except OSError:
                    continue


def read(p, limit=None):
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        return f.read(limit) if limit else f.read()


def section_overview():
    banner("1. 目录全景（文件数 / 扩展名直方图）")
    for e in sorted(os.listdir(MODE_ROOT)):
        fp = os.path.join(MODE_ROOT, e)
        if not os.path.isdir(fp):
            print("FILE  %-40s %10d" % (e, os.path.getsize(fp)))
            continue
        n = 0
        ext = collections.Counter()
        for dp, dn, fn in os.walk(fp):
            for f in fn:
                n += 1
                ext[os.path.splitext(f)[1].lower()] += 1
        top = " ".join("%s=%d" % (k or "(none)", v) for k, v in ext.most_common(6))
        print("DIR   %-40s files=%-6d %s" % (e + "/", n, top))


def section_keyword(keywords):
    banner("2. 文件名关键词命中: " + ", ".join(keywords))
    pat = re.compile("|".join(keywords), re.I)
    hits = [(s, r) for _, r, s in walk_ndf(MOD) if pat.search(os.path.basename(r))]
    hits.sort(reverse=True)
    print("命中 %d 个\n" % len(hits))
    for s, r in hits[:70]:
        print("%10d  %s" % (s, r))


def section_bigfiles(n=40):
    banner("3. 最大的 %d 个 .ndf（数据主体都在这里）" % n)
    hits = sorted(((s, r) for _, r, s in walk_ndf(MOD, skip_fx=False)), reverse=True)
    for s, r in hits[:n]:
        print("%10d  %s" % (s, r))


def section_generators():
    banner("4. 生成器标记汇总（文件 ← 由哪个 FileWriter 生成）")
    pat = re.compile(r"g[ée]n[ée]r[ée]\s+par\s+(\w+)", re.I)
    rows = []
    gen = os.path.join(MOD, "GameData", "Generated")
    if not os.path.isdir(gen):
        print("(无 GameData/Generated 目录)")
        return
    for dp, dn, fn in os.walk(gen):
        for f in fn:
            if not f.lower().endswith(".ndf"):
                continue
            fp = os.path.join(dp, f)
            try:
                first = read(fp, 300).splitlines()
            except OSError:
                continue
            m = pat.search(first[0]) if first else None
            if m:
                rows.append((m.group(1), os.path.relpath(fp, MOD)))
    for w, r in sorted(rows):
        print("%-50s <- %s" % (os.path.basename(r), w))
    print("\n共 %d 个生成文件" % len(rows))


OBJECT_RE = re.compile(r"^(?:export\s+)?(\S+)\s+is\s+(\S+)", re.M)
FIELD_RE_4 = re.compile(r"^\s{4}(\w+)\s*=", re.M)
FIELD_RE_ANY = re.compile(r"^\s+(\w+)\s*=", re.M)


def section_objects(rel_paths):
    banner("5. 目标文件的对象与字段统计")
    for rel in rel_paths:
        fp = os.path.join(MOD, rel)
        if not os.path.exists(fp):
            print("### MISSING " + rel)
            continue
        t = read(fp)
        objs = OBJECT_RE.findall(t)
        print("-" * 74)
        print("### %s   (%d bytes)" % (rel, len(t)))
        print("    顶层对象数: %d" % len(objs))
        if objs:
            print("    类型分布: %s" % collections.Counter(x for _, x in objs).most_common())
            print("    前 6 个: %s" % [n for n, _ in objs[:6]])
        f4 = collections.Counter(FIELD_RE_4.findall(t))
        if f4:
            print("    第 4 层字段 TOP25:")
            for k, v in f4.most_common(25):
                print("        %-42s %d" % (k, v))
        fa = collections.Counter(FIELD_RE_ANY.findall(t))
        print("    全部字段名 TOP30:")
        for k, v in fa.most_common(30):
            print("        %-42s %d" % (k, v))


def section_sample(rel, needle, n=2600):
    banner("6. 完整对象样本: %s @ %s" % (rel, needle))
    fp = os.path.join(MOD, rel)
    if not os.path.exists(fp):
        print("(missing)")
        return
    t = read(fp)
    i = t.find(needle)
    if i < 0:
        print("(未找到 " + needle + ")")
        return
    print(t[i:i + n])


def section_enums(rel, fields):
    banner("7. 枚举取值分布")
    fp = os.path.join(MOD, rel)
    if not os.path.exists(fp):
        print("(missing)")
        return
    t = read(fp)
    for f in fields:
        pat = r"%s\s*=\s*['\"]?([\w/\.\-]+)" % re.escape(f)
        c = collections.Counter(re.findall(pat, t))
        print("%-34s %s" % (f, c.most_common(25)))


def section_config():
    banner("8. Saved Games 侧 Config.ini 与 Gen 产物")
    sg = os.path.join(os.path.expanduser("~"), "Saved Games", "EugenSystems", "WARNO", "mod")
    if not os.path.isdir(sg):
        print("(无 Saved Games mod 目录: %s)" % sg)
        return
    for e in sorted(os.listdir(sg)):
        cfg = os.path.join(sg, e, "Config.ini")
        if os.path.exists(cfg):
            print("--- %s/Config.ini ---" % e)
            print(read(cfg))
    gen = os.path.join(MOD, "Gen")
    if os.path.isdir(gen):
        bins = [f for _, _, fn in os.walk(gen) for f in fn if f.endswith(".ndfbin")]
        print("Gen/ 下 .ndfbin: %s" % bins)
        print("判定: 只有 Mesh_All.ndfbin + <ModName>.ndfbin  => 该 mod 没有任何实际修改")


def main(argv):
    global MODE_ROOT, MOD
    MODE_ROOT = argv[1] if len(argv) > 1 else DEFAULT_ROOT
    mod_name = argv[2] if len(argv) > 2 else DEFAULT_MOD
    MOD = os.path.join(MODE_ROOT, mod_name)

    print("Mods 根目录: %s" % MODE_ROOT)
    print("目标 mod   : %s  (存在: %s)" % (MOD, os.path.isdir(MOD)))
    if not os.path.isdir(MOD):
        print("路径不存在，请检查。")
        return 1

    section_overview()
    section_keyword(["unit", "division", "deck", "battlegroup", "pack", "operation", "strateg"])
    section_bigfiles()
    section_generators()
    section_objects([
        r"GameData\Generated\Gameplay\Gfx\UniteDescriptor.ndf",
        r"GameData\Generated\Gameplay\Decks\Divisions.ndf",
        r"GameData\Generated\Gameplay\Decks\DivisionRules.ndf",
        r"GameData\Generated\Gameplay\Decks\DivisionCostMatrix.ndf",
        r"GameData\Generated\Gameplay\Decks\Decks.ndf",
        r"GameData\Generated\Gameplay\Decks\StrategicDecks.ndf",
        r"GameData\Generated\Gameplay\Decks\DeckPacks.ndf",
        r"GameData\Generated\Gameplay\Decks\DeckSerializer.ndf",
    ])
    section_enums(r"GameData\Generated\Gameplay\Gfx\UniteDescriptor.ndf",
                  ["UnitRole", "FactoryType", "PriceCategory", "Coalition", "MotherCountry"])
    section_enums(r"GameData\Generated\Gameplay\Decks\Divisions.ndf",
                  ["DivisionCoalition", "DivisionName", "TypeToken", "CountryId", "MaxActivationPoints"])
    section_sample(r"GameData\Generated\Gameplay\Decks\DeckTemplates.ndf", "template", 800)
    section_config()
    banner("完成")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
