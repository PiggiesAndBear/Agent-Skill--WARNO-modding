# -*- coding: utf-8 -*-
"""导出「旧基线 → 当前 Mod」的对象级改动包（manifest）。

核心思想（SOP §1.4）：不存「行号 + 整段新文本」，而存
  · add_units   整块新增对象（含前导注释），落点用「前后邻居声明」定位
  · patch_units 已存在对象内的行级增删改，用「旧行内容 + 上下文」定位
  · whole_file  新增/非 ndf/混合行尾文件，整份带走（内容存 sidecar，不塞进 JSON）
这样新版官方在原对象前后插了多少东西都不影响命中。

用法：
  python upgrade/export_manifest.py                 # 默认：旧 base.zip（新版本迁移/base(old).zip）vs 当前 Mod
  python upgrade/export_manifest.py --base <zip> --mod <dir> --out <dir>
  python upgrade/export_manifest.py --only UniteDescriptor.ndf   # 只导一个文件（调试）
"""
import argparse
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ndflib

DEF_MOD = None
DEF_BASE = None
DEF_OUT = None

SKIP_DIR_PREFIX = ("GameData/Gen/",)          # 编译产物，不进 manifest
ASSET_PREFIX = ("GameData/Assets/", "CommonData/Assets/")   # 二进制资产，只做清单
TEXT_EXT = (".ndf", ".csv", ".txt", ".dic")
# 开发期备份 / 临时文件：不是 Mod 的组成部分，必须排除
BACKUP_MARKS = (".bak", ".before", ".orig", "~", ".old", ".tmp", ".save")


def is_backup_name(rel):
    name = rel.rsplit("/", 1)[-1].lower()
    return any(m in name for m in BACKUP_MARKS)


# ---------------------------------------------------------------- 基础工具
def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def zip_index(zip_path):
    """zip → {relpath: bytes}（只收 GameData/ 与 CommonData/）。"""
    import zipfile
    out = {}
    with zipfile.ZipFile(zip_path) as z:
        for n in z.namelist():
            if n.endswith("/"):
                continue
            r = n.replace("\\", "/")
            if r.startswith(SKIP_DIR_PREFIX) or is_backup_name(r):
                continue
            if not (r.startswith("GameData/") or r.startswith("CommonData/")):
                continue
            out[r] = z.read(n)
    return out


def walk_tree(root):
    """mod 根目录 → {relpath: (abs_path, bytes)}（只收 GameData/ 与 CommonData/）。"""
    out = {}
    for top in ("GameData", "CommonData"):
        d = os.path.join(root, top)
        if not os.path.isdir(d):
            continue
        for dp, _, fs in os.walk(d):
            for f in fs:
                p = os.path.join(dp, f)
                rel = os.path.relpath(p, root).replace("\\", "/")
                if rel.startswith(SKIP_DIR_PREFIX) or is_backup_name(rel):
                    continue
                out[rel] = p
    return out


