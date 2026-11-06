# 地面导弹发射车（TEL）：挂架链与出管方向

**本文件管**：地面单位用 `MissileCarriage` 挂导弹的全部环节，以及**导弹从哪出去、朝哪个方向出去**。
**不管**：
- 飞机 / 直升机的 `as_N_M` 挂点组 → `24-rig-parts.md §7`（那套和地面**不是同一个机制**）
- 弹药字段语义、总弹量 → `22-ammo.md`
- 材质 / 贴图 / FBX 导出 → `25-asset-pipeline.md`
- 锚点契约与导入流水线 → `23-mesh-import.md`

> 本文所有结论都来自一台实车落地（M752 Lance / MGM-52，CENTAGRS 师），
> 出管方向那一节经过「改数值 → 加骨骼 → 拆挂架网格」三轮才定案，实机验证通过。
> 被推翻的判断集中在 §7，**先看 §7 能省一轮**。

## 目录

| 节 | 管什么 | 一句话判据 |
|---|---|---|
| §0 | 判据：这辆车是「打炮弹」还是「射导弹」 | 弹要不要自己飞 |
| §1 | 整条链 9 处注册 | 少一处就静默失败，且**不报错** |
| §2 | 弹药与飞行实体 | 两个速度字段必须相等 |
| §3 | 挂架链（地面版） | 地面靠 `TourelleN_MissileCount` 计数，不用 `as_N_M` |
| §4 | ⭐ **出管方向**（§4.6 兼起竖动画，§4.8 角度参数） | 方向来自**挂架网格**里的 box，不是数值、不是车体网格 |
| §5 | 三处显示场景 | 战场 / Showroom / 幽灵各自独立注册 |
| §6 | 验收与判读 | 先看弹在不在，再看出管方向 |
| §7 | 被推翻的判断 | 别在 `AngleRotationBasePitch` 上再花时间 |
| §8 | 执行清单 | 前置 / 顺序 / 禁止 |
| §9 | 底盘：轮式 / 履带的速度与地形系数 | 四个字段成套改，显示值是贴纸 |

---

## 0. 判据：打炮弹，还是射导弹

**【原理】** 弹药的「会不会自己飞」决定它挂在哪套系统上，两套系统**不通用**。

| 判据 | 炮弹 / 火箭弹 | 导弹 |
|---|---|---|
| 弹药文件 | `Gfx/Ammunition.ndf`（全库 965 条，全是 `Obus` / `Artillerie` / `Bombe` / `Grenade`） | `Gfx/AmmunitionMissiles.ndf`（全库 199 条，全是 `GuidedMissile`） |
| 是否需要「飞行实体」 | 不需要 | **必须**：`MissileDescriptors.ndf` 里一条 `TEntityDescriptor` |
| 发射后能不能自己爬升/转向 | 不能（纯弹道） | 能（分段配置驱动） |
| 需要挂架链吗 | 不需要 | **需要**：`MissileCarriage` |
| 外观 | 弹药本身没有独立网格 | 弹体是**独立网格**，由挂架注入 |

**【操作】** 先把目标车的弹药类型对齐到上面某一列，再决定往下读哪几节。
一辆「导弹发射车」如果弹药写进了 `Ammunition.ndf`，无论怎么调都只会打出纯弹道，
不会出现「拔地而起 + 中段巡航」。

**【验收】** `ndfq.py` 查该弹药对象所在文件与类型；查不到飞行实体就是漏了 §2。

---

## 1. 整条链：9 处注册

**【原理】** 这 9 处各自独立，**任何一处缺失都不会报错**，只表现为「不显示 / 打不出 / 卡面空」。

| # | 文件 | 新增对象 | 缺了会怎样 |
|---|---|---|---|
| 1 | `Gfx/AmmunitionMissiles.ndf` | `Ammo_<名>`（GuidedMissile） | 武器挂不上 |
| 2 | `Gfx/MissileDescriptors.ndf` | `Descriptor_Missile_<名>`（飞行实体） | 有弹无实体，开火无效果 |
| 3 | `Gfx/MissileCarriage.ndf` | `MissileCarriage_<名>` + `_Showroom` | **车上不出现弹** |
| 4 | `Gfx/MissileCarriageDepiction.ndf` | `SubGenerators_<名>` + `_Showroom` | 同上（两处都要） |
| 5 | `Gameplay/Gfx/DepictionResources/Char/<Unit>.ndf` | `Modele_` 车体 / 弹体 / **挂架** | 白模 |
| 6 | `Generated/.../Depictions/DepictionVehicles.ndf` | 注册块 + **`SubDepictionGenerators = [...]`** + 开火算子 | **整条挂架链不跑，且零报错**（本项目踩过，最难查） |
| 7 | `Generated/.../Depictions/DepictionVehiclesShowroom.ndf` | 同上 Showroom 版 | 军械库里看不到弹 |
| 8 | `Gfx/WeaponDescriptor.ndf` | 炮塔槽 `Ammunition` 指向 | 打不出 |
| 9 | `Generated/.../UniteDescriptor.ndf` | 单位本体 | 买不到 |

