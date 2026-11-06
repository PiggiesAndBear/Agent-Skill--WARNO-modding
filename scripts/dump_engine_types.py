#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dump_engine_types.py —— 查「引擎支持什么」与「原版用到了什么」的三方对比。

为什么要有这个脚本：NDF 只反映原版*用到了*的类型；引擎*支持*的全部类型只存在于
WARNO.exe 的 RTTI 字符串表里。不查这一层，必然把「原版没用过」误判成「不可能」。

    python dump_engine_types.py [WARNO.exe] [GameData目录] [--family PREFIX ...]
                               [--all] [--out types.json] [--gd <other GameData> ...]

不给路径时按常见 Steam 安装位置自动探测（`*/steamapps/common/WARNO/WARNO.exe`）。

输出三档：
    exe 有 + NDF 在用     -> 抄现成实例改参数
    exe 有 + NDF 零引用   -> 引擎支持、官方未启用，属「未验证区」
    exe 没有              -> 引擎不认，换层实现

用法示例：
    python dump_engine_types.py
    python dump_engine_types.py --family TUnitEffect --family TCondition
    python dump_engine_types.py --all > types.txt
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

# 关注的类型族：前缀 -> 说明。--family 可加自定义前缀。
FAMILIES = [
    ("TCondition", "状态检定类型（引擎注册，不可增）"),
    ("TCapacite", "技能描述符"),
    ("TEffectsPack", "效果包容器"),
    ("TUnitEffect", "效果原语（主流前缀）"),
    ("TGD", "剧本脚本描述符（NDF 里 0 引用）"),
    ("TGameDesignAddOn", "地图场景扩展点"),
    ("TDeck", "牌组系描述符"),
    ("TVisibility", "隐蔽 / 探测"),
    ("TDamage", "伤害 / 命中"),
    ("TTransport", "运输"),
    ("TMovement", "运动模块"),
]

# 名字不遵守 TUnitEffect 前缀、但同样是效果原语的类型（只按前缀搜必漏）
ODD_EFFECT_RE = re.compile(r"^T[A-Za-z0-9_]*(?:Kill|Deroute|Inflict|Evac)[A-Za-z0-9_]*Descriptor$")
DESCRIPTOR_RE = re.compile(r"^T[A-Za-z0-9_]*Descriptor$")
TYPE_RE = re.compile(r"^T[A-Za-z0-9_]{4,}$")
NDF_TOKEN_RE = re.compile(r"\b[A-Z][A-Za-z0-9_]{3,}\b")


def find_exe() -> str | None:
    pats = [
        r"D:/Steam/steamapps/common/WARNO/WARNO.exe",
        r"C:/Steam/steamapps/common/WARNO/WARNO.exe",
        r"D:/SteamLibrary/steamapps/common/WARNO/WARNO.exe",
        r"C:/Program Files (x86)/Steam/steamapps/common/WARNO/WARNO.exe",
    ]
    for p in pats:
        if os.path.isfile(p):
            return p
    for drive in "CDEFGH":
        for hit in glob.glob(f"{drive}:/**/steamapps/common/WARNO/WARNO.exe", recursive=False):
            return hit
    return None


def exe_type_names(exe: str) -> set[str]:
    """抽取 exe 里的类型名。RTTI 名以明文 ASCII 存在，无需解包。"""
    data = open(exe, "rb").read()
    names = set()
    for raw in re.findall(rb"[\x20-\x7e]{4,160}", data):
        s = raw.decode("ascii")
        if TYPE_RE.match(s):
            names.add(s)
    return names


def ndf_usage(gamedata: str) -> tuple[Counter, int]:
    """单遍扫描全部 .ndf，统计每个大写开头的标识符出现次数。

    用「一个词表正则 + Counter」而不是「每个候选名 str.count()」——
    后者是 O(候选数 × 文件数)，几千个候选项时会从秒级掉到分钟级。
    """
    counter: Counter[str] = Counter()
    files = 0
    for root, _dirs, names in os.walk(gamedata):
        for n in names:
            if not n.lower().endswith(".ndf"):
                continue
            files += 1
            path = os.path.join(root, n)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    counter.update(NDF_TOKEN_RE.findall(f.read()))
            except OSError:
                continue
    return counter, files


