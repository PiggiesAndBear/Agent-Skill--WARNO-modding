# 造单位：8 处注册链、克隆法、分类排布

> 适用：「给某师加一个单位」「克隆这个改成那个型号」「新单位买不到 / 存不了 / 没名字」。
> 外观细化见 `21-depiction.md`，弹药见 `22-ammo.md`，编译验收见 `40-engineering.md`。

---

## 0. 一句话判据

> **「单位存在」「单位可用」「单位看着对」是三件不同的事，各自隔着一组注册。**
> 每缺一环都**不报错**，只是现象不同：什么都没有 / 买不到 / 存不了 / 没名字 / 白模 / 有枪无火。

---

## 1. 动手前必须答完的 5 问

答不上任何一条，先做只读勘查（`00-recon.md`），不要写文件。

| # | 问题 | 决定什么 | 查法 |
|---|---|---|---|
| 1 | **克隆源的挂载形态**与目标一致吗？ | 炮塔类型、角度字段、ShootData、mesh、攻击策略（5 处结构差异） | 看源单位第二/三槽的 `TTurret*Descriptor` |
| 2 | 落在哪一栏？ | `TProductionModuleDescriptor.FactoryType`（与 `UnitRole` **无关**） | `Logistic` 后勤 / `Infantry` 步兵 / `Recons` 侦察 / `Tanks` 装甲 / `Planes` 空中 / `Art` 火炮 |
| 3 | 有武器吗？有乘员吗？ | depiction 对象数（7+N / 6+catalog / 7 / 9 / 12） | 块内有无 `TWeaponManagerModuleDescriptor`、`HasServants` |
| 4 | **独立可购买** 还是 **充当运输车**？ | 两者**互斥**（全库交集 0） | 有 `TDeckUniteRule` 的 2397 个、进 `AvailableTransportList` 的 364 个，交集 0 |
| 5 | 这个组合原版有先例吗？ | 0 先例 ≠ 不能做，但**必须写进验收清单** | 见 `22-ammo.md` 的先例统计命令 |

### 克隆源选择矩阵（第 1 问的答案表）

| 挂载形态 | 克隆源 | 反着做的代价 |
|---|---|---|
| 炸弹 / 航弹 | A10 炸弹型（`A10_Thunderbolt_II_US`） | 炮塔类型、3 条角度字段、2 条 ShootData、mesh 四联、攻击策略全要改 |
| 火箭巢 | A10 火箭型（`A10_..._Rkt_US`） | 同上 |
| 导弹 / ATGM | A10 导弹型（`A10_..._ATGM_US`） | 同上 |
| 机炮 / 加特林（地面） | 同族地面型（如 `ASU_85_POL`） | — |

> 实证：从炸弹型改成火箭型，depiction 层能做到 0 差异，但**单位层必然残留 3 项**
> （`Avion_Bombardier_Infanterie` 标签、`UnitAttackValue/DefenseValue` 档位、`BombTrajectoryConfig`）。

---

## 2. 8 处注册链（缺一即残废，症状各不相同）

| # | 文件 | 对象 | 缺了的症状 |
|---|---|---|---|
| 1 | `Gfx/UniteDescriptor.ndf` | `Descriptor_Unit_X` 本体 | 什么都没有 |
| 2 | `Gfx/WeaponDescriptor.ndf` | 武器 | 面板无武器 |
| 3 | **`Decks/DivisionRules.ndf`** | `TDeckUniteRule`（师内规则） | **任何师都买不到，且不报错** |
| 4 | **`Decks/DeckSerializer.ndf`** | `UnitIds` 数字序号 | **能买能编，一保存卡组报错** |
| 5 | `Localisation/<mod>/UNITS.csv` | `TOKEN;显示名` | 显示 token 原文 |
| 6 | `Decks/DeckPacks.ndf` | `_1_1` 卡包 | 预置牌组里没有（**非必需**） |
| 7 | `Decks/Decks.ndf` | `DeckPackList` 追加 | 同上（**非必需**） |
| 8 | `Decks/Divisions.ndf` | 师招牌位 | 师招牌位缺失（**可选**） |

**关键判据：**
- `DivisionRules` 是**卡池的唯一必需来源**。原版反证：`Pero_UAV_SOV` / `MP_US` / `M1025_Humvee_scout_US`
  零卡包照样能买 ⇒ 第 6/7 项只服务**预置默认牌组**。
