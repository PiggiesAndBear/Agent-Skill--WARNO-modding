# -*- coding: utf-8 -*-
"""把改动包（manifest）注入到目标 Mod 目录。

两个用途：
  1. **自洽性验证**：注入到旧基线解包目录，结果必须与当前 Mod 逐字节一致（selftest_roundtrip.py）。
  2. **真升级**：注入到新版官方干净基线（或 UpdateMod 后的目录）。

定位纪律（全部内容锚点，无行号）：
  · patch_units 的 op：在目标对象内按「旧行块 + 上下 N 行」找唯一命中；命中数必须 == 1
  · add_units：按 after/before 的 decl 找邻居；同名对象已存在时做「同内容则跳过、异内容则报冲突」
  · 每个对象改完都要满足 sha == sha_new，否则整文件拒绝写盘

用法：
  python upgrade/apply_manifest.py --target <dir> [--manifest <json>] [--dry]
  python upgrade/apply_manifest.py --target <dir> --only UniteDescriptor.ndf
"""
import argparse
import hashlib
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ndflib

HERE = os.path.dirname(os.path.abspath(__file__))
DEF_MANIFEST = None
RETARGET = None


def load_retarget(path=None):
    """目标基线里文件改名时的重定向表（键为改动包里的老路径）。

    默认与 manifest 同目录（`retarget.json`）；不存在就当作无重定向。
    """
    path = path or RETARGET
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    return {k: v for k, v in d.items() if not k.startswith("_")}


def retarget_candidates(manifest):
    """重定向表可能落的位置（按优先级）。

    实测踩过：`retarget.json` 通常与 manifest **目录**同级，而 manifest 在 `manifest/` 子目录里，
    只查 manifest 同级会找不到 → 路径重定向不触发 → 注入打在一份过期的旧文件上。
    """
    out = []
    if RETARGET:
        out.append(RETARGET)
    mp = manifest.get("_path")
    if mp:
        d = os.path.dirname(os.path.abspath(mp))
        out += [os.path.join(d, "retarget.json"),
                os.path.join(os.path.dirname(d), "retarget.json")]
    out.append(os.path.join(os.getcwd(), "retarget.json"))
    return out


class Fail(Exception):
    pass


class AlreadyDone(Exception):
    """目标对象已经是目标态（重复注入时走这条路，不算错误）。"""
    pass


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def load_manifest(p):
    with open(p, "r", encoding="utf-8") as f:
        m = json.load(f)
    m["_path"] = os.path.abspath(p)
    return m


# ------------------------------------------------------------------ 定位
def find_block(lines, old, ctx_before, ctx_after):
    """→ 命中位置列表（起点索引）。old 为空时按 ctx 找插入点。"""
    hits = []
    n_old = len(old)
    if n_old == 0:
        # 插入：位置 i 满足 lines[i-len(cb):i] == cb 且 lines[i:i+len(ca)] == ca
        lo = len(ctx_before)
        hi = len(lines) - len(ctx_after)
        for i in range(lo, hi + 1):
            if lines[i - len(ctx_before):i] == ctx_before and \
               lines[i:i + len(ctx_after)] == ctx_after:
                hits.append(i)
        return hits
    for i in range(0, len(lines) - n_old + 1):
        if lines[i:i + n_old] != old:
            continue
        if ctx_before and lines[max(0, i - len(ctx_before)):i] != ctx_before:
            continue
        if ctx_after and lines[i + n_old:i + n_old + len(ctx_after)] != ctx_after:
            continue
        hits.append(i)
    return hits


