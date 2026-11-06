"""模型体检（只读）：把「这个网格能不能进 WARNO」的硬指标一次性量出来。

用法（Blender 脚本，必须用 blender 跑，不需要打开界面）：

    blender -b -P mesh_check.py -- <model.fbx|model.blend|model.gltf> \
        [--weld 1e-4] [--json out.json] [--cook]

两档：
  **默认（几何规模档）** 顶点上限 / 壳数 / UV 量级 / 边界边 / 锚点清单
  **`--cook`（编译门槛档）** 再加 AssetCooker 会直接拒的脏数据：
      退化面、零法线面、n-gon（>4 边）、松散点/线、材质链断开、ORM 中转、alpha 通道

输出内容：
  1. 网格 / 空物体统计，总顶点是否顶破 65536
  2. 每个网格：面数、顶点数、包围盒、UV 层数与 |uv| 最大值、use_smooth 比例
  3. 「焊接后壳」统计：把三角汤还原成真实壳体后的壳数，并列出最大的几个壳
     ——壳数远小于面数说明这是装配体；壳数≈面数说明是三角汤（拆件必须整壳归组）
  4. 边界边比例（每条边只被 1 个面用到）：越高越像"单层皮"，
     单层皮上开洞 = 露内壁，拆件前必须先做「背后是实心还是凹兜」判定
  5. 锚点（空物体）清单与世界坐标 —— 拿去和 depiction 的 Anchors 对账
  6. `--cook` 追加：面/材质/贴图三类脏数据，**任一硬伤 rc=1**

判据（超出即打印 [!]）：
  顶点 > 65536        → AssetCooker 直接失败
  |uv| > 3.6          → 量化时报 Can't quantize texcoords（真实上限约 3.7，留余量）
  smooth 比例 0       → 导出会按面拆顶点，顶点数暴涨
  壳数 ≈ 面数          → 三角汤，按面拆/按坐标裁都会切开壳体
  `--cook` 硬伤（rc=1）：
    退化面 > 0        → 面积 < 1e-9，cook 时法线算不出来
    零法线面 > 0      → 叉积 < 1e-12，同上
    松散点/线 > 0     → 不属于任何面，导出时成为垃圾节点
    ORM 中转          → Roughness/Metallic 未直连贴图，FBX 里就没有 _R/_M，
                        AssetCooker 不生成 TSCORM 槽（详见 references/25 §ORM）

只读：不改任何文件（除非给了 --json 写出报告）。
"""
import bpy
import bmesh
import json
import os
import sys


def die(msg):
    print("[!] " + msg)
    sys.exit(2)


def parse_args():
    argv = sys.argv
    if "--" not in argv:
        die("参数要放在 -- 之后：blender -b -P mesh_check.py -- <model>")
    a = argv[argv.index("--") + 1:]
    opts = {"model": None, "weld": 1e-4, "json": None, "cook": False}
    i = 0
    while i < len(a):
        if a[i] == "--weld":
            opts["weld"] = float(a[i + 1]); i += 2
        elif a[i] == "--json":
            opts["json"] = a[i + 1]; i += 2
        elif a[i] == "--cook":
            opts["cook"] = True; i += 1
        elif a[i].startswith("--"):
            die("未知参数 " + a[i])
        else:
            opts["model"] = a[i]; i += 1
    if not opts["model"]:
        die("缺少模型路径")
    return opts


def load(path):
    low = path.lower()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if low.endswith(".blend"):
        bpy.ops.wm.open_mainfile(filepath=path)
    elif low.endswith(".gltf") or low.endswith(".glb"):
        # --cook 常见于 glTF 环节（AssetCooker 的实际输入），qa.py 只吃 glTF
        bpy.ops.import_scene.gltf(filepath=path)
    else:
        bpy.ops.import_scene.fbx(filepath=path)