**【操作】** 第 6 项是**唯一一个「对象都在、就是没挂上」**的位置：
写完 `MissileCarriage_*` / `SubGenerators_*` 之后，必须回到注册块里加那**一行引用**。
判据是「被谁引用」，不是「对象内容对不对」——只对比对象内容永远发现不了这一行缺失。

**【验收】** 编译后解压 `Depiction.ndfbin`，确认同时出现 `SubDepictionGenerators` 字段名与
`MissileCarriage_<名>`；`.ndfbin` 是 zstd 压缩，直接 grep 恒为 0。

---

## 2. 弹药与飞行实体

**【原理】** 武器侧只认弹药对象的 `ProjectileSpeedGRU`，飞行实体侧认自己 `DefaultConfig` 的
`MaxSpeedGRU`；两者不等会出现「贴地飞 / 到不了目标」。

**硬约束**

```
Ammunition.ProjectileSpeedGRU  ==  MissileDescriptor.DefaultConfig.MaxSpeedGRU
```

**分段配置**：飞行剖面按段给速度与高度。一台 40 km 级弹道导弹的实测起手值
（M752 / MGM-52，实机可用）：

| 项 | 值 | 备注 |
|---|---|---|
| 三段速度 | 1200 / 2400 / 3600 m/s | 对 `Ammunition.ProjectileSpeedGRU` 取**首段** |
| 巡航高度 `CruiseAltitudeGRU` | 5000 m | 太高会让「出管后陡升再压平」，观感不像 SRBM |
| 末段起始距离 | 8000 m | 参考同类 AGM114 只有 2000，打远目标要放大 |

**四段 config 的真实语义**（全库 198 条导弹实测：**193 条只有 `DefaultConfig` + `UncontrollableConfig`**，
只有 5 条用全套四段 —— 4 条 AGM114 加本项目的 M752）：

| 段 | 什么时候生效 | 备注 |
|---|---|---|
| `DefaultConfig` | **常态 / 平飞**（没有更高优先级阶段时就用它） | 只有它也能飞，193/198 就是这种 |
| `UncontrollableConfig` | 出管后那一小段「失控」抖动 | 配 `TimeBetweenChaosUpdates` 等一组混沌参数 |
| `AscendantPhaseConfig` | 爬升到 `CruiseAltitudeGRU` | 没有它就等于不爬升 |
| `TerminalPhaseConfig` | 进入末段（按 `HorizontalDistanceToTargetToStartTerminalPhaseGRU` 触发） | |

⚠ **平飞段的速度取 `DefaultConfig`**，不是 `AscendantPhaseConfig`（后者只在爬升时生效）。
平飞段**没有独立参数**，它的长度是余数：

```
平飞段 ≈ 到目标水平距离 − 爬升段耗掉的水平距离 − 末段触发距离
```

判据：想要「抛物线」而不是「梯形」，只能把 `CruiseAltitudeGRU` 压低（AGM114 只有 141 m，
所以它没有平飞段）或把末段触发距离拉到接近射程；改 `DefaultConfig` 的速度只改变平飞段的快慢，
不改变它存不存在。

**【操作】** 从同`MinMaxCategory`、同战斗部性质的现成导弹**逐字节克隆**，只换对象名与显示名；
不要凭空手写字段。

**【验收】** 解压 `Weapon.ndfbin` 确认浮点数在里面（**`ndfbin` 里的浮点是 float32，不是 double**——
按 double 去比对会一直是 0 次，误判成「没写进去」）。

---

## 3. 挂架链（地面版）——和飞机那套不是一回事

**【原理】**

| | 飞机 / 直升机 | **地面车（本文）** |
|---|---|---|
| 挂点骨骼 | `AS_{N}_{M}` / `AA_{N}_{M}` 挂点组 | **不用**（没有 `as_N_M` 要求） |
| 计数来源 | 组号 + `WeaponInfos` 顺序（还有倒序坑） | `PhysicalProperty = "Tourelle{WeaponIndex}_MissileCount"` |
| 挂架描述器 | `MissileCarriage_*`（机腹/翼下） | `MissileCarriage_*`（同名，但 `MeshDescriptor` 指向**发射架那份网格**） |

结构（三条对象 + 一条引用）：

```ndf
export MissileCarriage_<车> is TMissileCarriageConnoisseur
(
    MeshDescriptor = $/GFX/DepictionResources/Modele_<挂架网格>   // ← 见 §4，这里指向谁非常关键
    PylonSet = ~/DepictionPylonSet_Vehicle_Default
    WeaponInfos =
    [
        TMissileCarriageWeaponInfo( MissileCount=1 MissileType=eAGM WeaponIndex=1 ),
    ]
)
```

```ndf
export SubGenerators_<车> is TMissileCarriageSubDepictionGenerator
(
    Template = TemplateDepictionMissileGroundUnit
    (
        PhysicalProperty   = "Tourelle1_MissileCount"
        MissileNumber      = 1
        ProjectileModelResource = $/GFX/DepictionResources/Modele_Missile_<弹名>
    )
)
```

