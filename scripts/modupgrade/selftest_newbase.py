#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新基线等价性验收：纯净 base.zip + 注入  ==  当前 Mod 树（ndf 部分逐字节）。

旧版 `selftest_roundtrip` 是「旧基线 + 注入 == 旧树」，树换到新基线后必须换成这条口径，
否则会把「新版官方内容和我们不一样」误判成缺陷。
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import manifest_apply as A

MOD = None
BASE = None
TMP = os.path.join(HERE, "_verify_tree")


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description="等价性：纯净新基线 + 注入 == 当前树（逐字节）")
    ap.add_argument("--mod", required=True)
    ap.add_argument("--base", required=True, help="新版 base.zip")
    ap.add_argument("--manifest", required=True, help="manifest.json 路径")
    ap.add_argument("--tmp", default=None, help="解包临时目录（默认 <脚本目录>/_verify_tree）")
    a = ap.parse_args(argv)
    global MOD, BASE, TMP
    MOD, BASE = a.mod, a.base
    if a.tmp:
        TMP = a.tmp
    if os.path.isdir(TMP):
        shutil.rmtree(TMP)
    os.makedirs(TMP)
    zipfile.ZipFile(BASE).extractall(TMP)
    shutil.copy2(BASE, os.path.join(TMP, "base.zip"))

    m = A.load_manifest(a.manifest)
    counts, errors, _ = A.apply_manifest(m, TMP, dry=False, verbose=False)
    print("注入：%s" % " / ".join("%s=%d" % kv for kv in counts.items()))
    if errors:
        for e in errors:
            print("  ✗ %s" % e)
        print("RESULT FAIL（注入报错）")
        return 1

    # 逐字节比对 ndf（自有资产不参与）
    bad, only_tmp, checked = [], [], 0
    for top in ("GameData", "CommonData"):
        for dp, _, fs in os.walk(os.path.join(TMP, top)):
            for f in fs:
                if not f.endswith(".ndf"):
                    continue
                p = os.path.join(dp, f)
                rel = os.path.relpath(p, TMP).replace("\\", "/")
                q = os.path.join(MOD, rel.replace("/", os.sep))
                if not os.path.exists(q):
                    only_tmp.append(rel)
                    continue
                checked += 1
                if sha(p) != sha(q):
                    bad.append(rel)

    # 反向：树里有没有注入产物缺失的 ndf
    only_mod = []
    for top in ("GameData", "CommonData"):
        for dp, _, fs in os.walk(os.path.join(MOD, top)):
            for f in fs:
                if not f.endswith(".ndf"):
                    continue
                rel = os.path.relpath(os.path.join(dp, f), MOD).replace("\\", "/")
                if not os.path.exists(os.path.join(TMP, rel.replace("/", os.sep))):
                    only_mod.append(rel)

    print("比对 %d 个 ndf：不一致 %d / 只在注入侧 %d / 只在树里 %d"
          % (checked, len(bad), len(only_tmp), len(only_mod)))
    for r in bad[:10]:
        print("  ✗ 不一致 %s" % r)
    for r in only_mod[:10]:
        print("  ✗ 只在树里 %s" % r)
    ok = not bad and not only_tmp and not only_mod
    print("\nRESULT %s" % ("PASS" if ok else "FAIL"))
    if ok:
        shutil.rmtree(TMP, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
