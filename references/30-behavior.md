# 行为层数据表：AI 决策 / 状态检定 / 技能 / 效果原语

> 本文件是行为层的数据表全集；决策规则与能力边界速答见主 `SKILL.md §4`。
> 所有计数均带取数命令，可复跑；**两边冲突以本文件为准**（它是可验证的原始数据）。
> 基线：WARNO 构建 201602（2026-10），`GameData` 为 mod 工程内的全量 NDF 源。

---

## 0. 三层计数总览

| 层 | 数量 | 能不能自己造 | 权威来源 |
|---|---|---|---|
| 条件类型（Condition 的**类**） | **4** | ❌ 引擎注册 | `WARNO.exe` RTTI |
| 条件实例（可直接引用的具体条件） | **26** base + 自定义 | ✅ 无限新建 | `ConditionsDescriptor.ndf` |
| 技能（`TCapaciteDescriptor`） | **48** base + 自定义 | ✅ 可新建 | `CapaciteList.ndf` |
| 效果原语（`T*Effect*Descriptor`） | **42**（38 个 `TUnitEffect*` + 4 个异类前缀） | ❌ 引擎注册 | `WARNO.exe` RTTI |
| 效果包（`TEffectsPackDescriptor`） | **202** | ✅ 用原语拼装 | `EffetsSurUnite.ndf` |
| 血量档位包（`TDamageLevelsPackDescriptor`） | **15** | ✅ 可新建 | `Gfx/DamageLevels.ndf` |
| AI 空袭宏 / 标签池 | **5 / 5** | ❌ 改不动（只能改标签去迎合） | `SkirmishAirstrike.ndf` |

一句话：**只能从 4 种触发器 × 42 种动作里挑，但可以自由组合出任意数量的新技能实例。**

---

## 1. 取数命令

```bash
# ① exe 类型表（一次抽好，后面反复用；约 55.7 MB / 24 万可打印串）
python - <<'EOF'
import re
d = open(r"<WARNO>/WARNO.exe", "rb").read()
with open(r"%TEMP%/warno_strs.txt","w",encoding="utf-8") as f:
    for s in re.findall(rb"[\x20-\x7e]{4,160}", d):
        f.write(s.decode("ascii")+"\n")
EOF

# ② 条件类型（应只有 4 条）
grep -oE "^TCondition[A-Za-z0-9_]*$" "$TEMP/warno_strs.txt" | sort -u

# ③ 效果原语：先按前缀，再按「同名共同后缀」补漏（3 个异类前缀靠这一步捞出来）
grep -oE "^TUnitEffect[A-Za-z0-9_]*Descriptor$" "$TEMP/warno_strs.txt" | sort -u   # 38
grep -oE "^T[A-Za-z0-9_]*(Effect|Inflict)[A-Za-z0-9_]*Descriptor$" "$TEMP/warno_strs.txt" | sort -u

# ④ 条件实例数 / 技能数
grep -cE "^[A-Za-z0-9_]+ is TCondition" GameData/Generated/Gameplay/Gfx/ConditionsDescriptor.ndf
grep -c "^export Capacite_"            GameData/Generated/Gameplay/Gfx/CapaciteList.ndf

# ⑤ 条件字段的适用范围（只应命中 CapaciteList——这是"只能挂技能"的铁证）
grep -rc "^\s*Conditions\s*=" GameData --include=*.ndf | grep -v ":0"

# ⑥ 触发方式与叠加策略（应各命中 48/48）
grep -rho "CapacityTriggerType_[A-Za-z0-9_]*"    GameData --include=*.ndf | sort | uniq -c
grep -rho "CapacityStackPolicy_[A-Za-z0-9_]*"    GameData --include=*.ndf | sort | uniq -c
```

---

## 2. 状态检定（Condition）

### 2.1 四个类型（exe RTTI，无遗漏）

| 类型 | 字段 | 语义 | base 实例 |
|---|---|---|---|
| `TConditionTimeAfterShot` | `Duration`（**秒**） | 开火后 N 秒内为真；再开火重置计时 | 1 |
| `TConditionTagRaisedInUnit` | `Tag`（字符串） | 单位身上带该标签时为真 | 13 |
| `TConditionInMovement` | 无 | 正在移动时为真 | 1 |
| `TConditionNot` | `ConditionToInverse`（引用） | **唯一组合子，只能取反** | 11 |

