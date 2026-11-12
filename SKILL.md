---
name: warno-modding
description: WARNO / Eugen Systems 系游戏 Mod 数据全流程：只读勘查、造单位/弹药/外观、改将军模式(AG)牌组战斗群、行为层(AI/状态检定/技能/效果原语)、游戏 UI(图标/样式/HUD/视图)、崩溃分诊(CTD)。产出「要开发某编辑器→改哪些文件→字段怎么填→枚举有哪些值→有什么坑」的支撑报告，并判定玩法机制在引擎能力边界内能不能做。**弹道形状调参自带设计器：先用 scripts/warno_loft_designer.html 试算再写 NDF**。关键词：WARNO、Eugen、NDF、Mods、MyMod、UniteDescriptor、WeaponDescriptor、Ammunition、**弹道、高抛、曲射、飞行剖面、巡航高度、CruiseAltitude、MissileDescriptors、落点、设计器、loft**、Divisions、DeckPacks、DivisionRules、DeckSerializer、Army General、将军模式、Strategic、CombatGroup、战斗群、SmartGroup、BattleOrder、PackIndex、IsHQ、AI 行为、空袭、Airstrike、StrikeLimitations、Capacite、Condition、状态检定、技能、效果原语、UnitEffect、RTTI、WARNO.exe、能力边界、克隆单位、新弹药、白模、无火光、买不到、卡组保存、CTD、崩溃、游戏UI、界面、BUCK、HUD、ViewDescriptor、TUIStyleGuide、DefaultStyleGuides、StyleGuide、TextureToken、BlockColorsMap、UnitSpecialties、WeaponTraits、WeaponsMinMax、DivisionTypes、TUnitUIModuleDescriptor、MenuIconTexture、ButtonTexture、InfoPanelConfigurationToken、图标、卡面、兵牌、配色、本地化、dico_interface、modding_manual、ndf_reference_manual。
agent_created: true
---

# WARNO Modding

## 0. 这个技能管什么

**管**：WARNO 官方 Mods 目录（4500+ 个 `.ndf`）的勘查、造单位/弹药/外观、将军模式数据、行为层、**游戏内 UI 数据**、**导弹弹道形状调参（自带设计器试算）**、崩溃定位。
一句话目标：把「能不能做」变成「改这里、填这个、注意这个」。

> ⭐ **弹道形状类需求有专用前置步骤**：凡涉及「飞多高 / 在哪压平 / 平飞多长 / 落点偏不偏 / 改加速度角速度没反应」，
> **先让用户打开 `scripts/warno_loft_designer.html` 手动试算，参数确认后再动 NDF**（铁律 14，做法见 `references/27-loft-trajectory.md`）。
> 这个 HTML 是**参数试算台**（读参数 → 画轨迹 → 导出片段），不是「改数据的编辑器」，
> 所以它**不归** `eugen-ndf-editor-pattern`。

**不管**：
- 做**编辑器界面**（WinForms/PySide/Qt 的窗口与交互设计）→ `eugen-ndf-editor-pattern`
  ⚠ 注意区分：**改游戏里的 UI**（图标/配色/HUD/AG 面板）是本技能 `70-ui.md` 的事；
  **写一个改数据的编辑器**才是 editor-pattern。
- 别的 Eugen 游戏（SD2 / WGRD）→ 结构不同，别套

---

## 1. 第一步永远先分清：你是「查」还是「改」

| 意图 | 典型话术 | 走哪条 |
|---|---|---|
| **只读勘查** | 梳理 Mods 目录 / 这个字段是什么 / 这些枚举有哪些值 / 能不能做 X | `00-recon.md` |
| **动手落地** | 加一个单位 / 加一门炮 / 改牌组 / 让 AI 用我的单位 | 先过「动手前 5 问」，再按对象分流 |
| **调弹道形状** | 飞得太高 / 没有平飞段 / 打不远 / 落点比瞄准点远 / 改加速度没反应 | **不算「直接动手」**：先让用户在设计器里试算，见 `27-loft-trajectory.md` |

> 改数据前答不上 5 问的任一条（克隆源形态 / 落哪栏 / 有无武器乘员 / 独立购买还是运输 / 有无先例），
> **先回去勘查，不要写文件**。见 `20-unit-authoring.md §1`。
>
> ⭐ 只要涉及**模型上某个具体位置**（炮口 / 挂点 / 舱门 / 传感器），还有第 6 问：**"这个位置在哪？"**
> —— 这一问**问用户，不要猜**。见 `23-mesh-import.md §5.0`。

---

## 2. 任务路由表

| 用户说 | 读 | 前置 |
|---|---|---|
| 梳理 Mods / 字段是什么 / 枚举取值 / 能不能做 X | `00-recon.md` | — |
| 将军模式 / 战斗群 / AG 牌组 / 存档存不了 / 装备选不到 | `10-army-general.md` | `00-recon.md` |
| 加单位 / 克隆改型 / 买不到 / 存不了 / 没名字 | `20-unit-authoring.md` | `00-recon.md` + 5 问 |
| 白模 / 隐形 / 图标错 / 没火光 / 有枪无火 | `21-depiction.md` | `20-unit-authoring.md` |
| 加弹药 / 总弹量不对 / 字段含义 / 先例统计 / **齐射数改了以后别的炮塔也亮** / **命中瞬间 Fatal「requested and missing」** | `22-ammo.md` | `20-unit-authoring.md` |
| **用外部模型当单位网格**（.blend/.obj/别的游戏的资产）/ 模型导入 / 一加载就 CTD / 炮口特效位置不对 / **炮塔不转** / **履带不滚、轮子不转** / **起落架不收、舱门不折叠** / **旋翼轴不跟着转** / **转起来桨盘画圈** | `23-mesh-import.md`（导入·锚点）+ `24-rig-parts.md`（拆件/枢轴/炮塔/履带轮/旋翼/起落架）+ `25-asset-pipeline.md`（材质·导出） | `20-unit-authoring.md` |
| **做地面导弹发射车**（TEL / 发射架挂弹，不是打炮弹）/ **导弹水平出管、先平飞再拉起** / **垂发、定角发射** / 车上没有弹、开火后弹不消失 / **TEL 速度与地形系数（轮式 vs 履带）** / **武器角度参数不改变姿态、俯角设 0 不开火** | `26-ground-missile-tel.md`（挂架链 + 出管方向 + §4.8 角度 + §9 底盘） | `20-unit-authoring.md` + `21-depiction.md` |
| ⭐ **调弹道形状**（飞得太高/太直/像抛石机 / 没有平飞段 / 平飞太长 / 打不远 / **落点比瞄准点远** / 末段太陡 / **改加速度或角速度看不出效果** / 巡航高度超调） | `27-loft-trajectory.md`（**先在 `scripts/warno_loft_designer.html` 里试算，参数确认后再写 NDF**） | `26-ground-missile-tel.md §2` |
| **点进军械库就崩 / 部署放下那一刻崩** / 机腹多一具吊舱 / 挂架位置有白色异物 | `21-depiction.md §3c`、`§4.3` | — |
| **烟幕按钮按不出来 / 面板炮名还是克隆源那把** | `20-unit-authoring.md`（§3「克隆后必查：订单表」）+ `22-ammo.md`（§5 显示名 token） | `20-unit-authoring.md` |
| AI 不用我的单位 / 状态检定 / 技能 / 效果原语 / 血量档位 | `30-behavior.md` | — |
| 改了没生效 / 编译报错 / 换行编码 / 回滚 | `40-engineering.md` | — |
| **游戏大更新后 Mod 起不来 / 报一堆 `File not found` / 要不要跑 `UpdateMod.bat` / 想迁到新基线** | `28-mod-update.md`（对象级改动包重放，**不要跑 `UpdateMod.bat`**）+ `scripts/modupgrade/` | 先另存旧 `base.zip`（共同祖先） |
| 游戏崩溃 CTD / dump 分析 / RVA | `50-crash-triage.md` | — |
| 面板数字对不上 / 打不到直升机 / 飞行高度 / 弹丸可选 | `60-numbers.md` | — |
| **齐射数 `SimultaneousShotsCount` 改了以后，别的炮塔也跟着亮 / 部署瞬间闪退** | 三处 `WeaponShootData` 名数必须都等于 `Sim`（弹药 / 武器槽 / depiction 算子）；名数 < Sim → 越界串位，NbProj > 6 → 部署 CTD。改前先跑 `sim_sd_audit.py` | `22-ammo.md §2.5` |
| 改图标 / 配色 / HUD / 界面文字 / AG 面板 / 面板显示怪 | `70-ui.md` | — |
| **给单位换卡面（兵牌图）/ 卡面还是克隆源那张 / 卡面空白 / 卡面是透明底** | `20-unit-authoring.md §2.5` | 两段式：`render_card.py`（透明底渲染）→ `card_composite.py`（深色渐变）→ `set_card_art.py`（注册行 + 单位字段）；**这是外源美术资源，不归 `70-ui.md`** |

---

## 3. 全局铁律（跨所有任务，15 条）