- `UnitId` 取 `UnitIds` **全表 max+1**，不要填空洞。
- `NameToken` ≤ **10 字符**（`TLocalisationToken` 上限，CSV 里的引号不算）。
- **两套「成本」别混**（2026-11-07 实机口径，曾推错一次）：
  - 单位描述符里的 `Resource_CommandPoints` = **遭遇战里叫一台的单价**（BMPT 150 / Tochka 255），
    与组卡（deck building）**完全无关**。
  - 组卡消耗由 `Decks/DivisionCostMatrix.ndf` 决定：
    `MatrixCostName_<师名> is MAP [ (Factory/Tanks, [1,1,1,2,2,3,3]), ... ]`
    —— 按兵种类别栏给一个**固定数组**，该栏第 N 张卡吃第 N 位，**与卡内数量、单位单价都无关**。
  - 推论：改 `NumberOfUnitInPack`（一卡几台）**不会**让组卡变贵，只影响进入战场后一次放几台。
    别拿 `Resource_CommandPoints × 台数` 当卡价。
- **`NumberOfUnitInPackXPMultiplier` = 每档练度的**「单位数量系数**（不是可用开关）：恒 4 位，对应
  Rookie / Trained / Veteran / Elite，`0.0` = 该档开不出来，非 0 值 = 该档一卡只有基准数量的这么一倍率
  （如 `[1.0, 0.6, 0.34, 0.0]` = 老兵 60%、精英不可开）。要"锁最低练度"就写 `[1.0, 0, 0, 0]`。

### 改预置默认卡组（`Decks.ndf`）的两个启动期硬校验

手搓 `DeckPackList` 时，这两条只要违反一条，**编译 rc=0 但游戏启动弹 Fatal**，
而且报错文案直接把包名点到单位上，很容易误以为是单位描述符坏了（2026-11-07 连踩两次）：

| 报错原文 | 真实原因 | 修法 |
|---|---|---|
| `Error in deck autofill '<Deck>': Following packs have an invalid unit amount` | 引用的 pack 的 `Number` **大于**该师规则里的 `NumberOfUnitInPack` | 别图省事套 `_999`（∞ 包），按规则数量建 `_<xp>_<num>` |
| `... have an invalid associated transport` | pack 块里**漏写 `Transport = $/GFX/Unit/Descriptor_Unit_X`**（pack 名带运输车 ≠ 会被解析） | 补字段；且 `Transport` 必须在该单位 `AvailableTransportList` 里 |

- pack 命名约定：`Descriptor_Deck_Pack_<Unit>[_<Transport>]_<xp>_<num>`，`num` 只需 **≤** 规则数量（1 即可）。
- pack 块只有 4 个字段：`Xp`（可省 = 0）/ `Transport`（可省 = 无）/ `Unit` / `Number`。
- **校验卡组能不能过的最快办法**：直接编译，autofill 会把所有不合法的包一次性列出来。
  别静态推——`Decks.ndf` 里同一张卡出现两次（同一 pack 写两遍）是合法的，代表买两份。
- 反推「截图里某张卡是哪个单位」时，用**三量对齐**：显示名 + `Resource_CommandPoints`（含运输车价格）
  + `NumberOfUnitInPack`（卡面左下 xN）。最后再算一遍 `DivisionCostMatrix` 的动员点总数——
  和截图右上「xx/50」对上，就说明整份卡组一个单位都没认错。

### 分两次编译

| 批次 | 做哪几项 | 达成 |
|---|---|---|
| 第一批 | 1、2、5（+`OrderAvailability_Tactic.ndf`） | **能存在、能看** |
| 第二批 | 3、4（+6/7/8 可选） | **能买、能存** |

出错时一眼分清是哪层。不要一次全上。

---

## 2.5 卡面（ButtonTexture）：一张 PNG + 两条 NDF

> §2 那 8 项之外的第 9 项，**可选**：不做只是卡面沿用克隆源的图，不影响买、编、打。
> 与 `70-ui.md` 的分界：**本节产出外源美术资源（PNG 文件）**；70 章讲的是界面控件的 token / 样式 / 布局，不碰贴图。
> 与 `21/23` 的分界：depiction 决定**战场上**长什么样，`ButtonTexture` 只管**卡池里那张画**，两者互不影响。

### 【原理】三个「图标」别混

| 字段 | 是什么 | 取值域 |
|---|---|---|
| `MenuIconTexture` | 建造栏/卡池里的**兵种小符号** | 41 种，全局共享，且**决定进哪栏**（§6） |
| `ButtonTexture` | **卡面大图**（俗称兵牌） | 2898 种，**一单位一张** |
| `SpecialtiesList` | 特性图标行 | 27 种（须在 `UnitSpecialties` 的 83 个 key 内） |

