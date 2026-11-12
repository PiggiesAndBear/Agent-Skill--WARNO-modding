# 资产管线：FBX 导出、材质贴图、减面与预算

**本文件管**：模型"做完之后、进引擎之前"的工序——导出参数、PBR 通道、补几何、减面、atlas 预算、新增小 FBX 的门槛。
**不管**：拆件 / 枢轴 / 动画（`24-rig-parts.md`）、锚点契约与导入流程（`23-mesh-import.md`）。

## 目录

| 节 | 管什么 | 什么时候读 |
|---|---|---|
| §0 | 导出定稿参数 | 每次导出都看 |
| §1 | glTF/GLB 四道清洗 | 素材不是 FBX 而是 glTF 时 |
| §2 | PBR 通道接材质 / **整车发黑的坑（§2 附带坑四）** / **调色专题** | 表面发油、发亮、像镀铬、**发黑看不出颜色** |
| §3 | 在成品 FBX 上补几何 | 只想加几个零件、不想重跑烘焙 |
| §4 | 删不可见面减面 | 面数超标、内腔封闭 |
| §5 | atlas 像素预算 | 多套贴图要合并 |
| §6 | 新增小 FBX 的门槛 | 想让引擎画/不画某个小物件 |

## 0.0 【六条】AssetCooker 卡人的命名/数值规矩（本项目实测，各踩一次）

| 现象（AssetCooker 原文） | 真因 | 修法 |
|---|---|---|
| `Texture slot 'DiffuseTextureNoAlpha' from material 'FPV_DRONE_A' violates naming convention: "FPV_DRONE_A.png" does not match '^.*_(A\|NM\|O\|M\|R\|P\|ORS)$'` | **材质名以 `_A` 结尾**，被当成 alpha 贴图后缀 | 材质名换掉尾缀（本项目改成 `FPV_DRONE_BODY`） |
| `Trying to combine textures with different resolutions: 'X_R.png' and 'X_M.png'` | 同一套贴图**分辨率不一致**（主图 2048、补的平坦图 1024） | 同一材质名下 base/_NM/_R/_M/_O **全部同分辨率**；补的平坦图按主图尺寸生成 |
| `Can't quantize texcoords because UVs are not in the range [-4, 4]: UV=(3.91, 4.07)` | **FBX 导出会翻转 V**（写 1−v），只按源 UV 平移救不了 | 判据改成 `max(|u|,|v|,|1−u|,|1−v|) ≤ 3.9`；超了就整体乘 0.5（贴图是 seamless 的，平铺密度变了也不出缝） |
| `Mesh contains an abnormal normal: sub-mesh 'Chassis', position = (…), normal length 0` | 源模型有**零面积三角**，法线 (0,0,0) | 导出前统一 `quads_convert_to_tris` → `dissolve_degenerate(1e-5)` → `delete_loose` → `normals_make_consistent` |
| `Texture slot 'NormalTexture' from material 'X' violates naming convention: "X_N.png" does not match '^.*_NM$'` | 法线贴图后缀写成 **`_N`**（不是 `_NM`） | 后缀一律 `_NM`。⚠ 注意与第 1 行的区别：**diffuse 槽的规则是"不许以这些后缀结尾"，Normal 槽的规则是"必须恰好以 `_NM` 结尾"**，两条同时生效 |
| `fatal: … Unrecognized image format`（文件名明明是 `.png`） | 文件头不是 PNG。Blender 的 `image.save()` / `save_render()` 在部分情况下**把原始缓冲直接落盘**，扩展名是 `.png` 而内容是 JPEG（`ffd8ffe0`） | 用 PIL **按格式重编码**：`Image.open(src).save(dst, format="PNG")`；完事 `open(...,'rb').read(4) == b'\x89PNG'` 断言一次 |

六条都属于"编译期明确报错"，比缺骨骼那类静默失败好查；**报错里的文件名就是真因**，别去 NDF 里找。
但要注意**报错文字可能指向错误的槽位**：`Unrecognized image format` 那条只报"某张图不是图"，
不报是哪一张——按"最近新加的那套贴图"逐个查文件头，比按报错找快。


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

### 【附带坑四】从源材质「抄通道」时的两个致命误读（**整车发黑就查这两条**）

从外部模型（Sketchfab / glTF）迁材质时，常见做法是「顺着 Base Color / Roughness /
Metallic 的入链回溯，把摸到的贴图按通道拆出来」。这一步有两个会同时踩的误读。

#### ① 只看链接、不看**乘数** ⇒ 抄出一张全白金属度

```
SEPARATE_COLOR.Blue → MATH(MULTIPLY, B=0.0) → Metallic     ← 源材质把金属度压成 0
```

