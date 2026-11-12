#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第四步 · 拼装完整 Mod：新版基线 + 自有资产 + 注入改动包。

【原理】
升级后的 Mod 目录 = 新版官方基线（base.zip 解包） + 我们自己的文件（基线里没有的）
                     + 改动包注入（新增/改写对象）。

三者边界严格按 base.zip 的条目名单判定：
  · 在 base.zip 名单里      → 必须用新版内容（旧版是过期快照）
  · 不在 base.zip 名单里    → 是我们的自有文件（自建 3D 资产 / 自建 ndf / 本地化 CSV），
                              必须原样搬回，否则模型、卡面、单位名全丢
  · 脚本备份（*.bak* 等）  → 一律丢弃（实测 280 个占 1.1 GB，纯垃圾）

【操作】按 §1→§6 顺序执行；每一步都有断言，失败即停，不做半成品。
【验收】§7 打印文件数、体积、关键对象存在性，交给 verify 脚本做断言式检查。
"""
import argparse
import os
import re
import shutil
import sys
import time
import zipfile

MOD = None
NEWZ = None
OLDZ = None
OLDROOT = None
MANIFEST = None

# 脚本备份/中间产物：不进新树
RE_JUNK = re.compile(
    r"(\.bak|\.orig$|\.old$|\.before_|\.tmp$|\.swp$|~$"
    r"|^\..*\.swp$)"
)
JUNK_DIRS = {"__pycache__"}


def zip_names(path):
    z = zipfile.ZipFile(path)
    names = {n.replace("\\", "/") for n in z.namelist() if not n.endswith("/")}
    z.close()
    return names


def own_files(src_root):
    """从 src_root 挑出「真正属于我们」的文件。

    ★ 判据必须是「新旧两份基线里都没有」。只跟新版比会把**官方删掉/改名的文件**
      当成我们的搬回来 —— 实测 65 个（含 28 MB 旧 UniteDescriptor.ndf），
      而它一旦存在，路径重定向就不触发，注入会全部打在过期旧文件上。
    """
    base_new = zip_names(NEWZ)
    base_old = zip_names(OLDZ)
    out, junk, deprecated = [], 0, []
    for top in ("GameData", "CommonData"):
        root = os.path.join(src_root, top)
        if not os.path.isdir(root):
            continue
        for dp, dns, fs in os.walk(root):
            dns[:] = [d for d in dns if d not in JUNK_DIRS]
            for f in fs:
                p = os.path.join(dp, f)
                rel = os.path.relpath(p, src_root).replace("\\", "/")
                if rel in base_new:
                    continue          # 新版基线有 → 用新版
                if RE_JUNK.search(f):
                    junk += 1
                    continue
                if rel in base_old:
                    deprecated.append(rel)   # 官方已删/改名 → 丢弃
                    continue
                out.append((rel, os.path.getsize(p)))
    return out, junk, len(base_new), deprecated


def main(argv=None):
    ap = argparse.ArgumentParser(description="一条龙拼装：新基线 + 自有文件 + 注入")
    ap.add_argument("--mod", required=True, help="目标 Mod 根目录")
    ap.add_argument("--new-base", required=True, help="新版 base.zip")
    ap.add_argument("--old-base", required=True, help="旧版 base.zip（换代前那份）")
    ap.add_argument("--manifest", required=True, help="manifest.json 路径")
    ap.add_argument("--backup-root", default=None,
                    help="旧树备份目录（默认 <Mod 的父目录>/_backup_<Mod名>_<日期>）")
    a = ap.parse_args(argv)
    global MOD, NEWZ, OLDZ, OLDROOT, MANIFEST
    MOD, NEWZ, OLDZ, MANIFEST = a.mod, a.new_base, a.old_base, a.manifest
    if a.backup_root:
        OLDROOT = a.backup_root
    else:
        OLDROOT = os.path.join(os.path.dirname(os.path.abspath(MOD)),
                               "_backup_" + os.path.basename(os.path.abspath(MOD)) + "_"
                               + time.strftime("%Y%m%d"))
    if not os.path.isdir(MOD):
        sys.exit("[FAIL] Mod 目录不存在：%s" % MOD)
    if not os.path.exists(NEWZ):
        sys.exit("[FAIL] 新版 base.zip 不存在：%s" % NEWZ)
    if os.path.isdir(OLDROOT):
        sys.exit("[FAIL] 旧树备份目录已存在，说明上次没跑完：%s\n"
                 "        先人工确认后删除，避免覆盖唯一副本。" % OLDROOT)

    # ---------------------------------------------------------------- §1 清点
    print("=" * 78)
    print("§1 清点自有文件")
    own, junk, n_base, deprecated = own_files(MOD)
    print("  新版基线条目 %d 个文件" % n_base)
    print("  自有文件 %d 个，共 %.1f MB" % (len(own), sum(s for _, s in own) / 1048576))
    print("  丢弃脚本备份 %d 个 / 官方已删或改名 %d 个" % (junk, len(deprecated)))
    if deprecated:
        for p in sorted(deprecated)[:5]:
            print("    - %s" % p)
        if len(deprecated) > 5:
            print("    … 另 %d 个" % (len(deprecated) - 5))
    if len(own) < 300:
        sys.exit("[FAIL] 自有文件只有 %d 个，明显偏少（正常 600+），中止" % len(own))

    # ---------------------------------------------------------------- §2 迁移旧树
    print("\n§2 旧树整体移出（保留为唯一回滚副本）")
    os.makedirs(OLDROOT, exist_ok=True)
    for d in ("GameData", "CommonData"):
        src = os.path.join(MOD, d)
        if os.path.isdir(src):
            shutil.move(src, os.path.join(OLDROOT, d))
            print("  %-12s → %s" % (d, OLDROOT))
    assert not os.path.exists(os.path.join(MOD, "GameData"))

    # ---------------------------------------------------------------- §3 铺新基线
    print("\n§3 解包新版基线")
    z = zipfile.ZipFile(NEWZ)
    z.extractall(MOD)
    z.close()
    got = 0
    for top in ("GameData", "CommonData"):
        for _, _, fs in os.walk(os.path.join(MOD, top)):
            got += len(fs)
    print("  解出 %d 个文件" % got)
    if abs(got - n_base) > 5:
        sys.exit("[FAIL] 解出 %d 个，基线名单 %d 个，差异异常" % (got, n_base))

    # ---------------------------------------------------------------- §4 搬自有文件
    print("\n§4 搬回自有文件")
    n_copy, n_bytes = 0, 0
    for rel, size in own:
        src = os.path.join(OLDROOT, rel.replace("/", os.sep))
        dst = os.path.join(MOD, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        n_copy += 1
        n_bytes += size
    print("  搬回 %d 个，%.1f MB" % (n_copy, n_bytes / 1048576))

    # ---------------------------------------------------------------- §5 base.zip 换代
    print("\n§5 base.zip 换代")
    old_base = os.path.join(MOD, "base.zip")
    keep = OLDZ
    if not os.path.exists(keep):
        sys.exit("[FAIL] 旧 base 备份不见了：%s" % keep)
    shutil.copy2(keep, old_base)
    shutil.copy2(NEWZ, os.path.join(MOD, "base.zip"))
    import hashlib
    h = hashlib.sha256(open(os.path.join(MOD, "base.zip"), "rb").read()).hexdigest()
    print("  base.zip → %s… (%d B)" % (h[:16], os.path.getsize(os.path.join(MOD, "base.zip"))))

    # ---------------------------------------------------------------- §6 注入
    print("\n§6 注入改动包")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import manifest_apply as A
    m = A.load_manifest(MANIFEST)
    counts, errors, logs = A.apply_manifest(m, MOD, dry=False, verbose=False)
    print("  " + " / ".join("%s=%d" % (k, v) for k, v in counts.items()))
    if errors:
        for e in errors:
            print("  ✗ %s" % e)
        sys.exit("[FAIL] 注入有 %d 个错误" % len(errors))
    # ★ 重定向必须触发：改动包里 27 个新增单位挂在 UniteDescriptor.ndf 上，
    #   新版已改名 TacticalUnits.ndf。没重定向就说明旧文件还活着，注入打错了地方。
    if counts.get("retargeted", 0) < 1:
        sys.exit("[FAIL] 路径重定向未触发（retargeted=%d）——旧 UniteDescriptor.ndf 可能又"
                 "被搬回来了" % counts.get("retargeted", 0))

    # ---------------------------------------------------------------- §6b 断言
    print("\n§6b 关键对象断言")
    ok = True
    tu = os.path.join(MOD, "GameData/Generated/Gameplay/TacticalUnits.ndf")
    txt = open(tu, "rb").read().decode("utf-8", "replace")
    for name in ("RAH66_US", "T90A_SOV", "LOSAT_US", "M752_Lance_US",
                 "TU22_KH22", "Ka58_SOV", "MiG_29M_SOV", "FPV_AT4_US"):
        n = txt.count("Descriptor_Unit_%s is" % name)
        print("  %-14s ×%d" % (name, n))
        ok = ok and n >= 1
    # 官方删除/改名的文件不得复活
    back = [p for p in deprecated if os.path.exists(os.path.join(MOD, p.replace("/", os.sep)))]
    print("  已删文件复活 %d 个" % len(back))
    ok = ok and not back
    if not ok:
        sys.exit("[FAIL] 断言不通过")

    # ---------------------------------------------------------------- §7 汇总
    print("\n§7 汇总")
    total = 0
    for top in ("GameData", "CommonData"):
        for _, _, fs in os.walk(os.path.join(MOD, top)):
            total += len(fs)
    print("  Mod 内文件总数 %d" % total)
    tu = os.path.join(MOD, "GameData/Generated/Gameplay/TacticalUnits.ndf")
    print("  TacticalUnits.ndf %s (%.1f MB)"
          % ("存在" if os.path.exists(tu) else "缺失", os.path.getsize(tu) / 1048576))
    print("  旧树保留在 %s（确认无误后可删）" % OLDROOT)
    print("\nRESULT PASS")


if __name__ == "__main__":
    main()
