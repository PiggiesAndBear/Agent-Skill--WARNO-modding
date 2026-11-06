# 资产管线：FBX 导出、材质贴图、减面与预算

**本文件管**：模型"做完之后、进引擎之前"的工序——导出参数、PBR 通道、补几何、减面、atlas 预算、新增小 FBX 的门槛。
**不管**：拆件 / 枢轴 / 动画（`24-rig-parts.md`）、锚点契约与导入流程（`23-mesh-import.md`）。

## 目录

| 节 | 管什么 | 什么时候读 |
|---|---|---|
| §0 | 导出定稿参数 | 每次导出都看 |
| §1 | glTF/GLB 四道清洗 | 素材不是 FBX 而是 glTF 时 |
| §2 | PBR 通道接材质 | 表面发油、发亮、像镀铬 |
| §3 | 在成品 FBX 上补几何 | 只想加几个零件、不想重跑烘焙 |
| §4 | 删不可见面减面 | 面数超标、内腔封闭 |
| §5 | atlas 像素预算 | 多套贴图要合并 |
| §6 | 新增小 FBX 的门槛 | 想让引擎画/不画某个小物件 |

## 0.0 【四条】AssetCooker 卡人的命名/数值规矩（本项目实测，各踩一次）

| 现象（AssetCooker 原文） | 真因 | 修法 |
|---|---|---|
| `Texture slot 'DiffuseTextureNoAlpha' from material 'FPV_DRONE_A' violates naming convention: "FPV_DRONE_A.png" does not match '^.*_(A\|NM\|O\|M\|R\|P\|ORS)$'` | **材质名以 `_A` 结尾**，被当成 alpha 贴图后缀 | 材质名换掉尾缀（本项目改成 `FPV_DRONE_BODY`） |
| `Trying to combine textures with different resolutions: 'X_R.png' and 'X_M.png'` | 同一套贴图**分辨率不一致**（主图 2048、补的平坦图 1024） | 同一材质名下 base/_NM/_R/_M/_O **全部同分辨率**；补的平坦图按主图尺寸生成 |
| `Can't quantize texcoords because UVs are not in the range [-4, 4]: UV=(3.91, 4.07)` | **FBX 导出会翻转 V**（写 1−v），只按源 UV 平移救不了 | 判据改成 `max(|u|,|v|,|1−u|,|1−v|) ≤ 3.9`；超了就整体乘 0.5（贴图是 seamless 的，平铺密度变了也不出缝） |
| `Mesh contains an abnormal normal: sub-mesh 'Chassis', position = (…), normal length 0` | 源模型有**零面积三角**，法线 (0,0,0) | 导出前统一 `quads_convert_to_tris` → `dissolve_degenerate(1e-5)` → `delete_loose` → `normals_make_consistent` |

四条都属于"编译期明确报错"，比缺骨骼那类静默失败好查；**报错里的文件名就是真因**，别去 NDF 里找。

## 0. FBX 导出定稿参数

```python
bpy.ops.export_scene.fbx(
    filepath=fbx_out,
    use_selection=True,
    use_custom_props=True,
    apply_scale_options='FBX_SCALE_ALL',
    axis_forward='Y',
    axis_up='Z',
    use_mesh_modifiers=True,
    mesh_smooth_type='FACE',
    use_triangles=True,
    add_leaf_bones=False,
    bake_anim=False,
    object_types={'EMPTY', 'MESH'},
)
```

要点：**必须三角化**（`use_triangles`）、**不许生成叶骨**（`add_leaf_bones=False`，
多出来的 `_end` 节点会污染名字空间）、**必须带上 EMPTY**（锚点就是空物体）。

---

## 1. 素材来自 glTF / GLB：导出前的四道清洗

`use_triangles=True` 只保证**导出时**输出三角面，它救不了法线和 UV。GLB 来源的
模型会在 AssetCooker 阶段连续报四类 fatal，全部要在**导出前**改数据结构解决。

> 实测样本：T-90A（War Thunder 导出 GLB，22 个 `Object_NN`）→ ShowCase-FPV Strike。

**① 真三角化 + 清退化面（否则 `normal length 0`）**