- **没有**：血量、距离/邻近、全局状态、周期计时器、与 / 或。
- 多条 `Conditions = [...]` 是**「与」**；「或」= 建多个技能。
- ⚠ **实例名里的数字是毫秒，字段 `Duration` 是秒**（`_1000` = 1 秒、`_15000` = 15 秒）。这条是从两个实例反推的，不是文档写的。
- `Duration = 0` 未实测；想「开火瞬间」建议填 `0.05`，别填 0。

### 2.2 26 个 base 实例

**A. 标签类（13）**

| 实例 | 检测的标签 | 有取反 | 谁升起这个标签 |
|---|---|---|---|
| `ConditionTagRaisedInUnit_IFV_ok` | `IFV_ok` | ✅ | `Capacite_IFV_feedback` |
| `..._Instructor_immune` | `Instructor_immune` | ✅ | 引擎（防重复叠加教官光环） |
| `..._RadioJammed` | `RadioJammed` | ✅ | 电子战干扰 |
| `..._RadioJammed_gsr` | `RadioJammed_gsr` | ✅ | 反炮兵雷达干扰 |
| `..._Retraite` | `Retraite` | ✅ | 引擎（溃退） |
| `..._choc_ok` | `choc_ok` | ✅ | `Capacite_Choc_feedback` |
| `..._reserviste_immune` | `reserviste_immune` | ✅ | 引擎（防重复叠加） |
| `..._sigint_close` / `..._sigint_far` | 同名 | ✅ | `Capacite_sigint_close` / `_far` |
| `..._snipe_ok` | `snipe_ok` | ✅ | `Capacite_sniper_no_snipe` |
| `..._GroundUnit_Engaged` | `GroundUnit_Engaged` | ❌ | `TUnitEffectRaiseTag`（14 处效果包） |
| `..._Infanterie_Cowering` | `Infanterie_Cowering` | ❌ | 压制 / Cowering 效果包 |
| `..._Trepied_ok` | `Trepied_ok` | ❌ | `Capacite_Trepied_no_Trepied` |

**B. 取反类（11）** = 上表 ✅ 的 10 个 `ConditionTagNotRaisedInUnit_*` + `ConditionNotInMovement`。
**C. 移动类（1）** = `ConditionInMovement`；取反为 `ConditionNotInMovement`。
**D. 计时类（1）** = `ConditionTimeAfterShot_15000`（15 秒）。

> 26 个里 11 个是取反对象，真正的检测逻辑只有 15 条。
> `GroundUnit_Engaged` / `Infanterie_Cowering` / `Trepied_ok` **只有正向没有取反** ⇒ 服务于引擎内部判断
> （下车 / 溃散 / 架设），不是给条件系统用的。
> ★ 自建状态要用到的标签，**必须自己造一对 `Raised` + `NotRaised`**，光有 Raised 表达不了「没有这个状态」。

### 2.3 现有「开火后 N 秒」的两个用法

| 实例 | `Duration` | 谁在用 | 干什么 |
|---|---|---|---|
| `ConditionTimeAfterShot_15000` | 15 s | `Capacite_Artillerie_tag_on_shoot` | 挂 `CBR_cible` 标签，供反炮兵雷达抓 |
| `ConditionTimeAfterShot_1000` | 1 s | `Capacite_FPV_Destroy`（自定义） | 自杀无人机开火后自毁 |

⇒ **做「开火后 N 秒发生某事」只有这两个模板**：要删单位抄第二个，要加状态抄第一个。

---

## 3. 技能（Capacite）

### 3.1 字段模型：21 个必填 + 2 个可选

48/48 实例字段齐整度完全一致。

