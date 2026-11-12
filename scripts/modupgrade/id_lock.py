# -*- coding: utf-8 -*-
"""身份锁：把「升级后最容易静默撞车」的四类身份冻结成文件，升级后可一键复检。

四类身份
  UnitId        `DeckSerializer.ndf` 的 `UnitIds` MAP 里 `($/GFX/Unit/X, N)`
  DescriptorId  `UniteDescriptor.ndf` 里每个单位的 `GUID:{...}`
  NameToken     单位块的 `NameToken = '...'`（面板显示名，撞了就是乱码/错名字）
  BlackHoleKey  外观键（撞了就是「模型长成别人的样子」）

用法：
  python upgrade/lock_ids.py                       # 生成 upgrade/manifest/id_lock.json
  python upgrade/lock_ids.py --check <base.zip>    # 升级后复检（新版基线 vs 锁文件）
"""
import argparse
import hashlib
import json
import os
import re
import sys
import zipfile
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import manifest_export as E
import ndflib

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = None
DEF_BASE = None

RE_UNITID = re.compile(r"\(\s*\$/GFX/Unit/(\S+?)\s*,\s*(\d+)\s*\)")
RE_GUID = re.compile(r"GUID:\{([0-9a-fA-F\-]{36})\}")
RE_TOKEN = re.compile(r"NameToken\s*=\s*['\"]([^'\"]+)['\"]")
RE_BH = re.compile(r"BlackHoleKey\s*=\s*['\"]([^'\"]+)['\"]")
RE_MIMETIC = re.compile(r"MimeticName\s*=\s*['\"]([^'\"]+)['\"]")


def _strip(name):
    return name[len("Descriptor_Unit_"):] if name.startswith("Descriptor_Unit_") else name


def scan_dir(root):
    """→ dict(unitids, guids, tokens, blackholes, per_file)"""
    unite = os.path.join(root, "GameData/Generated/Gameplay/Gfx/UniteDescriptor.ndf")
    ser = os.path.join(root, "GameData/Generated/Gameplay/Decks/DeckSerializer.ndf")
    res = {"unitids": {}, "guids": {}, "tokens": {}, "blackholes": {}, "mimetics": {}}

    if os.path.exists(ser):
        t = open(ser, "rb").read().decode("utf-8", "replace")
        for name, n in RE_UNITID.findall(t):
            res["unitids"].setdefault(int(n), []).append(_strip(name))

    if os.path.exists(unite):
        t = open(unite, "rb").read().decode("utf-8", "replace")
        doc = ndflib.parse(t)
        for u in doc.units:
            body = "\n".join(u["lines"])
            m = re.search(r"Descriptor_Unit_(\S+?)\s+is", u["decl"])
            uid = m.group(1) if m else u["decl"]
            for g in RE_GUID.findall(body)[:1]:
                res["guids"].setdefault(g.lower(), []).append(uid)
            for tk in RE_TOKEN.findall(body)[:1]:
                res["tokens"].setdefault(tk, []).append(uid)
            for bh in RE_BH.findall(body)[:1]:
                res["blackholes"].setdefault(bh, []).append(uid)
            for mm in RE_MIMETIC.findall(body)[:1]:
                res["mimetics"].setdefault(mm, []).append(uid)
    return res


def scan_zip(path):
    """从 base.zip 里扫（不落盘）→ 同结构，另加 max_unitid。"""
    z = zipfile.ZipFile(path)
    res = {"unitids": {}, "guids": {}, "tokens": {}, "blackholes": {}, "mimetics": {}}

    def txt(name):
        for n in z.namelist():
            if n.replace("\\", "/").endswith(name):
                return z.read(n).decode("utf-8", "replace")
        return ""

    ser = txt("Decks/DeckSerializer.ndf")
    for name, n in RE_UNITID.findall(ser):
        res["unitids"].setdefault(int(n), []).append(_strip(name))
    # 2026-11-12 的游戏更新把单位表从 Gfx/UniteDescriptor.ndf 改名为 Gameplay/TacticalUnits.ndf
    unite = txt("Gameplay/TacticalUnits.ndf") or txt("Gfx/UniteDescriptor.ndf")
    for u in ndflib.parse(unite).units:
        body = "\n".join(u["lines"])
        m = re.search(r"Descriptor_Unit_(\S+?)\s+is", u["decl"])
        uid = m.group(1) if m else u["decl"]
        for g in RE_GUID.findall(body)[:1]:
            res["guids"].setdefault(g.lower(), []).append(uid)
        for tk in RE_TOKEN.findall(body)[:1]:
            res["tokens"].setdefault(tk, []).append(uid)
        for bh in RE_BH.findall(body)[:1]:
            res["blackholes"].setdefault(bh, []).append(uid)
        for mm in RE_MIMETIC.findall(body)[:1]:
            res["mimetics"].setdefault(mm, []).append(uid)
    return res


