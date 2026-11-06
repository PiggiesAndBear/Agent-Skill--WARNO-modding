# 可动部件与程序化动画（网格侧）

**本文件管**：让模型上的部件"动"起来的一切——拆件、定枢轴、炮塔、履带与轮、起落架与舱门、旋翼、挂点发射口。
**不管**：锚点契约与导入流水线（`23-mesh-import.md`）、材质与贴图（`25-asset-pipeline.md`）、
depiction 注册与 ndf 侧挂载（`21-depiction.md`）。

> 每个子系统都按同一副骨架写：**命名契约 → 数据侧开关（ndf）→ 网格侧做法 → 验收**。
> 加新子系统照着这套骨架加一节即可。
>
> 现象速查在 `23-mesh-import.md §8` 的总表里（表横跨三个文件，条目里标了归属）；
> 已被推翻的判断见 `23-mesh-import.md §10`。

## 目录

| 节 | 管什么 | 一句话判据 |
|---|---|---|
| §0 | 三套机制对照 | 先确认你要动的东西归哪一种机制，别混 |
| §1 | 拆件 | 三角汤必须「焊接 → 连通块 → 整壳归组」 |
| §2 | 枢轴 | 从几何求，骨骼坐标可能是错的 |
| §3 | 炮塔 | 能不能转取决于拓扑，不取决于算子 |
| §4 | 履带与轮 | 履带看材质名，轮子看节点名 |
| §5 | 起落架 / 舱门 | 走 CoatingRecipe，不在 depiction 里 |
| §6 | 旋翼 | `helice_ls_N` / `bloc_moteur_N`，轴也要并入 |
| §7 | 挂点与发射口 | 算子类型决定读不读 `Anchors` |

## 0. 先分清三套机制（别混）

| 机制 | 驱动什么 | 挂在哪 | 命名契约 |
|---|---|---|---|
| `DepictionOperator_Rotors`（内联 `THelix`） | 旋翼正/反转 | depiction 主注册块 | `helice_ls_N` / `bloc_moteur_N` |
| `DepictionOperator_Turret_1_Aim` + `TTurretTwoAxisDescriptor` | 炮塔回转 + 俯仰 | `WeaponDescriptor` 的槽 + depiction | `tourelle_0N` / `axe_canon_0N` |
| **`TCoatingRecipe`（涂层配方）** | 起落架收放、舱门/整流罩折叠 | `DepictionCoatingPantry.ndf` + `DepictionCoatingCookbook.ndf` | 网格节点名（`roue_*` / `spatule_*`） |

前两种在 depiction / 武器里；**第三种不在 depiction 里**——这就是"起落架收放找不到配置"的原因，
翻遍 `DepictionAerialUnits.ndf` 也不会有。

---

## 1. 拆件：从「三角汤」里拆出可动部件

### 【原理】为什么必须整壳拆

WARNO **没有 armature 驱动部件**：一个部件动不动，取决于「它是不是独立节点 + 节点名有没有被算子引用」，
不取决于蒙皮权重。所以想让旋翼头跟着转、让起落架收起来，唯一的路是把它从 `Chassis` 里**拆成独立网格**。

但成品模型（尤其是外部扒来的）的 `Chassis` 往往是**三角汤**：Ka-58 是 38 025 个顶点、
12 675 个互不相连的孤面。两条天真的路都会坏：

| 做法 | 后果 |
|---|---|
| 按面中心分区 | 把壳体切开，接缝落在曲面中间，动起来露内壁 |
| 按坐标盒子直接裁面 | 同上，而且会把相邻件切半，出现半截壳飘在空中 |

### 【操作】先焊接 → 求连通块 → 整壳归组

```python
# 1) 按重合顶点焊接（1e-4），把"三角汤"还原成真实壳体
# 2) 连通块（并查集 / DFS）→ 每个连通块 = 一个"真实壳"
# 3) 整壳判定：壳的包围盒**完全**落在目标盒子里，才整体归组
if bx0 <= x0 and x1 <= bx1 and by0 <= y0 and y1 <= by1 and bz0 <= z0 and z1 <= bz1:
    for f in shell: out[f] = tag
```

Ka-58 实测：38 025 顶点 → 焊接后 7 750 → **381 个真实壳**。

| 拆什么 | 判据（世界坐标） | 结果 |
|---|---|---|
| 旋翼头（上/下） | `rmax<2.0 and (zmin>3.30 or (zmin>3.15 and rmax<0.75))`；`zmin>=3.90` 归上组 | 64 壳 / 2 214 面 |
| 主起落架 ×2 | 盒 `x 2.30..3.90 / abs(y) 0.72..2.00 / z −0.10..1.30` | 各 360 面 |
| 尾轮组 | 盒 `x −5.60..−4.60 / abs(y) ≤0.30 / z −0.10..1.30` | 612 面 |
| 整流罩面板 ×2 | `2.15<x0 / x1<3.15 / 0.70<minAbsY / maxAbsY<1.35 / 0.88<z0 / z1<1.42` | 各 102 面 |

**盒子上界要卡得比"看起来"低**：起落架盒子定 `zmax ≤ 1.30`，是为了把机身侧面的整流罩（zmax 1.4+）
排除在外；定成 1.5 就会把一块蒙皮连同轮子一起拆走。

> 拆完新网格**必须继承 `use_smooth`**，否则 FBX 按面拆顶点、可能顶破 65536 上限，见 §4。
>
> **工具**：`scripts/split_shells.py` 就是这一套（焊接 → 连通块 → 整壳归组 → 拆节点 → 导出），
> 部位用 JSON 的 AABB 描述；拆前先用 `scripts/mesh_check.py` 看壳数/边界边比例/锚点清单。

### 【原理】拆之前必须回答：这块东西背后是什么

同一个模型里，"表面的一块"可能是两种东西，处置完全不同：

| 类型 | 拆走会怎样 | 判据 |
|---|---|---|
| **实心件 / 独立壳体** | 安全，机身蒙皮完整 | 隐藏它后，机身无洞 |
| **单层曲面 + 机身凹兜** | **露洞**（凹兜就是它的"背面"） | 隐藏它后，原地仍剩同形灰壳 |

Ka-58 的整流罩面板属于后者：外层面板 102 面可拆，**背后的凹兜是主壳体的一部分**（1783 面那块），
拆不开。所以它只能"压平"、不能"搬走"——转 100° 或平移 0.8 m 都会把凹兜让出来，看着像破了个洞。

判定手法（10 秒，两条一起用）：

```python
# ① 隐藏 + 背面剔除 + 红底渲染：出现红色 = 拆走必开洞
sh.show_backface_culling = True;  world.color = (0.85, 0.15, 0.15)
# ② 射线回打：隐藏后原地命中的是哪个壳？是主壳体 → 只是覆盖件
scene.ray_cast(dg, 相机方向, ...)  →  ob.name / face index → 归属壳
```

⚠ **不要用单色 Workbench 的"变黑"当判据**：单层曲面的背面本来就发黑，很容易被误判成"空腔"。
要判断"是实心还是贴片"，只能靠「隐藏 + 红底」或「隐藏 + 射线回打」。
（本项目就因此先误判成"有洞"，绕了一大圈。）

---

## 2. 枢轴：从几何求，别信骨骼

### 【原理】

Baked 模型的骨架骨骼位置，经常和几何真实回转中心**不是一回事**。Ka-58 实测：