`mesh_smooth_type='FACE'` 写的是**导出前那个多边形的面法线**，不是三角化之后的面
法线。GLB 带进来的 n-gon 里混着三点共线的退化面，其面法线算出来是 (0,0,0)，逐角
写进 `LayerElementNormal` 就成了零法线：

```
Fatal: Mesh contains an abnormal normal: sub-mesh 'Axe_Canon_02',
       position = (0.479347,-0.6609,2.5981), normal length 0
```

```python
active(obj)
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.quads_convert_to_tris(quad_method='BEAUTY', ngon_method='BEAUTY')
bpy.ops.mesh.dissolve_degenerate(threshold=1e-4)   # 三角化之后才算得出退化
bpy.ops.mesh.delete_loose()
bpy.ops.mesh.normals_make_consistent(inside=False)
bpy.ops.object.mode_set(mode='OBJECT')
obj.data.validate(verbose=False)
```

> **查不出来是正常的**：Blender 的 FBX 导入器会重算法线，任何 (0,0,0) 都会被面法线
> 覆盖。所以「导入回来检查 `corner_normals` / `bm.verts[].normal`」这条路从原理上
> 就发现不了问题，只有 `calc_loop_triangles()` 逐三角形算 `cross(b-a, c-a)` 才对得上。

**② 删掉多余的 UV 层（否则 `Can't quantize texcoords`）**

GLB 常带 4 套 UV（`UVMap` + `UVMap.001~003`），装箱/压缩只处理 active 那一套，
其余仍是原始 tiling。AssetCooker 对**每一套**都要求落在范围内。WARNO 只用一套。

```python
while len(obj.data.uv_layers) > 1:
    obj.data.uv_layers.remove(obj.data.uv_layers[-1])
obj.data.uv_layers.active = obj.data.uv_layers[0]
```

**③ UV 归一化到 [0,1]，不要靠 UV 平铺表达重复**

实测官方 `M1_Abrams.blend` 的 41 个网格，**所有 UV 严格落在 [0.000, 0.999]**，
履带也不例外（`Chenille_Droite` U 0.002–0.989）。WARNO 的重复是靠把图案在贴图里
多排几次实现的，不是靠 UV 超出 1。

glTF 恰好相反：T-90A 履带的 V 跨 8.7487，即贴图重复 8.75 次。照搬会撞 UV 上限。
正确改法是「归一化 UV + 条带贴图」，**总周期数不变，视觉零损失**：

```python
TILE_V = 8                       # 条带贴图的重复次数
uv[0] = uv[0] - u_min                       # U 平移到 0 起
uv[1] = (uv[1] - v_min) / TILE_V            # V 除以周期数 -> [0, span/TILE_V]
```

```python
# 贴图侧：原图竖排 TILE_V 次（albedo/M/R/NM/O 五张都要，否则通道之间错位）
strip = Image.new(im.mode, (w, h * TILE_V))
for i in range(TILE_V):
    strip.paste(im, (0, i * h))
```

校验：`(span_v / TILE_V) * TILE_V == span_v`。本例 UV V 跨 1.0936、贴图 8 个周期，
总周期 8.75，与原模型一致。

**④ 每个材质都要有 diffuse；透明度必须来自独立的 `<名>_A.png`**

```
Fatal: No diffuse texture for material 'T90A_glass'          # 只给 baseColorFactor 不行
Fatal: Texture slot 'OpacityTexture' ... does not match '^.*_A$'   # 透明度借了 diffuse 的 alpha
```

给玻璃这类常量材质也生成一张 512² 常量 PNG；alpha 另建一个 image node 指向
`<材质名>_A.png`，**不要**把 diffuse 图自己的 Alpha 接到 BSDF 的 Alpha。

另外：贴图在 FBX 里只记**文件名**，AssetCooker 回到 GameData 里按同名找。
所以**材质节点里引用的文件名**必须与落盘文件名一致 —— 源文件叫
`T90A_track_L.png` 而节点引用 `T90A_track.png` 时会报
`File not found : 'GameData:/.../T90A_track_L.png'`。
（文件名**不必**等于材质名：官方 M1 的 `Chenille_Droite` 材质引用的就是
`M1_Abrams_tracks.png`。）

**④-b 玻璃材质必须自成一对：`<名>.png` + `<名>_A.png`**

