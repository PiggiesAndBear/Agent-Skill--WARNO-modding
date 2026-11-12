# modupgrade —— 游戏大版本更新后的 Mod 迁移工具

> 完整原理与实测记录见 `../../references/28-mod-update.md`。
> 一句话：**不要跑官方 `UpdateMod.bat`**（实测静默丢掉 82/309 个自建对象），
> 用这里的对象级改动包重放。

## 安装即用

不需要安装，纯标准库。入口：

```bash
python modupgrade.py --help
```

## 六个子命令

| 子命令 | 干什么 | 关键参数 |
|---|---|---|
| `export` | 旧基线 + 当前 Mod → 对象级改动包 | `--base` 旧 base.zip、`--mod`、`--out` |
| `apply` | 把改动包注入目标树 | `--target`、`--manifest`、`--dry`、`--only` |
| `lock` | 身份锁 / 撞车复检 | `--mod`、`--out`、`--check <新 base.zip>` |
| `nsaudit` | 命名空间审计（`$/NS/Name` 前缀是否搬家） | `--mod`、`--base`、`--manifest`、`--fix` |
| `selftest` | 等价性：纯净新基线 + 注入 == 当前树 | `--mod`、`--base`、`--manifest`、`--tmp` |
| `assemble` | 一条龙拼装（清点→移树→铺基线→搬回→换代→注入） | `--mod`、`--new-base`、`--old-base`、`--manifest` |

## 典型一次完整迁移

```bash
SK=<skill>/scripts/modupgrade
M="D:/steam/steamapps/common/WARNO/Mods/MyMod"
B="D:/steam/steamapps/common/WARNO/Mods/ModData/base.zip"      # 新版
OB="$M/新版本迁移/base(old).zip"                                 # 旧版（务必先另存）
MF="<工作区>/upgrade/manifest"

python $SK/modupgrade.py export  --base "$OB" --mod "$M" --out "$MF"
python $SK/modupgrade.py lock    --mod "$M" --out "$MF/id_lock.json" --check "$B"
python $SK/modupgrade.py nsaudit --mod "$M" --base "$B" --manifest "$MF/manifest.json"
python $SK/modupgrade.py assemble --mod "$M" --new-base "$B" --old-base "$OB" \
                                  --manifest "$MF/manifest.json"
python $SK/modupgrade.py selftest --mod "$M" --base "$B" --manifest "$MF/manifest.json"
# 然后：genmod_guard.py 编译 → 实机验收
```

## 改动包目录结构

```
manifest/
├── manifest.json     # 索引：文件级 + 对象级改动
├── blobs/            # whole_file 的正文（新增文件 / CSV），按 sha 命名
├── retarget.json     # （手写，可选）文件改名映射，放 manifest/ 的**同级**
└── id_lock.json      # lock 子命令产出
```

`retarget.json` 例：

```json
{ "GameData/Generated/Gameplay/Gfx/UniteDescriptor.ndf":
  "GameData/Generated/Gameplay/TacticalUnits.ndf" }
```

## 三条容易踩的

1. **`retarget.json` 与 manifest 目录同级**，不是里面；工具会在同级 / 上一级 / 当前目录三处找。
2. `assemble` 会把旧树移到 `<Mod 的父目录>/_backup_<名字>_<日期>`，**故意放在 `Mods/` 之外**——
   放里面会被游戏列成一个坏 Mod。
3. `selftest` 才是这套流程的自证：它若 0 差异，就说明「树 = 基线 + 改动包」；
   差异若只落在文件末尾空行，看 `28-mod-update.md §6` 第 8 条。
