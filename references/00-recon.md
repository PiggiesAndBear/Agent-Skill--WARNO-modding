# 只读勘查：从 4500 个 NDF 到一份能开发编辑器的报告

> 适用：「梳理一下 Mods 目录」「这个字段是什么」「能不能做 X」「这些枚举有哪些取值」。
> 本文件只讲**怎么查**，不讲怎么改。改动落地走 `40-engineering.md`，造单位走 `20-unit-authoring.md`。

---

## 0. 先纠正一个几乎必犯的误判

`GameData/Generated/**` 每个文件头都写着：

```
// Ne pas éditer, ce fichier est généré par XXXFileWriter
```

**这句话对 mod 制作者无效。** 它是 Eugen 内部构建流程的遗留提示。
官方 `Mods/modding_manual.pdf` 第 9~10 页的教程，就是让用户直接编辑
`GameData/Generated/Gameplay/Decks/Divisions.ndf`（把 `MaxActivationPoints = 50` 改成 `100`）。

⇒ **`Generated/` 就是编辑源数据，没有被重新生成覆盖的风险。不要去找"真正的源文件"——没有别的源文件。**

---

## 1. 环境准备（本机有坑）

- **绝对不要内联执行 Python。** 本机 bash 会吞反斜杠，且缺 `ls`/`head`/`tail`，
  `python -c "...双反斜杠路径..."` 会直接 SyntaxError。
- 正确做法：把分析逻辑写成 `.py` 文件放 `%TEMP%`，用完整路径执行：
  ```bash
  "C:/Users/123/.workbuddy/binaries/python/versions/3.13.12/python.exe" "C:/Users/123/AppData/Local/Temp/recon.py"
  ```
- 读 PDF 需 pypdf，装在本机隔离环境：
  ```bash
  VP="C:/Users/123/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
  "$VP" "C:/Users/123/AppData/Local/Temp/extract_pdf.py"
  ```

---

## 2. 跑勘查脚本

`scripts/recon.py` 覆盖完整流程，改开头 `MOD_ROOT` 即可。输出六块：

1. **目录全景** — 各顶层目录文件数 + 扩展名直方图
2. **关键词命中** — 按目标编辑器（unit / division / deck / battlegroup…）搜文件名
3. **大文件 TOP40** — 数据主体都在这些文件里
4. **生成器标记汇总** — 扫 `Generated/**/*.ndf` 首行，建「文件 ← FileWriter」职责表
5. **对象与字段统计** —
   - 顶层对象数 `^(?:export\s+)?(\S+)\s+is\s+(\S+)`（**漏 `export` 会数出 0**）
   - **按缩进分层**的字段频率：`Counter((indent, name))`。
     ⚠ 不要用 `^\s{4}(\w+)\s*=` 固定缩进正则——只匹配恰好 4 空格，且掩盖「同名字段出现在多层」的事实（如 `IsHQ` 在缩进 4 和 12 都有）
   - 枚举取值 `Counter`
6. **完整样本** — 抓一个真实完整对象块作字段参考

---

## 3. 必看的高价值文件

| 文件 | 为什么值得看 |
|---|---|
| `Mods/modding_manual.pdf`（21 页） | 官方手册，"改哪个文件"的权威答案 |
| `Mods/ndf_reference_manual.pdf`（10 页） | NDF 语言参考。★ 三种引用语义只在这里有权威说明 |
| `Tools/map_editor_manual.pdf`（38 页） | ★ 唯一文档化将军模式扩展点（`TStrategicBattlegroundInfo`） |
| `Mods/Utils/Scripts/*.py` | 构建/备份/升级逻辑，`GenerateMod.py` 是管线主入口 |
| `Utils/Scripts/utils.py` | `IsModUpToDate()` 靠 `filecmp.cmp(ModData/base.zip, <Mod>/base.zip)` 判过期 |
| `GameData/Gameplay/Decks/DeckTemplates.ndf` | ★ 罕见地暴露 `T*Descriptor` 成员名与默认值的模板定义 |
| `GameData/Gameplay/Decks/GroupRules.ndf` | 各种上限（战斗群/包数）。⚠ 是 **UI 上限不是数据不变量** |
| `Mods/ModData/base.zip`（≈8.3 MB） | ★★ **原版 NDF 源文本基线**，做「原版 vs mod」对比的唯一可靠依据 |
| `Mods/ExampleAssets/Localisation/UNITS.csv` | ★ 判定「字段是不是本地化 key」的参照词典 |
| `WARNO.exe` 本体 | ★★ 判断「机制能不能做」的唯一权威：RTTI 类型名为明文（55.7 MB / 约 24 万串） |
| `Gameplay/Skirmish/SkirmishMacros/SkirmishAirstrike.ndf` | ★ AI 用飞机的唯一入口（5 宏 × 5 标签池） |
| `Gameplay/Constantes/IAStratConstantes.ndf` | ★ AI 行为总开关与目标白名单 `StrikeLimitations`。⚠ 与 `Constantes/Strategic/` 下同名文件不同 |
| `Generated/Gameplay/Decks/DivisionRules.ndf` | ★★ 卡池的唯一必需来源 |
| `GameData/Gameplay/Constantes/GDConstants.ndf` | `SplashCollisionPlanes`：6 个碰撞层 |

