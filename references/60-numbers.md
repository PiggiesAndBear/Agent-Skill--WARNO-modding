# 数值语义速查 + 引擎硬校验 + 能力边界

> 适用：「面板伤害和实际对不上」「为什么打不到直升机」「这个字段能不能填」「弹丸能不能做成可选单位」。
> 建弹药的具体流程见 `22-ammo.md`；本文件只讲**语义与边界**。

---

## 1. 把 `-generatemod` 当 schema 查询器

`-generatemod` 生成结束时会**真的加载一遍 ndfbin**，把引擎侧的类型约束逐条暴露。
**这是本库里唯一免费的「字段合法性查询接口」**：故意填错，让它告诉你规则。

### 已知硬校验清单【实测，报错原文照抄】

| 报错 | 含义 | 处置 |
|---|---|---|
| `Weapon with parabolic trajectory cannot be embedded on planes or helicos` | 飞机/直升机拒收**抛物线弹道**（`EProjectileType/Grenade`/`Artillerie`） | 换 `Obus` / `Roquette` / `Bombe` |
| `Value is too long for a TLocalisationToken: 'FPVSATCHELUS'` | token 上限 **10 字符** | 缩到 10 |
| `"TAirplaneModuleDescriptor" is required when order "AirplanePatrol" is available` | 订单与模块耦合，不能只删一边 | 一起删/一起留 |
| `NDF parsing error. Retry?`（**模态对话框**） | 语法错 | 会永久挂起，必须用守卫脚本 |

### 建「导弹类弹药」：换起点，别去改榴弹的弹道类型

`ProjectileType` 不是一个可自由翻转的字段 —— 两类弹药带的是**两套字段集**：

| | 榴弹类（`Artillerie` / `Obus`） | 导弹类（`GuidedMissile`） |
|---|---|---|
| 独有字段 | `PitchForParabolic`、`CorrectedShotDispersionMultiplier` | `MaxAccelerationGRU`、`MissileTimeBetweenCorrections`、`MissileDescriptor` |
| 落在哪个文件 | `Ammunition.ndf` | `AmmunitionMissiles.ndf` |

所以「做一发制导炮弹 / 任何一种导弹类弹药」的正确起点，是 `AmmunitionMissiles.ndf` 里
**现成的导弹类弹药**（弹药层可拿 `Ammo_SSM_MGM52_Lance` 当基准，它带全导弹类字段、
且是 `TirIndirect=True`），然后只从榴弹那边**借用共用参数**：

- 伤害 / 物理 AOE / 压制 / 压制 AOE（`PhysicalDamages`、`RadiusSplash*`、`SuppressDamages`）
- 散布（`DispersionAtMin/MaxRangeGRU`）、弹着特效（`ImpactHappening`）、`FxPower`
- 射击节奏（`AimingTime` / `TimeBetweenTwoSalvos` / `ShotsCountPerSalvo`）、`SupplyCost`
- 命中判定块（`HitRollRuleDescriptor`）、攻顶与命中位置（`ForceHitTopArmorOnSuccess` / `ComputeArmorFromImpactLocation`）
- 152mm 的本地化 token（`Name` / `TypeCategoryName` / `Caliber` / `WeaponDescriptionToken`）

反过来拿榴弹改弹道类型，会**同时带进非法字段、又缺必填字段**，改一个撞一个 —— 那是起点选错，
不是「换弹道要改三个字段」的规律。同理，`WeaponCursorType` / `MinMaxCategory` 只决定
**面板归类**，与投射类型无关：制导炮弹照样写 `Weapon_Cursor_CorrectedArtillery` + `MinMax_obusier`。

### 共现 ≠ 规则（本库最容易犯的错）

❌ 曾判定「气球是 Helo，所以不能做间瞄」，于是把 `TirIndirect` 改 `False`、光标改直射——**编译通过了，但归因是错的**。

被禁的是**弹道类型**，不是间接瞄准。数据也支持：
- `EProjectileType/Bombe` 的 68 个航弹**全是** `TirIndirect=True` + `Weapon_Cursor_CorrectedArtillery`，就挂在飞机上；
- `EProjectileType/Artillerie` 全库 204 个，**100%** 是 `TirIndirect=True` ⇒ 「间瞄 ≈ Artillerie」只是**统计相关**。

> 判据：**「100% 共现」不构成「必须共现」**。要断言因果，必须找到引擎硬校验，
> 或用一次「只改 A 不改 B」的最小实验证伪。

---

## 2. 总弹数 = 两个文件里的两个字段

```
总弹量 = Salves[AmmoBoxIndex]（在 WeaponDescriptor，长度 = 槽数） × ShotsCountPerSalvo（在弹药）
```

