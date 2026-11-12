# depiction 四型（外观）

外观分**四类受众**，文件、结构、能否共享都不同。**一个都不能类推**。

| 型 | 能否共享 | 对象数 | 主文件 |
|---|---|---|---|
| 载具 | **绝对不能**（2208 个载具 `MimeticName` 重复组 = 0） | 6～9 | `Depiction{Alternatives,Vehicles,Ghosts,VehiclesShowroom,Humans}.ndf` |
| 步兵 | 可以（55 组重复） | 共享 | `DepictionHumans.ndf` + `InfanterieWeaponsUnites.ndf` |
| 飞机 | 不能 | **12** | `DepictionAerialUnits.ndf` + `...Showroom` + `Alternatives` + `Ghosts` |
| 舰船 | 不能 | 同载具 | 同载具 |

> **判据**：`MimeticName` 重复组数。载具类 0，步兵 55。〔共享 = 改一个污染全族〕

## 1. 载具：七件套

| 文件 | 对象 | 缺了会怎样 |
|---|---|---|
| `DepictionAlternatives.ndf` | `Alternatives_<名>`（三档 LOD） | **白模** |
| `DepictionVehicles.ndf` | `DepictionOperator_<名>_WeaponN`（每挂载 1 个） | **有枪无火** |
| `DepictionVehicles.ndf` | `unnamed TacticVehicleDepictionRegistration` | **隐形**（地图上什么都没有） |
| `DepictionGhosts.ndf` | `unnamed GhostVehicleDepictionRegistration` | 残骸/幽灵态异常 |
| `DepictionHumans.ndf` | `HumanSubDepictions_<名>` + `HumanSubDepictionsShowroom_<名>` + 1 条 catalog | **车内没人** |
| `DepictionVehiclesShowroom.ndf` | `ShowroomVehicleDepictionRegistration` | 展厅不显示 |

主注册块字段：

```ndf
unnamed TacticVehicleDepictionRegistration
(
    BlackHoleKey = "<Key>"
    Alternatives = $/GFX/Depiction/Alternatives_<名>
    Operators =
    [
        $/GFX/Depiction/DepictionOperator_<名>_Weapon1,
        ...
    ]
    Actions = MAP
    [
        ( "weapon_effet_tag1", Weapon_Autocanon_30 )   ← ★ 开火视觉真开关
    ]
    SubDepictions / SubDepictionGenerators = ...
)
```

### 对象数公式

| 情形 | 对象数 | 组成 |
|---|---|---|
| 武装 + 有乘员 | **7 + N** | Alternatives + N×Operator + Tactic + Ghost + HumanSub + ShowroomHuman + Showroom (+1 catalog) |
| 无武器 + 有乘员 | **6** | 少一个 `Weapon1` 操作员 |
| 武装 + 无乘员（`HasServants=False`） | **7** | 3 Operator + 3 注册 + Alternatives，**无** HumanSub / catalog |
| 多炮塔无乘员（5 挂载） | **9** | Alternatives + 5 Operator + 3 注册 |

### 三个坑

1. **catalog 条目要插进** `TTransportedInfantryCatalogEntries.Entries`（块在**文件尾**），
   不能 append 到文件末。
2. **`Modele_*` / `CoatingName` 模板名不得替换** —— 换名 = 指向不存在的 mesh/材质。
   用占位符保护后整体换名。
3. 三档 LOD 的 mesh 名规律：`Modele_<名>`、`Modele_<名>_MID`、`Modele_<名>_LOW`，三档必须都存在。

## 2. 步兵：共享 + 五 key 同源

```
SoldierBlackHoleKey
  → TTransportedInfantryCatalogEntries
      → UnitMimetic
          → Alternatives + SubDepictions
              → AllWeaponAlternatives_*
                  → Modele_*
```

