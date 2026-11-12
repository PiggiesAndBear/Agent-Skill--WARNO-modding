# -*- coding: utf-8 -*-
"""按单位名克隆一套注册，并顺带给出该单位的「引用闭包」（哪些文件、哪些对象）。

【原理】
----
WARNO 的单位不是一个对象，是**一组互相引用的对象**散在十来个 NDF 里：
单位本体 → 武器描述器 → 弹药（不克隆，只改指向）→ depiction 三态（战场/Showroom/幽灵）
→ 描绘算子 → 订单可用性 → 师规则条目 → 牌组序列化的 UnitId → 本地化 token。

所以"造一个新单位"= **整块克隆这套对象 + 改名 + 换 GUID + 换 UnitId**，
再在三个**容器**里插一行（师规则的 `UnitRuleList`、`DeckSerializer` 的 `UnitIds`、
`UNITS.csv` 末尾）。容器不能整块克隆，只能插行 —— 这是本脚本区分"块克隆"与"容器插入"的原因。

三条硬约束（错了不报错，只在实机表现为买不到 / 存卡组崩 / 军械库闪退）：

* **`NameToken` ≤ 10 字符，且 `UNITS.csv` 必须有同名条目** —— 两条同时满足，
  缺一条就是 `Dictionary error: No string found for token`。
* **`UnitId` 必须全表唯一** —— 重复会让你买的单位和别人撞 ID，存卡组时报错。
* **每个 depiction 对象要各自注册**（战场 / Showroom / 幽灵三处），漏一处就是"军械库看不到"。

【操作】
----
  python clone_unit.py --mod <MOD_ROOT> --src M752_Lance_US --name Tochka_9K79

  # 只看闭包、不改任何文件（这就是"引用闭包收集器"的用法）
  python clone_unit.py --mod <MOD_ROOT> --src M752_Lance_US --list-only

  常用参数：
    --token TOCHKA9K79          本地化 token（缺省由 --name 推，自动截断到 10 字符）
    --display-name "Tochka 9K79"  面板显示名（缺省用 --name）
    --src-token M752LANCE       源 token，给了才替换
    --src-display "M752 Lance"  源显示名，给了才替换
    --deck-id 4692              牌组 UnitId（缺省自动 max+1）
    --division Descriptor_Deck_Division_SOV_ReconStrike_multi_Rule
    --max-pack 2 --num-in-pack 1 --xp 1.0,1.0,0.0,0.0
    --coalition PACT --country SOV --moving-type Wheel --terrain Wheel
    --ammo-map Ammo_SSM_MGM52_Lance=Ammo_SSM_9M79
    --dry                        只打印计划，不写盘
    --no-backup                  不写 .bak

【验收】
----
1. `--list-only` 的闭包表：单位本体必须命中，depiction 应有 3~4 个对象；
2. 克隆后 `python genmod_guard.py ...` 编译必须 `Mod Generation Success`；
3. 实机七问：买得到 / 能部署 / 能开火 / 军械库有卡 / 能存卡组 / 重进还在 / 弹体对得上。

【不要做的事】
----
* 不要整文件覆盖那批大 NDF（会把接收方别的单位冲掉）；
* 不要用裸数字（如 4692）当锚点 —— 会命中 GUID 字符串；
* 不要在容器块（NdfDepictionList / DeckSerializer / DivisionRules）上做块克隆。
"""
import os
import re
import sys
import uuid
import shutil
import argparse
import datetime

# 容器类文件：只插行，不整块克隆
CONTAINER_HINTS = ("NdfDepictionList", "DeckSerializer", "DivisionRules", "DivisionPacks",
                   "DeckPacks", "UNITS.csv")
SKIP_DIRS = ("Gen", ".base", "__pycache__")
MAX_BLOCK_LINES = 400          # 超过这个行数的"块"多半是容器，拒绝克隆

DECL_RE = re.compile(r"(?m)^(?:unnamed\s+\w+|export\s+\w+(?:\s+is\s+\w+)?|\w+\s+is\b)")


def argv_after_ddash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]


