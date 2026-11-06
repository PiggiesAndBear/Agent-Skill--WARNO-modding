# -*- coding: utf-8 -*-
"""带弹窗捕获的 mod 编译守卫。

为什么必须用脚本（三件事叠在一起，缺一条就白等）：
  1) `GenerateMod.py` 失败时**不返回错误码** —— 内层 python 报错，cmd.exe 仍返回 0，
     GUI 封装（WME 等）把「失败」报成「成功」。
  2) 语法错时 `WARNO.exe -headless` 弹**模态** "NDF parsing error. Retry?" 等人点确定：
     进程 CPU 归零、**永久挂起**（实测空等 25 分钟）。
  3) 这种时候 **stdout 一个字节都没有**（python 输出块缓冲，进程被 kill 时全丢）
     ⇒ 报错**只存在于弹窗里**。读不到弹窗 = 拿不到任何线索。

本脚本因此做四件事：
  枚举 #32770 弹窗 → 过滤按钮文字 → 解析出「对象 / 报错句 / 已知成因」→ 落盘。

用法：
    python genmod_guard.py                              # 当前目录当工程根，超时 1800s
    python genmod_guard.py 600                          # 指定超时
    python genmod_guard.py --mod "D:/.../Mods/X" --name "X" 900
    python genmod_guard.py --probe                      # 只读：解析当前挂着的弹窗，不发起编译
                                                        # （报错来自 WME/手动双击时用这个）

退出码：
    0  成功（rc=0 且日志含 Mod Generation Success）
    3  被弹窗拦下（报错文本已解析并写入 genmod_last_error.txt）
    4  超时（无弹窗、无完成 —— 通常是死循环逻辑或资源问题，不是语法）
    5  环境问题（找不到官方 Python / GenerateMod.py，或已挂着上一次的失败弹窗）
    其他 = GenerateMod 的真实返回码

安全性：报错时只杀**弹窗所属的那个 PID**（headless 编译进程），
        超时也只清理本次新起的 WARNO 进程 —— 不会误杀玩家正开着的游戏。

产出：
    .workbuddy/tmp/genmod_guard.log        编译 stdout 原文（-u 无缓冲，中途被 kill 也有内容）
    .workbuddy/tmp/genmod_last_error.txt   最近一次弹窗报错的解析结果（含原文 + 定位 + 已知成因）
"""
import ctypes
import os
import re
import subprocess
import sys
import time
from ctypes import wintypes


# ---------------------------------------------------------------- 参数
def parse_args(argv):
    mod_dir, name, timeout = None, None, 1800
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--mod" and i + 1 < len(argv):
            mod_dir = argv[i + 1]; i += 2
        elif a == "--name" and i + 1 < len(argv):
            name = argv[i + 1]; i += 2
        elif a.isdigit():
            timeout = int(a); i += 1
        else:
            i += 1
    if not mod_dir:
        mod_dir = os.getcwd()
    mod_dir = os.path.abspath(mod_dir)
    if not name:
        name = os.path.basename(mod_dir.rstrip("\\/"))
    return mod_dir, name, timeout


MOD_DIR, MOD_NAME, TIMEOUT = parse_args(sys.argv[1:])
MODS_ROOT = os.path.dirname(MOD_DIR)                       # .../WARNO/Mods
UTILS = os.path.join(MODS_ROOT, "Utils")                   # .../WARNO/Mods/Utils
PY = os.path.join(UTILS, "Python", "python.exe")
SCRIPT = os.path.join(UTILS, "Scripts", "GenerateMod.py")
TMP = os.path.join(MOD_DIR, ".workbuddy", "tmp")
LOG = os.path.join(TMP, "genmod_guard.log")
ERR_FILE = os.path.join(TMP, "genmod_last_error.txt")


# ---------------------------------------------------------------- 窗口读取
u = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def wtext(h, n=8192):
    buf = ctypes.create_unicode_buffer(n)
    k = u.GetWindowTextW(h, buf, n)
    return buf.value[:k]


def wclass(h):
    buf = ctypes.create_unicode_buffer(256)
    u.GetClassNameW(h, buf, 256)
    return buf.value


def dialogs():
    """返回 [(hwnd, title, [child texts])]，只取 #32770 对话框。"""
    out = []

    def cb(h, _):
        if wclass(h) == "#32770":
            texts = []

            def cb2(c, _2):
                t = wtext(c)
                if t.strip():
                    texts.append(t.strip())
                return True

            u.EnumChildWindows(h, WNDENUMPROC(cb2), 0)
            out.append((h, wtext(h), texts))
        return True

    u.EnumWindows(WNDENUMPROC(cb), 0)
    return out