因此「卡面空白」只有一个成因：`ButtonTexture` 的取值**不在纹理 bank 里**（拼错或没注册）。
**不报错、不崩、编译也过**，只能靠眼睛发现——所以它必须进验收清单。

mod 侧的 `ButtonTexturesUnites.ndf` 必须是**整份拷贝**，不能只写自己那一条：
它是 `AbstractButtonTextureFileWriter` 的产物，mod 内同名文件**整文件覆盖** base，不是追加合并。
实证（Hell Divers，本 skill 唯一一次实机通过的样本）：base 2911 条 → mod 版 2912 条 / 2923 行，
其余 2911 条逐字未动，只多自己在末尾加的一行。

> 【2026-11-05 实测补正】手写注册 + `-generatemod` 编译后，这份 ndf **未被 writer 重写**：
> token 数仍是 base+1，mtime 停在写入时刻。产物侧两处都对得上——
> token 进 `Gen/NDF/UI/Components.ndfbin`、单位引用进 `Gen/NDF/GFX/Unit.ndfbin`，各 1 次命中。
> ⇒ **手写路径可靠，不必赌「只放 PNG 会自动生成」**（后一种至今没有实例）。
> 注意产物位置：UI 纹理 bank 编到 **`Gen/NDF/UI/`**，不在 `GFX/` 下，`find Gen -name "*.ndfbin" | head`
> 容易看漏；`.ndfbin` 是 `EUG0`+`CNDF` + zstd（magic 在 offset 44），**直接 grep 二进制搜不到**，必须先解压。
> 与 SKILL 铁律 1「`Generated/UserInterface/` 是桥表、手改会被覆盖」不冲突：那 16 个是 gameplay→UI 的桥，
> 纹理 bank 是另一套（扫 Assets 产出），两者不要混着推理。

### 【操作】三步

| # | 动作 | 落点 |
|---|---|---|
| 1 | 图落地 | `<Mod>/GameData/Assets/2D/Interface/Common/UnitsIcons/<阵营>/<名>.png`，**512×288 RGBA（16:9）** |
| 2 | 注册 token | `<Mod>/GameData/Generated/UserInterface/Textures/ButtonTexturesUnites.ndf`，`Textures = MAP [` 收尾 `]` 之前追加一行 |
| 3 | 单位引用 | `Descriptor_Unit_X` 块内 `TUnitUIModuleDescriptor` 中（紧跟 `MenuIconTexture` 下一行）`ButtonTexture = 'Texture_Button_Unit_<名>'` |

注册行（缩进 8 空格，格式照抄，`~/ComponentState/` 不能省、`Normal` 不能改）：

        ("Texture_Button_Unit_X", MAP [( ~/ComponentState/Normal, TUIResourceTexture( FileName = "GameData:/Assets/2D/Interface/Common/UnitsIcons/PACT/X.png"))]),

插入点用「最后一个 `\n    ]` 之前」定位（`rfind`），**不要按行号**。

一条命令做完（含图规范化、备份、幂等）：

```bash
python scripts/set_card_art.py --mod <mod根> --png <图> --name <UnitName> \
       --faction PACT --units Descriptor_Unit_X Descriptor_Unit_Y --dry
```

去掉 `--dry` 才写盘。它做四件事：**按目标宽高比居中裁切（cover，不拉伸）** → LANCZOS 缩到目标尺寸 RGBA
→ 拷进 Assets 并补注册行 → 把每个 `--units` 的 `ButtonTexture` 改指新 token；按块切片改写，
行尾风格（CRLF/LF）随原文件。目标尺寸用 `--size WxH`，默认 `512x288`（16:9）。

> **比例必须是 16:9，不要出方图。** 兵牌是宽幅控件，方图进去会被压扁或裁掉上下。
> 512×288 是实测通过的规格（引擎侧 tgv 原样保留 512/288，未强制成正方形）。
> 分辨率别再往上加——卡面显示尺寸本就不大，2 倍图徒增包体。

### 三条规矩

- **永远新建文件名，不要覆盖原版 PNG。** 原版图在游戏打包资源里，同名覆盖会连带污染所有引用它的单位：
  全库 2911 个 token 只对应 **2868 张图**，复用在原版里很常见——`NATO/FOB_US.png` 被 **9 个 token** 共用，
  `PACT/FOB.png` 被 4 个共用，占位图 `PACT/default.png` 更是 13 个。