def build():
    if not MOD or not OUT:
        sys.exit("[FAIL] 需要 --mod 与 --out")
    mod = scan_dir(MOD)
    base = scan_zip(DEF_BASE)

    our_names = set()
    # 2026-11-12 起官方把单位表改名 TacticalUnits.ndf，两处都要兼容
    unite = os.path.join(MOD, "GameData/Generated/Gameplay/TacticalUnits.ndf")
    if not os.path.exists(unite):
        unite = os.path.join(MOD, "GameData/Generated/Gameplay/Gfx/UniteDescriptor.ndf")
    if os.path.exists(unite):
        for u in ndflib.parse(open(unite, "rb").read().decode("utf-8", "replace")).units:
            m = re.search(r"Descriptor_Unit_(\S+?)\s+is", u["decl"])
            if m:
                our_names.add(m.group(1))
    base_names = set()
    for lst in base["unitids"].values():
        base_names.update(lst)
    ours = sorted(our_names - base_names)
    our_ids = {n: i for i, lst in mod["unitids"].items() for n in lst if n in set(ours)}

    lock = {
        "schema": "warno-idlock/1",
        "captured_at": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
        "base_zip": os.path.abspath(DEF_BASE),
        "base_zip_sha256": hashlib.sha256(open(DEF_BASE, "rb").read()).hexdigest(),
        "base": {
            "max_unitid": max(base["unitids"]) if base["unitids"] else None,
            "unitid_count": len(base["unitids"]),
            "guid_count": len(base["guids"]),
            "guid_dups": {k: v for k, v in base["guids"].items() if len(v) > 1},
        },
        "mod": {
            "max_unitid": max(mod["unitids"]) if mod["unitids"] else None,
            "unitid_count": len(mod["unitids"]),
            "guid_count": len(mod["guids"]),
            "guid_dups": {k: v for k, v in mod["guids"].items() if len(v) > 1},
            "token_dups": {k: v for k, v in mod["tokens"].items() if len(v) > 1},
            "blackhole_dups": {k: v for k, v in mod["blackholes"].items() if len(v) > 1},
        },
        "our_units": sorted(ours),
        "our_unitids": {str(v): k for k, v in sorted(our_ids.items(), key=lambda x: x[1])},
        "our_guid": {n: [g for g, lst in mod["guids"].items() if n in lst] for n in sorted(ours)},
        "our_tokens": {n: [t for t, lst in mod["tokens"].items() if n in lst] for n in sorted(ours)},
        "our_blackholes": {n: [b for b, lst in mod["blackholes"].items() if n in lst]
                           for n in sorted(ours)},
        "our_mimetics": {n: [m for m, lst in mod["mimetics"].items() if n in lst]
                         for n in sorted(ours)},
        "rule": {
            "unitid_range": [min(our_ids.values()) if our_ids else None,
                             max(our_ids.values()) if our_ids else None],
            "collision_condition": "新版官方 max UnitId ≥ 本 Mod 最小自建 UnitId → 必须整体重编号",
        },
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(lock, f, ensure_ascii=False, indent=1)

    print("锁文件 → %s" % OUT)
    print("  基线 UnitId  %d 条，最大 %s" % (lock["base"]["unitid_count"], lock["base"]["max_unitid"]))
    print("  Mod  UnitId  %d 条，最大 %s" % (lock["mod"]["unitid_count"], lock["mod"]["max_unitid"]))
    print("  自建单位     %d 个，UnitId %s..%s"
          % (len(ours), lock["rule"]["unitid_range"][0], lock["rule"]["unitid_range"][1]))
    print("  GUID 重复    %d" % len(lock["mod"]["guid_dups"]))
    print("  NameToken 重复 %d / BlackHoleKey 重复 %d"
          % (len(lock["mod"]["token_dups"]), len(lock["mod"]["blackhole_dups"])))
    write_md(lock)
    print("  人读版       %s" % os.path.join(os.path.dirname(OUT), "ID_LOCK.md"))
    return lock


def write_md(lock):
    L = []
    L.append("# 身份锁（升级后复检用）\n")
    L.append("> 由 `upgrade/lock_ids.py` 生成，勿手改。复检：`python upgrade/lock_ids.py --check <新版base.zip>`\n")
    L.append("## 1. 基线 vs 本 Mod\n")
    L.append("| 项 | 基线 | Mod |")
    L.append("|---|---|---|")
    L.append("| UnitId 条数 | %s | %s |" % (lock["base"]["unitid_count"], lock["mod"]["unitid_count"]))
    L.append("| UnitId 最大值 | %s | %s |" % (lock["base"]["max_unitid"], lock["mod"]["max_unitid"]))
    L.append("| DescriptorId GUID | %s | %s |" % (lock["base"]["guid_count"], lock["mod"]["guid_count"]))
    L.append("")
    lo, hi = lock["rule"]["unitid_range"]
    L.append("## 2. 撞号红线\n")
    L.append("自建 UnitId 区间：**%s – %s**（%d 个）\n" % (lo, hi, len(lock["our_unitids"])))
    L.append("**判据**：新版官方 `max UnitId ≥ %s` → 必须把自建单位整体重编号到 `新版 max + 1` 起，"
             "否则卡组存档会串位（编译期零报错）。\n" % lo)
    L.append("## 3. 自建单位与身份\n")
    L.append("| 单位 | UnitId | NameToken | MimeticName |")
    L.append("|---|---|---|---|")
    for n in lock["our_units"]:
        uid = [k for k, v in lock["our_unitids"].items() if v == n]
        tk = (lock["our_tokens"].get(n) or ["-"])[0]
        mm = (lock["our_mimetics"].get(n) or ["-"])[0]
        L.append("| %s | %s | %s | %s |" % (n, uid[0] if uid else "-", tk, mm))
    L.append("")
    reuse = {n: [m for m in ms if m != n] for n, ms in lock.get("our_mimetics", {}).items()}
    reuse = {k: v for k, v in reuse.items() if v}
    if reuse:
        L.append("## 4. 有意复用原版外观（BlackHoleKey / MimeticName 与他人相同）\n")
        L.append("这不是 bug：这些单位就是拿原版模型当自己的外观。\n")
        L.append("| 我方单位 | 复用的外观键 |\n|---|---|")
        for n, ms in sorted(reuse.items()):
            L.append("| %s | %s |" % (n, ", ".join(ms)))
        L.append("")
    if lock["mod"]["token_dups"]:
        L.append("## 5. 既有 NameToken 重复（原版内部共用，非本轮引入）\n")
        for k, v in sorted(lock["mod"]["token_dups"].items())[:20]:
            L.append("- `%s` ← %s" % (k, ", ".join(v)))
        L.append("")
    with open(os.path.join(os.path.dirname(OUT), "ID_LOCK.md"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L))


def check(base_zip):
    lock = json.load(open(OUT, encoding="utf-8"))
    new = scan_zip(base_zip)
    ok = True
    lo, hi = lock["rule"]["unitid_range"]
    nmax = max(new["unitids"]) if new["unitids"] else -1
    print("新版基线 %s" % base_zip)
    print("  官方 UnitId 最大 %s（旧基线 %s，本 Mod 自建 %s..%s）"
          % (nmax, lock["base"]["max_unitid"], lo, hi))
    if nmax >= lo:
        ok = False
        clash = sorted(i for i in new["unitids"] if lo <= i <= hi)
        print("  ❌ UnitId 撞号：%d 个（%s…）→ 自建单位必须整体重编号到 %d 之后"
              % (len(clash), clash[:8], nmax + 1))
    else:
        print("  ✅ UnitId 无撞号（余量 %d）" % (lo - nmax - 1))

    # GUID / token / blackhole 撞车
    for kind, key in (("GUID", "guids"), ("NameToken", "tokens"), ("BlackHoleKey", "blackholes"), ("MimeticName", "mimetics")):
        ours = set(lock["our_" + ("guid" if kind == "GUID" else
                                  "tokens" if kind == "NameToken" else "blackholes")])
        hit = []
        for k, lst in new[key].items():
            for n in lst:
                if n in ours:
                    hit.append(k)
        if hit:
            ok = False
            print("  ❌ %s 撞车 %d 个：%s" % (kind, len(hit), hit[:5]))
        else:
            print("  ✅ %s 无撞车" % kind)

    # 我们的单位是否还在新版官方里（被官方接管/重名）
    our = set(lock["our_units"])
    official_new = set(n for lst in new["unitids"].values() for n in lst)
    overlap = sorted(our & official_new)
    if overlap:
        ok = False
        print("  ❌ 新版官方新增了与我们同名的单位：%s" % overlap[:8])
    else:
        print("  ✅ 无同名单位")
    print("\nRESULT %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mod", default=None, help="当前 Mod 根目录（建锁/复检都要）")
    ap.add_argument("--out", default=None, help="锁文件输出路径（默认 <mod>/upgrade_manifest/id_lock.json）")
    ap.add_argument("--check", default=None, help="对新版 base.zip 复检（不写锁）")
    a = ap.parse_args(argv)
    global MOD, OUT
    if a.mod:
        MOD = a.mod
    if a.out:
        OUT = a.out
    elif MOD:
        OUT = os.path.join(MOD, "upgrade_manifest", "id_lock.json")
    if a.check:
        if not OUT or not os.path.exists(OUT):
            sys.exit("[FAIL] 找不到锁文件：%s\n"
                     "       先建锁：python modupgrade.py lock --mod <Mod> --out <id_lock.json>"
                     % OUT)
        sys.exit(check(a.check))
    build()


if __name__ == "__main__":
    main()