| 旋翼 | 骨骼 / 旧枢轴 | 三桨叶质心外心 | 偏差 |
|---|---|---|---|
| 上 | (0, −0.55) | (0.617, 0.001) | **0.83 m** |
| 下 | (0, −0.55) | (0.534, −0.001) | **0.79 m** |

后果不是"转得难看"，而是**桨叶绕一个离轴 0.8 m 的点公转**，桨盘整体在机身上画圈
（游戏里表现为"上层桨像一顶歪帽子"）。这种错静止时完全看不出来，只有转起来才暴露。

### 【操作】用三片桨叶的质心求外心

```python
# 每片桨叶求质心 → 三点唯一等距点（外心）→ 上下两副取中点
AXIS_XY = ((0.617+0.534)/2, (0.001-0.001)/2)   # (0.575, 0.000)
```

取中点而不是各自用自身外心：上下两组与轴筒共用同一根轴，否则两副桨会互相剪切（单桨残余偏心 ≤4 cm，
8 m 半径下不到 0.5%，可忽略）。

### 【验收】

**换枢轴不能动任何几何**：顶点按 `P − HUB` 中心化、节点再放到 `HUB`，世界坐标原样还原。
所以判据是死板的——导出前后所有网格的包围盒必须**逐位一致**：

```
Helice_LS_1  Z 4.116..5.099       改枢轴前后相同
Helice_LS_2  Z 2.508..3.617       同上
```

对不上就说明中心化或父级矩阵写错了，不要往下做。

> **工具**：`scripts/mesh_check.py` 会逐个网格打印包围盒与焊接后壳数，改前改后各跑一次对比即可。

### 2.1 【陷阱】`matrix_world` 是惰性求值的 —— 枢轴会飞到模型外

**症状**：桨叶（或任何可动件）在游戏里**飘出去、绕着整个机体公转**，半径大到明显不合物理
（柳叶刀实测公转半径 **11.6 m**，而机体只有 1.6 m）。静止截图完全正常，几何位置一点没错——
错的只有枢轴，所以**预览图看不出来**，必须读节点原点才能发现。

**真因**：Blender 的 `matrix_world` 是惰性计算属性。写下面这段"摊平"代码时，改了 `parent` 和
`matrix_basis` 之后**不刷新依赖图**，紧接着读到的 `matrix_world` 仍是导入时的旧矩阵：

```python
for ob in meshes:
    mw = ob.matrix_world.copy()
    ob.parent = None                      # ← 改完这两行
    ob.matrix_basis = Matrix.Identity(4)
    me.transform(mw)                      # 顶点已经是世界坐标了
    me.transform(R); me.transform(Scale)

# ✗ 此处 matrix_world 还是旧值（带 glTF 的平移 11.11 + 缩放 0.49）
hub = sum(prop.matrix_world @ v.co for v in prop.data.vertices) / n
```

于是 `hub` 被算成 **10.62**（真值 −0.84）。后面的 `data.transform(−hub)` 和 `empty.location = hub`
都用了这同一个错值，**位置误差互相抵消**（几何落回了正确位置），但枢轴停在了 10.62+0.15 处。

**修法**（两条都做）：

```python
# ① 摊平循环之后强制刷新，再读矩阵
bpy.context.view_layer.update()

# ② 读之前断言它确实已经是单位阵
dev = max(abs(prop.matrix_world[i][j] - (1.0 if i == j else 0.0))
          for i in range(4) for j in range(4))
assert dev < 1e-5, "摊平没生效，枢轴会飞到远处（偏差 %.4f）" % dev
```

**验收（比包围盒更直接）**：导入导出的 FBX，比对三个值必须相等——空物体原点、网格物体原点、
网格**世界**质心：

```
Bloc_Moteur_1  origin=(-0.841, 0.000, 0.597)
Helice_LS_1    origin=(-0.841, 0.000, 0.597)   worldC=(-0.841, 0.000, 0.597)  ← 三者重合才对
```

再加一条不变式：网格**局部**质心必须为 `(0,0,0)`（`|c| < 1e-4`）。只要这条成立，
无论枢轴放在哪，旋转都不会公转。

> 同一份代码在四旋翼（`uav/bake_uav.py`）上没出问题，是因为它用 bmesh 直接操作顶点、
> 不走"读 `matrix_world` 求质心"这条路。**换模型 = 换一条路径，不能假设上一份脚本的写法还成立。**

---

## 3. 炮塔：能不能转，取决于拓扑，不取决于算子

炮塔是**独立 Mesh 子节点 + 旋转算子**，但"能不能拆出这个子节点"由原始网格的拓扑决定。
同一个结论把舰船判死、把直升机放行——先看 3.2 的失败案例，再看 3.3 的成功判据。

### 3.1 机制与前提（先读 3.2 的失败记录）

> **本节结论已于实机证伪一次，务必先读 §3.2「失败记录」再决定要不要动手。**
> 一句话：**「删原凸起 + 补洞 + 重建独立炮塔」这条路，在体素重构过的单层壳上走不通**，
> 实机表现为整片内部结构暴露。渲染图看不出来，只有进游戏才暴露。

炮塔**不是蒙皮动画**，是「独立 Mesh 子节点 + 旋转算子」：

```
Tourelle_0N [Mesh]        ← 绕 Z（水平回旋）
  └ Axe_Canon_0N [Mesh]   ← 绕 Y（俯仰）
      └ Canon_0N [Mesh]
          └ fx_tourelleN_tir_0M [Null]   ← 锚点挂这里，所以跟着转
```

配套算子 `TCosmeticTurretOperatorDesc`（官方 `DepictionOperators.ndf` 提供
`DepictionOperator_Turret_1..5_Aim`，**只到 5**）：

```
ZAxisNode = 'tourelle_0N'      YAxisNode = 'axe_canon_0N'
```

它是 **Cosmetic**——只驱动网格，不改弹道。轨道/间瞄武器弹道与炮口无关，
所以"看起来在瞄"就够，不会转了打歪。

**先做一次体检，别直接动手**。同时满足以下两条，原模型一定转不了：

1. 节点树里除 `Chassis` 外没有别的 Mesh（炮塔几何已合并进去）；
2. `tourelle_0N` / `axe_canon_0N` 是 Null 且位置在 `(0,0,0)`（转了也没几何动）。

**再判能不能"切"**：

- 原始工程的 Mesh 对象若全是数万顶点的跨舰体大块（按材质/分块切的），
  说明没有"一座炮塔"这个对象——查对象名 + 在炮塔坐标半径 15 m 内数命中对象数，
  命中 0~1 个就是没有；
- 成品网格若在炮塔位置只有 100~200 面，切出来是团块，旋转必穿模；
- 相邻炮塔的炮管若首尾相接（本项目单管炮口 x=−6.4、三联基座从 x=−4 起），
  边界根本划不干净。

→ 结论：**不能切**。这一点没错。但「那就重建」——**错**，见 §3.2。

**重建时三条硬规矩**（若确实要做，仍须遵守；但这三条只能保证「转得对」，保证不了「壳不破」）

| 规矩 | 原因 |
|---|---|
| `Tourelle` 原点放在**船壳下表面中心**（Z 转轴） | 原点偏了 = 绕偏心轴甩动 |
| `Axe_Canon` 原点放在**耳轴**，几何绕它俯仰 | 否则俯仰时炮管绕着炮塔中心划圈 |
| 导出前把场景里**所有** Mesh/Null 一起选上 | 只选新建对象会丢掉硬校验骨骼 → CTD |

> 实测踩坑：第一版 `use_selection=True` 只选了新建的 19 个对象，
> 10 个硬校验骨骼全没进 FBX。改成遍历 `scene.objects` 过滤 `{'MESH','EMPTY'}`。