上一版代码直接把 `SEPARATE_COLOR.Blue` 对应的 B 通道导成 `_M`，
结果那张 ORM 的 **B 通道整张 = 1.000**（min 0.787）⇒ 导出 `_M` 全白 ⇒
`metallic = 1` ⇒ **没有漫反射，整车在游戏里几乎全黑、只剩轮廓**。

- 症状极具误导性：看起来像「贴图太暗 / 光照不对 / 色调太黑」，**实际是材质类型错了**。
- **判据**：回溯到 BSDF 的**第一跳**之外，把中间节点（`MATH` / `MIX` / `SEPARATE_COLOR`）
  的乘数、混合模式一起读出来。乘数为 0 就必须导常量 0，而不是导那张通道。
- **验收（最省事）**：`_M.png` 用 PIL 量均值，和本 Mod **已实机通过**的车对比：

  ```python
  from PIL import Image; import numpy as np
  a = np.asarray(Image.open(p).convert("RGB"), np.float32) / 255.0
  print(a.mean(axis=(0, 1)))        # 车体应为 ~0.0；若 ≈1.000 就是全金属
  ```

  本项目实测：2S25 0.24–0.34、Object685 / Tochka / BMPT-787 / T-90A **0.000**、
  LOSAT（错误版）**1.000**。全 0 是这类「涂装车体」的正常值。

#### ② `Image.pixels` 返回的是**原始存储值**，不是线性值

```python
px = np.empty(w * h * 4, np.float32); im.pixels.foreach_get(px)
# 8bit sRGB 图：拿到的是 sRGB 数值（≈ 磁盘 PNG/255），不是线性值
```

Blender 只在**着色器采样时**做色彩管理；`pixels` 是裸缓冲。据此在调色函数里
再做一次 `lin2srgb()` 往返，等于**套了两遍 gamma**：日志里的「原值」
每个通道都虚高（实测 `R=0.513`，真值 `0.234`），调色结果整体偏色。
处理 8bit 贴图时直接对 `pixels` 做「sRGB 空间」运算（gamma / 增益 / 饱和度）即可，
写完再把图设成同样的 `colorspace_settings`。

#### ③ 源模型**根本没有 ORM** ⇒ `_R` / `_M` 整个缺失（与①同病）

有些源模型（尤其 Sketchfab 的低价位车模）材质里**只有 D 和 NM**，没有 ORM。
按「摸到什么导什么」写出来的烘焙脚本，就会只产出 `_D.png` / `_NM.png` 两张 ——
引擎拿不到 roughness / metallic，**结果与①的「`_M` 全白」完全一样：走成金属外观、发黑**。

- **判据**：`ls <资产目录>` 只有 `_D` / `_NM`，或编译产物 `Gen/PC/Atlas/.../` 里
  **没有 `TSCORM_CombinedORMTexture01.tgv`**。本 Mod LAV-600 就是这一例：
  补上 R/M 后该 tgv 才第一次出现（2,820 B，纯色压缩率极高）。
- **操作**：用**常量图**补齐，尺寸与 `_D` 一致（含平铺倍数）：

  ```python
  const_tex(path_R, 0.945, w, h * tile)   # 粗糙度：涂装车哑光
  const_tex(path_M, 0.000, w, h * tile)   # 金属度：非金属
  ```

  取值口径对齐本 Mod **已实机通过**的车：T90A / Object685 / BMPT-787 / LOSAT 的 `_R` 均 **0.945**、
  `_M` 均 **0.000**（2S25 的 `_R` 来自 ORM 的 G 通道，0.61–0.64，也可用）。
- 节点侧必须**四通道直连**（首跳 `TEX_IMAGE`，见坑三），否则 ORM 槽仍然不生成。
- **一句话**：`缺 _M` 与 `_M≡1` **是同一种病**。判据是「引擎最终拿到的 metallic」，
  不是「贴图文件有几张」。

---

### 【专题】贴图「偏黑 / 看不出颜色」的三层排查顺序

按这个顺序查，能少走两轮：

| 层 | 查什么 | 判据 |
|---|---|---|
| 0 | **`_R` / `_M` 这两个文件到底有没有生成** | 见坑四 ③；缺文件 ≡ 全金属，同样发黑。查 `Gen/PC/Atlas/…` 有没有 `TSCORM_*` |
| 1 | **`_M` 是否全白**（金属度） | 见坑四 ①；全 1.0 ⇒ 必然发黑 |
| 2 | **`_R` 是否被压暗** | 源 Roughness 若走了 `MATH×k`，`_R` 要按同一乘数导出；否则偏亮/偏哑 |
| 3 | **Base Color 本身是不是棕灰** | 用 PIL 量 `R/G/B` 均值：`G/R < 1` 且 `G−B < 0.05` ⇒ 这张图本来就没有绿，只能调色 |