# ---------------------------------------------------------------- 对象配对
def pair_units(base_units, mod_units):
    """→ (unchanged, added, removed, modified)

    modified: [(base_u, mod_u, ambiguous)]

    三级配对，逐级放宽：
      ① (decl, sha) 精确命中 —— 原封未动的对象
      ② 同 decl 且两侧各只剩一个 —— 唯一改名/改内容
      ③ 同 decl 但出现多次（`unnamed XXX` 这类共享声明）—— **按内容相似度贪心最优配对**，
         不能按出现顺序硬配：官方多插一块就会整体错位，配错的对象会产生
         「ops 应用后 sha 不符」这种难以定位的失败。
    """
    from collections import defaultdict
    import difflib

    base_by_key, mod_by_key = {}, {}
    for u in base_units:
        base_by_key.setdefault((u["decl"], u["sha"]), []).append(u)
    for u in mod_units:
        mod_by_key.setdefault((u["decl"], u["sha"]), []).append(u)

    unchanged = []
    used_base, used_mod = set(), set()
    for k, bl in base_by_key.items():
        ml = mod_by_key.get(k)
        if not ml:
            continue
        for i in range(min(len(bl), len(ml))):
            unchanged.append((bl[i], ml[i]))
            used_base.add(id(bl[i]))
            used_mod.add(id(ml[i]))

    rb = [u for u in base_units if id(u) not in used_base]
    rm = [u for u in mod_units if id(u) not in used_mod]

    gb, gm = defaultdict(list), defaultdict(list)
    for u in rb:
        gb[u["decl"]].append(u)
    for u in rm:
        gm[u["decl"]].append(u)

    removed, added, modified = [], [], []
    for d in set(list(gb.keys()) + list(gm.keys())):
        b, m = list(gb.get(d, [])), list(gm.get(d, []))

        # ② 一对一
        if len(b) == 1 and len(m) == 1:
            modified.append((b[0], m[0], False))
            continue
        if not b:
            added.extend(m)
            continue
        if not m:
            removed.extend(b)
            continue

        # ③ 相似度贪心配对
        def ratio(x, y):
            # 取前 240 行做指纹，足够区分 registration 块；避免大块全量 diff
            ax = "\n".join(x["lines"][:240])
            ay = "\n".join(y["lines"][:240])
            return difflib.SequenceMatcher(None, ax, ay).quick_ratio()

        cand = []
        for i, bu in enumerate(b):
            for j, mu in enumerate(m):
                cand.append((ratio(bu, mu), i, j))
        cand.sort(reverse=True)
        taken_b, taken_m = set(), set()
        for r, i, j in cand:
            if i in taken_b or j in taken_m:
                continue
            if r < 0.30:          # 相似度过低 → 不认为是同一对象
                break
            taken_b.add(i); taken_m.add(j)
            modified.append((b[i], m[j], True))
        for i, bu in enumerate(b):
            if i not in taken_b:
                removed.append(bu)
        for j, mu in enumerate(m):
            if j not in taken_m:
                added.append(mu)

    # 保持"新增"按 mod 内顺序，注入端依赖这个顺序做组内偏移
    order = {id(u): i for i, u in enumerate(mod_units)}
    added.sort(key=lambda u: order.get(id(u), 0))
    return unchanged, added, removed, modified


def witness_line(old_lines, siblings):
    """在「同 decl 的其它**旧版**对象」里挑一条只属于本对象的旧行。

    ★ 必须用 base 侧的兄弟来判唯一：用 mod 侧兄弟会把「本对象被我们改出来的新行」
      误判成不唯一（那些新行在 base 里压根不存在，无法在注入端命中）。
    """
    others = set()
    for s in siblings:
        others.update(s["lines"])

    def unique(s):
        return len(s) >= 8 and s not in others and s not in ("(", ")", "{", "}", "[", "]", "),")

    # ① 优先用「身份行」：同一族的无名块往往只差这一行（实测 AH64_Apache_US 与
    #    AH64_Apache_ATAS_US 相似度 0.987 vs 0.986，靠相似度会认错）。
    import re as _re
    for key in ("BlackHoleKey", "MimeticName", "NameToken", "DescriptorId"):
        rx = _re.compile(r"^\s*" + key + r"\s*=")
        for L in old_lines:
            if rx.match(L) and unique(L.strip()):
                return L
    # ② 退而求其次：最长且唯一的一行
    best, best_len = None, -1
    for L in old_lines:
        s = L.strip()
        if not unique(s):
            continue
        if len(s) > best_len:
            best, best_len = L, len(s)
    return best


# ---------------------------------------------------------------- 行级 diff
def line_ops(old_lines, new_lines, ctx=2):
    """→ [{op, old, new, ctx_before, ctx_after, occurrence, nth}]

    occurrence = 旧行块在对象内出现的总次数（用于判断锚点是否唯一）；
    nth        = 本次这一处是第几次命中（导出时就知道确切位置，注入端可按此兜底）。
    """
    import difflib
    sm = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    ops = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        o = old_lines[i1:i2]
        n = new_lines[j1:j2]
        cb = old_lines[max(0, i1 - ctx):i1]
        ca = old_lines[i2:i2 + ctx]
        # occurrence/nth 必须按「含上下文的命中」算，与注入端 ndflib.find_block 同口径。
        # 只按裸行块计数会让 `nth` 指向注入端并不存在的位置（StrategicDecks 实测踩到）。
        hits = ndflib.find_block(old_lines, o, cb, ca)
        occ = len(hits)
        nth = hits.index(i1) if i1 in hits else 0
        ops.append({
            "op": "replace" if (o and n) else ("insert" if n else "delete"),
            "old": o,
            "new": n,
            "ctx_before": cb,
            "ctx_after": ca,
            "occurrence": occ,
            "nth": nth,
        })
    return ops


