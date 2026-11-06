"""从「三角汤」里拆可动部件：焊接 → 连通块 → 整壳归组 → 拆成独立节点。

为什么必须整壳拆：WARNO 没有 armature 驱动部件，部件动不动取决于「是不是独立节点 + 名字有没有被引用」。
而按面中心分区或按坐标直接裁面，会把壳体切开、接缝落在曲面中间，动起来露内壁。

用法（Blender 脚本）：

    blender -b -P split_shells.py -- <in.blend|in.fbx> <out.fbx> --spec parts.json [--source Chassis] [--no-export]

parts.json:
{
  "weld": 0.0001,
  "source": "Chassis",
  "parts": [
    {"node": "Roue_Gauche", "pivot": [3.03,  0.95, 1.18],
     "box": [[2.30,  0.72, -0.10], [3.90,  2.00, 1.30]]},
    {"node": "Roue_Droite", "pivot": [3.03, -0.95, 1.18],
     "box": [[2.30, -2.00, -0.10], [3.90, -0.72, 1.30]]}
  ]
}

- box 是世界坐标 AABB；**壳的包围盒必须完全落在盒内**才归组（这就是"整壳"的含义）。
- pivot 是该部件的回转中心，同时成为新节点的原点（顶点会按 P − pivot 中心化）。
- 左右对称的部件要各写一条（程序不猜镜像，免得命名搞反）。
- 同一壳被多个 box 覆盖时，**先出现的 part 优先**，并在报告里列出。

输出：每个 part 一个网格对象，父级 = source，位置 = pivot；source 里那些面被移除。
⚠ 重建会丢自定义拆分法线（custom normals），smooth 标记与 UV / 材质索引会保留。
"""
import bpy
import json
import os
import sys
from mathutils import Matrix, Vector


def die(msg):
    print("[!] " + msg)
    sys.exit(2)


def parse_args():
    argv = sys.argv
    if "--" not in argv:
        die("参数要放在 -- 之后")
    a = argv[argv.index("--") + 1:]
    o = {"src": None, "dst": None, "spec": None, "source": None,
         "export": True}
    i = 0
    while i < len(a):
        if a[i] == "--spec":
            o["spec"] = a[i + 1]; i += 2
        elif a[i] == "--source":
            o["source"] = a[i + 1]; i += 2
        elif a[i] == "--no-export":
            o["export"] = False; i += 1
        elif a[i].startswith("--"):
            die("未知参数 " + a[i])
        elif o["src"] is None:
            o["src"] = a[i]; i += 1
        elif o["dst"] is None:
            o["dst"] = a[i]; i += 1
        else:
            die("多余的参数 " + a[i])
    if not o["src"] or not o["spec"]:
        die("用法: split_shells.py -- <in> <out.fbx> --spec parts.json")
    return o


def load(path):
    if path.lower().endswith(".blend"):
        bpy.ops.wm.open_mainfile(filepath=path)
    else:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.fbx(filepath=path)


def weld_key(v, eps):
    return (round(v.x / eps), round(v.y / eps), round(v.z / eps))