**NDF 两处**：`DepictionOperators.ndf` 补缺号算子（本项目补了 `Turret_6_Aim`）；
主描绘 `Operators` 列表注册 `Turret_2..6_Aim`。

> 定位坑：`DepictionOperator_Turret_1_Aim,` 全库出现 **402 次**（每个带炮塔的单位都有）。
> 必须先按 `BlackHoleKey = '<本单位>'` 切出单位块，再在块内替换，否则一次改坏 400 个单位。

**外观取舍要提前说清**：若某座炮塔在原模型里本来就没有炮管（内藏/收纳状态），
重建就等于**凭空造炮管**——这是新增设计，不是还原，交付时要写进文档。

### 3.2 失败案例：舰船融合壳上挖洞，必露底

**做法**：删掉成品网格上 6 处炮塔凸起（113 面），`holes_fill` 补 160 条开放边，
新建锥台基座 + 摇架套环 + 炮管（3 个 Mesh × 6 座），层级按官方
`Tourelle_0N → Axe_Canon_0N → Canon_0N → fx_...` 挂好，NDF 注册 `Turret_1..6_Aim`。
**FBX 校验、Node 层级、锚点全过，Blender 6 轮渲染看着都正常，编译 `rc=0`。**

**实机结果**：舰体腹部整片「内部结构」暴露——船底变成一片亮白折面，
原本的腹板、凹槽、内腔全部露在空气中，炮塔反而像浮在破洞上。
两轮截图（远景 + 近景）都确认不是某个角度的问题，是整段船腹的壳没了。

**根因（拓扑性，不是参数问题）**

| 环节 | 错在哪 |
|---|---|
| `holes_fill` 能补的只是「选面边界围成的环」 | 它生成一张**薄封盖**，不是有厚度的船底 |
| 体素重构后的船腹是**单层壳**，没有内壁 | 壳上开任何洞，视线直接穿到**对侧壳的背面**——这就是「内部结构暴露」 |
| 凸起与船壳是**融合**的（体素 0.8 m 已把两者并成连续面） | 删凸起 = 在承力面上挖掉一块，周围一圈失去支撑，补洞后与真实轮廓错位 |
| Blender WORKBENCH 渲染 | 单面 + 固定视角，背面穿透在截图里**看不出来**；引擎里双面着色才现形 |

**为什么官方模型能做**：官方 `.fbx` 本来就是「船壳 + 独立炮塔件」的**装配体**，
有真实内壁和基座环，转动的是本来就独立的部件。我们的网格是**一张皮**，
先天不具备「拆件」的前提。**「能转」不是靠算子，是靠拓扑。**

**判据（动手前先过这一关，任一不满足就别做）**

1. 原始工程里存在**独立的炮塔 Mesh 对象**（不是按材质切的跨舰体大块）；
2. 该 Mesh 有**自己的体积**，**不必闭合**——但边界边比例要与官方同级
   （实测基准：官方 `M1_Abrams/Tourelle_01` 406 条边界边 / 1,796 顶点 = **22.6%**；
   外部坦克 T-90A 炮塔 9,334 / 34,107 = 27.4%，同一档，可以直接用、不用补洞）；
   若比例远高（>50%，全是散面片）才是真的没体积；
3. 船壳在炮塔位置**本来就开了孔**、有基座环承接；
4. 面预算允许（切件后船壳与炮塔各自仍闭合，不掉到几十面）。

本项目 4 条全不满足 → 正确做法是**不做可动**，炮塔留作静态结构 + 锚点开火。

> **判据 2 的修正（2026-11 实测）**：早期写的"必须有闭合体积（有内壁）"过严。
> 官方炮塔本身就是**开敞薄壳**——只要边界边比例与官方同档，就是行业常规做法，不是缺陷。
> 用户实机看到"露内部"的真正原因是**在融合成一块的船壳上挖洞**（判据 1、3 不满足），
> 不是"炮塔没闭合"。这两件事必须分清。

**次优方案（若一定要视觉变化）**

- 用 `DepictionOperator_WeaponInstantFire` 的 `Anchors` 表达"不同炮口轮流开火"，
  静态炮塔也能有多点火力感；
- 想真的转，只能回建模软件从**原始高模**重做「船壳开孔 + 独立炮塔件 + 内壁」，
  成本约等于重做整船，且要重新过 65,536 顶点/UV/减面全流程。

**代价清单（本次回滚掉的改动，供估算再犯成本）**

- FBX：`Chassis`(1 Mesh) + 22 Null → 4 Mesh + 22 Null；顶点 7,572 → 8,326
- NDF：`DepictionOperators.ndf` 新增 `Turret_6_Aim`；主描绘注册 `Turret_2..6`
- 编译产物 `Mesh_All.spk` 425 KB → 433 KB

**留下的教训**

- **渲染图不是验收。** 壳层完整性、背面穿透、内部暴露这类问题，只有进引擎才看得见。
  凡动过几何删除/补洞，必须实机看一眼，别拿 Blender 截图交差。
- **「结构能对上」≠「视觉能接受」。** 层级、锚点、编译全绿，玩家一眼看到的是整片露底。
- 编号先查台账：本轮误用了已被「轨道120与加特林」占用的 M29。

### 3.3 成功案例：小口径机炮只拆炮管

§3.2 的失败根因是「**在融合成一块的壳上挖洞**」。同一个原理反过来用，Ka-58 成立了：

| 环节 | 做法 |
|---|---|
| 切什么 | **只切炮管 304 面**：面中心贴炮管轴线（`x>5.00`、`abs(y)<0.12`、`0.60<z<0.85`），且**所有顶点都细**（`abs(y)<0.155`、`0.50<z<0.92`）——加这一条是为了不带进机匣 |
| 不切什么 | **机匣留在 `Chassis`**。实测这一段机匣就是**机腹蒙皮本身**，切走必开洞（补扇形封口面、补俯视轮廓顶盖两条路都试过，都失败） |
| 为什么不会穿模 | 炮管轴线 Z 0.735 **低于**该段蒙皮 Z≈1.0，横扫 ±110° 全程从机身外侧划过 |
| 层级 | `Tourelle_01`(EMPTY, 绕Z) → `Axe_Canon_01`(EMPTY, 绕Y) → `Canon_01`(MESH) → `Fx_Tourelle1_Tir_01`(EMPTY, 炮口) |
| 命名 | 必须 `tourelle_01` / `axe_canon_01`——算子定义里写死，调用处不带参数 |

**判据（与 §3.2 同源，但放松一档）**

1. 要转的那部分**在原始网格里就是向外凸出的独立壳体**（炮管 / 雷达罩 / 机枪），不是贴面；
2. 它旋转的扫掠体**全程在机身外**——判据：轴线到机壳的最小距离 > 该部件半径；
3. **基座不切**：机匣 / 炮座往往就是蒙皮，切了必开洞。

三条都满足 → 可以做成可动炮塔；任一条不满足 → 回到 §3.2，别做。

**验证方式**：Blender 里按 18 帧扫过 ±110°、8 帧俯仰到极限，逐帧渲染看有没有扫进机身
（不要只渲静态一帧）；实机再确认炮口特效跟着炮管走。

> 与 §3.2 的分工：**§3.2 是舰船**——炮塔与船壳被体素融合成一张皮，挖洞必露底；
> **§3.3 是飞机 / 直升机**——炮管本来就是凸出件，只要不碰机匣就安全。
> 判据是同一条（"洞开在承力壳上就会露内壁"），结论不同是因为拓扑前提不同。