1. **`Generated/` 可编辑。** 文件头那句「Ne pas éditer」对 mod 制作者无效，它就是源数据。
   ⚠ 唯一例外：`Generated/UserInterface/`（16 个文件）是 `XxxFileWriter` 从 gameplay 扫出来的**桥表**，
   手改会被下次编译覆盖——要改效果就改上游（单位字段 / style token），见 `70-ui.md §7`。
2. **不报错 ≠ 成功。** 「单位存在 / 可用 / 看着对」是三件事，各隔一组注册，缺了都静默失败。
3. **先勘查后动手；勘查不出来就问人。** 5 问答不上就别写文件。文档 / 全库检索 / RTTI 能回答的自己查；
   **只有用户知道的事实（"你要的是哪个部件""这块是什么"）直接问**，别用十轮渲染比对去反推。见铁律 12。
4. **编译只走守卫脚本，不看退出码。** `GenerateMod.py` 语法错也返回 0；报错原文只在 `#32770` 模态框里。
5. **换行 / 编码先探测再写回。** 同一目录 CRLF/LF 可能混用；`UNITS.csv` 常被存成 GBK → 中文乱码；用 `Path.read_text/write_text` 改大 `.ndf` 会整文件重写换行 → 数十万行假 diff。
6. **文本锚点必须链式递进。**（这里的"锚点"是 `str.replace` 的定位串，与模型空物体锚点是两回事）
   `replace` 找不到定位串会**静默原样返回**；批量建型时每轮定位串更新为刚插入那条，否则全批只成功第一处。
7. **验收按依赖顺序。** 买得到 → 存得住 → 名字对 → 模型对 → 里面有人 → 打得出 → 有火光。跳步会误判。
8. **禁止动作**：改现有弹药对象 / 改现有 `WeaponDescriptor` 的 `Ammunition` 指向 / 共享载具 depiction / 沿用克隆源 `Name` token / 拿「原版 0 先例」当「引擎不支持」/ 用退出码判成功 / 游戏开着时编译。
9. **UI 是字符串契约，拼错不报错。** 纹理名、style token、`ElementName`、`ViewDescriptors` 的 key 任一写错，只会静默变空白图/默认色/原始 token 串，编译照样通过。验收必须看画面，见 `70-ui.md §10`。
10. **锚点同样是字符串契约，但拼错会 CTD。** 空物体名被 `Anchors` / `ZAxisNode` / `*BoneName` 引用，
    **加载时硬校验，缺一个即 Fatal error**；而编译期完全不查（`rc=0`、spk 也照常变大）。
    换模型必须沿描绘链**正向量一遍名字**，不能照抄别的模型，见 `23-mesh-import.md §3`。
11. **动一个部件之前，先问"它背后是什么"。** 表面的一块可能是实心件，也可能是**单层曲面 + 机身凹兜**
    （拆走/转大就露洞）。判据只能靠「隐藏 + 红底背面剔除」或「射线回打」，
    **不能用单色渲染里"发黑"当证据**——单层曲面背面本来就黑，本项目因此误判过两次，见 `24-rig-parts.md §1`。
12. ⭐ **多提问，少猜测——「这个东西在哪」永远先问。** 凡是「机体上某个具体位置/部件」的确认
    （炮口、挂点、舱门、传感器、天线、要拆的是哪块），**属于用户一句话就能定、我十轮渲染也未必猜对的事**。
    提问一次的成本远低于猜错一次。规矩：
    - **先问，再烘焙**。不要等部署进游戏、肉眼看不对了才回头问。
    - **问的时候给可点选的证据**，不要问开放式问题：渲染同角度图 + 叠 A–T/1–16 网格，让用户报格子（如 `M8–N9`）。
    - **不要拿自己猜的位置去问"是不是这里"**——用户只能答否，然后你换一个再问，来回多轮；
      应给一张含全部候选区域的图，让用户**指**，而不是让你**试**。
    - **警惕相邻零件**：加油探头 / 天线 / 传感器常在目标旁边，看着像"伸出来的那根管子"。
      用户已在图上标注时，**默认标注是对的**，先按标注做事，别自己另找一面。
    - **一次只问一个判据**。复合问题（"是不是这里、要不要加火光"）会让人答一半。
    这条在 **网格定位（`23-mesh-import.md §5.0`）、发射口与挂点（`24-rig-parts.md §7`）** 上最贵，见那两节。
13. ⭐ **行为不对，先查「骨骼有没有落点」，再查数值。** 引擎的行为参数（发射方向、俯仰角、挂点数）
    最终都要写在**某根骨骼**上；那根骨骼不存在、或是根**无子节点的空骨**，数值怎么调都不会有反应，
    而且编译期零报错。本项目在「导弹水平出管」上连绕三轮（改基角 → 车体网格加骨骼 → 独立挂架网格），
    真因就是俯仰骨是个空壳。见 `26-ground-missile-tel.md §4 / §7`。
    反向也成立：**`AngleRotationBasePitch` / `MaxPitch` / `MinPitch` 这类角度参数根本不驱动姿态**
    （它只管"打不打得到"），姿态只认 deploy/fold 动画与挂架网格；而且 `MinPitch` 别设 0，
    否则目标稍有高差就判不可瞄准 → 站着不开火。见 `26-ground-missile-tel.md §4.8`。
14. ⭐ **弹道形状不对，先让用户在设计器里试算，别在 NDF 里盲调。**
    形状由 13 个字段**耦合**决定（速度律 → 曲率半径 → 能爬多高 → 会不会冲过巡航线 → 末段起点），
    在 NDF 里改一个数、编译、进游戏，一轮 3–5 分钟，而且**看不到中间量**（当前 α 是多少、
    相切点落在哪、末段够不够距离）。正确顺序是：
    **打开 `scripts/warno_loft_designer.html` → 复现「现在的形状」→ 单变量迭代到用户满意 →
    导出片段 → 才回写 NDF**。跳过试算直接改，等于拿编译当调试器。
    见 `27-loft-trajectory.md`（含 §7 前置检查 / 顺序表 / 禁止动作）。
    ⚠ 工具的绝对落点**不是**实机落点（末段 ω 归属未实测），只作定性；
    `ω 尺度 k = 1.5` 是**标定值不是实测值**，别用它去凑实机数字。
15. ⭐ **默认新建单位，不改原版。** 改原版单位的描绘资源 / 武器槽 / 单位块属越界——它会把
    所有引用该单位的师一起改掉，且玩家一眼能看出「原版模型变了、面板多了一行」。
    **「注册到某个师」= 只加 `DivisionRules` 里该师的 `TDeckUniteRule`**；
    **不要**动默认卡组（`Decks.ndf` 的 `DeckPackList`）、**不要**动该师 `MaxActivationPoints`、
    **不要**为此加 `DeckPacks` 条目。往默认卡组塞卡会连锁触发 `deck autofill` 两类 Fatal
    （`invalid associated transport` / `exceed maximum activation points`）。
    恢复原版时，`base.zip`（Mod 模板）里有逐字原文，别凭记忆重建。
    本项目在 2A36→KRSN 上因此整轮回退重做，见 `giatsint/2A36_KRSN_落地报告.md §4.3`。
    ⚠ **克隆单位的模型不换**：`VehicleApparenceModuleDescriptor` 模板里写的是
    `Depiction = TTimelyDepictionReceiverFactory( BlackHoleKey = <MimeticName> )` ——
    **真正决定外观的键是 `MimeticName`**，模块里那个 `BlackHoleKey` 字段不是给 live depiction 用的。
    只改 `ReferenceMesh` 和 `BlackHoleKey`、漏改 `MimeticName`，就会**静默命中克隆源的那条 depiction**：
    编译全绿、单位能买到、就是模型永远是原版的。三个键（`MimeticName` / `BlackHoleKey` /
    `ReferenceMesh`）必须一起改。
    ⚠ **牵引类单位还有第四处**：`Generated/Gameplay/Gfx/Depictions/Towable.ndf` 的
    `TTowedUnitCatalogEntry`（`Catalog = TowedUnitCatalog`）按 `Identifier`（= 外观键）登记
    **牵引态**的三档 mesh 与 `InitialPose.Angle`（= 网格自带炮管仰角，照抄源单位数值）。
    `IsTowable = True` 的单位漏登这条，被牵引车挂上时直接
    `Fatal: No towed unit entry for depiction '<名字>' / Context: <牵引车>` ——
    编译期同样零报错。
    ⚠⚠ **拖行姿态还有两个必查项**（本项目踩过，炮管 40° 上翘、大架插地）：
    ① **炮管链层级**必须是 `tourelle_01 → axe_canon_01 → canon_01 → fx_tourelle1_tir_01`，
    网格 `Canon_01` 也要挂在 `axe_canon_01` 下。平铺在 `tourelle_01` 下时，部署态看不出问题，
    但引擎按链施加姿态时网格不跟转；
    ② `TowedUnitCatalog` **只吃静态 mesh、不播 deploy/fold 动画**，必须另导一份
    「静态行军网格」（炮管放平 + 大架并拢）放在**独立子目录**（同目录第二个产网格的 FBX 会被
    合并进同一份 `mesh.neu3`，本项目 382 KB 一度变 714 KB），并在 `TResourceMesh` 里补
    `Textures=` 指回贴图目录。
    ⚠⚠⚠ **`InitialPose.Angle` 是向下压的量，不是"目标角"**。实机三次迭代：Angle 越大炮管越
    **顺时针下压**；用静态行军网格时 **Angle 必须为 0**（写 40 会压掉几十度）。
    ⚠ 另外：**实机部署仰角可能比烘焙值高约 10°，且这个偏差改 NDF 角度参数无效**
    （`AngleRotationBasePitch` 改 0 / 改负值、`TurretIdleBehaviour` 俯仰锁 0，实机都没变化）。
    唯一可靠的补偿是**在烘焙时把起落部分绕耳轴下压同样的角度**（本项目 40.08° → 30.08°，
    实机即回到 40°）；`bake_fold` 的 `ARM_DEG` 要同步减，rail 网格**不要动**（出管方向独立）。
    ⚠ `AngleRotationMinPitch` 必须**严格小于** `AngleRotationBasePitch`，否则 `Weapon.ndfbin`
    加载期直接 Fatal（`Invalid property ... must be less than ...`）。

