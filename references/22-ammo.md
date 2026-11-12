# 弹药新建

## 0. 文件与行尾

| 内容 | 文件 |
|---|---|
| 枪械 / 坦克炮 / 火炮 / 炸弹 | `Gfx/Ammunition.ndf` | 简称“普通弹药”
| **导弹（ ATGM / AAM / SAM / LGB（激光制导炸弹））** | `Gfx/AmmunitionMissiles.ndf` + `Gfx/MissileDescriptors.ndf` 的飞行实体（见 `26-ground-missile-tel.md §2`） | 简称“导弹类弹药”
| 弹着特效注册 | `Gfx/MimeticImpactMapping.ndf` |

⚠ **行尾与其余 NDF 不同**：历史上这两个文件是 CRLF，但本项目某次整文件改写后
**已变成全 LF**（实测 0 个 CRLF，`WeaponDescriptor.ndf` 仍是全 CRLF）。抓字段的正则
必须兜住 `\r`：`^\s*%s\s*=\s*([^\r\n]*?)\r?$`。
写回前用 `scripts/ndfq.py eol <file>` 探一次，**别信这张表，也别假设**。

**`export` 前缀**：`Ammunition.ndf` / `AmmunitionMissiles.ndf` 的对象**不带** `export`；
`UniteDescriptor` / `WeaponDescriptor` / `Depictions` **带**。

## 1. 六步

1. **选模板**：同 `MinMaxCategory` + 同战斗部性质（AP / HE / 破甲）的最近实例。
2. **逐字节克隆**：只换 `DescriptorId`（对象名）与 `Name`（显示名 token）。
3. **调参**：按第 3 节表。
4. **挂载**：改 `TMountedWeaponDescriptor.Ammunition`；**绝不改现有弹药对象本身**。
5. **联动 depiction**（新挂载点要加 `WeaponAlternative_N` / `WeaponShootData_0_N` / Operator / `Actions` tagN）。
6. **入台账 + 新建专属 token**。

## 2. 总弹量公式（最重要的一条）

**弹药对象里没有"总量"字段。**

```
总弹量 = Salves[AmmoBoxIndex]   ← 数组按**弹药箱**索引，不是按武器槽
       × ShotsCountPerSalvo     ← 写在弹药对象
```

例：`Salves = [40,30,30,1]`、25mm 的 `ShotsCountPerSalvo = 5` → 箱 0 共 **200 发**。

- `Salves` = 该**弹药箱**能打几轮，长度 = `max(AmmoBoxIndex)+1`
  （全库 2515 个单位 100% 成立，实测无一例外）
- `ShotsCountPerSalvo` = 每轮**几发**
- `AffichageMunitionParSalve` = UI 显示，**自建弹药必须 == ShotsCountPerSalvo**
  （原版 237 条刻意不等，那是多管 AA 的情况，别照抄）

⭐ **同一个弹药箱里，所有弹药的 `ShotsCountPerSalvo` 必须逐条相等**——这是**加载期硬校验**，
不是软约束：

```
[Fatal error] Can't load 'Glad:/NDF/GFX/Weapon.ndfbin':
  Two ammunitions used by weapons on ammo box '0' don't have the
  same 'ShotCountPerSalvo': '4' and '3'
```

注意报错里写的是 **`ShotCountPerSalvo`**（少一个 s），按这个名字去 grep 会找不到字段。
真因永远是"给某个炮位加了一个 `ShotsCountPerSalvo` 与同箱邻居不同的弹"。
本项目实例：2A36 加红土地（原版 `=3`），同箱 HE 是 `4` → 整份 `Weapon.ndfbin` 拒绝加载。

**做双子弹药 / 加弹种时，先查同箱邻居再抄数**：`Salves` 长度不动、`AmmoBoxIndex` 相同、
`Name` 逐字符相同、`ShotsCountPerSalvo` **也要相同**。前三条在 §2.5 的"机载加槽四件套"里写了，
第四条最容易漏——因为它看起来属于"弹药自己的参数"。

### 术语：双子弹药（Dual Ammunition）

**双子弹药**指**共用同一个弹药箱（同一 `AmmoBoxIndex`）的两个或更多弹药对象**。

- 玩家侧表现：同一门武器上有多个弹种可切换（坦克炮的 AP / HE 就是这个结构）
- 弹量侧表现：打掉的弹从**同一份总弹量**里扣，不是各算各的
- 判定标准只有一条：**`AmmoBoxIndex` 相同**
- `AmmoBoxIndex` 不同 = 两个独立弹池，**不是**双子弹药
- **显示名永远保持一致**：双子弹药在武器面板上**共用一个槽位**，所以所有弹种的
  `Name` token 必须**完全相同**（用第一条弹的 token，不要为第二个弹种另建显示名）。
  各写各的名字会让面板出现两个名字、切换弹种时名字跳变。

