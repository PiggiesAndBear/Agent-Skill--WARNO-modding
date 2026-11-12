#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""depiction_anchors_all.py — 从「单位描绘入口」出发，跨文件递归穷举 FBX 必须存在的节点名。

为什么需要它（本轮踩的坑）：
    skill 自带的 depiction_anchors.py 只扫**一个文件**。PT76B_SOV 的描绘块里
    `+ DepictionAction_FX_Amphibious_NoPropulsion` 指向的是 DepictionActions.ndf，
    工具看不到，于是只报 7 个名字 —— 漏掉 `fx_eau`，进游戏直接
    `Missing anchor bone 'fx_eau'` Fatal error。编译期完全静默。

本脚本做三件 depiction_anchors.py 不做的事：
    1. 建立**跨文件**符号表（mod GameData + 原版 GameData 兜底），按名字解析引用；
    2. BFS 递归（Operators / Actions / Alternatives / SubDepiction / $路径）；
    3. 直接把结果和 FBX 里的空物体名做差集，报「缺谁、谁引用的」。

用法：
    python depiction_anchors_all.py --key <BlackHoleKey> [--fbx model.fbx]
        [--mod <mod根>] [--base <原版GameData父目录>] [--out need.txt] [--all]
    # 比较不区分大小写（AssetCooker 统一小写）；真正的坑是「只差大小写的两个节点撞名」
退出码：0 无缺失 / 1 有缺失 / 2 参数或解析问题
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

MOD = pathlib.Path(r"D:/Steam/steamapps/common/WARNO/Mods/ShowCase-FPV Strike")
BASE = pathlib.Path(r"C:/Users/123/WorkBuddy/2026-10-28-00-09-58/warno_base")

# 只认「引擎按名字找节点」的字段。SousMobileName 必须排在 SousMobile 前面。
FIELD_RE = re.compile(
    r"""(?P<field>
            Anchors? | \w*Node | \w*BoneName | SousMobileName | SousMobile
        )
        \s*=\s*
        (?:\[[^\]]*\]|"[^"]*"|'[^']*')""",
    re.X,
)
QUOTED_RE = re.compile(r"'([^']+)'|\"([^\"]+)\"")

# 描绘链上的下游引用
REF_RE = re.compile(
    r"(?:Op_\w+|DepictionOperator_\w+|DepictionAction_\w+|AllWeaponAlternatives_\w+"
    r"|Alternatives_\w+|SubDepiction\w*|GfxDescriptorChassis_\w+)")
REF_PATH_RE = re.compile(r"[$~][\w/$]*?/(\w+)")

# 顶层定义头：`NAME is ...` / `export NAME is ...` / `unnamed TYPE(...)`
HEAD_RE = re.compile(
    r"(?m)^[ \t]*(?:export[ \t]+|private[ \t]+|public[ \t]+)?"
    r"(?:(?P<name>[A-Za-z_]\w*)[ \t]+is[ \t]+|unnamed[ \t]+(?P<utype>[A-Za-z_]\w*))")


def strip_comments(text: str) -> str:
    """把 // 行注释换成空格，保持偏移。字符串里的 // 不动。"""
    out = list(text)
    n, i, quote = len(text), 0, ""
    while i < n:
        c = text[i]
        if c == "\n":
            quote = ""
        elif quote:
            if c == quote:
                quote = ""
        elif c in ("'", '"'):
            quote = c
        elif c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " "
            i = j
            continue
        i += 1
    return "".join(out)


def build_symbols(roots):
    """name -> [(file, text)]。同名多文件时 mod 优先（roots 顺序即优先级）。"""
    sym: dict[str, list[tuple[pathlib.Path, str]]] = {}
    unnamed = 0
    for root in roots:
        if not root.exists():
            continue
        for p in sorted(root.rglob("*.ndf")):
            try:
                raw = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            t = strip_comments(raw)
            heads = list(HEAD_RE.finditer(t))
            for idx, m in enumerate(heads):
                name = m.group("name")
                if not name:
                    unnamed += 1
                    name = f"<unnamed#{unnamed}>"
                end = heads[idx + 1].start() if idx + 1 < len(heads) else len(t)
                sym.setdefault(name, []).append((p, t[m.start():end]))
    return sym


def block_of(sym, name):
    for f, txt in sym.get(name, []):
        return f, txt
    return None, None


def anchors_in(txt: str) -> list[str]:
    got = []
    for m in FIELD_RE.finditer(txt):
        for a, b in QUOTED_RE.findall(m.group(0)):
            nm = a or b
            if nm and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", nm):
                got.append(nm)
    return got


def refs_in(txt: str) -> list[str]:
    out = list(REF_RE.findall(txt))
    out += REF_PATH_RE.findall(txt)
    return out


def find_entry(sym, key):
    """找所有 `BlackHoleKey = '<key>'` 的块。

    一个单位通常有 3 个注册点（Tactic / Ghost / Showroom），各自 Operators 不同，
    必须**取并集**：只取第一个命中的会落在 DepictionGhosts 上（它没有 Operators），
    枚举结果直接变 0 个名字 —— 本轮踩过这个坑。
    """
    pat = re.compile(r"BlackHoleKey\s*=\s*['\"]%s['\"]" % re.escape(key))
    hits = []
    for name, lst in sym.items():
        for f, txt in lst:
            if pat.search(txt):
                hits.append((name, f, txt))
    return hits