---

## 4. 能力边界速答（最高频的「能不能」）

| 问题 | 答案 | 依据 |
|---|---|---|
| 弹丸 / 导弹做成可选单位？ | **结构封死**（四次实机 CTD，崩溃点在 `TStateEngineUnit`） | `60-numbers.md §8` |
| 开火后 N 秒触发？ | **能**：`TConditionTimeAfterShot` + `Capacite` | `30-behavior.md` |
| 血量低于 X% 就…？ | **能**：`DamageLevels.ndf`（不走 Condition） | `30-behavior.md` |
| 让 AI 用我的飞机打某个目标？ | 先查标签池 + `StrikeLimitations` 白名单；白名单里没有目标类别 → **必死，改标签不是改参数** | `30-behavior.md §B` |
| 无人机能被坦克主炮打下来？ | 会：`AltitudeMinGRU < 100` 掉进 `NearGround` | `60-numbers.md §6` |
| 单位进哪个栏由 `UnitRole` 决定？ | **不是**：由 `FactoryType` + `MenuIconTexture` | `20-unit-authoring.md §6` |
| 新增师要注册吗？ | 要：`DeckSerializer.ndf` 的 `DivisionIds`，否则卡组存不了 | `10-army-general.md §5` |
| 外部模型（别的游戏扒的）能当单位网格吗？ | **能**：≤65,536 顶点、UV ≤±4、根网格叫 `Chassis`、朝向 +X；真正代价是补锚点名 | `23-mesh-import.md §1` |
| **模型看着没问题，能不能先判它过不过 cook（会不会被 AssetCooker 拒）？** | `scripts/mesh_check.py --cook`：退化面（面积<1e-9）、零法线、n-gon、松散点/线、无 UV 层、**ORM 走 MATH 中转**，任一硬伤 `rc=1`。比"编一遍看报错"快两个数量级 | `25-asset-pipeline.md §2 附带坑三` |
| **cook 全绿、rc=0，但主网格 `mesh.neu3` 根本没生成？** | **资产目录撞了原版路径**：烘焙器按**目录**判重，认为该路径已在 CoreCatalog 里注册过 → **静默跳过、不覆盖、不报错**。改内容/改文件名都没用，必须换一个游戏里不存在的目录名并同步改所有 `Mesh=` 引用。判据：日志里有没有 `Generating: …/mesh.neu3` | `25-asset-pipeline.md §6.1` |
| **牵引炮的重写 NDF 里照抄了 `HumanSubDepictions_*` 和 `Carriable_Canon_Arms*`，编译全绿但启动弹 `Missing subdepiction anchor bone` / `Missing bone … requested by operator 'carriable'`？** | 这两行代码会在**加载期**去 FBX 里找 4 根骨：班组落点 `servant_g`/`servant_d`（脚底 Z=0，挂 `SubDepiction_ServantLeft/Right`）与拖拽臂 `bras_droit`/`bras_gauche`（`carriable` 算子用，本模型无几何但必须存在）。回烘焙脚本的骨骼字典补 4 个静止空物体（`+Y = gauche`），重跑动画烘焙让 `.baf` 同步涨节点。**别在成品主网格上二次导出补骨** | `25-asset-pipeline.md §6.2` |
| **克隆车辆后进游戏弹 `Missing subdepiction anchor bone 'driver'`？** | `clone_unit.py` 把源单位的 `HumanSubDepictions_<源>` 一起搬来了，里面是驾驶员人体网格（要求 FBX 有 `driver` 骨）。**封闭车体（坦克 / 履带 TEL / 步战）直接摘掉**：战场版 `SubDepictions = [ ] + HumanSubDepictions_<新>` → `[ ]`；`DepictionHumans.ndf` 的块体 → `HumanSubDepictions_<新> is []`。**不要**补一根浮空 `driver` 骨（车里会凭空站一个人）；敞篷车相反——保留并烘焙时补骨。报错会列出 17 个外观算子、指向 `Depiction.ndfbin`，**真因是多挂了一条乘员子描绘**，容易追错方向 | `20-unit-authoring.md`「克隆后必查：乘员子描绘」 |
| 锚点（空物体）少一个会怎样？ | **直接 CTD**（加载时硬校验），且**编译期不报错**。注意还有一组**描绘块里没写、引擎默认 18 个外观算子也要**的标准特效骨骼（`fx_chaleur_01`/`fx_incendie`/`fx_fumee_01`/`fx_munition`/`fx_trainee_01`/`fx_leurre*`/`fx_moteur`/`fx_stress_*`），**一次只报一个，必须整组配齐**；报错文字指向 `Depiction.ndfbin` 但真因在 FBX 节点。地面车（TEL/坦克）另有 21 项全集，且**两套轮子命名不能混** | `23-mesh-import.md §2.3` |
| **骨骼补了、FBX 里也有名字，但动画里就是不跟着动？** | FBX 有名字 **≠** `.baf` 里有节点块。用 `scripts/fbx_anchors.py baf` 看节点块数有没有按新增数量上涨（实测 19 → 40）。别用 `count('fx_moteur')` 判——字符串池共享前后缀会得 0 | `23-mesh-import.md §2.3` |
| 改锚点位置能让武器从炮口开火吗？ | 看算子：`WeaponInstantFire` 读 `Anchors`；`WeaponMissileCarriageFire` 由 `Connoisseur` 决定，**不读** | `24-rig-parts.md §7` |
| **车开走了、发射架收了，弹体还立在发射位？** | `.baf` 是逐节点绝对矩阵、引擎不推层级：静态父级下骨骼矩阵恒定。父级保持静态，**逐帧给骨骼打关键帧**（= 臂位移 × rest）后再重烘 | `26-ground-missile-tel.md §4.7.1` |
| **移动时弹体被甩到车头下方/车身中部、停车瞬间跳回竖起？** | ①骨骼被挂到了**网格对象**下（不再是骨→退回模型原点）；②烘焙时把臂的 `location` 归零，整根臂绕世界原点转 | `26-ground-missile-tel.md §4.7.1` |
| **导弹竖起来后弹尾钻地 / 弹体悬在导轨下方 / 弹比导轨短一截？** | 挂点位置错了，**不是**起竖角也不是车太矮：挂点必须落在**沿弹轴的包围盒中点**（= 弹模型原点），用顶点均值会被尾翼拉偏（圆点 9M79 实测偏 2.05 m，尾钻地 0.48 m）。用 `scripts/render_ground.py` 一跑即知 | `26-ground-missile-tel.md §4.5` |
| **导弹能从发射架/竖管里按角度出去吗（垂发、定角发射）？** | **能，但只能模型层**：做一份**独立、无动画**的挂架网格，把出管轴骨骼（`missile_1`）烤成目标角度，再让 `MissileCarriage.MeshDescriptor` 指向它。改 `AngleRotationBasePitch` **无效**（反例 `FV438_Swingfire_UK` 基角 −30° 而发射箱仰着） | `26-ground-missile-tel.md §4` |
| **牵引炮能做出「行军放平 / 放列展开」两种形态吗？** | **能，官方 8 门同类先例**（B4M / Br5M / KS30 / 76T2 / HS831 / HSS630 / ZPU4）都用同一个 `DepictionOperator_AnimationDeployable`，难度在**几何**不在 NDF：折叠角必须从壳分组 + PCA 铰点 + 梁轴方位解出来，不能手填。炮管仰角要用**沿轴切片质心拟合直线**量（整体 PCA 会被后座机/制退器带偏，2A36 实测差 0.5°） | `26-ground-missile-tel.md §4.7.3` |
| **地面车的导弹要用 `as_N_M` 挂点组吗？** | **要，但不是车内那套**：`MissileCarriage.MeshDescriptor` 指向的**挂架网格**里必须有 `as_{武器槽}_1`（本例 `as_1_1`），否则**加载期** Fatal（`Not enough hardpoint groups : … model has 0 'as' and 'aa'`，编译期全绿、报错指向 `Depiction.ndfbin`）。数量与计数走 `MissileCarriage.WeaponInfos`（`MissileCount`）。`Tourelle{N}_MissileCount` **不是**计数口径，它只是「把弹画在车上」那套 `SubDepictionGenerator` 的 `PhysicalProperty` 字符串。**⚠ 挂架网格不必另做一份 Rail FBX**：官方 `MissileCarriage_AIFV_B_TOW_NL` 的 `MeshDescriptor` 直接指向单位主网格（LOSAT 实测 12 发弹照此落地）；硬点只要求「`MeshDescriptor` 指向的那份网格」里有 `as_1_1`。战场版 `TMissileCarriageSubDepictionGenerator` 还必须有 `Pylons` + `ReferenceMesh`，缺后者编译弹窗（编译期不查） | `26-ground-missile-tel.md §3 / §3.4 / §4.2` |
| **新建对象后编译弹窗 `Invalid character` / `unexpected $end`，或 `Property 'ReferenceMesh' must be defined`？** | ① `DescriptorId` 写成裸 `{uuid}` → 必须 `GUID:{uuid}`，改完要**回滚 `.bak_*` 全部备份再重跑幂等补丁**（不能只补前缀）；② 战场版 `TMissileCarriageSubDepictionGenerator` 缺 `ReferenceMesh`，这是**加载期**硬校验、编译期不查 → 补 `Pylons` + `ReferenceMesh`。两条均 LOSAT 2026-11-11 实测 | `40-engineering.md §5.4` / `21-depiction.md §4.3` |
| **战场 12 枚弹都对，军械库里却只有一枚悬在两个发射箱中间？** | 军械库那套 `TShowroom…Generator` **没有**逐发 `MissileNumber`，位置只看槽位骨 `as_{武器槽}_{N}`；官方 `DepictionPylonSet_ATGM_Showroom` 只有 **1 个槽位**，所以只画 1 枚、落点 = `as_1_1`。`as_1_1` 不是「过加载期校验的占位」，**必须与 `missile_1` 完全同位**（父级也相同，见下一行的父级判据）；顺手补齐 `as_1_2..N` 作对冲 | `26-ground-missile-tel.md §3.4`「`as_1_N` 的坐标 = 军械库里那枚弹的落点」 |
| **导弹飞到目标上空、即将命中那一刻弹窗 `happening 'X' requested and missing in Mimetic World Descriptor`？** | 弹药 `ImpactHappening` 写了**不存在的事件名**。合法值只能从 `MimeticImpactMapping.ndf` 的键里挑：地发 ATGM 只有 **Gen1/Gen2/Gen3**（Gen4 属**空射** `MissileAGMGen4`，别跨族借）；原版还有大量 `Canon*`/`Roquette*`/`Bombe*` 条目，别只 grep `Missile` 前缀。**只在命中瞬间触发**，编译/加载全绿也查不出 → 写完必须拿白名单扫全 Mod | `22-ammo.md §3.1`、`50-crash-triage.md §5.5` |
| **整车进游戏发黑、只剩轮廓、看不出任何涂装色？** | 先查金属度这条链，两种同病：①`_M` **全白**（抄通道时只顾链接、不看中间 `MATH` 的**乘数**，把 `B≡1.0` 的 ORM 通道直接导成 `_M`）；②**`_R`/`_M` 压根没生成**（源模型只有 D+NM，没有 ORM，如 LAV-600）。两者都是「引擎拿到的 metallic≈1」⇒ 无漫反射。判据：PIL 量 `_M` 均值（车体应≈0，本 Mod 先例 0.00–0.34）+ 看 `Gen/PC/Atlas/…` 有没有 `TSCORM_*`。排完金属度才轮到「`Base Color` 本身是棕灰」→ 走调色，别用改光照凑 | `25-asset-pipeline.md §2 附带坑四 + 调色专题` |
| **炮塔一转，车尾甲板上的舱盖/散热格栅跟着转？** | 分组判据**开口**了：只写 `c.z > 1.45` 没有车尾方向的**上限**，车尾薄板全被扫进炮塔组（本项目误收 1396 面）。按炮塔主壳实测 `y` 区间定上界；**验收必须把炮塔转 55° 再渲**，静止图看不出来 | `24-rig-parts.md §1.1` |
| **导弹挂架跟着武器俯仰、从发射筒里翘出来？** | 挂点父级错了：挂点的父级应 = **弹体所依附的那个网格**的父级。固定发射箱 → `tourelle_N`；可俯仰发射臂 → `axe_canon_N`。`missile_N` 与 `as_1_N` 必须同父级，否则军械库与战场显示不一致 | `26-ground-missile-tel.md §3.4.1` |
| **展厅/军械库里弹体一半多戳出炮塔外，但站姿、父级、数量都对？** | 引擎把弹体**几何中心**对齐挂点，不是弹尾。挂点原在「筒口平面」时，长弹（AIM-120 3.66 m vs 炮塔 3.635 m）会前端伸出 1.38 m。判据：**弹长≈炮塔纵向长 → 挂点取炮塔几何中心**，只改纵向一个分量，横向列位与两排高度不动。**验收必须摆示意圆柱量包围盒**，别用透视渲染目测 | `26-ground-missile-tel.md §3.4.2` |
| **弹体和筒孔咬出一道月牙形 / 看着一半沉在筒里、其余都在筒内？** | 先别算圆心，**先确认挂点接的是弹体哪个部位**：挂点贴的是**模型原点**，原版 AIM-120 的原点在**弹体最高处（顶面）**⇒ 弹心 = 挂点 − 弹半径（0.089），整个弹体吊在挂点下方。按「挂点=弹心」去取筒轴或内腔圆心，等于让弹低 89 mm，弹底必然穿筒底 —— LOSAT 为此返工四轮。判据：**想弹心落在哪，就换算回挂点**；管式发射要弹整颗坐进筒内 ⇒ 弹顶贴筒顶 ⇒ 挂点 = 该筒 `ceil_z`（内壁最高点，向 ±Z 打射线量，别用筒口通孔质心——被加强环削偏 8–12 mm）。⚠ 两排筒常是镜像，各用各的 `ceil_z`；验收按**弹心**算余量（脚本里 `anchor−R`），18 边形筒允许 −2 mm 级固有干涉 | `26-ground-missile-tel.md §3.4.3` |
| **飞行员/乘员穿出座舱盖、车顶？** | 锚点语义错了：**锚点对齐的是模型原点（人形=脚底），不是座垫面**。量三个面（玻璃顶 / 坐垫面 / 舱底）→ 锚点 = 坐垫面 − 臀部到脚底的高度；用原点在脚的坐姿 proxy 人形渲图核验 | `23-mesh-import.md §5.4` |
| **一轮齐射只有一对火光/弹道？** | **不是射速问题**：算子是 `WeaponContinuousFire`，整轮只在进入开火状态时触发一次火流。要「发射数 = 弹道轨迹数」必须换 `WeaponInstantFire` + `Single` 模板。**两处同时喷火也不要求 `ContinuousFire`**：`InstantFire` + 双锚点 + `NbProj = 2` 即可（官方 BTR-50 MRF） | `21-depiction.md §4.1b` |
| **想让一门武器有多个弹种（双子弹药）？** | **双子弹药** = 同一炮塔里多个 `TMountedWeaponDescriptor` 的 **`AmmoBoxIndex` 相同** ⇒ 共用一个弹池，`Salves` 长度不变；**组内 `Name` token 必须完全相同**（共用一个面板槽位，名字不能各写各的）。`AmmoBoxIndex` 不同则是两个独立池。**原版**飞机上 0 先例（769 例全是地面枪炮），但本 Mod 已实装 3 例机载双子弹药（柳叶刀 / Mig29M Kh29T / AH64 ATAS 地狱火）并编译通过；机载加槽四件套见 `22-ammo.md §2`，别动 `MissileCarriage.WeaponInfos`，仍须实机验收 | `22-ammo.md §2 / §5.3` |
| 炮塔能转吗？/ 怎么让炮塔转 | **分拓扑**：①炮塔与车/船壳被融合成一张皮（体素重构后的舰船）→ 挖洞必露底，**别做**；②部件本来就是凸出的独立壳（直升机炮管、雷达罩）→ **能**，但只切凸出件、基座留机身。两种都要先过 `24-rig-parts.md §3` 的判据 | `24-rig-parts.md §3.2 / §3.3` |
| 履带不滚 / 怎么让它滚？ | **改材质名**：左右各一个材质，名字含 `Chenille_Gauche` / `Chenille_Droite`，引擎据此绑履带 shader 滚 UV。**但"绑上"≠"看得见"**：贴图纯色（32×32 单色）或 UV 全 0 时滚了也看不出——先数贴图颜色数 | `24-rig-parts.md §4` |
| 轮子能转吗？ | 能。履带车：**独立网格 + 同名 `Roue_Elev_{D\|G}{n}` 空物体**在轮心；轮式车：官方 `GAZ_66B` 是 `Roue_Gauche_01`/`Roue_Droite_01` **根层 Mesh**、原点在轮心。名字由 `WARNO.exe` 的格式串拼出（`roue_d%1`/`roue_g%1`/`roue_elev_d%1`） | `24-rig-parts.md §4` |
| **轮式车的轮子纹丝不动（模型命名全对）** | **推进算子挂错**：从履带车克隆来的 depiction 里是 `Propulsion_ContinuousTrack`，它不驱动轮式轮子。换成 `DepictionOperator_Propulsion_Wheels_Generic` + `DepictionAction_MovementFX_Wheeled`（圆点 9K79 实测真因）。**命名也要对族**：轮式车按履带那套 `roue_elev_g1`+`Roue_G1` 命名，名字落进 `roue_g%1` 族，`Wheels` 算子不认 → 同样纹丝不动（LAV-600 实测第三种成因）。轮式 = `Roue_Gauche_0N`/`Roue_Droite_0N` **根层 Mesh、原点在轮心**，且**别建** `roue_gauche_01` 空物体（那是弹射出生点字面量，会与轮网格重名） | `24-rig-parts.md §4` |
| **武器描述器的角度参数改了，模型姿态不变？** | 正常：`AngleRotationBasePitch` / `MaxPitch` / `MinPitch` 只是**瞄准解算窗口**，姿态由 deploy/fold 动画与挂架网格决定 | `26-ground-missile-tel.md §4.8` |
| **俯角设 0 以后目标稍有高差就不开火** | `AngleRotationMinPitch = 0` = 不留任何俯角，仰角解算够不到 → 判不可瞄准。留负余量（−20° = −0.349 rad 起手） | `26-ground-missile-tel.md §4.8` |
| **两种同级车怎么做出速度差（轮式 vs 履带）** | 四个字段成套改：`MaxSpeedInKmph` / `SpeedBonusFactorOnRoad` / `TerrainSpeedFactors`（轮式用 Wheel 表，履带用 Track 表）/ `UnitMovingType`；`DisplayRoadSpeedInKmph` 只是**面板贴纸**（全库 0/1576 与计算相符），按档位抄整数 | `26-ground-missile-tel.md §9` |
| **要从一个已有单位克隆出变体（换武器 / 换阵营 / 换底盘 / 换师）？** | 一条命令 `scripts/clone_unit.py`：扫全 Mod 找出**引用闭包**（单位本体 + 武器 + 三态 depiction + 挂架链 + 订单可用性，圆点实测 14 个对象），整块克隆改名，再往三个**容器**插行（师规则 `UnitRuleList` / `DeckSerializer` 的 `UnitIds` / `UNITS.csv`）。`--list-only` 只看闭包。**回滚必须用 `--undo <manifest>`**，不要自己按块删 | `20-unit-authoring.md §2` |
| **发射架起竖 / 收拢动画怎么烘？** | `scripts/bake_deploy_fold.py`：折叠角**从几何解**（不手填）+「先抬后转」双旋钮 + 逐帧给挂点骨骼打关键帧 + `location` **绝不归零** + 逐帧偏差自校验（应 0.00000 m）。`--clip-check` 默认关，射线奇偶法对非闭合网格会整段误报 | `26-ground-missile-tel.md §4.7` |
| **起竖到一半会不会擦到车顶 / 中间过程穿模？** | **别只看两个端点**：中段（20–40%）才是高发段。`scripts/pose_render.py --sweep-progress 0.2,0.35,0.5,0.65,0.8,1.0` 逐点给 **BVH 最近距离 + 表面相交对数** 并出图；`--sweep-angle` 用同样方式扫行军抬头角（一次只改一个变量）。相交对数 = 0 **不等于**没问题（整个埋进去时也为 0），必须看图 | `26-ground-missile-tel.md §4.7.2` |
| **车体里的轮子拆不出来 / 拆了不转？** | `scripts/split_wheels.py`：焊接 → 连通块 → **双判据并集**（轮材质 ∪ 圆盘几何）选壳 → 拆成 `roue_elev_*`（空物体，轮心）+ `roue_*`（网格子节点，local 0）。只按材质筛会**漏掉没有轮材质的诱导轮**（M752 漏 2 只），且不报错 | `24-rig-parts.md §4` |
| **起落架能收放吗？** | 能，但走**涂层配方 `TCoatingRecipe`**（Pantry + Cookbook），**不在 depiction 的 Operators 里**；网格必须先拆成独立节点（`roue_*`），bake 在 `Chassis` 里的永远不动 | `24-rig-parts.md §5` |
| **舱门/整流罩能折叠吗？** | 看它背后是什么：实心件可自由转；**单层曲面 + 机身凹兜**只能"压平"（本项目 60° 是上限），转多/搬走会把凹兜让出来，像破了个洞 | `24-rig-parts.md §1` |
| **模型里到底有没有做「门/可动件」？分块上色看侧面是一整片，是不是就说明没有？** | **不是。** 分块色只回答「哪些面连在一起」，外皮连成整块**不妨碍**门是另一块独立壳。三条判据一起看：① 是**闭合体**（边界边 0 + 体积 > 0，不是单层皮）；② **删掉它，背后露出的是凹腔/挂架/机构**（不是黑洞）；③ 尺寸像机构（门 1–3 m × 0.5–1 m）。判据 ② 是决定性的。做法：**按壳隐藏**重渲（`--hide`），不是涂色；⚠ 壳索引必须在**焊接后**的 blend 上算，否则拆第二个件时编号会移位 | `24-rig-parts.md §1.2` |
| 部件拆出来转起来露内壁 / 桨盘画圈？ | 前者是**按面切**（要焊接后整壳归组）；后者是**枢轴抄了骨骼坐标**（骨架与几何中心可差 0.8 m，要用质心求外心） | `24-rig-parts.md §1 / §2` |
| **桨叶/可动件飘出去、绕机体公转**（半径大到不合物理）？ | **`matrix_world` 惰性求值**：摊平循环改了 `parent`/`matrix_basis` 后没 `view_layer.update()`，读到的是旧矩阵 → `hub` 算错；位置误差会自己抵消（几何看着对），错只落在枢轴上，**静止截图查不出来**。摊平后先刷新 + 断言 `matrix_world` 是单位阵，并验「空物体原点 = 网格原点 = 网格世界质心」 | `24-rig-parts.md §2.1` |
| **四旋翼 / 旋翼超过 3 副？** | **引擎硬上限 3 副**，写 4 个 `THelix` 会 `Fatal: On limite a 3 rotors pour raisons de performances`（整个 `Depiction.ndfbin` 加载失败，所有飞机一起坏）。解法：拆两个算子 + **各给不同 `OperatorId`**（`'Rotors'` / `'Rotors2'`），只拆不给 Id 会被合并、报同样的错。**算子类必须留在 `TCosmeticRotorOperatorDesc`**——换成 `TCosmeticAirCushionRotorOperatorDesc`（气垫船风扇）会落地不停转 | `24-rig-parts.md §6.1` |
| **引擎多画了一个挂架/吊舱，能去掉吗？** | 能：**别给那件武器登记 `MissileCarriage.WeaponInfos`**（引擎只对登记过的武器找挂架）；同时把它的算子从 `WeaponMissileCarriageFire` 换成 `WeaponInstantFire`。`Pylons` 不能为空、槽位数是模型元数据，所以"做隐形挂架"这条路是死的 | `21-depiction.md §4.3` |
| **烟幕按钮不见了 / 烟幕下不了指令 / 不会「受损自动放烟」** | **订单表漏了一项**，不是缺模块、也不是弹药问题：`Descriptor_OrderAvailability_*` 里要 `EOrderType/ShootDefensiveSmoke`（坦克自放烟幕）或 `EOrderType/ShootOnPositionSmoke`（自行火炮打烟幕弹）。自动烟幕走同一条订单——`GDConstants.ndf` 的 `AutoSmokeQuandRatioPvInferieurA = 1.0`，没有单位级开关。顺序顺带补 `SpecialtiesList` 的 `'_smoke_launcher'` | `20-unit-authoring.md §3「克隆后必查：订单表」` |
| **面板上那把炮还是克隆源的名字（如 100mm 显示 D-10T）** | 弹药 `Name` 沿用克隆源的**共享 token**（`JSGOCUPBIT` 被基座 7 条 D-10T 弹药共用）→ **不要改它的文本**（会把原版全改名），给本单位换一个专用 token（≤10 字符）+ 在 `UNITS.csv` 登记一行，然后**必须重新编译**（`.dic` 是编译产物） | `22-ammo.md §5` |
| 界面图标/配色/文字怎么改？ | 四条 token 链：纹理 bank / StyleGuide 三张色表 / 字体 / dico；**拼错不报错** | `70-ui.md §5` |
| **想给自己的单位出卡面（兵牌）？** | **两段式出图 + 三步注册**：`render_card.py`（Blender 自动取景渲 512×288 透明底，`--trim-z` 剔天线）→ `card_composite.py`（深色渐变合成，**不要直接交透明 PNG**）→ `set_card_art.py` 一条命令落图 + 注册 token + 改 `ButtonTexture`。**mod 侧那份纹理 ndf 必须是整份拷贝**（整文件覆盖，只写自己一条会把 2911 条原版全弄没）；原版 PNG 不能同名覆盖（`NATO/FOB_US.png` 被 9 个 token 共用）。编译后 token 在 `Gen/NDF/UI/Components.ndfbin`、引用在 `GFX/Unit.ndfbin` | `20-unit-authoring.md §2.5` |
| 新单位面板显示怪 / 特性少一行？ | 查 `TUnitUIModuleDescriptor`：`InfoPanelConfigurationToken`(8 档) + `SpecialtiesList`(须存在 UnitSpecialties 的 83 key 中) | `70-ui.md §6` |
| **导弹飞得太高 / 太直 / 像抛石机 / 没有平飞段？** | **先在设计器里试算**（`scripts/warno_loft_designer.html`）：`CruiseAltitudeGRU` 定形态、`Dt` 定末段；两者定完再谈速度。别在 NDF 里盲调 | `27-loft-trajectory.md §3` |
| **落点比瞄准点远 / 巡航高度比设定高？** | 不是 bug：上升段 ω 太低 ⇒ 压平前冲过巡航线；末段仍按 `Terminal.AutoGyr` 尽力修俯角，修不完就落在后面。工具里能先看到超调量 | `27-loft-trajectory.md §4` |
| **改 `MaxAccelerationGRU` / `AutoGyr` 看不出效果？** | 加速度**会改形状**（`R=v/ω` 逐点变），但前提是走对相位：上升段两段转向统一读 `Ascendant.AutoGyr`（实机：两段都变缓）。工具里切 `split` 可复现"没反应"的旧口径 | `27-loft-trajectory.md §5` |
| **弹道形状的参数怎么调、调完写成什么？** | 13 个字段的映射表 + 定稿总表在 `27-loft-trajectory.md §2 / §8`；`α`、`k`、`v₀` 是派生/换算量，**不写进 NDF** | `27-loft-trajectory.md §2` |