并确认 `TMissileCarriageModuleDescriptor` 挂在该单位的模块列表里（克隆源如果自带宽，
别顺手删掉——删了会连带让开火算子指向不存在的对象）。

**【操作】**
0. ⚠ **`GameplayBBoxBoneName`（通常是 `"chassis"`）指向的骨必须带几何** —— 直接用
   `Chassis` 那个**网格**，别再建一个叫 `chassis` 的空物体。AssetCooker 会把节点名统一小写，
   两者撞名后引擎取到没几何的那个，部署时 Fatal：
   `Mesh 'chassis' requires a bbox on bone '...fbx'`。
1. `MissileType`：对地 `eAGM`、对空 `eAAM`。
2. `PhysicalProperty` 里的数字是 **WeaponIndex**（炮塔号），不是挂点序号。
3. 弹体网格**必须放独立子目录**（同目录多个 FBX 会被 AssetCooker 合并成一份 `mesh.neu3`），
   并且**必须带 `fx_fumee_missile` 锚点**——缺了是加载期 Fatal（`Missing anchor bone`），
   报错指向 `Depiction.ndfbin`，真因在 FBX。

**【验收】** 静止时车上应出现弹；开火后弹消失、变空架。
Showroom 里也要有（否则是 §1 第 7 项的 Showroom 版没写）。

---

## 4. ⭐ 出管方向：必须做一份独立挂架网格

> **一句话**：导弹出管的方向来自**挂架网格里的出管 box**，不来自车体网格，也不来自武器描述器的俯仰数值。
> 所以要做的是：把发射臂（连同出管轴）拆成一份**独立、无动画**的挂架网格，
> 让 `MissileCarriage.MeshDescriptor` 指向它。

### 4.1 现象与判据

**现象**：展开后发射架已经抬到 70°，导弹却**水平出管**，先平飞一段再急转拉起。
换「垂发」就是发射管立着、弹却朝天随机方向窜。

**【原理】方向由谁给**

1. `MissileCarriage.MeshDescriptor` 指向谁，引擎就去**谁的网格**里找出管 box。
2. 那份网格**不能带 deploy / fold 动画**。动画会让骨骼姿态随状态变，
   绑定姿态（收拢）下导轨是水平的，出管方向就退回 0°。
3. 姿态要**烤成展开态**（本例 +X 抬 70°），坐标用**车体坐标系**，与展开态车体重合。

两条判据（都不是猜的）：

**判据一：骨骼名表。** `WARNO.exe` 里 `missile_%1` 与 `roue_%1`、`axe_canon_0%1`、
`roue_0%1`、`base_tourelle_0%1` **同处一张格式表** —— 同一张表全是标准单位骨架的骨骼，
所以它是按**武器号**索引的导弹出管挂点，不是碰撞体、也不是特效点。

**判据二：源码注释。** `Gameplay/Gfx/Units/DepictionOperators.ndf` 里
`DepictionOperator_WeaponMissileCarriageFire` 的原文：

> tir instantané utilisant une box de départ de tir dans le MissileCarriageConnoisseur
> et non pas dans le skeleton du mesh principal

出管 box 取自 MissileCarriageConnoisseur，**不是**主网格的骨架。

**这两条合起来也解释了一句流传很广的话**——「垂发必须换道尔模型」：
换的不是「引擎藏了个开关」，而是**那份烤着竖直 box 的网格**。

### 4.2 做法（照抄即可）

**第一步：建挂架网格** —— 用 `scripts/rail_mesh.py`，别手搓

```bash
blender -b -P scripts/rail_mesh.py -- \
    --src <展开态 blend> --out <mod>/.../Rail/<名>_Rail.fbx \
    --bones missile_1,canon_01,as_1_1 --expect-elev 70
```

它做四件事：抄骨骼世界矩阵 → 建 4 mm `Chassis`（沿轴线摆正）→ 三角化 → 落一张 4×4 贴图并导出。
两道守卫都是踩坑换来的：**期望仰角不符**、**骨骼不共姿态**（最常见原因是 `--src` 给了收拢态文件，
动画驱动的骨骼还停在平位，而烤死的骨骼已是 70°）。

⚠ **取坐标必须用「展开态」那份 blend。** 收拢态文件里，由 deploy 动画驱动的骨骼
（如弹体挂点 `as_1_1`）仍在水平位，抄出来的方向和轴线对不上。


| 项 | 要求 | 为什么 |
|---|---|---|
| 目录 | 单位资产目录下的**独立子目录**（如 `<Unit>/Rail/`） | 同目录多 FBX 会被合并成一份 `mesh.neu3` |
| 贴图 | FBX 同目录放一张同名 PNG（哪怕 4×4 纯色） | 缺了报 `fatal: File not found` |
| 面数 | 全三角面 | 四边形报 `Mesh not exported triangulating faces`（AssetCooker 不做三角化） |
| 体积 | 越小越好（本例 4 mm 立方体） | 万一引擎把它画出来也不可见 |
| 根节点 | 必须叫 `Chassis` | 手册硬要求：主部件名 |

