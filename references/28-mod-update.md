# 28 · Mod 更新专题（游戏大版本升级后的迁移）

> **状态：已验证手册**。2026-11-13 WARNO 更新后，本项目（27 个自建单位 / 335 个新增对象 /
> 66 个改动文件）用本节流程完成迁移，`Mod Generation Success`，实机通过。
> 所有数字都是这一轮实测值，不是推算。

---

## 0. 什么时候翻这一节

| 你的处境 | 结论 |
|---|---|
| 游戏大更新后，Mod 一加载就崩 / 报一堆 `File not found` | 走本节 |
| 你在犹豫「要不要跑官方 `UpdateMod.bat`」 | **不要**，见 §1.2 实测 |
| 已经改了几十个对象、几百行，想迁到新基线 | 走本节，对象级重放 |
| 只是改了几个数值、没有任何新增对象 | `UpdateMod.bat` 可以用，但不必要 |

**一句话**：官方那套是**行级三方合并**，对「改动分散在几十万行里」的 Mod 会静默丢对象；
本节的工具是**对象级重放**，不依赖行号，抗版本漂移。

---

## 1. 【原理】为什么不能跑 `UpdateMod.bat`

### 1.1 官方机制到底做了什么

`Mods/Utils/Scripts/UpdateMod.py` 的流程：

1. 把新版 `ModData/base.zip` 解到 `Mod/.base/`；
2. 逐个 `*.ndf` 调 `diff3.merge(new=新版, old=旧版, mod=你的)`；
3. 冲突就打印清单 + `input()` 等你按回车；
4. 收尾：删 `Gen/`、把 `base.zip` 换成新版、留一份 `GameData_backup`。

关键点：**它只合并 `.ndf`**，`Assets/`（模型贴图）、`Localisation/*.csv` 不在合并范围 —— 自建资产是安全的。

### 1.2 实测后果（本项目，2026-11-12 真跑过一次，已完整回滚）

| 指标 | 结果 |
|---|---|
| 耗时 / 退出码 | 25 s / **0**，自报 `Mod updated successfully!` |
| ndf 总数 | 4577 → 4931（改 435 / 未变 4077 / **删 65** / 新增 419） |
| 报告的冲突 | **只有 4 个文件、6 处 `<<<<<<<`** |
| 自建对象存活 | **227 / 309（丢 82 个）** |
| `UniteDescriptor.ndf` | **被整份删除**（新版改名 `TacticalUnits.ndf`，被判「文件废弃」→ `os.remove`），日志里**一个字都没提** |
| `WeaponDescriptor.ndf` | 你我 20 个自建武器 **0/20**，结果与新基线**逐字节相同** |
| `AmmunitionMissiles.ndf` | 文件被写坏：325 个对象（应 219）、111 个重名、残留 1 处冲突标记 |
| 悬空引用 | 师注册、挂架、描绘算子还在，**但单位和武器没了** |

**这是最坏的一种失败**：它不喊、不报错、退出码 0，坏在「单位和它的一堆注册各行其是」。

### 1.3 为什么会退化

`diff3.py` 判定冲突的依据是**行区间是否重叠/邻接**（源码里 `while d2[k][0][1] <= hi + 1` 把相邻改动**链式**连起来）。
本项目的 27 个单位按字母序散布在 71 万行里，于是整份文件被判成**一个区间、覆盖 100% 行**：

| 文件 | `diff3.merge` 返回 |
|---|---|
| `UniteDescriptor.ndf` | **1 个区间**，`cmd='A'`，`orig 1..711 160`（100%），`body` 行数 ≈ 三份之和 |
| `DivisionRules.ndf` | 同样退化（122 752 行 ≈ 三份之和） |
| `DeckSerializer` / `ButtonTexturesUnites` | 纯末尾追加 → 0 冲突，能自动合并 |

四档插入位置对照（末尾 / 1 处 / 3 处 / 30 处均匀）结果**完全一致** —— 说明退化与「官方怎么改」无关，
是由**我们这边的改动密度**决定的。

### 1.4 对象级注入为什么抗漂移

NDF 顶层只有三类边界，按它切块就不需要行号：