这条和上一条是一伙的，但坑法不同 —— **不报错，进游戏才看得见**。

AssetCooker 是按 **base 的文件名**去配 alpha 的：`MIG_29M.png` 永远配 `MIG_29M_A.png`。
所以玻璃材质如果偷懒借用机体的 diffuse：

```python
# ❌ 错：玻璃用机体贴图当 diffuse，只换 alpha
mat_glass = make_mat("Vitre", "MIG_29M.png", ..., "MIG_29M_glass_A.png")
```

那么 `Vitre` 的 `OpacityTexture` 虽然写进了 neu3，实际取到的却是机体的
`MIG_29M_A.png`（全 255）——**舱盖在游戏里完全不透明**，而 neu3 里
`OpacityTexture / Transparency / SurfaceStandard` 一应俱全，静态查不出来。

```python
# ✅ 对：玻璃自己的 base + 自己的 _A（已验真的 Ka-58 就是 Ka58_glass + Ka58_glass_A）
Image.new("RGB", (512, 512), (88, 104, 116)).save(".../MIG_29M_glass.png")
Image.new("L",   (512, 512), 110).save(".../MIG_29M_glass_A.png")
mat_glass = make_mat("Vitre", "MIG_29M_glass.png", R, M, NM, "MIG_29M_glass_A.png")
mat_glass.blend_method = 'BLEND'        # 与 Ka-58 一致；HASHED 会有抖动噪点
```

尺寸：玻璃这一对可以只有 512²（base 与 `_A` 互相同尺寸即可，不必等于机体 4K）；
`_R/_M` 沿用它自己的 ORM 组，与玻璃 base 不同尺寸没问题（Ka-58 同样如此）。

【验收】除了看 neu3 里 `OpacityTexture` 后面的文件名确实是自己那一对，
还要**回 Blender 渲一张座舱近景**：玻璃半透 + 能看到座椅/仪表板 = 对；
看得见"穿透到另一侧的空壳" = 该机型本来没有座舱内构，得先补内壳再上玻璃。

---

## 2. PBR 通道必须接进材质，不能只把图放对目录

这是 T-90A 那一轮最贵的坑，值得单列。

### 【原理】AssetCooker 看的是**节点**，不是文件名约定

三条互相独立的证据：

1. 官方 `M1_Abrams.fbx` 的**每个**材质都挂了 4 个 image 节点：

   ```
   <名>.png     sRGB       -> Base Color
   <名>_NM.png  Non-Color  -> Normal Map.Color -> Normal
   <名>_R.png   Non-Color  -> Roughness
   <名>_M.png   Non-Color  -> Metallic
   ```

2. 官方 `Chenille_Droite` 材质引用的是 `M1_Abrams_tracks.png`，
   **材质名与贴图名对不上**。若是按命名约定去找，它永远找不到图。

3. 反证：只挂 base color 时，编译产物只有
   `TSCColor_DiffuseTexture…` + `TSCColorAlpha_CombinedDA…` 两张；
   把 3 条通道接上后，立刻多出
   **`TSCNM_NormalTexture01.tgv`（5.1 MB）** 与
   **`TSCORM_CombinedORMTexture01.tgv`（2.1 MB）**。
   `Mesh_All.spk` 也因切线数据从 852 KB 涨到 1.04 MB。

### 【现象】不接不报错，只是"静默变丑"

- 引擎回落到默认粗糙度（观感约 0.1–0.2），车体像涂了油、镀了铬，
  天空环境被整片镜面反射，迷彩被白光冲掉；
- 没有法线细节，高光是一整片连续镜面，越看越像塑料；
- **NDF 侧无从补救**：`TResourceMesh` 只有 `Mesh=` 一个字段，没有材质参数，
  材质 100% 由 FBX 决定。

### 【操作】四条通道的接法