节点（坐标 = **车体坐标系**，与展开态完全重合）：

| 节点 | 类型 | 位置（本例） | 朝向 |
|---|---|---|---|
| `Chassis` | 4 mm 立方体（12 三角面） | 弹体中心 | 沿发射架轴线 |
| `as_1_1` | 空 | 弹体中心 | 同上 |
| `missile_1` | 空（**出管挂点**） | 弹体中心 | 同上 |
| `canon_01` | 空（炮口轴） | 发射架前端 | 同上 |

**挂到哪根父骨**：挂 `Tourelle_01`（yaw 骨），**不要**挂随动画走的枢轴（如 `MSL_Pivot`）。
后者绑定姿态是 0°，方向会退回水平；挂 yaw 骨则无论读动画姿态还是绑定姿态都是目标角度，
而且随炮塔转向，方位角仍正确。

**第二步：NDF 两处**

```ndf
export Modele_<车>_Rail is TResourceMesh
(
    Mesh="GameData:/Assets/3D/Units/<阵营>/Char/<Unit>/Rail/<Unit>_Rail.fbx"
)
```

```ndf
export MissileCarriage_<车> is TMissileCarriageConnoisseur
(
    MeshDescriptor = $/GFX/DepictionResources/Modele_<车>_Rail    // ← 唯一的改动点
    ...
)
```

`_Showroom` 那份如果写的是 `MeshDescriptor = ~/MissileCarriage_<车>.MeshDescriptor`，自动跟随，不用改。

**第三步：参数同源**

网格里的角度**不要手写常量**，从「展开态」的绑定文件里现抄世界矩阵。
发射架角度一改，重跑一次挂架网格就自动跟上；手写常量迟早和动画打架。

**第四步：只改必需的那一个字段**

`AngleRotationBasePitch` / `MinPitch` / `MaxPitch` 保持武器本来的值即可，**不要**指望它们改方向。
（例外：如果改过基角、想退回，记得 `MinPitch < BasePitch <= MaxPitch` 是编译硬约束。）

### 4.3 三个「看起来对、其实不够」的做法

| 做法 | 结果 |
|---|---|
| 只改 `AngleRotationBasePitch` | **无效**。方向不取这个值。反例就在同一张表里：`FV438_Swingfire_UK` 基角 **−30°**，而它的发射箱明明是仰着的 |
| 只往**车体**网格里加 `missile_1` / `canon_01` | **有效但脆弱**。方向对了，可它依赖"引擎读到动画姿态"；车体网格带 deploy/fold 动画，绑定姿态下导轨水平，读法一变就退回 0° |
| 把 `MinPitch/MaxPitch` 锁死 | 锁的是炮塔别乱抬，不是出管方向 |

### 4.4 遗留与清理

车体网格里那份冗余骨骼（上表第二条）**可以留着当退路**：两条路径都是同一个角度时，
无法从行为上区分引擎读的是哪一份。真要清理，删完必须**重测一次「沿发射架出管」**再收工。

### 4.5 挂点位置：用**沿弹轴的包围盒中点**，不是顶点均值

方向对了，位置错了同样表现为「弹体不对」——而且表现是**钻地 / 悬空**，
不是不显示，很容易被当成「起竖角太大」或「车太矮」去调错对象。

**机制**：`ProjectileModelResource` 指向的弹体模型，原点就是**包围盒中心**
（建弹时 `extract_missile.py` 会把原点归到 bbox 中心）。引擎把这个原点贴在
挂点骨骼上，所以挂点必须落在弹体的几何中心。

**坑**：从车体网格里剥弹体时，最自然的写法是取顶点均值：

```python
c = vs.mean(axis=0)      # ✗ 尾翼/格栅舵顶点密，均值被拉向尾部
```

圆点 9M79 实测均值偏离几何中心 **2.052 m** —— 实例化后整枚弹沿弹轴下滑同样距离，
弹尾钻进地面 0.48 m、弹尖比导轨前端低 2.01 m。而车体网格里那份弹体最低点还有
1.532 m，**在 Blender 里完全看不出问题，只在游戏里显形**。

**做法**：

```python
proj = (vs - c) @ np.array(axis)
lo, hi = proj.min(), proj.max()
mid = (lo + hi) / 2.0                     # ✓ 沿弹轴的包围盒中点
tail_z = (c + axis * mid).z - (hi - lo) / 2 * axis.z
assert tail_z > 0.3, "挂载后弹尾离地仅 %.2f m" % tail_z

# 炮口轴仍取弹尖内缩几厘米
canon_off = hi - 0.05
```

**本地怎么验**（引擎摆的是实例，不是网格里那一份）：取 `missile_N` 的世界矩阵，
把弹体模型以该矩阵实例化，量 bbox 最低点。脚本 `scripts/render_ground.py` 就是
干这个的：红=按骨骼矩阵摆的实例、绿=按几何中心摆的参照，**两者重合才算对**。
断言判据：实例最低点应等于车体网格里那份弹体的最低点（圆点 1.53 m）。