> ⚠ **判定纪律**：`WARNO.exe` 的 RTTI 才是「引擎支持什么」的权威；NDF 只反映「原版用到了什么」。
> 「原版 0 先例」只能写进待验清单，**不能当结论**。要断言「不支持」，必须找到引擎硬校验或实机复现。

---

## 5. 索引

### references/

| 文件 | 内容 |
|---|---|
| `00-recon.md` | 只读勘查：目录全景、必看文件、RTTI 三方对比、原版/mod diff、改了没生效排查 |
| `10-army-general.md` | 将军模式：五层数据链、**PackIndex W1–W4**、IsHQ、DivisionIds、指挥链、ndfbin/dic |
| `20-unit-authoring.md` | 造单位：**8 处注册**、**§2.5 卡面 ButtonTexture 三步（PNG→纹理 bank→单位字段）**、克隆法、单位块六组、CV 四判据、分类排布、验收七问 |
| `21-depiction.md` | 外观：四型 depiction 对象数公式、七件套、飞机 12 对象、**武装直升机（§3c 四处注册 + 崩溃原文对照 + 炮塔三层）**、**挂架 PylonSet 三定律与终局（§4.3）**、开火四段链、**算子 × FX 模板配对（§4.1b：连发只有第一发 = 算子选错）** |
| `22-ammo.md` | 弹药：六步、总弹量公式、字段语义表、**§3.1 `ImpactHappening` 只能在 `MimeticImpactMapping.ndf` 白名单里挑（地发 ATGM 只有 Gen1–3）**、先例统计、token、台账 |
| `23-mesh-import.md` | **导入外部网格 · 通用层**：判据、硬约束表、锚点硬校验（官方真实层级 / 大小写）、锚点正向枚举、七步流水线、锚点定位（别用包围盒比例）、NDF 三处接入、**§7 类型装配清单**（哪种装备要接哪些子系统）、排错总表、验收、被推翻、执行清单、参数总表 |
| `24-rig-parts.md` | **可动部件 · 子系统层**：§0 三套机制对照、§1 三角汤拆件（焊接壳整壳归组 + 「背后是实心还是凹兜」）、§2 枢轴从几何求（§2.1 matrix_world 惰性求值陷阱）、§3 炮塔（失败案例 + 只拆炮管的成功判据）、**§4 履带与轮（引擎格式串 `roue_d%1`/`roue_elev_d%1`、轮式必须挂 `Propulsion_Wheels_Generic`、履带滚动三前提）**、§5 起落架/舱门（CoatingRecipe，含旋转方向反与角度上限）、§6 旋翼（§6.1 三副上限与四旋翼拆法）、§7 挂点与发射口、§8 验收 、**§1.1 分组判据必须有界 + 必须转起来验收（否则尾舱盖被炮塔带走）**、**§1.2 判「有没有做门/可动件」= 闭合体 + 隐藏看背后露出什么 + 尺寸像机构（分块色不算数；壳索引要在焊接版上算）** |
| `25-asset-pipeline.md` | **资产管线**：FBX 导出定稿参数、glTF 四道清洗、PBR 通道接材质、在成品 FBX 上补几何、删不可见面减面、atlas 像素预算、新增小 FBX 的 AssetCooker 门槛 、**§2 附带坑四（抄通道的三个误读：B 通道当金属度 / `pixels` 不是线性值 / 源模型没有 ORM 导致 `_R`/`_M` 整个缺失）+ 贴图偏黑四层排查（含第 0 层：文件到底有没有）与调色专题** |
| `26-ground-missile-tel.md` | **地面导弹发射车（TEL）**：判据（炮弹 vs 导弹）、9 处注册、弹药与飞行实体、挂架链（**§3 计数口径修正：`WeaponInfos.MissileCount`，且 `MeshDescriptor` 指向的网格仍要有 `as_{槽}_1`**）、**§3.4 多枚弹（12 发）主网格范式 + `ReferenceMesh` 硬校验 + `as_1_N` 落点（军械库那枚弹就画在 `as_1_1`）**、**§4 出管方向 = 需要改角度时才做独立挂架网格**、**§4.5 挂点位置 = 包围盒中点**、**§4.8 角度参数只管瞄准不管动画（俯角别设 0）**、三处显示场景、判读表、**§9 轮式/履带速度与地形系数**、被推翻的判断 、**§3.4.1 挂点父级：固定发射箱挂 `tourelle_N`、可俯仰发射臂挂 `axe_canon_N`（否则弹翘出筒）**、**§3.4.2 挂点纵向位置：弹长≈炮塔长时取炮塔几何中心（引擎对齐弹体中心，留筒口会戳出一半多）**、**§3.4.3 挂点高度：先量模型原点（AIM-120 原点在弹顶 ⇒ 弹心=挂点−R，按「挂点=弹心」算必低一个半径）；管式发射取筒 `ceil_z`；两排镜像各算各的；18 边形筒有 −2 mm 级固有干涉** |
| `30-behavior.md` | 行为层：AI 决策五池五标签、4 类 Condition、48 技能、42 效果原语、血量档位 |
| `40-engineering.md` | 工程规范：五条铁律、换行、锚点截断、**全局替换打穿原版（§3.5）**、守卫、编译四通道、**§5.4 弹窗原文对照（含裸 `GUID` / 缺 `ReferenceMesh` 两条）**、**编译范围与「改了没生效」判据（§5.7）**、验收五件套、回滚 + Fatal 对照 |
| `50-crash-triage.md` | 崩溃分诊：CrashRpt 位置、四字段、RVA、指令解码、对照组、**§5.5 弹窗 Fatal 与 CTD 的分流（`Missing`/`must be defined`/`requested and missing` 一律查数据，不解 dump）** |
| `60-numbers.md` | 数值语义：引擎硬校验、伤害尺度、对空开关、视野隐蔽命中、碰撞层、弹丸 CTD |
| `70-ui.md` | 游戏 UI：324 个 NDF 的 6 类分法、**五根五层**、BUCK 模板体系、**四条 token 解析链**、生成层 16 文件、`TUnitUIModuleDescriptor` 接口、六条改动路径 |
| `27-loft-trajectory.md` | ⭐ **高抛/曲射弹道调参**：什么时候必须上设计器、**13 个字段 ↔ 参数栏映射**（哪些是派生量不能填 NDF）、8 步流程（先复现现状再改单变量）、红/黄诊断含义、三条口径开关与 `k=1.5` 是标定值、实机五项对照、**给智能体的前置/顺序/禁止清单**、定稿参数总表 |
| `28-mod-update.md` | ⭐ **Mod 更新专题（游戏大版本升级后）**：为什么不能跑 `UpdateMod.bat`（实测静默丢 82/309 个对象、删掉整份单位表）、对象级改动包三件套原理、五步迁移（导出→三件套预检→拼装→编译→实机）、四道验收闸、**定稿号段规则（UnitId 整体平移 / Division ID 重算）**、**新版引擎 5 条新约束**（不再自带 Python / `GfxDescriptorChassis.ndf` 不可改 / 命名空间搬家 / 产物变 `.txn` / 号段被消耗）、**8 条被推翻的判断与错因**、回滚四档 |