---

## 4. 履带与轮：可动底盘

一句话：**履带靠材质名绑 shader 滚 UV，轮子靠节点名，但"轮式车轮子要转"还得挂对推进算子**。
NDF 里没有开关能改转向细节，可**算子类型本身就是开关**（见下文「轮式车」）。

### 【原理】这条路没有 NDF 开关

三处实测，结论一致：

| 查什么 | 结果 |
|---|---|
| 全库 4368 个 ndf 搜 `Roue` / `Animator` | **零命中** |
| 搜 `Chenille` | 只命中 `TemplateCriticalEffectModules.ndf`（履带被打断的暴击模块）和 `EffetsSurUnite.ndf`，**与运动无关** |
| `DepictionOperator_Propulsion_ContinuousTrack` 的定义 | `is TCosmeticCaterpillarTrackOperatorDesc(OperatorId='Tracks' WorldFloorProxy=... FirstWheelOnGround=false LastWheelOnGround=false)`——**没有任何骨骼名 / 材质名参数** |

也就是说这两个效果**全部是引擎按模型内的名字硬编码驱动的**，NDF 侧只声明"这车是履带车"（挂这个算子）。
所以"履带不动"永远不是 NDF 的问题，改 NDF 也修不好。

### 【原理】履带 = 材质名契约

官方 `Mods/modding_manual.pdf`（§Mesh → *Specific case : continuous track material*）：

> Some vehicles need a specific material for their tracks, in order to bind a specific
> shader able to **rotate UV indices when the vehicle is moving**. In order to use this
> specific track shader, **name of material must contains either "Chenille_Gauche"
> (for left track) or "Chenille_Droite" (for right track)**.

要点三条：

1. 判定物是**材质名**，不是网格名、不是贴图名。名字只要**包含**关键字即可。
2. 左右必须各一个材质——引擎要分别处理两条履带（转向时左右速度不同）。
   一个材质给两条履带用，等于告诉引擎"这车只有一条履带"。
3. 贴图文件名不必等于材质名（官方 `Chenille_Droite` 引用的就是 `M1_Abrams_tracks.png`），
   所以拆材质时可以共用同一套 `_R/_M/_O/_NM`。

**左右怎么认**：WARNO 车头朝 +X，右手系下 **+Y 是车左、−Y 是车右**。
官方 M1 的 `Chenille_Droite` 就在 Y 负侧、`Chenille_Gauche` 在 Y 正侧。
**按实际世界 Y 判定，不要信对象名**——装配脚本很容易把两侧命名搞反（本项目就反了，
后果是前进时一侧履带往反方向滚，而且编译完全正常）。

### 【原理】履带的 UV 走向轴必须是 V

shader 只滚一个轴。哪个轴是"走向"，必须与官方一致，否则履带会**横向滑**。

判据不是看 UV 范围（走向/宽度都铺满 0..1），而是：

> 取同一 X（车长位置）上 Y 最小和最大的两个顶点，比较它们的 ΔU 与 ΔV。
> **变化大的那个轴是宽度轴**，另一个才是走向轴。

实测两个模型：

| 模型 | 宽度轴 | 走向轴 |
|---|---|---|
| 官方 `M1_Abrams` | **U** | **V** |
| 本项目 T-90A（源 GLB 直接搬来的） | V | U |

**两者正好相反。** 照搬源模型 UV 会出现"材质名改对了、履带还是乱动或不动"。
所以要么把 UV 转置、要么改贴图排布——两者必须一起改：

```
UV:     (u, v) → (v, u)                       # 转置
贴图:   转置（PIL Image.TRANSPOSE）+ 在 V 方向平铺原次数
法线图: 转置的同时 R/G 通道互换（否则光照方向错）
```

本项目履带贴图从 `2048×256（U 向平铺 4 次）` 变成 `256×2048（V 向平铺 4 次）`，
法线图做了 RG 互换。改完复测：宽度轴 U、走向轴 V，与官方一致。

### 【原理】履带要"看得见在滚"，还差两个前提：贴图有花纹 + UV 连续

材质名和 UV 轴向只是**让 shader 绑上**，滚动本身是**贴图在 V 上平移**。所以：

| 前提 | 不满足会怎样 | 怎么查 |
|---|---|---|
| 履带贴图**有花纹**（不是纯色） | shader 照滚，但每一帧颜色一样 → **肉眼完全看不出在动** | 数贴图颜色数：`len(Image.getcolors())==1` 就是纯色 |
| 履带网格的 UV **沿走向连续** | UV 全 0 → 所有顶点采同一个像素，滚了等于没滚 | 抽一个履带壳看 `uv` 是否全 `(0,0)` |

**本项目实测（M752 Lance）**：履带是 **462 个独立链节壳**（每节 24 顶点 12 三角），
三张履带贴图 `M752_tread1/2/3_D.png` 都是 **32×32 纯色**（各只有 1 种颜色），UV 全是 `(0,0)`。
这种模型**改材质名也没用**——滚的是 UV，不是几何。要让履带看起来在动，必须：

1. 贴图换成**带横向花纹**的履带条（能平铺，V 方向周期 = 链节间距）；
2. 给每个链节按「沿履带环的弧长」写 UV：`V = s / L × 重复数`，`U = 横向 0..1`；
   链节是独立壳也不怕——只要 V 是沿环连续的，平移 V 时花纹就会一节一节往前挪。

**只有轮子在转、履带是纯色**时，实机看起来仍然是"底盘一动不动"。
先确认贴图有没有花纹，再决定这条要不要做。

### 【原理】轮子 = 独立节点 + 原点在轮心（名字由引擎拼）

引擎不是"扫描名字里带 roue 的对象"，而是**用格式串拼名字**再去找节点。
`WARNO.exe` 里能直接捞出这一组（ASCII，格式化模板，`%1` = 序号）：

```
roue_%1        roue_0%1
roue_d%1       roue_g%1
roue_elev_d%1  roue_elev_g%1
roue_gauche_0%1   roue_droite_0%1      （带 _depr 后缀的两条是废弃旧名）
```

含义：`%1` 从 1 开始试，直到找不到为止。所以 **`roue_d1` / `roue_g1` … `roue_dN` 就是对的写法**，
`Roue_Gauche_01`（官方轮式样例）走的是 `roue_gauche_0%1` 那条。**不分大小写**（FBX 里是小写也能命中）。

官方 M1 的每个轮子是三件套，**缺一不可**（`Roue_Elev_D1` 为例）：

```
Chassis (Mesh)
 ├─ Roue_Elev_D1 (EMPTY，位置 = 轮心)      ← 引擎按这个名字找轮子并旋转它
 │   └─ Roue_D1 (MESH，本地原点 = 0,0,0)   ← 轮子网格
 └─ Armature_D1 (ARMATURE，骨骼 Roue_Elev_D1)  ← 只用于给履带蒙皮
```

- **最常漏的一条：网格必须是空物体的子节点**（官方两种车型都是这个结构）。
`Roue_Elev_D1`(EMPTY, 轮心) 下面挂 `Roue_D1`(MESH)，`matrix_parent_inverse = Identity`、局部 `location=(0,0,0)`。
把两者都挂在 `Chassis` 下当**兄弟**，本项目实测就是"轮子不转"——引擎转的是空物体这一层，
网格不跟着走，而且**编译、加载全都不报错**（BMPT-787 实测：16 个轮子全是兄弟，改父子后立刻转）。
> 引擎两侧的名字都会去找（`roue_elev_d%1` 与 `roue_d%1`），所以"兄弟"结构理论上网格自己也会被转到——
> 但前提是**网格原点就在轮心**；BMPT 那批网格原点是 0,0,0（车身原点附近），兄弟关系下转起来是**绕车身飞**，
> 改父子之后由空物体带着走才正常。**结论不变：空物体在轮心 + 网格做子节点 + 网格 local 0。**