def weld_shells(ob, eps):
    """焊接重合顶点后按「共享边」求连通壳。返回 (壳列表[面索引集], 焊接顶点数, 边界边数, 总边数)。"""
    mw = ob.matrix_world
    co = [mw @ v.co for v in ob.data.vertices]
    ids, fids = {}, {}
    for p in ob.data.polygons:
        loop = []
        for vi in p.vertices:
            c = co[vi]
            k = (round(c.x / eps) if eps else round(c.x, 6),
                 round(c.y / eps) if eps else round(c.y, 6),
                 round(c.z / eps) if eps else round(c.z, 6))
            if k not in ids:
                ids[k] = len(ids)
            loop.append(ids[k])
        fids[p.index] = loop

    parent = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    edge_use = {}
    for fi, loop in fids.items():
        parent.setdefault(fi, fi)
        n = len(loop)
        for i in range(n):
            a, b = loop[i], loop[(i + 1) % n]
            e = (a, b) if a < b else (b, a)
            edge_use.setdefault(e, []).append(fi)
    for fl in edge_use.values():
        for k in range(1, len(fl)):
            union(fl[0], fl[k])

    groups = {}
    for fi in fids:
        groups.setdefault(find(fi), []).append(fi)
    boundary = sum(1 for fl in edge_use.values() if len(fl) == 1)
    return list(groups.values()), len(ids), boundary, len(edge_use)


def bbox_of(ob, faces=None):
    mw = ob.matrix_world
    if faces is None:
        vs = [mw @ v.co for v in ob.data.vertices]
    else:
        idx = set()
        for f in faces:
            idx.update(ob.data.polygons[f].vertices)
        vs = [mw @ ob.data.vertices[i].co for i in idx]
    if not vs:
        return None
    return (min(p.x for p in vs), max(p.x for p in vs),
            min(p.y for p in vs), max(p.y for p in vs),
            min(p.z for p in vs), max(p.z for p in vs))


# ================================================================ cook 预检
# 移植自 tochka/qa.py（AssetCooker 四道清洗的预检）。与上面「几何体检」的分工：
#   上面看**规模**（顶点/壳数/UV 量级）——超了会失败，但模型本身是干净的；
#   这里看**脏数据**（退化面/零法线/n-gon/松散点/材质链断）——量级再小也会被拒。

# Roughness / Metallic 若直连贴图，Blender 导出器才写得进 _R / _M；
# 中间隔了任何节点（MATH / SEPARATE_COLOR / MIX）都会静默丢槽。
# 依据：bpy_extras/node_shader_utils.py 的 ShaderImageTextureWrapper 只认
#       from_node.bl_idname == 'ShaderNodeTexImage'；否则 node_image 为 None，
#       export_fbx_bin.py 的 PRINCIPLED_TEXTURE_SOCKETS_TO_FBX 循环 continue 跳过。
ORM_SOCKETS = ("Roughness", "Metallic")


def cook_geometry(ob):
    """返回 (info, fails)。fails 是「会直接让 cook 失败」的项。"""
    me = ob.data
    me.calc_loop_triangles()

    degen = zero_n = 0
    minarea = float("inf")
    for t in me.loop_triangles:
        a, b, c = [me.vertices[i].co for i in t.vertices]
        cr = (b - a).cross(c - a)
        ar = cr.length / 2.0
        if ar < minarea:
            minarea = ar
        if ar < 1e-9:
            degen += 1
        if cr.length < 1e-12:
            zero_n += 1
    if minarea == float("inf"):
        minarea = 0.0

    n_tri = sum(1 for p in me.polygons if len(p.vertices) == 3)
    n_quad = sum(1 for p in me.polygons if len(p.vertices) == 4)
    n_ngon = sum(1 for p in me.polygons if len(p.vertices) > 4)

    bm = bmesh.new()
    bm.from_mesh(me)
    loose_v = sum(1 for v in bm.verts if not v.link_edges)
    loose_e = sum(1 for e in bm.edges if not e.link_faces)
    bm.free()

    info = dict(tris=len(me.loop_triangles), poly_tri=n_tri, poly_quad=n_quad,
                poly_ngon=n_ngon, degenerate=degen, zero_normal=zero_n,
                min_area=round(minarea, 12), loose_verts=loose_v, loose_edges=loose_e,
                uv_layers=[l.name for l in me.uv_layers],
                materials=[m.name for m in me.materials if m])

    fails = []
    if degen:
        fails.append("%s: 退化面 %d 个（面积 < 1e-9，法线算不出来）" % (ob.name, degen))
    if zero_n:
        fails.append("%s: 零法线面 %d 个（叉积 < 1e-12）" % (ob.name, zero_n))
    if loose_v:
        fails.append("%s: 松散点 %d 个（不属于任何面）" % (ob.name, loose_v))
    if loose_e:
        fails.append("%s: 松散边 %d 条（不属于任何面）" % (ob.name, loose_e))
    if len(me.polygons) and not me.uv_layers:
        fails.append("%s: 没有 UV 层（任何带图材质都会落到 (0,0) 一点上）" % ob.name)
    return info, fails