def bfs(sym, entries):
    """entries: [(块名, 文件, 文本)]。返回 (need, unresolved)。"""
    need: dict[str, list[tuple[int, str]]] = {}
    unresolved: list[str] = []
    visited: set[str] = set()
    seen_txt: set[str] = set()
    queue = []
    for nm, f, txt in entries:
        if txt in seen_txt:
            continue
        seen_txt.add(txt)
        queue.append((txt, f"{f.name}:{nm}", 0))
    while queue:
        txt, src, depth = queue.pop(0)
        for nm in anchors_in(txt):
            need.setdefault(nm, []).append((depth, src))
        for ref in refs_in(txt):
            if ref in visited:
                continue
            visited.add(ref)
            f, sub = block_of(sym, ref)
            if sub is None:
                unresolved.append(f"{ref} (from {src})")
                continue
            if sub in seen_txt:
                continue
            seen_txt.add(sub)
            queue.append((sub, ref, depth + 1))
    return need, unresolved


def fbx_models(path: pathlib.Path) -> list[tuple[str, str]]:
    """[(节点名, 类别)]，类别来自 FBX Model 的第三个属性（Mesh / Null / Root …）。"""
    sys.path.insert(0, str(pathlib.Path(r"C:/Users/123/.workbuddy/skills/warno-modding/scripts")))
    import fbx_anchors as FA  # noqa: E402

    _ver, nodes = FA.parse(str(path))
    models, conns = {}, []
    FA.collect(nodes, models, conns)
    return [(nm, cls) for nm, cls in models.values() if nm]


def fbx_all_names(path: pathlib.Path) -> list[str]:
    """所有节点名（保留重复、保留大小写）—— 用来查「大小写撞名」。"""
    return [nm for nm, _cls in fbx_models(path)]


def fbx_nulls(path: pathlib.Path) -> set[str]:
    """借用 skill 的 fbx_anchors.py 解析器，取出所有节点名（大小写敏感原样返回）。"""
    return set(fbx_all_names(path))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True, help="BlackHoleKey，如 PT76B_SOV / OBJECT_685")
    ap.add_argument("--mod", default=str(MOD), help="mod 根目录（含 GameData）")
    ap.add_argument("--base", default=str(BASE), help="原版 GameData 的父目录（兜底解析）")
    ap.add_argument("--fbx", default="", help="可选：与 FBX 内节点名做差集")
    ap.add_argument("--out", default="", help="把缺的名字写成 need-file 供 fbx_anchors 用")
    ap.add_argument("--all", action="store_true", help="打印全部名字（默认只打印与 FBX 差集）")
    a = ap.parse_args()

    sym = build_symbols([pathlib.Path(a.mod) / "GameData",
                         pathlib.Path(a.base) / "GameData"])
    entries = find_entry(sym, a.key)
    if not entries:
        print(f"[FAIL] 找不到 BlackHoleKey='{a.key}' 的描绘块", file=sys.stderr)
        return 2
    print(f"入口 {len(entries)} 个：")
    for nm, f, _t in entries:
        print(f"  - {f.name}:{nm}")

    need, unresolved = bfs(sym, entries)
    print(f"符号表 {len(sym)} 个块；引用解析失败 {len(unresolved)} 个；锚点需求 {len(need)} 个")

    if a.fbx:
        # 比较必须**不区分大小写**：AssetCooker 会把节点名统一小写后再进 mesh.neu3，
        # 而 NDF 里写的是小写（`GameplayBBoxBoneName = "chassis"`、`SousMobileName = 'chassis'`）。
        # 若按大小写严格比，主网格 `Chassis` 会被误报成「缺 chassis」。
        # 真正的坑不是大小写本身，而是**两个只差大小写的节点撞名**——那条由下面的重名判据负责。
        have = fbx_nulls(pathlib.Path(a.fbx))
        have_low = {n.lower() for n in have}
        miss = sorted(n for n in need if n.lower() not in have_low)
        print(f"FBX 空物体 {len(have)} 个；缺失 {len(miss)} 个")
        for n in miss:
            srcs = ", ".join(sorted({s for _, s in need[n]}))
            print(f"  [MISS] {n:<26} ← {srcs}")
        if a.all:
            extra = sorted(n for n in have if n.lower() not in {m.lower() for m in need})
            print(f"  (多余，无害) {len(extra)} 个：{', '.join(extra)}")
        if a.out and miss:
            pathlib.Path(a.out).write_text("\n".join(miss) + "\n", encoding="utf-8")
            print(f"  已写 {a.out}")
        return 1 if miss else 0

    for n in sorted(need):
        srcs = ", ".join(sorted({s for _, s in need[n]}))
        print(f"  {n:<26} ← {srcs}")
    if a.out:
        pathlib.Path(a.out).write_text("\n".join(sorted(need)) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
