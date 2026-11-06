"""锚点定位三合一（Blender 脚本）：渲图 → 叠网格 → 反算世界坐标 → 红球复核。

配合 references/23-mesh-import.md §5.0「点格子法」使用。
用户指不出坐标、只能指"图上哪块"时，用本脚本把"那块"变成世界坐标。

子命令
------
render  渲一张与参考图同视角的图；可选叠 A..T / 1..N 网格、可选打红球标记。
pick    把格子（M8 / M8:N9 / 逗号多格）或像素反算成世界坐标，输出 JSON；
        可选 --mark-shot 顺便渲一张带红球的复核图。

用法（Blender，不是 python）
---------------------------
blender -b -P pick_anchor.py -- render --blend model.blend --out ask_raw.png \
        --cam 12.6,6.2,4.9 --target 7.95,0.75,2.25 --lens 85 --res 2000x1600 --grid 20x16

blender -b -P pick_anchor.py -- pick --cam-json ask_raw.cam.json \
        --cell M8:N9 --mark-shot mark.png

参数
----
--blend PATH           .blend 源文件（render / pick 都要）
--out PATH             render 输出 png；同目录写 <out>.cam.json（相机 sidecar）
--cam x,y,z            相机世界坐标
--target x,y,z         视线目标点（决定朝向；用 track_quat('-Z','Y')，与历史脚本一致）
--fit [AZIM]           不给机位时按包围球自动取景，AZIM 为方位角（默认 42°）
--fit-elev DEG         自动取景的仰角，默认 20
--lens MM              透视焦距，默认 85；给了 --ortho 则忽略
--ortho SCALE          正交相机 ortho_scale（视图宽/高较大者对应的世界尺寸）
--res WxH              分辨率，默认 2000x1600
--grid CxR             网格列数 x 行数（列标 A..，行标 1..），默认 20x16
--cell-labels          每格左上角再打一个 "M8" 小标（格子够大时更省沟通）
--mark x,y,z           在渲染图上打红球（可重复，最多 8 个）
--mark-radius M        红球半径，默认按场景包围盒对角线 1%（太小就 --mark-radius 指定）
--color TEXTURE|SINGLE workbench 着色方式，默认 TEXTURE；判定拆件用 SINGLE
--cell SPEC            pick 用：M8 单格 / M8:N9 区域（取中心）/ M8,M9 多格
--px x,y               pick 用：直接给像素（左上角为原点）
--mark-out PATH        pick 用：在反算点上打红球另存一张
--cam-json PATH        pick 用：读 render 写的 sidecar，避免手抄相机参数抄错
--json                 pick 时输出纯 JSON（默认人读 + JSON 混排则用 --quiet）

退出码：0 正常；2 参数/文件错；3 反算有 miss（几何没打中）。
"""

import sys
import os
import json
import math

import bpy
import numpy as np
from mathutils import Vector

# ---------------------------------------------------------------- 5x7 点阵字体
# 只含 0-9 A-Z：网格标号只需要这些。每字符 7 行 x 5 列，'1' 为亮。
FONT = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11111", "00010", "00100", "00010", "00001", "10001", "01110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11100", "10010", "10001", "10001", "10001", "10010", "11100"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("01110", "00100", "00100", "00100", "00100", "00100", "01110"),
    "J": ("00111", "00010", "00010", "00010", "00010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "11011", "10001"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
}
GLYPH_W, GLYPH_H = 5, 7


# ------------------------------------------------------------------ 参数解析
def parse_argv():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv:
        sys.exit(__doc__)
    cmd = argv[0]
    opts, flags = {}, set()
    i = 1
    while i < len(argv):
        tok = argv[i]
        if not tok.startswith("--"):
            i += 1
            continue
        key = tok[2:]
        if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            val = argv[i + 1]
            if key in opts:
                opts[key] = opts[key] + [val] if isinstance(opts[key], list) else [opts[key], val]
            else:
                opts[key] = val
            i += 2
        else:
            flags.add(key)
            i += 1
    return cmd, opts, flags


def as_list(v):
    return v if isinstance(v, list) else [v]


