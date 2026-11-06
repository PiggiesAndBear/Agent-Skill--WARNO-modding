# -*- coding: utf-8 -*-
"""判定履带 UV 的「走向轴」是 U 还是 V（只读）。

为什么需要：引擎绑的履带 shader 只滚一个轴，滚错轴会让履带横向滑动。
判据不能看 UV 范围（走向/宽度都铺满 0..1），要看：
  **同一 X（车长位置）上，Y 最小与最大的两个顶点，ΔU 与 ΔV 谁更大**——
  变化大的那个轴是宽度轴，另一个才是走向轴。

官方 M1_Abrams 实测：宽度轴 U、走向轴 V。源模型常是反的。

用法:
  blender -b <blend> -P track_uv_axis.py -- [履带对象名]
  （不给对象名时自动找名字含 chenille / track 的网格）

输出末尾的 “⇒ 宽度轴 X，走向轴 Y”，与官方对比即可。
"""
import bpy, sys

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
target = args[0] if args else None

objs = [o for o in bpy.data.objects if o.type == 'MESH' and target and o.name == target]
if not objs:
    objs = [o for o in bpy.data.objects if o.type == 'MESH'
            and ('henille' in o.name or 'rack' in o.name.lower())]
if not objs:
    print("[中止] 没找到履带网格，请显式给对象名")
    raise SystemExit(1)

for ob in objs:
    me = ob.data
    if not me.uv_layers:
        print("[%s] 没有 UV" % ob.name)
        continue
    uvl = me.uv_layers.active
    mw = ob.matrix_world

    vmap = {}
    for p in me.polygons:
        for li in p.loop_indices:
            vmap.setdefault(me.loops[li].vertex_index, uvl.data[li].uv.copy())
    pts = [(mw @ me.vertices[i].co, vmap[i]) for i in vmap if i < len(me.vertices)]
    if len(pts) < 8:
        print("[%s] 顶点太少，跳过" % ob.name)
        continue

    ys = [p[0].y for p in pts]
    print("\n[%s] 顶点 %d  Y %.2f..%.2f（宽 %.2f）材质 %s"
          % (ob.name, len(pts), min(ys), max(ys), max(ys) - min(ys),
             [s.material.name for s in ob.material_slots if s.material]))

    xs = sorted(set(round(p[0].x, 2) for p in pts))
    mid_x = xs[len(xs) // 2]
    band = [p for p in pts if abs(p[0].x - mid_x) <= 0.25]
    if len(band) < 2:
        band = pts
    a = min(band, key=lambda p: p[0].y)
    b = max(band, key=lambda p: p[0].y)
    du = abs(b[1][0] - a[1][0])
    dv = abs(b[1][1] - a[1][1])
    print("  同一 X≈%.2f：Y %.2f→%.2f  |ΔU|=%.3f  |ΔV|=%.3f" % (
        mid_x, a[0].y, b[0].y, du, dv))
    width = "U" if du > dv else "V"
    print("  ⇒ 宽度轴 %s，走向轴 = %s" % (width, "V" if width == "U" else "U"))
    print("  参考：官方 M1_Abrams 宽度轴 U、走向轴 V。走向轴不一致 → 要 UV 转置 + 贴图转置（法线图 RG 互换）")

print("\nTRACK_UV_AXIS_DONE")