def parse_args():
    p = argparse.ArgumentParser(
        prog="clone_unit.py",
        description="按单位名克隆一整套 NDF 注册（并给出引用闭包）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--mod", help="Mod 根目录（含 GameData/Generated）；--undo 时可省")
    p.add_argument("--src", help="源单位名，如 M752_Lance_US（--undo 时可省）")
    p.add_argument("--name", help="新单位名，如 Tochka_9K79（--list-only 时可省）")
    p.add_argument("--list-only", action="store_true", help="只列引用闭包，不改文件")
    p.add_argument("--token", default="", help="本地化 token（≤10 字符）")
    p.add_argument("--display-name", default="", help="面板显示名")
    p.add_argument("--src-token", default="", help="源 token，给了才替换")
    p.add_argument("--src-display", default="", help="源显示名，给了才替换")
    p.add_argument("--guid", default="", help="新 GUID，缺省自动生成")
    p.add_argument("--deck-id", type=int, default=0, help="牌组 UnitId，0=自动 max+1")
    p.add_argument("--division", default="", help="放入哪个师的规则描述器名")
    p.add_argument("--max-pack", type=int, default=2)
    p.add_argument("--num-in-pack", type=int, default=1)
    p.add_argument("--xp", default="1.0,1.0,0.0,0.0")
    p.add_argument("--coalition", choices=["NATO", "PACT"], default="")
    p.add_argument("--country", default="", help="MotherCountry，如 SOV / US / RFA")
    p.add_argument("--moving-type", choices=["Track", "Wheel", "WheelAmphibious"], default="")
    p.add_argument("--terrain", choices=["Track", "Wheel"], default="", help="地形速度系数表")
    p.add_argument("--ammo-map", action="append", default=[], metavar="OLD=NEW",
                   help="弹药指向替换，可多次")
    p.add_argument("--rename-mesh", action="store_true",
                   help="连 GameData: 资源路径一起改名（默认**不改**：新单位复用源单位的模型/动画；"
                        "只有在已把资产目录（.fbx、贴图）按新名摆好时才加这个，"
                        "否则编译报 File not found）")
    p.add_argument("--dry", action="store_true")
    p.add_argument("--no-backup", action="store_true")
    p.add_argument("--undo", default="", metavar="MANIFEST",
                   help="按 manifest 回滚一次克隆（恢复备份 + 删除新建文件）。"
                        "**回滚请用它，不要自己按块删** —— 容器文件里一个块可能包含整个列表，"
                        "删块会把整份列表带走")
    return p.parse_args(argv_after_ddash())


def do_undo(manifest_path):
    """按 manifest 回滚：用备份覆盖原文件 + 删除新建文件。

    只做这两件事，不解析 NDF。这是**唯一安全**的回滚方式：
    按对象名删块会误伤容器（`block_at` 从列表里的条目往回找，会找到整个大列表的声明）。
    """
    import json
    if not os.path.isfile(manifest_path):
        sys.exit("[错误] 找不到 manifest %s" % manifest_path)
    mf = json.load(open(manifest_path, encoding="utf-8"))
    print("=== 回滚 %s（%s）===" % (mf.get("name"), mf.get("stamp")))
    bad = 0
    for orig, bak in mf.get("backups", []):
        if not os.path.isfile(bak):
            print("  [缺失] 备份不见了：%s" % bak)
            bad += 1
            continue
        shutil.copy2(bak, orig)
        print("  [恢复] %s" % os.path.relpath(orig, mf["mod"]))
    for f in mf.get("created", []):
        if os.path.isfile(f):
            os.remove(f)
            print("  [删除] %s" % os.path.relpath(f, mf["mod"]))
    print("=== %s ===%s" % ("回滚完成" if not bad else "回滚不完整，%d 个备份缺失" % bad,
                            "" if not bad else "，请手工处理"))
    print("回滚后请重新编译一次（Gen/ 里仍是合并后的产物）")


# ---------------------------------------------------------------- 文本工具
def indent_mode(text, pattern):
    """取 `pattern` 各行缩进的**众数**，用于把新条目对齐到该列表的常规缩进。

    不能用「最近一条」：原文件里常有缩进异常的历史条目（本项目圆点那条就是 12 空格，
    而同列表其它条目是 8 空格），照抄它就会把新条目也写歪。
    也不能用「块首行」：块起点往往是整个大容器的声明行，缩进是 0。
    """
    from collections import Counter
    c = Counter(m.group(1) for m in re.finditer(pattern, text, re.M))
    return c.most_common(1)[0][0] if c else "        "


def identity_of(blk):
    """块的唯一身份：具名对象用声明名，unnamed 用 BlackHoleKey 值。

    幂等判断必须用它，**不能**用「块名里把源名替换成新名」来猜 ——
    `unnamed TacticVehicleDepictionRegistration` 这类块没有名字，
    猜出来的字符串在文件里永远不存在，于是每次重跑都会再追加一遍。
    """
    head = blk.split("\n", 1)[0].strip()
    m = re.match(r"(?:export\s+)?([A-Za-z_]\w*)\s+is\b", head)
    if m:
        return ("name", m.group(1))
    k = re.search(r'BlackHoleKey\s*=\s*["\']([^"\']+)["\']', blk[:400])
    if k:
        return ("bhk", k.group(1))
    return ("raw", head[:60])