def apply_ops_to_unit(u, patch, rel):
    """在 unit 的 lines 上应用 ops，返回 (lines, applied, skipped, fuzzy)。

    ★ 关键一：**所有位置都先在原始行上算好，再从后往前应用**。
      否则前一个 op 的插入/替换会改变后一个 op 的上下文，导致「明明存在却找不到」。
    ★ 关键二：严格上下文失手时退到容错匹配（允许官方在同一处也插了行）。
    """
    orig = list(u["lines"])
    if sha("\n".join(orig)) == patch["sha_new"]:
        return orig, 0, len(patch["ops"]), 0          # 整对象已是目标态
    plan = []
    fuzzy = 0
    skipped = 0
    for k, op in enumerate(patch["ops"]):
        old, new = op["old"], op["new"]
        cb, ca = op.get("ctx_before", []), op.get("ctx_after", [])

        # 逐条幂等：这一处**已经注过**就跳过，而不是靠「整对象 sha 等于快照」判。
        # 官方在同一对象里也改过时，整对象 sha 永远不会等于快照，必须逐条判。
        if old:
            if new and not ndflib.find_block(orig, old, cb, ca) and contains_block(orig, new):
                skipped += 1
                continue
        else:
            if new and _inserted_already(orig, new, cb, ca):
                skipped += 1
                continue

        hits = ndflib.find_block(orig, old, cb, ca)
        if not hits:
            # 递增放大容错窗口：官方一次插入几十行（如 UnitIds 追加 30 条）时，
            # 8 行窗口不够。**只在命中唯一时接受**，唯一性就是安全网。
            for sl in (8, 32, 128, 512):
                h = ndflib.find_block_fuzzy(orig, old, cb, ca, slack=sl)
                if len(h) == 1:
                    hits = h
                    fuzzy += 1
                    break
                if len(h) > 1:
                    break          # 放大窗口导致多候选 → 放弃，交给下面的报错
        if len(hits) == 1:
            pos = hits[0]
        elif len(hits) > 1:
            nth = op.get("nth", 0)
            if nth < len(hits):
                pos = hits[nth]
            else:
                raise Fail("%s / %s：第 %d 处 op 命中 %d 次且 nth=%d 越界"
                           % (rel, patch["decl"], k, len(hits), nth))
        else:
            raise Fail("%s / %s：第 %d 处 op 找不到锚点（old %d 行，occurrence=%s）"
                       % (rel, patch["decl"], k, len(old), op.get("occurrence")))
        plan.append((pos, k, op))

    # 从后往前：位置大的先做；同位置按导出顺序**倒序**执行以保持插入顺序
    for pos, k, op in sorted(plan, key=lambda x: (-x[0], -x[1])):
        orig[pos:pos + len(op["old"])] = op["new"]
    return orig, len(plan), skipped, fuzzy


def contains_block(lines, block):
    n = len(block)
    if n == 0:
        return False
    return any(lines[i:i + n] == block for i in range(len(lines) - n + 1))


def _inserted_already(lines, new, ctx_before, ctx_after=()):
    """新块是否已经落在锚点旁（插入型 op 的幂等判据）。

    判「紧邻前上下文」或「紧邻后上下文」之一即可：同一处插入后，
    前上下文可能被官方后续插入推远，但后上下文通常仍在紧邻位置。
    """
    n, m, q = len(ctx_before), len(new), len(ctx_after)
    for i in range(len(lines) - m + 1):
        if lines[i:i + m] != new:
            continue
        if n and i >= n and lines[i - n:i] == ctx_before:
            return True
        if q and lines[i + m:i + m + q] == ctx_after:
            return True
    return False


def locate_unit(doc, patch, rel):
    """按 decl + 全文 + witness + occur 四级定位目标对象。

    共享声明的对象（`unnamed XXX`）优先用**旧正文精确匹配**：
    序号会随官方插入而整体漂移，正文不会。
    """
    decl = patch["decl"]
    cands = [u for u in doc.units if u["decl"] == decl]
    if not cands:
        raise Fail("%s：目标对象不存在 —— %s" % (rel, decl))
    if len(cands) == 1:
        return cands[0]

    body = patch.get("body_old")
    if body:
        exact = [u for u in cands if u["lines"] == body]
        if exact:
            return exact[0]
        # 旧正文已不存在，但目标态正文在 → 说明早就注过了，绝不能继续按序号猜
        if any(u["sha"] == patch["sha_new"] for u in cands):
            raise AlreadyDone()
        # 官方改过同一块时，旧正文不再完全相等。共享声明的块按**序号**猜会选错。
        # 两步：① 先用见证行把候选收窄（同一族的块往往只差一行，纯相似度会认错，实测
        # AH64_Apache_US 与 AH64_Apache_ATAS_US 相似度 0.987 vs 0.986）；② 再在收窄后的
        # 候选里按相似度取最像的一块。
        import difflib
        w0 = patch.get("witness")
        pool = [u for u in cands if w0 in u["lines"]] if w0 else list(cands)
        if not pool:
            pool = list(cands)
        base_txt = "\n".join(body)
        best, best_r = None, 0.0
        for u in pool:
            r = difflib.SequenceMatcher(None, base_txt, u["body"]).ratio()
            if r > best_r:
                best, best_r = u, r
        if best is not None and best_r >= 0.5:
            return best

    if any(u["sha"] == patch["sha_new"] for u in cands):
        raise AlreadyDone()

    w = patch.get("witness")
    if w:
        cands2 = [u for u in cands if w in u["lines"]]
        if len(cands2) == 1:
            return cands2[0]
        cands = cands2 or cands

    occ = patch.get("occur", 0)
    if occ < len(cands):
        return cands[occ]
    raise Fail("%s：%s 有 %d 个同名对象，无法定位（witness=%r）" % (rel, decl, len(cands), w))