**命名**：`Roue_Elev_{D|G}{n}`。`D`=右侧（Y 负）、`G`=左侧（Y 正）；
  `1` 是最前一个轮（诱导轮），`n` 递增到最后一个（主动轮）。M1 是 1..9（7 个负重轮 + 前后），
  T-90 是 1..8（6 个负重轮 + 前后）。**编号连续即可，数量不固定。**
- **轮心 = 空物体位置 = 网格局部原点**。M1 的 `Roue_xx` local 就是 `(0,0,0)`。
  原点若留在世界原点，引擎一旋轮子就飞出去。
- **骨骼不是必须的**：骨骼只承担"履带随轮子上下起伏"的形变，M1 里那片履带蒙皮到
  `Roue_Elev_*` 顶点组就是为了这个。纯刚性履带可以不加。

### 【原理】⭐ 轮式车：轮子转不转，由**推进算子**决定，不是只有模型层

这条是后来修圆点 9K79（轮式 6×6 TEL）时补的，之前那句"轮式车没有轮子节点、旋转只对履带实现"是**错的**：

| 底盘 | depiction 里的推进算子 | 轮子节点（官方样例实测） |
|---|---|---|
| 履带 | `DepictionOperator_Propulsion_ContinuousTrack`（`TCosmeticCaterpillarTrackOperatorDesc`） | `Roue_Elev_D1`(Null，轮心) → `Roue_D1`(Mesh，local 0) |
| **轮式** | **`DepictionOperator_Propulsion_Wheels_Generic`**（`TCosmeticWheelsOperatorDesc`） | `Roue_Gauche_01` / `Roue_Droite_01` / `Roue_02`——**直接是 Mesh**，原点在轮心，**不需要空物体** |

官方 `ExampleAssets/Meshes/GAZ_66B.fbx`（轮式卡车）就是第二种：三个轮子网格挂在**根层**（`Chassis` 的兄弟），
原点 (1.762, ±0.981, 0.520) 正是轮心，`Roue_02` 把后桥两个轮子装在**一个**网格里（同轴，绕自己的 Y 转就同时对）。

`TCosmeticWheelsOperatorDesc` 的三个开关（`DepictionOperators.ndf`）：

```ndf
DepictionOperator_Propulsion_Wheels_Generic   is TCosmeticWheelsOperatorDesc( OperatorId='Wheels' RotateDirection=true  MoveFromSuspension=true )
DepictionOperator_Propulsion_Wheels_Canon     is TCosmeticWheelsOperatorDesc( OperatorId='Wheels' RotateDirection=false MoveFromSuspension=false )
DepictionOperator_Propulsion_Wheels_TowedCanon is TCosmeticWheelsOperatorDesc( OperatorId='Wheels' RotateDirection=false MoveFromSuspension=false ReverseRotation=true )
```

`RotateDirection` = 转向时左右差速（牵引炮要关掉，注释原文：*les roues ne tournent pas lors des virages*）；
`MoveFromSuspension` = 轮子按悬挂上下跳。**普通车辆一律用 `_Generic`。**

**踩过的坑（圆点 9K79）**：模型层全对（`roue_elev_d1..3` 空物体在轮心 + `roue_d1..3` 网格做子节点），
但 depiction 是从履带克隆源（M752 / M113 底盘）抄来的，挂着 `Propulsion_ContinuousTrack` ——
**履带算子不驱动轮式轮子**，实机就是"轮子纹丝不动"，而编译、加载、其它一切正常。
改两行就好：

```ndf
DepictionOperator_Propulsion_Wheels_Generic,     // 原来是 Propulsion_ContinuousTrack
...
+ DepictionAction_MovementFX_Wheeled             // 原来是 DepictionAction_MovementFX_Tracked
```

> 判据（省一轮）：**"某个部件不动"先看它归哪个算子管**。模型命名对了，还要有算子来驱动它。
> 履带算子管履带（材质 `Chenille_*` 滚 UV）+ 轮子升降；轮式得挂 `Wheels` 算子。

### 【操作】从已合并的模型里拆轮

难点不在拆分，在**判定**。T-90A 的 16 个轮子全是独立封闭壳体，可以干净拆出；
但用错判据会把侧裙板切碎。

```python
# 按「连通壳体」整体判定，绝不要按面中心分配——
# 侧裙板这种跨数米的大面板，面中心会落进轮子区间，按面分会把整块裙板当轮子。
for 每个壳体:
    c = 包围盒中心; s = 尺寸
    if c.z <= 1.20 and 0.95 <= abs(c.y) <= 1.85 \
       and 0.40 <= max(s.x, s.z) <= 1.10 and s.y <= 0.60 \
       and abs(s.x - s.z) <= 0.30 * max(s.x, s.z):
        归属到 X 区间对应的轮号
```

阈值来自实测：T-90A 负重轮是 `0.78 × 0.44 × 0.78`（直径 0.78、宽 0.44）、各 68 顶点；
诱导轮/主动轮是多片壳体（2 片 / 5 片），按 X 区间合并成一个轮子；
`|y| ≈ 1.97` 的挡泥板靠 `YMAX=1.85` 排除。

**拆完必须做两件事**：

1. **单次遍历**把面分进轮子，然后在同一份 bmesh 上删面。
   分两次遍历（先记索引再删）会导致面索引漂移，轮子里混进别的东西。
2. **继承 `use_smooth`**：`newface.use_smooth = oldface.smooth`。
   丢掉它会变成全平面着色 → FBX 导出按面拆顶点 → **顶破 AssetCooker 的 65536 上限**。
   本项目实测：16 个轮子 smooth 从 100% 正确变 0%，顶点计数 66465（超限 929）；
   继承后回落，一次编译通过。

### 【验收】

1. `fbx_anchors.py dump` / 导入 Blender 复核：16 个 `Roue_Elev_*` 空物体在轮心、
   16 个 `Roue_*` 网格 local 全为 `(0,0,0)`。
2. 把轮子绕 Y 轴转 45° 再渲染：**位置不动、只在原地转**（轮心对）。
   负重轮有轮毂辐条，转动肉眼可辨；纯光滑圆盘转了也看不出来，别用"看不出来"当失败。
3. 履带 UV 复测宽度轴 = U、走向轴 = V。
4. 编译必须 `Mod Generation Success`；顶点超限的报错长这样：
   `Vertex count 66465 above limit of 65536`。
5. 进游戏：开车看履带是否朝正确方向滚（倒车应该反着滚）、轮子是否转、转向时左右是否差速。

### 【状态】

- **履带材质名 → 绑定滚动 shader**：官方手册明写，属**已验证的引擎契约**。
  ⚠ 但"绑上了"≠"看得见"：贴图纯色 / UV 全 0 时滚动不可见（见上文两个前提）。
- **轮子按 `Roue_Elev_*` 旋转**：✅ **T-90A 实机验收通过**（开着走时轮子在转）。
  结论：引擎读的是**空物体**，不需要 `Armature` / 骨骼蒙皮也能转；
  前提仍是那两条硬契约——轮子是独立网格、同名空物体在轮心、网格局部原点为 0。
  （此前担心的"要补骨骼"可以划掉。）
