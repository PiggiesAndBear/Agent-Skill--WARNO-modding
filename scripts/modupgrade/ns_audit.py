#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""命名空间审计：把自己内容里所有 `$/NS/Name` 引用与新基线核对。

背景：新版把一批对象搬了文件，命名空间随之变化
（实测 `CriticalEffectModule_*`：`$/GFX/UnitConstantes/` → `$/GFX/CriticalEffects/`）。
我们 27 个单位是从旧版抄的，引用前缀还是旧的 → 编译期 `object not found`。

做法：
  ① 从改动包收集我们写进去的所有 `$/a/b/Name` 引用；
  ② 在新基线里找 `Name` 的声明位置；
  ③ 从新基线里找官方对该 `Name` 的**实际引用前缀**（出现最多的那个）；
  ④ 与我们的前缀比对，输出待改清单。

用法：python ns_audit.py            # 只报告
      python ns_audit.py --fix      # 改改动包 + 改树
"""
import argparse
import collections
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ndflib

MOD = None
BASE = None
MAN = None

RE_REF = re.compile(r"\$/([A-Za-z0-9_]+)/([A-Za-z0-9_]+)/([A-Za-z0-9_]+)")


def baseline():
    z = zipfile.ZipFile(BASE)
    texts = {}
    for n in z.namelist():
        if n.endswith(".ndf"):
            texts[n] = z.read(n).decode("utf-8", "replace")
    return texts


def declared_names(texts):
    """name → 声明所在文件"""
    out = {}
    for f, t in texts.items():
        for m in re.finditer(r"(?m)^(?:export\s+)?([A-Za-z_]\w*)\s+is\b", t):
            out.setdefault(m.group(1), f)
    return out


def canonical_prefix(texts, name):
    """官方引用该名字时用的 `$/a/b/` 前缀（取众数）"""
    c = collections.Counter()
    pat = re.compile(r"\$/([A-Za-z0-9_]+)/([A-Za-z0-9_]+)/" + re.escape(name) + r"\b")
    for t in texts.values():
        for m in pat.finditer(t):
            c["$/ %s/%s/" % (m.group(1), m.group(2))] += 1
    if not c:
        return None
    return c.most_common(1)[0][0].replace("$/ ", "$/")


def our_refs(m):
    refs = collections.Counter()
    for e in m["files"]:
        for a in e.get("add_units", []):
            for L in a["lines"]:
                for m2 in RE_REF.finditer(L):
                    refs["$/ %s/%s/%s" % m2.groups()] += 1
        for p in e.get("patch_units", []):
            for op in p["ops"]:
                for L in op["new"]:
                    for m2 in RE_REF.finditer(L):
                        refs["$/ %s/%s/%s" % m2.groups()] += 1
    return collections.Counter({k.replace("$/ ", "$/"): v for k, v in refs.items()})


def main(argv=None):
    ap = argparse.ArgumentParser(description="命名空间审计：核对 $/NS/Name 引用与新基线是否一致")
    ap.add_argument("--mod", required=True, help="当前 Mod 根目录")
    ap.add_argument("--base", required=True, help="新版 base.zip（官方基线）")
    ap.add_argument("--manifest", required=True, help="manifest.json 路径")
    ap.add_argument("--fix", action="store_true", help="应用修复（写回 manifest 与树）")
    a = ap.parse_args(argv)
    global MOD, BASE, MAN
    MOD, BASE, MAN = a.mod, a.base, a.manifest
    fix = a.fix
    texts = baseline()
    decl = declared_names(texts)
    m = json.load(open(MAN, encoding="utf-8"))
    refs = our_refs(m)
    print("我们内容里的 `$/a/b/Name` 引用 %d 种" % len(refs))

    bad = []
    for ref, cnt in sorted(refs.items()):
        mm = re.match(r"\$/([^/]+)/([^/]+)/([^/]+)$", ref)
        if not mm:
            continue
        name = mm.group(3)
        if name not in decl:
            bad.append((ref, cnt, "名字在基线里不存在", None))
            continue
        canon = canonical_prefix(texts, name)
        # canon 是「前缀」，要补回名字再比；否则前缀永远不等于完整引用
        if canon and (canon + name) != ref:
            bad.append((ref, cnt, "命名空间已变", canon + name))

    if not bad:
        print("\n全部引用有效。RESULT PASS")
        return 0

    print("\n待修 %d 种：" % len(bad))
    for ref, cnt, why, canon in bad:
        print("  %-58s ×%-3d %s%s" % (ref, cnt, why, (" → " + canon) if canon else ""))
    if not fix:
        print("\n（加 --fix 应用）")
        return 1

    # 改改动包
    map_ = {ref: canon for ref, _c, _w, canon in bad if canon}
    n = 0
    for e in m["files"]:
        for a in e.get("add_units", []):
            for i, L in enumerate(a["lines"]):
                for ref, canon in map_.items():
                    if ref in L:
                        a["lines"][i] = L = L.replace(ref, canon); n += 1
        for p in e.get("patch_units", []):
            for op in p["ops"]:
                for side in ("old", "new"):
                    for i, L in enumerate(op[side]):
                        for ref, canon in map_.items():
                            if ref in L:
                                op[side][i] = L = L.replace(ref, canon); n += 1
    # 重算 add sha
    import hashlib
    for e in m["files"]:
        for a in e.get("add_units", []):
            a["sha256"] = hashlib.sha256("\n".join(a["lines"]).encode()).hexdigest()
    json.dump(m, open(MAN, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n改动包已更新 %d 处" % n)

    # 改树
    nt = 0
    for top in ("GameData", "CommonData"):
        for dp, _, fs in os.walk(os.path.join(MOD, top)):
            for f in fs:
                if not f.endswith(".ndf"):
                    continue
                p = os.path.join(dp, f)
                raw = open(p, "rb").read()
                if b"$/GFX/UnitConstantes/" not in raw:
                    continue
                t = raw.decode("utf-8", "replace")
                for ref, canon in map_.items():
                    if ref in t:
                        t = t.replace(ref, canon); nt += 1
                open(p, "wb").write(t.encode("utf-8"))
    print("树内已更新 %d 处" % nt)
    print("\nRESULT FIXED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