| 字段 | 必填 | 取值 / 说明 |
|---|---|---|
| `DescriptorId` | ✅ | GUID，全局唯一 |
| `Name` | ✅ | 调试名，**不是本地化 token**、不进 UI |
| `StackPolicy` | ✅ | 全库只有 `CapacityStackPolicy_never` |
| `Trigger` | ✅ | 全库只有 `CapacityTriggerType_automatic` |
| `TargetTeamFilter` | ✅ | `_joueur`(36) / `_ennemi`(11) / `_allie`(2) |
| `InfluenceMapAlliance` | ✅ | 全库都用 `~/AllianceRelation/vide` |
| `RangeGRU` | ✅ | 0 = 只对自己；>0 为半径 |
| `CastTime` | ✅ | 全库 `0.00` |
| `CheckVisibility` | ✅ | 是否需要视野（对敌 + 要视野时，看不见目标就不触发） |
| `CanBeCastFromTransport` | ✅ | 车内能否生效 |
| **`TargetEffect`** | ✅ | 作用于**目标**的效果包，**可为 `nil`** |
| **`SelfEffect`** | ❌ | 作用于**自己**，只有 3 个技能用 |
| `CapacityDuration` | ✅ | 全库 `-1.00` = **常驻 / 由条件决定时效，不是 1 秒** |
| `TargetInBuilding` / `TargetInTransport` / `TargetInSelf` / `TargetMySelf` | ✅ | 目标位置开关 |
| `FeedbackActivationMask` | ✅ | UI 高亮：`_never`(35) / `_anyalliance`(9) / `_selected`(8) / `_soloselected`(6) / `_allied`(5) |
| `DisplayRangeColor` / `DisplayRangeThickness` | ✅ | 隐形技能填 `RGBA[0,0,0,0]` / `0.00` |
| `AllowedTargetTags` / `ForbiddenTargetTags` | ✅ | 目标标签白 / 黑名单 |
| **`Conditions`** | ❌ | 条件数组（「与」），24/48 个技能有 |

「对自己生效」两种写法都能跑：

```ndf
// 写法 1：SelfEffect（Capacite_Choc / sigint_close / sigint_far）
SelfEffect    = ~/UnitEffect_Choc
// 写法 2：TargetEffect + TargetMySelf（Capacite_FPV_Destroy / Artillerie_tag_on_shoot，主流）
TargetEffect  = ~/UnitEffect_Destruction
TargetMySelf  = True
RangeGRU      = 0
```

### 3.2 按功能分组（base 48）

| 组 | 数 | 成员 |
|---|---|---|
| 自毁 / 销毁 | 1 | `Capacite_FPV_Destroy`（自定义） |
| 状态 / 标签写入 | 5 | `Declare_hors_transport`、`Trepied_no_Trepied`、`sniper_no_snipe`、`Artillerie_tag_on_shoot`、`Choc` |
| 反馈锁（一次性效果范式） | 6 | `Choc_feedback`、`IFV_feedback`、`MilitaryPolice_feedback`、`SF_feedback`、`sigint_feedback`、`sniper_feedback` |
| 隐蔽 / 静止加成 | 4 | `Infanterie_Dissimulee`、`Infanterie_Retranchee`、`Tank_Dissimule`、`security` |
| 压制 / 士气 / 护盾 | 9 | `Malus_Suppress_*`、`Bouclier_Anti_Suppression_50/99`、`IFV`、`gunship_plane`、`Cowering_Rampe`、`Cowering_Stop`、`eo_dazzler` |
| 电子战 / 信号情报 | 8 | `jammer`、`jammer_arty`、`jammer_gsr`、`GSR`、`electronic_warfare`、`Counter_Battery_Radar`、`sigint_close`、`sigint_far` |
| 光环 / 指挥 | 5 | `Instructor_INF`、`Instructor_TNK`、`MilitaryPolice`、`fireDirection`、`UAV` |
| 训练水平 | 4 | `militia`、`poorly_trained`、`reserviste`、`resolute` |
| 其它 | 7 | `StressOnMiss_low/mid/high`、`Debarque_camion`、`Trepied`、`security_feedback`、`sniper` |

**读表要点**

1. **带 `¬InMovement` 的 11 个**都是「静止才生效」（隐蔽、架设、狙击、GSR、训练水平）——「停稳才强」照抄这组。
2. **7 个 `_feedback` 里 6 个**用「`¬某_ok` → 执行 → 升 `某_ok`」自锁 = 一次性效果唯一范式（第 7 个 `security_feedback` 无条件，纯被动）。
3. **无条件 + `TargetEffect`** 的一批（jammer / Instructor / UAV / resolute / militia）= 常驻被动，挂上永远生效。
4. 狙击手典型 5 件套：`Choc` + `sniper` + `sniper_no_snipe` + `sniper_feedback` + `Choc_feedback`
   = **「主效果 + 开关 + 反馈」三件套**，自定义状态机的模板。

### 3.3 挂载

```ndf
TCapaciteModuleDescriptor
(
    DefaultSkillList = [ $/GFX/EffectCapacity/Capacite_XXX, ],
),
```

