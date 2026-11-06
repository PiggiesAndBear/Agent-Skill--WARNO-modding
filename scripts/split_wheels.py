# -*- coding: utf-8 -*-
"""拆轮：把合并进 Chassis 的轮子拆成引擎认的「空物体 + 网格子节点」，轮心为原点。

【原理】
----
引擎**按名字拼节点**去找轮子（`WARNO.exe` 里的格式串：`roue_%1` / `roue_d%1` / `roue_g%1` /
`roue_elev_d%1` / `roue_elev_g%1`），旋转的是**名为 `roue_elev_*` 的空物体**，网格必须挂在它下面。
所以三件事缺一不可：

1. 轮子是**独立网格节点**（合并进 Chassis 的轮子永远不转，且编译、加载零报错）；
2. 顶层是一个**同名 `roue_elev_{g|d}{n}` 空物体**，位置 = 轮心；
3. 网格是它的**子节点**，局部变换为 0（`matrix_parent_inverse = 父的逆`，`matrix_world = 轮心平移`）。

官方两种写法都成立：`M1_Abrams.fbx`（履带）是 `Roue_Elev_D1`(Null) → `Roue_D1`(Mesh)；
`GAZ_66B.fbx`（轮式）是 `Roue_Gauche_01` 直接 Mesh、原点在轮心。本脚本输出前者（更保险，
因为引擎转的是空物体，网格跟着走不依赖额外逻辑）。

【判据】轮子壳 = 焊接后一个连通块，满足（**取并集**）：
  a) 含轮子材质面片  —— 主判据；
  b) 纯圆盘几何      —— 兜底，因为**诱导轮常常复用车身暗色材质、没有轮材质**
                        （M752 实测：14 只轮子里有 2 只只用了 `M752_dark`，
                         只按材质筛会漏掉车尾，且不报错）。

(b) 的阈值**不写死**：先由 (a) 找到的轮子统计中位直径 / 厚度 / |y| / z，
再用 ±40% 之类相对区间收窄。找不到材质轮时才回退到 `--dia/--max-thick` 显式值。

【操作】
----
  blender -b -P split_wheels.py -- --blend <rig.blend> [--chassis Chassis] [--dry]

  常用覆盖：
    --wheel-mat M752_wheel        指定轮材质（可多次；缺省按名字含 wheel/roue/tire/... 自动找）
    --expect 14                   期望轮子数，不符即失败
    --front +x                    车头方向（决定 1 号是哪一头）
    --left +y                     车左方向（+y→g（gauche），另一侧 d（droite））
    --dia 0.50 0.85               圆盘判据的直径区间（不给则自动推）
    --max-thick 0.32              圆盘判据的厚度上限
    --min-abs-y 0.9               圆盘判据的 |y| 下限（离车身中线足够远）

【验收】
----
1. 脚本末尾打印 `新增轮子 N 只` 与 `Chassis 剩余 verts/polys`；
2. 拆完**必须重烘 deploy/fold 动画**（加了节点，帧节点表对不上会 `Skeleton mismatch`）；
3. 导 FBX 后用 `fbx_anchors.py dump` 确认 `roue_elev_*` 是 Null、`roue_*` 是其子 Mesh；
4. 进游戏开起来看轮子是否转（这是唯一终审）。
"""
import bpy
import bmesh
import sys
import os
import shutil
import time
import argparse
import statistics
from mathutils import Vector, Matrix

WHEEL_HINTS = ("wheel", "roue", "tire", "tyre", "pneu", "jante", "rim")


def argv_after_ddash():
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1:]
    return []