- **一个 token 也可以被多个单位共用。** 同模型的多个型号（如 FPV 四型）没必要各建一条；
  Hell Divers 的两版超级驱逐舰（直升机型 / 固定翼型）就是共用一个 token、各改一次 `ButtonTexture`。
- **阵营目录可以自建。** 原版只有 `PACT/` `NATO/`，新建国家直接开子目录（如 Hell Divers 的 `SE/`），
  `FileName` 跟着写即可，不需要注册目录。改卡面**不要动** `MenuIconTexture`（动了会换栏位）。

### 【验收】三步都要过

1. **图进没进 cook**：编译日志里应有 `Generating: .../UnitsIcons/<阵营>/<名>.tgv`。
   tgv 头 offset 8/12 = 宽高（LE32，**应为 512/288，这是判断比例有没有被引擎改写的唯一硬证据**），
   offset 20 起是格式串 `A8B8G8R8_LIN`，解压后长度 = W×H×4 = 589824 字节。
2. **token 进没进产物**：查 `Gen/NDF/UI/Components.ndfbin`（token）与 `Gen/NDF/GFX/Unit.ndfbin`（引用）。
   `.ndfbin` 是 `EUG0`+`CNDF` 头 + zstd，**直接 grep 二进制搜不到字符串**，
   必须先解压再搜，否则会误判「没编进去」（详见 `40-engineering.md`）。
3. **实机**：卡池/牌组里卡面是自己的图，**且原版同族单位没被改**——后者是「覆盖了原版 PNG」的唯一症状。

---

## 3. 克隆法：只换「身份 + 机体」两张皮

克隆是造单位的默认手法（比从零写 255 行可靠）。**先 diff 两款现成单位，把差异归成三类**：

| 类 | 字段 | 处理 |
|---|---|---|
| **身份** | `Coalition`（`TWargameCoalition/PACT→NATO`）、`MotherCountry`、`ClassNameForDebug`、`TagSet`（`UNITE_*`）、`NameToken`、`DescriptorId`(GUID) | 逐个换，**GUID 必须全库 0 命中** |
| **机体** | `MimeticName`、`BlackHoleKey`、`ReferenceMesh`、`ButtonTexture`、`ShowRoomBlackHoleIdentifier`（5 处联动） | 一起换，漏一处就「模型对但图标错」。卡面若要**自己的图**（不是沿用源单位那张），走 §2.5 |
| **玩法数值** | CP / 票 / 血量 / 隐蔽 / ECM / 弹药 / 速度 | ★ **默认不动**。动了要单独说明理由 |

【实测】苏军 `FPV_Satchel_SOV` 与 `FPV_RPG7VL_SOV` 全部差异只有 6 类，**没有一处玩法数值不同**
⇒ 美军版 = 苏军炸药包**整块照搬 255 行**，只换身份 + 机体。「两国等价」由构造保证，不靠核对。

**守卫写法（务必 do-not-contain）**：克隆后检查 `"_SOV"`、`"Pero_UAV"`、`"PACT"`、`"'SOV'"`
在块内**一个都不剩**，再检查 must-contain 清单（新 GUID、新 TagSet、新武器路径、造价行…）。
只做 must-contain 会漏掉「换了一半」。

### 单位块改写六组（逐条核）

1. **GUID 全重签** — 全库 0 命中。
2. **五处换名** — `Coalition` / `MotherCountry` / `ClassNameForDebug` / `TagSet` / `NameToken`。
3. **`NameToken` 换新** — 新建专属 token（≤10 字符），不要沿用克隆源。
4. **删 `UpgradeFromUnit`** — 克隆源带的话要删（见 §6 星形约束）。
5. **保留共享资源名** — `Modele_*` / `CoatingName` 不能换（换名 = 指向不存在的 mesh/材质）。
6. **验收：残留模板名恰好 4 行** — 多于 4 行说明还有没换干净的。

---

## 4. 外观与弹药（只放入口）

- **四型 depiction 对象数公式、七件套、固定翼 12 对象、无武器运输直升机 4 对象、开火四段链** → `21-depiction.md`
- **弹药六步、总弹量公式、字段语义表、先例统计、台账** → `22-ammo.md`

一条必须记住的边界：**载具 depiction 绝对不能共享**（2208 个载具 `MimeticName` 重复组 = 0）；
步兵可以共享（55 组重复）。

---

## 5. 指挥单位（CV）四判据

（详细写法见 `20` 原文与 `unit-registration.md`）判 CV 的四个条件必须同时满足，缺一不算：