- `squad_*` 只挂音效、**不画模型** → 换模型只改 `SoldierBlackHoleKey`
- `WeaponAlternative_N` 与 `WeaponShootData_<i>_N` **共用同一个 N**（武器槽编号），但 **N ≠ `AmmoBoxIndex`+1**：
  实测 6745 个槽里只有 4465 槽恰好满足 `box+1 == N`，其余 2280 槽不等（`AmmoBoxIndex` 是弹药箱分组，可与其他槽共用）。
  齐射时 `i = 0…Sim−1` 必须齐备，见 `22-ammo.md §2.5`
- 人形与枪**独立随机组合** → 不能锁「某兵拿某枪」
- `ConditionalTags` 是动画覆盖（smg/mmg/bazooka/grenade），不是槽号
- 换枪判据：新弹药 `MinMaxCategory` == 原槽类别
- `Selector` 命名 `X_YY`：X=UniqueCount，YY=变体总数
- **4 槽不是硬限**（舰船 6 槽，本项目 5 槽已过）

## 3. 飞机：12 对象 / 6 文件

| 对象 | 文件 | 缺了 |
|---|---|---|
| `Op_*_Weapon1..4`（2×`WeaponContinuousFire` + 2×`WeaponMissileCarriageFire`，`FireEffectTag="weapon_effet_tagN"`） | `DepictionAerialUnits.ndf` | 有枪无火 |
| 主 `unnamed TacticAerialDepictionRegistration`（`Deviator=DepictionDeviator_Airplane`、`Selector=SpecificMechanicalDepictionSelector`、17 项 `Operators`、`Actions=MAP[(tag,Weapon_xxx)]`、`SubDepictions=[pilot]`、`SubDepictionGenerators`） | 同上 | 隐形 |
| `Alternatives_*` | `DepictionAlternatives.ndf` | 白模 |
| `unnamed GhostAerialDepictionRegistration` | `DepictionGhosts.ndf` | 残骸异常 |
| `unnamed ShowroomAerialDepictionRegistration`（含 `ShowroomLandingGear`） | `DepictionAerialUnitsShowroom.ndf` | 展厅不显示 |
| `MissileCarriage_*` ×2 + `SubGenerators_*` ×2（`Missiles[]` 实例化、`PhysicalProperty="TourelleN_MissileCount"`） | 同上 | **机腹无弹** |

飞机可**独立购买**（普通 pack），不受载具运输互斥约束；不进 `StandoutUnits`，`DeckSerializer` 仍要 `UnitId`。
`OrderAvailability` 纯数组一行、无 GUID、不用 `export`。

## 3b. 无武器运输直升机：4 对象 / 4 文件

**不要照抄上面的 12 对象**——那套是为「有武器 + 有挂载」的固定翼准备的。

| 对象 | 文件 | 缺了 |
|---|---|---|
| `Alternatives_*`（3 档 LOD） | `DepictionAlternatives.ndf` | 白模 |
| `unnamed TacticAerialDepictionRegistration`（`AdditionalTextures=$/M3D/Shader/HelicoDestTextures`、`Selector=SpecificMechanicalDepictionSelector`、`DepictionOperator_HelicopterLanding`、`DepictionOperator_Rotors`(内联 `THelix` 列表)、`Actions` 只有特技/干扰弹、`SubDepictions` 锚点 `pilot`/`pilot2`） | `DepictionAerialUnits.ndf` | 隐形 / 无旋翼 |
| `unnamed ShowroomAerialDepictionRegistration`（`BlackHoleKey="showroom_<key>"` + 同一个 `MeshDescriptor` + 两个 `TCosmeticFixedBoneRotationOperatorDesc` 把旋翼摆到静止角） | `DepictionAerialUnitsShowroom.ndf` | 展厅不显示 |
| `unnamed GhostAerialDepictionRegistration`（`Alternatives` + `BlackHoleKey` + `Selector`） | `DepictionGhosts.ndf` | 残骸异常 |

- **不需要 `DepictionHumans` catalog**（载具要 `TTransportedInfantryEntry`，直升机不要）——乘员挂在 Tactic 注册的 `SubDepictions`
  上，指向共享的 `Pilot_Pilote_Helico_US`。所以比「无武器载具 6 对象 + catalog」还少 2 个对象。