### scripts/

| 文件 | 用途 |
|---|---|
| `recon.py` | 目录级勘查：目录全景 / 关键词命中 / 生成器标记 / 字段与枚举统计 |
| `ndfq.py` | 单文件查询器：列对象 / 看块 / 字段分布 / 换行探测 / 先例统计 |
| `sim_sd_audit.py` | **齐射联动审计（只读）**：扫全库挂载槽，交叉弹药 `SimultaneousShotsCount` 与两处 `WeaponShootDataPropertyName` 名数，报 `Sim × 名数` 表、尾号是否等于武器号、`i` 是否 0..N−1；`rc=1` 即有不一致 |
| `genmod_guard.py` | 编译守卫：捕获 `#32770` 弹窗 → 解析「对象 → 文件:行号 → 成因」→ 落盘 |
| `dump_engine_types.py` | 抽 `WARNO.exe` RTTI 类型表，与 NDF 用量做三档对照 |
| `analyze_crashdump.py` | 崩溃转储：RVA → `.pdata` 函数区间 → 寄存器/栈帧 → 字符串标注 |
| `patch_template.py` | 补丁脚本骨架：换行探测、幂等、must/must-not/结构三类守卫、`--dry-run` |
| `clone_unit.py` | ⭐ **克隆单位变体（一条命令 · 幂等 · 可回滚）**：`--src --name [--token --display-name --src-token --division --list-only --dry]`。先扫**引用闭包**（实测比手工枚举多 4 处：挂架链 + Ghost + Showroom，14 vs 10），再逐块克隆、容器插行（`NdfDepictionList` / `DivisionRules` / `DeckSerializer` / `UNITS.csv`），UnitId 自动取 `max+1`。四条护栏：`GameData:` 资源路径**不跟着改名**（否则 `File not found`）、专属资源文件只留本单位块（否则 `Namespace opened twice`）、缩进取**众数**、幂等按对象身份判（`unnamed` 块也能认）。`--undo <manifest>` 按备份覆盖回滚 —— **绝不要自己按块删**，容器文件里一个块可能是整个大列表。**写回按目标文件原换行风格**（`write_like()`，2026-11 修：此前容器写回会把 CRLF 整份压成 LF，编译照样过，但 diff 变成「全文件改写」，事后查不出改了哪几行）。**NameToken 双护栏**（2026-11-10 补，LAV-600 实测克隆源 `NameToken='RJJGNUEUQO'` 残留）：① 自动从源单位块读 `NameToken` 加进改名表（不传 `--src-token` 也换）；② 写盘后按新对象名复查，不等则打 `[FAIL]` —— 残留的症状是面板显示哈希串或 Dictionary error，编译零报错。**复查窗口按块边界截**（2026-11-11 LOSAT 修：原用固定 4000 字符，而单位块可到 9 KB、`NameToken` 实测在偏移 8275，会误报 `(无字段)`；改为从块头截到行首 `)`，嵌套块有缩进不会误截） |
| `fbx_anchors.py` | **FBX 7.x 直读校验 + .baf 结构表**（不需 Blender）：`dump` 列节点树与类型；`check` 验 `Chassis` 是 Mesh + 锚点名全命中 + 父子层级；**`baf`** 读烘焙产物的节点块偏移表（时长/帧数/节点数/每块是否带轨道）。多文件逐个处理。`rc=1` 即有缺失或 `--expect-nodes/--expect-anim` 不符。**补完约定骨骼后必须用 `baf` 验节点块数有没有涨**——FBX 里有名字 ≠ baf 里有节点块 |
| `depiction_anchors.py` | **从 NDF 正向枚举锚点名**：给 `--key <BlackHoleKey>` 或 `--object <算子名>`，沿 Operators / SubDepictions / 算子定义递归，收齐 `Anchors` / `*Node` / `*BoneName`；`--out` 直接产出 `fbx_anchors.py --need-file` 能吃的清单。⚠ **只扫单个 NDF 文件**：`Actions` 里 `+ DepictionAction_*` 指向 `DepictionActions.ndf` 的内容它看不到（实测只报 7 个，漏 `fx_eau` → 实机 `Missing anchor bone`）。要完整清单用下一条 |
| `depiction_anchors_all.py` | ⭐ **跨文件锚点穷举 + FBX 差集（推荐默认用这个）**：`--key <BlackHoleKey> --fbx model.fbx [--mod --base --out --all]`。建 mod+原版**符号表**，把 `BlackHoleKey` 的**所有注册点取并集**（Tactic / Ghost / Showroom，只取第一个会落在 Ghosts → 结果 0 个），BFS 跟到 `DepictionActions.ndf` / `DepictionOperator_*` / `$/GFX/...`，最后与 FBX 节点名做差集，逐条打印「缺谁 ← 谁引用的」。`rc=1` = 有缺失。**新单位/FBX 换完必跑，编译期查不出这类错** |
| `track_uv_axis.py` | **履带 UV 走向轴判定（只读）**：测「同 X 不同 Y 两点 ΔU/ΔV 谁大」，判出宽度轴与走向轴，与官方 M1（宽度 U / 走向 V）对照。不一致就得 UV 转置 + 贴图转置，见 `24-rig-parts.md §4` |
| `mesh_check.py` | **模型体检（Blender 脚本，只读）**：顶点是否超 65536、每网格面数/包围盒/UV 范围/smooth 比例、**焊接后壳数**（判断"三角汤"还是"装配体"）、边界边比例（判断"单层皮"）、锚点清单与世界坐标。`blender -b -P` 跑。**`--cook`** 追加 AssetCooker 编译门槛预检：退化面（面积<1e-9）、零法线、n-gon、松散点/线、无 UV 层、**ORM 走 MATH 中转**（→ FBX 无 `_R`/`_M`，不生成 TSCORM 槽）；任一硬伤 `rc=1`。输入支持 `.fbx` / `.blend` / `.gltf` |
| `split_shells.py` | **三角汤拆件（Blender 脚本）**：焊接 → 连通块 → **整壳归组** → 拆成独立节点（顶点按 pivot 中心化，保留 UV/材质索引/smooth）→ 导出 FBX。部位用 JSON 的 AABB 描述，左右各写一条 |
| `split_wheels.py` | ⭐ **拆轮（Blender 脚本）**：`--src --out [--dia --thick --dry]`。按**双判据并集**（含轮材质的面片 ∪ 纯圆盘几何）拆出 `roue_elev_{g\|d}{n}` 空物体 + 子网格，并强制网格子节点 `matrix_parent_inverse = Identity` + 局部 `location = 0`（官方 M1 契约，引擎按轮心算滚动）。**只按材质筛会漏诱导轮**——它复用车身暗色材质，M752 实测漏 2 只且编译、加载零报错，只有渲染才发现。阈值由材质轮的中位直径/厚度自动推导，不硬编码；文件已有 `roue_elev_*` 时直接拒绝（防重复拆）。见 `24-rig-parts.md §4` |
| `pose_render.py` | **姿态 × 机位带材质渲染（Blender 脚本）**：读 `poses.json` / `views.json`，每个姿态重新载入模型后摆姿势，Cycles/EEVEE 出图。判断"贴不贴合 / 露不露内腔 / 有没有翘边"用，**至少三个机位**。**扫掠模式** `--sweep-progress 0.2,0.35,…` / `--sweep-angle 10,4,0`：按铰点从几何解折叠角（与 `bake_deploy_fold.py` 同算法），逐采样点同时给 **BVH 最近距离 + 表面相交对数** 并出图。中段 20–40% 才是穿模高发段，**别只看两个端点** |
| `pick_anchor.py` | ⭐ **锚点定位四合一（Blender 脚本）**：`render` 渲与参考图同角度的图、自动叠 `A..T / 1..N` 网格、可打红球；`pick` 把**格子**（`M8` / `M8:N9`）或像素**反算成世界坐标**（透视 / 正交都支持）出 JSON，`--mark-out` 直接出红球复核图。`--fit` 自动取景、`--cam-json` 复用渲图相机（防手抄错位）。流程见 `23-mesh-import.md §5.0` |
| `render_ground.py` | ⭐ **验收：弹体落位是否穿地**（Blender 脚本）：`--src <展开态 blend> --missile <弹体 fbx/blend> --out <目录>`。按引擎的做法把弹体实例摆到 `missile_N` 骨骼上，与车体里那份弹体比：**红=实际、绿=应为**，判定「挂点与几何中心相距」应 < 0.01 m。见 `26-ground-missile-tel.md §4.5` |
| `rail_mesh.py` | ⭐ **出管挂架网格（Blender 脚本）**：`--src <展开态 blend> --out <fbx> --bones missile_1,canon_01,as_1_1 [--expect-elev 70]`。抄骨骼世界矩阵 → 建 4 mm `Chassis` → 三角化 → 落 4×4 贴图 → 导出。两道守卫：期望仰角不符 / 骨骼不共姿态（多因给了收拢态文件）直接拒绝。见 `26-ground-missile-tel.md §4.2` |
| `set_card_art.py` | **卡面一条命令（幂等）**：`--mod --png --name --units ... [--faction --size 512x288 --from --dry]`。按宽高比居中裁切 → 512×288 RGBA → 落 `UnitsIcons/<阵营>/` → 在 `ButtonTexturesUnites.ndf` 的 MAP 收尾前注册 token → 按块切片改各单位 `ButtonTexture`；行尾随原文件、写前备份、写后校验 token 数与 CRLF。见 `20-unit-authoring.md §2.5` |
| `render_card.py` | **卡面两段式①·透明底渲染（Blender 脚本）**：`blender -b <baked.blend> -P render_card.py -- --out card_raw.png [--trim-z 3.15 --view 1,-1,0.52 --margin 1.10 --res 512x288]`。自动取景（顶点投相机空间算 `ortho_scale`，**它是水平可见宽度**，手填必切炮口）；`--trim-z` 剔天线防画幅被撑高（LAV-600 实测车体被压到 67% 宽）。三点布光 + EEVEE + Standard 变换 + 透明底。**产物不要直接交**——透明底与卡池风格不一致 |
| `card_composite.py` | **卡面两段式②·深色渐变合成（普通 Python + PIL）**：`python card_composite.py --raw card_raw.png --out card_final.png`。径向渐变 `C_IN(0.100,0.115,0.140)→C_OUT(0.022,0.026,0.034)` `r**0.85` + 噪点 0.04 + 底部椭圆接触阴影 blur14 + vignette `0.45*(r-0.55)**1.6`，512×288 RGB。参数是 PT100 / 2S25 / LAV-600 三单位逐值复用的定稿，合成结果与先上线的 `OBJECT_685.png` 四角像素逐值相同。之后再走 `set_card_art.py` 注册 |
| `bake_deploy_fold.py` | ⭐ **起竖/收拢烘焙（Blender 脚本）**：`--arm --chassis --hinge --bones --fold-dir --frames [--axis --fps --lift --fwd --stow-lift --stow-nose-up --exclude-mesh --clip-check --no-export --dry]`。出 `_fold.fbx` / `_deploy.fbx` 两份，`rest` 定为发射态。**三条铁律**：① 绝不归零 `arm.location`（原点在铰点上时归零＝把它搬到世界原点再绕车体中部转）；② 折叠角从**几何**解（铰点 → 臂上离铰点最远的顶点），别手填角度；③ 出管挂点骨骼**逐帧打关键帧**（`delta @ rest`，`delta = arm.matrix_world @ arm_rest.inverted()`），不能把挂点挂到网格对象下。逐帧自校验挂点偏差（实测 0.00000 m）。「先抬后转」用 `--lift`（sin² 包络）+ `--stow-lift`；`--clip-check` 用 BVH 对**非闭合网格**整段误报（实测 151/151 帧全报），**只作参考，必须渲染目视**。见 `26-ground-missile-tel.md §4` |
| `warno_loft_designer.html` | ⭐ **高抛弹道设计器（不是 Python，是单文件 HTML，双击即用、零依赖、不联网）**。用途：**调弹道形状前先在它里面试算，参数确认后再回写 NDF**。参数栏 = 13 个 NDF 字段 + 4 个口径开关（速度律 / 转向率归属 / 末段制导 / ω 尺度 k）；右侧实时画曲线 + 指标卡（派生 α、保持段 L、相切点、平飞段、落点、超调量）；能导出只含官方字段的 NDF 片段。内置 `AGM114A` / `SRBM` 两个实测预设。⚠ 默认 `k = 1.5` 是**标定值**，改回 1.00 可复现早期基线；绝对落点只作定性。用法见 `27-loft-trajectory.md` |
| `modupgrade/` | ⭐ **版本迁移工具包（六子命令 · 纯标准库）**：`modupgrade.py export / apply / lock / nsaudit / selftest / assemble`。`export` 把「旧基线 + 当前 Mod」导成**对象级改动包**（add_units / patch_units / whole_file，66 个文件 / 335 对象 / 1.3 MB）；`apply` 注入（`--dry` 先看，逐条 op 幂等）；`lock` 查 UnitId/GUID/NameToken/BlackHoleKey/MimeticName 撞车；`nsaudit` 查 `$/NS/Name` 前缀搬家（`--fix` 批量改）；`selftest` 验「纯净基线 + 注入 == 当前树」逐字节；`assemble` 一条龙拼装。详见 `references/28-mod-update.md` |

