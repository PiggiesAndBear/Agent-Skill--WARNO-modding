# -*- coding: utf-8 -*-
"""补丁脚本骨架 —— 复制本文件改名后改 CONFIG 段即可。

设计要点（每条都踩过坑，见 references/patch-workflow.md）：
  * 换行按文件探测，写回时还原（否则 71 万行文件全变红）
  * 每个 step 自带幂等判断：重跑全部走「跳过」
  * 每个 step 自带三类守卫：must / must-not / 结构（行数·括号·块数）
  * --dry-run 不写盘，但用内存 CACHE 让下游 step 看到上游结果
  * 备份命名带时间戳与语义标签

用法：
    python patch_template.py --dry-run
    python patch_template.py
"""
import datetime
import os
import re
import shutil
import sys

# ---------------------------------------------------------------- CONFIG
# ROOT 默认 = 脚本所在目录的上两级（即把本脚本放进 <Mod>/.workbuddy/scripts/ 的用法）。
# 从别处试跑时用环境变量覆盖：MOD_ROOT="D:/.../Mods/<Mod>" python patch_template.py --dry-run
ROOT = os.environ.get("MOD_ROOT") or os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
GD = os.path.join(ROOT, "GameData")
P_UNIT = os.path.join(GD, "Generated/Gameplay/Gfx/UniteDescriptor.ndf")
P_BACKUP = os.path.join(ROOT, ".workbuddy", "backup")
TAG = "demo"                       # 备份标签：写这次改动的语义，不写序号

TEMPLATE_HEADER = "Descriptor_Unit_Pero_UAV_SOV"    # 被克隆的模板
NEW_HEADER = "Descriptor_Unit_Demo_UAV_SOV"         # 新对象
KIND = "TEntityDescriptor"

MUST = ["export %s is %s" % (NEW_HEADER, KIND)]
# ⚠ 真正的克隆要把 must-not 写成「旧身份的全部痕迹」（如 "_SOV" / "PACT" / 旧模型名）。
#   本 demo 只换名字、不换阵营，所以这里只列旧对象名，避免 demo 自相矛盾。
MUST_NOT = ["Descriptor_Unit_Pero_UAV_SOV"]

DRY = "--dry-run" in sys.argv or "--dry" in sys.argv
CACHE = {}
# ----------------------------------------------------------------------


def rd(path):
    with open(path, "rb") as f:
        head = f.read(200000)
    eol = "\r\n" if head.count(b"\r\n") > head.count(b"\n") / 2 else "\n"
    with open(path, encoding="utf-8", newline=None) as f:
        return f.read(), eol


def wr(path, text, eol):
    if eol != "\n":
        text = text.replace("\n", eol)
    with open(path, "w", encoding="utf-8", newline="") as f:   # newline="" 必须
        f.write(text)


def backup(path, tag):
    os.makedirs(P_BACKUP, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(P_BACKUP, "%s.%s.before_%s" % (os.path.basename(path), ts, tag))
    if not DRY:
        shutil.copy2(path, dst)
    print("    备份:", dst)
    return dst


def die(msg):
    print("[拒绝] " + msg)
    sys.exit(1)


def ok(msg):
    print("  [OK] " + msg)


def block_of(text, header, kind=KIND):
    """定位一个顶层对象块：到下一个 '\\nexport ' 为止。"""
    m = re.search(r"(?m)^export " + re.escape(header) + r" is " + re.escape(kind), text)
    if not m:
        die("找不到块 " + header)
    nxt = text.find("\nexport ", m.end())
    return text[m.start(): nxt if nxt > 0 else len(text)]


def exists(text, header, kind=KIND):
    return re.search(r"(?m)^export " + re.escape(header) + r" is " + re.escape(kind), text) is not None


def apply_block_guards(old_block, new_block):
    """块级三条守卫：must / must-not / 结构。"""
    for s in MUST:
        if s not in new_block:
            die("改写后缺少 %r" % s)
    for b in MUST_NOT:
        if b in new_block:
            die("改写后仍残留 %r" % b)
    if new_block.count("\n") != old_block.count("\n"):
        die("块行数变化 %d -> %d（克隆类改动应保持行数）"
            % (old_block.count("\n"), new_block.count("\n")))
    open_, close_ = new_block.count("("), new_block.count(")")
    if open_ != close_:
        die("块内括号不平衡 (%d vs %d)" % (open_, close_))


def transform(seg):
    """TODO: 在这里写替换。替换前先数出现次数，避免正则吃掉标签名。"""
    if seg.count("MimeticName") != 1:
        die("MimeticName 出现次数异常：%d" % seg.count("MimeticName"))
    seg = seg.replace(TEMPLATE_HEADER, NEW_HEADER)
    seg = seg.replace("Pero_UAV_SOV", "Demo_UAV_SOV")     # 机体链：MimeticName/BlackHoleKey/Mesh/Button/showroom
    return seg


# ---------------------------------------------------------------- steps
def step_clone():
    print("\n[1/2] %s -> 新块" % os.path.basename(P_UNIT))
    t, eol = rd(P_UNIT)
    if exists(t, NEW_HEADER):
        ok("已存在，跳过（幂等）")
        CACHE["text"] = t
        return
    seg = block_of(t, TEMPLATE_HEADER)
    new = transform(seg)
    apply_block_guards(seg, new)
    out = t.replace(seg, new, 1)

    # 文件级守卫：行数增量 + 括号净值 + 粘连
    if out.count("\n") != t.count("\n"):
        die("文件行数变化 %d -> %d" % (t.count("\n"), out.count("\n")))
    if out.count("(") - out.count(")") != t.count("(") - t.count(")"):
        die("文件括号净值变化")
    if re.search(r"\)export ", out):
        die("存在 )export 粘连，插入块尾部缺换行")

    if not DRY:
        backup(P_UNIT, TAG)
        wr(P_UNIT, out, eol)
    CACHE["text"] = out
    ok("校验通过，%d 行%s" % (new.count("\n"), "（dry-run 未写盘）" if DRY else " 已写入"))


def step_verify():
    print("\n[2/2] 结构复核")
    t = CACHE.get("text")
    if t is None:
        t, _ = rd(P_UNIT)
    n = len(re.findall(r"(?m)^export \w+ is " + re.escape(KIND), t))
    ok("顶层对象 %d 个，括号净值 %d" % (n, t.count("(") - t.count(")")))


def main():
    print("=" * 66)
    if not os.path.exists(P_UNIT):
        print("[中止] 找不到 %s" % P_UNIT)
        print("       把本脚本复制到 <Mod>/.workbuddy/scripts/ 再用，")
        print("       或设环境变量 MOD_ROOT 指向 mod 根目录。")
        return 2
    print("DRY-RUN（不写盘）" if DRY else "正式写入")
    step_clone()
    step_verify()
    print("\n下一步：python scripts/run_genmod_guard.py --mod \"%s\" 1800" % ROOT)
    return 0


if __name__ == "__main__":
    main()