- `THelix` 里的骨骼名（`helice_ls_1/2`、`bloc_moteur_1/2`）是**克隆源模型专有**，换模型必须重查，不能照抄。
- 判「这个直升机有没有武器」搜单位块里的 `WeaponDescriptor_` 引用，**不是**搜 `TWeaponManagerModuleDescriptor`
  （该类型名在单位块里从不出现）。US 侧无武装运输机只有 `CH47_Chinook_US` / `CH54B_Tarhe_trans_US` / `UH1N_TwinHuey_US`。
- 飞行单位移动差异：`TGenericMovementModuleDescriptor.PathfindType=~/Pathfind/PathfindTypes/Flying` 才是「直线穿越地形」的来源；
  `THelicopterMovementModuleDescriptor` 只给速度与高度。


### 3c. 武装直升机（炮塔 + 多槽挂载）

比 §3b 多出来的全是"武器侧"：

| 对象 | 文件 | 缺了会怎样 |
|---|---|---|
| `Op_*_Weapon1..N`（机炮 `WeaponInstantFire` / `WeaponContinuousFire`；导弹火箭 `WeaponMissileCarriageFire`） | `DepictionAerialUnits.ndf` | 有枪无火 |
| 主 `TacticAerialDepictionRegistration`（`Operators` 列表 + `Actions = MAP`） | 同上 | 隐形 |
| `Alternatives_*` | `DepictionAlternatives.ndf` | 白模 |
| `ShowroomAerialDepictionRegistration` | `DepictionAerialUnitsShowroom.ndf` | **点进军械库那一刻 CTD** |
| `GhostAerialDepictionRegistration` | `DepictionGhosts.ndf` | **部署放下单位那一刻 CTD** |
| `MissileCarriage_*` + `SubGenerators_*` | `MissileCarriage.ndf` / `MissileCarriageDepiction.ndf` | 机腹无弹 / 挂架错位 |

#### 「一个单位四处注册」+ 崩溃原文对照

| 原文 | 缺的是 | 在哪个场景炸 |
|---|---|---|
| `Unknown unit mimetic: 'showroom_<key>'` | Showroom 注册 | 点进军械库 |
| `Unknown unit ghost mimetic: '<key>'` | Ghost 注册 | 部署落地瞬间 |
| `No pylon with requested slot count (1) found in PylonSet` | 挂架集里没有能挂 1 槽的挂架 | 启动 |
| `No missile carriage slot found in skeleton for weapon index N` | `WeaponInfos` 没第 N 槽，算子却还是 `MissileCarriageFire` | 启动 |

> **记法**：比「12 对象」更好用的是「四处注册」——`DepictionAerialUnits` / `...Showroom` /
> `DepictionGhosts` / `UniteDescriptor`。少任何一处都不是"少显示一个东西"，而是**在某个具体场景 CTD**，
> 而且每个场景不同。报错原文里直接带 key，照着表填即可。

#### 炮塔三层（照官方 Mi-24VP）

```
Tourelle_01 (EMPTY, 绕 Z 回转)
 └ Axe_Canon_01 (EMPTY, 绕 Y 俯仰)
    └ Canon_01 (MESH, 沿 X 后坐)
       └ Fx_Tourelle1_Tir_01 (EMPTY, 炮口)
```

- 前两层**必须是 EMPTY**，第三层才是网格。
- 节点名被算子**写死**：`DepictionOperator_Turret_1_Aim` 的定义里就是
  `ZAxisNode='tourelle_01'`、`YAxisNode='axe_canon_01'`，**调用处不带参数**——名字只能长这样。
- 可俯仰用 `TTurretTwoAxisDescriptor`，单轴用 `TTurretUnitDescriptor`。
- 射界照同型机抄（Mi-24VP）：`AngleRotationMax = 3.8397`（±110°）、
  `AngleRotationMaxPitch = 0.1745`（+10°）、`AngleRotationMinPitch = −1.309`（−75°）、
  `VitesseRotation = 2.0944`（120°/s）。
