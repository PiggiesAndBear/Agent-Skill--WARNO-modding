# -*- coding: utf-8 -*-
"""验收渲染：按引擎的做法把弹体实例摆到挂点骨骼上，与地面一起渲染。

为什么需要它
------------
游戏里看到的弹是 `ProjectileModelResource` 的**实例**，挂在 `missile_N` 骨骼上；
车体网格里那份弹体（如果剥剩了一份）不参与显示。所以「本地看着没问题、
进游戏钻地」的错，只能靠按同样规则摆一遍才看得见。

红 = 按 `missile_N` 骨骼矩阵摆的实例（= 游戏里会看到的）
绿 = 按弹体几何中心摆的参照（= 应该看到的位置）
两者重合 = 挂点位置正确。

用法
----
blender -b -P scripts/render_ground.py -- \
    --src <展开态的车体 blend> \
    --missile <弹体 fbx 或 blend，原点在包围盒中心> \
    --out <输出目录> \
    [--mesh Missile_9M79] [--bone missile_1] [--ground-z 0.0]

判据（脚本会打印）：
    红/绿 的 bbox 最低点应相同，且 > 0；若红 << 绿 或红为负，说明挂点位置错了。
"""
import bpy
import sys
import os
import math
import argparse
import numpy as np
from mathutils import Vector, Matrix

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--src", required=True, help="车体 blend（展开态）")
ap.add_argument("--missile", required=True, help="弹体模型：.fbx 或 .blend")
ap.add_argument("--out", required=True, help="渲染输出目录")
ap.add_argument("--mesh", default=None, help="车体里那份弹体网格名（只用来量参照，可省）")
ap.add_argument("--bone", default="missile_1", help="挂点骨骼名")
ap.add_argument("--ground-z", type=float, default=0.0)
args = ap.parse_args(argv)

os.makedirs(args.out, exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=args.src)
sc = bpy.context.scene
sc.frame_set(0)
bpy.context.view_layer.update()

# ---------- 1. 挂点骨骼 ----------
bone = bpy.data.objects.get(args.bone)
if bone is None:
    raise SystemExit("找不到骨骼 %s —— 这个单位还没补出管骨骼？" % args.bone)
BASE = bone.matrix_world.copy()
print("[骨骼] %-10s = (%.3f, %.3f, %.3f)" % (args.bone, *BASE.to_translation()))

# 骨骼 +X 方向（引擎据此定弹轴）
bx = BASE.to_3x3().normalized().col[0]
print("[骨骼] +X 仰角 = %.2f°" % math.degrees(math.asin(max(-1, min(1, bx.z)))))

# ---------- 2. 车体里那份弹体（参照 + 轴线） ----------
ref = None
if args.mesh:
    ref = bpy.data.objects.get(args.mesh)
if ref is None:
    cands = [o for o in bpy.data.objects if o.type == 'MESH' and 'Missile' in o.name]
    ref = cands[0] if cands else None
REF_CENTER = None
if ref is not None:
    vs = np.array([[*(ref.matrix_world @ v.co)] for v in ref.data.vertices])
    ref_min = float(vs[:, 2].min())
    # 基准必须是「沿弹轴的投影中点」——不能用轴对齐包围盒中心：
    # 弹体是斜的，AABB 中心与轴向中点相差可到 0.28 m（圆点实测）。
    rc = vs.mean(axis=0)
    pr = (vs - rc) @ np.array(bx)
    REF_CENTER = Vector(rc) + bx * ((pr.min() + pr.max()) / 2)
    print("[参照] 车体里那份弹体 %s 最低点 z = %.3f，轴向中点 (%.3f, %.3f, %.3f)"
          % (ref.name, ref_min, *REF_CENTER))
    ref.hide_render = True
else:
    ref_min = None
    print("[参照] 车体里没有弹体网格，跳过参照（无法判定「应为」）")

# ---------- 3. 载入弹体模型 ----------
if args.missile.lower().endswith(".fbx"):
    bpy.ops.import_scene.fbx(filepath=args.missile)
    imported = [o for o in bpy.context.selected_objects if o.type == 'MESH']
    src = imported[0]
else:
    with bpy.data.libraries.load(args.missile) as (srclib, dstlib):
        dstlib.objects = [n for n in srclib.objects]
    cands = [o for o in dstlib.objects if o is not None]
    src = None
    for o in cands:
        if o.type == 'MESH':
            src = o
            sc.collection.objects.link(o)
            break
    assert src is not None, "弹体文件里没有网格"
src.hide_render = True