⇒ 做双子弹药时 **`Salves` 长度不变**（数组按箱索引，不按武器槽索引）。
多出来的 `TMountedWeaponDescriptor` 只是多一个弹种入口，不占新的 `Salves` 位。

原版实证（命名与弹量都对得上）：

| 单位 | `Salves` | 箱 → 弹种 | 总弹量 | `Name` token |
|---|---|---|---|---|
| T-72AV | `[2,65,65,1]` | 箱 0：AP + HE | 2 × 22 = 44 ≈ 实车 45 | 两者同为 `KUPNLKSDNF` |
| 2S1 | `[6,4]` | 箱 0：榴弹 + 烟雾弹 | 6 × 6 = 36 ≈ 实车 35 | 两者同为 `WQEYYEBLDI` |
| 2S23 | `[4,6,15]` | 箱 0：榴弹 + 烟雾；箱 1：AP；箱 2：机枪 | — | 箱 0 两者同为 `CWBCQJBMHY` |

⚠ **原版全库 0 先例**：769 个「同炮塔多武器」的实例**全是地面枪炮**，
原版没有一个炮塔里挂两种导弹。

⭐ **但本项目已实装 3 例机载双子弹药并编译通过**（2026-11-08 复核；柳叶刀 / Mig29M
是本轮之前就有的先例，AH64 ATAS 地狱火为本轮新增），
所以「0 先例」只描述**原版**，不能当「本项目不能做」的结论：

| 实例 | 炮塔 | 两个弹种 | 共箱 | `Name` token |
|---|---|---|---|---|
| 柳叶刀 `Descriptor_Unit_Lancet_SOV` | 单机 | `Ammo_Lancet_AP_SOV` / `_HE_SOV` | box0 | 同为 `LNCTHEAD` |
| `WeaponDescriptor_MiG_29M_SOV` | tourelle2（槽 2 + 槽 4） | `Ammo_AGM_Kh29T_HE` / 原版 `Ammo_AGM_Kh29T` | box1 | 同为 `ISDQZQPFVK` |
| `WeaponDescriptor_AH64_Apache_ATAS_US` | tourelle3（槽 3 + 槽 5） | 原版 `Ammo_AGM_AGM114A_x8` / `_HE` | box1 | 同为 `PMPTRGMCKS` |

**机载加槽四件套**（从 `.bak_kh29slot` 加槽前后 diff 反推，三例同构）：

1. 弹药：克隆新弹，`Name` 与同组第一条**逐字符相同**；共用 `EffectTag`。
2. 武器管理器：在该炮塔的 `MountedWeaponDescriptorList` 加第二个
   `TMountedWeaponDescriptor`，`AmmoBoxIndex` 与第一条相同，`Salves` **不动**；
   新号 `N` 用 `WeaponAlternative_N` / `WeaponActiveAndCanShoot_N` /
   `WeaponIgnored_N` / `WeaponShootData_0_N`。
3. `Depictions/DepictionAerialUnits.ndf`：新增
   `Op_<Unit>_WeaponN is DepictionOperator_WeaponMissileCarriageFire`
   （`Connoisseur = MissileCarriage_<Unit>`、`WeaponIndex = <炮塔序号>`、
   `WeaponShootDataPropertyName = ["WeaponShootData_0_N"]`、
   `FireEffectTag = "weapon_effet_tagN"`），加进 `Operators` 列表，
   `Actions` MAP 加 `( "weapon_effet_tagN", <复用同组第一条弹的特效对象> )`。
4. **不要动** `MissileCarriage.WeaponInfos`：它按 `WeaponIndex`（炮塔序号）登记
   `MissileCount`，双子弹药共用同一条即可；多登记反而让引擎多画一组挂架
   （`21-depiction.md §4.3`）。`DepictionAlternatives` / Showroom / Ghosts 也不用动。

⇒ 早先担心的「`TourelleN_MissileCount` 按武器求和导致挂载模型翻倍」**没有发生**：
    计数来源是 `WeaponInfos` 而不是挂载槽数量。
    仍须实机验收的是「两个弹种是否真共用同一份弹量」与「面板名字是否跳变」。

### 每轮时长（改 `Sim` 必算）

```
每轮时长 = ShotsCountPerSalvo ÷ SimultaneousShotsCount × TimeBetweenTwoShots
```

`Sim` 翻倍 → 轮时长**减半**；总弹量 `Salves × Shots` 不变。
改小 `Sim` 后若想保持原来的轮时长，得同步把 `ShotsCountPerSalvo` 按同一倍数调回去。

### 射速取值必须落在同类武器的先例区间（0.1 是航空专属）

