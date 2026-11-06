# -*- coding: utf-8 -*-
"""set_card_art.py —— 给单位设置自定义卡面（ButtonTexture）

三步一条命令：
  1. 图规范化：按目标宽高比居中裁切（cover，不拉伸）→ LANCZOS 缩放 → RGBA → 落到
     <mod>/GameData/Assets/2D/Interface/Common/UnitsIcons/<阵营>/<名>.png
  2. 纹理 bank 注册：<mod>/GameData/Generated/UserInterface/Textures/ButtonTexturesUnites.ndf
     的 UnitButtonTextureAdditionalBank.Textures MAP 收尾前追加一条 token
  3. 单位引用：Descriptor_Unit_<X> 块内 ButtonTexture 改指该 token

用法：
  python set_card_art.py --mod <mod根> --png <图> --name <UnitName> \
      --units Descriptor_Unit_A Descriptor_Unit_B [--faction PACT] [--dry]

  --mod        mod 根目录（含 GameData；也可直接给 GameData 路径）
  --png        源图（任意尺寸；会自动裁方缩放）
  --name       卡面名，token = Texture_Button_Unit_<name>，PNG 文件名 = <name>.png
  --units      要改的单位，可写 Descriptor_Unit_X 或裸 X；可重复/多个
  --faction    UnitsIcons 下的子目录，默认 PACT；NATO / 自建国家目录都行
  --size       目标尺寸：默认 512x288（16:9）；也可写 256 出正方形
  --from       可选：base 的 ButtonTexturesUnites.ndf，mod 里没有时据此初始化
  --dry        只打印计划，不写盘

幂等：token 已注册 / 单位已指向 → 跳过。改文件前备份 <file>.<ts>.before_cardart。
行尾（CRLF/LF）随原文件，全程按字节切片，不做全文 replace。
"""
import argparse
import datetime
import os
import shutil
import sys

TEX_REL = 'GameData/Generated/UserInterface/Textures/ButtonTexturesUnites.ndf'
UNIT_REL = 'GameData/Generated/Gameplay/Gfx/UniteDescriptor.ndf'
ICON_DIR = 'GameData/Assets/2D/Interface/Common/UnitsIcons'


# ------------------------------------------------------------------ 基础工具
def die(msg):
    raise SystemExit('[ERROR] ' + msg)


def norm_mod(p):
    p = os.path.abspath(p)
    if os.path.basename(p) == 'GameData':
        p = os.path.dirname(p)
    if not os.path.isdir(os.path.join(p, 'GameData')):
        die('不是 mod 根（缺 GameData/）：%s' % p)
    return p


def eol_of(data):
    crlf = data.count(b'\r\n')
    lf = data.count(b'\n') - crlf
    return b'\r\n' if crlf > lf else b'\n'


def backup(path, dry):
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    dst = path + '.' + ts + '.before_cardart'
    if not dry:
        shutil.copy2(path, dst)
    print('  backup -> %s' % os.path.basename(dst))


def need_pil():
    try:
        from PIL import Image
    except ImportError:
        die('需要 Pillow：pip install pillow')
    return Image


# ------------------------------------------------------------------ 1. PNG
def parse_size(s):
    """'256' -> (256,256)；'512x288' -> (512,288)"""
    s = str(s).lower().strip()
    if 'x' in s:
        w, h = s.split('x', 1)
        return int(w), int(h)
    v = int(s)
    return v, v


