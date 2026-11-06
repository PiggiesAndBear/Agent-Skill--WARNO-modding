# -*- coding: utf-8 -*-
"""烘焙 deploy / fold 两段动画：发射架「起竖 ↔ 收拢」，并逐帧驱动出管挂点骨骼。

【原理】
----
绑定 rest 姿态 = **发射态**（臂已抬起）。所以两段是同一套姿态曲线的正反播放：

    fold   : 0 帧 = 发射态 → N 帧 = 行军态（放平）
    deploy : 0 帧 = 行军态 → N 帧 = 发射态

三件必须做对的事，任何一件错了都不报错、只在实机穿模或弹体乱飞：

1. **不要归零 `arm.location`**。若臂的原点就在铰点上（多数 TEL 如此），归零等于把整根臂
   搬到世界原点，于是绕车体中部旋转 —— 实机表现为「弹体被甩到车头下方」。
   原点是 (0,0,0) 的机型（如 M752 的 Boom）才需要归零。本脚本直接取 `arm.location` 当基准。
2. **折叠角从几何解，不手填**。取铰点→臂最远顶点这个方向，解出把它转到水平所需的角度。
   同时校验：转完臂端必须落在车头一侧（`--fold-dir`），否则是往车尾倒，姿态与真车不符。
3. **出管挂点骨骼要逐帧打关键帧**。父级保持静态（挂在 `tourelle_01` 这类空物体下），
   但每帧把它的世界矩阵设成 `delta @ rest`，`delta = arm.matrix_world @ arm_rest.inverted()`。
   不能把它挂到网格对象（如 `Canon_01`）下 —— 那样它不再是骨，引擎找不到 `missile_1`，
   弹体会退回模型原点。

「先抬后转」= 两个旋钮：
* `--lift`    中段额外抬升（sin² 包络，峰值在 50%），消掉折叠中段扫过车顶的穿模；
* `--stow-lift` 收拢终点整体抬高，让弹体停在车顶之上（不抬就埋进车顶）。
* `--fwd`     折叠过程中沿车头方向平移，真车折叠也要先离开顶部凹槽。
* `--stow-nose-up` 行军态残余抬头角。**可以设 0**（放平），不要再照抄「必须留 10°」。

【操作】
----
  blender -b -P bake_deploy_fold.py -- --blend <rig.blend> --out <资产目录> [--dry]

  常用：
    --arm Canon_01 --chassis Chassis        臂与车体对象名
    --hinge X,Y,Z                           缺省取 arm 的世界原点
    --bones missile_1,as_1_1,canon_01       要跟着臂走的挂点骨骼（缺省同左）
    --frames 150 --fps 30                   150/30 = 5 s
    --lift 0.35 --fwd 0.45 --stow-lift 0.34 --stow-nose-up 0
    --name-prefix Tochka_9K79               输出 <prefix>_fold.fbx / _deploy.fbx
    --exclude-mesh Missile_9M79             导出时不选它（弹体是独立资源）
    --clip-check                             可选：逐帧射线判穿模（**默认可信度低**，见下）

【验收】
----
1. 脚本末尾的 `[校验] 挂点最大偏差` 应为 0.00000 m（逐帧对比「设进去的世界矩阵」与
   「理论值 delta @ rest」）；
2. 读回导出的 `_fold.fbx`，看末帧 `missile_N` 坐标是否等于算出的收拢位
   （`fbx_anchors.py dump` 或 `pose_render.py` 摆末帧出图）；
3. **穿模不要信 `--clip-check`**：射线奇偶法对非闭合网格会整段误报
   （圆点实测 151/151 帧全报）。改用 `pose_render.py --sweep` 按 20/35/50/65/80/100%
   出图目视，看最近距离。

用法示例：
  blender -b -P bake_deploy_fold.py -- \\
      --blend rig/tochka.blend --out GameData/Assets/3D/Units/URSS/Char/Tochka_9K79 \\
      --arm Canon_01 --chassis Chassis --bones missile_1,as_1_1,canon_01 \\
      --frames 150 --lift 0.35 --fwd 0.45 --stow-lift 0.34 --stow-nose-up 0 \\
      --name-prefix Tochka_9K79 --exclude-mesh Missile_9M79
"""
import bpy
import sys
import os
import math
import argparse
from mathutils import Vector, Matrix

PLANE = {"Y": (0, 2), "Z": (0, 1), "X": (1, 2)}   # 绕某轴转时的「旋转平面」两个分量


def argv_after_ddash():
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1:]
    return []