### 4.6 验收

打好一发看三点：

1. 弹沿发射架轴线出去（不再先平飞再拉起）；
2. 发射架角度没翻倍（基角若也调过，可能出现 70°+70°=140° 的「翻到车头上方」）；
3. 炮塔转向时出管方向跟着转。

---

### 4.7 顺带：发射架的起竖 / 收拢动画怎么挂

**算子**：`DepictionOperator_AnimationDeployable`，五个槽各指一个动画文件：

```ndf
export DepictionOperator_Deployable_<车> is DepictionOperator_AnimationDeployable
(
    DeployAnimation    = TResourceMatrixArrayAnimation( FileName='..._deploy.fbx' PlayInLoop=false )
    FoldAnimation      = TResourceMatrixArrayAnimation( FileName='..._fold.fbx'   PlayInLoop=false )
    IdleAnimation      = TResourceMatrixArrayAnimation( FileName='..._deploy.fbx' PlayInLoop=false )
    MoveFrontAnimation = TResourceMatrixArrayAnimation( FileName='..._fold.fbx'   PlayInLoop=false )
    MoveBackAnimation  = TResourceMatrixArrayAnimation( FileName='..._fold.fbx'   PlayInLoop=false )

    DeployFromMoveTime = 1.0
    DeployFromTurnTime = 1.0
    FoldForMoveTime    = 1.0
    FoldForTurnTime    = 1.0

    FilterTurretBoneForAllAnimation = false
)
```

**触发不需要部署模块。** 这个算子是**由移动状态驱动**的：停车 → 播 Deploy，起步 → 播 Fold。
先例 `M113_ADATS_CAN` 的单位块里**没有** `TWeaponDeploymentModuleDescriptor`，却挂了同一个算子。
所以「车停下起竖、开走收拢」不需要额外的部署时间字段。

**`FilterTurretBoneForAllAnimation`**：是否让动画覆盖炮塔骨（`tourelle_*` / `axe_canon_*`）。
`false` = 动画可以驱动炮塔骨；改它之前先想清楚会不会和瞄准算子抢同一根骨。

**坑**：动画只烘焙**对象级**变换，导出 FBX 时必须开 `bake_anim` 且帧范围覆盖整段，
否则 `Gen/AllPlatforms/Animation/.../<名>_deploy.baf` 里是空的（文件照样生成，不报错）。
判据是 baf 大小与上一次成功构建相同，且模型在游戏里真的会动——**编译通过不代表动画进去了**。

#### 4.7.1 弹体挂点怎么跟着发射架动：**父级保持静态，逐帧打关键帧**

`.baf` 是**逐节点的绝对矩阵**，引擎不做层级推导。所以：

- 挂点父级是静态骨（`tourelle_01`）时，骨骼矩阵恒定 → 架收了、**弹体还立在发射位**；
- 挂点如果挂到**网格对象**（如发射臂 `Canon_01`）下，它就不再是"骨架里的骨"，
  引擎找不到 `missile_N`，弹体退回**模型原点**（实机表现：弹心落在车体中部、
  弹头从车头下方探出，停车瞬间跳回竖起态）。

**正解**：父级保持静态（挂在 yaw 骨/根骨这类空物体下），然后把骨骼**逐帧打关键帧**，
每帧设成 `臂的位移量 × 骨骼 rest 世界矩阵`：

```python
delta = arm.matrix_world @ arm_rest_world.inverted()
for name, rest in rest_worlds.items():
    o = bpy.data.objects[name]
    o.matrix_world = delta @ rest
    o.keyframe_insert("location", frame=f)
    o.keyframe_insert("rotation_euler", frame=f)
```

**必须同源的坑：枢轴。** 取 `arm_rest_world` 之前**不要**把臂的 `location` 归零 ——
如果臂的原点就在铰点（很常见），归零等于把它搬到世界原点：整根臂和挂点都绕车体中部旋转，
实机就是「弹体被甩到车头下方、架也移到车体中部」。这个重置从"臂原点在 (0,0,0)"的
机型（如 M752 的 `Boom`）抄过来会直接踩雷。

**验收**：读回烘焙出的 `_fold.fbx`，看末帧 `missile_N` 的坐标是不是你算的那个收拢位
（圆点：(−1.68, 2.77)，臂 (−4.29, 2.53)）。对得上再看图。

**状态：已在圆点 9K79 上实机验收通过**（起步放平、弹体随架躺下；停车随架竖起）。
两处坑都真撞过：先挂网格对象（弹体退回原点），后归零臂 location（弹体被甩到车头下方）。

#### 4.7.2 行军态「防埋车顶」有两个旋钮：抬头角 与 整体抬升

折叠终点弹体够不够高，取决于**两个独立参数**：