- ✅ **`AngleRotationMax` 实测 = 全角（弧度）**：填 `3.8397` 时炮管转到 **±110° 就停住**，不会绕圈（Ka-58 实机确认）。
  早期一度怀疑「要填半值」，原因是 Mi-24P 那个 `7°` 看着像另一种量纲——它的真实含义是「几乎不转」（固定前射），
  不是半角。**别再折半。**

> 机炮槽**不需要** `MissileCarriage` 条目——挂架与发射点都只对登记过的武器生效，见 §4.3。

---

## 4. 开火视觉：四段链 + 三套开关

```
ImpactHappening（弹着，MimeticImpactMapping.ndf）
  └─ EffectTag → FXWeapon_*（枪口焰/拖尾，DepictionFXWeapons.ndf）
       └─ DepictionWeaponBlock（组合块）
            └─ depiction 注册的运算符 + Actions = MAP[(tag, Weapon_X)]   ★ 最常缺
```

| 受众 | 真开关 | 校验方式 |
|---|---|---|
| 载具 / 飞机 | depiction 的 `Actions = MAP[("weapon_effet_tagN", Weapon_xxx)]` | **不查表**（直接写在注册块里） |
| 步兵 | `AllWeaponSubDepiction_*.Operators`（`FireEffectTag` + `WeaponShootData_0_N`） | **必须查注册表** |
| 弹药命中 | `ImpactHappening` | 查 `MimeticImpactMapping.ndf` |

**步兵注册表** = `InfanterieWeaponsUnites.ndf` 末尾的 `unnamed TMimeticWorldHappeningRegistration`（约 177 条，只覆盖步兵，无机炮）。
缺键补：`( 'FireEffect_<弹药去Ammo_>', FXWeapon_<同名> )`。
缺失时报 `happening 'X' requested and missing in Mimetic World Descriptor`。

⚠ **校验必须查注册表，不能查「这个字符串在 WD 里出现过」** —— 后者是自证，必然通过。

⚠ **换火光必须新建一份注册**：`Actions` 是按注册共享的，借用会把**原单位**一起改掉。

**`Anchors` 是骨骼名（空物体名）**：全库 430 处空中开火锚点**全部**是 `fx_tourelle1_tir_01`，另 `tourelle2/3` 共 16 处。
模型没有对应骨骼 → 只能换模型，不是加一行运算符能解决的。
名字是**加载时硬校验**，缺一个即 CTD（编译期不查）——补名 / 摆位 / 层级见 `23-mesh-import.md §2`。

⚠ **算子类型决定读不读 `Anchors`**：`WeaponInstantFire` 读；`WeaponMissileCarriageFire` 由
`Connoisseur` 定发射点、**完全不读**。想让武器从自定炮口出来，先确认算子类型，见 `24-rig-parts.md §7`。

### 4.1 两支字段：`NbFX`（Continuous）vs `NbProj`（Instant）

同一次开火要「几个炮口同时冒火」，两个算子的字段**语义不同、互不通用**：

| 算子 | 字段 | 语义 | 原版先例 |
|---|---|---|---|
| `WeaponContinuousFire` | `NbFX = N` | 进入开火状态时点亮 N 个锚点的**持续火流** | Gepard 双联 35mm：双锚点 + `NbFX = 2` |
| `WeaponInstantFire` | `NbProj = N` | **每次触发出 N 个投射物光效** | 烟雾弹 `NbProj = 4`；常规机炮 `NbProj = 1` |

- `WeaponContinuousFire` 的 `WeaponShootDataPropertyName` 是**单个字符串** `"WeaponShootData_0_N"`，
  并且必须带 `WeaponActiveAndCanShootPropertyName`；
  `WeaponInstantFire` 是**数组** `['WeaponShootData_0_N', ...]`，长度 == 弹药 `SimultaneousShotsCount`。
- **双联炮不靠 `NbWeapons = 2`**：原版双联炮（Gepard / ZSU-57-2 / 2A72 双联）的 `NbWeapons` 都是 1，
  "两门"只体现在**两个锚点**上。至于用哪个算子，看**这一轮的发数要不要数清**，**不看管数**（判据见 §4.1b）。