`TimeBetweenTwoShots` 只要求是 0.1 的整数倍（tick 约束），但**合法 ≠ 合理**。

全库 117 条 `TimeBetweenTwoShots = 0.1` 的弹药，除自建那一条外**全是航空武器/加特林**：
GAU-8 / M197 / GAU-12 / GSh-23L / NS-23 / M134 / 各型飞机炸弹挂架。**地面自动炮一律 0.2～0.3**：

| 武器 | `TimeBetweenTwoShots` | `ShotsCountPerSalvo` |
|---|---|---|
| 2A72（BMP-3 / BTR-80A，单管） | 0.3 | 5 |
| 双联 35mm（Gepard） | 0.2 | 8 |
| 四联 23mm（Shilka） | 0.2 | 10 |

**为什么仍要守这条**：这类问题静态校验查不出来，**只有实机手感能看出来**——0.1 s 的地面炮打出来像机枪，
和同类武器放在一起明显不像一个时代的装备；改数值时也不好再按先例推平衡。

> ⚠ **不要把"一轮只有一对弹道/火光"记成射速的锅。** 那是**算子类型**造成的：
> `WeaponContinuousFire` 整轮只触发一次火流，发数与弹道数天然对不上；要逐发对应必须
> `DepictionOperator_WeaponInstantFire` + `Single` 模板（`21-depiction.md §4.1b`）。
> 把 `TimeBetweenTwoShots` 从 0.1 改成 0.2 只会让那一对弹道打得慢一点，条数不会变。

⇒ 双联机炮取 **0.2**；想更密就加 `ShotsCountPerSalvo`，**不要压 `TimeBetweenTwoShots`**。

### `NbSalvosShootOnPosition` 只在 `CanShootOnPosition = True` 时可非零

写进 `CanShootOnPosition = False` 的弹药里，编译期直接硬报：

```
Invalid property in object '<anonymous> (TAmmunitionDescriptor)
GUID={...}': failed condition 'FNbSalvosShootOnPosition == 0'
```

它管的是**面射 / 压制**的连发轮数，**不是**普通交战的连发轮数 —— 想加长连射请改
`ShotsCountPerSalvo`。AP 类弹药通常 `CanShootOnPosition = False`（打不了面射），该字段必须为 0
（即整行删掉）；HE 才可以给 3～4。原版同族弹药就是这个规律：BMP-3 的 30mm AP 无此字段、HE 为 3。

## 2.5 齐射：`SimultaneousShotsCount` 与 `WeaponShootData` 的三处联动

**这是本类工程踩过三次的地方**，症状只有两种：**别的炮塔也跟着亮**，或者**部署瞬间闪退**。

`SimultaneousShotsCount`（下文 `Sim`）住在**弹药对象**里，但它控制的是**武器槽的事件表长度**。
三处必须同时成立：

| # | 位置 | 字段 | 内容 |
|---|---|---|---|
| 1 | `Ammunition(.Missiles).ndf` | `SimultaneousShotsCount` | 整数 `N`。**缺省即 1** |
| 2 | `WeaponDescriptor.ndf` → `TMountedWeaponDescriptor` | `WeaponShootDataPropertyName` | **N 个**字符串：`"WeaponShootData_0_<W>"` … `"WeaponShootData_<N-1>_<W>"` |
| 3 | `Depictions/*.ndf` → 武器算子 | `WeaponShootDataPropertyName` | 同集合、同顺序的 N 个名字（**单引号**写，见下） |

命名规则（全库 6745 槽 **0 例外**）：

```
WeaponShootData_<i>_<W>
    i = 0 … N-1        ← 齐射发序号
    W = 武器槽编号      ← == 同一个 TMountedWeaponDescriptor 里 HandheldEquipmentKey = "WeaponAlternative_<W>" 的 W
```

⚠ `W` **不是** `AmmoBoxIndex + 1`。实测只有 4465/6745 槽碰巧相等，其余不等
（`AmmoBoxIndex` 是弹药箱分组，两个槽可以共用一个箱 —— 即**双子弹药**，见 §2 术语）。

⚠ 引号风格不同：**武器槽侧用双引号 `"..."`，depiction 侧用单引号 `'...'`**。
只按一种引号写正则会漏掉另一半（写审计脚本时就因此误判过「depiction 侧没有 4 名」，实际是 409 个）。

### 引擎行为：按 i 直接索引，不是可选集合

引擎每轮按发序号 `i` 抛事件 `WeaponShootData_<i>_<W>`，然后**用 i 去索引那张名字数组**：