第 3 层确认「图本身无绿」后，才做**调色**（不要用改光照/改 `_R` 去凑）：

```python
# 全部在 sRGB 空间算；参数集中放一个模块，烘焙脚本与离线对照工具共用
def grade_srgb(s, gamma, gain, sat):
    y = np.clip(s, 0, 1) ** gamma * np.asarray(gain)      # gamma<1 提亮中间调
    lum = (y * [0.2126, 0.7152, 0.0722]).sum(-1, keepdims=True)
    return np.clip(lum + (y - lum) * sat, 0, 1)           # 饱和度绕亮度缩放
```

**调参要留对照图**：把「原色 / 温和 / 橄榄 / 明显」四档并排渲成一张图
（同一批裁剪区域，不跑引擎），选中哪档再写回参数。本项目实测一组可直接复用的值：

| 目标 | gamma | 通道增益 (R,G,B) | sat | 8bit 均值变化 |
|---|---|---|---|---|
| 橄榄绿车体 | 0.85 | (1.00, 1.10, 0.80) | 1.15 | `R .234 G .222 B .188 → R .288 G .306 B .176` |
| 枪械（保持灰） | 0.92 | (1.00, 1.00, 1.00) | 1.00 | 只提亮，不改色相 |
| 履带 | 0.85 | (1.00, 1.02, 0.95) | 1.05 | 跟上车体亮度，微绿偏 |

> 验收不能只看贴图数值，必须**渲一张整车**看：`_M` 归零后暗部会被环境光抬起来，
> 与只看 albedo 的判断不同。本项目在 `R .288/.306/.176`、`lum 0.293` 时
> 与同批单位（0.26–0.27）亮度接近且绿色可辨。

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

## 6.1 【静默杀手】资产目录不能与原版游戏路径重名

**症状**：`AssetCooker` 全程 `rc=0`、无 Fatal、日志一路绿，但 `Gen/PC/Mesh/…/`
下**主网格 `mesh.neu3` 根本不生成**，只生成了你后来加的那份附属小 FBX
（本项目：主模型没有，`Rail/…_Rail` 那份有）。进游戏自然是空白/无模型，**零报错**。

**真因**：`AssetCooker` 按**路径**判重。若你的 FBX 落在与原版游戏资产完全相同的目录

```
✅ 原版：GameData:/Assets/3D/Units/URSS/Canon/Howz_2A36_Giatsint_B/
❌ 你的：同一条路径 —— 烘焙器认为"这个路径已在 CoreCatalog 里注册过"，直接跳过不生成
```

它不会覆盖、不会提示、不会报错，就是**当作已做过**跳过。改内容、改文件名、加 `_v2`
都没用，**判据是目录**（`Ref` 路径），不是文件。

**修法**：换一个游戏里**不存在**的目录名，把整个资产目录搬过去，再同步改所有
`Mesh="GameData:/Assets/..."` 引用：

```
GameData:/Assets/3D/Units/URSS/Canon/Howz_2A36_Giatsint_B_KRSN/
```

**验收判据（别看 rc）**：

- [ ] `Gen/PC/Mesh/<新目录>/mesh.neu3` 存在且**体积合理**（百 KB 级，不是 0）
- [ ] 附属 FBX 各自也有 `.neu3`（放在子目录 `Rail/` 的会单独出一份）
- [ ] `AssetCooker` 日志里出现 `Generating: …/mesh.neu3`（**没有这一行就是被跳过了**）

⚠ 反向陷阱：为了"省事"直接原地改原版目录的操作**同样危险** —— 你会静默地改不掉，
且下一次全量 cook 时可能与核心包互相覆盖。**永远另起目录名。**

---

## 6.2 【加载期】骨骼校验：编译全绿，启动才 Fatal

管线分三道闸，**前两道全过不代表能进游戏**：

| 闸 | 谁在查 | 查什么 | 不过的表现 |
|---|---|---|---|
| ① NDF 编译 | `WARNO.exe -generatemod` | 语法 / 引用 / 弹药箱数值一致性 | `Can't load NDF/GFX/Weapon.ndfbin` |
| ② 资产烘焙 | `AssetCooker` | 贴图命名、UV、法线、材质 | `Fatal: ...` + 文件名 |
| ③ **加载期** | 游戏读 `ndfbin` 时 | **FBX 的节点名 / 骨骼名** | `Can't load 'Glad:/NDF/GFX/Depiction.ndfbin'` 弹窗 |

第 ③ 道最坑：**编译链没有任何输出**，报错文本指向 `Depiction.ndfbin`，
但真因全在 FBX 的节点表里。

