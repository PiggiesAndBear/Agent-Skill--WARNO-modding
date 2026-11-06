"""多姿态 × 多机位带材质渲染：用来判断「装上去对不对」。

为什么需要它：形态类问题（贴不贴合、有没有露内腔、翘边、穿模）**数值算不出来**，
而单色 Workbench 会把单层曲面的背面渲成黑色，容易被误判成"空腔"。
所以判形态一律用带材质渲染，且至少三个机位（正视 / 斜前 / 斜下后）。

用法（Blender 脚本）：

    blender -b -P pose_render.py -- <model.fbx|model.blend> <outdir> \
        [--poses poses.json] [--views views.json] [--samples 20] [--res 900x700] \
        [--engine CYCLES|WORKBENCH]

poses.json（键=姿态名，值=对象名 → 变换；角度是**度**，写的是 Blender 的 rotation_euler）

    {
      "rest":   {},
      "folded": {
        "Roue_Gauche":    {"rot": [-120, 0, 0]},
        "Roue_Droite":    {"rot": [ 120, 0, 0]},
        "Roue_Arriere":   {"loc": [-5.10, 0.0, 1.50]},
        "Spatule_Gauche": {"rot": [ -60, 0, 0]}
      }
    }

  ⚠ **引擎的 `TBoneProceduralAnimation` 绕 X 方向与 Blender 的 rotation_euler 相反**
    （本项目实测两次）。所以这里写的是"Blender 侧姿态"：想预览引擎的 +120，这里要写 -120。

views.json（键=机位名）

    {
      "front": {"eye": [6.4, 2.7, 1.28], "target": [2.75, 1.05, 1.18], "lens": 105},
      "side":  {"eye": [2.6, 9.0, 1.2],  "target": [2.6, 1.0, 1.2],  "ortho": 3.0}
    }

  `lens` = 透视焦距；`ortho` = 正交视野高度（给一个就切正交）。两者都不给则用 lens=60。

不给 --poses / --views 时用内置的最小组合（rest + 三个通用机位），只为验证脚本能跑。

-------------------------------------------------------------------- 扫掠模式
起竖/收拢类问题**不能只看两个端点**：中段（20–40%）才是弹体擦车顶的高发段。
所以另给一条「扫掠」通道，把一个连续过程拆成若干采样点，每个点同时给
**数值判据**（BVH 最近距离 + 表面相交对数）和**出图**：

    # 扫进度：固定收拢参数，看 t=0..1 全过程
    blender -b -P pose_render.py -- <rig.blend> <outdir> \
        --sweep-progress 0.2,0.35,0.5,0.65,0.8,1.0 \
        --arm Canon_01 --chassis Chassis --probe Missile_9M79 \
        --lift 0.35 --fwd 0.45 --stow-lift 0.34 --stow-nose-up 0

    # 扫角度：固定终点抬升，只变行军抬头角（一次只改一个变量）
    blender -b -P pose_render.py -- <rig.blend> <outdir> \
        --sweep-angle 10,8,6,4,2,0 --probe Missile_9M79 --stow-lift 0.34

  折叠角**从几何解**（铰点 → 臂上离铰点最远的顶点），与 `bake_deploy_fold.py`
  同一算法 —— 两边不一致会导致「预览的收拢态」和「实际烘焙的动画终点」对不上。

  ⚠ 判据怎么读：
    · **最近距离** 是主判据，越大越安全；但「完全陷进车体里」时最近距离会变小
      而不是变大，所以要同时看 **相交对数**（>0 就是穿模）。
    · 相交对数 = 0 **不代表没问题**（弹体整个埋进车体时面片可能一个都不交）。
      所以最终必须**看渲染图**，数值只用来定位可疑的 t。

  ⚠ 射线奇偶法（`ray_cast` 数穿过次数）对**非闭合网格**会整段误报 ——
    车体是开放网格，本项目实测 151/151 帧全报「穿模」。只用 BVH 面片判据。
"""
import bpy
import json
import math
import os
import sys
from mathutils import Vector
from mathutils.bvhtree import BVHTree

DEG = math.pi / 180.0
AXIS_IDX = {"X": 0, "Y": 1, "Z": 2}
# 绕某轴旋转时的「旋转平面」两个分量（与 bake_deploy_fold.py 同一张表）
PLANE = {"Y": (0, 2), "Z": (0, 1), "X": (1, 2)}


def die(msg):
    print("[!] " + msg)
    sys.exit(2)