def parse_args():
    p = argparse.ArgumentParser(
        prog="split_wheels.py",
        description="把合并进车体的轮子拆成 roue_elev_*(空物体) + roue_*(网格子节点)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--blend", required=True, help="车辆绑定 .blend（原地修改，写前自动备份）")
    p.add_argument("--chassis", default="Chassis", help="车体对象名（默认 Chassis）")
    p.add_argument("--wheel-mat", action="append", default=[],
                   help="轮子材质名，可多次；缺省按名字含 wheel/roue/tire... 自动找")
    p.add_argument("--expect", type=int, default=0, help="期望轮子数，0=不校验")
    p.add_argument("--front", choices=["+x", "-x"], default="+x", help="车头方向（默认 +x）")
    p.add_argument("--left", choices=["+y", "-y"], default="+y", help="车左方向（默认 +y）")
    p.add_argument("--weld", type=float, default=1e-4, help="焊接容差（默认 1e-4）")
    p.add_argument("--dia", type=float, nargs=2, default=None, metavar=("LO", "HI"),
                   help="圆盘判据直径区间；不给则从材质轮自动推")
    p.add_argument("--max-thick", type=float, default=None, help="圆盘判据厚度上限")
    p.add_argument("--min-abs-y", type=float, default=None, help="圆盘判据 |y| 下限")
    p.add_argument("--disc-tol", type=float, default=0.08, help="圆盘 x/z 尺寸差容差比例（默认 0.08）")
    p.add_argument("--dry", action="store_true", help="只报告，不写盘")
    p.add_argument("--no-backup", action="store_true", help="不写 .bak 备份")
    return p.parse_args(argv_after_ddash())


