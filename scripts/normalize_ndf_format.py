# -*- coding: utf-8 -*-
"""还原被「文本模式写入」污染过的 NDF 排版。

现象
----
文件里每行代码之间都空了一行，体积异常大。成因：某脚本用文本模式
`open(p, "w")` / `Path.write_text()` 写入一个已含 `\\r\\n` 的字符串，
Windows 下默认 newline 转换把 `\\n` 再翻成 `\\r\\n`，得到 `\\r\\r\\n`；
下一次读写时裸 `\\r` 被当成行尾 → 变成真正的空行。

规范
----
基准是 `<WARNO>/Mods/ModData/base.zip`（官方 Mod 模板，4687 个 .ndf 全是纯 LF）：
  * 行尾一律 LF，无 BOM
  * 第 1 行 `// Ne pas éditer...` 后留 1~2 空行（DivisionRules 是 1，其余是 2）
  * 之后整个文件紧凑：对象之间、字段之间零空行
  * 以 `)\\n` 结尾

用法
----
    # 先看哪些文件有问题
    python normalize_ndf_format.py --mod "D:/.../Mods/MyMod" --dry

    # 真跑（写前自动 .bak_normfmt_<ts>）
    python normalize_ndf_format.py --mod "D:/.../Mods/MyMod"

    # 指定官方模板，做共同前缀复核（更有说服力）
    python normalize_ndf_format.py --mod "..." --base "D:/.../Mods/ModData/base.zip"
"""
import argparse, os, re, shutil, sys, time, zipfile

SKIP_EXT = (".bak", ".bin", ".png", ".jpg", ".dds", ".tga", ".fbx", ".blend", ".zip")
DEFAULT_HEAD_BLANK = 2
HEAD_BLANK_OVERRIDE = {"divisionrules.ndf": 1}

# 判定「被污染」：每行之间都空了一行 → 空行数与非空行数同量级。
# 正常文件（含 Fx/ 那种带分组空行的）空行占比只有百分之几，不会到这里。
# 每行之间都空一行时，空行数 ≈ 非空行数（实测 100%）。取 0.8 作阈值，
# 既能命中整文件污染，又不会碰到 Fx/ 那种几个分组空行、或 500 字节小文件。
POLLUTE_RATIO = 0.8
POLLUTE_MIN_LINES = 20


def is_polluted(b):
    blanks, nonbanks = stats(b)
    if nonbanks < POLLUTE_MIN_LINES:
        return False
    return blanks >= nonbanks * POLLUTE_RATIO


def detect_eol(b):
    crlf = b.count(b"\r\n")
    if crlf and b.count(b"\r") == crlf and b.count(b"\n") == crlf:
        return "CRLF"
    if crlf == 0 and b.count(b"\r") == 0:
        return "LF"
    return "MIX"


def stats(b):
    lines = b.decode("utf-8", "replace").replace("\r\n", "\n").split("\n")
    return sum(1 for l in lines if l.strip() == ""), sum(1 for l in lines if l.strip())


def normalize(b, head_blank):
    t = b.decode("utf-8")
    if t.startswith("\ufeff"):
        t = t[1:]
    body = [l for l in t.replace("\r\n", "\n").split("\n") if l.strip() != ""]
    if not body:
        return b""
    out = [body[0]] + [""] * head_blank + body[1:]
    return ("\n".join(out) + "\n").encode("utf-8")


def nonblank(b):
    t = b.decode("utf-8").replace("\r\n", "\n")
    return [l for l in t.split("\n") if l.strip() != ""]


def head_blank_for(name, base_zip, rel_zip):
    if name.lower() in HEAD_BLANK_OVERRIDE:
        return HEAD_BLANK_OVERRIDE[name.lower()]
    if base_zip and rel_zip in base_zip.namelist():
        b = base_zip.read(rel_zip)
        lines = b.decode("utf-8", "replace").split("\n")
        # 第 1 行注释之后连续空行的数量
        n = 0
        for l in lines[1:]:
            if l.strip() == "":
                n += 1
            else:
                break
        if 0 < n <= 3:
            return n
    return DEFAULT_HEAD_BLANK


def common_prefix_len(a, b):
    i = 0
    while i < len(a) and i < len(b) and a[i] == b[i]:
        i += 1
    return i


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mod", required=True, help="Mod 根目录")
    ap.add_argument("--base", help="官方模板 base.zip，用于头部空行与共同前缀复核")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--all", action="store_true", help="不等判定，强制处理所有 ndf")
    args = ap.parse_args()

    mod = os.path.abspath(args.mod)
    gd = os.path.join(mod, "GameData")
    if not os.path.isdir(gd):
        print("[中止] 找不到 %s/GameData" % mod)
        return 5

    base_zip = zipfile.ZipFile(args.base) if args.base and os.path.exists(args.base) else None
    ts = time.strftime("%Y%m%d_%H%M%S")
    todo, ok_skip = [], 0

    for root, _, files in os.walk(gd):
        for fn in files:
            if not fn.lower().endswith(".ndf") or any(s in fn.lower() for s in SKIP_EXT):
                continue
            p = os.path.join(root, fn)
            b = open(p, "rb").read()
            eol = detect_eol(b)
            blanks, nonbanks = stats(b)
            if args.all or is_polluted(b):
                todo.append((p, b, eol, blanks))
            else:
                ok_skip += 1

    print("扫描完成：需处理 %d 个，已是规范格式 %d 个" % (len(todo), ok_skip))
    if not todo:
        return 0

    failed = 0
    for p, b, eol, blanks in todo:
        rel = os.path.relpath(p, mod).replace(os.sep, "/")
        rel_zip = rel
        hb = head_blank_for(os.path.basename(p), base_zip, rel_zip)
        new = normalize(b, hb)
        same = nonblank(b) == nonblank(new)
        print("\n%s" % rel)
        print("  eol=%s 空行=%d  %d -> %d (%+d)  非空行一致=%s"
              % (eol, blanks, len(b), len(new), len(new) - len(b), same))
        if not same:
            print("  !! 非空行发生变化，拒绝写入")
            failed += 1
            continue
        if new.startswith(b"\xef\xbb\xbf"):
            print("  !! 出现 BOM，拒绝写入")
            failed += 1
            continue
        if base_zip and rel_zip in base_zip.namelist():
            bl = base_zip.read(rel_zip).decode("utf-8", "replace").split("\n")
            nl = new.decode("utf-8").split("\n")
            cp = common_prefix_len(bl, nl)
            print("  与 base.zip 共同前缀 %d 行" % cp)
        if args.dry:
            continue
        bak = p + ".bak_normfmt_%s" % ts
        if not os.path.exists(bak):
            shutil.copy2(p, bak)
        with open(p, "wb") as f:          # 二进制写，绝不触发换行转换
            f.write(new)
        print("  已写回，备份 %s" % os.path.basename(bak))

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