def parse_args():
    argv = sys.argv
    if "--" not in argv:
        die("参数要放在 -- 之后")
    a = argv[argv.index("--") + 1:]
    o = {"model": None, "out": None, "poses": None, "views": None,
         "samples": 20, "res": "900x700", "engine": "CYCLES",
         # ---- 扫掠模式 ----
         "sweep_progress": None, "sweep_angle": None,
         "arm": "Canon_01", "chassis": "Chassis", "hinge": None,
         "axis": "Y", "probe": "",
         "lift": 0.35, "fwd": 0.45, "stow_lift": 0.34, "stow_nose_up": 0.0}
    i = 0
    while i < len(a):
        if a[i] == "--poses":
            o["poses"] = a[i + 1]; i += 2
        elif a[i] == "--views":
            o["views"] = a[i + 1]; i += 2
        elif a[i] == "--samples":
            o["samples"] = int(a[i + 1]); i += 2
        elif a[i] == "--res":
            o["res"] = a[i + 1]; i += 2
        elif a[i] == "--engine":
            o["engine"] = a[i + 1].upper(); i += 2
        elif a[i] == "--sweep-progress":
            o["sweep_progress"] = [float(x) for x in a[i + 1].split(",") if x.strip()]; i += 2
        elif a[i] == "--sweep-angle":
            o["sweep_angle"] = [float(x) for x in a[i + 1].split(",") if x.strip()]; i += 2
        elif a[i] == "--arm":
            o["arm"] = a[i + 1]; i += 2
        elif a[i] == "--chassis":
            o["chassis"] = a[i + 1]; i += 2
        elif a[i] == "--hinge":
            o["hinge"] = [float(x) for x in a[i + 1].split(",")]; i += 2
        elif a[i] == "--axis":
            o["axis"] = a[i + 1].upper(); i += 2
        elif a[i] == "--probe":
            o["probe"] = a[i + 1]; i += 2
        elif a[i] == "--lift":
            o["lift"] = float(a[i + 1]); i += 2
        elif a[i] == "--fwd":
            o["fwd"] = float(a[i + 1]); i += 2
        elif a[i] == "--stow-lift":
            o["stow_lift"] = float(a[i + 1]); i += 2
        elif a[i] == "--stow-nose-up":
            o["stow_nose_up"] = float(a[i + 1]); i += 2
        elif a[i].startswith("--"):
            die("未知参数 " + a[i])
        elif o["model"] is None:
            o["model"] = a[i]; i += 1
        elif o["out"] is None:
            o["out"] = a[i]; i += 1
        else:
            die("多余参数 " + a[i])
    if not o["model"] or not o["out"]:
        die("用法: pose_render.py -- <model> <outdir> [...]")
    return o


DEFAULT_VIEWS = {
    "q34":   {"eye": [9.0, 6.5, 3.2], "target": [0.0, 0.0, 1.6], "lens": 55},
    "side":  {"eye": [0.0, 14.0, 2.0], "target": [0.0, 0.0, 1.6], "ortho": 14.0},
    "front": {"eye": [13.0, 0.0, 2.2], "target": [0.0, 0.0, 1.6], "lens": 55},
}