---

## 6. 环境（本机有坑）

- **绝对不要内联执行 Python**（bash 吞反斜杠、缺 `ls`/`head`/`tail`）。写成 `.py` 文件再跑。
- 查询器优先用 `scripts/recon.py`，别手写一次性脚本。
- **`mesh_check.py` / `split_shells.py` / `split_wheels.py` / `pose_render.py` / `bake_deploy_fold.py` / `pick_anchor.py` 是 Blender 脚本**，
  要用 `blender -b -P` 跑（不是 python）；参数一律写在 `--` 之后，
  例如 `blender -b -P split_shells.py -- in.fbx out.fbx --spec parts.json`。
  本机 blender 在 **`D:/blender-5.3.0/blender.exe`**（不在 PATH 里）。
- **Blender 里的相对输出路径会掉到盘符根**（`out/x.png` → `C:\out\x.png`），
  `pick_anchor.py` 已内部转绝对路径；自己写别的 Blender 脚本时记得同样处理。
- 编译唯一入口：
  ```bash
  "<python>" "<skill>/scripts/genmod_guard.py"
  ```
  退出码：`0` 成功 / `3` 被弹窗拦下（有原文）/ `4` 超时（**不是语法错**）/ `5` 环境问题。
  ⚠ **新版游戏（2.3.3 起）不再自带 `Mods/Utils/Python`**：守卫会自动回退到系统 `python3`；
  若 `python3` 不可用，先装 Python 再编译。

