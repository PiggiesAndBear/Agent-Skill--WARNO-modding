# -*- coding: utf-8 -*-
"""卡面合成（普通 Python + PIL）：透明底渲染图 → 512×288 深色渐变卡面（两段式第二段）。

参数是 PT100 / 2S25 / LAV-600 三个单位实测定稿、逐值一致的那套：
深蓝灰径向渐变（中心偏左上）+ 细噪点压色带 + 底部椭圆接触阴影 + vignette。
三个单位合成后与先上线的 OBJECT_685.png 四角像素逐值相同，风格自证统一。

用法：python card_composite.py --raw card_raw.png --out card_final.png
产物：512×288 RGB（不透明）。

注意：车体本体不加边框、不加额外阴影；接触阴影只给一点点防「飘」。
换风格时不要在这里加东西——先确认现有单位卡池是不是真的需要。
"""
import argparse
import math
import os

from PIL import Image, ImageDraw, ImageFilter

p = argparse.ArgumentParser()
p.add_argument("--raw", required=True, help="透明底 PNG（render_card.py 的产物）")
p.add_argument("--out", required=True)
a = p.parse_args()

RAW = os.path.abspath(a.raw)
DST = os.path.abspath(a.out)
W, H = 512, 288

# 背景：中心 (0.100,0.115,0.140) → 边缘 (0.022,0.026,0.034)；径向 r**0.85
C_IN = (0.100, 0.115, 0.140)
C_OUT = (0.022, 0.026, 0.034)

bg = Image.new("RGB", (W, H))
px = bg.load()
cx, cy = W * 0.46, H * 0.40
maxr = math.hypot(max(cx, W - cx), max(cy, H - cy))
for y in range(H):
    for x in range(W):
        r = math.hypot(x - cx, y - cy) / maxr
        t = min(1.0, r ** 0.85)
        px[x, y] = tuple(
            int(round(255 * (C_IN[i] + (C_OUT[i] - C_IN[i]) * t))) for i in range(3)
        )

# 细噪点：压掉渐变的色带（官方卡面也有轻微噪点）
noise = Image.effect_noise((W, H), 6).convert("L")
bg = Image.blend(bg, Image.merge("RGB", (noise, noise, noise)), 0.04)

raw = Image.open(RAW).convert("RGBA")
if raw.size != (W, H):
    raw = raw.resize((W, H), Image.LANCZOS)

# 载具底部一点点接触阴影，避免「飘」
sh = Image.new("L", (W, H), 0)
d = ImageDraw.Draw(sh)
d.ellipse([W * 0.16, H * 0.74, W * 0.84, H * 0.98], fill=110)
sh = sh.filter(ImageFilter.GaussianBlur(14))
bg = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), bg, sh.point(lambda v: int(v * 0.55)))

out = bg.convert("RGBA")
out.alpha_composite(raw)

# vignette：四周压暗 0.45*(r-0.55)**1.6
vig = Image.new("L", (W, H), 0)
vp = vig.load()
for y in range(H):
    for x in range(W):
        r = math.hypot((x - W / 2) / (W / 2), (y - H / 2) / (H / 2))
        vp[x, y] = int(max(0, min(255, 255 * (1.0 - 0.45 * max(0.0, r - 0.55) ** 1.6))))
out = Image.composite(out, Image.new("RGBA", (W, H), (0, 0, 0, 255)), vig)

res = out.convert("RGB")
res.save(DST, "PNG", optimize=True)
print("→ %s  %dx%d  %d B" % (DST, res.size[0], res.size[1], os.path.getsize(DST)))
