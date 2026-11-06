# 将军模式 / Army General：牌组、战斗群、PackIndex 与存档

> 适用：「将军模式」「战斗群」「AG 牌组」「战役编制」「存档存不了」「装备组合选不到」。
> 通用勘查方法见 `00-recon.md`，编译与验收见 `40-engineering.md`。

---

## 0. 命名空间与数据链

将军模式 = `Strategic`（官方手册 p.8：`Strategic : everything related to Army General mode`）。
但别只看目录名——**战斗群藏在 `Decks/` 下**。

```
Pawn 棋子      Unit/Strategic/Units.ndf (≈2100) + AirplaneUnits.ndf
   │           每个带 TDeckModuleDescriptor.DeckIdentifier / StrategicUIModuleDescriptor.NameToken
   ▼
战略牌组       Generated/Gameplay/Decks/StrategicDecks.ndf (≈2200)
   │           只有 4 字段：DeckIdentifier / DeckDivision / DeckPackList / DeckCombatGroupList
   │           ⚠ 没有 DeckName（遭遇战的 Decks.ndf 才有），显示名走 DeckDivision
   ├─ DeckPackList ──────▶ StrategicPacks.ndf  (DeckPackDescriptor)
   │                      字段：Xp / Transport / Unit（Unit 指向 Gfx/UniteDescriptor.ndf 的战术单位）
   └─ DeckCombatGroupList ▶ StrategicCombatGroups.ndf
                            TDeckCombatGroupDescriptor  Name / IsHQ / SmartGroupList
                              └ TDeckSmartGroupDescriptor  Name / IsHQ / PackIndexUnitNumberList
                                   └ (PackIndex, Number)
```

---

## 1. ★ PackIndex：不是下标，是「算出来的窗口起点」

**`PackIndex` 是父牌组 `DeckPackList` 的数组下标，而且它「指向一段区间」。**

```
实际分配单位数 = min(Number, len(DeckPackList) − PackIndex)
```

即 `(PackIndex, Number)` 占用 `Number` 个**连续且同 pack** 的槽位，全部区间首尾相接铺满整个 `DeckPackList`
（`ΣNumber == len`）。

### W1–W4 四条铁律（2026-10 在 `.ndfbin` 上实测，三个 mod / 6811 个 AG 牌组各 100%）

| | 规则 | 意义 |
|---|---|---|
| W1 | `ΣNumber == len(DeckPackList)` | 窗口恰好填满，无空隙 |
| W2 | 窗口两两不重叠 | 每个槽位恰属一个条目 |
| W3 | 窗口内 pack 全同 | 一个窗口的 N 个槽位是**同一个 pack 对象重复 N 次** |
| W4 | `PackIndex` == 按「牌组 → 战斗群 → 连排 → 条目」顺序铺开的**累计偏移** | **`PackIndex` 不是存储状态，是算出来的** |

**W4 是全部编辑策略的钥匙**：既然下标完全由遍历顺序决定，合法的槽位布局就**只有一个**。
⇒ 编辑器正确做法是**整牌组规范化重算**，而不是局部插入/删除。

- 实测该重算是**幂等**的：对未改动的牌组重算后重建字节与原文件**逐字节相同**
  （Test 70300 / Berlin 71364 / N.Thunder 73504 次重算，零漂移）。
- ⚠ 「临时追加到池尾、只追加 1 个槽位」会**静默截断**池尾单位的第 2 元——
  用户设定 3 队只出 2 队，游戏不报错、日志无痕。**这是该编辑器头号陷阱。**
- 订正：**不存在「空闲槽位」**。旧报告里「61.5% 空闲槽」是把区间填充位误读成空闲池。

### `.ndfbin` 的额外约束（NDF 源里没有）

- `SmartGroupList` 字段名**没有 `Deck` 前缀**（deck 用 `DeckCombatGroupList` / `DeckPackList`，
  combat group 用 `SmartGroupList`，smart group 用 `PackIndexUnitNumberList`）。
- 改 `items` 长度时**必须同步 `length` 字段**，否则编码器报 `NDF collection length mismatch`。
- **连排对象与牌组严格 1:1，零共享**（实测三 mod 共 129826 个连排对象，每个恰好被一个牌组引用一次）
  ⇒ 改一个牌组的数量绝不会牵连别的牌组。
- 官方 `GroupRules` 上限（连排≤6 / 战斗群≤5 / 每连排条目≤3）**原版数据自己就超**
  （实测 7 连排的连排组、4 条装备的连排、6 个战斗群的牌组都存在）⇒ 只能**软警告**。

---

## 2. `DeckPackDescriptor` 的定义格式与命名规则（可推导，2685/2685 零例外）