### 已实测的加载期硬校验（本项目各撞一次）

| 报错原文 | 缺失的节点 | 修法 |
|---|---|---|
| `Not enough hardpoint groups : missile system needs 1 hardpoint groups, model has 0 'as' and 'aa' hardpoint groups combined.` | `as_{槽}_{序}`（如 `as_1_1`） | 挂架网格补硬点组，见 `26-ground-missile-tel.md §4.2` |
| `Missing subdepiction anchor bone 'servant_g'` / `'servant_d'` | 班组锚点骨 | 见下 |
| `Missing bone 'bras_droit' requested by operator 'carriable'` / `'bras_gauche'` | 拖拽臂骨 | 见下 |

### 【原理】牵引炮模型必须自带 4 根「非几何」骨

原版牵引炮的 depiction 里有两条引用，**它们不在 NDF 里点名骨骼，而是由算子/子描绘去 FBX 里找**：

```
SubDepictions = [ ] + HumanSubDepictions_<Unit>   →  锚点 = servant_g / servant_d
Operators     = [ ..., DepictionOperator_Carriable_Canon_Arms35, ... ]
                                                 →  TCosmeticCarriableOperatorDesc 找 bras_droit / bras_gauche
```

- `servant_g` / `servant_d`（gauche 左 / droite 右）是**可见班组的落点**：
  `SubDepiction_ServantLeft/Right` 把兵挂在这两根骨上，锚点在**脚底、地面高度 Z=0**。
  少了 → 班组无处可挂，整份 depiction 加载失败。
- `bras_droit` / `bras_gauche` 是 `carriable` 算子（起步时抬架 / 展臂）用的骨。
  本模型没有手臂几何，它们**只占位、不可见**，但**必须存在**。

⚠ 这两类骨**都不是**「可选装饰」：`HumanSubDepictions_*` 和 `carriable` 是官方牵引炮的标准配置，
自己重写 `Towed/*.ndf` 时照抄了这两行，就必须把骨补进 FBX。

### 【操作】

1. 回**烘焙脚本**的骨骼字典里加节点（父级 = `Chassis`，与其他 `fx_*` 同级、静止不参与动画）：

```python
"servant_g": Vector((-0.6,  1.15, 0.0)),   # 炮尾后方、大架内侧，脚底 Z=0
"servant_d": Vector((-0.6, -1.15, 0.0)),
"bras_gauche": Vector((-3.0,  3.15, 0.9)), # 贴着大架后段，手的高度
"bras_droit":  Vector((-3.0, -3.15, 0.9)),
```

2. 左右符号沿用项目既有约定：**`+Y = gauche(左)`**（与 `roue_gauche_01`、`fx_tourelle5_tir_01` 一致）。
3. 站位要**算、不要猜**：加一段自校验，打印锚点到最近网格顶点的距离。
   本项目实测 `servant_*` 距最近顶点 0.97~1.06 m（清楚站在两腿大架之间），
   `bras_*` 0.16~0.32 m（贴梁，不可见所以不要求间距）。
4. 若已有 `_fold` / `_deploy` 动画，**重跑动画烘焙**：`.baf` 是逐节点矩阵，新骨会作为静止节点一起导出，
   不重跑就会出现「网格有骨、动画没骨」的不一致。
5. **不要**在成品主网格 FBX 上二次导入再导出补骨（贴图相对路径与材质节点会受影响）；
   直接改烘焙脚本重跑，代价只是几分钟。

### 【验收】

- [ ] FBX 节点表里有这 4 根（`scripts/fbx_anchors.py dump <fbx>`）
- [ ] 烘焙出的 `mesh.neu3` 里能 `strings` 到 `servant_g` / `servant_d` / `bras_droit` / `bras_gauche`
- [ ] 两段 `.baf` 体积比补骨前略大（本项目 8,732 → 9,628 B）
- [ ] 进游戏能过主菜单（这一步过了才说明加载期校验全过）

⚠ **判据**：加载期 Fatal 指向 `*Depiction.ndfbin` 或 `*Unit.ndfbin` 时，
**先去数 FBX 的节点名**，不要先去 NDF 里搜字段 —— 报错里的 NDF 只是"谁在读"，
真因在它读的那张网格上。


---

## 7. 验收（管线）

- [ ] 贴图 6 张与 `.fbx` 同目录、基名一致；`_A`（透明）独立
- [ ] 顶点 / UV / 三角化的硬门槛见 `23-mesh-import.md §9`（同一道门，不在这里重复）
- [ ] 编译 `Mod Generation Success`，且 `Mesh_All.spk` **明显变大**、`Gen/PC/Atlas/` 下 4 个 tgv 齐
- [ ] 进游戏：不白模、不发油、不是纯黑

