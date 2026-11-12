# -*- coding: utf-8 -*-
"""给 Rail 挂架网格补 as_N_M 硬点组（TMissileCarriageConnoisseur 的加载期硬校验要求）。

背景
----
引擎报错：
  Error in weapon carriage for model '...Rail.fbx':
  Not enough hardpoint groups : missile system needs 1 hardpoint groups,
  model has 0 'as' and 'aa' hardpoint groups combined.

=> 挂架网格里必须有 `as_{武器槽}_{硬点序号}` 空物体。`missile_N` 是「可见弹体」用的，
   不参与这项校验。

做法
----
读回已烘好的 Rail FBX → 以 `missile_1` 的世界矩阵为准建 `as_1_1`（同在出管轴、同朝向）
→ 原样导出（保留原导出参数，贴图引用不变）。

用法
----
blender -b -P add_hardpoint_rail.py -- --in <Rail.fbx> [--out <Rail.fbx>] [--count 1]
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
ap.add_argument("--in", dest="src", required=True)
ap.add_argument("--out", dest="out", default=None)
ap.add_argument("--count", type=int, default=1, help="组 1 里要几个硬点（as_1_1..as_1_N）")
ap.add_argument("--spacing", type=float, default=0.06, help="多硬点时沿出管轴的间距 m")
a = ap.parse_args(argv)

SRC = os.path.abspath(a.src)
OUT = os.path.abspath(a.out or a.src)


def elev(v):
    return math.degrees(math.asin(max(-1.0, min(1.0, v.z))))


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=SRC)
sc = bpy.context.scene
bpy.context.view_layer.update()

print("== 导入 %s" % os.path.basename(SRC))
for o in sorted(bpy.data.objects, key=lambda x: x.name):
    m = o.matrix_world
    p = m.to_translation()
    ax = m.to_3x3().normalized().col[0]
    print("  %-12s %-6s pos=(%8.3f,%8.3f,%8.3f)  +X elev=%6.2f°  parent=%s"
          % (o.name, o.type, p.x, p.y, p.z, elev(ax), o.parent.name if o.parent else "-"))

ch = bpy.data.objects.get("Chassis")
assert ch is not None, "找不到 Chassis"
ref = bpy.data.objects.get("missile_1") or bpy.data.objects.get("canon_01")
assert ref is not None, "找不到 missile_1 / canon_01 作为硬点姿态参考"

POS = ref.matrix_world.to_translation()
ROT = ref.matrix_world.to_quaternion().to_matrix().to_4x4()
AX = (ROT @ Vector((1, 0, 0))).normalized()
print("\n参考 %s：pos=(%.3f,%.3f,%.3f) 出管仰角 %.2f°" % (ref.name, POS.x, POS.y, POS.z, elev(AX)))

for i in range(1, a.count + 1):
    name = "as_1_%d" % i
    old = bpy.data.objects.get(name)
    if old:
        bpy.data.objects.remove(old, do_unlink=True)
    e = bpy.data.objects.new(name, None)
    e.empty_display_type = 'PLAIN_AXES'
    e.empty_display_size = 0.2
    sc.collection.objects.link(e)
    e.parent = ch
    e.matrix_parent_inverse = ch.matrix_world.inverted()
    e.matrix_basis = Matrix.Translation(POS + AX * (a.spacing * (i - 1))) @ ROT
    bpy.context.view_layer.update()
    w = e.matrix_world
    assert (w.to_translation() - (POS + AX * (a.spacing * (i - 1)))).length < 1e-4
    print("[硬点] %-8s pos=(%8.3f,%8.3f,%8.3f)  elev=%6.2f°  parent=Chassis"
          % (name, w.to_translation().x, w.to_translation().y, w.to_translation().z,
             elev(w.to_3x3().normalized().col[0])))

bpy.ops.object.select_all(action='DESELECT')
for o in bpy.data.objects:
    if o.type in ('MESH', 'EMPTY'):
        o.select_set(True)
bpy.context.view_layer.objects.active = ch

bpy.ops.export_scene.fbx(
    filepath=OUT, use_selection=True, object_types={'MESH', 'EMPTY'},
    apply_scale_options='FBX_SCALE_UNITS', axis_forward='Y', axis_up='Z',
    use_mesh_modifiers=True, mesh_smooth_type='FACE', add_leaf_bones=False,
    path_mode='RELATIVE', embed_textures=False, bake_anim=False,
    bake_anim_use_all_bones=False, bake_anim_use_nla_strips=False,
    bake_anim_use_all_actions=False)
print("\n[导出] %s  %d B" % (OUT, os.path.getsize(OUT)))