【实测】M1A1 `Salves=[40,65,80,1]` 的 4 个弹药箱对应 4 种弹（主炮 40 发）；BM-21 `Salves=[1]` × `ShotsCountPerSalvo=40` = 40 发。

⇒ 想给「10 组 × 10 发 = 100 发」，改的是**两个文件里的两个字段**，不是总数一个数。
（`ShotsCountPerSalvo` 在 `Ammunition.ndf` 出现 957 次，武器侧只有极个别特例——先查弹药。）

---

## 3. 两套并存的伤害数值尺度（★ 最容易误判）

| 类型 | `PhysicalDamages` | 实际伤害 | `ShowDamageInUI` |
|---|---|---|---|
| AP / AP_Missile | **恒 1.0**（归一化基准） | 1.0 × 矩阵倍率 | **False（面板不显示）** |
| HE / 其他 | 0.1~0.9（真实值） | 绝对值，矩阵只做效率修正 | True |

⇒ 「面板低、实际高」真实存在，就是 AP 家族。**换伤害家族的收益是数量级的，调 `PhysicalDamages` 是线性的。**

伤害矩阵在 `Gfx/DamageResistance.ndf`（40 行 × 49 列），列布局按 `ResistanceFamilyCounts` **顺序展开**，
`Index` 是 **1-based**——不能假定按字母序。

---

## 4. 「能不能打空中」只有一个开关

`TWeaponManagerModuleDescriptor` **没有任何「能否对空」字段**。能否打空中/直升机，
**完全由弹药的 `MaximumRangeAirplaneGRU` / `MaximumRangeHelicopterGRU` 是否为 0 决定**。

【实测】941 个弹药里 **864 个为 0**，只有 77 个能打空中（`Ammo_DCA_*` 50 / 飞机航炮 18 / 其他零散）。
⇒ 「FPV 打不到直升机」不用查武器，查那两行；`= 0` 是「不参与该判定」，不是「射程为 0」。

---

## 5. 视野、隐蔽、命中是三套独立的东西

| 想改什么 | 字段 | 常见误解 |
|---|---|---|
| 它**能看多远** | `TVisibilityModuleDescriptor.VisionRangesGRU`（**三档 MAP**：Standard / LowAltitude / HighAltitude） | 光环只能「加」，做不出「圈外归零」；要「出圈就瞎」必须**把基础值压到 0** |
| 它**多难被发现** | `UnitConcealmentBonus`（全库 2899 个实例**只有这一个字段**） | ❌ `OpticalStrengths` **不是**签名：侦察兵 7067、摩托化步兵 3180，侦察兵更高却更隐蔽 ⇒ 它是「自己看别人多强」，调它只会瞎掉自己 |
| 被发现后**多难命中** | `TDamageModuleDescriptor.HitRollECM` | 与隐身无关：F-117 是 `0.0`；只有电子战/SEAD 用负值（原版最好 −0.6） |

★ **视野压 0 之前先写 `1.0`**：全库 8706 个档位实例**没有一个为 0**（最小 2500 / 4947 / 5654）。
先试 `1.0`（视觉一样是瞎，避开「恰好为 0」的边界分支），确认光环加得回来再试 `0.0`。

---

## 6. 高度决定「谁打得到你」：碰撞层模型

`Gameplay/Constantes/GDConstants.ndf` 的 `SplashCollisionPlanes` 决定空间分 6 层：

```
炮弹所在 ProjectileAltitude  ↔  Ground / NearGround      ← 撞不到 LowAltitude / HighAltitude
NearGround                   ↔  Ground / NearGround / LowAltitude / ProjectileAltitude
```

【实测】`AltitudeMinGRU = 10` 把无人机放进 `NearGround`，**坦克主炮就能把它打下来**
（坦克的 `MaximumRangeAirplaneGRU = 0`，本来按数据不能瞄空中）。
全库 391 架飞机的该字段**最小值就是 100** ⇒ 飞行单位 `AltitudeMinGRU` **不得低于 100**。

---

## 7. `ModifierType` 的乘算语义：`Multiplicatif` 是直接乘，不是 1+x

【实测】语义铁证 `Effet_Suppress_Recu_25pourcent = 0.25`；同描述符先例 `Optique_plus_15/25/33pourcent`
= **1.15 / 1.25 / 1.33**。⇒ 想把光学砍半就写 `0.5`，写 `1.5` 会变成「增加 50%」。

⚠ **改效果前先算一遍它作用在什么基准上**：三款 FPV 的光学强度已被压成 0，
所以「光学 ×0.5」对**裸 FPV 是空操作**（0×0.5=0），只对「带控制车、被加过 +7067」的才生效。
这类「改了但没效果」多数不是没生效，是**基数为 0**。

---

## 8. ★ 弹丸做成可选单位：结构上封死（2026-10-29，三次实机）