| 形态 | 例子 | 定位方式 |
|---|---|---|
| `export X is T` | `export Descriptor_Unit_RAH66_US is TEntityDescriptor` | 对象名 |
| `X is T`（无 export） | `Ammo_AGM_AGM114A_RAH66_HE is TAmmunitionDescriptor` | 对象名 |
| `unnamed T` / 共享声明 | `unnamed TDeckSerializerEntries`、`DepictionOperator_*`| 内容相似度 + 见证行 |

改动包里存三样东西：

- `add_units`：整块新增对象（落点用**前后邻居声明**定位，附带真实索引偏移）；
- `patch_units`：已存在对象内的行级增删改（锚点是**行内容 + 上下文**，不是行号）；
- `whole_file`：新增的独立文件 / 本地化 CSV（整份带走，正文存 `blobs/`）。

新版官方在原对象前后插多少东西都不影响命中——这就是它能跨版本的原因。

---

## 2. 【操作】五步，不可跳步

工具全在 `scripts/modupgrade/`，入口一个：

```bash
python <skill>/scripts/modupgrade/modupgrade.py <子命令> ...
```

### 2.0 备份（缺一不可，先做）

1. **旧 `base.zip` 另存**：升级成功后官方会覆盖 Mod 里那份，**共同祖先就没了**
   → 存成 `<Mod>/新版本迁移/base(old).zip`；
2. **整包备份**：`CreateModBackup.bat` 或直接 zip 一份 `GameData/`；
3. 记下旧版 sha：`sha256sum <Mod>/base.zip`（本次 `422528b6…`）。

### 2.1 判定「更新真的落地了」

```bash
sha256sum "D:/steam/steamapps/common/WARNO/Mods/ModData/base.zip"
```
与旧值不同才算更新。本次：`422528b6…`（8 291 186 B / 4564 ndf）→ `facbbab4…`（8 953 693 B / 4916 ndf）。
没变就**停在这里**，后面全是白做。

### 2.2 导出改动包（**必须是升级前那棵树**）

```bash
python modupgrade.py export \
  --base "<Mod>/新版本迁移/base(old).zip" \
  --mod  "<Mod>" \
  --out  "<工作区>/upgrade/manifest"
```

产物：`manifest.json` + `blobs/`。< 2 MB 是正常值（本项目 66 个文件 / 335 新增对象 / 91 改写 / 202 处 op → `manifest.json` **1.26 MB**，含 `blobs/` 共 1.4 MB）。
二进制资产**只记 sha256 不复制**（331 个 / 244.8 MB 原样留在 Mod 里）。

`retarget.json`（可选，手写）用于**文件改名**：键是改动包里的老路径，值是目标路径。

```json
{ "GameData/Generated/Gameplay/Gfx/UniteDescriptor.ndf":
  "GameData/Generated/Gameplay/TacticalUnits.ndf" }
```

> ⚠ `retarget.json` 放 `manifest/` 的同级目录（不是里面）。工具会在三个候选位置找。

> ⚠ **树一旦迁到新基线就不能再导**：那时 diff 会把「新版官方内容」算成你的改动
> （实测 1.26 MB → 21 MB、2490 个对象被判「改写」），且不报错。
> 工具已加警告（检测到树里有 `TacticalUnits.ndf`、而旧基线还是 `UniteDescriptor.ndf`）。

### 2.3 预检三件套（任一不过就不要往下走）

```bash
# ① 身份撞车：UnitId / GUID / NameToken / BlackHoleKey / MimeticName
python modupgrade.py lock --mod "<Mod>" --out "<manifest>/id_lock.json" --check "<新 base.zip>"

# ② 命名空间搬家（官方把对象换个目录放）
python modupgrade.py nsaudit --mod "<Mod>" --base "<新 base.zip>" --manifest "<manifest>/manifest.json"

# ③ 等价性：纯净新基线 + 注入 == 当前树（迁移完成后再跑）
python modupgrade.py selftest --mod "<Mod>" --base "<新 base.zip>" --manifest "<manifest>/manifest.json"
```

- `lock` 报撞号 → 先整体重编号（见 §4 的号段规则），**不要只改撞上的那几个**；
- `nsaudit` 报「命名空间已变」→ 加 `--fix` 一键改写（manifest + 树同时改）；
- `selftest` 只在迁移后有意义。