```python
def link_pbr(nt, bsdf, name, texdir):
    d = texdir
    for suff, sock in (("_R", "Roughness"), ("_M", "Metallic")):
        p = os.path.join(d, name + suff + ".png")
        if os.path.exists(p):
            t = nt.nodes.new('ShaderNodeTexImage')
            t.image = bpy.data.images.load(p, check_existing=True)
            t.image.colorspace_settings.name = 'Non-Color'   # 关键
            nt.links.new(t.outputs['Color'], bsdf.inputs[sock])

    p = os.path.join(d, name + "_NM.png")
    if os.path.exists(p):
        t = nt.nodes.new('ShaderNodeTexImage')
        t.image = bpy.data.images.load(p, check_existing=True)
        t.image.colorspace_settings.name = 'Non-Color'       # 关键
        nm = nt.nodes.new('ShaderNodeNormalMap')             # 必须过这个节点
        nt.links.new(t.outputs['Color'], nm.inputs['Color'])
        nt.links.new(nm.outputs['Normal'], bsdf.inputs['Normal'])
```

⚠ **色彩空间是第二个坑**：`_R`/`_M`/`_NM` 存的是线性数据，按 sRGB 解码会
被压暗（0.5 → 0.21）。roughness 平白变低，等于白接。

### 【验收】看编译产物有没有 4 个 tgv

```
Gen/PC/Atlas/<资产路径>/
  TSCColor_DiffuseTextureNoAlpha01.tgv     颜色
  TSCColorAlpha_CombinedDATexture01.tgv    颜色 alpha
  TSCNM_NormalTexture01.tgv                法线   ← 少了就是 _NM 没接
  TSCORM_CombinedORMTexture01.tgv          O/R/M  ← 少了就是 _R/_M 没接
```

`ORM` 这个命名说明引擎把 `_O`/`_R`/`_M` 打成 R/G/B 三通道。
所以 `_O` 虽然**不需要**挂节点，但它**会被用** —— 给一张纯白 `_O`
等于主动放弃 AO，缝隙和车底不会变暗。

### 【附带坑一】glTF 拆出来的法线基准是歪的

从 GLB 拆的 `_NM`，平坦区不是 (128,128,255)，而是 **(177,178,234)**，
反算得法线 (0.394, 0.390, 0.832)，与 +Z 夹角 **33.7°**。

判据：平坦区采样 9240 点，与均值方向夹角**中位 0.6° / p90 0.9°**
→ 这是**统一基准偏移**，不是局部损坏。用一个 Rodrigues 旋转把基准
扳回 +Z，细节的相对起伏完整保留：

```python
axis = (B[1], -B[0], 0)      # B x (0,0,1)
s, c = |axis|, B[2]          # 旋转角 acos(B·Z)
```

不校正直接接，所有表面会被照成同一个斜角，**比不接更糟**。

判断阈值：偏 < 3° 就别动，免得把本来正确的烘焙图来回揉。

### 【附带坑二】烘焙 atlas 的空白区会把材质带坏

UV 岛只占图纸一部分，空白区被清成：

- `_R` → 纯黑 255 个 0，即 **roughness 0 = 满镜面**。
  UV 边缘插值和远处 mipmap 都会把这片黑平均进来，表现为「**越远越亮**」。
  本例 gun/mg/net 的纯黑占比 42% / 42% / 78%。
- `_NM` → **(128,128,128)**，解出 (0,0,0) 零长度法线，会出黑斑或异常高光。

处理：组装阶段统一填掉。`_R` 的纯黑填 190（先确认内容区不含 0 值，
判据是 `<32 的占比 == 纯黑占比`）；`_NM` 的长度 <0.5 一律复位成 (128,128,255)。

### 【附带坑三】Roughness / Metallic 上"顺手加个 MATH"→ ORM 槽静默消失

**症状与坑二不同**：这里不是"图放错了"，是**图明明在、节点也连着，但 FBX 里就是没有 `_R`/`_M` 引用**，
于是编译产物里 `TSCORM_CombinedORMTexture01.tgv` 根本不生成，车体又是一片镜面。
**编译不报任何错**，只有蹲在 `Gen/` 里数 tgv 才发现。

**【原理】** Blender 的 FBX 导出器取贴图的方式是"认直连"：

```python
# bpy_extras/node_shader_utils.py  ShaderImageTextureWrapper
if socket_dst.is_linked:
    from_node = socket_dst.links[0].from_node
    if from_node.bl_idname == 'ShaderNodeTexImage':     # ← 只认这一种
        self._node_image = from_node
```