---

## 4. 必须查清的关系与规则

- **师级数据是五层聚合**，不存在"一个师一个文件"：
  `Divisions.ndf → DivisionRules.ndf + DivisionCostMatrix.ndf → Decks.ndf → DeckPacks.ndf → UniteDescriptor.ndf`
- **区分"可玩师"与"战役师"**：同时有 `MaxActivationPoints` 和 `CostMatrix` 才是可玩师；
  `MaxActivationPoints = 9999` + `STRAT` 标签的是 AG 战役编制。编辑器默认列表只给可玩师。
- **变长数组**：`DivisionCostMatrix` 每个工厂解锁数组长度不等（Infantry 10 档、Defense 1 档），表格列数必须动态生成。
- **固定长度数组**：`NumberOfUnitInPackXPMultiplier` 长度恒为 4，末位多为 `0.0`。
- **新增师必须注册**：`DeckSerializer.ndf` 的 `DivisionIds`，不注册则卡组无法存档。
- **引用前缀**：`$/Path/Obj` 绝对引用、`~/Path/Obj` 加载命名空间引用、裸名同作用域。

---

## 5. 能力边界判定：读 `WARNO.exe` 的 RTTI 做三方对比

**NDF 只反映「原版用到了什么」，exe 才反映「引擎支持什么」。** 不查这层，必然把「原版没用过」误判成「不可能」。

```bash
"<python>" scripts/dump_engine_types.py "<WARNO>/WARNO.exe" "<Mod>/GameData"
```

| 档 | 含义 | 正确用法 |
|---|---|---|
| exe 有 + NDF 在用 | 官方在用 | 找最近实例改参数 |
| exe 有 + NDF **零引用** | 引擎支持、官方没启用 | **可试，属未验证区** |
| exe **没有** | 引擎不认 | 换层实现，别硬写 |

⚠ **类型名不遵守前缀**：只搜 `^TUnitEffect` 会漏掉 `TEffectInflictDamage` / `TDerouteUnitEffect` /
`TKillUnitEffect` / `TEvacAirplaneEffect`——四条同样是效果原语。**按「同一父类的全部子类」反查，不要按名字前缀数。**

⚠⚠ **「原版 0 先例」不是「引擎不支持」的证据**——比上面所有坑都危险。
实测反例：`Crew ∩ Air = 0`、全库 0 个地面载具装载飞机 ⇒ BTR-80 装 FPV **实测可用**。
⇒ **统计孤例只能产出「待验清单」，不能产出结论。** 断言「不支持」必须找到引擎层硬校验
（启动期 `Fatal error` / 加载期 `Invalid property` / 进游戏闪退）。

---

## 6. 区分「原版数据」与「mod 数据」—— 别用命名前缀

**第一反应用 `AGF_` 之类前缀 grep 是错的**：它没有误报，但**有 43% 的漏报**。

✅ 正确做法：拿 `Mods/ModData/base.zip`（≈8.3 MB / 4564 项）做基线 diff。
★ `base.zip` 里装的是**纯 NDF 文本，一个 `.ndfbin` 都没有**——它是原版**源**，mod 的 `.ndfbin` 是**产物**，可直接做语义对比。

解析原版 NDF 文本（顶层对象）的可靠正则：

```python
vre = re.compile(r'^(?:export\s+)?(\S+)\s+is\s+(\S+)\s*\n\(\s*\n(.*?)^\)', re.M | re.S)
```

