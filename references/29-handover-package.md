# 29 · 单位交接包（跨 Mod 迁出）专题

> 适用场景：把本 mod 里**已实机验证**的自建单位整份拆出来，落到另一个 WARNO mod。
> 与 `clone_unit.py`（同 mod 内克隆）的区别：跨 mod 不能假定目标 mod 的容器内容、号段、基线一致，
> 所以产物不是「改好的目标文件」，而是**插入块 + 冲突清单 + 校验表**，让落地方自己按它的号段放。
> 先例：TBM 包（圆点 9K79 + M752 长矛，地面 TEL）、Mig29M 包（MiG-29M，固定翼），均 2026-11 实作。

---

## 1. 一句话流程

**从单位块的 6 个锚出发，追全引用闭包 → 用 base.zip 判别哪些是原版 → 按精确行号切块 →
资产体检 + 锚点闭环 → 文档 + MANIFEST + zip。**

交接包的本质是**只读勘查**（`00-recon.md`），全程不改 mod 任何一个字节。

---

## 2. 定稿包结构（7 件套）

```
<单位名>/
├── README.md                    # 落地手册（7 节，见 §6）
├── MANIFEST.csv                 # 全文件 sha256 前 16 位 + 目标路径映射
├── <单位名>.zip                 # 整包
├── 01_Assets/                   # 直接对应 GameData/Assets/，落地时不要再套一层 Assets
│   ├── 3D/Units/<国>/<类>/<单位>/...    # FBX + 贴图（按 mod 里的真实目录原样）
│   └── 2D/Interface/Common/UnitsIcons/<阵营>/<单位>.png
├── 02_Depiction/                # 专属资源 NDF（TResourceMesh 等 export），整份复制
├── 03_InsertBlocks/
│   ├── INDEX.md                 # 每块落到哪个容器、怎么放、放置顺序
│   └── <单位>/ *.ndf.txt        # 一块一 txt，文件名 = 目标容器文件名
├── 04_Localisation/UNITS_rows.csv
└── 05_Reports/                 # 模型体检 + 单位设定摘要 + 移植总纲（不进游戏）
```

两条定稿规矩：

1. **插入块的文件名 = 目标容器文件名**（如 `WeaponDescriptor.ndf.txt`），落地方看文件名就知道往哪放，不用翻 INDEX。
2. **原版共用资产不打包**（弹药对象、导弹弹体网格、机音效、通用挂架组等）——但必须在 README 里**逐条点名**它们是原版，
   落地方才敢按「目标 mod + 原版都能找到」去验收。

---

## 3. 八步工作流

### 步 1　追引用闭包（从 6 个锚出发）

先拿到单位块（`Generated/Gameplay/TacticalUnits.ndf` 里 `export Descriptor_Unit_*`），从块内 6 个锚全库搜：

| 锚 | 在块里的字段 | 会牵出 |
|---|---|---|
| Descriptor 名 | `export Descriptor_Unit_X` | DeckSerializer、DivisionRules |
| NameToken | `TUnitUIModuleDescriptor.NameToken` | UNITS.csv |
| 外观键 | `MimeticName` / `BlackHoleKey` | Depiction* 全家（战场/幽灵/展厅三处注册） |
| Modelé 名 | `ReferenceMesh` | DepictionResources 专属文件、NdfDepictionList |
| 图标 token | `ButtonTexture` | ButtonTexturesUnites、UnitsIcons PNG |
| 武器 / 挂架 / 订单 | `$/GFX/Weapon/WeaponDescriptor_X`、`TMissileCarriageModuleDescriptor.Connoisseur`、`Descriptor_OrderAvailability_X` | WeaponDescriptor → Ammunition → MissileDescriptors；MissileCarriage + MissileCarriageDepiction；OrderAvailability_Tactic |

**搜索用 `grep -rli`（不区分大小写）**：`MiG29` / `MIG_29M` / `MiG_29M_SOV` 混着大小写，区分大小写会漏文件。
搜出来后按文件逐个打开看块，直到引用闭包不再长出新文件为止。实测闭包规模：地面 TEL 13~14 块，固定翼 14 块。

⚠ **别忘 NdfDepictionList**：专属资源文件必须在 `Generated/Gameplay/Gfx/NdfDepictionList.ndf` 里有一行
（语法是 `    "GameData:/Gameplay/Gfx/DepictionResources/...ndf",` —— **双引号字符串行，不是括号形式**）。
若源单位的 `Modele_*` 是**追加在别的单位资源文件尾部**的（本项目 MiG-29M 就是），交接时要抽成专属文件，
并补一个 NdfDepictionList 插入块。