只要 `Roughness` / `Metallic` 的**第一跳**不是 `ShaderNodeTexImage`
（中间隔了 `MATH`、`SEPARATE_COLOR`、`MIX` 任何一个），`node_image` 就是 `None`，
`export_fbx_bin.py` 里 `PRINCIPLED_TEXTURE_SOCKETS_TO_FBX` 的循环直接 `continue` 跳过，
**该通道在 FBX 里静默消失**。

这个坑特别容易被"顺手"引入：想让粗糙度整体偏一点，就在图后面挂个 `MATH > Multiply 0.75`，
看起来完全合理，实际上把整条 ORM 通道废掉了。

**【操作】** 有中转就拆掉，让贴图**直接**连 BSDF：

```python
# 沿链往上游找第一个贴图节点，然后清掉旧链接、贴图直连 BSDF
for sock in ("Roughness", "Metallic"):
    inp = bsdf.inputs.get(sock)
    if not inp.is_linked:
        continue
    cur, tex = inp.links[0].from_node, None
    for _ in range(4):                      # 最多往上找 4 跳，防环
        if cur.type == 'TEX_IMAGE' and cur.image:
            tex = cur
            break
        nxt = next((i.links[0].from_node for i in cur.inputs if i.is_linked), None)
        if nxt is None:
            break
        cur = nxt
    if tex is None:
        continue
    for l in list(inp.links):
        nt.links.remove(l)
    nt.links.new(tex.outputs['Color'], inp)
# 顺手清掉不再被引用的 MATH 节点
for n in list(nt.nodes):
    if n.type == 'MATH' and not any(o.links for o in n.outputs):
        nt.nodes.remove(n)
```

> 参考实现：本项目 `lance/fix_orm_direct.py`（批量扫 .blend，幂等）。

**【验收】两条一起看**

```bash
# ① 静态查（快）：--cook 会把「ORM 走中转」直接判成硬伤，rc=1
blender -b -P mesh_check.py -- <model.blend> --cook
#   期望输出里没有：xxx: Roughness 走 MATH 中转，未直连贴图 → FBX 无 _R …
#   且材质行 ORM= 后面只出现 TEX_IMAGE

# ② 动态查（准）：重新导出 FBX 并编译，数 tgv
ls Gen/PC/Atlas/<资产路径>/TSCORM_*.tgv      # 必须存在
```

**注意**：这条只适用于 `Roughness` / `Metallic`。`Base Color` 走 `MIX`/渐变是合法用法
（多材质混合、双层迷彩），`--cook` 对它只给提示不判失败。

---

## 3. 在成品 FBX 上补几何（不重跑烘焙）

适用场景：模型已经编译通过、贴图也验收过了，只想**加一小块几何**
（本例：T-90A 的 Shtora 干扰灯圆窗）。重跑整条烘焙流水线风险大、也没必要。

### 【原理】FBX 进 Blender 再出来**不是无损的**

实测（Blender 5.3，同一份 FBX 导入→立即导出）：

| 项 | 结果 |
|---|---|
| 节点层级 / Mesh / Null 数量 | **完全一致**（29 节点、6 Mesh、23 Null） |
| 不透明材质的 4 条通道节点树 | **完全一致** |
| 玻璃材质的 `_A` 引用 | **丢失** —— 两个 image 节点的 filepath 都变成 `T90A_glass.png` |
| 三角面 | 冒出若干共线/零面积退化面 |

两条后果都很硬：

- `_A` 丢了 → 编译报 `Texture slot 'OpacityTexture' ... does not match '^.*_A$'`。
- 退化面 → 报 `Mesh contains an abnormal normal: sub-mesh 'X', ... normal length 0`，
  且报的那个 sub-mesh 往往**不是**你改动过的那个（本例是 `Axe_Canon_02`，完全没碰）。

### 【操作】导出前必须做的两件事

1. **按贴图文件重建全部材质**，不要沿用导入结果。
   FBX 只记贴图**文件名**，所以材质完全由「贴图文件 + 建材质代码」决定，
   重建比"修"可靠。命名空间要先腾：把导入的材质改名成 `OLD_<名>`，
   再 `bpy.data.materials.new()`，否则会得到 `T90A_body.001` 这种名字写进 FBX，
   AssetCooker 按同名找图必然找不到。