---

## 7. Mod 更新专题（游戏大版本升级后）

> 完整版：`references/28-mod-update.md`。工具：`scripts/modupgrade/`。**已验证**（2026-11-13 实机通过）。

### 7.1 一句话

**不要跑 `UpdateMod.bat`。** 实测：它只报 4 处冲突，却**静默丢掉 82/309 个自建对象**、
把 `UniteDescriptor.ndf` 整份删除（新版改名 `TacticalUnits.ndf` 被判「文件废弃」），
`WeaponDescriptor.ndf` 结果与新基线**逐字节相同**（我们的 20 个武器全没了），退出码还是 **0**。
改用**对象级改动包重放**：不存行号，存「新增对象块 / 对象内行级改动 / 整份新文件」三类。

### 7.2 五步

```bash
SK=<skill>/scripts/modupgrade
python $SK/modupgrade.py export   --base "<旧 base.zip>" --mod "<Mod>" --out "<manifest>"
python $SK/modupgrade.py lock     --mod "<Mod>" --out "<manifest>/id_lock.json" --check "<新 base.zip>"
python $SK/modupgrade.py nsaudit  --mod "<Mod>" --base "<新 base.zip>" --manifest "<manifest>/manifest.json"
python $SK/modupgrade.py assemble --mod "<Mod>" --new-base "<新 base.zip>" --old-base "<旧 base.zip>" --manifest "<...>"
python $SK/modupgrade.py selftest --mod "<Mod>" --base "<新 base.zip>" --manifest "<...>"
# 再 genmod_guard.py 编译 → 实机七问
```