```
Descriptor_StrategicPack_[<transport 去 Descriptor_Unit_ 前缀>_]<unit 去前缀>_<xp|0> is DeckPackDescriptor
(
    Xp = 1|2|3                                 ← 可选，311/2685 整个没有这个字段（名字后缀写 _0）
    Transport = $/GFX/Unit/Descriptor_Unit_X    ← 可选
    Unit      = $/GFX/Unit/Descriptor_Unit_Y
)
```

- **只有 4 种字段形状**：`(Xp,Transport,Unit)` 1301 / `(Xp,Unit)` 1073 /
  `(Transport,Unit)` 195 / `(Unit,)` 116。`Xp ∈ {1,2,3}`，**没有 `Xp = 0` 的写法**。
- 字段顺序恒为 Xp → Transport → Unit；对象之间**恰好一个空行**；文件以 `\n\n` 结尾。
  ⇒ 追加新对象只需在文件末尾写 `对象 + "\n\n"`，既有字节一个不动。
- 引用前缀是 `$/GFX/Unit/...`（**不是** `~/`，别照抄别的文件写法）。
- ★ **单位词表远大于装备词表**：`UniteDescriptor.ndf` 有 2898 个单位，只有 1620 个被 pack 引用，
  **1290 个单位根本没有任何装备组合**——这就是「制作者在装备选择器里选不到的东西」。
  ⇒ 做装备类编辑器时，「新建缺失组合」比「编辑既有组合」更有价值。

---

## 3. `IsHQ`：两级都存在，且是「存在性标志」

- 战斗群级（缩进 4）与智能编组级（缩进 12）**都有** `IsHQ`。解析器按缩进区分，别只按字段名取。
- ★ **`IsHQ` 是「存在性标志」，不是布尔值**：取消勾选时应**删除整个字段**，不是写 `IsHQ = False`。
  留下 present-but-False 的垃圾属性，游戏可能仍按「有字段」处理。

```ndf
IsHQ = True        ✅ 勾选
（整行删除）        ✅ 取消勾选
IsHQ = False       ❌ 会留下 present-but-False 垃圾
```

- 官方数据内部也有不对称 bug 可作校验来源：`SOV_8GA_134Reco` 的 4 个战斗群各有 2 个 `IsHQ=True`
  的智能编组（全库 96.3% 恰好 1 个，共 68 个超 1）⇒ 「一组内 `IsHQ == 1`」值得当软警告。
- `Name` 是 `dico_platoons` 的 key（不是内部 ID）。⚠ 但 `Name` **可整个缺失**
  （官方 16 个智能编组不带 `Name`，如 US 10th SFG 全系列），且**可跨编组重复**
  （52128 个值只 17434 个不同）。解析器与渲染器都必须支持"字段不存在"。

---

## 4. 指挥链（组织语义，最容易漏）

- `Generated/UserInterface/BattleOrder.ndf`：580 个 `TBattleOrderSubordination`，
  字段 `BackgroundTexture`（front / corps / division / regiment / brigade）+ `NameToken` + `Superior`
  （无 `Superior` 的是根，共 7 个）。
  ★ `NameToken` **100% 可在样例词典查到**，值是 `#US  8th Infantry Div.` / `#DDR  10. MSD`
  这种「国家码 + 原文番号」形式——**拿到可读番号最省力的来源**。
- `Generated/UserInterface/Strategic/StrategicBattleOrderResources.ndf`：`DeckSuperiors` MAP，
  把每个棋子挂到建制树 → **「某营平时归谁指挥」的权威依据**（比名字前缀可靠）。
  - ⚠ **键名不一致，join 前必须归一化**：MAP 键是 `pion_XXX`，编辑器对象名是 `Descriptor_Deck_pion_XXX`。
    **不剥 `Descriptor_Deck_` 前缀会全表返回 `None`**。覆盖率：归一化后 **2207/2208 棋子**、**233/233 师**；链深 1–4 层。
  - 差的那 1 个是**官方数据本身**没有 `DeckSuperiors` 条目 ⇒ UI 上应单列「未编入建制」，别静默丢。
- ⚠ 解析 `Superior` 必须用**括号配平的整块切片**；用「取对象后 N 字节」的窗口会把下一个对象的
  `Superior` 抓进来，树就乱了（实测根变成 `1st Armoured Div.`）。正则锚 `^` + `re.M`。

---

## 5. `DivisionIds` 注册：存档阻断

`DeckSerializer.ndf` 的 `DivisionIds` 是「师 → 数字 ID」映射。
**新增师不注册，卡组无法存档**——且这是最容易漏的一步。

- 实测：两个 AGF mod 都没做 `DivisionIds` 注册，导致存档阻断。
- `UnitId` 取 `UnitIds` **全表 max+1**，不要填空洞。