- **留抬头角**（不让发射架完全放平）—— 改的是**姿态**；
- **终点整体抬升**（把臂连弹一起上移）—— 改的是**高度**。

**先固定抬升、单独扫角度，再决定要不要抬头。** 圆点实测（抬升固定 0.34 m）：

| 行军角 | 弹轴仰角 | 弹体到车体最近距离 |
|---|---|---|
| 0° | 5.3°（弹轴本身比臂轴高 5.3°） | **0.153 m** |
| 5° | 10.3° | 0.116 m |
| 10° | 15.3° | 0.096 m |

**角度越低，间隙反而越大**：抬升不变时，放平会让弹尾随臂抬起。所以「必须留抬头」
多半是把「抬升不够」记到了角度头上。只有一种情况真的需要抬头：**弹头压到驾驶室** ——
那要单独看弹头那一端，而不是看全局最近距离。

**必须扫全过程，不能只看终点**：中段（20%–40%）才是擦车顶的高发段。
用项目脚本 `check_fold_sweep.py`（按 20/35/50/65/80/100% 出图 + 量最近距离）扫一遍。

---

### 4.8 ⭐ 武器描述器的角度参数：只管「能不能瞄」，**不管模型怎么摆**

`TTurretTwoAxisDescriptor` 里的三个角（弧度）是**瞄准解算的允许窗口**，
它跟"发射架在模型里长什么样、抬到多少度"**没有任何关系**——后者只由 deploy/fold 动画
和挂架网格决定（§4、§4.7）。实机反例：把 M752 的 `AngleRotationBasePitch` 从 10° 改到 70°，
发射架纹丝不动（§7 第一条）。

```ndf
TTurretTwoAxisDescriptor
(
    AngleRotationBase    = 0
    AngleRotationBasePitch = 1.3613568165555772   // 78°：基准仰角（发射架展开姿态）
    AngleRotationMax     = 3.141592653589793      // 360° 方位
    AngleRotationMaxPitch = 1.3962634015954636    // 80°：最多还能再抬 2°
    AngleRotationMinPitch = -0.34906              // −20°：允许往下压 20°
)
```

**⭐ 硬规矩：`AngleRotationMinPitch` 不要设成 0（也不要贴着 0）。**
把它设成 0 = 不允许任何俯角，于是**目标只要有一点高差**（站在稍高/稍低的地面上），
仰角解算就落进"够不到"的区间，武器判成不可瞄准 —— 实机表现为**杵在那儿不开火**，
而编译、加载、动画、出管方向全都正常，极难倒查。

| 弧度 | 角度 |
|---|---|
| −0.34906 | −20° |
| 1.22173 | 70° |
| 1.36136 | 78° |
| 1.39626 | 80° |
| 1.57080 | 90° |

**推荐起手值**（两种 TEL 都在用）：`Base = 发射架展开角`、`MaxPitch = Base + 2°`、`MinPitch = −20°`。
窗口是"相对基角"还是"绝对"不影响结论，关键是**两头都要留余量**，别把任何一头钉在 0。

> 记住两句话就不会再混：
> **动画看模型（deploy/fold + 挂架网格），瞄准看数值（三个角 + 射程）。**
> 反过来改，两边都不动。

---

## 5. 三处显示场景，各自独立注册

| 场景 | 文件 | 关键行 | 缺了的症状 |
|---|---|---|---|
| 战场 | `DepictionVehicles.ndf` | `SubDepictionGenerators = [ SubGenerators_<车> ]` | 车上永远没有弹 |
| 军械库 | `DepictionVehiclesShowroom.ndf` | 同上（Showroom 版） | 军械库里没有弹 |
| 幽灵（部署预览） | `DepictionGhosts.ndf` | — | **官方一律不挂子生成器，本来就不带弹**，别当缺陷修 |

---

## 6. 验收与判读

**按依赖顺序，跳步会误判**：弹在不在 → 弹跟着发射架动没有 → 打得出吗 → 出管方向对不对 → 打得到吗。

| 现象 | 先查 | 归因 |
|---|---|---|
| 车上完全没弹（静止/军械库都没有） | §1 第 6/7 项那**一行引用** | 子生成器没被注册，零报错 |
| 军械库没弹、战场有 | Showroom 版 `SubGenerators` | 两个场景各自注册 |
| 加载 Fatal `Missing anchor bone 'fx_fumee_missile'` | 弹体网格锚点 | 缺锚点，硬校验 |
| 弹有了但不跟发射架抬 | 弹体挂在哪个节点的子树下 | 挂点必须在会动的臂下 |
| 开火后弹不消失 | `PhysicalProperty` 与炮塔号 | `Tourelle{N}_MissileCount` 的 N 写错 |
| **弹水平出管 / 朝天乱窜** | §4：`MissileCarriage` 指向的网格 | 出管 box 不在挂架网格里 |
| 编译 `Mesh not exported triangulating faces` | 新挂架网格 | 先三角化再导出 |
| 编译 `File not found : .../X_D.png` | 新 FBX 所在目录 | 贴图必须跟着 FBX 走 |