### 7.3 新版引擎的 5 条新约束（2.3.3 实测）

| # | 约束 | 应对 |
|---|---|---|
| 1 | **不再自带 Python** | 用系统 `python3`（守卫已回退） |
| 2 | **`Gameplay/Gfx/Units/GfxDescriptorChassis.ndf` 不可改**（加一行注释就索要不存在的 `Gameplay/Gfx/Properties.ndf`） | 不在该文件加对象；要别的参数就改用官方既有对象。**新建同目录 ndf 也不行**——跨文件 `~/` 解析不到 |
| 3 | **命名空间随文件搬家**（`$/GFX/UnitConstantes/` → `$/GFX/CriticalEffects/`） | 每次升级跑 `nsaudit`，`--fix` 批量改 |
| 4 | **编译产物变 `.txn`**（不再有 `.ndfbin`） | 验收看 `Gen/NDF/**/*.txn` 时间戳 |
| 5 | **UnitId / Division ID 号段被官方继续消耗**（官方最大 UnitId 4674 → 5021） | 每次重算：UnitId 整体平移、Division ID 取「排除我方后最大值 +1」 |

### 7.4 三条最容易写错的判据

1. **「自有文件」= 新旧两份基线里都没有**。只跟新版比，会把官方删/改名的 65 个文件搬回来；
   旧 `UniteDescriptor.ndf` 一复活，路径重定向就不触发，**注入全打在过期文件上**（本项目第一次拼装就这么废的）。
2. **`retarget.json` 放 manifest 目录的同级**，不是里面；工具会在同级 / 上一级 / 当前目录三处找。
3. **结尾空行不能进 `tail` 拼接**：同一内容会有两个固定点（`…)\n` 与 `…)\n\n`），
   注入与二次注入各落一个，等价性验收永远差一行。按**目标文件的结尾换行签名**收尾。

### 7.5 验收四道闸（缺一不可）

| # | 闸 | 判据 |
|---|---|---|
| 1 | 身份 `lock --check` | 六项全绿（UnitId/GUID/NameToken/BlackHoleKey/MimeticName/同名） |
| 2 | 命名空间 `nsaudit` | 0 条「命名空间已变」 |
| 3 | 结构抽查 | 自建对象名全在、号段正确、无 `<<<<<<<` |
| 4 | 等价性 `selftest` | 「纯净基线 + 注入 == 当前树」**逐字节 0 差异** |

第 4 条是这套流程的自证：它证明「树 = 基线 + 改动包」。**编译通过不等于对**，还要过实机七问。