| 情形 | 引擎行为 | 症状 |
|---|---|---|
| 名数 **= Sim** | 每发都有人认领 | 正常 |
| 名数 **< Sim** | `names[i]` 越界，读到**相邻槽**的名字 | **串位**：那一门别的炮塔跟着亮、并飞出弹道（不报错） |
| 名数 **> Sim** | 多出的名字永远等不到事件 | 不报错，但对不上账；改 Sim 时必须一起裁 |
| 名数 = Sim 但 `NbProj > 6` | 实例化期解析不到第 7+ 个事件槽 | **点选部署瞬间 CTD** |

### 全库实测（6745 个挂载槽）

```
弹药 Sim 分布：1 → 1153 个弹药对象 / 2 → 38 / 3 → 1 / 4 → 1 / 6 → 1
```

- **`Sim` 上限 6**（原版只有 1/2/3/4/6 这五档）
- 名数 == Sim 的槽：6743 / 6745。**唯一 2 例不符是 Maelstrom 的 `Ammo_SE_Commando(_HE)`
  （Sim=2 只登记 1 个名），同炮塔同 `EffectTag` 所以肉眼看不出来**
- 特例：车载烟雾弹 409 个槽是 **Sim=4 / 4 个名**（`Ammo_SMOKE_Vehicle_Grenadex8`，一次抛 4 管）；
  它 `EffectTag` 不参与 depiction 的 `Actions` 映射，但 SD 名照样登记 4 个 —— 别拿它当「不用齐」的先例

### 自查（改任何 `Sim` 之前跑一遍）

```bash
P="<python>"; A="<skill>/scripts/sim_sd_audit.py"
"$P" "$A"                              # 全库审计，rc=1 即有武器槽名数 ≠ Sim
"$P" "$A" --unit SE_SuperDestroyer_US  # 只看某个武器管理器
"$P" "$A" --verbose                    # 打印每个槽的 Sim / 名数 / 名单
```

输出直接给出 `Sim × 名数` 交叉表、尾号是否等于武器号、`i` 是否 0..N−1 升序。

### 禁止动作

- **只改弹药 `Sim`，不改两处名字数组** —— 三次故障里有两次是这么来的（一次改大、一次改小）
- 只改武器槽名数、不改 depiction 算子名数
- 为「打得更密」去加 `Sim`（>6 直接部署 CTD）。要密就调 `TimeBetweenTwoShots`，不是加 `Sim`
- 把 `NbProj` 当成「必须等于 Sim」—— `NbProj` 是「一次事件出几团火光」，取 1/2/4 都有原版先例
  （`Ammo_SE_OrbitalNapalm` 是 Sim=1 / 1 个名 / `NbProj=2`：一次事件、双管各一团）


## 3. 字段语义表

| 字段 | 语义 | 取值 / 约束 |
|---|---|---|
| `MinMaxCategory` | 类别，决定**炮塔形态**与换枪可行性 | 必须与原槽一致 |
| `ProjectileType` | `EProjectileType/Obus` / `GuidedMissile` / `Roquette` / `Bombe` | 直射三件套见下 |
| `Arme` | 伤害族 | 高爆 `TDamageTypeRTTI(Family=DamageFamily_he Index=1)`（229 例统一 Index=1） |
| `PhysicalDamages` | 直伤 | **AP 家族恒 1.0 是归一化基准**，HE 才是绝对值 |
| `RadiusSplashPhysicalDamagesGRU` | 溅射半径 | HE 主流档 16～22 |
| `SuppressDamages` / `RadiusSplashSuppressDamagesGRU` | 压制 / 压制半径 | |
| `ShotsCountPerSalvo` | 每次几发 | 见总弹量公式 |
| `SimultaneousShotsCount` | 同时发射几发 | 齐射类；**与两处 `WeaponShootData` 名数强联动，见 §2.5**。上限 6 |
| `AffichageMunitionParSalve` | UI 显示 | **自建弹药 == Shots** |
| `MaximumRangeGRU` | 射程 | |
| `MaximumRangeAirplaneGRU` / `MaximumRangeHelicopterGRU` | 能否打空中 | **是否为 0** 是唯一判据 |
| `WeaponCursorType` | 光标 | `Weapon_Cursor_GroundMissile` / `Weapon_Cursor_FastCanon` / `Weapon_Cursor_CorrectedArtillery` |
| `IsFireAndForget` | 射后不理 | 位置在 `ShotsBeforeMaxNoise` **之后** |
| `DistanceToTarget` | 命中率是否随到目标距离变化（嵌在 `HitRollRuleDescriptor = TDiceHitRollRuleDescriptor` 内部，全库唯一的命中掷骰模型） | `True`(1071) 掷骰含距离因子、命中率随射程衰减；缺失/False(77) 命中率与距离无关。自寻的导弹/制导炸弹保持缺失 |
| `CanShootOnPosition` + `NbSalvosShootOnPosition` | 可直接点地面（**两行相邻**） | N 原版只取 **1~4** |
| `TraitsToken` | 标签 | F&F 弹一律 `['MOTION','F&F']`；F&F 弹 `PiercingWeapon=False` |
| `PiercingWeapon` | 是否穿透 | |
| `ImpactHappening` | 弹着特效键 | 必须已在 `MimeticImpactMapping.ndf` 注册；**枚举值不许臆造**，见 §3.1 |
| `TirIndirect` | 间瞄 | 与 `Weapon_Cursor_CorrectedArtillery` 搭配 |
| `TimeBetweenTwoShots` | 射速间隔 | **下限 0.1，且必须是 0.1 的整数倍**（= gameplay tick）。0.15 / 0.25 / 0.35 这类值**非法**，启动期 Fatal：`TimeBetweenTwoShots (%1) must be multiple of a gameplay tick length (%2s)` |
| `TimeBetweenTwoSalvos` | 齐射间隔 | 粒度 0.05 |
| `TimeBetweenTwoFx` | 特效间隔 | **最小 0.05**（全加特林） |
| `ShotsBeforeMaxNoise` | 连发上限 | |
| `IsHarmlessForAllies` | 不伤友军 | 火焰/爆炸类常用 |