def _abs(p):
    """Blender 的 render.filepath 不认相对路径（会落到盘符根），一律转绝对。"""
    return p if os.path.isabs(p) else os.path.abspath(p)


def vec3(s):
    return Vector([float(x) for x in s.split(",")])


def parse_res(s):
    if "x" in s.lower():
        w, h = s.lower().split("x")
    else:
        w, h = s.split(":")
    return int(float(w)), int(float(h))


def parse_grid(s):
    w, h = s.lower().split("x")
    cols, rows = int(w), int(h)
    if not (1 <= cols <= 26):
        sys.exit("[pick_anchor] --grid 列数必须在 1..26（标签只有 A..Z）")
    if not (1 <= rows <= 99):
        sys.exit("[pick_anchor] --grid 行数必须在 1..99")
    return cols, rows


# ------------------------------------------------------------------ 场景准备
def open_blend(path):
    path = _abs(path)
    if not os.path.isfile(path):
        sys.exit("[pick_anchor] 找不到 blend: %s" % path)
    bpy.ops.wm.open_mainfile(filepath=path)
    return bpy.context.scene


def make_camera(scene, loc, tgt, lens=85.0, ortho=None, sensor=36.0):
    cam_data = bpy.data.cameras.new("PICKCAM")
    cam = bpy.data.objects.new("PICKCAM", cam_data)
    scene.collection.objects.link(cam)
    if ortho:
        cam_data.type = "ORTHO"
        cam_data.ortho_scale = float(ortho)
    else:
        cam_data.lens = float(lens)
        cam_data.sensor_width = sensor
        cam_data.sensor_fit = "AUTO"
    cam.location = loc
    cam.rotation_euler = (tgt - loc).to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam
    return cam


def setup_render(scene, res, color_type="TEXTURE"):
    w, h = res
    scene.render.engine = "BLENDER_WORKBENCH"
    sh = scene.display.shading
    sh.light = "STUDIO"
    sh.color_type = color_type
    sh.show_shadows = True
    sh.show_cavity = True
    sh.cavity_type = "BOTH"
    sh.cavity_ridge_factor = 2.5
    sh.cavity_valley_factor = 2.5
    scene.render.image_settings.file_format = "PNG"
    scene.render.resolution_x, scene.render.resolution_y = w, h
    scene.render.resolution_percentage = 100


def scene_bbox():
    lo = Vector((1e18, 1e18, 1e18))
    hi = Vector((-1e18, -1e18, -1e18))
    for ob in bpy.context.scene.objects:
        if ob.type != "MESH":
            continue
        for c in ob.bound_box:
            p = ob.matrix_world @ Vector(c)
            for k in range(3):
                lo[k] = min(lo[k], p[k])
                hi[k] = max(hi[k], p[k])
    if lo.x > hi.x:                       # 场景里没有网格
        return Vector((-1, -1, -1)), Vector((1, 1, 1))
    return lo, hi


def scene_diag():
    """场景包围盒对角线，用于红球默认半径。"""
    lo, hi = scene_bbox()
    return (hi - lo).length


def fit_camera(res, lens, azim_deg=42.0, elev_deg=20.0, pad=1.08):
    """按包围盒 8 角自动取景：方位角/仰角给角度，返回 (loc, target)。

    逐个角点求"要多远才刚好装下"，取最大值——比用包围球半径准得多，
    细长物体（飞机、舰船）不会被缩成一小团。
    """
    lo, hi = scene_bbox()
    center = (lo + hi) / 2.0
    w, h = res
    sensor = 36.0
    if w >= h:
        tan_w = (sensor / 2.0) / lens
        tan_h = tan_w * (h / float(w))
    else:
        tan_h = (sensor / 2.0) / lens
        tan_w = tan_h * (w / float(h))
    az, el = math.radians(azim_deg), math.radians(elev_deg)
    d = Vector((math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)))
    # 相机正交基
    up_ref = Vector((0, 0, 1))
    right = d.cross(up_ref)
    if right.length < 1e-6:
        right = Vector((1, 0, 0))
    right.normalize()
    up = right.cross(d).normalized()
    dist = 0.0
    for ix in (lo.x, hi.x):
        for iy in (lo.y, hi.y):
            for iz in (lo.z, hi.z):
                v = Vector((ix, iy, iz)) - center
                depth = -v.dot(d)                       # 朝相机方向为正
                need = depth + max(abs(v.dot(right)) / max(tan_w, 1e-6),
                                   abs(v.dot(up)) / max(tan_h, 1e-6))
                dist = max(dist, need)
    dist = max(dist, 1e-3) * pad
    return center + d * dist, center