# ------------------------------------------------------------------ 单文件
def _trim_leaked_prefix(blob_lines, units):
    """把新增对象开头「并非本对象」的前导行裁掉。

    背景：解析器会把不认识的整段（`//Firing Templates` + `template FXFiring_*`）
    当成下一个 decl 的前导行；若那一段正好在旧 Mod 里紧挨着我们新增的对象，
    导出时就会把它一起粘进新增对象（实测 649 行）。再插回新基线就是重复/错位。

    判据：前 4 行内看不到 decl，且后面的行有属于本文件其它对象的 → 裁到 decl 处。
    任何异常都不改变原行为（返回原 blob）。
    """
    try:
        if len(blob_lines) < 12:
            return blob_lines
        k = 0
        while k < len(blob_lines) and not blob_lines[k].strip():
            k += 1
        if k >= len(blob_lines):
            return blob_lines
        toks = blob_lines[k].strip().split()
        if not toks:
            return blob_lines
        first_word = toks[0]
        for i in range(min(4, len(blob_lines))):
            if blob_lines[i].strip().startswith(first_word + " "):
                return blob_lines
        body = set()
        for u in units:
            body.update(u["lines"])
        cut = 0
        for i in range(4, len(blob_lines)):
            if blob_lines[i] in body:
                cut = i
        if not cut:
            return blob_lines
        for i in range(cut, min(cut + 800, len(blob_lines))):
            t = blob_lines[i].strip()
            if re.match(r"^(?:export\s+)?[A-Za-z_]\w*\s+(?:is|\[)", t):
                if i > 3:
                    return blob_lines[i:]
                break
        return blob_lines
    except Exception:
        return blob_lines