> **`DistanceToTarget` 实测结论（base.zip 全库只读勘查，未改任何 NDF）**：全库命中掷骰模型只有 `TDiceHitRollRuleDescriptor` 一种；1,148 个掷骰块中 **1,071** 带 `DistanceToTarget = True`（命中率随到目标距离变化，瞄射类弹药），**77** 不带（命中率与距离无关）。后者两类成因：① 射后不理自寻的（AA / AGM / SAM / 制导炸弹——命中由制导决定，制导炸弹借超长制导时间实现）；② 狙击步枪 / 自动榴弹 / 迫击炮等"距离无关精度"模型。
> **改弹药时**：新建常规瞄射弹药 → 设 `True`（精度随射程衰减）；新建自寻的导弹 → 保持缺失（=False）。该字段在命中掷骰模型内，与 loft 设计器操作的 `TGuidedMissileMovementConfigDescriptor`（运动/弹道）**正交**，互不影响。

### 3.1 ⭐ `ImpactHappening`：只能从表里挑，不许按「几代弹」推

**【原理】** 这个字段是**命中事件名**。运行期引擎拿它去
`GameData/Generated/Gameplay/Gfx/MimeticImpactMapping.ndf`（`TMimeticWorldDescriptor` 那张 MAP）
里查表；查不到就当场 Fatal：

```text
Fatal error
happening '<你写的名字>' requested and missing in Mimetic World Descriptor
```

**只在真的打中那一刻才炸** —— 加载、编译、静态检查全绿也发现不了，
所以「编译 rc=0 + 能进游戏」完全不能证明这个字段对。

**【操作】** 定值前先把白名单抓出来，再挑同名族的现役条目：

```python
import re
src = open(r"C:/.../warno_base/GameData/Generated/Gameplay/Gfx/MimeticImpactMapping.ndf",
           encoding="utf-8-sig", errors="replace").read()
legal = set(re.findall(r"\(\s*'([^']+)'\s*,", src))   # 156 条
```

实测分族（**别跨族借**）：

| 族 | 合法取值 |
|---|---|
| 地面反坦克（地发导弹） | `MissileATGMGen1` / `MissileATGMGen2` / `MissileATGMGen3` —— **无 Gen4 / Gen5** |
| 空对地 | `MissileAGMGen1` / `Gen2` / `Gen2TopHEAT` / `Gen3` / **`Gen4`** / `MissileAGMGros` |
| 对空 | `MIssileAASPARROW` / `MIssileAASIDEWINDER` / `MIssileAAAMRAAM`（注意原版就是三连大写 I 的拼写）/ `MIssileAA9K38Igla` / … |
| 炸弹 | `MissileBombeGBU250Kg` / `500Kg` / `1000Kg` / `1500Kg` |

> LOSAT（2026-11-11）踩过：源 AIM120 的 `'MIssileAAAMRAAM'` 被我改成按「四代反坦克」推的
> `'MissileATGMGen4'` —— 该名字不存在，弹飞到目标上空才 Fatal。
> 定稿改 `'MissileATGMGen3'`（现役最高一代地发 ATGM）。

**【验收】** 写盘后扫一遍本 Mod 全部 `ImpactHappening`，逐个比对白名单：

```python
bad = {v for p in Path(MOD, "GameData").rglob("*.ndf")
       for v in re.findall(r"ImpactHappening\s*=\s*'([^']+)'",
                           p.read_text(encoding="utf-8", errors="replace"))
       if v not in legal}
assert not bad, bad
```