def place_png(mod, src, name, faction, size_wh, dry):
    Image = need_pil()
    TW, TH = size_wh
    dst_rel = '%s/%s/%s.png' % (ICON_DIR, faction, name)
    dst = os.path.join(mod, dst_rel.replace('/', os.sep))
    im = Image.open(src)
    w, h = im.size
    if im.mode != 'RGBA':
        im = im.convert('RGBA')
    # 按目标宽高比做 cover 裁切（居中）：不拉伸、不补边
    if abs(w / float(h) - TW / float(TH)) > 1e-6:
        if w / float(h) > TW / float(TH):     # 源更宽 -> 裁左右
            nw = int(round(h * TW / float(TH)))
            box = ((w - nw) // 2, 0, (w - nw) // 2 + nw, h)
        else:                                  # 源更高 -> 裁上下
            nh = int(round(w * TH / float(TW)))
            box = (0, (h - nh) // 2, w, (h - nh) // 2 + nh)
        im = im.crop(box)
        print('  crop  %dx%d -> %dx%d（按 %d:%d 居中）'
              % (w, h, im.size[0], im.size[1], TW, TH))
    if im.size != (TW, TH):
        im = im.resize((TW, TH), Image.LANCZOS)
        print('  scale -> %d x %d LANCZOS' % (TW, TH))
    if not dry:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        im.save(dst, 'PNG')
    print('  png   %s  (%d x %d %s)' % (dst_rel, TW, TH, im.mode))
    # 注册行里的 FileName 是 "GameData:/..." 前缀，这里回传相对 GameData 的部分
    return dst_rel[len('GameData/'):]


# ------------------------------------------------------------------ 2. 纹理 bank
def register_token(mod, name, png_rel, base_from, dry):
    path = os.path.join(mod, TEX_REL.replace('/', os.sep))
    token = 'Texture_Button_Unit_%s' % name

    if not os.path.exists(path):
        if base_from and os.path.exists(base_from):
            if dry:
                print('  [dry] 用 base 初始化 %s' % TEX_REL)
            else:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                shutil.copy2(base_from, path)
                print('  init  %s（来自 %s）' % (TEX_REL, os.path.basename(base_from)))
        else:
            die('缺少 %s。\n       这是 AbstractButtonTextureFileWriter 的产物，mod 侧必须是'
                '**整份拷贝**（不能只写自己那一条）；\n       把游戏/基础包的该文件拷到此处，'
                '或用 --from <路径> 指过去。' % TEX_REL)

    data = open(path, 'rb').read()
    if token.encode() in data:
        print('  [skip] token 已注册：%s' % token)
        return token

    idx = data.rfind(b'\n    ]')
    if idx < 0:
        die('%s 里找不到 MAP 收尾 "\\n    ]"' % TEX_REL)
    line = ('        ("%s", MAP [( ~/ComponentState/Normal, TUIResourceTexture( '
            'FileName = "GameData:/%s"))]),' % (token, png_rel)).encode('utf-8')
    line += eol_of(data)

    before = data.count(b'"Texture_Button_Unit_')
    if not dry:
        backup(path, dry)
        open(path, 'wb').write(data[:idx + 1] + line + data[idx + 1:])
    after = open(path, 'rb').read().count(b'"Texture_Button_Unit_') if not dry else before + 1
    if after != before + 1:
        die('注册后 token 数异常：%d -> %d' % (before, after))
    print('  reg   %s  (token %d -> %d)' % (token, before, after))
    return token


# ------------------------------------------------------------------ 3. 单位块
def unit_block(data, unit_name):
    """返回 (start, end)；块以 \\nexport Descriptor_Unit_X is 起，到下一个 \\nexport 止。"""
    name = unit_name if unit_name.startswith('Descriptor_Unit_') else 'Descriptor_Unit_' + unit_name
    head = ('\nexport %s is' % name).encode()
    if data.startswith(head[1:]):
        s = 0
    else:
        s = data.find(head)
        if s < 0:
            return None
    n = data.find(b'\nexport ', s + 1)
    return (s, len(data) if n < 0 else n), name


def patch_units(mod, token, units, dry):
    path = os.path.join(mod, UNIT_REL.replace('/', os.sep))
    if not os.path.exists(path):
        die('缺少 %s' % UNIT_REL)
    data = open(path, 'rb').read()
    eol_before = data.count(b'\r\n')
    changed = 0
    plan = []

    for u in units:
        r = unit_block(data, u)
        if r is None:
            die('找不到单位块：%s' % u)
        (s, e), name = r
        blk = data[s:e]
        i = blk.find(b'ButtonTexture')
        if i < 0:
            die('%s 块内没有 ButtonTexture（TUnitUIModuleDescriptor 缺失？）' % name)
        q1 = blk.find(b"'", i)
        q2 = blk.find(b"'", q1 + 1)
        if q1 < 0 or q2 < 0:
            die('%s 的 ButtonTexture 取值格式异常' % name)
        old = blk[q1 + 1:q2].decode('utf-8', 'replace')
        if old == token:
            print('  [skip] %s 已指向新卡面' % name)
            continue
        plan.append((name, old, s + q1 + 1, s + q2))

    for name, old, a, b in plan:
        print('  unit  %s  %s -> %s' % (name, old, token))
        changed += 1

    if plan and not dry:
        backup(path, dry)
        for name, old, a, b in sorted(plan, key=lambda x: -x[2]):
            data = data[:a] + token.encode() + data[b:]
        open(path, 'wb').write(data)
        new = open(path, 'rb').read()
        if new.count(b'\r\n') != eol_before:
            die('行尾被改动了（CRLF %d -> %d），已中止' % (eol_before, new.count(b'\r\n')))
        if new.count(token.encode()) != data.count(token.encode()):
            die('写入校验失败')
    return changed


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description='给 WARNO 单位设置自定义卡面（ButtonTexture）')
    ap.add_argument('--mod', required=True)
    ap.add_argument('--png', required=True)
    ap.add_argument('--name', required=True)
    ap.add_argument('--units', nargs='+', required=True)
    ap.add_argument('--faction', default='PACT')
    ap.add_argument('--size', default='512x288',
                    help='目标尺寸，WxH（默认 512x288，16:9）或单边正方形')
    ap.add_argument('--from', dest='base_from', default=None)
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()

    if not os.path.exists(a.png):
        die('源图不存在：%s' % a.png)
    mod = norm_mod(a.mod)
    size_wh = parse_size(a.size)
    print('mod  : %s' % mod)
    print('name : %s   faction: %s   size: %dx%d%s'
          % (a.name, a.faction, size_wh[0], size_wh[1], '   [DRY]' if a.dry else ''))

    png_rel = place_png(mod, a.png, a.name, a.faction, size_wh, a.dry)
    token = register_token(mod, a.name, png_rel, a.base_from, a.dry)
    n = patch_units(mod, token, a.units, a.dry)

    print('\n%s  改 %d 个单位。验收：编译日志里找 UnitsIcons/%s/%s.tgv，再进游戏看卡池。'
          % ('DRY-RUN 结束' if a.dry else 'DONE', n, a.faction, a.name))
    return 0


if __name__ == '__main__':
    sys.exit(main())