> **双联 ≠ 双倍火力。** 引擎里一门"武器"一次射击事件只出 **1 发弹**（`SimultaneousShotsCount = 1` 是
> 全库机炮的常态；全库 31 条 `Sim=2` 全是火箭/集束，**机炮零先例**），"联"只体现在**火光落在几个锚点**上。
>
> | 想让双联炮"看起来/打起来"是两门 | 做法 | 代价 |
> |---|---|---|
> | 只要两个炮口都有火光 | 双锚点。`InstantFire`：`NbProj = 2` 时两处**同时**亮（BTR-50 MRF 即此写法），`NbProj = 1` 时按弹序**轮取**；`ContinuousFire`：`NbFX = 2`。**「两处同时喷火」不要求 `ContinuousFire`** | 无，**但 DPS 仍是单门** |
> | 要真正的双倍投射量 | 射速减半（`TimeBetweenTwoShots` 0.2 → 0.1） | DPS 翻倍，要么接受，要么把 `PhysicalDamages` 减半 |
> | 一次事件发两弹 | `Sim = 2` + 三处 `WeaponShootData` 名数同改 | **无机炮先例**，风险自负（见 `22-ammo.md §2.5`） |
>
> 实测参考值：单门 2A72 = 0.3 s/发（BMP-3 每轮 5 发；BMPT-787 每轮 10 发、同为 0.3 s/发）。
> 0.3 s/发 是单门 DPS，想还原"两门 2A72 同时开火"才需要 0.15 s/发——但那属于改数值，不是改视觉。

### 4.1b 只有第一发有火光/弹道 → **算子类型选错**

#### 现象

一轮 10 发，**只有第 1 发有枪口焰和曳光**，其余 9 发只有后坐力在动。

后坐力走 `Turret_*_Recoil`，是**另一个算子**，每发都响应 → 这恰好证明
**射击事件是每发都到 depiction 层的，被吞的只是 FX 的触发次数**。

#### 正解（先看这一段）

1. 先看**算子**：这一轮的发数需要数得清吗？要 → `WeaponInstantFire`；不 → `WeaponContinuousFire`。
   需要数清的例子：步战车直升机的低射速机炮、大口径高炮、坦克炮等，**命中效果和弹道轨迹一一对应**；不需要数清的例子：小口径高射速机炮，机枪、步枪等，**命中效果和弹道轨迹不一定一一对应**。
2. 再看**模板**是否与算子配对：`InstantFire` ↔ `Single`，`ContinuousFire` ↔ `Infinite`。
3. 两项都对还不正常，才去查 FX 资源、锚点、`Actions` 引用。

#### 两层模型：算子决定「触发几次」，模板决定「每次长什么样」

| 层 | 对象 | 决定 |
|---|---|---|
| 触发源 | `DepictionOperator_WeaponInstantFire` / `WeaponContinuousFire` | **触发几次**（逐发 vs 每轮一次） |
| 重播策略 | `FXFiring_N` / `FXProjectile_N` 是 `HappeningSingle` 还是 `Infinite` | 每次触发**播多久 / 要不要自己循环** |

`Gameplay/Gfx/Units/DepictionOperators.ndf`（387–438 行）里两类算子的展开，是判据的根：

| 模板 | 展开成的类 | `OperatorId` | 计数参数 | 驱动源 |
|---|---|---|---|---|
| `WeaponInstantFire` | `TCosmeticWeaponInstantFireOperatorDesc` | `MissileCarriageFire` | `NbProj` | **弹丸事件**：每发触发一次 |
| `WeaponContinuousFire` | `TCosmeticWeaponContinuousFireOperatorDesc` | `ContinuousFire` | `NbFX` | **武器状态**：进入开火状态时点亮一次 |

**必须配对**：

| 算子 | 搭配的模板 | 结果 | 原版先例 |
|---|---|---|---|
| `InstantFire` | `Single`（`Wait` ≈ 射速） | 每发一条，**数得清** | BMP-3 的 2A72（5 发/轮 × 0.3 s）、ZSU-57-2 的 S-60（8 发/轮 × 0.6 s） |
| `ContinuousFire` | `Infinite`（`Wait` ≈ 射速） | 整轮一条火流，**数不清** | Gepard 35mm、M163、Shilka、车载机枪 |
| `ContinuousFire` | `Single` | 整轮只播一次（故障态） | 无，禁止这样配 |
| `InstantFire` | `Infinite` | 一条持续拖尾，火光糊成一片 | 少见，不推荐 |