def add_marker(points, radius, name="PICKMARK", color=(1.0, 0.0, 0.0, 1.0)):
    for idx, p in enumerate(points):
        bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, location=p)
        ob = bpy.context.active_object
        ob.name = "%s_%02d" % (name, idx)
        mat = bpy.data.materials.new("%s_mat_%02d" % (name, idx))
        mat.diffuse_color = color
        ob.data.materials.append(mat)


# --------------------------------------------------------------- 像素 <-> 格子
def grid_px_bounds(cols, rows, res):
    """每格像素宽高与左上原点。"""
    w, h = res
    return w / float(cols), h / float(rows)


def cell_to_rect(spec, cols, rows, res):
    """'M8' / 'M8:N9' -> (x0,y0,x1,y1) 像素矩形（左上原点）。"""
    def one(tag):
        tag = tag.strip().upper()
        col = ord(tag[0]) - ord("A")
        row = int(tag[1:]) - 1
        if not (0 <= col < cols) or not (0 <= row < rows):
            sys.exit("[pick_anchor] 格子 %s 越界（网格 %dx%d，列 A..%s 行 1..%d）"
                     % (tag, cols, rows, chr(ord("A") + cols - 1), rows))
        return col, row

    cw, ch = grid_px_bounds(cols, rows, res)
    if ":" in spec:
        a, b = spec.split(":", 1)
        c0, r0 = one(a)
        c1, r1 = one(b)
    else:
        c0, r0 = one(spec)
        c1, r1 = c0, r0
    xs = sorted((c0, c1))
    ys = sorted((r0, r1))
    return (xs[0] * cw, ys[0] * ch, (xs[1] + 1) * cw, (ys[1] + 1) * ch)


# ---------------------------------------------------------------- 网格叠加绘制
def load_png(path):
    img = bpy.data.images.load(path, check_existing=False)
    img.colorspace_settings.name = "Non-Color"  # 避免 sRGB->线性 往返色偏
    w, h = img.size
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    return img, buf.reshape(h, w, 4), w, h


def blend_px(arr, y0, y1, x0, x1, rgba, alpha=1.0):
    """在 arr（行 0 = 底部）上按矩形混色，坐标用左上原点。"""
    h, w = arr.shape[0], arr.shape[1]
    y0, y1 = max(0, int(y0)), min(h, int(y1))
    x0, x1 = max(0, int(x0)), min(w, int(x1))
    if y0 >= y1 or x0 >= x1:
        return
    r0, r1 = h - y1, h - y0
    block = arr[r0:r1, x0:x1, :]
    if alpha >= 1.0:
        block[..., 0:3] = rgba[0:3]
        block[..., 3] = 1.0
    else:
        block[..., 0:3] = block[..., 0:3] * (1 - alpha) + np.array(rgba[0:3]) * alpha


def draw_text(arr, x, y, text, scale, rgba, pad=True):
    """左上原点画 5x7 点阵字；pad=True 时先铺一层深色底提高可读性。"""
    wpx = (GLYPH_W + 1) * len(text) * scale
    hpx = GLYPH_H * scale
    if pad:
        blend_px(arr, y - scale, y + hpx + scale, x - scale, x + wpx + scale,
                 (0.05, 0.05, 0.05), alpha=0.75)
    cx = x
    for ch in text.upper():
        g = FONT.get(ch)
        if g:
            for ry in range(GLYPH_H):
                for rx in range(GLYPH_W):
                    if g[ry][rx] == "1":
                        blend_px(arr, y + ry * scale, y + (ry + 1) * scale,
                                 cx + rx * scale, cx + (rx + 1) * scale, rgba)
        cx += (GLYPH_W + 1) * scale