def apply_ndf(entry, target_path, dry=False, log=None):
    """→ (bytes_written, stats)"""
    rel = entry["path"]
    if not os.path.exists(target_path):
        raise Fail("%s：目标文件不存在（新版基线里应该有）" % rel)
    text, eol, _ = ndflib.read_text(target_path)
    doc = ndflib.parse(text)
    # 行尾策略：**跟随目标基线**，不沿用旧 Mod 的状态。
    # 旧 Mod 里有一批文件被早期脚本从 LF 改写成了 CRLF；若把它们再写回新基线，
    # 之后每次 diff 都会「整个文件都变了」，跨版本合并就永久失去可读性。
    eol_fix = (doc.eol != entry["eol"])

    st = {"add": 0, "add_skip": 0, "op_applied": 0, "op_skip": 0, "del": 0,
          "eol": ("%s→%s" % (entry["eol"], doc.eol)) if eol_fix else ""}
    new_units = list(doc.units)

    # 1) 已存在对象内的行级改动
    for patch in entry.get("patch_units", []):
        try:
            u = locate_unit(doc, patch, rel)
        except AlreadyDone:
            st["op_skip"] += len(patch["ops"])
            continue
        except Fail:
            # 已经注入过的对象，定位锚点（旧正文/见证行）自然不再成立 —— 用「目标态 sha」兜底
            if any(x["sha"] == patch["sha_new"] for x in doc.units):
                st["op_skip"] += len(patch["ops"])
                continue
            raise
        lines, a, s, fz = apply_ops_to_unit(u, patch, rel)
        # 验收口径：**逐条确认我们插入/替换的行确实在**，而不是要求整个对象等于旧快照。
        # 新版官方可能在同一对象里也改了东西，整体 sha 天然对不上（那是正常的）。
        missing = []
        for k, op in enumerate(patch["ops"]):
            if op["new"]:
                if not contains_block(lines, op["new"]):
                    missing.append("op%d(+%d 行)" % (k, len(op["new"])))
            elif op["old"] and contains_block(lines, op["old"]):
                missing.append("op%d(旧行未删除)" % k)
        if missing:
            raise Fail("%s / %s：注入后自检失败，缺 %s"
                       % (rel, patch["decl"], ", ".join(missing)))
        got = sha("\n".join(lines))
        idx = new_units.index(u)
        new_units[idx] = dict(u, lines=lines, body="\n".join(lines), sha=got)
        st["op_applied"] += a
        st["op_skip"] += s
        st["fuzzy"] = st.get("fuzzy", 0) + fz
        if got != patch["sha_new"]:
            # 我们的改动都在，但对象不再与旧快照全等 → 官方在此对象里也有改动（预期内）
            st["drift"] = st.get("drift", 0) + 1

    # 2) 新增对象
    adds = entry.get("add_units", [])
    for add in adds:
        decl = add["decl"]
        # ★ 导出侧可能把「基线里已有的前导内容」粘进新增对象（实测某 FX 武器吞了
        #   649 行官方模板声明）；这种前导一旦再插回去就是重复/错位，必须在入口裁掉。
        add = dict(add, lines=_trim_leaked_prefix(add["lines"], doc.units))
        body_sha = add["sha256"]
        same = [u for u in new_units if u["decl"] == decl]
        if any(u["sha"] == body_sha for u in same):
            st["add_skip"] += 1
            continue
        # `unnamed XXX` 天生共享声明，多块并存是正常的；具名对象撞名才是真冲突
        if same and not decl.startswith("unnamed"):
            raise Fail("%s：同名对象已存在且内容不同 —— %s（新版官方可能新增了同名对象，"
                       "必须人工裁定后再注入）" % (rel, decl))
        pos = None
        for i, u in enumerate(new_units):
            if u["decl"] == add.get("after") and u["sha"] == add.get("after_sha"):
                pos = i + 1 + add.get("offset_after", 0)
                break
        if pos is None:
            for i, u in enumerate(new_units):
                if u["decl"] == add.get("before") and u["sha"] == add.get("before_sha"):
                    pos = i - add.get("offset_before", 0)
                    break
        if pos is None:
            pos = len(new_units)          # 两侧锚点都没了 → 追加到末尾（报告里会体现）
        pos = max(0, min(pos, len(new_units)))
        nu = {"decl": decl, "lines": add["lines"],
              "body": "\n".join(add["lines"]), "sha": body_sha}
        new_units.insert(pos, nu)
        st["add"] += 1

    # 3) 删除对象（默认不做，只报）
    for d in entry.get("del_units", []):
        hit = [u for u in new_units if u["decl"] == d["decl"] and u["sha"] == d["sha256"]]
        for u in hit:
            new_units.remove(u)
        st["del"] += len(hit)

    out = []
    for u in new_units:
        out.extend(u["lines"])
    # 收尾行（最后一个对象之后的注释/模板声明等）：**目标基线有就用目标的**。
    # ★ 旧实现无条件用 manifest 里的 tail，而 manifest 的 tail 是从旧 Mod 抓的 ——
    #   旧 Mod 里若某段内容被误当成「新增对象的前导行」吃掉了，tail 就是空的，
    #   于是新版基线新增的整段官方内容被清空（实测丢了 template FXFiring_18，
    #   29 条 Unknown class 报错）。只有目标 tail 为空时才回退到 manifest。
    tail = doc.tail if doc.tail else entry.get("tail", [])
    # 尾部的**纯空行**不参与拼接：改由「结尾换行签名」统一补。
    # ★ 否则同一份内容会有两个固定点（`...)\n` 与 `...)\n\n`），注入到纯净树和
    #   二次注入各落一个，等价性验收永远差一行（实测 MissileCarriageDepiction.ndf）。
    while tail and not tail[-1].strip():
        tail = tail[:-1]
    out.extend(tail)
    sep = "\r\n" if doc.eol == "CRLF" else "\n"
    body = sep.join(out).rstrip("\r\n")
    # 结尾换行数量跟随**目标文件**（0/1/2…），保证「重建 == 原样」可判定
    flat = text.replace("\r\n", "\n")
    n_nl = len(flat) - len(flat.rstrip("\n"))
    new_text = body + sep * n_nl
    data = new_text.encode("utf-8")

    st["noop"] = (new_text == text)
    if not dry and not st["noop"]:
        with open(target_path, "wb") as f:
            f.write(data)
    if log is not None:
        log.append((rel, len(data), st))
    return len(data), st