# 弹窗里的按钮文字会混进正文（实测第一段就是「确定」），必须滤掉
BUTTONS = {"确定", "OK", "Ok", "CANCEL", "Cancel", "取消", "Retry", "重试",
           "Abort", "中止", "是", "否", "Yes", "No", "Close", "关闭", "继续", "忽略"}
HINT = ("error", "Error", "ERROR", "NDF", "Invalid", "invalid", "Failed", "failed",
        "cannot", "must be", "not allowed", "too long")


def body_of(texts):
    """拼出报错正文：多行正文是**单个** static 控件，取最长的那段。"""
    parts = [t for t in texts if t not in BUTTONS]
    if not parts:
        return ""
    return max(parts, key=len)


def looks_like_error(title, body):
    if "parsing error" in title or "Fatal error" in title:
        return True
    return any(h in body for h in HINT)


# ---------------------------------------------------------------- 报错解析
OBJ_RE = re.compile(r"Object\s*<(\S+?)\s*:\s*(\w+)>")
MSG_HINTS = [
    # (正则, 已知成因) —— 全部来自本项目实测弹窗原文
    # ---- 本工程（Hell Divers）实测过的启动期 Fatal，按命中优先级排在前面 ----
    (r"No string found for token '([A-Z0-9]+)' in dictionary list '(\w+)'",
     "本地化字典缺 token：把该 token 追加到 GameData/Localisation/<Mod>/<DICO>.csv 后**重编译**"
     "（只改 csv 不重编译不生效）。硬规则：脚本「生成 token」与「写入字典」必须成对，"
     "NDF 里出现的任何 token 都要在字典里存在"),
    (r"TimeBetweenTwoShots must be multiple of a gameplay tick length",
     "射速不是 gameplay tick 的整数倍。实测 tick = 0.1 秒（值域全是 0.1 的倍数），"
     "如 0.64 非法、0.6 合法。⚠ TimeBetweenTwoSalvos 粒度是 0.05，两者别混用"),
    (r"Invalid character with ASCII value",
     "mod 名/路径含非 ASCII 字符（全角冒号等）→ WARNO.exe 启动即 Fatal。Mod 目录名必须全 ASCII，"
     "且 Localisation/、ResourcePacks/ 子目录与 LocalisationDicos.ndf、ResourcePacks.ndf 内的硬编码路径要同步"),
    (r"(?i)HasDeploymentTime|WeaponDeploymentModule",
     "弹药带部署属性（继承自牵引炮/阵地炮模板 HasDeploymentTime=True），但目标单位没有 "
     "TWeaponDeploymentModuleDescriptor。舰炮/空投类即时打击应把 HasDeploymentTime 改 False"),
    (r"(?i)NumberOfUnitInPackXPMultiplier|ExperienceLevel|experience level",
     "牌组自动填充的 ExperienceLevel 与 NumberOfUnitInPackXPMultiplier 不匹配。"
     "单载具（pack=1）最常见取值 [1.0, 0.0, 0.0, 0.0]（允许 Exp0）；抄直升机模板会带 [0.0,1.0,0,0]（只允许 Exp1）"),
    (r"(?i)already defined|duplicate definition",
     "对象/GUID 重复定义：克隆块内往往不止 1 个 GUID（单位本体 + 内嵌 MimeticDescriptor），"
     "**每个都要重签**，对象名也要先查全库 0 命中"),
    # ---- 引擎通用硬校验 ----
    (r"Value is too long for a TLocalisationToken:\s*'([^']+)'",
     "NameToken 超长：上限 10 字符，且要同步 Localisation/*/UNITS.csv 的键"),
    (r"Property '(\w+)' must be equal to '([^']*)'",
     "该属性由其它字段的取值**强制**决定，不能自由设（如弹道类型决定 PitchForParabolic）"),
    (r"Non-zero corrected shot dispersion multiplier is only relevant to .* type Artillery",
     "武器类型不符：该偏差系数只对类型 Artillery 的武器有意义；换弹道类型或删掉这个系数"),
    (r"Weapon with parabolic trajectory cannot be embedded on planes or helicos",
     "抛物线弹道不能挂在飞机/直升机上。注意：**不是禁间瞄**，禁的是弹道类型 Artillerie；"
     "换 Obus 弹道即可（代价是强制删 CorrectedShotDispersionMultiplier）"),
    (r"tag list incompatible|TagSet",
     "运输关系断裂：承运方与被运方的标签集合必须有**交集**，否则游戏启动即 Fatal error"),
    (r"Invalid property",
     "字段名写错或该模块不接受此字段（加载期报错，多半是拼写/放错模块）"),
]