⚠ **车辆 vs 飞机容器不同**：车辆走 `DepictionVehicles(.ndf/.Showroom)`，固定翼走 `DepictionAerialUnits(.ndf/.Showroom)`，
注册块分别是 `TacticVehicleDepictionRegistration` / `TacticAerialDepictionRegistration`。直升机另见 `21-depiction.md §3c`。

### 步 2　判别原版 vs mod 新增（唯一权威：base.zip）

在 mod 的 Generated 里 grep 不到定义，**不能**推出「原版有」（`Ammo_GatlingAir_Gsh_30_1_30mm` 定义在 `Ammunition.ndf`，
不在 `AmmunitionMissiles.ndf`）。唯一判据：

```python
import zipfile
z = zipfile.ZipFile('Mods/ModData/base.zip')
for n in z.namelist():
    if n.endswith('.ndf') and b'export <对象名> is' in z.read(n):
        print(n)   # 有输出 = 原版，不随包；无输出 = mod 新增，必须打包
```

判别结果要写进 README 的武器/资产表（标「原版」/「本 mod 新增」）。

### 步 3　按精确行号切块（不猜边界）

**块边界推断脚本在生成文件上会翻车**，本项目三种翻法都实踩过：

| 翻法 | 症状 | 正确做法 |
|---|---|---|
| walk-up 到「最近的顶层声明」 | 生成文件开头是 `// Ne pas éditer` 注释，walk-up 一直爬到文件头 → **抓到整文件**（15463 行） | 直接看原文，定精确行号 |
| `cut(起始行)` 到下一个 `export` | 多块连排（如 `MissileCarriage` 主 + `_Showroom` 两个 export）只抓到**第一个** | 先看原文形态，两个 export 一起给 |
| 尾部边界含尾 | 块尾带进**下一个单位的注释行**（`// ===== 四旋翼侦察无人机…`） | 尾行 = 下一块声明行 − 1，且**剥尾部空行** |

操作顺序：先 `grep -n` 拿到所有相关 export / `unnamed` 块的行号 → `sed -n` 看每个块的原文确认形态 →
把**精确行号写死**在提取脚本里（`cut(path, 822986, 823226)`）→ 抽检每块首尾 2 行。
行号是勘查产物，不是猜出来的。

### 步 4　抽资产

- FBX / 贴图 / 图标按 mod 里的真实目录原样复制（`01_Assets/3D/Units/...`）。
- **不重命名、不重排目录**：NDF 里 `GameData:/...` 是硬编码路径。
- 原版共用资产（步 2 判别出的）不抽。

### 步 5　体检 + 锚点闭环（交接包最硬的验收）

对**每一份**打进包的 FBX：

```bash
# ① cook 预检（退化面/零法线/n-gon/松散点线/ORM 直连）
blender -b -P mesh_check.py -- <包内>.fbx --cook
# ② 跨文件锚点穷举：拿 mod 里的引用链对 FBX 做差集
python depiction_anchors_all.py --key <BlackHoleKey> --fbx <包内>.fbx --mod <源Mod>
```

两项结果写进 `05_Reports/<单位>_MODEL_HEALTHCHECK.md`。

⚠ **工具的 MISS 要人工核实，可能是模板解析假阳性**：`depiction_anchors_all.py` 报
`[MISS] fx_reacteur ← DepictionAction_VortexFX`，实查该单位用的是**双发**模板
`template_Happening_DoubleReactorAirplane`，真实锚点是 `fx_reacteur_1/2`（都在 FBX 里）；
单发模板的名字被误拼进来了。核实方法：打开 `DepictionActions.ndf` 看单位实际用的模板链，
把模板实参里的 `SousMobile`/`Anchor` 逐个对 FBX。**假阳性也要写进报告**（结论 + 证据），不能静默略过。

### 步 6　写文档（README 七节定稿结构）