红龙那边摸出过「可操控弹药」的路子；WARNO 里对应的是 `MissileDescriptors.ndf` 的**导弹实体**
（`TEntityDescriptor`，共 197 个，有 GUID / 血量 / 护甲 / 位置 / 队伍）。它们缺的是**可选 + 可指令 + 有 UI**。

### 三条命名空间铁律（踩了 4 轮才通）

1. **`~/` 不是命名空间，是搜索路径集。** 同一目录下两个文件可达范围不同，报错只显示其中一个候选路径。
   - `MissileDescriptors.ndf`：能拿导弹侧别名，拿不到 `ModulesStandard.ndf` 的别名
   - `UniteDescriptor.ndf`：反过来
   - **结论：要在导弹上加单位侧模块，必须在 Missile 文件里用「类型名内联」**（`TSelectionModuleDescriptor(...)`），
     不能用 `~/SelectionModuleDescriptor`。
2. **跨命名空间引用单向可见。** `Weapon` 命名空间看不到 `$/GFX/Unit/`。把弹药搬进 `UniteDescriptor.ndf`
   能构造成功，但生成流程**静默崩溃**（rc=1、无弹窗、无日志）→ 这条路作废。
3. **枚举有加载顺序。** `EOrderType` 在 Missile 文件之后加载，只能写**数值**：
   `Stop=37 Shoot=29 ShootOnPosition=31 ShootOnPositionWithoutCorrection=33`；`MinMax_AGM` 写 `21`。
   但 `TWargameCoalition` 可直接用（常量组加载早）。

### 实测结局：四次实验闭环

| 实验 | 实体模块 | 结果 |
|---|---|---|
| 对照 | 弹药指向**原版** Maverick | 开火正常，不崩 |
| 全量 | 导弹 + 选择/UI/指令 + **两个状态机** | **开火瞬间 CTD**，`0xC0000005 读 0x20`，RVA `0x95B4C9`，两次同址 |
| 去指令 | 摘 `TOrderConfig`/`TOrderable`/`TOrderDisplay` | **仍 CTD**，同一 RVA ⇒ 指令侧无罪 |
| 去状态机 | 再摘 `TStateEngineUnit` + `TStateEngineSubUnit` | **不崩、能发射，但选不中、无图标** |
| 只留 Unit | 加回 `TStateEngineUnit`（不带 SubUnit） | **又 CTD**，同一 RVA |

三条证据构成闭环：

1. **崩溃点在状态机**：`TStateEngineUnit` 一挂上就确定性空指针。不是字段没填——
   `TStateEngineUnitModuleDescriptor` 本身**零字段**，运行期内容由别的系统装配。
2. **可选中离不开状态机**：全库 2908 个带 `TSelectionModuleDescriptor` 的单位，**100% 同时带
   `TStateEngineUnit` 和 `TGroupableUnitModuleDescriptor`——零例外**。
3. **Groupable 强制要求两个状态机**：`Missing TStateEngineUnitModuleDescriptor for unit with
   TGroupableUnitModuleDescriptor`（编译期 Fatal 原文）。所以「想有单位行为」→ 必需 Groupable →
   必需双状态机 → 弹丸上必崩。

⇒ **描述符层面能写、能编译、能发射；引擎层面不允许弹丸进入可选集合。**
想操控飞行中的弹，在 WARNO 里不是配置问题。红龙能摸出来是那套实体系统不同，别当本作可行性证据。

### 残留物（不影响正常游玩）

`Descriptor_Missile_TEST_Controllable_AGM65D` 留在 `MissileDescriptors.ndf` 但无人引用；
`AmmunitionMissiles.ndf` 的弹药副本 `Ammo_TEST_Controllable_Maverick_avion` 与
`WeaponDescriptor_Su_25T_SOV_TEST` 同样闲置。只要弹药指向原版 Maverick 就不会崩。

---

## 9. 常见误判速查

| 误判 | 实际 |
|---|---|
| 「面板伤害低就是伤害低」 | AP 家族 `PhysicalDamages=1.0` 是归一化基准，面板另标 `ShowDamageInUI=False` |
| 「`OpticalStrengths` 低 = 隐身」 | 它是探测能力。隐蔽只看 `UnitConcealmentBonus` |
| 「`Multiplicatif 0.5` = 减半后再 ×0.5」 | 直接乘。注意基数是否已是 0 |
| 「`Salves=[1]` 能保证只打一发」 | 与「一发即毁」无关；自毁是**技能**给的 |
| 「`UnitRole` 决定进哪个栏」 | 由 `FactoryType` + `MenuIconTexture` 决定 |
| 「100% 共现 = 必须共现」 | 只是统计相关，因果要引擎硬校验 |
| 「原版 0 先例 = 引擎不支持」 | 只能产出待验清单，不能产出结论 |