- 唯一写法，没有「条件挂载 / 进阶解锁」。
- 挂载数量分布（1213 个带技能单位）：1 个 720、2 个 349、3 个 116、4 个 15、5 个 12、7 个 1。
- 最多的是 `Descriptor_Unit_LAV_MEWSS_US`（7 个）。

---

## 4. 效果原语（42 个）

> ⚠ 早期报告写「41 个（38 + 3 异类）」是**少算了一个**：三份互不相同的清单各漏一条，
> 取并集实为 **4 条**异类前缀。`TEvacAirplaneEffectDescriptor` 曾被漏掉——它在
> `EffetsSurUnite.ndf:3320` 的 `UnitEffect_evac_avion` 里用了 1 次（`DamageLevels.ndf` 引用）。

### 4.1 四个不叫 `TUnitEffect*` 的原语（只按前缀搜必漏）

| 原语 | 语义 |
|---|---|
| `TEffectInflictDamageDescriptor` | **直接造成伤害**（`DamageType` + `Additional` / `Pourcentage`） |
| `TDerouteUnitEffectDescriptor` | 强制溃退 |
| `TKillUnitEffectDescriptor` | **杀死单位**（走死亡流程，≠ 移除单位） |
| `TEvacAirplaneEffectDescriptor` | **强制飞机撤离 / 返航**（唯一用例：伤害档位 0.8 触发） |

**未使用的 3 个**（exe 有、NDF 零引用，可试）：

| 原语 | 推测语义 |
|---|---|
| `TUnitEffectAddFatigueDescriptor` | 增加疲劳 |
| `TUnitEffectChangeTeamDescriptor` | **改变所属阵营**（策反 / 缴获） |
| `TUnitEffectRemoveFromUnitGroupsDescriptor` | 移出编组（脱队） |

### 4.2 在用 38 个，按语义分组（括号内为效果包引用次数）

| 组 | 数 | 成员 |
|---|---|---|
| **生死 / 伤害 / 溃退** | 4 | `RemoveUnit`(1，`UnitEffect_Destruction`)、`TKillUnitEffect`(1，`UnitEffect_Effet_Meurt`，**零引用**)、`TEffectInflictDamage`(6+，暴击系)、`TDerouteUnitEffect`(1，`UnitEffect_Critic_Deroute`) |
| 标签 / 可见 / 可选 | 4 | `RaiseTag`(81，最多)、`MakeUnitVisible`(1)、`SetSelectable`(4)、`ShowLabelIcon`(27) |
| 开火节奏 | 3 | `AlterWeaponTempsEntreDeuxSalves`(58)、`AlterWeaponTempsEntreDeuxTirs`(12)、`StopWithInertiaEffect`(3) |
| 命中 / 精度 | 7 | `IncreaseWeaponPrecisionMouvement`(44)、`...Arret`(44)、`IncreaseDispersion`(20)、`IncreaseWeaponDispersionMaxRange`(9)、`BonusPrecisionWhenTargeted`(6)、`BonusHitRollECM`(1)、`IncreaseSpecializedDetection`(1) |
| 射程 | 5 | `IncreaseWeaponMaxRange`(7) + `...Projectile` / `...Helicopter` / `...Airplane`(各 6) + `...IgnoreSmoke`(1) |
| 伤害 / 生存 | 4 | `IncreaseDamageTaken`(42)、`IncreaseWeaponPhysicalDamages`(2)、`ReplaceArmor`(8)、`HealOverTime`(23) |
| 机动 | 4 | `IncreaseSpeed`(18)、`IncreaseChassisRotationSpeed`(14)、`IncreaseTurretRotationSpeed`(12)、`TransportSlotNumberModification`(4) |
| 感知 / 价值 | 5 | `IncreaseOpticalStrength`(9)、`IncreaseVision`(2)、`IncreaseDangerousness`(11)、`IncreaseInfluenceValue`(7)、`...Min`(2) |
| 隐蔽 / 经验 | 2 | `IncreaseConcealmentBonus`(4)、`BonusExperienceLevel`(4) |

### 4.3 反面清单（**没有**的原语）

创建单位 · 传送单位 · 变形 / 换成另一个单位 · 给弹药 · 改武器类型 · 切换弹药索引 ·
设置血量绝对值 · 修改分值 · 修改卡数 · 改阵营归属（有类型但零引用）· 周期计时器。