def describe_path(rel):
    return rel


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="旧基线 zip（升级前那份 base.zip）")
    ap.add_argument("--mod", required=True, help="当前 Mod 根目录")
    ap.add_argument("--out", required=True, help="改动包输出目录")
    ap.add_argument("--only", default=None, help="只处理文件名包含该子串的文件（调试用）")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    if not os.path.isfile(a.base):
        sys.exit("[FAIL] 找不到旧基线 zip：%s" % a.base)

    t0 = time.time()
    base = zip_index(a.base)
    mod = walk_tree(a.mod)
    base_sha = sha_bytes(open(a.base, "rb").read())

    os.makedirs(a.out, exist_ok=True)
    blob_dir = os.path.join(a.out, "blobs")
    os.makedirs(blob_dir, exist_ok=True)

    files_out = []
    binary_inv = []
    stats = {"changed_ndf": 0, "new_ndf": 0, "whole_file": 0,
             "deleted": 0, "identical": 0, "add_units": 0,
             "patch_units": 0, "del_units": 0, "ops": 0, "mixed_eol": 0,
             "binary_assets": 0, "binary_other": 0}
    warnings = []

    # ★ 防御：目标树若**已经是新基线**，diff 会静默爆掉 —— 实测拿迁移后的树去导出，
    #   得到 22 MB 改动包、2490 个对象被判改写（真值 1.26 MB / 91），而且不报任何错。
    #   这里只警告、不阻断（有人可能确实想快照「新版官方 vs 我的」）。
    if ("GameData/Generated/Gameplay/TacticalUnits.ndf" in mod
            and "GameData/Generated/Gameplay/Gfx/UniteDescriptor.ndf" in base):
        warnings.append("目标树看起来**已经是新基线**（它有 TacticalUnits.ndf，而旧基线还是 "
                        "UniteDescriptor.ndf）。这样导出的改动包会把「新版官方内容」当成你的改动，"
                        "通常是错的 —— 请对**升级前**的树导出。")

    rels = sorted(set(list(base.keys()) + list(mod.keys())))
    for rel in rels:
        if a.only and a.only not in rel:
            continue
        if rel.endswith(".ndf") is False and rel not in base:
            pass  # 新增非 ndf 也要收
        in_base, in_mod = rel in base, rel in mod
        if not in_mod:
            stats["deleted"] += 1
            files_out.append({"path": rel, "kind": "deleted",
                              "note": "Mod 里已删除，官方新版若有需显式再删"})
            continue
        mod_bytes = open(mod[rel], "rb").read()
        if in_base and sha_bytes(mod_bytes) == sha_bytes(base[rel]):
            stats["identical"] += 1
            continue

        # 资产目录（fbx/png…）单独走清单，不进 files
        if rel.startswith(ASSET_PREFIX):
            binary_inv.append({"path": rel, "bytes": len(mod_bytes),
                               "sha256": sha_bytes(mod_bytes),
                               "base": "present" if in_base else "absent"})
            stats["binary_assets"] += 1
            continue

        ext = os.path.splitext(rel)[1].lower()
        if ext not in TEXT_EXT:
            binary_inv.append({"path": rel, "bytes": len(mod_bytes),
                               "sha256": sha_bytes(mod_bytes),
                               "base": "present" if in_base else "absent"})
            stats["binary_other"] += 1
            continue

        if not rel.endswith(".ndf") or not in_base:
            # 新增 ndf / 文本附件 → 整份带走（正文落 blobs，按 sha 校验）
            blob = hashlib.sha256(mod_bytes).hexdigest()[:16] + "__" + os.path.basename(rel)
            open(os.path.join(blob_dir, blob), "wb").write(mod_bytes)
            files_out.append({"path": rel, "kind": "whole_file",
                              "base": "present" if in_base else "absent",
                              "bytes": len(mod_bytes),
                              "sha256": sha_bytes(mod_bytes),
                              "blob": blob})
            stats["whole_file"] += 1
            if not in_base and rel.endswith(".ndf"):
                stats["new_ndf"] += 1
            continue

        # 改动过的 ndf → 对象级
        btext = base[rel].decode("utf-8", "replace")
        mtext = mod_bytes.decode("utf-8", "replace")
        bdoc, mdoc = ndflib.parse(btext), ndflib.parse(mtext)
        # 安全网：解析不出对象却又有内容差异 → 降级整份拷贝，绝不「看起来处理了其实没改」
        if not mdoc.units and mtext.strip():
            blob = hashlib.sha256(mod_bytes).hexdigest()[:16] + "__" + os.path.basename(rel)
            open(os.path.join(blob_dir, blob), "wb").write(mod_bytes)
            files_out.append({"path": rel, "kind": "whole_file", "base": "present",
                              "bytes": len(mod_bytes), "sha256": sha_bytes(mod_bytes),
                              "blob": blob, "note": "对象切分失败（0 个顶层对象）→ 降级整份拷贝"})
            warnings.append("%s：解析出 0 个顶层对象 → 降级整份拷贝（请检查声明关键字）" % rel)
            continue
        if "MIXED" in (bdoc.eol, mdoc.eol):
            stats["mixed_eol"] += 1
            blob = hashlib.sha256(mod_bytes).hexdigest()[:16] + "__" + os.path.basename(rel)
            open(os.path.join(blob_dir, blob), "wb").write(mod_bytes)
            files_out.append({"path": rel, "kind": "whole_file", "base": "present",
                              "bytes": len(mod_bytes), "sha256": sha_bytes(mod_bytes),
                              "blob": blob, "note": "混合行尾，降级整份拷贝"})
            warnings.append("%s 混合行尾 → 降级整份拷贝" % rel)
            continue

        unchanged, added, removed, modified = pair_units(bdoc.units, mdoc.units)
        entry = {"path": rel, "kind": "ndf", "eol": mdoc.eol,
                 "sha256": sha_bytes(mod_bytes),
                 "sha256_base": sha_bytes(base[rel]),
                 # 收尾也要带上：对象之后的空行/注释若与基线不同（如删掉末尾多余空行），
                 # 只记对象级改动是还原不出来的。
                 "tail": mdoc.tail,
                 "final_newline": mdoc.final_newline,
                 "counts": {"units_base": len(bdoc.units), "units_mod": len(mdoc.units),
                            "unchanged": len(unchanged), "added": len(added),
                            "removed": len(removed), "modified": len(modified)}}

        # --- 新增对象：锚在「相邻且两侧都唯一的对象」上
        # ★ 不能用 (decl, sha) 不唯一的块当锚点：`unnamed XXX` 这类块大量重复，
        #   注入端按 (decl, sha) 找会永远命中第一个，整块就被搬到文件前部。
        # ★ offset 用**真实索引差**（锚对象与本对象之间隔了几个对象），而不是"隔了几个新增对象"：
        #   中间那些原版对象在目标里同样存在，位置必须一起算进去。
        from collections import Counter
        uniq_mod = Counter((u["decl"], u["sha"]) for u in mdoc.units)
        uniq_base = Counter((u["decl"], u["sha"]) for u in bdoc.units)

        def is_unique(decl, sha):
            k = (decl, sha)
            return uniq_mod.get(k, 0) == 1 and uniq_base.get(k, 0) == 1

        mod_index = {id(u): i for i, u in enumerate(mdoc.units)}
        adds = []
        for u in added:
            idx = mod_index[id(u)]
            after = after_sha = before = before_sha = None
            off_a = off_b = 0
            for j in range(idx - 1, -1, -1):
                cand = mdoc.units[j]
                if is_unique(cand["decl"], cand["sha"]):
                    after, after_sha = cand["decl"], cand["sha"]
                    off_a = idx - j - 1
                    break
            for j in range(idx + 1, len(mdoc.units)):
                cand = mdoc.units[j]
                if is_unique(cand["decl"], cand["sha"]):
                    before, before_sha = cand["decl"], cand["sha"]
                    off_b = j - idx - 1
                    break
            # ★ 新增对象只保留「从 decl 起」的部分：解析器会把不认识的整段
            #   （如 //Firing Templates + template FXFiring_* ）当成下一个 decl 的
            #   前导行，导致新增对象吞掉几百行官方内容（实测 649 行）。
            _lines = u["lines"]
            _name = u["decl"].split()[0]
            for _i, _L in enumerate(_lines[:400]):
                if _L.strip().startswith(_name + " "):
                    if _i > 0:
                        _lines = _lines[_i:]
                    break
            adds.append({"decl": u["decl"],
                         "after": after, "after_sha": after_sha, "offset_after": off_a,
                         "before": before, "before_sha": before_sha, "offset_before": off_b,
                         "sha256": u["sha"], "lines": _lines})
        if adds:
            entry["add_units"] = adds
            stats["add_units"] += len(adds)

        # --- 删除对象（罕见，但要留痕）
        if removed:
            entry["del_units"] = [{"decl": u["decl"], "sha256": u["sha"],
                                   "lines": u["lines"]} for u in removed]
            stats["del_units"] += len(removed)

        # --- 已存在对象内的行级改动
        patches = []
        for bu, mu, amb in modified:
            if bu["lines"] == mu["lines"]:
                continue
            siblings = [x for x in bdoc.units if x["decl"] == bu["decl"] and x is not bu]
            ops = line_ops(bu["lines"], mu["lines"])
            if not ops:
                continue
            p = {"decl": mu["decl"], "ambiguous": amb,
                 "occur": [x["decl"] for x in mdoc.units].index(mu["decl"]),
                 "sha_old": bu["sha"], "sha_new": mu["sha"], "ops": ops}
            if amb:
                # 共享声明的对象（`unnamed XXX`）：把旧正文整块带上，注入端按**全文精确匹配**
                # 定位，天然免疫「官方多插一块 → 序号整体错位」。
                p["body_old"] = bu["lines"]
                w = witness_line(bu["lines"], siblings)
                if w is None:
                    warnings.append("%s / %s 无法取得 witness，注入端只能按序号定位"
                                    % (rel, mu["decl"]))
                else:
                    p["witness"] = w
            patches.append(p)
            stats["ops"] += len(ops)
        if patches:
            entry["patch_units"] = patches
            stats["patch_units"] += len(patches)

        files_out.append(entry)
        stats["changed_ndf"] += 1

    # --- 资产目录清单（官方升级不碰，但要能核对没丢）
    asset_dirs = {}
    for rel, p in mod.items():
        if not (rel.startswith("GameData/Assets/") or rel.startswith("CommonData/Assets/")):
            continue
        d = os.path.dirname(rel)
        e = asset_dirs.setdefault(d, {"dir": d, "files": 0, "bytes": 0})
        e["files"] += 1
        e["bytes"] += os.path.getsize(p)
    # 只保留「base 里没有的目录」（自建资产）
    base_dirs = set(os.path.dirname(r) for r in base)
    own_assets = [v for k, v in sorted(asset_dirs.items()) if k not in base_dirs]

    manifest = {
        "schema": "warno-upgrade/2",
        "source_mod": os.path.basename(os.path.normpath(a.mod)),
        "base_zip": os.path.abspath(a.base),
        "base_zip_sha256": base_sha,
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mod_root": os.path.abspath(a.mod),
        "stats": stats,
        "warnings": warnings,
        "files": files_out,
        "own_asset_dirs": own_assets,
        "binary_files": binary_inv,
        "notes": [
            "add_units.lines 含对象前导注释；落点用 after/before 的 decl，不用行号。",
            "patch_units.ops 用旧行内容 + 上下文定位，occurrence=0 表示旧文本在对象内不唯一。",
            "whole_file 的正文在 blobs/ 下，按 sha256 校验（只收文本类 ndf/csv/txt/dic）。",
            "binary_files / own_asset_dirs 只做清单与校验：官方升级不动 *.fbx/*.png，原地保留即可；"
            "若走「新建干净 Mod」路线，从 BeforeUpdate.zip 整目录拷回。",
        ],
    }
    mp = os.path.join(a.out, "manifest.json")
    with open(mp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    if not a.quiet:
        print("基线 zip  : %s" % a.base)
        print("           sha256 %s" % base_sha)
        print("Mod 根目录: %s" % a.mod)
        print("输出      : %s" % mp)
        print()
        print("文件：改动 ndf %d / 新增 ndf %d / 整份文本 %d / 删除 %d（未变 %d）"
              % (stats["changed_ndf"], stats["new_ndf"], stats["whole_file"],
                 stats["deleted"], stats["identical"]))
        print("资产：二进制清单 %d 条（资产 %d + 其它 %d），只记 sha 不复制"
              % (stats["binary_assets"] + stats["binary_other"],
                 stats["binary_assets"], stats["binary_other"]))
        print("对象：新增 %d / 改写 %d（%d 处 op）/ 删除 %d"
              % (stats["add_units"], stats["patch_units"], stats["ops"], stats["del_units"]))
        if warnings:
            print("\n⚠ 警告 %d 条：" % len(warnings))
            for w in warnings[:10]:
                print("  - %s" % w)
        # 只打印有对象级改动的文件
        print("\n对象级改动文件（前 25）：")
        for e in files_out:
            if e["kind"] == "ndf":
                c = e["counts"]
                if c["added"] or c["modified"] or c["removed"]:
                    print("  %-72s +%d ~%d -%d"
                          % (e["path"].replace("GameData/Generated/", ""),
                             c["added"], c["modified"], c["removed"]))
        print("\n耗时 %.1f s，manifest %.2f MB"
              % (time.time() - t0, os.path.getsize(mp) / 1048576.0))


if __name__ == "__main__":
    main()