#### 判据：这类武器该用哪个

问一句「**这一轮要数得清发数吗？**」

- **数得清** → `InstantFire` + 双锚点 + `NbProj = 1`。
  适用：5–10 发/轮、0.2–0.6 s/发的机炮与速射炮（2A72、2A42、S-60、57mm等加农）。
- **数不清 / 本来也不该数** → `ContinuousFire` + `NbFX`。
  适用：>5 发/秒的高射速高炮（Gepard 35mm 0.2 s × 8、M163、Shilka）与 12.7 mm 车载机枪等。

⚠ **高射速高炮与连发机炮是两套表达，不能互换。** Gepard 一轮 8 发在 1.6 s 内打完，官方刻意让 FX 与实弹数**解耦**，
整轮只画一条火流；要数清每一发的中速机炮必须走 `InstantFire`。
`FXProjectile_*` 也不能顺手抄：`FXProjectile_12` 的 `InitialSpeed = 2079`（35/23 mm 的速度），2A72 是 1104。

> ⚠ 顺带一条：**别用调 `WaitBetweenShot` / `TimeBetweenTwoShots` 去凑发数**。
> 每轮间隔受士气与压制影响（官方正是用这一点区分自动装弹与手动装弹），
> 靠时间硬凑出来的"多发"在压制状态下会立刻失真。发数必须由**事件**驱动。

#### 改法：只改 depiction 的算子，其余六层不动

弹药 / `WeaponDescriptor` / `FXWeapon_*` / `Weapon_*` 复合块 / `Actions` / 锚点，只要已与参照车同构就一律别碰。

```ndf
DepictionOperator_XXX_Weapon1 is DepictionOperator_WeaponInstantFire
(
    FireEffectTag = "weapon_effet_tag1"
    Anchors = ["fx_tourelle1_tir_01", "fx_tourelle1_tir_02"]
    WeaponShootDataPropertyName = ['WeaponShootData_0_1']
    NbProj = 1
)
```

双锚点 + `NbProj = 1` 抄 ZSU-57-2（双联 S-60 同模式），引擎按弹序轮流取锚点 → 两根管子交替冒火。

#### 仍要遵守：`Actions` 认 `Weapon_*`，不是 `FXWeapon_*`

`Actions` 里写的是 **`Weapon_*`（`TCompositeHappening` 包装器）**。只建了 `FXWeapon_*` 就改 `Actions`，启动即：

```
NDF parsing error. object not found : 'Weapon_AutoCanon_AP_30mm_2A72_BMPT787'
```

`FXWeapon_*` 只负责粒子，`Weapon_*` 才是「粒子 + 音效」的组合体。四层缺一层就报错或静默失效，
而 `GenerateMod` 一路 `Success`，**不校验引用**。

#### 自检

1. 一轮打 10 发，数曳光是否 = 10（不是 1），双联是否左右交替。
2. 算子是 `InstantFire` 时模板必须 `Single`；是 `ContinuousFire` 时模板必须 `Infinite`。
3. `FXProjectile_*` 的 `InitialSpeed` == 弹药 `ProjectileSpeedGRU`。
4. `Actions → Weapon_* → FXWeapon_*` 三层引用都能解析。
5. 原版同名对象仍在（没被全局替换打穿）。

### 4.2 底盘算子跟武器走，不跟车重走

`DepictionOperator_Chassis_*` 有 6 个变体，**它决定开火时车体怎么动**：

| 算子 | 台数 | 面向 |
|---|---|---|
| `Chassis_Vehicle` | 330 | 卡车/吉普等无炮载具 |
| `Chassis_HeavyTank` | 225 | 125/152mm 重炮（**含开炮掀车体动画**） |
| `Chassis_MediumTank_NoCanonRecoil` | 215 | 有炮但不该有车体后坐的（ATGM 车等） |
| `Chassis_MediumTank_AutoCanon` | 150 | **机炮车（Gepard / Shilka 同款）** |
| `Chassis_SmallTank` | 135 | 轻甲 |
| `Chassis_MediumTank` | 128 | 中型坦克炮 |

