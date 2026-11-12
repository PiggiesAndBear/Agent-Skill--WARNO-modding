# -*- coding: utf-8 -*-
"""卡面渲染（Blender 脚本）：baked blend → 512×288 透明底 PNG（兵牌两段式的第一段）。

流程 = render_card.py（本脚本，透明底）→ card_composite.py（PIL，深色渐变合成）
     → set_card_art.py（注册 token + 单位引用）。三步各自幂等，见 20-unit-authoring.md §2.5。

取景是自动的：把所有网格顶点投到相机空间量 min/max 再算 ortho_scale，
不手调数值。两个实测坑都已内置：
- `ortho_scale` 是**水平可见宽度**（不是垂直高度），按垂直算会把车头/炮口切掉（2S25 实测）；
- 天线等细高部件会把画幅撑高、车体被压小（LAV-600 实测：车体 67% 宽，正常应 81%），
  用 --trim-z 剔除超过某高度的天线顶点（天线高出画幅顶部属正常裁切）。

用法：
  blender -b <baked.blend> -P render_card.py -- --out card_raw.png [--trim-z 3.15]
      [--view 1,-1,0.52] [--margin 1.10] [--res 512x288]

产物：RGBA 透明底 PNG。**不要直接把它当卡面交出去**——透明底与其它单位风格不一致，
必须过 card_composite.py 合成深色渐变底。
"""
import argparse
import os
import sys

import bpy
from mathutils import Vector

# 相对输出路径会掉到盘符根（Blender 坑），先转绝对
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
p = argparse.ArgumentParser()
p.add_argument("--out", default="card_raw.png")
p.add_argument("--trim-z", type=float, default=0.0,
               help="取景只统计 z <= 此值的顶点（剔除天线尖）；0 = 不剔除")
p.add_argument("--view", default="1,-1,0.52", help="相机方向（车头 +X 约定下的 3/4 前左上）")
p.add_argument("--margin", type=float, default=1.10, help="取景余量（1.0 = 贴边）")
p.add_argument("--res", default="512x288")
a = p.parse_args(argv)

OUT = os.path.abspath(a.out)
RES_X, RES_Y = (int(v) for v in a.res.lower().split("x"))
MARGIN = a.margin
TRIM_Z = a.trim_z

scene = bpy.context.scene

# ---------------- 清场：去掉旧相机与灯 ----------------
for ob in list(bpy.data.objects):
    if ob.type in {'CAMERA', 'LIGHT'}:
        bpy.data.objects.remove(ob, do_unlink=True)

# ---------------- 包围盒（只算网格） ----------------
pts = []
for ob in bpy.data.objects:
    if ob.type != 'MESH':
        continue
    mw = ob.matrix_world
    for v in ob.data.vertices:
        pts.append(mw @ v.co)
if TRIM_Z > 0:
    fpts = [q for q in pts if q.z <= TRIM_Z]
    print("[card] 取景顶点 %d / %d（z <= %.2f）" % (len(fpts), len(pts), TRIM_Z))
else:
    fpts = pts
if not fpts:
    sys.exit("[card] 没有可取景的顶点（TRIM_Z 切太高了？）")

lo = Vector((min(q.x for q in fpts), min(q.y for q in fpts), min(q.z for q in fpts)))
hi = Vector((max(q.x for q in fpts), max(q.y for q in fpts), max(q.z for q in fpts)))
CENTER = Vector(((lo.x + hi.x) / 2, 0.0, (lo.z + hi.z) / 2))
print("[card] bbox %s .. %s" % ([round(x, 2) for x in lo], [round(x, 2) for x in hi]))

# ---------------- 世界：近黑（透明底渲染时只影响反射） ----------------
w = bpy.data.worlds.new("CardWorld")
scene.world = w
w.use_nodes = True
bg = w.node_tree.nodes.get("Background")
if bg is None:
    bg = w.node_tree.nodes.new('ShaderNodeBackground')
    outn = w.node_tree.nodes.get("World Output") or w.node_tree.nodes.new('ShaderNodeOutputWorld')
    w.node_tree.links.new(bg.outputs['Background'], outn.inputs['Surface'])