2. **对全场景**（不只是新加的对象）清 custom split normals + 迭代清洗退化面：
   `dissolve_degenerate(1e-4)` → `quads_convert_to_tris` → `delete_loose`，
   循环到「无 n-gon 且无零面积三角面」为止（实测一轮不够：dissolve 会把
   相邻三角面合并成 n-gon，必须再三角化一次）。
   导出前逐个三角形算 `(b-a)×(c-a)` 自检，最小长度不能是 0。

### 【操作】新几何怎么挂上去

- 在**世界坐标**建网格，再 `bpy.ops.object.join()` 进目标部件（本例 `Tourelle_01`），
  join 会自动把顶点换算进目标的局部空间 —— 不要手算 `matrix_world.inverted()`。
- 新材质会作为新槽追加；用 `material_index` 计数自检（本例期望 `SEG*6` 面）。
- UV **不许全塌到一个点**：UV 退化会让引擎算不出切线基，法线贴图通道拿到 NaN 切线，
  整块面可能变黑或全反光。按半径把 UV 铺开即可，贴图是常量色也不影响观感。

### 【验收】

- `fbx_anchors.py check` 仍通过（Mesh/Null 数量不变）
- 导出 FBX 里 `<名>_A.png` 等 8 套引用齐全（可以 `grep -aoi "T90A_[A-Za-z_]*\.png"` 数一遍）
- 编译产物 `Mesh_All.spk` 增大，4 个 tgv 都在；128² 的常量色贴图只让
  4096² 合并 atlas 涨 ~1.5 KB，不会挤爆已占 98% 的图集

---

## 4. 「删掉不可见面」的减面法（仅对内腔封闭的模型成立）

### 【原理】

按「从面沿半球方向发射线、全被挡住就删」来减面，在实机里表现为**车体漏风**：
能看到坦克内部，或者直接看穿车身。原因是这套判据把**双层壳的背面**当成了冗余。

坦克模型通常是「外壳 + 内衬」两层：外壳正面朝外，内衬正面朝里。内衬从外面
确实一发线都打不出去，判定为"完全不可见"——**但它正是外壳开孔处的视觉背板**。
模型本身不是水密体（面板拼接、舱口、格栅都有既存开口），日常渲染时是内衬在
挡着视线。内衬一删，那些既存开口就直通空腔，于是"漏风"。

判据：**边界边（只被 1 个面共享的边）数量**。T-90A 实测

| 部件 | 原始（可正常显示） | 删不可见面后 | 倍数 |
|---|---|---|---|
| Chassis | 7,994 | **30,677** | 3.8× |
| Tourelle_01 | 4,496 | **15,314** | 3.4× |
| Axe_Canon_02 | 219 | 1,040 | 4.7× |

原始模型本来就有几千条边界边（说明它本来就不封闭），所以「边界边 > 0」
不能当报警线；**要看的是删完之后涨了几倍**。涨 3 倍以上，必然漏风。

第二个放大器是**删完再 Decimate**：collapse 会沿着新产生的开放边界塌陷，
把小缝拉成大洞。即使删除本身只是"轻微漏"，减面会把它放大成明显破口。

### 【操作】

- **不要**用「可见方向数为 0 就删」直接减面，除非确认模型是水密单体
  （先数边界边，或 `is_manifold` 检查）。
- 需要真正减面时，按优先级用：① 只删**整个连通分量**都不可见的岛（分量级删除
  不产生新边界边）；② 删完立刻对每条边界环做封盖；③ 改用顶点组加权的
  Decimate，保留背板不删。
- 减面收益的判断标准不是面数，而是**纹素密度**：先量
  `sqrt(表面积 / (W×H))`。T-90A 的面数从 44,718 提到 62,811（面密度 93 → 461 f/m²），
  贴图仍是 8 mm/texel，实机观感几乎无差别。**面数不是瓶颈时，减面/加面都是白做。**

### 【验收】

- 删除前后边界边数量比值 < 1.5
- 近距贴地视角（仰角 0°、距离 3 m）绕一圈，看不到车体内部
- 实机确认，不要只看离线渲染——离线渲染器的背面剔除与光照和引擎不同，
  漏风在离线图上往往不明显

### 【本次结论】

T-90A 高清版（62,811 面）已实机确认为漏风，**回滚**至 44,718 面版本。
高清重建的产物保留在 `build/hd/`（`bpy_t90_geo_hd.py` 生成），但不可用于发布。