def main():
    a = parse_args()
    blend = os.path.abspath(a.blend)
    if not os.path.isfile(blend):
        sys.exit("[错误] 找不到 %s" % blend)
    bpy.ops.wm.open_mainfile(filepath=blend)
    sc = bpy.context.scene

    ch = bpy.data.objects.get(a.chassis)
    if ch is None or ch.type != 'MESH':
        sys.exit("[错误] 没有网格对象 %r" % a.chassis)
    me = ch.data
    mats = list(me.materials)
    n_poly0 = len(me.polygons)

    # 守卫：已经拆过就别再拆一次（重复拆会二次删面，且不一定报错）
    pre = [o.name for o in bpy.data.objects if o.name.startswith("roue_elev_")]
    if pre:
        sys.exit("[错误] 本文件已有 %d 个 roue_elev_*（%s ...），疑似已拆过轮子。\n"
                 "        如需重来，请先恢复 .bak_wheels_*.blend，再加 --dry 复核判据。"
                 % (len(pre), ", ".join(sorted(pre)[:4])))
    # 提示：模型自带的扬尘锚点常叫 roue_gauche_01 / roue_droite_01，别与本脚本的
    # roue_{g|d}{n} 混淆（前者是空物体，只提供 fx 挂点位置）
    anchors = [o.name for o in bpy.data.objects
               if o.type == 'EMPTY' and "roue" in o.name.lower() and o.name not in pre]
    if anchors:
        print("[提示] 模型自带轮位锚点 %d 个（%s），保持不动"
              % (len(anchors), ", ".join(sorted(anchors)[:4])))

    # ---------- 1. 焊接 + 连通块 ----------
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    parent = {v: v for v in bm.verts}

    def find(v):
        while parent[v] is not v:
            parent[v] = parent[parent[v]]
            v = parent[v]
        return v

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx is not ry:
            parent[ry] = rx

    q = max(a.weld, 1e-9)
    qd = {}
    for v in bm.verts:
        k = (round(v.co.x / q), round(v.co.y / q), round(v.co.z / q))
        if k in qd:
            union(v, qd[k])
        else:
            qd[k] = v
    for e in bm.edges:
        union(e.verts[0], e.verts[1])

    shells = {}
    for f in bm.faces:
        shells.setdefault(find(f.verts[0]), []).append(f)
    print("[壳] 焊接容差 %.1e → 连通块 %d 个" % (q, len(shells)))

    # ---------- 2. 材质判据 ----------
    want = list(a.wheel_mat)
    if not want:
        want = [m.name for m in mats if m and any(h in m.name.lower() for h in WHEEL_HINTS)]
        if want:
            print("[材质] 自动识别轮材质：%s" % ", ".join(sorted(set(want))))
        else:
            print("[材质] 自动识别失败（没有名字像轮子的材质），只走圆盘判据")
    mi_set = {i for i, m in enumerate(mats) if m and m.name in want}

    # ---------- 3. 逐壳量包围盒，先按材质取基准轮 ----------
    def shell_geo(faces):
        vids = {v for f in faces for v in f.verts}
        mn = Vector((min(v.co.x for v in vids), min(v.co.y for v in vids), min(v.co.z for v in vids)))
        mx = Vector((max(v.co.x for v in vids), max(v.co.y for v in vids), max(v.co.z for v in vids)))
        return (mn + mx) * 0.5, mx - mn

    geos = {}
    for root, faces in shells.items():
        geos[root] = shell_geo(faces) + (faces,)

    bases = [g for root, g in geos.items() if any(f.material_index in mi_set for f in g[2])]
    print("[基准] 材质轮 %d 只" % len(bases))

    # 圆盘判据阈值：优先命令行 > 自动推 > 内置兜底
    if a.dia:
        dia_lo, dia_hi = a.dia
    elif bases:
        dm = statistics.median([max(g[1].x, g[1].z) for g in bases])
        dia_lo, dia_hi = dm * 0.55, dm * 1.45
    else:
        dia_lo, dia_hi = 0.30, 1.20

    if a.max_thick is not None:
        thick_max = a.max_thick
    elif bases:
        thick_max = statistics.median([g[1].y for g in bases]) * 1.6
    else:
        thick_max = 0.40

    if a.min_abs_y is not None:
        y_min = a.min_abs_y
    elif bases:
        y_min = statistics.median([abs(g[0].y) for g in bases]) * 0.5
    else:
        y_min = 0.0

    if bases:
        z_max = statistics.median([g[0].z for g in bases]) + max(0.35, thick_max)
    else:
        z_max = 1.10

    print("[判据] 圆盘：厚<%.3f  |y|>%.3f  直径 %.3f..%.3f  x/z差<%.0f%%  中心z<%.3f"
          % (thick_max, y_min, dia_lo, dia_hi, a.disc_tol * 100, z_max))

    # ---------- 4. 取并集 ----------
    wheels = []
    for root, (c, s, faces) in geos.items():
        has_mat = any(f.material_index in mi_set for f in faces) if mi_set else False
        dia = max(s.x, s.z)
        disc = (s.y < thick_max
                and abs(c.y) > y_min
                and dia_lo < dia < dia_hi
                and abs(s.x - s.z) < a.disc_tol * dia
                and c.z < z_max)
        if not (has_mat or disc):
            continue
        wheels.append(dict(faces=faces, c=c, s=s, dia=dia, mat=has_mat, disc=disc))

    print("[结果] 轮子壳 %d 只（材质 %d / 仅圆盘 %d）"
          % (len(wheels), sum(w["mat"] for w in wheels), sum(1 for w in wheels if w["disc"] and not w["mat"])))

    if not wheels:
        sys.exit("[错误] 一只轮子都没找到。检查 --chassis / --wheel-mat，或显式给 --dia/--max-thick/--min-abs-y")
    if a.expect and len(wheels) != a.expect:
        sys.exit("[错误] 轮子数 %d ≠ 期望 %d。多半是漏了诱导轮（无轮材质），"
                 "用 --dia/--max-thick 放宽圆盘判据，或补 --wheel-mat" % (len(wheels), a.expect))

    # ---------- 5. 编号 ----------
    sx = 1.0 if a.front == "+x" else -1.0
    y_left_positive = (a.left == "+y")
    for w in wheels:
        is_left = (w["c"].y > 0) if y_left_positive else (w["c"].y < 0)
        w["side"] = "g" if is_left else "d"
    for side in ("g", "d"):
        grp = sorted([w for w in wheels if w["side"] == side], key=lambda w: -sx * w["c"].x)
        for n, w in enumerate(grp, start=1):
            w["n"] = n
            print("   roue_%s%-2d 轮心=(%7.3f,%7.3f,%6.3f)  直径≈%.3f  宽%.3f  %s"
                  % (side, n, w["c"].x, w["c"].y, w["c"].z, w["dia"], w["s"].y,
                     "材质" if w["mat"] else "圆盘"))

    if a.dry:
        print("[dry] 未写盘。以上为将要拆出的 %d 只。" % len(wheels))
        return

    # ---------- 6. 逐只拆出 ----------
    uv_layer = bm.loops.layers.uv.active
    created = []

    def extract(faces, name):
        nbm = bmesh.new()
        vmap = {}
        nuv = nbm.loops.layers.uv.new("UVMap") if uv_layer else None
        for f in faces:
            nvs = []
            for v in f.verts:
                nv = vmap.get(v)
                if nv is None:
                    nv = nbm.verts.new(v.co.copy())
                    vmap[v] = nv
                nvs.append(nv)
            try:
                nf = nbm.faces.new(nvs)
            except ValueError:
                continue
            nf.material_index = f.material_index
            nf.smooth = f.smooth
            if nuv:
                for lo_old, lo_new in zip(f.loops, nf.loops):
                    lo_new[nuv].uv = lo_old[uv_layer].uv
        nme = bpy.data.meshes.new(name)
        nbm.to_mesh(nme)
        nbm.free()
        for m in mats:
            nme.materials.append(m)
        o = bpy.data.objects.new(name, nme)
        sc.collection.objects.link(o)
        return o

    for w in wheels:
        mname = "roue_%s%d" % (w["side"], w["n"])
        ename = "roue_elev_%s%d" % (w["side"], w["n"])
        c = w["c"]

        o = extract(w["faces"], mname)

        e = bpy.data.objects.get(ename)
        if e is None:
            e = bpy.data.objects.new(ename, None)
            e.empty_display_type = 'PLAIN_AXES'
            e.empty_display_size = 0.2
            sc.collection.objects.link(e)
        e.parent = ch
        e.matrix_parent_inverse = ch.matrix_world.inverted()
        e.matrix_world = Matrix.Translation(c)
        bpy.context.view_layer.update()

        # 网格：数据以原点为中心化（顶点 = 原坐标 − 轮心），然后
        # parent_inverse = Identity、world = 轮心平移 → 局部变换正好是单位阵。
        # 这是官方 M1 的契约写法（`Roue_D1` 的 local location 为 0）。
        # 若沿用 `matrix_parent_inverse = 父的逆`，世界位置同样对、旋转中心也对，
        # 但 local location 会等于轮心坐标，与官方惯例不符，后人核对时容易误判。
        o.data.transform(Matrix.Translation(-c))
        o.parent = e
        o.matrix_parent_inverse = Matrix.Identity(4)
        o.matrix_world = Matrix.Translation(c)
        bpy.context.view_layer.update()

        d1 = (o.matrix_world.to_translation() - c).length
        d2 = (o.matrix_world.to_translation() - e.matrix_world.to_translation()).length
        d3 = o.location.length
        if max(d1, d2) > 1e-4 or d3 > 1e-4:
            sys.exit("[错误] %s 落位异常：世界偏移 %.5f / 与轮心差 %.5f / 局部 location %.5f"
                     % (mname, d1, d2, d3))
        created.append(o)

    # ---------- 7. 从 Chassis 删面 ----------
    dead = [f for w in wheels for f in w["faces"]]
    bmesh.ops.delete(bm, geom=dead, context='FACES')
    bm.to_mesh(me)
    bm.free()
    me.update()
    print("[Chassis] %d → %d 面（删掉 %d）" % (n_poly0, len(me.polygons), len(dead)))
    if len(me.polygons) < n_poly0 * 0.5:
        sys.exit("[错误] Chassis 面数掉了一半以上，圆盘判据可能吃掉了车体件。先用 --dry 看清单")

    # ---------- 8. 保存 ----------
    if not a.no_backup:
        bak = os.path.splitext(blend)[0] + ".bak_wheels_%s.blend" % time.strftime("%H%M%S")
        shutil.copy2(blend, bak)
        print("[备份] %s" % bak)
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    print("[完成] 新增轮子 %d 只：%s" % (len(created), ", ".join(o.name for o in created)))
    print("[必做] 重烘 deploy/fold 动画，否则 Skeleton mismatch")


if __name__ == "__main__":
    main()