bg.inputs[0].default_value = (0.012, 0.015, 0.022, 1.0)
bg.inputs[1].default_value = 1.0

# ---------------- 相机：正交 + 自动取景 ----------------
DIR = Vector(tuple(float(v) for v in a.view.split(","))).normalized()
DIST = 30.0

cd = bpy.data.cameras.new("CardCam")
cd.type = 'ORTHO'
cam = bpy.data.objects.new("CardCam", cd)
scene.collection.objects.link(cam)
cam.location = CENTER + DIR * DIST
cam.rotation_euler = (CENTER - cam.location).to_track_quat('-Z', 'Y').to_euler()
scene.camera = cam
bpy.context.view_layer.update()

inv = cam.matrix_world.normalized().inverted()
cpts = [inv @ q for q in fpts]
xs = [q.x for q in cpts]
ys = [q.y for q in cpts]
half_w = (max(xs) - min(xs)) / 2.0
half_h = (max(ys) - min(ys)) / 2.0
aspect = RES_X / float(RES_Y)
# ortho_scale = 水平可见宽度：宽高比换算必须在「投影后的真实宽高」上做
ortho_w = 2.0 * max(half_w, half_h * aspect) * MARGIN
cd.ortho_scale = ortho_w
# 投影中心不在相机轴上 → 沿相机本地 X/Y 平移归中
cx = (max(xs) + min(xs)) / 2.0
cy = (max(ys) + min(ys)) / 2.0
cam.location = cam.location + cam.matrix_world.to_3x3() @ Vector((cx, cy, 0.0))
bpy.context.view_layer.update()
print("[card] 投影半宽 %.2f 半高 %.2f → ortho_scale = %.3f（画幅 %.2f）"
      % (half_w, half_h, ortho_w, aspect))

# ---------------- 三点布光（PT100/2S25/LAV600 实测同一套） ----------------
def area(name, loc, energy, size_m, color=(1, 1, 1)):
    d = bpy.data.lights.new(name, 'AREA')
    d.energy = energy
    d.size = size_m
    d.color = color
    o = bpy.data.objects.new(name, d)
    scene.collection.objects.link(o)
    o.location = loc
    o.rotation_euler = (CENTER - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()

area("Key",  CENTER + Vector((6.0, -6.0, 6.0)), 2400, 8.0, (1.0, 0.96, 0.90))
area("Fill", CENTER + Vector((3.0, 7.0, 2.5)), 650, 9.0, (0.72, 0.80, 1.0))
area("Rim",  CENTER + Vector((-7.0, 2.5, 5.0)), 1300, 7.0, (0.85, 0.90, 1.0))
area("Top",  CENTER + Vector((0.0, 0.0, 8.0)), 450, 10.0, (1.0, 1.0, 1.0))

# ---------------- 渲染（EEVEE，透明底，Standard 变换） ----------------
for e in ('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE'):
    try:
        scene.render.engine = e
        break
    except Exception:
        continue
print("[card] engine = %s" % scene.render.engine)
scene.render.resolution_x, scene.render.resolution_y = RES_X, RES_Y
scene.render.resolution_percentage = 100
scene.render.film_transparent = True
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGBA'
scene.view_settings.view_transform = 'Standard'
scene.view_settings.look = 'None'
try:
    scene.eevee.taa_render_samples = 128
    scene.eevee.use_raytracing = True
    scene.eevee.use_shadows = True
except Exception as e:
    print("  eevee 参数提示：", e)

scene.render.filepath = OUT
bpy.ops.render.render(write_still=True)
print("[card] %s  %d B" % (OUT, os.path.getsize(OUT)))