def apply_whole_file(entry, target_path, blob_dir, dry=False):
    rel = entry["path"]
    blob = os.path.join(blob_dir, entry["blob"])
    if not os.path.exists(blob):
        raise Fail("%s：blob 缺失 %s" % (rel, blob))
    data = open(blob, "rb").read()
    got = hashlib.sha256(data).hexdigest()
    if got != entry["sha256"]:
        raise Fail("%s：blob sha 不符（%s != %s）" % (rel, got[:16], entry["sha256"][:16]))
    if os.path.exists(target_path):
        cur = open(target_path, "rb").read()
        if hashlib.sha256(cur).hexdigest() == got:
            return len(data), "skip"
    if not dry:
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "wb") as f:
            f.write(data)
    return len(data), "write"


# ------------------------------------------------------------------ main
def apply_manifest(manifest, target_root, dry=False, only=None, verbose=True, retarget=None):
    blob_dir = os.path.join(os.path.dirname(manifest.get("_path", "")), "blobs")
    if not os.path.isdir(blob_dir):
        blob_dir = os.path.join(HERE, "manifest", "blobs")
    logs, errors = [], []
    counts = {"ndf": 0, "whole": 0, "del": 0, "skip": 0, "written": 0, "retargeted": 0}
    if retarget is None:
        retarget = {}
        for c in retarget_candidates(manifest):
            if os.path.exists(c):
                retarget = load_retarget(c)
                break
    rm = retarget
    for entry in manifest["files"]:
        rel = entry["path"]
        if only and only not in rel:
            continue
        # 重定向只在「目标树里老路径不存在、新路径存在」时生效：
        # 注入回旧基线（自洽性验收）时老文件在，就不该重定向。
        target_rel = rel
        if rel in rm and not os.path.exists(os.path.join(target_root, rel.replace("/", os.sep))) \
                and os.path.exists(os.path.join(target_root, rm[rel].replace("/", os.sep))):
            target_rel = rm[rel]
            counts["retargeted"] += 1
        tp = os.path.join(target_root, target_rel.replace("/", os.sep))
        try:
            if entry["kind"] == "deleted":
                if os.path.exists(tp) and not dry:
                    os.remove(tp)
                counts["del"] += 1
            elif entry["kind"] == "whole_file":
                _, how = apply_whole_file(entry, tp, blob_dir, dry=dry)
                counts["whole"] += 1
                if how == "skip":
                    counts["skip"] += 1
                else:
                    counts["written"] += 1
            elif entry["kind"] == "ndf":
                _, st = apply_ndf(entry, tp, dry=dry, log=logs)
                counts["ndf"] += 1
                if st.get("noop"):
                    counts["skip"] += 1
                else:
                    counts["written"] += 1
                if verbose:
                    print("  %-70s +%-3d ~%-3d(跳过 %d)%s"
                          % ((rel.replace("GameData/Generated/", "") +
                              ("  →  %s" % target_rel.split("/")[-1] if target_rel != rel else "")),
                             st["add"], st["op_applied"], st["op_skip"],
                             ("  行尾归正 %s" % st["eol"]) if st["eol"] else ""))
            else:
                errors.append("%s：未知 kind %s" % (rel, entry["kind"]))
        except Fail as e:
            errors.append(str(e))
    return counts, errors, logs


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, help="目标 Mod 根目录（含 GameData/）")
    ap.add_argument("--manifest", required=True, help="manifest.json 路径")
    ap.add_argument("--only", default=None)
    ap.add_argument("--retarget", default=None,
                    help="改名重定向表；默认取 manifest 同目录的 retarget.json")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)

    m = load_manifest(a.manifest)
    m["_path"] = a.manifest
    print("manifest : %s" % a.manifest)
    print("基线 sha : %s" % m["base_zip_sha256"])
    print("目标     : %s%s" % (a.target, "（dry-run，不写盘）" if a.dry else ""))
    print()
    counts, errors, logs = apply_manifest(m, a.target, dry=a.dry, only=a.only,
                                         retarget=None if a.retarget is None
                                         else load_retarget(a.retarget))
    print()
    print("结果：ndf %d / 整份 %d / 删除 %d / 已是目标态 %d / 实际写盘 %d / 重定向 %d"
          % (counts["ndf"], counts["whole"], counts["del"], counts["skip"],
             counts["written"], counts["retargeted"]))
    if errors:
        print("\n[FAIL] %d 条：" % len(errors))
        for e in errors[:20]:
            print("  - %s" % e)
        sys.exit(1)
    print("RESULT PASS")


if __name__ == "__main__":
    main()