HEADLINE_RE = re.compile(r"(?i)(retry\?\s*$|^ndf parsing error\.?$|^fatal error\.?$|^error\.?$)")


def parse_error(title, body):
    """把弹窗正文拆成 {object, type, message, hint}

    取值顺序很重要：弹窗**首行往往就是标题本身**（"NDF parsing error. Retry?"），
    若直接取「第一段够长的文字」会把它当成报错句，于是永远匹配不到已知成因。
    因此：① 先按已知成因逐行正则匹配；② 都不中，再退化成最长的一行。
    """
    d = {"title": title, "body": body, "object": None, "type": None,
         "message": None, "hint": None}
    m = OBJ_RE.search(body)
    if m:
        d["object"], d["type"] = m.group(1), m.group(2)

    cand = []
    for ln in (x.strip() for x in body.splitlines()):
        if not ln or ln in BUTTONS or "Object <" in ln:
            continue
        if ln == title or HEADLINE_RE.search(ln):
            continue
        cand.append(ln)

    for ln in cand:
        for pat, hint in MSG_HINTS:
            if re.search(pat, ln):
                d["message"], d["hint"] = ln, hint
                return d
    if cand:
        d["message"] = max(cand, key=len)
    return d


# 报错对象最可能所在的文件（先查这些，避免全库扫描 4500 个文件）
HOT_FILES = [
    "GameData/Generated/Gameplay/Gfx/UniteDescriptor.ndf",
    "GameData/Generated/Gameplay/Gfx/WeaponDescriptor.ndf",
    "GameData/Generated/Gameplay/Gfx/Ammunition.ndf",
    "GameData/Generated/Gameplay/Gfx/OrderAvailability_Tactic.ndf",
    "GameData/Generated/Gameplay/Gfx/CapaciteList.ndf",
    "GameData/Generated/Gameplay/Decks/DivisionRules.ndf",
    "GameData/Generated/Gameplay/Decks/Divisions.ndf",
    "GameData/Generated/Gameplay/Decks/DeckPacks.ndf",
    "GameData/Generated/Gameplay/Decks/DeckSerializer.ndf",
    "GameData/Generated/Gameplay/Decks/Decks.ndf",
    "GameData/Generated/Gameplay/Gfx/Depictions/DepictionAerialUnits.ndf",
    "GameData/Generated/Gameplay/Gfx/Depictions/DepictionDescriptions.ndf",
    "GameData/Generated/Gameplay/Effects/EffetsSurUnite.ndf",
]


def locate(symbol, mod_dir=None):
    """把 $/GFX/Unit/Descriptor_Unit_X 或裸符号定位到「文件:行号」。

    ⚠ 锚点用 `[ \\t]*` 而**不是** `\\s*`：`re.M` 下 `\\s` 会吃掉换行，
    匹配起点被拉到上一条对象的末尾空行，行号**稳定偏小 1**（本工程实测）。
    """
    mod_dir = mod_dir or MOD_DIR
    sym = symbol.rstrip("/").split("/")[-1]
    alts = [sym]
    if "_Unit_" not in sym:
        alts.append("Descriptor_Unit_" + sym)
    pat = re.compile(r"(?m)^[ \t]*(?:export[ \t]+)?(%s)[ \t]+(?:is|=)" % "|".join(map(re.escape, alts)))
    for rel in HOT_FILES:
        p = os.path.join(mod_dir, rel)
        if not os.path.exists(p):
            continue
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            txt = f.read()
        m = pat.search(txt)
        if m:
            return "%s:%d" % (rel, txt[: m.start()].count("\n") + 1)
    return None


def write_report(d):
    os.makedirs(TMP, exist_ok=True)
    loc = locate(d["object"]) if d.get("object") else None
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    lines = ["[%s] 编译被弹窗拦下" % ts,
             "dialog : %s" % d["title"],
             "object : %s" % (d.get("object") or "-"),
             "type   : %s" % (d.get("type") or "-"),
             "file   : %s" % (loc or "未在热区文件里找到（可能是 GameData 别名或新文件）"),
             "message: %s" % (d.get("message") or "-"),
             "hint   : %s" % (d.get("hint") or "无已知匹配，按原文自行判断"),
             "", "--- 弹窗原文 ---", d["body"]]
    text = "\n".join(lines) + "\n"
    with open(ERR_FILE, "w", encoding="utf-8") as f:
        f.write(text)
    return text


# ---------------------------------------------------------------- 主流程
def pid_of(hwnd):
    """弹窗所属进程的 PID。精确到这一个进程，才不会误杀玩家正在跑的游戏。"""
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def kill_pid(pid):
    if pid:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)