---

## 5. 合并 atlas 的像素预算怎么分

### 【原理】

AssetCooker 把一套模型的所有贴图**按各自 PNG 的像素尺寸装箱**进一张 4096² 的
合并图（`TSCColor_DiffuseTextureNoAlpha01.tgv` 等 4 张），不做统一缩放。
所以：

```
atlas 占用率 = Σ(每张 albedo 的 W×H) / 4096²      4096² = 16.78 M px
```

**占用率不是画质指标，纹素密度才是**：

```
mm/texel = sqrt( 表面积_mm² / (W × H × UV覆盖率) )
```

UV 覆盖率（UV 岛总面积，可能 >1 表示镜像复用）必须实测，不能按 1.0 假设。
校准基准：官方 `M1_Abrams` 是 **6.66 / 6.31 mm/texel**。

### 【操作】

1. 逐材质统计三件东西：面数、3D 表面积、UV 岛面积（按极坐标公式算三角形面积和）。
2. 与官方基准比，算出每组的 mm/texel。
3. 对「比基准细」的组按 `W×H = 表面积 / (目标密度² × UV覆盖)` 反算，取 2 的幂。
   比基准粗的组**不动**——除非有更高分辨率的源图，否则放大了也不长信息。
4. 烘焙外扩 margin 要随分辨率缩放（`max(4, min(12, res//128))`），
   否则小图上 margin 会盖住相邻 UV 岛。

### 【验收】

- 编译后 4 个 tgv 应同步变小（diffuse / NM / ORM / ColorAlpha）
- 同机位渲染逐像素比：平均差 < 1/255，>8 的像素 < 1%
- 各组 mm/texel 都不比改动前粗

### 【实测（T-90A，44,718 面）】

改前：gun 2048² / mg 2048² / net 2048² 各 4.19 M px，合计 12.6 M（atlas 的 75%），
而这三组只覆盖 16.5 m²；真正占屏的 body(273 m²) / turret(60 m²) 只有 1.05 M / 0.52 M。
**mg 的密度 0.37 mm/texel，比官方细 18 倍**——纯浪费。

改后（gun 1024² / mg 256² / net 256² / track 512×1024 / glass 256²）：
占用 98.5% → **20.0%**，tgv 合计 10.62 → **4.34 MB（−59%）**，渲染差 ≤0.8% 像素。

### 【这条路的边界】

源图分辨率就是天花板。T-90A 的 GLB 内嵌图最大 1024²/1024×512，
把 body 放到 2048² 只是插值，**不会更清楚**。想再提升只能
AI 超分源图，或者接受现状。空出来的画布是给超分后用的，本身不产生画质。

---

## 6. 新增一个「小 FBX」当资源时的门槛

背景：为了"让引擎别画挂架"，试过自建一个 4 mm 立方体当隐形挂架。

`AssetCooker` 对任何新 FBX 有两道硬门槛（任一不满足直接 Exit 1，整个 GenerateMod 失败）：

| 报错 | 要求 |
|---|---|
| `fatal: No diffuse texture for material 'X'` | 材质必须挂 diffuse 贴图，且**材质名 = 贴图基名** |
| `fatal: Missing UV indices on object 'Y'` | 必须带 UV 层（`smart_project` 出来即可） |

**但通过 ≠ 能用。** `TResourceMesh` 只有一个 `Mesh` 字段、指向**整份 FBX**，没有节点过滤；
而引擎找挂架时匹配的是**模型自带的"槽位数"元数据**，自建几何声明不了槽，
所以"做一个看不见的挂架"永远匹配不上（`No pylon with requested slot count (1)`）。
详见 `21-depiction.md §4.3`。

---

## 7. 验收（管线）

- [ ] 贴图 6 张与 `.fbx` 同目录、基名一致；`_A`（透明）独立
- [ ] 顶点 / UV / 三角化的硬门槛见 `23-mesh-import.md §9`（同一道门，不在这里重复）
- [ ] 编译 `Mod Generation Success`，且 `Mesh_All.spk` **明显变大**、`Gen/PC/Atlas/` 下 4 个 tgv 齐
- [ ] 进游戏：不白模、不发油、不是纯黑