- **轮式车必须挂 `Propulsion_Wheels_Generic`**：✅ 圆点 9K79 修复（`Propulsion_ContinuousTrack`
  → `Propulsion_Wheels_Generic` + `MovementFX_Wheeled`）。模型层本来就合规，错的是算子。
- **M752 Lance 拆轮**：14 只轮子（7 只/侧：前主动轮 r 0.385、5 只负重轮 r 0.31、后诱导轮 r 0.315）
  从 `Chassis` 按整壳拆出，轮心空物体 + 网格子节点，已编译通过（待实机确认转动）。
  ⚠ **别只按轮子材质找**：车尾两只诱导轮只用了 `M752_dark`，按 `M752_wheel` 材质筛会漏掉两只，
  判据要用「材质 ∪ 圆盘几何」（厚 < 0.32、直径 0.5–0.85、x/z 尺寸差 < 5%、|y| > 0.9）。
  履带因贴图纯色未做 UV 滚动。

---

## 5. 起落架 / 舱门 / 整流罩：CoatingRecipe

```ndf
// 1) Pantry：配件（对节点做程序化动画）
Ka58_SOV_landing_gears_coating_ingredient is TCoatingIngredientOperator
(
    Descriptor = TCosmeticLandingGearOperatorDesc
    (
        AnimationList = [ TBoneProceduralAnimation(...) ]
    )
)

// 2) Cookbook：配方（把配件绑到涂层名上）
unnamed TCoatingRecipe
(
    Cookbook = $/DepictionCore/CoatingCookbook
    CoatingName = 'Ka58_SOV'          ← 必须 == depiction 的 BlackHoleKey
    Ingredients = [ Ka58_SOV_landing_gears_coating_ingredient, ]
)
```

`CoatingName` 必须逐字等于 depiction 的 `BlackHoleKey`（全库 44 条配方都是这么对的，`Puma_Orchidee_FR` 亦然）。
写错不报错，只是"不动"。

### 【字段】

| 字段 | 含义 |
|---|---|
| `BoneName` | 网格节点名，**不分大小写**（`Roue_Gauche` ← `roue_gauche`） |
| `Axis` | 0=X / 1=Y / 2=Z。全库只有这三个值（0 有 12 处、1 有 258、2 有 267），**没有斜轴** |
| `LimitValue` | 角度（度）；`IsTranslation` 时是位移（米） |
| `Delay` / `Duration` | 延迟多久开始 / 用多久做完（秒） |
| `IsTranslation` | 改成平移而不是旋转 |

同一根骨头**可以有多条动画**（官方 Mi-24V 的 `roue_gauche` 就同时有平移和旋转两条），
所以"先转再挪"是可以做到的。

### 【坑一】引擎绕 X 的旋转方向与 Blender 相反

实测两次（同一个部件，正负各写一版）：

| 写法 | Blender 预演 | 实机 |
|---|---|---|
| `roue_gauche = +150` | 向外翻 | **向内收 ✓** |
| `roue_gauche = −150` | 向内收 | 向外翻、穿过座舱 ✗ |

**纪律**：在 Blender 里预演姿态时用「引擎值取反」；写回 ndf 前再翻回来。
不要用 Blender 的 `rotation_euler` 直接定符号——两者不是同一套坐标系。

### 【坑二】角度/位移不是越大越好，要"刚好藏住"

| 部件 | 定稿 | 为什么是这个值 |
|---|---|---|
| 主轮 | 绕 X **120°** | 轮盘 ⌀0.64，转得越多 Y 向投影越宽：120° 时 0.63 m（落进机腹），150° 时 1.26 m（顶穿座舱侧壁） |
| 尾轮组 | 沿 Z **+0.55 m** | 尾梁内空只有 z 0.80..1.83，旋转会扫出轮廓；平移正好缩进去 |
| 整流罩面板 | 绕 X **60°** | 50° 开口即闭合；再大开始翻进机体、露出背后凹兜（100° 最明显）。60° 是上限 |

取值的通用做法：**先用「逐顶点内外判定」扫一遍角度**（把部件顶点变换后逐点算它在机壳内还是外），
再看剩余的"外露最大距离"；数值给不出结论的（比如"贴不贴"），必须渲染看。

### 【验收】

1. `Mod Generation Success`，且 `Gen/NDF/GFX/Depiction.ndfbin` 的 **mtime** 变新（体积变化不能当证据）。
2. **带材质**渲染至少三个机位：正视（看开口）、斜前、斜下后（看有没有露内腔、翘边、穿模）。
3. 进游戏：起飞后延迟 2 s 开始、1.5 s 收完；落地后自动放回。

⚠ 单色 Workbench 分不清"背面发黑"和"真空腔"，判形态一律用带材质渲染。本项目的"看起来像开了个洞"
就是因为用 Workbench 单色看的（见 §1 末尾那条）。

> **工具**：`scripts/pose_render.py`（`poses.json` + `views.json`）批量出"多姿态 × 多机位"带材质图，
> 注意它写的是 **Blender 侧角度**（= 引擎值取反）。

---

## 6. 旋翼：桨叶、桨毂、轴筒要一起转

**命名契约**（由 `21-depiction.md §3b` 的 `DepictionOperator_Rotors` 内联 `THelix` 引用，加载时硬校验）：

| 节点 | 内容 |
|---|---|
| `Helice_LS_N` | 桨叶（N=1 上旋翼、2 下旋翼） |
| `Bloc_Moteur_N` | 桨毂罩 + 轴筒（**必须是独立网格**，烘焙在 `Chassis` 里的部分不会转） |

三条要点：

1. **轴筒必须并入旋转节点。** 只把桨叶给 `Helice_*` 是最常见的漏项——转起来只有桨在动、中间那截轴纹丝不动，
   一眼假。做法见 §1：按整壳把桨毂罩与轴筒从 `Chassis` 里拆出来，父级挂 `Bloc_Moteur_N`。
2. **枢轴不能抄骨骼**：见 §2，实测偏 0.83 m 时桨盘会在机身上画圈。
3. **静止姿态必须与改前逐位一致**：顶点按 `P − HUB` 中心化、节点再放到 `HUB`，导出前后包围盒不变。

> 共轴双旋翼（Ka 系）要给两个独立的 `Bloc_Moteur_1/2`，`THelix` 里分别给正反转速；
> 单旋翼机尾桨同理，节点名照官方样例抄。

### 6.1 【硬限制】一个旋翼算子最多 3 副 —— 四旋翼必须拆两个算子

四旋翼（多旋翼无人机）照常写成一个 `DepictionOperator_Rotors` 里 4 个 `THelix`，**编译期必炸**：

```
Fatal error
Can't load 'Glad:/NDF/GFX/Depiction.ndfbin':
Invalid property in object 'TCosmeticRotorOperatorDesc name = Rotors':
On limite a 3 rotors pour raisons de performances, demandez plus pour obtenir plus.
```

这不是拼写问题，是引擎的**性能上限 3 副**。`Depiction.ndfbin` 整包加载失败 ⇒ 所有飞机/直升机一起坏。

**解法（实机验收通过）**：拆成两个算子，给**不同的 `OperatorId`**，并且**必须用 `TCosmeticRotorOperatorDesc`**
（直升机旋翼）。只拆不给 Id 没用——两个算子会按 `OperatorId = 'Rotors'` 合并成一个对象，总数仍是 4，
报同样的错（本项目连踩两次）。