---

## 7. 被推翻的判断（省钱用）

| 当初的判断 | 为什么错 | 正确结论 |
|---|---|---|
| 「出管仰角取炮塔基角 `AngleRotationBasePitch`」——依据是全表只有 Tor 是 89° | 相关性当因果；Tor 的 89° 是它那一型的结果。反例 `FV438_Swingfire_UK` 基角 −30° 而发射箱仰着 | 方向来自**挂架网格里的出管 box**（§4） |
| 「数值调不动就是引擎不支持垂发」 | 没查「这个值最终写到哪根骨骼上」 | 我们的俯仰骨是**无子节点的空骨**，网格里没有落点；补上挂架网格即成立 |
| 「行军态必须留 8–12° 抬头，否则弹体埋进车顶」 | **两个变量一起改**（抬头角 + 抬升量），功劳记在了抬头上 | 抬升量（≈弹半径）才是主因；角度放平到 0°，间隙反而更大（0.153 vs 0.096 m）。见 §4.7.2 |
| 「弹体挂在 yaw 骨上更稳（朝向不随动画变）」 | 朝向稳定 ≠ 位置正确；父级不动，收拢时弹体不动 | 父级保持静态，但**逐帧给骨骼打关键帧**跟臂走，见 §4.7.1 |
| 「把它挂到发射臂对象下面就会跟着动」 | 挂到**网格对象**下就不再是骨，引擎找不到 `missile_N`，弹体退回模型原点 | 见 §4.7.1：父级必须仍是空物体/骨，靠关键帧驱动 |
| 「烘焙前把臂的 location 归零更保险」 | 圆点臂原点就在铰点，归零＝搬到世界原点，整根臂绕车体中部转 | 从原点在 (0,0,0) 的机型照抄会踩雷；rest 矩阵要按真实位置取 |
| 「轮式车的轮子本来就不转（官方样例里没有 `Roue_*`）」 | 只看了 `Chassis` 子树；官方 `GAZ_66B` 的三个轮子是**根层 Mesh**。而且轮式车转不转由**推进算子**决定 | 轮式必须挂 `Propulsion_Wheels_Generic`；圆点从履带克隆源抄来的 `ContinuousTrack` 就是"纹丝不动"的真因（`24-rig-parts.md §4`） |
| 「武器描述器的角度参数能调发射架姿态」 | 它是**瞄准解算窗口**，模型姿态只由 deploy/fold 动画与挂架网格决定 | 改动画；角度参数只决定"打不打得到"（§4.8） |
| 「俯角（`AngleRotationMinPitch`）设 0 最省事」 | 0 = 不留任何俯角，目标**有一点高差**就落进够不到的区间，表现为站着不开火 | 两头都要留余量：`MinPitch = −20°`（−0.349 rad）起手（§4.8） |

**方法论**：查「某行为由哪个数值决定」之前，先查「这个数值最终写到哪个骨骼上」。
数值层怎么调都不动的，多半是模型层缺件。
反过来，**一次只改一个变量**：两个一起改，你会把功劳（或罪过）记在错的那个上。

---

## 8. 执行清单

**前置**
- [ ] 弹药是 `GuidedMissile`，放 `AmmunitionMissiles.ndf`
- [ ] `MissileDescriptors.ndf` 有飞行实体；`ProjectileSpeedGRU == MaxSpeedGRU`
- [ ] 弹体独立子目录 + `fx_fumee_missile` 锚点
- [ ] 瞄准窗口 `MinPitch` 留负余量（**不要设 0**，§4.8）
- [ ] 底盘类型 / 速度 / 道路加成 / 地形表成套（§9）

**顺序**
1. `MissileCarriage_*`（本体 + Showroom）
2. `SubGenerators_*`（本体 + Showroom）
3. 注册块里加 `SubDepictionGenerators`（**战场 + Showroom 各一处**）
4. 开火算子 + `Actions` tag + `WeaponShootData`
5. 建**独立挂架网格**（§4.2 四步），`MissileCarriage.MeshDescriptor` 指过去
6. 编译（走 `genmod_guard.py`，不看退出码）

**禁止**
- 别用 `AngleRotationBasePitch` 试图改出管方向
- 别把挂架网格和车体 FBX 放同一目录
- 别在挂架网格里放四边形
- 别用「原版没有先例」当「引擎不支持」（真反例见 §4.1）
- 别把 `AngleRotationMinPitch` 设 0（§4.8）
- 别让轮式车挂着履带的 `Propulsion_ContinuousTrack` 与 `TrackVehicleTerrainSpeedFactors`

---

## 9. 底盘：轮式 / 履带要分开配（速度、道路加成、地形系数）

TEL 都是"重载底盘"，速度差通常就是玩法差异的主要来源。**四个字段必须成套改**，
只改速度不改系数，会出现"面板写着 A、实际跑 B、进树林却是另一套"的割裂。

