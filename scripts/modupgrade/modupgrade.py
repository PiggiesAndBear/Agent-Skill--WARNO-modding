#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""modupgrade —— 游戏大版本更新后，把 Mod 迁到新基线的工具集（子命令分发）。

为什么需要它：官方 `UpdateMod.bat` 是**行级 diff3**，对本项目这种「几十个对象分散在
八十万行里」的 Mod 会静默丢对象（实测 309 个自建对象丢 82 个、`UniteDescriptor.ndf`
被整份删除，且只报 4 个冲突）。本工具改用**对象级**定位，抗版本漂移。

子命令一览（详细用法与实机验证记录见 references/28-mod-update.md）：

  export    旧基线 + 当前 Mod → 对象级改动包
            --base <旧 base.zip> --mod <Mod> --out <目录>

  apply     把改动包注入目标树（先 --dry）
            --target <目标 Mod> --manifest <manifest.json> [--only 子串] [--dry]

  lock      身份锁 / 撞车复检（UnitId / GUID / NameToken / BlackHoleKey / MimeticName）
            --mod <Mod> --check <新版 base.zip>     # 只复检，不写锁
            --mod <Mod> --out <id_lock.json>        # 建锁

  nsaudit   命名空间审计：我们的 `$/NS/Name` 引用是否与官方前缀一致
            --mod <Mod> --base <新版 base.zip> --manifest <manifest.json> [--fix]

  selftest  等价性验收：纯净新基线 + 注入  ==  当前树（逐字节）
            --mod <Mod> --base <新版 base.zip> --manifest <manifest.json>

  assemble  一条龙：清点自有文件 → 旧树移出 Mods → 解包新基线 → 搬回自有 →
            换 base.zip → 注入 → 断言
            --mod <Mod> --new-base <新 base.zip> --old-base <旧 base.zip> --manifest <...>

典型顺序（升级当天）：
    python modupgrade.py nsaudit  ...        # 先看命名空间有没有搬家
    python modupgrade.py lock     ... --check
    python modupgrade.py assemble ...        # 一条命令重建整棵树
    python modupgrade.py selftest ...        # 证明「树 == 基线 + 改动包」
    <genmod_guard.py 编译>
"""
import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SUBS = {
    "export":   "manifest_export",
    "apply":    "manifest_apply",
    "lock":     "id_lock",
    "nsaudit":  "ns_audit",
    "selftest": "selftest_newbase",
    "assemble": "assemble",
}


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        print("可用子命令：" + " / ".join(SUBS))
        return 0
    cmd = argv[0]
    if cmd not in SUBS:
        print("[FAIL] 未知子命令 %r；可用：%s" % (cmd, " / ".join(SUBS)))
        return 2
    mod = importlib.import_module(SUBS[cmd])
    try:
        return mod.main(argv[1:]) or 0
    except SystemExit as e:            # 子模块用 sys.exit 报结果，透传
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)


if __name__ == "__main__":
    sys.exit(main())