```ndf
            // 第 1 组：OperatorId 显式写，才能与第 2 组区分开
            TCosmeticRotorOperatorDesc
            (
                OperatorId = 'Rotors'
                DecelerationAfterDeath = 2.0
                ForceRotorBladeBlur = $/Camera/ForceRotorBladeBlur
                HelixList = [ THelix(…bloc_moteur_1…), THelix(…bloc_moteur_2…) ]
            ),
            // 第 2 组：换个 Id
            TCosmeticRotorOperatorDesc
            (
                OperatorId = 'Rotors2'
                DecelerationAfterDeath = 2.0
                ForceRotorBladeBlur = $/Camera/ForceRotorBladeBlur
                HelixList = [ THelix(…bloc_moteur_3…), THelix(…bloc_moteur_4…) ]
            ),
```

**⚠ 算子类不能乱换（本项目踩过）**：`DepictionOperator_Rotors` 的底层是
`TCosmeticRotorOperatorDesc`，它吃直升机的**旋翼状态**（起降/悬停/落地停车调速）。
另有一个 `TCosmeticAirCushionRotorOperatorDesc`（气垫船抬升风扇，原版只用于 `Kalmar_supply_SOV`），
它**活着就一直转、落地不停**。一开始为了绕上限顺手换成了它，结果飞机落地后四副桨照转，
实机一眼假。**绕上限要改的是 `OperatorId`，不是算子类。**

四条配套细节：

- **用类名而不是 `DepictionOperator_Rotors` 模板**：`OperatorId` 是该类的字段，直接写类名最稳；
  模板里 `OperatorId` 已硬编码为 `'Rotors'`，改不动。
- `DecelerationAfterDeath = 2.0` 与 `ForceRotorBladeBlur = $/Camera/ForceRotorBladeBlur`
  都是原版模板自带的，别省（前者是残骸减速，后者强制桨叶动态模糊）。
- `Actions` 侧仍是四条独立的 `Template_DepictionAction_Rotor(... SousMobile = "bloc_moteur_N")`，
  与新算子的 Id 无关；`PaleLength ≈ 桨叶长度(mm) × 0.23~0.28`
  （Mi-2 7.3 m 桨→1700、Ka-58→1800、Pero 小桨→70）。0.35 m 桨取 **90**。
- **3 副上限按 `OperatorId` 分组计数，与算子类无关**：拆成 `Rotors` / `Rotors2` 后，
  每组 2 副，用真正的旋翼类照样通过编译与加载。

> 旋转轴：`THelix.RotationAxis = 2` 是绕 Z（垂直），四旋翼四副都用 2；
> 顺逆交替只为好看，对角同向即可（`Clockwise = False/True/False/True`）。



---

## 7. 挂点与发射口：算子类型决定读不读 Anchors

> **本节只讲飞机 / 直升机那套 `as_N_M` 挂点组。** 地面导弹发射车（发射架 / 发射箱挂弹）
> 不用挂点组，走 `MissileCarriage` + `Tourelle{N}_MissileCount`，
> 「导弹从哪个方向出管」也在那边 —— 见 `26-ground-missile-tel.md §3 / §4`。

> ⭐ **先分清两件事：算子决定「锚点读不读」，用户决定「锚点放哪」。**
> 「炮口 / 挂点具体在机体哪个位置」属于**只有用户知道**的领域事实，**动手前先问**：
> 渲同角度图 → 叠 A–T/1–16 网格 → 让用户报格子 → 反算 → **红球复核**。流程见 `23-mesh-import.md §5.0`。
> 本项目曾连错三轮（找错舷、把加油探头当炮口），一次都没在烘焙前把候选区域摊给用户看。

| 概念 | 语义 | 坑 |
|---|---|---|
| `Anchors` | 一次射击从哪几个节点发出，**是数组** | 多元素 = 多点齐射，不是多发弹 |
| `NbProj` | `InstantFire` 下「每次触发出几发/几处」 | 「一对齐射」= 双锚点 + `NbProj=2`（官方 BTR-50 MRF），不必改炮塔结构；**两处同时喷火不要求 `ContinuousFire`** |
| `FireEffectTag` | 关联主描绘 `Actions = MAP[("weapon_effet_tagN", Weapon_X)]` | tag 没注册 = 有枪无火 |
| 算子类型 | **决定读不读 `Anchors`** | 见下 |

**算子类型是最阴的坑**：`DepictionOperator_WeaponMissileCarriageFire` 从**导弹挂架**发射，
发射点由 `Connoisseur = MissileCarriage_<源>` 决定，**根本不读 `Anchors`**。
所以挂在这个算子下的武器，锚点怎么改都不会从炮口出来。
要按炮口走，必须换成 `DepictionOperator_WeaponInstantFire`。

> 实测：napalm 原本走 `MissileCarriageFire`，改锚点毫无反应；换 `InstantFire` 后立刻生效。

**多武器共用一个炮口**是允许的（本项目精准与 380 共用单管炮），此时两者在游戏里互斥可选。

### 7.1 挂点组：组号必须从 1 起连号，层级必须走炮塔链

**【原理】引擎在加载时按 `MissileCarriage.WeaponInfos` 逐条找挂点组**

官方定义（`modding_manual.pdf` p15「Specific case : missiles and bombs attachment locations」）：

- `AS_{N}_{M}` = 空对空 **或** 空对地武器的挂点
- `AA_{N}_{M}` = 仅空对空武器的挂点
- `{N}` = **武器序号**（第几种武器，从 1 起），`{M}` = 该武器下的挂点序号（从 1 起）

三条硬约束，按踩坑顺序：

1. **`{N}` 必须 1,2,3… 连号**。引擎按序号逐个找组，**缺 1 就整轮作废**，而报错却是
   「model has 0 ... groups combined」—— 名字明明在 neu3 里，看起来像"一个都没认出来"。
   本项目 MiG-29M 连崩三轮的**真因**就是组号写成了 2、3（照抄 NDF 的 `WeaponIndex`）。
2. **`{N}` 与 NDF 的 `WeaponIndex` 无关**，只与 `WeaponInfos` 里的**顺序**对应，
   而且**是倒序**：最后一条 → 组 1，倒数第二条 → 组 2……（见下条实测证据）。
3. **前缀用 `AS_` 就够了，`AA_` 不是必需的**。手册明写 AS 兼容空对空；已验真的
   Ka-58 全部用 `as_`（含挂 eAAM 的组），零 `aa_` 组也照跑。别为"语义正确"去拆前缀。

**倒序绑定的两条独立实测证据**（照正序写会导致"两种弹的位置互换"，且**不会报错**）：

| 样本 | `WeaponInfos` 顺序 | 模型节点 | 结论 |
|---|---|---|---|
| Ka-58（已验真） | 12 发 eAGM → 4 发 eAAM | `as_1_*` 仅 4 个、`as_2_*` 有 12 个 | 12 发那条绑的是**组 2** |
| MiG-29M（本项目） | Kh-29(4) → R-77(4) | 组 1 在内侧、组 2 在外侧 | 进游戏后 R-77 在内、Kh-29 在外 → Kh-29 绑的是**组 2** |

所以写法是槽号 → 组号取**倒序**，例如两条弹时 `GROUP = {2: 2, 3: 1}`。
两侧弹数相同时这个错误**完全静默**（不报错、不崩溃），只能靠"谁在内谁在外"发现。
若发现位置对不上、又没有报错，优先怀疑这一条，而不是模型位置。