⇒ 想做这些必须换层：静态配置（`TModuleDescriptor`）或剧本层（`TGD*`，遭遇战够不着）。

### 4.4 生死类两个包的完整写法

```ndf
export UnitEffect_Destruction is TEffectsPackDescriptor      // 在用：直接消失
( DescriptorId = GUID:{c61861fb-...}  NameForDebug = 'Destruction'
  EffectsDescriptors = [ TUnitEffectRemoveUnitDescriptor(), ] )

export UnitEffect_Effet_Meurt is TEffectsPackDescriptor      // 原版遗留、零引用：走死亡流程
( DescriptorId = GUID:{74f45ca1-...}  NameForDebug = 'Effet_Meurt'
  EffectsDescriptors = [ TKillUnitEffectDescriptor(), ] )
```

⇒ 想给自杀单位加「击毁爆炸 / 残骸」表现，把技能的 `TargetEffect` 换成后者，**一个字段**（未验证）。

---

## 5. AI 决策数据

### 5.1 五个空袭宏（`Skirmish/Airstrike.ndf`）

| 宏 | 池 | 唯一认的标签 | 请求类型 |
|---|---|---|---|
| `Airstrike_AA` | `Pool_Airstrike_AA` | `Avion_Chasseur` / `Avion_Chasseur_Bombardier` | Defense / OpportunisticSingleTarget |
| `Airstrike_Offense` | `Pool_Airstrike_Offense` | `Avion_Bombardier` / `Avion_Chasseur_Bombardier` / `Avion_Napalm` | Attack / OpportunisticTargetInGroup |
| `Airstrike_Assault` | `Pool_Airstrike_Assault` | `Avion_AT` | OpportunisticSingleTarget |
| `Airstrike_SEAD` | `Pool_Airstrike_SEAD` | `Avion_SEAD` | OpportunisticSingleTarget |
| `Airstrike_AirReco` | `Pool_AirReco` | `Avion_Reco` | 侦察巡逻 |

`TagsPriority` = 「按顺序找第一个有货的标签」。**标签不匹配 = 这个宏对这条卡视而不见。**

### 5.2 `StrikeLimitations` 全表（`Constantes/IAStratConstantes.ndf`）

> 原文注释：`Les avions avec des limitations sur leurs cibles sont renseignés ici. Ceux qui n'en ont pas non.
> Ex: les avions AT ne peuvent attaquer que les blindés` —— **白名单制，没列出的标签无限制。**

| 飞机标签 | 允许攻击的目标标签 |
|---|---|
| `Avion_AT` | `Char`、`ChasseurDeChar`、`Vehicule_Appui`、`Vehicule_CMD`、`Vehicule_Reco`、`Artillerie` ← **不含 `Infanterie`** |
| `Avion_SEAD` | `Canon_AA` |
| `Avion_Napalm` | `Infanterie` |
| `Avion_Chasseur` | `Helo_Gunship`、`Helo_AT`、`Helo_AA`、`Avion`、`Avion_Reco` |
| `Avion_Bombardier_Infanterie` | `Infanterie`、`ChasseurDeChar_Standard` |
| `Avion_Bombardier_Vehicule` | `ChasseurDeChar`、`Char`、`Vehicule_Appui` |

### 5.3 三个阈值

```
TargetPowerForOpportunisticSingleTargetAirStrike    = 70     // 单目标战力门槛
TargetPowerForOpportunisticTargetInGroupAirStrike   = 60     // 群目标
RadiusForOpportunisticTargetInGroupAirStrikeGRU     = 212    // ≈120 m
MinNbrOfTargetsForOpportunisticTargetInGroupAirStrike = 2    // 212 GRU 内至少 2 个目标
```

### 5.4 难度 → 宏调用次数（`Strategies/*Generic*.ndf`）

| 宏 | 非常简单 | 简单 | 普通 | 困难 | 非常困难 |
|---|---|---|---|---|---|
| `Airstrike_Assault` | **0** | 1 | 4 | 5 | 5 |

⇒ 验 AI 行为**必须普通以上**。普通难度下它挂在 `Airstrike_Arti_Shuffle`（`GenericSkirmishStrategy.ndf:301`）。

### 5.5 通道与标签的 base 惯例（判断「我的单位违和吗」的基线）