def overlay_grid(png_in, png_out, cols, rows, cell_labels=False):
    img, arr, w, h = load_png(png_in)
    cw, ch = w / float(cols), h / float(rows)
    line = (1.0, 0.92, 0.15)
    # 网格线（1~2 px）
    lw = max(1, int(round(min(w, h) / 900.0)))
    for c in range(cols + 1):
        x = int(round(c * cw))
        blend_px(arr, 0, h, x, x + lw, line, alpha=0.55)
    for r in range(rows + 1):
        y = int(round(r * ch))
        blend_px(arr, y, y + lw, 0, w, line, alpha=0.55)

    scale = max(2, int(round(min(cw, ch) / 24.0)))
    text_h = GLYPH_H * scale
    # 列字母：格子上沿（首行）；行号：格子下沿（首列）——错开，免得第一格挤成一团
    for c in range(cols):
        draw_text(arr, int(c * cw + cw / 2 - 2.5 * scale), 6,
                  chr(ord("A") + c), scale, (1.0, 1.0, 1.0))
    for r in range(rows):
        draw_text(arr, 6, int((r + 1) * ch - text_h - 6),
                  str(r + 1), scale, (1.0, 1.0, 1.0))
    # 每格小标（可选）：画在格子右下角，避免与行号/列字母打架
    if cell_labels and cw > 70 and ch > 50:
        s2 = max(1, int(round(min(cw, ch) / 60.0)))
        tw = (GLYPH_W + 1) * 3 * s2
        for c in range(cols):
            for r in range(rows):
                draw_text(arr, int((c + 1) * cw - tw - 4 * s2),
                          int((r + 1) * ch - GLYPH_H * s2 - 4 * s2),
                          "%s%d" % (chr(ord("A") + c), r + 1), s2, (0.62, 0.66, 0.70))

    img.pixels.foreach_set(arr.ravel())
    img.filepath_raw = png_out
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
    return png_out


# ---------------------------------------------------------------------- 反算
def make_camera_state(loc, tgt, lens, ortho, sensor=36.0):
    return {"loc": list(loc), "tgt": list(tgt), "lens": float(lens),
            "ortho": float(ortho) if ortho else None, "sensor": float(sensor)}


def ray_at_pixel(scene, cam, px, res, ortho=None):
    """像素（左上原点）→ 世界命中点。返回 (hit, xyz, normal, objname)。"""
    w, h = res
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    M = cam.matrix_world
    nx = (px[0] + 0.5) / w * 2.0 - 1.0
    ny = 1.0 - (px[1] + 0.5) / h * 2.0
    if ortho:
        right = M.col[0].xyz.normalized()
        up = M.col[1].xyz.normalized()
        fwd = -M.col[2].xyz.normalized()
        half_w = (float(ortho) / 2.0) if w >= h else (float(ortho) / 2.0) * (w / float(h))
        half_h = half_w * (h / float(w))
        origin = M.translation + right * (nx * half_w) + up * (ny * half_h)
        hit, loc, nor, idx, ob, _ = scene.ray_cast(dg, origin, fwd)
    else:
        lens = cam.data.lens
        sensor = cam.data.sensor_width
        if w >= h:
            half_w = (sensor / 2.0) / lens
            half_h = half_w * (h / float(w))
        else:
            half_h = (sensor / 2.0) / lens
            half_w = half_h * (w / float(h))
        d = Vector((nx * half_w, ny * half_h, -1.0))
        dirw = (M.to_3x3() @ d).normalized()
        hit, loc, nor, idx, ob, _ = scene.ray_cast(dg, M.translation, dirw)
    if hit:
        return True, loc, nor, ob.name
    return False, None, None, None