def warno_pids():
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq WARNO.exe", "/FO", "CSV", "/NH"],
                       capture_output=True, text=True, errors="replace")
    return {int(m) for m in re.findall(r'"WARNO\.exe","(\d+)"', r.stdout or "", re.I)}


def probe():
    """只读：把当前挂着的 #32770 逐个解析出来。不发起编译、不杀任何进程。

    用于「WME / 手动双击 GenerateMod.bat 已经弹错了」的场景 —— 那种情况守卫脚本
    没有在跑，报错文本没人接，用这个把原文捞出来。
    """
    ds = dialogs()
    if not ds:
        print("当前没有 #32770 对话框。")
        return 0
    hit = 0
    for h, title, texts in ds:
        body = body_of(texts)
        is_err = looks_like_error(title, body)
        print("[%s] PID %s  %s" % ("报错" if is_err else "信息", pid_of(h), title or "(无标题)"))
        if not body:
            continue
        if is_err:
            print(write_report(parse_error(title, body)))
            hit += 1
        else:
            print("    " + body.splitlines()[0][:140])
        print("-" * 60)
    print("报错弹窗 %d 个；解析结果已写入 %s" % (hit, ERR_FILE) if hit else "未发现报错弹窗。")
    return 3 if hit else 0


def main():
    if "--probe" in sys.argv[1:]:
        return probe()

    for p, label in ((PY, "官方 Python"), (SCRIPT, "GenerateMod.py")):
        if not os.path.exists(p):
            print("[中止] 找不到 %s：%s" % (label, p))
            print("       确认 --mod 指向 <WARNO>/Mods/<ModName>，且官方 Utils 目录完整。")
            return 5

    # 开跑前先记：① 已有的对话框 ② 已有的 WARNO 进程（玩家可能正开着游戏）
    before = dialogs()
    baseline = {h for h, _t, _x in before}
    pre_pids = warno_pids()
    if pre_pids:
        print("[提示] 已有 WARNO.exe 在运行（PID %s），本次只清理新起的进程，不动它。"
              % ", ".join(map(str, sorted(pre_pids))))
    for h, title, texts in before:
        if looks_like_error(title, body_of(texts)):
            print("[中止] 已有一个报错弹窗挂着（PID %s）：%s" % (pid_of(h), title))
            print("       那是上一次失败留下的，先关掉它再跑，否则分不清是谁的错。")
            return 5

    os.makedirs(TMP, exist_ok=True)
    log = open(LOG, "wb")
    t0 = time.time()
    # -u：无缓冲。否则进程被 kill 时日志 0 字节，连「卡在哪一步」都看不到
    proc = subprocess.Popen(
        [PY, "-u", SCRIPT, "WARNO", MOD_NAME],
        cwd=MOD_DIR,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    print("mod=%s  pid=%d  timeout=%ss" % (MOD_NAME, proc.pid, TIMEOUT), flush=True)

    result = None
    while True:
        time.sleep(3)
        rc = proc.poll()
        if rc is not None:
            result = "finished rc=%s after %ds" % (rc, int(time.time() - t0))
            break
        for h, title, texts in dialogs():
            if h in baseline:
                continue
            body = body_of(texts)
            if looks_like_error(title, body):
                print("=== 弹窗拦截 ===", flush=True)
                print(write_report(parse_error(title, body)), flush=True)
                kill_pid(pid_of(h))          # 只杀弹窗所属的那个 headless 进程
                proc.terminate()
                result = "BLOCKED_BY_DIALOG"
                break
        if result == "BLOCKED_BY_DIALOG":
            break
        if time.time() - t0 > TIMEOUT:
            print("=== 超时 ===", flush=True)
            for pid in warno_pids() - pre_pids:   # 只清理本次新起的
                kill_pid(pid)
            proc.terminate()
            result = "TIMEOUT"
            break

    log.close()
    print("RESULT:", result, flush=True)

    out = ""
    try:
        with open(LOG, "rb") as f:
            out = f.read().decode("utf-8", "replace")
    except Exception as e:
        print("读日志失败", e)
    if out.strip():
        print("=== 日志尾部 ===", flush=True)
        print(out[-2500:], flush=True)
    else:
        print("(stdout 为空——语法错时正常，线索全在弹窗里)", flush=True)

    if result == "BLOCKED_BY_DIALOG":
        return 3
    if result == "TIMEOUT":
        return 4
    if result and result.startswith("finished rc=0") and "Mod Generation Success" in out:
        return 0
    rc = proc.returncode if proc.returncode is not None else 1
    return rc or 1


if __name__ == "__main__":
    sys.exit(main())