def families_with(prefixes: list[str]) -> list[tuple[str, str]]:
    """把 --family 给的裸前缀配上说明；FAMILIES 里有的沿用原说明。"""
    known = dict(FAMILIES)
    return [(p, known.get(p, p)) for p in prefixes]


def classify(name: str, families: list[tuple[str, str]]) -> str:
    for prefix, label in families:
        if name.startswith(prefix):
            return label
    if ODD_EFFECT_RE.match(name):
        return "效果原语（异类前缀）"
    return "其它"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("exe", nargs="?", help="路径 WARNO.exe")
    ap.add_argument("gamedata", nargs="?", help="要对照的 GameData 目录")
    ap.add_argument("--family", action="append", default=[], help="只看这些前缀（可重复）")
    ap.add_argument("--all", action="store_true", help="输出全部 T*Descriptor，不只关注族")
    ap.add_argument("--out", default="", help="把完整结果写成 JSON")
    ap.add_argument("--quiet", action="store_true", help="只输出汇总，不打印明细表")
    args = ap.parse_args()

    exe = args.exe or find_exe()
    if not exe or not os.path.isfile(exe):
        print("找不到 WARNO.exe，请把路径作为第一个参数传进来。", file=sys.stderr)
        return 2

    gamedata = args.gamedata
    if gamedata and not os.path.isdir(gamedata):
        print(f"GameData 目录不存在：{gamedata}", file=sys.stderr)
        return 2

    print(f"[1/3] 抽 exe 类型名：{exe}")
    types = exe_type_names(exe)
    descriptors = sorted(t for t in types if DESCRIPTOR_RE.match(t))
    odd = sorted(t for t in descriptors if ODD_EFFECT_RE.match(t))
    print(f"      T* 类型 {len(types)} 个，其中 *Descriptor {len(descriptors)} 个"
          f"（名字不遵守 TUnitEffect 前缀的效果原语另 {len(odd)} 个）")

    usage: Counter = Counter()
    files = 0
    if gamedata:
        print(f"[2/3] 扫 NDF 用量：{gamedata}")
        usage, files = ndf_usage(gamedata)
        print(f"      扫描 {files} 个 .ndf，命中不同标识符 {len(usage)} 个")
    else:
        print("[2/3] 未给 GameData，跳过用量对照（只列引擎类型）")

    if args.family:
        prefixes = args.family
        candidates = sorted(t for t in types if any(t.startswith(p) for p in prefixes))
    elif args.all:
        prefixes = [p for p, _ in FAMILIES]
        candidates = descriptors
    else:
        prefixes = [p for p, _ in FAMILIES]
        candidates = sorted(t for t in types
                            if any(t.startswith(p) for p in prefixes) or ODD_EFFECT_RE.match(t))

    labeled = families_with(prefixes)
    rows = [{
        "name": n,
        "family": classify(n, labeled),
        "in_exe": True,
        "ndf_refs": usage.get(n, 0) if gamedata else None,
        "used": (usage.get(n, 0) > 0) if gamedata else None,
    } for n in candidates]

    print("[3/3] 结果")
    if gamedata:
        used = [r for r in rows if r["used"]]
        unused = [r for r in rows if not r["used"]]
        print(f"      在用 {len(used)} / 零引用 {len(unused)} / 合计 {len(rows)}")
        if unused and not args.quiet:
            print("\n  ★ 零引用（引擎支持、官方未启用 —— 可试，属未验证区）")
            for r in unused:
                print(f"    {r['name']:<52} {r['family']}")

    if not args.quiet:
        by_family: dict[str, list] = defaultdict(list)
        for r in rows:
            by_family[r["family"]].append(r)
        for fam, items in sorted(by_family.items()):
            print(f"\n== {fam}（{len(items)}）")
            for r in sorted(items, key=lambda x: (-(x["ndf_refs"] or 0), x["name"])):
                refs = "—" if r["ndf_refs"] is None else r["ndf_refs"]
                print(f"  {r['name']:<52} refs={refs}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
        print(f"\nJSON 已写入 {args.out}")

    print("\n提醒：exe 有 + NDF 零引用 ≠ 一定可用（可能缺配套字段）；"
          "\n      exe 没有 = 一定不可用。反向同理：原版 0 先例 ≠ 引擎不支持。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
