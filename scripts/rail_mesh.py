# -*- coding: utf-8 -*-
"""建「出管挂架网格」：把出管轴骨骼单独烤成一份无动画网格（Blender 脚本）。

用途
----
地面导弹发射车 / 垂直发射装置，导弹出管方向不取武器描述器的俯仰数值，
而取 `MissileCarriage.MeshDescriptor` 所指网格里的出管 box（骨骼）。
车体网格带 deploy/fold 动画，绑定姿态下发射架是平的 → 方向会退回水平。
所以要把出管轴烤进一份**独立、无动画**的网格，再让挂架指向它。详见
`26-ground-missile-tel.md §4`。

用法
----
blender -b -P rail_mesh.py -- \\
    --src  <展开态 blend>              （取骨骼世界矩阵的那份，必须是"部署好"的姿态）
    --out  <mod>/.../Rail/<名>_Rail.fbx
    --bones missile_1,canon_01,as_1_1  （第一个当作 Chassis 的位置与朝向）
    [--box 0.004]                      （Chassis 立方体边长，米）
    [--expect-elev 70]                 （期望的出管仰角，用于断言）
    [--tol 5]                          （仰角容差，度）
    [--blend <另存 .blend 路径>]

要点（都是踩过的）
------------------
* 骨骼在*车体*网格里应挂 `Tourelle_0N`（yaw 骨）下、不挂随动画走的枢轴；
  本脚本产的是独立挂架件，根就是 Chassis，骨骼直接挂 Chassis 即可（世界坐标不变）。
* 三角化：AssetCooker 报 `Mesh not exported triangulating faces`，必须先在 Blender 里三角化。
* FBX 所在目录要有同名贴图，否则报 `fatal: File not found`；本脚本落一张 4×4 纯色 PNG。
* 输出路径必须绝对（Blender 里相对路径会掉到盘符根）。
"""
import bpy
import os
import sys
import math
import argparse
from mathutils import Matrix, Vector

argv = sys.argv
argv = argv[argv.index("--") + 1:] if "--" in argv else []