# 弹体自身包围盒（模型坐标，原点应在包围盒中心）
vv = [src.matrix_world @ v.co for v in src.data.vertices]
mn = Vector((min(v.x for v in vv), min(v.y for v in vv), min(v.z for v in vv)))
mx = Vector((max(v.x for v in vv), max(v.y for v in vv), max(v.z for v in vv)))
half_len = (mx.x - mn.x) / 2.0
print("[弹体] 模型包围盒 X[%.2f, %.2f]  半长 %.3f  原点偏移 %.3f"
      % (mn.x, mx.x, half_len, (mn.x + mx.x) / 2))


def clone(name, mtx, color):
    o = src.copy()
    # copy() 会把 hide_render 一起复制；网格也必须 copy，否则两份实例共用
    # 同一 mesh，materials.clear() 会互相清掉。
    o.hide_render = False
    o.data = src.data.copy()
    o.name = name
    sc.collection.objects.link(o)
    o.matrix_world = mtx
    m = bpy.data.materials.new(name + "_mat")
    m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    b.inputs["Base Color"].default_value = color
    b.inputs["Metallic"].default_value = 0.0
    b.inputs["Roughness"].default_value = 0.55
    o.data.materials.clear()
    o.data.materials.append(m)
    return o


# 绿：沿骨骼 X 把模型原点推到几何中心（应然）
Y = Vector((0, 1, 0))
Y = (Y - bx * Y.dot(bx)).normalized()
Z = bx.cross(Y)
R = Matrix((bx, Y, Z)).transposed().to_4x4()
# 绿 = 车体里那份弹体的包围盒中心（若没有参照，退化为骨骼自身，只表达方向）
GOOD = Matrix.Translation(REF_CENTER if REF_CENTER is not None else BASE.to_translation()) @ R
if REF_CENTER is not None:
    d = (BASE.to_translation() - REF_CENTER).length
    print("[判据] 挂点与弹体几何中心相距 %.3f m %s"
          % (d, "（合格）" if d < 0.01 else "（不合格，应 < 0.01）"))
red = clone("MIS_AS_IS", BASE, (0.75, 0.10, 0.10, 1))
grn = clone("MIS_SHOULD", GOOD, (0.15, 0.65, 0.20, 1))

for o, tag in ((red, "红=游戏实际"), (grn, "绿=应为")):
    w = [o.matrix_world @ v.co for v in o.data.vertices]
    zmin = min(v.z for v in w)
    print("  %s  bbox z[%.3f, %.3f]" % (tag, zmin, max(v.z for v in w)))
    if tag.startswith("红") and zmin < 0:
        print("     ⚠ 弹尾在地面以下 %.3f m —— 挂点位置错了" % (-zmin))

# ---------- 4. 地面、灯光、相机 ----------
bpy.ops.mesh.primitive_plane_add(size=40, location=(0, 0, args.ground_z))
gp = bpy.context.object
gm = bpy.data.materials.new("ground")
gm.use_nodes = True
gb = next(n for n in gm.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
gb.inputs["Base Color"].default_value = (0.16, 0.17, 0.15, 1)
gb.inputs["Roughness"].default_value = 0.95
gp.data.materials.append(gm)

bpy.ops.object.light_add(type='SUN', location=(6, -10, 14))
bpy.context.object.data.energy = 3.2
bpy.context.object.rotation_euler = (math.radians(52), 0, math.radians(38))
bpy.ops.object.light_add(type='AREA', location=(-4, -8, 6))
bpy.context.object.data.energy = 800
bpy.context.object.data.size = 8
bpy.context.object.rotation_euler = (math.radians(70), 0, math.radians(-20))

cam_d = bpy.data.cameras.new("cam")
cam = bpy.data.objects.new("cam", cam_d)
sc.collection.objects.link(cam)
sc.camera = cam

sc.render.engine = 'BLENDER_EEVEE'
sc.render.resolution_x = 1280
sc.render.resolution_y = 760
sc.view_settings.view_transform = 'Standard'
sc.view_settings.exposure = 0.6


def shot(name, pos, target, lens=42):
    cam.location = Vector(pos)
    d = Vector(target) - cam.location
    cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    cam_d.lens = lens
    sc.render.filepath = os.path.join(args.out, name + ".png")
    bpy.ops.render.render(write_still=True)
    print("  [渲染] %s" % sc.render.filepath)


p = BASE.to_translation()
shot("g_side", (p.x + 2, p.y - 26, 5.2), (p.x + 2, p.y, 3.6))
shot("g_rear34", (p.x - 12, p.y - 18, 7.5), (p.x + 0.5, p.y, 3.0))
shot("g_tail", (p.x - 5, p.y - 11, 2.2), (p.x, p.y, 1.0), 60)