### 2.4 拼装（一条命令）

```bash
python modupgrade.py assemble \
  --mod "<Mod>" \
  --new-base "<ModData>/base.zip" \
  --old-base "<Mod>/新版本迁移/base(old).zip" \
  --manifest "<manifest>/manifest.json"
```

它按顺序做六件事，每步都带断言：

1. **清点自有文件**：只认「**新旧两份基线里都没有**」的文件；
2. 旧树整体移到 `Mods` **之外**（`_backup_<Mod名>_<日期>`）——放在 `Mods/` 里会被游戏列成一个坏 Mod；
3. 解包新基线；
4. 搬回自有文件；
5. `base.zip` 换代；
6. 注入改动包 + 断言（`retargeted ≥ 1`、抽样单位命中、已删文件没复活）。

> ⚠ 第 1 步的判据是本节最容易写错的地方，见 §6 第 2 条。

### 2.5 编译

```bash
python <skill>/scripts/genmod_guard.py --mod "<Mod>" --name "<Mod名>" 2400
```

必须看到 `Mod Generation Success`。新版不再自带 Python，守卫会自动回退到系统 `python3`。

---

## 3. 【验收】

### 3.1 四道闸（缺一不可）

| # | 闸 | 命令 | 通过判据 |
|---|---|---|---|
| 1 | 身份 | `lock --check` | 六项全绿，余量 ≥ 1 更安全 |
| 2 | 名称空间 | `nsaudit` | 0 条「命名空间已变」 |
| 3 | 结构 | 自写脚本或抽查 | 24 个自建对象名全在、UnitId 号段正确、Division ID 不重复、无 `<<<<<<<` |
| 4 | 等价性 | `selftest` | 「纯净基线 + 注入 == 当前树」逐字节 **0 差异** |

`selftest` 是这套流程的**唯一自证**：它证明「树 = 基线 + 改动包」，也就是「改动包里没有漏、树里没有多」。

### 3.2 编译后

- `Gen/NDF/**/*.txn`（新版格式，**不再是 `.ndfbin`**）时间戳刷新；
- 自建模型有 `Gen/PC/Mesh/**/mesh.neu3`（本项目 24 个，RAH66 215 599 B）；
- `Gen/MeshPack/**/Mesh_All.spk` 体积正常（6.9 MB）。

### 3.3 实机七问（编译全绿也不等于对）

买得到 → 存得住 → 名字对 → 模型对 → 里面有人 → 打得出 → 有火光。
本项目实机清单：单位进 REC 栏 / 三师卡数 / 武器与描绘 / 前后座飞行员 / 起落架收起不穿蒙皮 /
主旋翼只剩一大一小 / 导弹贴住挂架。

---

## 4. 定稿参数总表（2026-11-13 这次的实际取值）

| 参数 | 取值 | 怎么来的 |
|---|---|---|
| UnitId 号段 | **5022–5048**（旧 4675–4701，delta +347） | 官方新最大 5021 + 1，整体平移，不局部改 |
| Division ID | **453 / 454** | 排除我方后的最大值 452 + 1 |
| 6 个显示字段位置 | `TMountedWeaponDescriptor` 内（`Caliber` / `InterfaceWeaponTexture` / `Name` / `TraitsToken` / `TypeCategoryName` / `WeaponDescriptionToken`） | 新版从 `TAmmunitionDescriptor` 整体搬走 |
| 关键效果模块前缀 | `$/GFX/CriticalEffects/CriticalEffectModule_*` | 旧 `$/GFX/UnitConstantes/` 已废 |
| 文件改名 | `Gfx/UniteDescriptor.ndf` → `Gameplay/TacticalUnits.ndf` | 写进 `retarget.json` |
| `export` 关键字 | **仍然接受** | 27 个单位用 `export` 新增，编译通过 |
| 行尾 | **跟随目标基线**（多为 LF） | 旧 Mod 有 20 个文件被早期脚本改成 CRLF |
| 结尾换行 | **跟随目标文件签名**（0/1/2 个） | 见 §6 第 8 条 |

号段规则（两条，别只做一半）：