def already_present(txt, ident):
    kind, val = ident
    if kind == "name":
        return re.search(r"(?m)^(?:export\s+)?" + re.escape(val) + r"\s+is\b", txt) is not None
    if kind == "bhk":
        return re.search(r'BlackHoleKey\s*=\s*["\']' + re.escape(val) + r'["\']', txt) is not None
    return val in txt


def keep_only_src_blocks(txt, src):
    """整文件复制时，只保留**声明行含 src** 的顶层块。

    专属资源文件里常混着**共享资源** —— 例如圆点的 `Tochka_9K79.ndf` 里第一个块就是
    `export Modele_Missile_9M79`（那发导弹本身）。它不含单位名、不该改名，若整份复制，
    同一个 export 就在两个文件里各定义一次 → 编译期通过，加载时报
    `Namespace opened twice : Modele_Missile_9M79`。
    """
    ms = list(DECL_RE.finditer(txt))
    if not ms:
        return txt
    parts = [txt[:ms[0].start()]]
    kept = 0
    for i, m in enumerate(ms):
        s = m.start()
        e = ms[i + 1].start() if i + 1 < len(ms) else len(txt)
        blk = txt[s:e]
        if src in blk.split("\n", 1)[0]:
            parts.append(blk)
            kept += 1
        else:
            print("  [跳过共享资源] %s" % blk.split("\n", 1)[0].strip()[:62])
    if kept == 0:
        sys.exit("[错误] 专属文件里没有任何含 %s 的声明块，这份不是该单位的资源文件" % src)
    return "".join(parts)


def read(p):
    return open(p, encoding="utf-8", errors="replace").read()


def eol_of(p):
    b = open(p, "rb").read()
    return "\r\n" if b.count(b"\r\n") > b.count(b"\n") // 2 else "\n"


def write_like(p, txt):
    """按目标文件**原有**的换行风格落盘。

    read() 走 universal newlines，读进来一律是 \\n。若直接
    `open(p, "w", newline="").write(txt)`，本来 CRLF 的文件会被**整份改成 LF** ——
    WARNO 的 ndf 一旦换行被打穿，`genmod_guard.py` 编译仍可能通过，
    但 diff 会显示整文件被改写，事后没法判断到底动了哪几行。

    所以：读侧保持 \\n（所有正则 / 下标定位都不必改），写侧统一用本函数。
    eol_of() 读的是磁盘上的**当前**文件；首次写就保住了原风格，后续读取仍然稳定。
    """
    eol = eol_of(p)
    if eol == "\r\n":
        txt = txt.replace("\r\n", "\n").replace("\n", "\r\n")
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(txt)


def block_at(text, idx):
    """从 idx 所在块往回找声明行，再按括号深度取到收尾。兼容三种声明 + () / []。"""
    starts = [m.start() for m in DECL_RE.finditer(text) if m.start() <= idx]
    if not starts:
        return None
    s = starts[-1]
    cand = [x for x in (text.find("(", s), text.find("[", s)) if x >= 0]
    if not cand:
        return None
    op = min(cand)
    close = ")" if text[op] == "(" else "]"
    obt = text[op]
    d, i = 0, op
    while i < len(text):
        ch = text[i]
        if ch == obt:
            d += 1
        elif ch == close:
            d -= 1
            if d == 0:
                return s, i + 1
        i += 1
    return None


def obj_name_of(blk):
    """从块首行猜对象名；`unnamed` 的块改用 BlackHoleKey 标识（否则一堆同名看不出区别）。"""
    head = blk.split("\n", 1)[0].strip()
    m = re.match(r"(?:export\s+)?([A-Za-z_]\w*)\s+is\b", head)
    if m:
        return m.group(1)
    m = re.match(r"unnamed\s+(\w+)", head)
    if m:
        k = re.search(r'BlackHoleKey\s*=\s*["\']([^"\']+)["\']', blk[:400])
        return "%s(%s)" % (m.group(1), k.group(1)) if k else "unnamed:" + m.group(1)
    return head[:48]