| 字段 | 在哪 | 管什么 |
|---|---|---|
| `TGenericMovementModuleDescriptor.MaxSpeedInKmph` | 单位块 | **基准速度**（非道路） |
| `TLandMovementModuleDescriptor.SpeedBonusFactorOnRoad` | 单位块 | 道路上的**加成倍率**（实际道路速度 ≈ 基准 × 它） |
| `TLandMovementModuleDescriptor.TerrainSpeedFactors` | 单位块（引用常量） | **每种地形的系数表**，轮式/履带是两张不同的表 |
| `TLandMovementModuleDescriptor.UnitMovingType` | 单位块 | `Wheel` / `Track` / `WheelAmphibious`…，决定换挡、转向、越野表现 |
| `TUnitUIModuleDescriptor.DisplayRoadSpeedInKmph` | 单位块 | **只影响面板显示**，不参与任何计算 |

### 9.1 `DisplayRoadSpeedInKmph` 是"贴纸"，别拿它反推

全库 2269 个带移动模块的单位实测：`Display ≈ Max × RoadX` 的命中数 **0/1576**。
官方惯例是**按速度档位抄一个整数**（同一档位的车取值完全一致），与真实计算无关：

| 底盘 | 基准 `MaxSpeedInKmph` | `SpeedBonusFactorOnRoad` | `DisplayRoadSpeedInKmph` | 样本 |
|---|---|---|---|---|
| 履带 | 45 | **2.09** | 75 | FV432 全系、M47/M48、FV438 Swingfire（一致） |
| 履带 | 55 | 1.71 | 75 | AMX-13 / AMX-30B 系 |
| 履带 | 70 | 1.43 | 80 | AMX-30B2 |
| 轮式 | 60 | 2.08 | 100 | BM-21 / BTR-40 / CUCV |
| 轮式 | **65** | **1.92** | **100** | BM-21V Grad-V、AMX-10 RC |
| 轮式 | 90 | 1.39 | 100 | AML-90 / Auverland |

> 结论：**定速度 = 先定档位，再抄同档位的整行数**。自己算 `Max×系数` 填显示值，
> 会和全库所有单位都不一样，而且面板与实际依旧对不上（因为显示本来就不参与计算）。

### 9.2 地形系数：轮式与履带差在哪

两张表都在 `GamePlay/Constantes/TerrainSpeedFactors.ndf`：

| 地形 | `WheelVehicleTerrainSpeedFactors` | `TrackVehicleTerrainSpeedFactors` | 谁强 |
|---|---|---|---|
| `ForetDense` 密林 | 0 | 0 | 一样进不去 |
| `ForetLegere` 疏林 | **0.4** | **0.5** | 履带 |
| `PetitBatiment`/`Batiment`/`Ruin`/`Rocher` | 0 | 0 | 一样 |
| `EauPeuProfonde` 浅水 | **1.0** | **0.4** | **轮式（能趟水）** |
| `EauProfonde` 深水 | 0.3 | 0.4 | 履带 |

所以"轮式快、履带稳"是错的简化：**轮式在疏林更慢、在浅水里不受影响**，履带反过来。
改 `UnitMovingType` 时**必须同时换表**，否则会出现"轮式车挂着履带表"——不报错，但数值全错：

```ndf
// 轮式（示例：圆点 9K79）
TLandMovementModuleDescriptor
(
    UnitMovingType = EUnitMovingType/Wheel
    SpeedBonusFactorOnRoad = 1.92
    TerrainSpeedFactors = $/GFX/Terrains/WheelVehicleTerrainSpeedFactors
)

// 履带（示例：M752 Lance）
TLandMovementModuleDescriptor
(
    UnitMovingType = EUnitMovingType/Track
    SpeedBonusFactorOnRoad = 2.09
    TerrainSpeedFactors = $/GFX/Terrains/TrackVehicleTerrainSpeedFactors
)
```

**本项目定稿**（2026-11-06）：

| 车 | 底盘 | `MaxSpeedInKmph` | `SpeedBonusFactorOnRoad` | 地形表 | 面板显示 |
|---|---|---|---|---|---|
| 圆点 9K79 | 轮式 6×6 | 65 | 1.92 | Wheel | 100 |
| M752 Lance | 履带（M113） | 45 | 2.09 | Track | 75 |

### 9.3 两种 TEL 的飞行模块要不要一致？

**要，而且"一致"包含速度。** `TGuidedMissileMovementModuleDescriptor` 的
`DefaultConfig.MaxSpeedGRU` 必须等于弹药 `ProjectileSpeedGRU`（§2 的硬约束，全库 198/198 恒等）。
所以"照抄圆点的移动模块"= 连 `MaxSpeedGRU` 一起抄，弹药侧也要同步改，
否则两个速度字段打架（贴地飞 / 到不了目标）。

抄的时候**整块**抄，别只抄 `AutoGyr`：拐弯半径、爬升加速、末段触发距离、混沌抖动都在同一块里，
参数互相咬合（例如 `AutoGyr` 小 = 转弯半径大，配合 `CruiseAltitudeGRU` 决定弹道是"抛物线"还是"梯形"）。