1. `TProductionModuleDescriptor` 的 `FactoryType = Logistic`
2. `TUnitUIModuleDescriptor` 的 `UnitRole = CV`
3. 有 `TCommandModuleDescriptor`
4. `TagSet` 含 `UNITE_CMD`

> ⚠ 四个条件要一起核，只满足 2~3 个会出现「看着像 CV 但不提供指挥范围」或「提供范围但买不到」。

---

## 6. 分类与排布（最容易搞反）

| 判据 | 结论 | 证据 |
|---|---|---|
| 进哪个栏 | **`FactoryType` + `MenuIconTexture`**，**不是 `UnitRole`** | `FPV_AT4_US` 是 `role=uav / icon=uav / Factory/Recons`，实机在**侦察栏**；控制车 `role=reco` 同栏 |
| 可选池顺序 | `DivisionRules` 条目顺序 | — |
| 预置卡组顺序 | `Decks.ndf` 的 `DeckPackList` | **与 `DivisionRules` 不互为子序列** |
| 卡内排序 | 按 `MultiSelectionSortingOrder` | `M1025_Humvee_GVLLD_US` 文件序第 3、msso 最低，却排第 1 |

### `UpgradeFromUnit` 是星形，不是链，也不控排布

【实测】全库 1899 条：**引用深度全部 = 1**，无 A→B→C。语义是「这一族从哪个型号起步」（族根）。

四条硬约束 **1899/1899 全中**：同 `UnitRole` / 同 `MenuIconTexture` / 同 `FactoryType` / 同 `Coalition`（各 0 例外）。

- 价格**不是**约束：子>父 1275 / 同价 258 / 子<父 **366**。
- 它**不是排布键**：`GameData/UserInterface/` 全文搜 `Upgrade` → **0 命中**；同根兄弟只有 65% 连号。
  ⇒ 加了大概率**看不到变化**，别把「两车相邻」误判成它生效。
- 写位置：`TUnitUIModuleDescriptor` 内、`InfoPanelConfigurationToken` 之后。

**排布的真正三个层次**：可选池（`DivisionRules` 顺序）✅ 可改 / 预置卡组（`DeckPackList`）✅ 可改 / 玩家自建卡组 ❌ 数据改不到。

---

## 7. 验收七问（按依赖顺序，别跳）

1. **买得到吗** → 师内对应栏出现、造价/卡数正确（验 `DivisionRules`）
2. **存得住吗** → 自建牌组 → 保存 → 退出重进，单位仍在（验 `UnitIds` 序号）
3. **名字对吗** → 显示名不是 token 原文（验 `UNITS.csv` + 10 字符上限）
4. **模型对吗** → 不是白模、图标对（验 5 处机体字段）；**卡面是自己的图吗**（验 §2.5 三步，缺了不报错）
5. **里面有人吗** → 乘员显示（验 `HumanSubDepictions`）
6. **打得出吗** → 面板有武器与弹药数（验 `Salves × ShotsCountPerSalvo`）
7. **有火光/有弹体吗** → 枪口焰 + 弹道光（验 `21-depiction.md` 四段链）

台账写完必须复核：`csv.reader` 列数恒定、目标行含新内容、**其他行零改动**。按**第 1 列名字**匹配，不按行号猜。

---

## 8. 禁止动作

- ❌ 改**现有**弹药对象（弹药高度共享，改一处污染全库）→ 只能克隆新的再换挂载
- ❌ 改现有 `WeaponDescriptor` 的 `Ammunition` 指向（WD:单位 = 1:1）
- ❌ 替换 `Modele_*` / `CoatingName` 模板名
- ❌ 载具 depiction 共享（全库 0 例）
- ❌ 沿用克隆源的 `Name` token（会改掉所有共用该 token 的原版面板）
- ❌ 覆盖原版 `Assets/2D/.../UnitsIcons/` 里的 PNG（同名会污染所有共用该图的原版单位）→ 新建文件名，见 §2.5
- ❌ mod 侧的 `ButtonTexturesUnites.ndf` 只写自己那一条（整文件覆盖，会把 2911 条原版 token 全弄没）
- ❌ 用「卡面换了没有」判断 depiction 是否生效（两者完全无关）
- ❌ 拿「原版 0 先例」当「引擎不支持」
- ❌ 用退出码判断编译成功
- ❌ 游戏开着时编译
- ❌ 为改一个字段去重跑整条 `-generatemod` 管线（分钟级；优先直接改 NDF 文本）