⚠ 别用 `grep "Missile..."` 抓白名单 —— 表里还有大量 `Canon*` / `Roquette*` / `Bombe*` / `Mortier*` / `DestructionUnite*` 条目，
只按 `Missile` 前缀过滤会把合法值误判成非法（本项目就走了一次这个弯路）。

### 建「导弹类 / 制导炮弹」：起点在 `AmmunitionMissiles.ndf`

**不要**拿 `Ammunition.ndf` 的榴弹去改 `ProjectileType` —— 两类弹药带的是两套字段集：
榴弹类有 `PitchForParabolic` / `CorrectedShotDispersionMultiplier`，导弹类有
`MaxAccelerationGRU` / `MissileTimeBetweenCorrections` / `MissileDescriptor`。

正确做法（红土地 Krasnopol 实测）：以导弹文件里现成的导弹类弹药为起点
（弹药层可用 `Ammo_SSM_MGM52_Lance`，它带全导弹类字段且 `TirIndirect=True`），
**只从榴弹借用共用参数**：伤害 / 物理 AOE / 压制 / 散布 / 弹着特效 / `FxPower` /
射击节奏 / `SupplyCost` / `HitRollRuleDescriptor` / 攻顶与命中位置判定 / 口径本地化 token。
对象也放在 `AmmunitionMissiles.ndf`（导弹类弹药的家）。

面板归类由 `WeaponCursorType` + `MinMaxCategory` 决定，**与投射类型无关**：
制导炮弹照样写 `Weapon_Cursor_CorrectedArtillery` + `MinMax_obusier`。
半主动制导（激光）一律**不写** `IsFireAndForget`（`Ammo_AGM_Kh29L` / `Ammo_Bomb_GBU_12_x1` 全 0 例）。
语义与字段集对照见 `60-numbers.md §1`。

### 直射三件套（间瞄改直射时）

`ProjectileType = Obus` + `PitchForParabolic = 0` + **删** `CorrectedShotDispersionMultiplier`。
三件必须一起做，少一件启动期 Fatal。
（被禁的是**弹道类型**，不是「间瞄」——68 个 `Bombe` 航弹全是 `TirIndirect=True`。）

### 高爆战斗部

`Arme = TDamageTypeRTTI(Family=DamageFamily_he Index=1)`，Index 一律取 1（229 例统一）。
原版 HE 主流档：直伤 0.9～1.25 + 溅射 16～22 + 压制 150/40。

**面板上的「高爆」数字就是 `PhysicalDamages` 本身**，没有换算系数（本项目实测：
`PhysicalDamages = 0.9` 的弹面板显示 0.9）。想要面板显示 15 就写 `15.0` ——
这个档位有原版先例（`Ammo_Bomb_KAB_500Kr_x1` / `Ammo_Bomb_CPU_123_x1` 都是 15.0）。
「取消穿甲」= 换 HE 族（HE 族在 `WeaponConstantes.BlindagesToIgnoreForDamageFamilies`
里本就忽略 `ResistanceFamily_blindage`）+ `PiercingWeapon = False` + `TraitsToken` 把 `HEAT` 去掉。

## 4. 先例统计（动手前的必做步骤）

0 先例 ≠ 不能做，但**必须写进验收清单**，并准备好回退方案。统计用 `scripts/ndfq.py`：

```bash
P="<python>"; Q="<skill>/scripts/ndfq.py"

# 某类弹药的全部取值分布
"$P" "$Q" stat GameData/Generated/Gameplay/Gfx/Ammunition.ndf \
      --is TAmmunitionDescriptor --group MinMaxCategory,ProjectileType,WeaponCursorType

# 「这个字段组合有没有先例」：先 list 出 CanShootOnPosition=True 的，再看它们的类别
"$P" "$Q" find GameData/Generated/Gameplay/Gfx/Ammunition.ndf \
      --is TAmmunitionDescriptor --where CanShootOnPosition=True \
      --show MinMaxCategory,ProjectileType,WeaponCursorType,NbSalvosShootOnPosition

# 某字段的取值直方图（判断自己的取值是否越界）
"$P" "$Q" stat GameData/Generated/Gameplay/Gfx/Ammunition.ndf \
      --is TAmmunitionDescriptor --group NbSalvosShootOnPosition
```

**已知先例边界（本类工程实测）**：

| 组合 | 先例数 | 结论 |
|---|---|---|
| `CanShootOnPosition=True` + `GuidedMissile` | 10（全是 GBU/KAB 制导炸弹） | 可做 |
| `MinMax_ATGM` + 可对地 | **0** | 待验（已有实机通过案例） |
| `CanShootOnPosition` + `IsFireAndForget` | **0** | 待验（已有实机通过案例） |
| `IsFireAndForget=True` 全量 | 58（AAM/SAM/SEAD/AGM） | 可做 |
| 地面 `MinMax_Gatling` | **0**（409 例全在飞机） | 待验（已有实机通过案例） |
| `MinMax_AutocanonHE` 地面 | 169 | 有弹不开火时的替代方案 |