1. `new_unitid = old_unitid - min(ours) + (base_max + 1)`；
2. 改完必须跑 `lock --check`，且**余量 ≥ 1**（本次余量 0，恰好卡在边界，官方再加一个单位就撞）。

---

## 5. 给智能体的执行清单

### 5.1 前置检查（有一项不满足就停下问人）

- [ ] 旧 `base.zip` 已另存（`新版本迁移/base(old).zip`），且 sha 与旧版一致；
- [ ] 整包备份存在（能覆盖回滚）；
- [ ] `ModData/base.zip` 的 sha **与旧值不同**（= 更新真的落地了）；
- [ ] 游戏没在运行（编译会抢文件）；
- [ ] `python3 --version` 可用（新版游戏不再自带 Python）。

### 5.2 顺序表

| 步 | 动作 | 失败怎么办 |
|---|---|---|
| 1 | `export` 导出改动包 | 失败多半是旧 base 路径错 |
| 2 | `lock --check` | 撞号 → 整体重编号后重导 |
| 3 | `nsaudit` | 有搬家 → `--fix` 后重导 |
| 4 | `assemble` | 断言失败**不要跳过**，按报错回 §6 对照 |
| 5 | `selftest` | 有差异 → 先看是不是结尾换行/尾部空行，再查 add 落点 |
| 6 | `genmod_guard` 编译 | 弹窗原文是唯一线索，按 §6 对照 |
| 7 | 实机七问 | 按 `40-engineering.md` 的验收顺序 |

### 5.3 禁止动作

- ❌ 跑 `UpdateMod.bat` 处理有新增对象的 Mod（§1.2）；
- ❌ 修改 `GameData/Gameplay/Gfx/Units/GfxDescriptorChassis.ndf`（§7 第 2 条）；
- ❌ 用「新建同目录 ndf」绕开上一条（跨文件 `~/` 解析不到新文件里的对象）；
- ❌ 只改撞号的那几个 UnitId / 沿用旧 Division ID；
- ❌ 只跟新版基线比就判定「哪些文件是我们的」（§6 第 2 条）；
- ❌ 把 `_backup_*` / 旧树放在 `Mods/` 目录里（会被当成 Mod 列出来）；
- ❌ 「编译通过」就收工（还要过 §3.3 实机七问）。

---

## 6. 被推翻的判断与错因（8 条，全部实测）

| # | 我原本的判断 | 实际 | 错因 |
|---|---|---|---|
| 1 | 「`UpdateMod` 会整段冲突，吵得很凶」 | **只报 4 处冲突，却静默丢了 82 个对象、删掉整份 `UniteDescriptor.ndf`** | 把「冲突」当成唯一失败形态。真正危险的是**不冲突的静默丢弃**——`diff3` 在 `\n` 口径下干净合并，把 mod 侧新增内容判成「对方已删」 |
| 2 | 「自有文件 = 新版 base.zip 里没有的文件」 | 官方**删掉或改名**的 65 个文件被当成自有搬回来；旧 `UniteDescriptor.ndf` 一复活，路径重定向不触发，注入全打在过期文件上 | 漏了「旧基线里有、新版没有」这一类。判据必须是**两份基线里都没有** |
| 3 | 「`GfxDescriptorChassis.ndf` 不能改，那就新建一个同目录 ndf 放对象」 | 新建文件能编译，但**跨文件 `~/GfxDescriptorChassis_2S25` 解析不到**（对象没登记进 `$/GFX/Depiction/`） | 只验证了「能编译」，没验证「引用能解析」。改放是死路，只能放弃这个对象 |
| 4 | 「命名空间不会变，路径变了而已」 | `CriticalEffectModule_*`：`$/GFX/UnitConstantes/` → `$/GFX/CriticalEffects/`，27 个单位 × 4 类全中 | NDF 的 `$/a/b/Name` 是**逻辑命名空间**，与文件路径不绑定。必须有专门审计 |
| 5 | 「Division ID 是自增的，不会撞」 | 自建战斗群的 434 与官方 `US_101AB_solo` 撞 | 官方也在消耗同一号段。必须按「排除我方后的最大值 +1」重算 |
| 6 | 「新增对象的 `lines` 就是这个对象」 | 某个新增 FX 武器带了 **649 行**官方模板声明（`//Firing Templates` + `template FXFiring_*`） | 解析器把不认识的整段当「下一个 decl 的前导行」。导出时必须从**自身 decl** 起裁 |
| 7 | 「`tail` 用 manifest 记录的就行」 | 旧 Mod 的 tail 是空的，于是把新版新增的 `template FXFiring_18` **整段清空** → 29 条 `Unknown class` | manifest 的 tail 是**旧文件**的快照。目标基线非空时必须用目标的 |
| 8a | 「改动包随时都能补导」 | 树迁到新基线后再导，得到 **21 MB** 的错包（真值 1.26 MB），2490 个对象被判改写 | `export` 必须对**升级前**的树跑。已加自动警告，但警告不是拦截 |
| 8 | 「空行怎么处理无所谓」 | 同一份内容有**两个固定点**（`…)\n` 与 `…)\n\n`）：注入到纯净树落一个，二次注入落另一个，`selftest` 永远差一行 | 结尾空行不能进 `tail` 拼接，必须按**目标文件的结尾换行签名**统一收尾 |