---

## 6. `.ndfbin` 与 `.dic`：什么时候必须碰二进制

### `.ndfbin` 已可无损读写（2026-10-12 实测）

外层 `EUG0/CNDF`（zstd，magic `28 B5 2F FD` 常在 0x2C），内层是 **GladNDFBin**，段表：

| 段 | 内容 |
|---|---|
| `OBJE` | 对象图：`class_id u32` + 循环(`property_id u32` + value)，`OBJECT_END_MARKER` 收尾 |
| `TOPO` | 顶层对象 object_id 列表 |
| `CHNK` | 8 字节 = 对象总数 |
| `CLAS` | 类名表 |
| `PROP` | ★★ **属性表：属性名 + 所属 class_id**——字段枚举不用猜 |
| `STRG` / `TRAN` / `IMPR` / `EXPR` | 字符串表 / 路径片段表 / 导入导出路径树 |

**值类型 `type_id`**：0/1/2/3 = bool/int8/int32/uint32；5 = float；7 = strg_ref；**17 = list**；
29 = **loc_hash（8 字节）**；34 = map；`3149642683` = obj_ref；`2863311530` = trans_ref。

🚨 **`.ndfbin` 里的 `Name` / `NameToken` / `DivisionName` 是 `type_id 29` 的 8 字节哈希，不是明文 token。**
⇒ 改名 UI 只能做「从现有键里下拉选」，新键算不出来。

**无损往返已实测**（Berlin 1989，6 个文件全过）：先比 `full_data`（未压缩体）字节，再比文件字节。
已通过的三项写操作：改 `loc_hash`、改 int32 数值、`append_graph_objects` 追加新对象。

工具：社区 `WarnoArmyGeneralFramework` 的 `cndf.py`（MIT）已实现，可直接取用，别自己重写。

### `.dic` 本地化字典（`TRAD` 格式）

```
偏移 0  "TRAD" | u32 N+1 | u64 时间戳 | u32 | u32      ← 头 24 字节
偏移 24 N × 16B: [hash(8B)][u32 off][u32 len][u32 填充]  ← 有效字段只有 12
偏移 24+16N     UTF-16LE 字符串池
```

- 索引条数 **`N = u32@4 − 1`**。★ 最后一条高 4 字节恒为 `0x80000000`，**不是终止标记，是真条目**，当哨兵会少算 1 条。
- `off` 是**文件绝对偏移**，`len` 是**字符数**（不是字节，别 `len-1`）。
- **键是 8 字节内部 ID，不是 token 明文，也推不出来**（40 算法 × 6 编码全 0 命中）
  ⇒ `.dic` 能枚举文本，但做不了 `token → text` 反查。要 token→文本走 `HarvestedStrings.csv`。
- ★★ **`.dic` 的键 == `.ndfbin` 的 `loc_hash`**（Test 实测 5/7 逐字节吻合）
  ⇒ 编辑器不需要反查 token 就能显示连排名：`load_dic(...).get(smart_group['Name']['value_hex'])`。
- 🚨 **mod 自带词典覆盖率极低**：Test 5/8064 = 0.06%，Berlin 865/8924 = 9.7%。
  **其余全在游戏本体词典里，而本体词典不在 mod 目录** ⇒ 编辑器必须能加载本体词典。

---

## 7. 自制战役（AGF）

- 官方工具链 `-headless -generatemod` 是地基（未写入 README，随游戏发布在 `.bat/.py` 里，版本敏感）。
- 社区范本 **WarnoArmyGeneralFramework**（MIT，v1.1.0，约 26,700 行）验证两件事：
  1. **编制层可纯文本生成**：`modgen.py` 用「模板原文 + 追加新 export」生成 8 个 ndf + 3 个本地化 CSV（`;` 分隔）。
  2. **二进制层仍要克隆 + 补丁**：`bruderkrieg.py` + `cndf.py` 解官方 `.dat` 对象图再改。**这才是难点的 44%。**
- ⇒ 「能不能做自制战役」答案是可以，但**工作量集中在场景二进制，不在编制表**。

### 不可编辑边界（先说清楚，免得期待落空）

战役本体（用哪张图、初始态势、回合序列、目标）**没有 .ndf 源**，烘焙在
`Data/PC/<build>/Scenarios/CampagneStrat_*.dat` 与 `Maps/PC/*.dat`。
⇒ 编辑器只能做「只读浏览战役 + 改其中的战斗群」，**不能造战役**。

### 两个会咬人的细节

1. 所有 `DeckDivision` 的 ident 都以 `_solo` 结尾，join 前必须剥。
2. `Divisions.ndf` 的 `DivisionName` 是随机 10 位内部 ID；可读番号走指挥链 `NameToken`。