| 观察项 | base 分布 |
|---|---|
| `Factory/Recons` 通道的 19 个飞机 | `Avion_Reco` **16**、`Avion_AT` **0**（38 架 AT 机全在 `Factory/Planes`） |
| 含飞机单位的卡包 | **274**，其中带 `Transport`（运输车）**0** |
| AT 机的 `TypeStrategicCount` | `Air_AT`（38 个）；侦察机是 `Air_Support` |
| AI 全部池标签 | **45** 个，**不含 `Vehicule_Transport`** |

⇒ 这三条是「AI 认不认这个单位」的模板基线。**偏离基线的孤例要先当嫌疑，但不能当结论**（见 `60-numbers.md §1`「共现 ≠ 规则」）。

---

## 6. 能做 / 不能做（一句话版）

### ✅ 能做

| 需求 | 做法 |
|---|---|
| 开火后 N 秒自毁 | 复制 `Capacite_FPV_Destroy`，新建 `TConditionTimeAfterShot` 改 `Duration` |
| 开火后 N 秒挂标记 | 复制 `Capacite_Artillerie_tag_on_shoot`，换效果包 |
| 静止时加 / 减成 | `Conditions = [ConditionNotInMovement]` + 对应效果包 |
| 「某状态」触发效果 | 效果包升标签 → 自建 `Raised`/`NotRaised` 条件对 → 技能读标签 |
| 一次性效果（不可重叠加） | feedback 锁范式 |
| 被干扰时禁用某能力 | `Conditions = [ConditionTagNotRaisedInUnit_RadioJammed]` |
| 自毁带击毁表现 | `TargetEffect` 换 `UnitEffect_Effet_Meurt` |
| **血量降到 X% 时施加效果** | 不走 Condition，走 `TBaseDamageModuleDescriptor` 的两个 `...DamageLevelsPack`（见 §7） |

### ❌ 不能做

| 需求 | 原因 |
|---|---|
| 血量条件**参与「与 / 或」组合** | 血量档位是独立通道，只吃「阈值 → 效果包」，不与 Condition 组合 |
| 敌人在附近时… | 无距离 / 邻近条件类型 |
| 某单位存活 / 死亡时… | 无全局状态条件 |
| 玩家点击触发 | Capacite 全库无手动触发（走 OrderAvailability） |
| 「A 且 B，或 C」 | `TConditionNot` 只能取反 |
| 生成 / 变形 / 回收单位 | 42 原语里没有；`TGD*` 有但 NDF 0 引用 |
| 给武器 / 订单加前置条件 | `Conditions` 只存在于 Capacite |
| 每 N 秒周期触发 | `TimeAfterShot` 只在开火时重置，无周期计时器 |

### 改动顺序（新增一个条件效果）

| # | 文件 | 动作 | 验收 |
|---|---|---|---|
| 1 | `ConditionsDescriptor.ndf` | 新建条件实例（含 GUID） | 类型名与已有实例一致 |
| 2 | `EffetsSurUnite.ndf` | 新建效果包（引用已有原语） | 括号配平、GUID 唯一 |
| 3 | `CapaciteList.ndf` | 新建 Capacite（21 必填字段齐全） | `grep -c "^\s*Trigger"` +1 |
| 4 | `UniteDescriptor.ndf` | 单位块加 `TCapaciteModuleDescriptor` | 块内有 `DefaultSkillList` |
| 5 | — | 编译 | `Mod Generation Success` |
| 6 | — | md5 比对工程 vs 部署 | `EffectCapacity.ndfbin` / `Unit.ndfbin` 全 OK |

> `CapaciteList` + `ConditionsDescriptor` 一起编进 **`EffectCapacity.ndfbin`**；弹药 / 武器进 `Weapon.ndfbin`；
> 单位 + 订单集进 `Unit.ndfbin`。改完只重建对应那个——ModGen 是按需编译的。

---

## 7. ★ 第三条通道：血量档位（`DamageLevels.ndf`）—— 「血量低于 X% 就…」唯一能做的地方

前面 §2 说「没有血量条件类型」，那是针对 **Condition**。血量阈值→效果**有一条独立通道**，
它不参与 Capacite 系统，也不需要任何条件——阈值直接写在单位自己的伤害模块里。