# ---------------------------------------------------------------------- 子命令
def cmd_render(opts, flags):
    sc = open_blend(opts["blend"])
    res = parse_res(opts.get("res", "2000x1600"))
    cols, rows = parse_grid(opts.get("grid", "20x16"))

    if "fit" in opts or "fit" in flags or "cam" not in opts:
        azim = float(opts["fit"]) if isinstance(opts.get("fit"), str) else 42.0
        elev = float(opts["fit-elev"]) if "fit-elev" in opts else 20.0
        lens = float(opts.get("lens", 50.0))
        loc, tgt = fit_camera(res, lens, azim, elev)
        print("[pick_anchor] 自动取景 azim=%.0f elev=%.0f lens=%.0f -> cam=(%.3f,%.3f,%.3f) target=(%.3f,%.3f,%.3f)"
              % (azim, elev, lens, loc.x, loc.y, loc.z, tgt.x, tgt.y, tgt.z))
        camera = make_camera_state(loc, tgt, lens, opts.get("ortho"))
    else:
        camera = make_camera_state(vec3(opts["cam"]), vec3(opts["target"]),
                                   opts.get("lens", 85.0), opts.get("ortho"))
    setup_render(sc, res, opts.get("color", "TEXTURE"))
    cam = make_camera(sc, Vector(camera["loc"]), Vector(camera["tgt"]),
                      camera["lens"], camera["ortho"], camera["sensor"])

    out = _abs(opts["out"])
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    # 1) 原始图（标记球必须在原始图之后加，否则会进 raw）
    sc.render.filepath = out
    bpy.ops.render.render(write_still=True)
    print("[pick_anchor] raw  -> %s" % out)

    # 2) 网格
    if "grid" in opts or "cell-labels" in flags:
        grid_out = _abs(opts.get("grid-out") or (os.path.splitext(out)[0] + "_grid.png"))
        overlay_grid(out, grid_out, cols, rows, cell_labels=("cell-labels" in flags))
        print("[pick_anchor] grid -> %s" % grid_out)

    # 3) 红球复核（复核图也叠网格：用户能直接说"偏左两格"）
    marks = as_list(opts["mark"]) if "mark" in opts else []
    if marks:
        pts = [vec3(m) for m in marks]
        radius = float(opts.get("mark-radius") or scene_diag() * 0.01)
        add_marker(pts, radius)
        mark_out = _abs(opts.get("mark-out") or (os.path.splitext(out)[0] + "_mark.png"))
        sc.render.filepath = mark_out
        bpy.ops.render.render(write_still=True)
        print("[pick_anchor] mark -> %s (r=%.4f, %d 个)" % (mark_out, radius, len(pts)))
        if "grid" in opts:
            overlay_grid(mark_out, mark_out, cols, rows, cell_labels=("cell-labels" in flags))
            print("[pick_anchor] mark 图已叠网格")

    # 4) 相机 sidecar：pick 直接读它，杜绝手抄错位
    side = {"res": list(res), "grid": [cols, rows], "camera": camera}
    sidecar = _abs(opts.get("cam-out") or (out + ".cam.json"))
    with open(sidecar, "w", encoding="utf-8") as f:
        json.dump(side, f, ensure_ascii=False, indent=2)
    print("[pick_anchor] cam  -> %s" % sidecar)


def load_camera(opts):
    if "cam-json" in opts:
        with open(_abs(opts["cam-json"]), encoding="utf-8") as f:
            side = json.load(f)
        c = side["camera"]
        return (Vector(c["loc"]), Vector(c["tgt"]), c["lens"], c["ortho"],
                c["sensor"], tuple(side["res"]), tuple(side["grid"]))
    res = parse_res(opts.get("res", "2000x1600"))
    cols, rows = parse_grid(opts.get("grid", "20x16"))
    return (vec3(opts["cam"]), vec3(opts["target"]), float(opts.get("lens", 85.0)),
            opts.get("ortho"), 36.0, res, (cols, rows))