# ---------------------------------------------------------------- 闭包扫描
def scan_closure(mod, src):
    """扫全 Mod 的 .ndf，返回 [{file, obj, start, end, lines, kind}]（不含容器文件）。"""
    gd = os.path.join(mod, "GameData")
    if not os.path.isdir(gd):
        sys.exit("[错误] %s 下没有 GameData（--mod 指到 Mod 根目录）" % mod)
    hits = []
    seen = set()
    for dp, dn, fn in os.walk(gd):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for f in fn:
            if not f.endswith(".ndf"):
                continue
            p = os.path.join(dp, f)
            if any(h in f for h in CONTAINER_HINTS):
                continue
            txt = read(p)
            if src not in txt:
                continue
            # 专属资源文件（DepictionResources/Char/<SRC>.ndf）：整份复制，不按块拆
            if os.path.splitext(f)[0] == src and "DepictionResources" in p.replace("\\", "/"):
                hits.append(dict(file=p, rel=os.path.relpath(p, mod).replace("\\", "/"),
                                 obj="<专属资源文件>", start=0, end=len(txt),
                                 lines=txt.count("\n") + 1, dedicated=True))
                continue
            bhk = re.compile(r'BlackHoleKey\s*=\s*["\'](?:showroom_|ghost_)?' + re.escape(src) + r'["\']')
            for m in re.finditer(re.escape(src), txt):
                rng = block_at(txt, m.start())
                if rng is None:
                    continue
                s, e = rng
                key = (p, s)
                if key in seen:
                    continue
                seen.add(key)
                blk = txt[s:e]
                # 声明行必须含 src，或块内就是 BlackHoleKey = "<src>"（注意可能是双引号，
                # Showroom 用的是 "showroom_<src>"，Ghosts 是 "<src>"）
                decl = blk.split("\n", 1)[0]
                if src not in decl and not bhk.search(blk[:400]):
                    continue
                nlines = blk.count("\n") + 1
                if nlines > MAX_BLOCK_LINES:
                    print("  [跳过] %s 里有个 %d 行的块含 %s，疑似容器，不克隆"
                          % (f, nlines, src))
                    continue
                hits.append(dict(file=p, rel=os.path.relpath(p, mod).replace("\\", "/"),
                                 obj=obj_name_of(blk), start=s, end=e, lines=nlines))
    # 排序：单位本体最前
    hits.sort(key=lambda h: (0 if h["obj"].startswith("Descriptor_Unit_") else 1, h["rel"], h["obj"]))
    return hits