🚨 **跨格式 diff 必须先归一化**，否则会造出成片假阳性（如 NDF 源与 ndfbin 的字段序/默认值差异）。

**找 mod 的「未部署工程源」比部署产物有用得多**：优先在 `Saved Games/EugenSystems/WARNO/mod/<Mod>/` 下找 `GameData/`，那是 ModGen 工作区，改这里再编译，不用碰 `Gen/` 产物。

---

## 7. 「改了没生效」的排查顺序（照走，别乱猜）

**第 0 步：确认改动真的落盘。** 看目标文件与 `.bak` 的 mtime；对改前/改后做**逐对象 diff**（不是整文件 diff）。
先把「没写进去」和「写了但不生效」分开。

**第 1 步：确认用户选的就是他想要的。** 对象内部名与显示名经常不同：

```
Descriptor_Unit_Scout_LRRP_SOV → NameToken QVXJDDQWRD → 词典文本 "SPETSNAZ GRU"
Descriptor_Unit_Spetsnaz_SOV   → NameToken NYXTELMHUW → 词典文本 "SPETSNAZ"
```

⇒ 不要拿对象名判断用户选了什么，一定走 `NameToken → 词典` 还原。

**第 2 步：查 `Gen/` 时间戳。** `Gen/` 停在很久以前 = 构建从未成功。`Gen/Version.ndf` 的 mtime 就是最后成功时间。

**第 3 步：读构建日志里的 `Process output:`。** GUI 封装只看 cmd 退出码，`.bat` 里的 python 报错不改退出码 → "失败"被报成"成功"。
最高频拒绝理由 **`Error: Mod outdated. Update required.`**：游戏更新后 `ModData/base.zip` 变了，
`<Mod>/base.zip` 还是旧快照。修法跑官方 `UpdateMod.bat`（diff3 三方合并），**必须双击运行**（会 `input()` 等冲突处理），
跑完复核玩家改动还在不在。

**第 4 步：查这数据会不会被游戏用到。** 编辑器常列全部对象，但并非每个都被引用。

**第 5 步（最后）：才怀疑编辑器写入逻辑。**

---

## 8. 两条会咬人的数据细节

1. **所有 `DeckDivision` 的 ident 都以 `_solo` 结尾**（`Descriptor_Deck_Division_SOV_1GTA_solo`），
   与 `DeckDivision` join 前必须先剥 `_solo`，否则全表匹配为空。
2. `Divisions.ndf` 里师的 `DivisionName` 是**随机 10 位内部 ID**（不可读、不经本地化）；
   可读番号只能走指挥链 `NameToken`（`Generated/UserInterface/BattleOrder.ndf`，580/580 可查）。

**NameToken vs Name（判定字段是不是本地化 key 的通用方法）**

| 字段 | 比对哪个 csv | 命中率 | 结论 |
|---|---|---|---|
| `NameToken`（单位 / Pawn / 指挥链节点） | `UNITS.csv`（`dico_units`） | 100% | 本地化 key |
| `Name`（战斗群 / 智能编组） | `UNITS.csv` | 0% | ← **别就此下结论** |
| `Name`（同上） | **`PLATOONS.csv`（`dico_platoons`）** | **命中** | **也是本地化 key** |

🚨 **踩过的坑**：`Name` 在 `UNITS.csv` 0 命中，曾误判成「内部 ID、不要翻译」——错了。
它对应 `PLATOONS.csv`。**判匿名 10 位串是不是 key，必须逐个 dico 试**：
`dico_units` / `dico_companies` / `dico_platoons` / `dico_maps` / `dico_interface_ingame` / `dico_interface_outgame`。
更省事：看 `Gen/Localisation/Intermediate/HarvestedStrings.csv`（`DICO;TOKEN;REFTEXT`，一眼看出 token 归谁）。

---

## 9. 交付格式

一份勘查报告应含：

1. **一句话结论**（能不能做 / 改哪几个文件）
2. **改动清单**（文件 → 对象 → 字段 → 新值）
3. **枚举取值表**（每个枚举列全量值 + 原版用量）
4. **风险与坑**（引用本技能对应 reference 的条目）
5. **验收方法**（怎么确认改成功了）
6. **未验证项**（明确区分【实测】与【推断】）

> ★ 所有结论标注 **【实测】** 或 **【推断】**。推断项必须写进「待验清单」，不能当结论交付。