def cook_materials():
    """返回 (mats_info, imgs_info, fails, warns)。

    只对 Roughness/Metallic 判「中转」为硬伤 —— 这两个 socket 的判定依据是确定的
    （见 ORM_SOCKETS 上面的注释）。Base Color 走 MIX/渐变是合法用法，只给提示。
    """
    mats, imgs, fails, warns = {}, {}, [], []

    for m in bpy.data.materials:
        if not m.use_nodes or not m.node_tree:
            continue
        nt = m.node_tree
        bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        linked = {}
        if bsdf:
            for k in ("Base Color", "Alpha", "Metallic", "Roughness", "Normal"):
                s = bsdf.inputs.get(k)
                if s is not None:
                    linked[k] = bool(s.is_linked)
        # ORM 中转检测
        routed = {}
        if bsdf:
            for sock in ORM_SOCKETS:
                s = bsdf.inputs.get(sock)
                if s is None or not s.is_linked:
                    continue
                src = s.links[0].from_node
                ok = (src.type == 'TEX_IMAGE' and getattr(src, "image", None) is not None)
                routed[sock] = src.type
                if not ok:
                    fails.append("%s: %s 走 %s 中转，未直连贴图 → FBX 无 _%s，"
                                 "AssetCooker 不生成 TSCORM 槽"
                                 % (m.name, sock, src.type,
                                    "R" if sock == "Roughness" else "M"))
        base_src = None
        if bsdf:
            s = bsdf.inputs.get("Base Color")
            if s is not None and s.is_linked:
                base_src = s.links[0].from_node.type
                if base_src != 'TEX_IMAGE':
                    warns.append("%s: Base Color 源自 %s（非贴图直连）" % (m.name, base_src))
        mats[m.name] = dict(images=[n.image.name for n in nt.nodes
                                    if n.type == 'TEX_IMAGE' and n.image],
                            blend=m.blend_method, linked=linked,
                            orm_routed=routed, base_src=base_src,
                            nodes=len(nt.nodes))

    for im in bpy.data.images:
        if im.size[0] == 0 or im.size[1] == 0:
            continue
        px = list(im.pixels[:])
        n = max(1, len(px) // 4)
        alphas = px[3::4]
        amin, amax = min(alphas), max(alphas)
        uniq = len(set(round(a, 2) for a in alphas[::max(1, n // 4000)]))
        rgb = [round(sum(px[i::4]) / n, 3) for i in range(3)]
        imgs[im.name] = dict(size=list(im.size),
                             cs=im.colorspace_settings.name,
                             alpha=[round(amin, 3), round(amax, 3), uniq],
                             rgb_mean=rgb, packed=im.packed_file is not None)
        if amax <= 0.001:
            fails.append("%s: alpha 全 0（整张透明）" % im.name)
        elif amin >= 0.999 and im.colorspace_settings.name == 'sRGB' and uniq == 1:
            pass    # 全不透明，正常
    return mats, imgs, fails, warns


def main():
    o = parse_args()
    if not os.path.exists(o["model"]):
        die("找不到文件 " + o["model"])
    load(o["model"])

    meshes = [x for x in bpy.data.objects if x.type == 'MESH']
    empties = [x for x in bpy.data.objects if x.type == 'EMPTY']
    if not meshes:
        die("场景里没有网格")

    rep = {"file": os.path.abspath(o["model"]), "weld": o["weld"],
           "meshes": [], "empties": [], "warnings": []}

    tot_v = sum(len(m.data.vertices) for m in meshes)
    tot_f = sum(len(m.data.polygons) for m in meshes)
    print("=" * 78)
    print("模型: %s" % os.path.abspath(o["model"]))
    print("网格 %d 个 / 空物体 %d 个 / 顶点 %d / 面 %d"
          % (len(meshes), len(empties), tot_v, tot_f))
    if tot_v > 65536:
        rep["warnings"].append("总顶点 %d 超过 65536" % tot_v)
    print("=" * 78)

    for ob in meshes:
        me = ob.data
        uvl = me.uv_layers.active
        uvmax = 0.0
        if uvl:
            for d in uvl.data:
                uvmax = max(uvmax, abs(d.uv.x), abs(d.uv.y))
        smooth = sum(1 for p in me.polygons if p.use_smooth)
        shells, nw, bnd, ne = weld_shells(ob, o["weld"])
        shells.sort(key=len, reverse=True)
        bb = bbox_of(ob)
        info = dict(name=ob.name, verts=len(me.vertices), faces=len(me.polygons),
                    uv_layers=len(me.uv_layers), uv_abs_max=round(uvmax, 3),
                    smooth_ratio=round(smooth / max(1, len(me.polygons)), 3),
                    welded_verts=nw, shells=len(shells),
                    boundary_ratio=round(bnd / max(1, ne), 3),
                    bbox=[round(v, 3) for v in bb] if bb else None,
                    top_shells=[[len(s), [round(v, 2) for v in (bbox_of(ob, s) or [])]]
                                for s in shells[:3]])
        rep["meshes"].append(info)

        vpf = len(me.vertices) / max(1, len(me.polygons))
        print("\n-- %s" % ob.name)
        print("   面 %-6d 顶点 %-6d (%.2f/面)  焊接后 %-5d 壳 %-4d  边界边 %.2f  smooth %.0f%%  UV层 %d  |uv|max %.2f"
              % (len(me.polygons), len(me.vertices), vpf, nw, len(shells),
                 info["boundary_ratio"], info["smooth_ratio"] * 100,
                 info["uv_layers"], uvmax))
        if bb:
            print("   包围盒 X %6.2f..%6.2f  Y %6.2f..%6.2f  Z %6.2f..%6.2f"
                  % (bb[0], bb[1], bb[2], bb[3], bb[4], bb[5]))
        print("   最大壳: " + ", ".join("%d面" % len(s) for s in shells[:5]))

        if uvmax > 3.6:
            rep["warnings"].append("%s: |uv| = %.2f > 3.6" % (ob.name, uvmax))
            print("   [!] UV 超出安全范围，AssetCooker 可能报 Can't quantize texcoords")
        if info["smooth_ratio"] == 0 and len(me.vertices) > 45000:
            rep["warnings"].append("%s: 全平面着色且顶点已接近上限" % ob.name)
            print("   [!] 全平面着色 + 顶点 %d 已接近 65536；继承 use_smooth 可把顶点数压下来"
                  % len(me.vertices))
        elif info["smooth_ratio"] == 0 and len(me.polygons) > 50:
            print("   [i] 全平面着色：导出会按面拆顶点（当前 %.2f 顶点/面），总量没超限就不用管"
                  % vpf)
        if info["shells"] > 0.8 * len(me.polygons) and len(me.polygons) > 200:
            print("   [i] 三角汤模型（壳数≈面数）：拆件必须「焊接→连通块→整壳归组」，")
            print("       按面中心或按坐标直接裁会切开壳体、动起来露内壁")
        if info["boundary_ratio"] > 0.9 and len(me.polygons) > 200:
            print("   [i] 边界边比例接近 1：多为单层皮拼的装配体。")
            print("       拆件前先做「隐藏 + 红底 + 背面剔除」判定它背后是实心还是机身凹兜")

    if empties:
        print("\n-- 锚点（空物体）%d 个" % len(empties))
        for e in sorted(empties, key=lambda z: z.name.lower()):
            w = e.matrix_world.translation
            rep["empties"].append(dict(name=e.name,
                                       world=[round(w.x, 3), round(w.y, 3), round(w.z, 3)],
                                       parent=e.parent.name if e.parent else None))
            print("   %-24s (%.3f, %.3f, %.3f)%s"
                  % (e.name, w.x, w.y, w.z,
                     "   <- " + e.parent.name if e.parent else ""))

    cook_fails, cook_warns = [], []
    if o["cook"]:
        print("\n" + "=" * 78)
        print("AssetCooker 预检（--cook）")
        print("=" * 78)
        rep["cook"] = {"objects": {}, "materials": {}, "images": {},
                       "fails": [], "warns": []}
        for ob in meshes:
            info, fl = cook_geometry(ob)
            rep["cook"]["objects"][ob.name] = info
            cook_fails += fl
            print("\n-- %s" % ob.name)
            print("   三角 %-6d 面 tri/quad/ngon = %d/%d/%d   最小面积 %.3e"
                  % (info["tris"], info["poly_tri"], info["poly_quad"],
                     info["poly_ngon"], info["min_area"]))
            print("   退化面 %-4d 零法线 %-4d 松散点 %-4d 松散边 %-4d UV层 %d"
                  % (info["degenerate"], info["zero_normal"], info["loose_verts"],
                     info["loose_edges"], len(info["uv_layers"])))
            if info["poly_ngon"]:
                print("   [i] n-gon %d 个：AssetCooker 会三角化，凹多边形可能翻转法线"
                      % info["poly_ngon"])

        mats, imgs, fl, wl = cook_materials()
        rep["cook"]["materials"] = mats
        rep["cook"]["images"] = imgs
        cook_fails += fl
        cook_warns += wl

        print("\n-- 材质（%d 个）" % len(mats))
        for k, v in mats.items():
            tag = "" if not v["orm_routed"] else \
                "  ORM=" + ",".join("%s<-%s" % (s, t) for s, t in v["orm_routed"].items())
            print("   %-18s blend=%-6s nodes=%-3d imgs=%d%s"
                  % (k[:18], v["blend"], v["nodes"], len(v["images"]), tag))
        if imgs:
            print("\n-- 贴图（%d 张）" % len(imgs))
            for k, v in imgs.items():
                print("   %-22s %-11s cs=%-9s alpha=%s mean=%s"
                      % (k[:22], "%dx%d" % tuple(v["size"]), v["cs"],
                         v["alpha"], v["rgb_mean"]))
        rep["cook"]["fails"] = cook_fails
        rep["cook"]["warns"] = cook_warns

        if cook_warns:
            print("\n[i] 提示 %d 条：" % len(cook_warns))
            for w in cook_warns:
                print("    - " + w)
        if cook_fails:
            print("\n[X] 硬伤 %d 条（cook 会失败）：" % len(cook_fails))
            for i, f in enumerate(cook_fails, 1):
                print("    %d. %s" % (i, f))
        else:
            print("\n[ok] cook 预检通过：无退化面/零法线/松散点线/材质链断")

    if rep["warnings"]:
        print("\n[!] 共 %d 条告警：" % len(rep["warnings"]))
        for w in rep["warnings"]:
            print("    - " + w)
    else:
        print("\n[ok] 硬指标全部通过")

    if o["json"]:
        with open(o["json"], "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)
        print("\n报告已写入 " + o["json"])

    if o["cook"] and cook_fails:
        sys.exit(1)


main()