全库交叉统计（底盘算子 × 是否同时挂了 `Turret_X_HydraulicRecoil_AutoCannon`）：
`HeavyTank` + 机炮后坐的组合**只有 1 台**——那次是自建车照抄 T-72B 的算子清单，结果
600 发/分的 30mm 每发都按 125mm 幅度掀一次车体。**224 台 HeavyTank 其余全不带机炮后坐；
131 台机炮后坐配的是 `MediumTank_AutoCanon`。**

⇒ 换模型/换武器时，底盘算子要**跟着武器类别改**，不能跟着车体重量抄克隆源。
`Chassis_HeavyTank` 换成 `Chassis_MediumTank_AutoCanon` 即可，机炮后坐算子不动。

> 拼写：`AutoCanon` 是**单 n**。写成 `AutoCannon` 编译期报
> `object not found : 'DepictionOperator_Chassis_MediumTank_AutoCannon'`。

## 4.3 挂架（PylonSet）：三条定律 + 一条终局

模型自带的挂梁 / 发射箱 / 火箭巢都在网格里时，"引擎再多画一个挂架"是最常见的多余装饰。这条路有明确解。

### 三条定律

| 律 | 内容 | 违反时 |
|---|---|---|
| 1 | `Pylons` **不能为空**，至少 1 项（`Missiles` 可以为空，别混） | `No pylon with requested slot count (1) found in PylonSet` |
| 2 | "槽位数"是**挂架模型自带的元数据**，不是列表长度 | 自建几何 / 孤儿资源永远匹配不上 |
| 3 | 引擎**只对 `WeaponInfos` 里登记过的武器**去找挂架 | 没登记 = 不画（这正是解法） |
| 4 | ⭐ 战场版 `TMissileCarriageSubDepictionGenerator` 的 **`Pylons` 与 `ReferenceMesh` 缺一不可**（`TShowroom…` 同理，用 `_Showroom` 那套 PylonSet）。这是**加载期**硬校验，编译期不查 | 编译弹窗 `Invalid property in object '<anonymous> (TMissileCarriageSubDepictionGenerator)': Property 'ReferenceMesh' must be defined`，指向 `Depiction.ndfbin`；语法全绿照样拦（LOSAT 2026-11-11 实测） |

### 终局：不登记就不画

本机槽 1（机炮）从第一版起就没有 `WeaponInfos` 条目，也从来没出现过挂架问题——这就是先例。
把「模型自带硬件」的那几个槽从 `WeaponInfos` 里**整条删掉**，引擎根本走不到"找挂架"这一步：

```ndf
WeaponInfos =
[
    TMissileCarriageWeaponInfo( MissileCount=12 MissileType=eAGM WeaponIndex=2 ),
    TMissileCarriageWeaponInfo( MissileCount=4  MissileType=eAAM WeaponIndex=3 ),
]   // 槽 4（模型自带火箭巢）刻意不写
```

`_Showroom` 版用 `~/…WeaponInfos` 继承，改一处两处生效。

### 连带必须成对改：射击算子

删了 `WeaponInfos` 条目，该槽的发射点也没了。算子要从「取挂载槽」换成「取骨骼锚点」：

| 算子 | 发射点来源 | 前提 |
|---|---|---|
| `WeaponMissileCarriageFire` | 挂载槽（`Connoisseur` + `WeaponIndex`） | 该槽在 `WeaponInfos` 里 |
| `WeaponInstantFire` | 骨骼锚点（`Anchors`） | 锚点在网格里 |

```ndf
Op_X_Weapon5 is DepictionOperator_WeaponInstantFire
(
    Anchors = [ "as_3_1", "as_3_2" ]      // 网格里现成的挂点锚点
    FireEffectTag = "weapon_effet_tag5"
    NbProj = 1
    WeaponShootDataPropertyName = [ "WeaponShootData_0_5" ]
)
```