def build_shells(ob, eps):
    """返回 (shells: list[list[面索引]], fids: 面 -> 焊接顶点 id 列表, id2co: id -> Vector)"""
    mw = ob.matrix_world
    co = [mw @ v.co for v in ob.data.vertices]
    ids, id2co = {}, {}
    fids = {}
    for p in ob.data.polygons:
        loop = []
        for vi in p.vertices:
            k = weld_key(co[vi], eps)
            if k not in ids:
                ids[k] = len(ids)
                id2co[ids[k]] = co[vi]
            loop.append(ids[k])
        fids[p.index] = loop

    parent = {fi: fi for fi in fids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    edge_use = {}
    for fi, loop in fids.items():
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
    return list(groups.values()), fids, id2co


def shell_bbox(shell, fids, id2co):
    vs = set()
    for f in shell:
        vs.update(fids[f])
    ps = [id2co[i] for i in vs]
    return (min(p.x for p in ps), max(p.x for p in ps),
            min(p.y for p in ps), max(p.y for p in ps),
            min(p.z for p in ps), max(p.z for p in ps))


def make_mesh_from_faces(name, ob, faces, pivot):
    """用 ob 的面子集建一份新 mesh（世界坐标，顶点按 pivot 中心化），保留 UV / 材质索引 / smooth。"""
    me = bpy.data.meshes.new(name)
    uvl = ob.data.uv_layers.active
    mw = ob.matrix_world
    verts, polys, uvs, mids, sms = [], [], [], [], []
    for fi in faces:
        p = ob.data.polygons[fi]
        base = len(verts)
        for vi in p.vertices:
            verts.append(mw @ ob.data.vertices[vi].co - pivot)
        polys.append(list(range(base, base + len(p.vertices))))
        if uvl:
            uvs.append([(uvl.data[p.loop_start + k].uv.x, uvl.data[p.loop_start + k].uv.y)
                        for k in range(len(p.vertices))])
        else:
            uvs.append([(0.0, 0.0)] * len(p.vertices))
        mids.append(p.material_index)
        sms.append(p.use_smooth)

    me.from_pydata(verts, [], polys)
    me.update()
    for m in ob.data.materials:
        me.materials.append(m)
    for i, p in enumerate(me.polygons):
        p.material_index = mids[i]
        p.use_smooth = sms[i]
    if uvl:
        lay = me.uv_layers.new(name="UVMap")
        for pi, uvl2 in enumerate(uvs):
            for k, uv in enumerate(uvl2):
                lay.data[me.polygons[pi].loop_start + k].uv = uv
    return me


def main():
    o = parse_args()
    if not os.path.exists(o["src"]):
        die("找不到 " + o["src"])
    with open(o["spec"], encoding="utf-8") as f:
        spec = json.load(f)
    eps = float(spec.get("weld", 1e-4))
    parts = spec.get("parts") or []
    if not parts:
        die("spec 里没有 parts")

    load(o["src"])
    src_name = o["source"] or spec.get("source") or "Chassis"
    src = bpy.data.objects.get(src_name)
    if src is None or src.type != 'MESH':
        meshes = [x for x in bpy.data.objects if x.type == 'MESH']
        if not meshes:
            die("场景里没有网格")
        src = max(meshes, key=lambda m: len(m.data.polygons))
        print("[i] 没找到 %r，改用最大网格 %r" % (src_name, src.name))

    shells, fids, id2co = build_shells(src, eps)
    print("源 %s: 面 %d / 焊接顶点 %d / 壳 %d"
          % (src.name, len(src.data.polygons), len(id2co), len(shells)))

    assign = {p["node"]: [] for p in parts}
    owner_of_shell = {}
    conflict = []
    for si, shell in enumerate(shells):
        b = shell_bbox(shell, fids, id2co)
        for p in parts:
            (x0, y0, z0), (x1, y1, z1) = p["box"]
            if x0 <= b[0] and b[1] <= x1 and y0 <= b[2] and b[3] <= y1 and z0 <= b[4] and b[5] <= z1:
                if si in owner_of_shell:
                    conflict.append((si, owner_of_shell[si], p["node"]))
                assign[p["node"]].extend(shell)
                owner_of_shell.setdefault(si, p["node"])
                break

    ok = True
    for p in parts:
        n = len(assign[p["node"]])
        mark = "" if n else "   [!] 空，检查 box 是否写错"
        if not n:
            ok = False
        print("  %-18s %5d 面   pivot (%.3f, %.3f, %.3f)%s"
              % (p["node"], n, p["pivot"][0], p["pivot"][1], p["pivot"][2], mark))
    if conflict:
        print("  [i] 有 %d 个壳被多个 box 命中，按先出现的 part 归属" % len(conflict))
    if not ok:
        die("有 part 分到 0 面，已中止（未写任何文件）")

    used = set()
    for p in parts:
        used.update(assign[p["node"]])

    print("拆分中…")
    created = []
    for p in parts:
        pivot = Vector(p["pivot"])
        faces = assign[p["node"]]
        me = make_mesh_from_faces(p["node"], src, faces, pivot)
        ob = bpy.data.objects.new(p["node"], me)
        bpy.context.scene.collection.objects.link(ob)
        ob.parent = src
        ob.matrix_parent_inverse = Matrix.Identity(4)
        ob.location = pivot
        created.append((p["node"], len(faces)))

    rest = [fi for fi in range(len(src.data.polygons)) if fi not in used]
    keep = make_mesh_from_faces(src.name, src, rest, Vector((0, 0, 0)))
    old = src.data
    src.data = keep
    src.matrix_world = Matrix.Identity(4)
    if old.users == 0:
        bpy.data.meshes.remove(old)
    print("源剩余 %d 面；新建 %d 个节点" % (len(rest), len(created)))

    if o["export"] and o["dst"]:
        kw = dict(filepath=o["dst"], object_types={'MESH', 'EMPTY'}, use_selection=False,
                  use_custom_props=True, apply_scale_options='FBX_SCALE_ALL',
                  axis_forward='Y', axis_up='Z', use_mesh_modifiers=False,
                  add_leaf_bones=False, bake_space_transform=False,
                  use_triangles=True, embed_textures=False, path_mode='RELATIVE',
                  mesh_smooth_type='FACE')
        try:
            bpy.ops.export_scene.fbx(**kw)
        except TypeError as e:
            print("[!] 部分导出参数不支持，降级重试: %s" % e)
            for k in ("use_triangles", "mesh_smooth_type", "bake_space_transform"):
                kw.pop(k, None)
            bpy.ops.export_scene.fbx(**kw)
        print("已导出 " + o["dst"])

    tot_v = sum(len(x.data.vertices) for x in bpy.data.objects if x.type == 'MESH')
    tot_f = sum(len(x.data.polygons) for x in bpy.data.objects if x.type == 'MESH')
    print("汇总: 网格 %d / 顶点 %d / 面 %d"
          % (sum(1 for x in bpy.data.objects if x.type == 'MESH'), tot_v, tot_f))
    if tot_v > 65536:
        print("[!] 顶点 %d 超过 65536，AssetCooker 会失败" % tot_v)


main()