> 教训：**「原版 0 先例」只能产出「待验清单」，不能产出「不支持」的结论。**
> 要断言不支持，必须找到引擎硬校验（启动 `Fatal error` / 加载 `Invalid property` / 进游戏闪退）。

## 5. 显示名 token：必须新建

**沿用克隆源的 `Name` 会改掉所有共用该 token 的原版弹药面板。**
一个 token 常被多个原版弹药共用（例：`MNXRQCDUND` 被 GAU8 HE/AP + 我方两条共用）。

> ⚠ **双子弹药是例外（而且是硬约定）**：同槽多弹种在面板上**共用一个槽位**，
> 所以所有弹种必须共用**同一个** `Name` token，**不要**给第二个弹种另建显示名。见 §5.3。

规则：
- 格式 **10 位大写字母**，字母表 `A-Z` 去掉 `I` / `O`（base32 变体）
- > 10 字符 → `Value is too long for a TLocalisationToken`（CSV 里的引号**不算**字符）
- **硬约束只有「≤10 字符」**；字符集不限于字母。可读的自造名实测可用：
  `OBJ685GUN`（9 位，含数字，2026-11 编译通过并已写进 `UNITS-DEV.dic`，面板显示待实机确认）、
  `KRSN2A36`、`MGM52CAL`、`9M79TYPE`。可读名比哈希名好维护，**优先用可读名**。

### 5.1 自造 token **必须**在 `UNITS.csv` 里登记一行（漏了必崩）

`Name` 不是「随便一个唯一串」，它是**字典键**。引擎在打开单位面板时按 token 查字典列表 `UNITS`，
查不到就当场弹窗，**不是**编译期错误：

```
Fatal error
Dictionary error : No string found for token 'KRWREMVCJZ' in dictionary list 'UNITS'.
```

所以新建弹药时 `UNITS.csv` 要加一行 `TOKEN;显示名`（同一个文件、同一种写法，和单位名混排）：

```csv
KRWREMVCJZ;30mm AP
WWRFXHPUAA;30mm HE
NVVCYZQSPN;S-8 80mm
```

三个必须知道的点：

1. **`UNITS.csv` 不是「查重用的名单」，是注册表**。旧版本本文件写「查 `UNITS.csv` 不重复即用」，
   那是误读——不重复只保证不撞车，不等于能解析。
2. **编译期才生成字典**。产物是 `Gen/Localisation/Localisation/Test/UNITS-<LANG>.dic`（7 个语言包），
   **改完 CSV 必须重新编译**，否则跑的还是旧字典。`.dic` 头是 `TRAD` + u32 条目数 + 每条目
   `hash / … / offset / length`，文本以 **UTF-16LE** 存在文件里。
3. **崩在「点选那一刻」是正常的**。字典是懒查的——单位能显示在列表里、能买、能部署，
   直到你打开详情面板看弹药行才炸。所以「编译通过 + 列表正常」不能证明弹药名没问题。

### 5.2 自查脚本（新弹药写完就跑）

```python
# 1) 新对象的 token 里，哪些是全库唯一的（= 自己造的，必须登记）
# 2) 自己造的 token 是否都在 UNITS.csv 里有行
# 3) 编译后 UNITS-DEV.dic 里能否原样找到其 UTF-16LE 文本
import re, os
R = r"D:/Steam/steamapps/common/WARNO/Mods/ShowCase-FPV Strike"
csv = open(os.path.join(R, "GameData/Localisation/Test/UNITS.csv"), encoding="utf-8").read()
have = {l.split(";")[0].strip() for l in csv.splitlines()[1:] if ";" in l}
dic = open(os.path.join(R, "Gen/Localisation/Localisation/Test/UNITS-DEV.dic"), "rb").read()
for tok, text in [("KRWREMVCJZ", "30mm AP")]:
    print(tok, "in csv:", tok in have, "| text in dic:", text.encode("utf-16-le") in dic)
```

> 判「是不是自己造的」：全库 `GameData/Generated/**/*.ndf` 里该 token 只出现 1 次 ⇒ 自己造的；
> 出现多次 ⇒ 原版共用 token，能解析，不用登记。

### 5.3 双子弹药：`Name` token 必须完全一致

双子弹药在武器面板上**共用一个槽位**，显示名只有一个。因此：

- 组内所有弹种的 `Name` 必须**逐字符相同**，用第一条弹的 token
- **不要**为「HE 版 / 烟雾版 / 增程版」另建显示名 —— 面板上会出现两个名字、切换时跳变
- 原版先例（三组，全部同 token，无一例外）：