```ndf
// 单位块内（几乎每个单位都有：物理档位 2916 处引用）
TBaseDamageModuleDescriptor
(
    MaxPhysicalDamages       = 10
    PhysicalDamageLevelsPack = ~/DamageLevelsPackDescriptor_Default_pack_paliers_degats_phy
    SuppressDamageLevelsPack = ~/DamageLevelsPackDescriptor_Airplanes_packSupp
    ...
)
```

```ndf
// DamageLevels.ndf：一个包 = 一串阈值档位，每档一组 EffectsPacks
export DamageLevelsPackDescriptor_Airplanes_packSupp is TDamageLevelsPackDescriptor
(
    DescriptorId = GUID:{...}
    DamageLevelsDescriptors = [
        TDamageLevelDescriptor
        (
            DescriptorId     = GUID:{...}
            Value            = 0.8                       // ★ 血量比例阈值（0~1）
            LocalizationToken = "mrl_1"                  // 状态图标上的文字
            MoralModifier    = 0
            AnimationType    = ESoldierSuppressStatus/Cowering
            FeedbackOnSelf   = "OnUnitPanicking"
            EffectsPacks     = [ $/GFX/EffectCapacity/UnitEffect_evac_avion, ... ]
        ),
    ]
)
```

15 个包，按用途分三类（引用数 = 含定义本身）：

| 用途 | 字段 | 包（引用数） |
|---|---|---|
| 物理伤害档位 | `PhysicalDamageLevelsPack` | `Default_pack_paliers_degats_phy`(2916) |
| 压制伤害档位 | `SuppressDamageLevelsPack` | `GroundUnits_packSupp`(2016)、`Airplanes_packSupp`(394)、`helo_packSupp`(249)、`ArtyUnits_packSupp`(247)、`Default_pack_paliers_suppression`(14) |
| 眩晕档位 | `…Stun…` | `Unit_packStun`(2905)、`Unit_packStun_Artillerie`(640)、`Unit_packStun_aa`(161)、`Unit_packNoStun`(1) |

**零使用的 4 个**（只有定义、无人引用，可直接拿来做模板）：
`ArtillerieInf_packSupp`、`Artillerie_packSupp`、`CanonAT_packSupp`、`Infanterie_packSupp`。

要点：

- **阈值是「血量比例」，不是绝对值**（`Value = 0.8` 表示剩余 80% 时切到这一档）。默认物理包是 0 / 0.16 / 0.33 / 0.5 / 0.66 / 0.83 六档，只改 `MoralModifier`，`EffectsPacks` 全空。
- 一档可以挂**多个效果包**，所以「受伤 20% 后变慢 + 降危险度 + 换装甲」一次写完。
- 档位是**单向爬升**的语义（血量往下掉才进入更高档），**官方 0 例「血量回升就退出」**——
  按「越打越惨、不可逆」设计。这一条是推断（没有实测回血时档位是否回退），当待验项。
- ★ **实际用途**：想做「残血后弃车 / 强制撤离 / 降低危险度 / 挂 debuff」，**这是唯一干净的做法**，
  比「用开火计时器凑」可靠得多。`UnitEffect_evac_avion` 就是靠 0.8 档触发的（飞机被打到 80% 自动返航）。
- ⚠ 它与 Capacite 的 feedback 锁叠加时，两边各自独立判定，别指望互相抑制。

---

## 8. 相关的旁支：暴击（`CriticalEffectModule`）

不属于 Capacite 系统，但同属「条件成立 → 施加效果」，常被误认为条件系统的一部分。

- 定义：`Gameplay/Unit/CriticalModules/TemplateCriticalEffectModules.ndf`
- 7 种模块按单位类型分发（`Airplane` 393 / `Helico_Arme` 223 / `Helico_NonArme` 25 / `Infanterie` 855 /
  `Vehicule_Arme` 379 / `Vehicule_ArmeSansTourelle` 835 / `Vehicule_NonArme` 192）
- 15 个 `Critic_*` 包（注意拼写：只有 `Perd_1_PV` 是 Perd，其余是 Pert）：
  `Bailed_Out` `Chenille_Detruite` `Deroute` `Full_Stop` `Perd_1_PV` `Pert_2_PV`…`Pert_5_PV`
  `Reload_50` `Stop_Armes` `Stop_Reload` `Tourelle_Bloquee` `Visee_50` `Vitesse_50`
- **限制**：触发源只能是「被击中」，概率在模块里配，**不能挂自定义条件**。