def parse_args():
    p = argparse.ArgumentParser(
        prog="bake_deploy_fold.py",
        description="烘焙 deploy/fold 动画（发射架起竖/收拢），逐帧驱动出管挂点骨骼",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--blend", required=True, help="展开态（发射态）的车辆绑定 .blend，只读不写")
    p.add_argument("--out", required=True, help="输出目录（放 _fold.fbx / _deploy.fbx）")
    p.add_argument("--arm", default="Canon_01", help="发射臂对象名（默认 Canon_01）")
    p.add_argument("--chassis", default="Chassis", help="车体对象名（默认 Chassis）")
    p.add_argument("--hinge", default="", help="铰点 X,Y,Z；缺省取臂的世界原点")
    p.add_argument("--bones", default="missile_1,as_1_1,canon_01",
                   help="随臂运动的挂点骨骼，逗号分隔（默认 missile_1,as_1_1,canon_01）")
    p.add_argument("--axis", choices=["X", "Y", "Z"], default="Y", help="折叠旋转轴（默认 Y）")
    p.add_argument("--fold-dir", choices=["+", "-"], default="+",
                   help="折叠时臂端朝哪个方向倒（+ = 世界 +X/+Y/+Z，默认 +，即朝车头）")
    p.add_argument("--frames", type=int, default=150,
                   help="总帧数（0..frames 共 frames+1 帧；默认 150，30fps ≈ 5 s）")
    p.add_argument("--fps", type=int, default=30, help="场景帧率（默认 30）")
    p.add_argument("--lift", type=float, default=0.35, help="中段额外抬升 m（默认 0.35）")
    p.add_argument("--fwd", type=float, default=0.45, help="折叠前移 m（默认 0.45）")
    p.add_argument("--stow-lift", type=float, default=0.34, help="收拢终点抬高 m（默认 0.34）")
    p.add_argument("--stow-nose-up", type=float, default=0.0, help="行军态残余抬头角（默认 0）")
    p.add_argument("--name-prefix", default="", help="输出文件名前缀，缺省取 blend 名")
    p.add_argument("--exclude-mesh", default="", help="导出时排除的网格对象（弹体）")
    p.add_argument("--clip-check", action="store_true",
                   help="逐帧射线判穿模（对非闭合网格不可靠，建议改用 pose_render --sweep）")
    p.add_argument("--no-export", action="store_true", help="只打关键帧与校验，不导 FBX")
    p.add_argument("--dry", action="store_true", help="只解算姿态与校验，不写关键帧、不导出")
    return p.parse_args(argv_after_ddash())


def main():
    a = parse_args()
    blend = os.path.abspath(a.blend)
    if not os.path.isfile(blend):
        sys.exit("[错误] 找不到 %s" % blend)
    bpy.ops.wm.open_mainfile(filepath=blend)
    sc = bpy.context.scene
    sc.render.fps = a.fps

    arm = bpy.data.objects.get(a.arm)
    if arm is None:
        sys.exit("[错误] 没有对象 %r（用 --arm 指定发射臂）" % a.arm)
    ch = bpy.data.objects.get(a.chassis)

    # ---------- 1. 铰点 ----------
    if a.hinge:
        HINGE = Vector([float(x) for x in a.hinge.split(",")])
    else:
        HINGE = arm.matrix_world.to_translation().copy()
        print("[铰点] 取臂的世界原点 (%.3f, %.3f, %.3f)。若臂原点不在铰点上，用 --hinge 显式给"
              % (*HINGE,))

    # ---------- 2. 解折叠角 ----------
    iu, iv = PLANE[a.axis]
    vs = [arm.matrix_world @ v.co for v in arm.data.vertices] if arm.type == 'MESH' else []
    if not vs:
        sys.exit("[错误] 臂 %r 不是网格，无法从几何解折叠角；改用 --hinge 并手工确认" % a.arm)
    far = max(vs, key=lambda p: (p - HINGE).length)
    d = far - HINGE
    du, dv = d[iu], d[iv]
    if abs(dv) < 1e-6:
        dv = 1e-6
    theta_fold = math.atan2(dv, du)
    print("[解算] 铰点=(%.3f,%.3f,%.3f)  臂远端=(%.3f,%.3f,%.3f)"
          % (*HINGE, far.x, far.y, far.z))
    print("[解算] 绕 %s 旋转，平面内方向 (%.3f, %.3f) → 折叠角 %.2f°"
          % (a.axis, du, dv, math.degrees(theta_fold)))

    R = Matrix.Rotation(theta_fold, 4, a.axis)
    pe = R @ (far - HINGE)
    print("[校验] 按此角旋转后臂端相对铰点 = (%.3f, %.3f, %.3f)" % (pe.x, pe.y, pe.z))
    if abs(pe[iv]) > max(0.15, 0.02 * (far - HINGE).length):
        sys.exit("[错误] 折叠角解算失败：臂端没落到水平（残余 %.3f m）。"
                 "检查 --hinge 是否真的是铰点" % abs(pe[iv]))
    sgn = 1.0 if a.fold_dir == "+" else -1.0
    if pe[iu] * sgn <= 0.2:
        sys.exit("[错误] 折叠方向反了：臂端落在反向（%s 分量 %.3f，期望朝 %s）。"
                 "改 --fold-dir 或确认车头朝向" % (a.axis, pe[iu], a.fold_dir))

    # ---------- 3. 逐帧关键帧 ----------
    arm.rotation_mode = 'XYZ'
    if arm.animation_data:
        arm.animation_data_clear()
    # ⚠ 绝不归零 location（见文件头原理 1）
    raw_rot = list(arm.rotation_euler)
    if any(abs(x) > 1e-6 for x in raw_rot):
        print("[提示] 臂原始 rotation=(%.3f, %.3f, %.3f) rad，已归零作为 rest 基准"
              % (*raw_rot,))
    arm.rotation_euler = (0, 0, 0)
    bpy.context.view_layer.update()
    base_loc = arm.location.copy()
    A0 = arm.matrix_world.copy()
    print("[基准] 臂 rest 世界位置=(%.3f, %.3f, %.3f)  局部 location=(%.3f, %.3f, %.3f)"
          % (*A0.to_translation(), *base_loc))

    bones = [n.strip() for n in a.bones.split(",") if n.strip()]
    REST = {}
    for n in bones:
        o = bpy.data.objects.get(n)
        if o is None:
            print("[警告] 没有挂点骨骼 %s，跳过（会导致弹体不随臂动）" % n)
            continue
        o.rotation_mode = 'XYZ'
        if o.animation_data:
            o.animation_data_clear()
        REST[n] = o.matrix_world.copy()
        print("       %-12s rest=(%.3f, %.3f, %.3f)" % (n, *o.matrix_world.to_translation()))
    if not REST:
        sys.exit("[错误] 一个挂点骨骼都没找到。用 --bones 指定，或先补骨骼")

    iax = "XYZ".index(a.axis)
    theta_stow = theta_fold - math.radians(a.stow_nose_up)

    def smoothstep(t):
        return t * t * (3 - 2 * t)

    def pose(t):
        """t∈[0,1]：0=发射态，1=行军态。返回 (angle, dx_vec, 挂点偏差)。"""
        s = smoothstep(t)
        ang = theta_stow * s
        fwd = a.fwd * s
        lift = a.lift * (math.sin(math.pi * t) ** 2) + a.stow_lift * s
        return ang, fwd, lift

    worst_dev = 0.0

    def key_frames(mode):
        nonlocal worst_dev
        worst_dev = 0.0
        for f in range(a.frames + 1):
            t = f / a.frames
            if mode == "deploy":
                t = 1.0 - t
            ang, fwd, lift = pose(t)
            sc.frame_set(f)
            rot = [0.0, 0.0, 0.0]
            rot[iax] = ang
            arm.rotation_euler = rot
            loc = base_loc.copy()
            # 前移沿「旋转平面内的第一个分量」方向，即车头/车尾轴（Y 或 Z 折叠时都是 X）
            loc[iu] += fwd * (1.0 if a.fold_dir == "+" else -1.0)
            loc.z += lift
            arm.location = loc
            arm.keyframe_insert("rotation_euler", frame=f)
            arm.keyframe_insert("location", frame=f)

            bpy.context.view_layer.update()
            delta = arm.matrix_world @ A0.inverted()
            for n, rest in REST.items():
                o = bpy.data.objects[n]
                want = delta @ rest
                o.matrix_world = want
                o.keyframe_insert("location", frame=f)
                o.keyframe_insert("rotation_euler", frame=f)
                bpy.context.view_layer.update()
                dev = (o.matrix_world.to_translation() - want.to_translation()).length
                if dev > worst_dev:
                    worst_dev = dev
            if f % max(1, a.frames // 5) == 0:
                print("   f%-3d t=%.2f  %s角=%7.2f°  fwd=%.3f  lift=%.3f"
                      % (f, t, a.axis, math.degrees(ang), fwd, lift))

    # ---------- 4. 可选穿模复测（默认关） ----------    def clip_check():
        from mathutils.bvhtree import BVHTree
        if ch is None or ch.type != 'MESH':
            print("  [穿模] 没有车体网格，跳过")
            return
        mis = bpy.data.objects.get(a.exclude_mesh) if a.exclude_mesh else None
        if mis is None:
            print("  [穿模] 没指定 --exclude-mesh 或对象不存在，跳过")
            return
        cvs = [ch.matrix_world @ v.co for v in ch.data.vertices]
        cfaces = [tuple(pl.vertices) for pl in ch.data.polygons]
        bvh = BVHTree.FromPolygons(cvs, cfaces, all_triangles=False)
        sc.frame_set(0)
        bpy.context.view_layer.update()
        mvs0 = [mis.matrix_world @ v.co for v in mis.data.vertices]
        arm0 = arm.matrix_world.copy()
        worst, bad = (0, 0.0), 0
        for f in range(a.frames + 1):
            sc.frame_set(f)
            bpy.context.view_layer.update()
            delta = arm.matrix_world @ arm0.inverted()
            dmax = 0.0
            for p0 in mvs0:
                p = delta @ p0
                hits, org = 0, p.copy()
                for _ in range(16):
                    hit = bvh.ray_cast(org, Vector((1.0, 0.0, 0.0)))
                    if hit[0] is None:
                        break
                    hits += 1
                    org = hit[0] + Vector((1e-4, 0.0, 0.0))
                if hits % 2 == 1:
                    near = bvh.find_nearest(p)
                    if near[0] is not None and near[3] > dmax:
                        dmax = near[3]
            if dmax > 0.05:
                bad += 1
            if dmax > worst[1]:
                worst = (f, dmax)
        print("  [穿模] 最坏帧 %d 深度 %.3f m；超 5cm 的帧 %d/%d"
              % (worst[0], worst[1], bad, a.frames + 1))
        print("  [提醒] 射线奇偶法对非闭合网格会整段误报，务必用 pose_render --sweep 目视复核")

    if a.dry:
        key_frames("fold")
        print("[校验] 挂点最大偏差 %.5f m" % worst_dev)
        if a.clip_check:
            clip_check()
        print("[dry] 未导出")
        return

    os.makedirs(a.out, exist_ok=True)
    prefix = a.name_prefix or os.path.splitext(os.path.basename(blend))[0]

    for mode in ("fold", "deploy"):
        key_frames(mode)
        print("[校验] %s 挂点最大偏差 %.5f m" % (mode, worst_dev))
        if worst_dev > 1e-3:
            sys.exit("[错误] %s 挂点偏差过大（%.4f m）：骨骼没跟上臂。检查 --bones 名字是否拼对"
                     % (mode, worst_dev))
        sc.frame_start, sc.frame_end = 0, a.frames
        sc.frame_set(0)
        bpy.ops.object.select_all(action='DESELECT')
        skip = a.exclude_mesh
        for o in bpy.data.objects:
            if o.type in ('MESH', 'EMPTY') and o.name != skip:
                o.select_set(True)
        out = os.path.join(a.out, "%s_%s.fbx" % (prefix, mode))
        bpy.ops.export_scene.fbx(
            filepath=out, use_selection=True, object_types={'MESH', 'EMPTY'},
            apply_scale_options='FBX_SCALE_UNITS', axis_forward='Y', axis_up='Z',
            use_mesh_modifiers=True, mesh_smooth_type='FACE', add_leaf_bones=False,
            path_mode='RELATIVE', embed_textures=False,
            bake_anim=True, bake_anim_use_all_bones=False,
            bake_anim_use_nla_strips=False, bake_anim_use_all_actions=False,
            bake_anim_force_startend_keying=True, bake_anim_step=1.0,
            bake_anim_simplify_factor=0.0)
        print("[导出] %-34s %.1f KB" % (os.path.basename(out), os.path.getsize(out) / 1024))

    if a.clip_check:
        print("\n=== 穿模复测（fold 方向）===")
        key_frames("fold")
        clip_check()

    print("\n[完成] %s_fold.fbx / %s_deploy.fbx  →  %s" % (prefix, prefix, a.out))
    print("[必做] 节点有增删时先拆轮/补骨，再烘；烘完顺序不能反，否则 Skeleton mismatch")


if __name__ == "__main__":
    main()