README 七节（TBM/Mig29M 两包逐节复用）：**0 包里有什么 / 1 开工前必查冲突点 / 2 落地步骤（带验收行）/
3 给智能体的执行清单（前置检查+顺序表+禁止动作）/ 4 定稿参数总表 / 5 已知陷阱（有实证）/
6 验收清单 / 7 出问题时先看这里（症状→首查表）**。
另有 `05_Reports/<单位>_UNIT_SETUP.md` 写数据侧全量设定（武器表、飞行参数、订单 14 项、编组），
README 只放落地要用的摘要；通用移植手册 `UNIT_MIGRATION_PLAYBOOK.md` 直接复用，不重写。

冲突点清单按单位类型 6 项起步：**UnitId（落地重取 max+1）/ GUID（必须换新，`GUID:{…}` 带前缀）/
NameToken（≤10 字符，与 UNITS.csv 键同名）/ Descriptor 名 / Modelé 名（Namespace opened twice）/
外观键+图标 token（`MimeticName` 与 `BlackHoleKey` 双键都要改）**。本 mod 用过的号写出来只为提醒「照抄必撞」。

### 步 7　MANIFEST.csv

列**全部文件**（含文档），列：`类型,包内路径,目标Mod路径,字节,sha256`。
目标路径映射：`01_Assets/3D/x` → `GameData/3D/x`；插入块标「见 INDEX」；sha256 取前 16 位（校验用，防传输损坏）。

### 步 8　打 zip

zip 与目录同级（`Mig29M.zip`），排除 MANIFEST 自身与 zip。

---

## 4. 落地方角度的保证（包必须替落地方想到的）

| 陷阱 | 交接包侧的对策 |
|---|---|
| UnitId / GUID 照抄撞号 | README 冲突表第 1、2 条 + 插入块里注释「落地重取」 |
| 共享 export 重复定义 | 02_Depiction 文件头注释 + README §5.1「判据：全局搜出现两次删本包那份」 |
| 落地方容器是旧版（`UniteDescriptor.ndf`） | INDEX.md 注明新旧文件名对照（新版 `TacticalUnits.ndf`） |
| 只加 Alternatives 不加 Registration | 顺序表 + 禁止动作双写（编译过、进游戏不显示） |
| 算子/注册块顺序反 | INDEX 写明「算子必须先于注册块存在」（反序能编过但运行时不挂武器特效） |
| 原版对象找不到 | README 逐条点名「原版」对象，验收按「目标 mod + 原版都找得到」 |
| 飞机 12 对象 / TEL 9 处注册漏项 | 按 `21-depiction.md` / `26-ground-missile-tel.md` 的注册口径在 README 落地步骤里逐条列 |

---

## 5. 给智能体的执行清单

### 前置检查

- [ ] 源单位**已实机验证**（没验证过的单位不配出交接包）
- [ ] 用 `grep -rli` 拿到全闭包，画成「文件 → 块行号」清单
- [ ] base.zip 判别完成：原版对象逐条点名，mod 新增逐条打包
- [ ] 每块**精确行号**经 `sed -n` 原文确认（多块连排、注释头、尾部注释三种翻法都查过）
- [ ] 包内全部 FBX 过 `mesh_check --cook` + `depiction_anchors_all`（假阳性人工核实并写报告）

### 顺序表

```
追闭包(6锚) → base.zip判别 → 定行号切块 → 抽资产 → 体检+锚点闭环
→ README/INDEX/Reports → MANIFEST → zip → 抽检（块首尾2行 + MANIFEST行数 = 文件数）
```

### 禁止动作

- ❌ 用块边界推断脚本代替人工定行号（三种翻法都实踩过）
- ❌ 在 mod 里搜不到定义就判「原版」（唯一判据是 base.zip）
- ❌ 重命名/重排任何资产目录或文件
- ❌ 静默略过工具报的 MISS（假阳性也要写报告给证据）
- ❌ 把 `Generated/UserInterface/` 的桥表文件当可打包对象（它是重生成产物，见铁律 1 例外）
- ❌ 打包 `.blend` 源工程（README 声明「改模型请从 FBX 重新导入」）

---

## 6. 与相邻专题的关系

| 专题 | 关系 |
|---|---|
| `20-unit-authoring.md`（造单位） | 造完、实机验证通过，才有资格出交接包 |
| `clone_unit.py` | 同 mod 内克隆（可改目标文件）；跨 mod 出包是只读拆解 |
| `28-mod-update.md`（版本迁移） | 同是「对象级搬运」，但方向不同：那个管游戏升级，这个管 mod 间迁移；号段规则（UnitId 重取）两边通用 |
| `00-recon.md` | 交接包的前半程（步 1–3）就是一次完整勘查 |