- **挂点必须是 `Tourelle_0N → Axe_Canon_0N → Canon_0N` 最内层 `Canon_0N` 的子节点**。
  直接挂 `Chassis` 下 → 引擎只当普通子部件，计 0 组。
  `Tourelle_0N` 的 N **不必**等于组号：Ka-58 的 `as_1_*` 挂在 `canon_03` 下，实机正常。
- 大小写**无所谓**：AssetCooker 会把节点名统一小写（`AS_1_1` → `as_1_1`），
  能跑的 Ka-58 在 neu3 里同样是 `as_1_1`。所以别在大小写上找 bug。
- 报错原文（区分两种，`%2` 恒为"识别到的组总数"）：

  ```
  # 总数不够（本项目的三轮 CTD 都是这一条）
  Not enough hardpoint groups : missile system needs 2 hardpoint groups,
  model has 0 'as' and 'aa' hardpoint groups combined.

  # 只缺对地那一类（模型只有 AA_ 组，拿来挂 Kh-29 这类 eAGM 时才会出现）
  Not enough air-to-ground hardpoint groups : missile system needs 1 'as'
  hardpoint groups, model has 0 'as' hardpoint groups.
  ```

> **被推翻的旧结论**（写在这里是因为错因比答案更值钱）：
> ① 「前缀由 `MissileType` 决定，eAGM 用 AS、eAAM 用 AA」——手册里 AS 本就覆盖空对空，
>    Ka-58 也与该说法矛盾；当年把 `AA_3_*` 改 `AS_3_*` 后报错变样，被误读成"拆前缀导致缺 aa"，
>    实际只是组号仍是 2、3，`has` 一直是 0。
> ② 「Tourelle_01 必须存在且连号，否则枚举中断」——连号规则确实存在，但作用在**挂点组**上，
>    不是炮塔号上（补了 `Tourelle_01` 后依旧 0 组）。

**【操作】Blender 里建锚点时的固定写法**

```python
def weapon_node_chain(n):          # n = 炮塔号，只为给 fx 锚点找个家，与组号无关
    t = add_empty("Tourelle_0%d" % n, (0, 0, 0))
    a = add_empty("Axe_Canon_0%d" % n, (0, 0, 0), t)
    return add_empty("Canon_0%d" % n, (0, 0, 0), a)     # 返回最内层，挂点挂它下面

GROUP = {2: 2, 3: 1}               # 槽号 → 挂点组号（倒序！见上）
# 组名： "AS_%d_%d" % (GROUP[weapon_index], m)
```

**【验收】不看 FBX，看烘焙产物**（FBX 结构对 ≠ 引擎认；`GenerateMod.bat` 永远 rc=0）

```python
# 解 <mod>/Gen/PC/Mesh/.../<Model>/mesh.neu3，从 offset 44 起 zstd 解压
# NodeNames 区里应出现完整层级序，且组号从 1 连号：
#   chassis → tourelle_01 → axe_canon_01 → canon_01 → fx_tourelle1_tir_01
#           → tourelle_02 → axe_canon_02 → canon_02 → as_?(倒序映射的组)
#           → tourelle_03 → axe_canon_03 → canon_03 → as_?(另一组)
```

### 7.2 挂点高度：位移循环只能加在「直接挂 Chassis」的节点上

**【原理】空物体是父子链，子节点继承父节点位移**

给一个挂在 `Canon_0N` 下的 `AS_*` 加 `z += 1.971`，它同时还会吃到
`Tourelle → Axe_Canon → Canon` 三层的位移。若"整机抬升"那段代码对**所有** EMPTY
无条件加一次，位移就按层数累加：`Tourelle` +1 层、`Axe_Canon` +2 层、`Canon` +3 层、
`AS_*` +4 层。本项目实测 `AS_1_1` 落在 z=7.585，而翼下表面只有 1.897 ——
**导弹整体浮在翼面上方 5.6 m**（进游戏不报错，只是穿帮）。

**【操作】**

```python
GROUND_Z = 1.971
chassis.data.transform(Matrix.Translation((0, 0, GROUND_Z)))
for e in bpy.data.objects:
    if e.type == 'EMPTY' and e.parent is chassis:   # ← 只抬直接子节点
        e.location.z += GROUND_Z
```

**【验收】节点与机体表面的距离**（不要只看有节点、名字对）

```python
# 对每个 AS_* 量它同 (x,y) 半径 0.35 m 内机体顶点的 z 区间
# 期望：节点 z ≈ 挂轨底面 z_min − 0.015（就贴在挂梁下面，见 §7.3）
# 若节点比表面高十几厘米以上 → 位移被重复累加
```

### 7.3 别减弹体半径：引擎把节点当「挂点」，不是弹心

**【原理】静态弹的模型原点在弹体上表面，不在轴线上**

第一版为了让弹「挂在挂梁正下方」，把节点压到 `挂轨底面 − 0.02 − 弹体半径`
（Kh-29 0.19 / R-77 0.10）。进游戏后 8 发弹**位置、内外顺序全对，但每一发都在
挂梁下面悬空 0.2 m** —— 空档高度恰好等于减掉的那个半径。这反过来说明：引擎把
**节点当成挂点**（弹的原点），弹体整体挂在节点**下面**，节点只要贴住挂梁底面即可。

**【操作】**

```python
Z_CLEAR = 0.015                       # 挂轨底面 − 1.5 cm，弹顶正好贴住
z = zmin - Z_CLEAR                    # 不要减弹径！
```

**【判据】看空档高度而不是看"有没有对上"**

| 现象 | 含义 | 改法 |
|---|---|---|
| 弹整体比挂梁低一个弹径左右 | 减了弹体半径 | 去掉半径项 |
| 弹陷进挂梁/机翼 | 原点在弹心，抬头了 | 加回半径的一半～全部 |
| 弹与挂梁完全贴合 | 正确 | — |

**顺带**：`PylonSet = DepictionPylonSet_Airplane_SOV` 会被引擎逐挂点实例化
`ModelPylon1..7`，与模型自带的挂梁几何**叠着画**。若弹贴住挂梁后看到挂梁发粗/重影，
那是引擎挂架，不是模型问题 —— 想干净就删掉模型里的挂梁件，让引擎挂架独占。

**验收还要对一遍 `PhysicalProperty`**：静态导弹的 `PhysicalProperty = "Tourelle{WeaponIndex}_MissileCount"`
里那个数字是 **WeaponIndex**，不是组号（官方 MiG-29S：`WeaponIndex=2/3` ↔ `Tourelle2/3_MissileCount`）。
组号与它不一致是**正常且必须的**，别"顺手统一"。


---

## 8. 验收（可动件专用）

按顺序，别跳：

- [ ] 拆出的件是**整壳**（焊接后按连通块），没有半截壳飘着
- [ ] 隐藏该件后机身**无洞**（红底 + 背面剔除判据，见 §1）
- [ ] 枢轴从几何求；导出前后所有网格包围盒**逐位一致**（见 §2）
- [ ] 动作量有数值依据（逐顶点内外判定扫角度；"贴不贴"必须渲染看）
- [ ] **带材质**渲染至少三个机位：正视 / 斜前 / 斜下后，无露腔、无翘边、无穿模（见 §5 末尾）
- [ ] 走 CoatingRecipe 的：`CoatingName` == depiction `BlackHoleKey`，且**已重新编译**
      （判据是 `Gen/NDF/GFX/Depiction.ndfbin` 的 **mtime**，不是体积）
- [ ] 进游戏：动作**方向**对、时序对（Delay/Duration）、落地能复位