def load_model(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if path.lower().endswith(".blend"):
        bpy.ops.wm.open_mainfile(filepath=path)
    else:
        bpy.ops.import_scene.fbx(filepath=path)


def _try_engine(sc, name):
    try:
        sc.render.engine = name
        return True
    except (TypeError, ValueError):
        return False


def setup_scene(o, w, h):
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = w, h
    sc.render.image_settings.file_format = 'PNG'
    sc.render.film_transparent = False

    world = bpy.data.worlds.new("W")
    sc.world = world
    world.use_nodes = True
    nt = world.node_tree
    bg = next((n for n in nt.nodes if n.type == 'BACKGROUND'), None)
    if bg is None:                      # 新版 Blender 不再自动带 Background 节点
        bg = nt.nodes.new("ShaderNodeBackground")
        out = next((n for n in nt.nodes if n.type == 'OUTPUT_WORLD'), None) \
            or nt.nodes.new("ShaderNodeOutputWorld")
        nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    bg.inputs[0].default_value = (0.55, 0.58, 0.62, 1)
    bg.inputs[1].default_value = 1.5

    if o["engine"] == "WORKBENCH":
        sc.render.engine = 'BLENDER_WORKBENCH'
        sh = sc.display.shading
        sh.light = 'STUDIO'
        sh.color_type = 'SINGLE'
        sh.single_color = (0.66, 0.66, 0.68)
        sh.show_cavity = True
        sh.cavity_type = 'BOTH'
        sh.show_backface_culling = False
        sc.view_settings.view_transform = 'Standard'
    else:
        ev = o["engine"]
        if ev == "EEVEE":
            # Blender 4.2+ 叫 BLENDER_EEVEE_NEXT，5.x 又改回 BLENDER_EEVEE；
            # 两个都试，都不行就退回 Cycles（慢但一定有）。
            if not (_try_engine(sc, 'BLENDER_EEVEE') or
                    _try_engine(sc, 'BLENDER_EEVEE_NEXT')):
                print("[!] 本机没有 EEVEE，退回 CYCLES")
                ev = "CYCLES"
            else:
                print("[引擎] EEVEE")
        if ev == "CYCLES":
            sc.render.engine = 'CYCLES'
            sc.cycles.device = 'CPU'
            sc.cycles.samples = o["samples"]
            sc.cycles.use_denoising = True
        for energy, rot in ((3.0, (math.radians(50), math.radians(10), math.radians(-130))),
                            (1.0, (math.radians(62), 0, math.radians(55)))):
            ld = bpy.data.lights.new("Sun", 'SUN')
            ld.energy = energy
            ld.angle = math.radians(12)
            lo = bpy.data.objects.new("Sun", ld)
            sc.collection.objects.link(lo)
            lo.rotation_euler = rot

    cd = bpy.data.cameras.new("Cam")
    cam = bpy.data.objects.new("Cam", cd)
    sc.collection.objects.link(cam)
    sc.camera = cam
    return sc, cam, cd


def apply_pose(pose, missing):
    """pose: {objname: {"rot":[x,y,z] 度, "loc":[x,y,z], "scale": float}}"""
    for name, tr in pose.items():
        ob = bpy.data.objects.get(name)
        if ob is None:
            missing.add(name)
            continue
        if "rot" in tr:
            r = tr["rot"]
            ob.rotation_euler = (math.radians(r[0]), math.radians(r[1]), math.radians(r[2]))
        if "loc" in tr:
            ob.location = Vector(tr["loc"])
        if "scale" in tr:
            s = tr["scale"]
            ob.scale = (s, s, s)
    bpy.context.view_layer.update()


# ================================================================ 扫掠模式

def solve_fold_angle(arm, hinge, axis):
    """从几何解折叠角：铰点 → 臂上离铰点最远的顶点。

    与 `bake_deploy_fold.py` 必须同一算法。手填角度一定会和烘焙出来的
    动画终点错开，而错开在渲染里只表现为「差一点点」，很容易放过。
    """
    mw = arm.matrix_world
    if not arm.data.vertices:
        die("臂对象 %s 没有顶点，无法解折叠角" % arm.name)
    far = max((mw @ v.co for v in arm.data.vertices), key=lambda p: (p - hinge).length)
    d = far - hinge
    i0, i1 = PLANE[axis]
    comp = [d.x, d.y, d.z]
    a, b = comp[i0], comp[i1]
    if axis == "Y":
        b = max(b, 1e-6)        # 防止正好 0 时 atan2 跳到 ±90°
    return math.atan2(b, a)


def sweep_pose(t, theta_fold, o):
    """t=0 展开态 → t=1 收拢态。smoothstep 起停 + sin² 中段抬升。

    与 `bake_deploy_fold.py` 的 `pose()` 同源。改这里必须同步改那边，
    否则「预览好看、实机擦车顶」。
    """
    s = t * t * (3.0 - 2.0 * t)
    ang = (theta_fold - o["stow_nose_up"] * DEG) * s
    dx = o["fwd"] * s
    dz = o["lift"] * (math.sin(math.pi * t) ** 2) + o["stow_lift"] * s
    return ang, dx, dz


def apply_sweep(arm, base_loc, ang, dx, dz, axis):
    e = [0.0, 0.0, 0.0]
    e[AXIS_IDX[axis]] = ang
    arm.rotation_euler = e
    # 前移沿世界 X（车头方向），抬升沿世界 Z —— 与 bake 脚本一致
    arm.location = (base_loc.x + dx, base_loc.y, base_loc.z + dz)
    bpy.context.view_layer.update()


def bvh_of(ob):
    mw = ob.matrix_world
    vs = [mw @ v.co for v in ob.data.vertices]
    fs = [tuple(p.vertices) for p in ob.data.polygons]
    if not vs or not fs:
        return None
    return BVHTree.FromPolygons(vs, fs, all_triangles=False)


def probe_gap(probes, chassis):
    """返回 (最近距离, 相交对数)。相交对数 > 0 即穿模。"""
    tc = bvh_of(chassis)
    if tc is None:
        return None, 0
    best = float("inf")
    hits = 0
    for ob in probes:
        mw = ob.matrix_world
        for v in ob.data.vertices:
            loc, nrm, idx, dist = tc.find_nearest(mw @ v.co)
            if loc is not None and dist < best:
                best = dist
        tm = bvh_of(ob)
        if tm is not None:
            hits += len(tm.overlap(tc))
    return (None if best == float("inf") else best), hits


def run_sweep(o):
    o["out"] = os.path.abspath(o["out"])
    os.makedirs(o["out"], exist_ok=True)
    load_model(o["model"])

    arm = bpy.data.objects.get(o["arm"])
    ch = bpy.data.objects.get(o["chassis"])
    if arm is None:
        die("找不到臂对象 %r（用 --arm 指定）" % o["arm"])
    if ch is None:
        die("找不到车体对象 %r（用 --chassis 指定）" % o["chassis"])
    if o["hinge"]:
        hinge = Vector(o["hinge"])
    else:
        hinge = arm.matrix_world.translation.copy()
        print("[铰点] 未给 --hinge，取臂的世界原点 (%.3f, %.3f, %.3f)"
              % (hinge.x, hinge.y, hinge.z))

    names = [x.strip() for x in o["probe"].split(",") if x.strip()]
    probes = []
    for nm in names:
        p = bpy.data.objects.get(nm)
        if p is None:
            die("找不到被测对象 %r（--probe）" % nm)
        probes.append(p)
    if not probes:
        probes = [arm]
        print("[被测] 未给 --probe，只测臂自身")

    theta = solve_fold_angle(arm, hinge, o["axis"])
    print("[解算] 折叠角 %.2f°（铰点 → 臂最远顶点）" % (theta / DEG))

    arm.rotation_mode = 'XYZ'
    base_loc = arm.location.copy()
    base_rot = arm.rotation_euler.copy()

    wxh = o["res"].lower().split("x")
    w, h = int(wxh[0]), int(wxh[1])
    sc, cam, cd = setup_scene(o, w, h)
    views = DEFAULT_VIEWS
    if o["views"]:
        with open(o["views"], encoding="utf-8") as f:
            views = json.load(f)

    def shoot(tag, ang, dx, dz):
        apply_sweep(arm, base_loc, ang, dx, dz, o["axis"])
        gap, hits = probe_gap(probes, ch)
        zmin = None
        for ob in probes:
            mw = ob.matrix_world
            if ob.data.vertices:
                zz = min((mw @ v.co).z for v in ob.data.vertices)
                zmin = zz if zmin is None else min(zmin, zz)
        for vname, v in views.items():
            eye = Vector(v["eye"])
            cam.location = eye
            cam.rotation_euler = (Vector(v["target"]) - eye).to_track_quat('-Z', 'Y').to_euler()
            if v.get("ortho"):
                cd.type = 'ORTHO'
                cd.ortho_scale = float(v["ortho"])
            else:
                cd.type = 'PERSP'
                cd.lens = float(v.get("lens", 60))
            sc.render.filepath = os.path.abspath(os.path.join(o["out"], "%s__%s.png" % (tag, vname)))
            bpy.ops.render.render(write_still=True)
        return gap, hits, zmin

    rows = []
    if o["sweep_progress"]:
        print("\n=== 扫进度（抬升 %.2f / 前移 %.2f / 终点抬高 %.2f / 抬头 %.1f°）==="
              % (o["lift"], o["fwd"], o["stow_lift"], o["stow_nose_up"]))
        for t in o["sweep_progress"]:
            ang, dx, dz = sweep_pose(t, theta, o)
            tag = "p%03d" % int(round(t * 100))
            gap, hits, zmin = shoot(tag, ang, dx, dz)
            rows.append((tag, "t=%.2f" % t, ang / DEG, gap, hits, zmin))
            print("  %s  rot=%6.2f°  dz=%.3f  最近 %s m  相交 %d 对%s  最低 z=%s"
                  % (tag, ang / DEG, dz,
                     "—" if gap is None else "%.3f" % gap, hits,
                     "  ⚠穿模" if hits else "",
                     "—" if zmin is None else "%.3f" % zmin))

    if o["sweep_angle"]:
        print("\n=== 扫角度（固定终点抬升 %.2f m，只变抬头角）===" % o["stow_lift"])
        for a_deg in o["sweep_angle"]:
            save = o["stow_nose_up"]
            o["stow_nose_up"] = a_deg
            ang, dx, dz = sweep_pose(1.0, theta, o)
            o["stow_nose_up"] = save
            tag = "a%03d" % int(round(a_deg))
            gap, hits, zmin = shoot(tag, ang, dx, dz)
            rows.append((tag, "nose=%.1f°" % a_deg, ang / DEG, gap, hits, zmin))
            print("  %s  rot=%6.2f°  最近 %s m  相交 %d 对%s  最低 z=%s"
                  % (tag, ang / DEG,
                     "—" if gap is None else "%.3f" % gap, hits,
                     "  ⚠穿模" if hits else "",
                     "—" if zmin is None else "%.3f" % zmin))

    # 复位，避免下游误存成「半收拢态」
    arm.rotation_euler = base_rot
    arm.location = base_loc
    bpy.context.view_layer.update()

    print("\n=== 汇总 ===")
    worst = min((r for r in rows if r[3] is not None), key=lambda r: r[3], default=None)
    anyhit = [r for r in rows if r[4]]
    for tag, lbl, ang, gap, hits, zmin in rows:
        print("  %-6s %-12s rot=%6.2f°  最近 %s m  相交 %-3d 最低 z=%s"
              % (tag, lbl, ang, "—" if gap is None else "%.3f" % gap, hits,
                 "—" if zmin is None else "%.3f" % zmin))
    if worst:
        print("\n[最紧] %s（%s）最近 %.3f m" % (worst[0], worst[1], worst[3]))
    if anyhit:
        print("[!] %d 个采样点有表面相交：%s —— 看图确认是擦碰还是整个陷进去"
              % (len(anyhit), ", ".join(r[0] for r in anyhit)))
    else:
        print("[ok] 所有采样点表面相交对数均为 0（注意：0 不等于没问题，"
              "弹体完全埋进车体时也可能为 0，必须看图）")
    print("\n出图 %d 张 → %s" % (len(rows) * len(views), o["out"]))
    return 0


def main():
    o = parse_args()
    if not os.path.exists(o["model"]):
        die("找不到 " + o["model"])
    if o["sweep_progress"] or o["sweep_angle"]:
        return run_sweep(o)
    wxh = o["res"].lower().split("x")
    if len(wxh) != 2:
        die("--res 要写成 900x700")
    w, h = int(wxh[0]), int(wxh[1])

    poses = {"rest": {}}
    if o["poses"]:
        with open(o["poses"], encoding="utf-8") as f:
            poses = json.load(f)
    views = DEFAULT_VIEWS
    if o["views"]:
        with open(o["views"], encoding="utf-8") as f:
            views = json.load(f)

    o["out"] = os.path.abspath(o["out"])
    os.makedirs(o["out"], exist_ok=True)
    sc, cam, cd = setup_scene(o, w, h)

    print("姿态 %d 个 × 机位 %d 个 = %d 张；引擎 %s，%dx%d"
          % (len(poses), len(views), len(poses) * len(views), o["engine"], w, h))

    missing_all = set()
    for pname, pose in poses.items():
        load_model(o["model"])          # 每个姿态都重新载入，避免状态串味
        sc, cam, cd = setup_scene(o, w, h)
        miss = set()
        apply_pose(pose, miss)
        if miss:
            missing_all |= miss
            print("  [!] 姿态 %s 里这些对象不存在：%s" % (pname, ", ".join(sorted(miss))))
        for vname, v in views.items():
            eye = Vector(v["eye"])
            cam.location = eye
            cam.rotation_euler = (Vector(v["target"]) - eye).to_track_quat('-Z', 'Y').to_euler()
            if v.get("ortho"):
                cd.type = 'ORTHO'
                cd.ortho_scale = float(v["ortho"])
            else:
                cd.type = 'PERSP'
                cd.lens = float(v.get("lens", 60))
            path = os.path.abspath(os.path.join(o["out"], "%s__%s.png" % (pname, vname)))
            sc.render.filepath = path
            bpy.ops.render.render(write_still=True)
            print("  ->", path)

    if missing_all:
        print("\n[!] 共 %d 个对象名在模型里找不到：%s"
              % (len(missing_all), ", ".join(sorted(missing_all))))
        print("    对照 mesh_check.py 的锚点清单核对拼写")
    print("\n完成，共 %d 张" % (len(poses) * len(views)))


main()