---

## 7. 新版引擎（2.3.3）新增的 5 条硬约束

| # | 约束 | 表现 | 应对 |
|---|---|---|---|
| 1 | **不再自带 Python** | `Mods/Utils/Python/python.exe` 消失，`GenerateMod.py` 起不来 | 用系统 `python3`；`genmod_guard.py` 已加回退链 |
| 2 | **特定 `Gameplay/` 文件不可改** | 改 `Gameplay/Gfx/Units/GfxDescriptorChassis.ndf` 一行注释，即报 `File not found: GameData:/Gameplay/Gfx/Properties.ndf`；补空 `Properties.ndf` 又变成要 `CommonData:/Gameplay/Gfx/Units/DepictionCatalog.ndf` | 不在该文件加对象；需要不同参数就改用官方既有对象（本项目 2S25 改用 `GfxDescriptorChassis_SmallTank`） |
| 3 | **命名空间随文件搬迁** | `$/GFX/UnitConstantes/` → `$/GFX/CriticalEffects/` | `nsaudit` 每次升级跑一次 |
| 4 | **编译产物改为 `.txn`** | `Gen/NDF/GFX/Unit.txn`、`Division.txn`…（不再有 `.ndfbin`） | 验收看 `.txn` 时间戳，别去 `.ndfbin` 里找 |
| 5 | **Division / UnitId 号段被官方继续消耗** | 官方最大 UnitId 4674 → **5021**；Division ID 用到 452 | 每次升级都重算号段，不要沿用上次的值 |

---

## 8. 回滚

四档，按代价从低到高：

1. **只回滚注入**：`manifest_apply.py` 不写备份，但 `selftest` 的临时树可直接对照；
   单文件回滚从 `base.zip` 里取原文覆盖；
2. **回滚整棵树**：把 `_backup_<Mod>_<日期>` 移回 `Mods/`，`base.zip` 换回旧版；
3. **回滚到更新前**：用 `新版本迁移/BeforeUpdate.zip` 覆盖 + 删多余文件 + 换回旧 `base.zip`
   （本项目实测：4577 个 ndf **缺失 0 / 多出 0 / 不一致 0**）；
4. **重来**：旧树 → 旧 `base.zip` + `manifest` 重放，结果应与回滚前逐字节相同（`selftest` 的逆命题）。

> 删除 `Gen/` 是安全的（编译会重建），但**别**把 `Gen/` 回滚成旧版——它必须与当前 ndf 一致。

---

## 9. 未验证 / 边界

- `Localisation/**` **整目录覆盖**式迁移：若新版官方改了同名 CSV 会被我们盖掉
  （本项目 6 个 CSV 全是新增，风险低）；
- 官方若把某个**我们已改过**的对象改成了不兼容结构（字段删除），`patch_units` 会报「找不到锚点」，
  需要人工裁定——工具**不猜**；
- 本节的号段规则只覆盖 `UnitId` 与 `Division ID`；若新版引入新的自增号（如 Pack 序号），需另加一项检查；
- 工具的 `export` 端在超大 Mod（>200 MB ndf）上耗时数分钟，属正常。