# ---------------------------------------------------------------- 主流程
def main():
    a = parse_args()
    if a.undo:
        do_undo(a.undo)
        return
    if not a.mod or not a.src:
        sys.exit("[错误] 需要 --mod 与 --src（回滚用 --undo <manifest>）")
    mod = os.path.abspath(a.mod)
    STAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    print("=== 引用闭包：%s ===" % a.src)
    hits = scan_closure(mod, a.src)
    if not hits:
        sys.exit("[错误] 全 Mod 没找到 %s 的任何定义块。确认单位名拼写（是描述器里的短名，"
                 "不是显示名）" % a.src)
    for h in hits:
        print("   %-58s %-46s %4d 行" % (h["rel"], h["obj"], h["lines"]))
    n_unit = sum(1 for h in hits if h["obj"].startswith("Descriptor_Unit_"))
    n_dep = sum(1 for h in hits if "Depiction" in h["obj"] or "Alternatives" in h["obj"])
    print("   合计 %d 个对象（单位本体 %d，描绘相关 %d）" % (len(hits), n_unit, n_dep))
    if n_unit == 0:
        print("   [警告] 没找到 Descriptor_Unit_%s，这个单位可能不存在" % a.src)

    if a.list_only:
        print("\n[list-only] 未改任何文件")
        return

    if not a.name:
        sys.exit("[错误] 需要 --name 指定新单位名（或加 --list-only 只看闭包）")
    NEW = a.name
    TOKEN = a.token or re.sub(r"[^A-Z0-9]", "", NEW.upper())[:10]
    DISPLAY = a.display_name or NEW
    if len(TOKEN) > 10:
        sys.exit("[错误] token %r 有 %d 字符，超过 10 会 Fatal（TLocalisationToken）" % (TOKEN, len(TOKEN)))
    GUID = a.guid or "{%s}" % uuid.uuid4()

    print("\n新单位=%s  token=%s(%d)  显示名=%s  GUID=%s" % (NEW, TOKEN, len(TOKEN), DISPLAY, GUID))

    if "--" in NEW or " " in NEW:
        sys.exit("[错误] 单位名里不能有空格或破折号，NDF 标识符只接受 [A-Za-z0-9_]")

    # ---------- 改名表 ----------
    rel = [(a.src, NEW)]
    for kv in a.ammo_map:
        if "=" not in kv:
            sys.exit("[错误] --ammo-map 要写成 OLD=NEW：%r" % kv)
        o, n = kv.split("=", 1)
        rel.append((o.strip(), n.strip()))
    if a.src_token:
        rel.append((a.src_token, TOKEN))

    # ⭐ 源 NameToken 自动检测（2026-11-10 LAV-600 踩坑后补）：
    # 克隆源的 `NameToken` 经常是一个哈希串（如 'RJJGNUEUQO'），与单位名无关。
    # 只靠 --src-token 手工传会漏；漏换的后果是面板显示克隆源的原始 token 串
    # （CSV 没登记 → 更糟，Dictionary error）。这里直接从源单位块里读出来加进改名表。
    src_unit = next((h for h in hits if h["obj"].startswith("Descriptor_Unit_")), None)
    if src_unit:
        src_txt = read(src_unit["file"])
        src_blk = src_txt[src_unit["start"]:src_unit["end"]]
        m_nt = re.search(r"(?<![A-Za-z])NameToken\s*=\s*'([^']+)'", src_blk)
        if m_nt:
            src_tok = m_nt.group(1)
            if src_tok == TOKEN:
                print("   [提示] 源 NameToken 与新 token 相同（%s），改名表不再加" % TOKEN)
            elif any(o == src_tok for o, _ in rel):
                print("   [提示] 源 NameToken %r 已在改名表（--src-token/--ammo-map）" % src_tok)
            else:
                rel.append((src_tok, TOKEN))
                print("   [自动] 源 NameToken %r → %r（未传 --src-token，从源块读出）" % (src_tok, TOKEN))
        else:
            print("   [警告] 源单位块里没找到 NameToken 字段，请人工核对")

    if a.src_display:
        rel.append((a.src_display, DISPLAY))

    def rename(blk, is_first=False):
        out = blk
        # ⚠ 资源路径要保护：`Mesh = ".../Tochka_9K79/Tochka_9K79.fbx"` 里的名字如果被一起换掉，
        # 而资产目录没改名，编译必报 `File not found`。默认只换逻辑标识符，路径原样保留。
        store = []

        def _hold(m):
            store.append(m.group(0))
            return "\x00M%d\x00" % (len(store) - 1)

        if not a.rename_mesh:
            # ① 先护住**所有** `GameData:` 资源路径，不看字段名、单双引号通吃。
            #    踩过的坑：`Mesh=` 用双引号被护住了，但
            #        FileName = 'GameData:/Assets/.../Tochka_9K79/Tochka_9K79_fold.fbx'
            #    用的是单引号，正则漏掉 → 路径里的源名被一起替换 →
            #    编译报 `File not found : .../Tochka_T01/Tochka_T01_fold.fbx`。
            out = re.sub(r"""(['"])GameData:[^'"]*\1""", _hold, out)
            # ② 再兜一层不含 `GameData:` 前缀的资源字段
            out = re.sub(r'(?:Mesh\w*|SubGenerators\w*|Animations\w*)\s*=\s*"[^"]*"', _hold, out)

        for o, n in rel:
            out = out.replace(o, n)

        for i, v in enumerate(store):
            out = out.replace("\x00M%d\x00" % i, v)
        # GUID：**每一个都换新的**，且整个会话内保持映射一致。
        # 只换第一个是危险的：克隆出的多个对象会与源共用 GUID（单位本身不会报错，
        # 但两个对象同 GUID 属于脏数据，编辑器/序列化一旦按 GUID 索引就会串）。
        def rep(m):
            g = m.group(0)
            if g in GUID_MAP:
                return GUID_MAP[g]
            if is_first and not GUID_MAP:
                newg = "GUID:" + GUID
            else:
                newg = "GUID:{%s}" % uuid.uuid4()
            GUID_MAP[g] = newg
            return newg

        out = re.sub(r"GUID:\{[0-9a-fA-F-]{36}\}", rep, out)
        # 阵营 / 国籍 / 底盘 / 地形表：只在块内按字段名替换，避免误伤
        if a.coalition:
            out = re.sub(r"(Coalition\s*=\s*TWargameCoalition/)\w+", r"\g<1>" + a.coalition, out)
        if a.country:
            out = re.sub(r"(MotherCountry\s*=\s*)'[^']*'", r"\g<1>'" + a.country + "'", out)
        if a.moving_type:
            out = re.sub(r"(UnitMovingType\s*=\s*EUnitMovingType/)\w+", r"\g<1>" + a.moving_type, out)
        if a.terrain:
            out = re.sub(r"\$/GFX/Terrains/\w*VehicleTerrainSpeedFactors",
                         "$/GFX/Terrains/%sVehicleTerrainSpeedFactors" % a.terrain, out)
        return out

    GUID_MAP = {}
    BACKED = set()
    MANIFEST = {"mod": mod, "stamp": STAMP, "name": NEW, "src": a.src,
                "backups": [], "created": [], "objects": []}

    def backup_once(p):
        """同一文件只备份一次：多块克隆时第二块进来，文件已被第一块改过，
        再 copy 就会把「已改版」当成原始备份 —— 回滚回去仍是脏的。"""
        if a.no_backup or p in BACKED:
            return
        bak = p + ".bak_" + STAMP
        shutil.copy2(p, bak)
        BACKED.add(p)
        MANIFEST["backups"].append((p, bak))

    written = 0
    dep_files = []
    # ---------- 逐块克隆 ----------
    for h in hits:
        p = h["file"]

        # 专属资源文件：整份另存为 <NEW>.ndf，并登记到 NdfDepictionList
        if h.get("dedicated"):
            newp = os.path.join(os.path.dirname(p), NEW + ".ndf")
            if os.path.isfile(newp):
                print("  [跳过] %s 已存在" % os.path.basename(newp))
                dep_files.append(newp)
                continue
            txt = read(p)
            txt = keep_only_src_blocks(txt, a.src)
            new = rename(txt, is_first=True)
            eol = eol_of(p)
            print("  [复制] %-46s → %s (%d 行)" % (os.path.basename(p), os.path.basename(newp),
                                                  new.count("\n") + 1))
            if not a.dry:
                with open(newp, "w", encoding="utf-8", newline="") as f:
                    f.write(new.replace("\r\n", "\n").replace("\n", eol))
                MANIFEST["created"].append(newp)
                MANIFEST["objects"].append(os.path.basename(newp))
            dep_files.append(newp)
            written += 1
            continue

        txt = read(p)
        blk = txt[h["start"]:h["end"]]
        new = rename(blk, is_first=h["obj"].startswith("Descriptor_Unit_"))
        ident = identity_of(new)
        if already_present(txt, ident):
            print("  [跳过] %-46s 已存在" % (ident[1],))
            continue
        eol = eol_of(p)
        body = (eol + new.replace("\r\n", "\n").replace("\n", eol) + eol)
        print("  [克隆] %-46s → %-46s (%d 行)" % (h["obj"], obj_name_of(new), new.count("\n") + 1))
        if not a.dry:
            if not a.no_backup:
                backup_once(p)
            with open(p, "ab") as f:
                f.write(body.encode("utf-8"))
            MANIFEST["objects"].append(ident[1])
        written += 1

    # ---------- 容器 0：NdfDepictionList（漏了就是"资源不加载"） ----------
    ndl_p = os.path.join(mod, "GameData/Generated/Gameplay/Gfx/NdfDepictionList.ndf")
    if dep_files:
        if not os.path.isfile(ndl_p):
            print("  [警告] 找不到 NdfDepictionList.ndf，专属资源不会被加载")
        else:
            txt = read(ndl_p)
            for newp in dep_files:
                relp = os.path.relpath(newp, os.path.join(mod, "GameData")).replace("\\", "/")
                entry_path = "GameData:/" + relp
                if entry_path in txt:
                    print("  [跳过] NdfDepictionList 已登记 %s" % os.path.basename(newp))
                    continue
                cut = txt.rfind("]")
                nl = txt.rfind("\n", 0, cut)
                insert_at = nl + 1 if nl >= 0 else cut
                ind = "    "
                m = re.search(r'(?m)^([ \t]*)"GameData:', txt)
                if m:
                    ind = m.group(1)
                line = '%s"%s",%s' % (ind, entry_path, eol_of(ndl_p))
                print("  [登记] NdfDepictionList ← %s" % entry_path)
                if not a.dry:
                    if not a.no_backup:
                        backup_once(ndl_p)
                    newtxt = txt[:insert_at] + line + txt[insert_at:]
                    write_like(ndl_p, newtxt)
                    txt = newtxt

    # ---------- 容器 1：师规则 ----------
    rules_p = os.path.join(mod, "GameData/Generated/Gameplay/Decks/DivisionRules.ndf")
    if a.division:
        if not os.path.isfile(rules_p):
            print("  [警告] 找不到 DivisionRules.ndf，跳过师规则")
        else:
            txt = read(rules_p)
            if "Descriptor_Unit_" + NEW in txt:
                print("  [跳过] 师规则已含该单位")
            else:
                i = txt.find(a.division)
                if i < 0:
                    sys.exit("[错误] 找不到师 %s（要写全 Descriptor_Deck_Division_... 名）" % a.division)
                rng = block_at(txt, i)
                if rng is None:
                    sys.exit("[错误] 师块括号不配对")
                s, e = rng
                blk = txt[s:e]
                # 在该师的 UnitRuleList 收尾 ] 之前插入
                cut = blk.rfind("]")
                if cut < 0:
                    sys.exit("[错误] 师块里没有 UnitRuleList 列表")
                nl = blk.rfind("\n", 0, cut)
                insert_at = nl + 1 if nl >= 0 else cut
                # 缩进取该师 UnitRuleList 里的众数（避开历史上缩进歪掉的条目）
                ind = indent_mode(blk, r"^([ \t]*)TDeckUniteRule")
                xp = "[" + ", ".join(x.strip() for x in a.xp.split(",")) + "]"
                entry = ("%sTDeckUniteRule\n%s(\n%s    UnitDescriptor = $/GFX/Unit/Descriptor_Unit_%s\n"
                         "%s    AvailableWithoutTransport = True\n%s    MaxPackNumber = %d\n"
                         "%s    NumberOfUnitInPack = %d\n%s    NumberOfUnitInPackXPMultiplier = %s\n%s),\n"
                         % (ind, ind, ind, NEW, ind, ind, a.max_pack, ind, a.num_in_pack, ind, xp, ind))
                new_blk = blk[:insert_at] + entry + blk[insert_at:]
                print("  [插入] 师规则 %s ← %s（%d 组 ×%d）" % (a.division.split("_Rule")[0], NEW, a.max_pack, a.num_in_pack))
                if not a.dry:
                    if not a.no_backup:
                        backup_once(rules_p)
                    write_like(rules_p, txt[:s] + new_blk + txt[e:])
    # ---------- 容器 2：DeckSerializer UnitId ----------
    deck_p = os.path.join(mod, "GameData/Generated/Gameplay/Decks/DeckSerializer.ndf")
    if os.path.isfile(deck_p):
        txt = read(deck_p)
        if "Descriptor_Unit_" + NEW in txt:
            print("  [跳过] DeckSerializer 已含该单位")
        else:
            ids = [int(x) for x in re.findall(r"\$/GFX/Unit/Descriptor_Unit_[\w]+,\s*(\d+)", txt)]
            uid = a.deck_id or (max(ids) + 1 if ids else 1)
            if a.deck_id and a.deck_id in ids:
                sys.exit("[错误] --deck-id %d 已被占用（换一个，或留空自动 max+1）" % a.deck_id)
            i = txt.find("UnitIds")
            if i < 0:
                print("  [警告] DeckSerializer 里没有 UnitIds，跳过")
            else:
                op = txt.find("[", i)
                rng = block_at(txt, op + 1)
                if rng is None:
                    print("  [警告] UnitIds 列表括号不配对，跳过")
                else:
                    s, e = rng
                    blk = txt[s:e]
                    cut = blk.rfind("]")
                    nl = blk.rfind("\n", 0, cut)
                    insert_at = nl + 1 if nl >= 0 else cut
                    ind = indent_mode(blk, r"^([ \t]*)\(")
                    entry = "%s($/GFX/Unit/Descriptor_Unit_%s, %d),\n" % (ind, NEW, uid)
                    new_blk = blk[:insert_at] + entry + blk[insert_at:]
                    print("  [追加] DeckSerializer %s → UnitId %d" % (NEW, uid))
                    if not a.dry:
                        if not a.no_backup:
                            backup_once(deck_p)
                        write_like(deck_p, txt[:s] + new_blk + txt[e:])

    # ---------- 容器 3：本地化 CSV ----------
    csv_p = None
    for cand in ("GameData/Localisation/Test/UNITS.csv", "GameData/Localisation/UNITS.csv"):
        q = os.path.join(mod, cand)
        if os.path.isfile(q):
            csv_p = q
            break
    if csv_p is None:
        print("  [警告] 没找到 UNITS.csv，token %s 未登记（会 Dictionary error）" % TOKEN)
    else:
        txt = read(csv_p)
        if re.search(r"(?m)^%s;" % re.escape(TOKEN), txt):
            print("  [跳过] CSV 已含 token %s" % TOKEN)
        else:
            # 注意：不能用 `"\r\n" in txt` 判断风格 —— read() 是 universal newlines，
            # txt 里永远没有 \r\n，这样判断会让 CRLF 的 UNITS.csv 追加出 LF 行
            # （混合换行不会报错，但会让整表 diff 变成「全文件改写」）。
            nl = eol_of(csv_p)
            line = "%s;%s%s" % (TOKEN, DISPLAY, nl)
            print("  [追加] CSV %s;%s" % (TOKEN, DISPLAY))
            if not a.dry:
                if not a.no_backup:
                    backup_once(csv_p)
                with open(csv_p, "ab") as f:
                    f.write(line.encode("utf-8"))

    # ⭐ NameToken 收尾自检（与上面自动检测配套）：新单位块里的 NameToken 必须 == TOKEN。
    #    残留克隆源 token 的症状是面板显示原始哈希串或 Dictionary error，编译期零报错。
    #    按新对象名重新定位（不能复用旧偏移——插入新块后同文件偏移已变）。
    if not a.dry:
        ud_p = os.path.join(mod, "GameData", "Generated", "Gameplay", "Gfx", "UniteDescriptor.ndf")
        if os.path.exists(ud_p):
            txt2 = read(ud_p)
            m_blk = re.search(r"export Descriptor_Unit_%s is" % re.escape(NEW), txt2)
            if m_blk:
                # ⭐ 2026-11-11 LOSAT 踩坑：单位块常 230+ 行 / 9 KB，NameToken 实测在
                #    块内偏移 8275 字符处；固定 4000 字符窗口会漏掉并误报 "(无字段)"。
                #    改为按块边界截取：NDF 顶层块的收括号是行首 `)`（嵌套块有缩进）。
                tail = txt2[m_blk.start():]
                m_end = re.search(r"(?m)^\)", tail)
                seg = tail[:m_end.end()] if m_end else tail[:30000]
                m2 = re.search(r"(?<![A-Za-z])NameToken\s*=\s*'([^']+)'", seg)
                got = m2.group(1) if m2 else "(无字段)"
                if got != TOKEN:
                    print("   [FAIL] 新单位块 NameToken = %r ≠ %r —— 面板会显示原始 token，请手工修正"
                          % (got, TOKEN))
                else:
                    print("   [ok]   NameToken = %s" % TOKEN)

    # ⭐ 乘员子描绘提示（2026-11-11 LOSAT 踩坑）：克隆源自带 HumanSubDepictions_* 时，
    #    战场版 depiction 会挂 SubDepiction_Driver，加载期要求 FBX 里有 'driver' 骨；
    #    封闭车体（坦克 / 履带 TEL / 步战）模型没有乘员几何 → Fatal，**编译期零报错**。
    #    这里只提示，不自动改（敞篷车需要保留，判据是「车里能不能看见人」）。
    if not a.dry:
        dh_p = os.path.join(mod, "GameData", "Generated", "Gameplay", "Gfx",
                            "Depictions", "DepictionHumans.ndf")
        if os.path.exists(dh_p):
            dtx = read(dh_p)
            m_h = re.search(r"HumanSubDepictions_%s\s+is\s*(.{0,1200}?)(?:\n\n|\Z)"
                            % re.escape(NEW), dtx, re.S)
            body = m_h.group(1) if m_h else ""
            if "SubDepiction_Driver" in body or "SubDepiction_Servant" in body:
                print("   [警告] 源单位带乘员子描绘（HumanSubDepictions_%s）：" % NEW)
                print("          加载期会要求 FBX 里有 driver / servant 骨，缺失即 Fatal error，编译期零报错。")
                print("          · 封闭车体（坦克 / 履带 TEL / 步战）→ 摘掉：")
                print("            DepictionVehicles.ndf: ` ] + HumanSubDepictions_%s` → ` ]`" % NEW)
                print("            DepictionHumans.ndf : 块体 → `HumanSubDepictions_%s is []`" % NEW)
                print("          · 敞篷车 → 保留，并在烘焙时补 `driver` 骨（脚底 Z=0）。")
                print("          改完必须跑 depiction_anchors_all.py 做全链差集（此类校验一次只报一个）。")

    print("\n=== 完成 === 克隆 %d 个对象%s" % (written, "（dry，未写入）" if a.dry else ""))
    if not a.dry and not a.no_backup:
        import json
        mpath = os.path.join(mod, "clone_manifest_%s.json" % STAMP)
        with open(mpath, "w", encoding="utf-8") as f:
            json.dump(MANIFEST, f, ensure_ascii=False, indent=2)
        print("[清单] %s" % mpath)
        print("[回滚] python clone_unit.py --undo \"%s\"" % mpath)
    print("备份后缀 .bak_%s" % STAMP)
    print("\n下一步：")
    print("  1) python genmod_guard.py --mod \"%s\" --name <Mod名> 1800   # 编译" % mod)
    print("  2) 实机七问：买得到 / 能部署 / 能开火 / 军械库有卡 / 能存卡组 / 重进还在 / 弹体对得上")
    print("  3) 卡面仍在源单位那张上，用 set_card_art.py 换")


if __name__ == "__main__":
    main()