| 弹组 | token |
|---|---|
| 125mm 2A46M AP + HE | `KUPNLKSDNF` |
| 122mm 2A18 榴弹 + 烟雾 | `WQEYYEBLDI` |
| 120mm 2A60 榴弹 + 烟雾 | `CWBCQJBMHY` |

- 若第一条弹的 token 是自造的（在 `UNITS.csv` 有行），组内共用这一行即可，
  **不要重复登记**（token 是字典键，重复行没有意义）
- 判据仍是「整组照抄」：抄原版双子弹药时，`Name` 一起抄，不要只抄一半

### 5.4 克隆新建弹药对象（原版还要被别的单位用时）

要给本单位换一款「同名不同数」的弹药（如 105mm M68 的 LR 增程版），而原版弹药对象
还被 M1/M1IP 等 5 处引用 —— **禁止改原版对象**（铁律 8），克隆一对新的：

**【操作】**（2026-11-10 LAV-600 `M68(LR)` 实测定稿，脚本思路 `clone_ammo_*.py`）

1. **整块复制**原版 AP / HE 两个对象到文件尾部（同一弹种对、同一弹药箱结构），
   对象名加后缀区分（`Ammo_Canon_AP_105mm_M68_LR`）；
2. `DescriptorId` 换**新生成的 GUID**，写完做全库唯一性自检（新 GUID 0 命中）；
3. **AP / HE 的 `Name` 改成同一个新 token**（双子弹药硬约定，§5.3）——
   面板上双弹共用一个槽位名，各建各的会在切弹种时名字跳变；
4. `UNITS.csv` 登记一行（`M68LR;M68(LR)`，可读名优先，≤10 字符）；
5. `WeaponDescriptor_<单位>` 里指向新对象；**`EffectTag` 不动**——它引用的是
   开火特效对象（`FireEffect_...`），与弹药数值无关，跟着换只会多复制一堆特效；
6. 写回前探测换行（块间分隔是空行 + CRLF，写死 `"\n"` 会留裸 LF）。

**【验收】**：① 全库弹药对象数 +2、括号结构逐块闭合（逐对象数括号深度，970 个零异常）；
② 全库 GUID 零重复；③ `sim_sd_audit --unit <名>` 全绿；④ 编译后 `.dic` 里能查到新显示名
（UTF-16LE，**改 CSV 不重编等于没改**）。

> 自查判据：**某 token 在 mod 的 `Generated/` 里只出现 1 次 ≠ 自造 token**——
> `Generated/` 是原版数据的副本，token 文本可能在本体字典里（2026-11-10 用户纠正：
> 原版单位的面板名不需要在 UNITS.csv 登记）。只有「本单位新建的 token」才必须登记。

## 6. 台账

每次克隆新弹药**必做**：写入 `doc/武器弹药台账.csv`（6 列：HD2武器 / 模板弹药自然语言 / 模板内部名 /
备注 / 完成状态 / 新弹药内部名）。

- 编码：UTF-8 无 BOM + **LF**（写入前探测）
- 备注里的双引号必须转义 `""`（裸 `"` 会让 `csv.reader` 拆列）
- 写完 `csv.reader` 复核：列数恒定、目标行含新内容、**其他行零改动**
- 按**第 1 列名字**匹配，不按行号猜

## 7. 挂载到哪里

| 目的 | 做法 |
|---|---|
| 换掉某槽的弹药 | 改该 `TMountedWeaponDescriptor.Ammunition` |
| **做双子弹药**（同炮塔第二个弹种，共用弹池） | 在该炮塔里再加一个 `TMountedWeaponDescriptor`，**`AmmoBoxIndex` 与第一条相同**；`Salves` 长度不变（见 §2 术语）。还要配新号的 `WeaponAlternative_N`、`WeaponShootData_0_N`、depiction Operator + `Actions` 映射（机载四件套见 §2 表格，**不要动 `MissileCarriage.WeaponInfos`**） |
| 同炮塔第二个弹种，但**独立弹池** | 同上，但 `AmmoBoxIndex` 换新值，并在 `Salves` 末尾补一个元素 |
| 新开一个炮塔槽 | 要同时改 `Salves` / `SalvoIsMainSalvo` 长度、`WeaponAlternative_N`、`WeaponShootData_0_N`、depiction Operator + `Actions`，且**模型要有对应骨骼**（缺骨骼 = 有弹无火） |

新开炮塔前先查模型骨骼：`tourelleN` / `fx_tourelleN_tir_01` 是否存在。
ASU-85 只有 `tourelle1..4`，加 `tourelle5` 会变成有弹无锚点。

自建网格上的锚点可以直接加（用 `scripts/fbx_anchors.py check` 验），
但**必须挂在炮塔旋转链下**才会跟着转，见 `23-mesh-import.md §2.1`。