漏了这步，启动报 `No missile carriage slot found in skeleton for weapon index N`。

### 为什么绕了四圈（否定记录，写给后来者）

| 版本 | 做法 | 结果 |
|---|---|---|
| v1 | `PodPylonSet = PylonSet_SOVPodHelico` | 引擎额外叠一具原版吊舱 |
| v2 | `PylonSet_DefaultNoPOD` | 吊舱没了，换成白色 **BRU-55A 双联挂架**（`NoPOD` ≠ "什么都不画"） |
| v3 | `Pylons = []` 空集 | 启动崩 `slot count (1)` |
| v4 | 自建 4 mm 隐形网格 | **同一条错**——槽位数是模型元数据，野模型声明不了 |
| v5 | 孤儿资源 `ModelPylon9NoPOD` | 全库无引用，不敢用 |
| v6 | 三槽统一 `DefaultMissileHelico` | 能启动，但仍露（治标） |
| **v7** | **对应槽不登记 `WeaponInfos`** | **根除** |

⚠ 改挂架集**不会立刻生效**：`Gameplay/Gfx/Units/Pylons.ndf` 属于会被编进 `Depiction.ndfbin` 的那批，
必须重新编译，且**不编译不报错**——见 `40-engineering.md §5.7`。

---

## 5. 排错：按现象定位

| 现象 | 先查 |
|---|---|
| 白模 | `Alternatives_*` 存在？三档 mesh 名都对？ |
| 地图上隐形 | `Tactic*DepictionRegistration` 存在？`BlackHoleKey` 与单位块一致？ |
| 有枪无火 | Operator + `Actions` 里的 tag 都在？ |
| 车内没人 | `HumanSubDepictions_*` + `Showroom*` + catalog 条目三样齐？ |
| 展厅不显示 | `Showroom*DepictionRegistration` |
| 飞机机腹无弹 | `MissileCarriage_*` + `SubGenerators_*` |
| 残骸异常 | `Ghost*DepictionRegistration` |
| **点进军械库那一刻 CTD** | 缺 `ShowroomAerialDepictionRegistration`（报 `Unknown unit mimetic: 'showroom_X'`），见 §3c |
| **部署放下单位那一刻 CTD** | 缺 `GhostAerialDepictionRegistration`（报 `Unknown unit ghost mimetic: 'X'`），见 §3c |
| 挂架位置多出白色异物 / 叠了一具吊舱 | 该槽登记了 `WeaponInfos`，引擎去 `PylonSet` 取挂架；删登记，见 §4.3 |
| 启动报 `No missile carriage slot ... weapon index N` | 删了 `WeaponInfos` 但算子还是 `MissileCarriageFire`，见 §4.3 |
| 船上多出别的模型的零件（如机炮塔、飞行员） | 子描绘 `Anchors` 把克隆源部件实例化了；删子描绘，或把对应空物体压进体内（`23-mesh-import.md §3.1`） |
| 开火特效不从炮口出来 | 先查算子类型（`MissileCarriageFire` 不读 `Anchors`），再查锚点坐标是在**最终网格**上量的（`24-rig-parts.md §7`） |
| **一轮连发只有第 1 发有火光/曳光**（其余只有后坐力） | 算子用了 `WeaponContinuousFire`；能数清发数的机炮必须 `WeaponInstantFire` + `Single` 模板，见 §4.1b |
| 开火时车体被掀 / 后仰严重 | 底盘算子选错档（§4.2）：机炮车用了 `Chassis_HeavyTank` |
| 一轮齐射只有一对火光（其余各发只有后坐力） | 算子用了 `WeaponContinuousFire`——它整轮只在进入开火状态时触发一次；换 `InstantFire` + `Single`，见 §4.1b。**与 `TimeBetweenTwoShots` 无关** |
| 同一武器在面板上并列成两条 | AP/HE 用了两个 `AmmoBoxIndex`；原版共用槽位的应共用 `AmmoBoxIndex` + 共用 `Name` token |