def cmd_pick(opts, flags):
    sc = open_blend(opts["blend"])
    loc, tgt, lens, ortho, sensor, res, grid = load_camera(opts)
    cols, rows = grid
    setup_render(sc, res, opts.get("color", "TEXTURE"))
    cam = make_camera(sc, loc, tgt, lens, ortho, sensor)

    queries = []  # (label, px)
    if "cell" in opts:
        for spec in as_list(opts["cell"]):
            for part in spec.split(";"):
                part = part.strip()
                if not part:
                    continue
                if part.count(",") and ":" not in part:
                    for sub in part.split(","):
                        x0, y0, x1, y1 = cell_to_rect(sub, cols, rows, res)
                        queries.append((sub.strip().upper(), ((x0 + x1) / 2, (y0 + y1) / 2)))
                else:
                    x0, y0, x1, y1 = cell_to_rect(part, cols, rows, res)
                    queries.append((part.strip().upper(), ((x0 + x1) / 2, (y0 + y1) / 2)))
    if "px" in opts:
        for spec in as_list(opts["px"]):
            for part in spec.split(";"):
                if part.strip():
                    p = [float(v) for v in part.split(",")]
                    queries.append(("px", (p[0], p[1])))
    if not queries:
        sys.exit("[pick_anchor] pick 需要 --cell M8 或 --px x,y")

    results, misses, hits = [], 0, []
    for label, px in queries:
        hit, p, n, name = ray_at_pixel(sc, cam, px, res, ortho)
        row = {"cell": label, "px": [round(px[0], 1), round(px[1], 1)], "hit": bool(hit)}
        if hit:
            row.update({"object": name,
                        "xyz": [round(p.x, 4), round(p.y, 4), round(p.z, 4)],
                        "normal": [round(n.x, 3), round(n.y, 3), round(n.z, 3)]})
            hits.append(p)
            print("  %-3s px(%7.1f,%7.1f) -> %-16s (%8.4f, %8.4f, %8.4f)  n=(%5.2f,%5.2f,%5.2f)"
                  % (label, px[0], px[1], name, p.x, p.y, p.z, n.x, n.y, n.z))
        else:
            misses += 1
            print("  %-3s px(%7.1f,%7.1f) -> MISS（射线没打中任何网格，检查 --cam/--target 是否与渲图一致）"
                  % (label, px[0], px[1]))
        results.append(row)

    out = {"res": list(res), "grid": [cols, rows], "results": results,
           "camera": make_camera_state(loc, tgt, lens, ortho, sensor)}
    if hits:
        cx = sum(p.x for p in hits) / len(hits)
        cy = sum(p.y for p in hits) / len(hits)
        cz = sum(p.z for p in hits) / len(hits)
        out["center"] = [round(cx, 4), round(cy, 4), round(cz, 4)]
        print("[pick_anchor] 落点均值 = (%.4f, %.4f, %.4f)" % (cx, cy, cz))
    print(json.dumps(out, ensure_ascii=False, indent=2))

    if "mark-out" in opts and hits:
        radius = float(opts.get("mark-radius") or scene_diag() * 0.01)
        add_marker(hits, radius)
        mark_out = _abs(opts["mark-out"])
        sc.render.filepath = mark_out
        bpy.ops.render.render(write_still=True)
        print("[pick_anchor] mark -> %s (r=%.4f)" % (mark_out, radius))
        if "grid" in opts or "cam-json" in opts:      # cam-json 里带 grid，默认叠
            overlay_grid(mark_out, mark_out, cols, rows, cell_labels=("cell-labels" in flags))
            print("[pick_anchor] mark 图已叠网格")

    return 3 if misses else 0


def main():
    cmd, opts, flags = parse_argv()
    if cmd == "render":
        for k in ("blend", "out"):
            if k not in opts:
                sys.exit("[pick_anchor] render 缺 --%s" % k)
        if "cam" not in opts and "fit" not in opts and "fit" not in flags:
            sys.exit("[pick_anchor] render 需要 --cam/--target，或用 --fit 自动取景")
        if "cam" in opts and "target" not in opts:
            sys.exit("[pick_anchor] 给了 --cam 就必须给 --target（相机看哪里）")
        cmd_render(opts, flags)
        sys.exit(0)
    if cmd == "pick":
        if "blend" not in opts:
            sys.exit("[pick_anchor] pick 缺 --blend")
        if "cam-json" not in opts:
            for k in ("cam", "target"):
                if k not in opts:
                    sys.exit("[pick_anchor] pick 缺 --%s（或直接给 --cam-json）" % k)
        sys.exit(cmd_pick(opts, flags))
    sys.exit("[pick_anchor] 未知子命令 %r，只支持 render / pick" % cmd)


main()