ap = argparse.ArgumentParser()
ap.add_argument("--src", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--bones", default="missile_1,canon_01,as_1_1")
ap.add_argument("--box", type=float, default=0.004)
ap.add_argument("--expect-elev", type=float, default=None)
ap.add_argument("--tol", type=float, default=5.0)
ap.add_argument("--blend", default=None)
ap.add_argument("--tex", default=None, help="贴图基名，默认取 FBX 同名的 _D")
a = ap.parse_args(argv)

SRC = os.path.abspath(a.src)
OUT = os.path.abspath(a.out)
OUTDIR = os.path.dirname(OUT)
os.makedirs(OUTDIR, exist_ok=True)
TEXNAME = (a.tex or os.path.splitext(os.path.basename(OUT))[0]) + "_D.png"
TEXP = os.path.join(OUTDIR, TEXNAME)


def elev(v):
    return math.degrees(math.asin(max(-1.0, min(1.0, v.z))))


# ---------- 1. 从源 blend 抄骨骼世界矩阵 ----------
bpy.ops.wm.open_mainfile(filepath=SRC)
names = [n.strip() for n in a.bones.split(",") if n.strip()]
assert names, "--bones 为空"
M = {}
for n in names:
    o = bpy.data.objects.get(n)
    if o is None:
        raise SystemExit("源文件里没有骨骼 %s（可用 dump: bpy.data.objects.keys()）" % n)
    M[n] = o.matrix_world.copy()
    p = M[n].to_translation()
    print("[抄取] %-12s (%8.3f,%8.3f,%8.3f)  +X elev=%6.2f°"
          % (n, p.x, p.y, p.z, elev(M[n].to_3x3().normalized().col[0])))

AXIS = M[names[0]].to_3x3().normalized().col[0]
E = elev(AXIS)
if a.expect_elev is not None and abs(E - a.expect_elev) > a.tol:
    raise SystemExit("出管仰角 %.2f° 与期望 %.2f°±%.1f 不符 —— 源 blend 姿态不对？"
                     % (E, a.expect_elev, a.tol))
if E < -1.0:
    raise SystemExit("出管轴朝下（%.1f°），几乎肯定是抄了一个没展开的姿态" % E)

ROT = M[names[0]].to_quaternion().to_matrix().to_4x4()
POS = M[names[0]].to_translation()

# ---------- 2. 新场景 ----------
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene

bpy.ops.mesh.primitive_cube_add(size=a.box)
ch = bpy.context.object
ch.name = "Chassis"
ch.data.name = "ChassisMesh"
ch.matrix_world = Matrix.Translation(POS) @ ROT
bpy.context.view_layer.objects.active = ch

mat = bpy.data.materials.new("RAIL_INVIS")
mat.use_nodes = True
nt = mat.node_tree
for n in list(nt.nodes):
    if n.type != 'OUTPUT_MATERIAL':
        nt.nodes.remove(n)
outn = [n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL'][0]
bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
tex = nt.nodes.new('ShaderNodeTexImage')
img = bpy.data.images.new(os.path.splitext(TEXNAME)[0], 4, 4, alpha=False)
img.pixels = [0.25, 0.26, 0.22, 1.0] * 16
img.filepath_raw = TEXP
img.file_format = 'PNG'
img.save()
img.filepath = TEXP
img.source = 'FILE'
tex.image = img
nt.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
nt.links.new(bsdf.outputs['BSDF'], outn.inputs['Surface'])
ch.data.materials.append(mat)

# 三角化（AssetCooker 不做三角化）
tri = ch.modifiers.new("tri", 'TRIANGULATE')
bpy.ops.object.modifier_apply(modifier=tri.name)
nbad = sum(1 for f in ch.data.polygons if len(f.vertices) != 3)
assert nbad == 0, "仍有 %d 个非三角面" % nbad
print("[Chassis] %.1f mm，%d 面，elev=%.2f°" % (a.box * 1000, len(ch.data.polygons), E))

# ---------- 3. 骨骼挂到 Chassis 下 ----------
# 注意：*车体*网格里这些骨骼要挂在 Tourelle_0N（yaw 骨）下；但这份网格是独立
# 挂架件，根就是 Chassis，所以直接挂在 Chassis 下即可，世界坐标保持不变。
for n in names:
    e = bpy.data.objects.new(n, None)
    e.empty_display_type = 'PLAIN_AXES'
    e.empty_display_size = 0.2
    sc.collection.objects.link(e)
    e.parent = ch
    e.matrix_parent_inverse = ch.matrix_world.inverted()
    e.matrix_basis = M[n]
    bpy.context.view_layer.update()
    w = e.matrix_world
    assert (w.to_translation() - M[n].to_translation()).length < 1e-4, "%s 位置偏差" % n
    e_n = elev(w.to_3x3().normalized().col[0])
    if abs(e_n - E) >= 0.01:
        raise SystemExit(
            "%s 的朝向是 %.2f°，与基准骨骼 %.2f° 不一致。\n"
            "  两种可能：① --src 给的是**收拢态**文件（动画驱动的骨骼还在平位）；"
            "② 这些骨骼本来就不共姿态。\n"
            "  请改用**展开态**（部署好）的 blend 取坐标。" % (n, e_n, E))
    print("[骨骼] %-12s parent=Chassis  elev=%6.2f°" % (n, elev(w.to_3x3().normalized().col[0])))

# ---------- 4. 存 blend + 导出 FBX ----------
blend_out = os.path.abspath(a.blend) if a.blend else os.path.join(os.path.dirname(OUT), "rail_only.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend_out)
print("[保存] %s" % blend_out)

bpy.ops.object.select_all(action='DESELECT')
for o in bpy.data.objects:
    if o.type in ('MESH', 'EMPTY'):
        o.select_set(True)
bpy.ops.export_scene.fbx(
    filepath=OUT, use_selection=True, object_types={'MESH', 'EMPTY'},
    apply_scale_options='FBX_SCALE_UNITS', axis_forward='Y', axis_up='Z',
    use_mesh_modifiers=True, mesh_smooth_type='FACE', add_leaf_bones=False,
    path_mode='RELATIVE', embed_textures=False, bake_anim=False,
    bake_anim_use_all_bones=False, bake_anim_use_nla_strips=False,
    bake_anim_use_all_actions=False)
print("[导出] %s  %.2f KB" % (OUT, os.path.getsize(OUT) / 1024))
print("[贴图] %s  %d B" % (TEXP, os.path.getsize(TEXP)))
print("\n完成。记得在 NDF 里让 MissileCarriage.MeshDescriptor 指向这份网格的 TResourceMesh。")
