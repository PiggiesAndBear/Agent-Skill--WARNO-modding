# -*- coding: utf-8 -*-
"""NDF 顶层对象切分 / 行尾保真 / 对象级 diff —— 跨版本升级工具链的公共层。

设计要点（与 WARNO_跨版本升级_SOP.md §1.4 一致）：
- **不按行号定位**：所有补丁都以「对象声明串 + 行内容 + 上下文」定位，版本漂移后仍可命中。
- **对象 = 括号深度归零的顶层块**：`export X is T ( ... )` / `X is T ( ... )` / `unnamed T ( ... )`，
  单行声明（`X is T(A = 1)`）同样支持。
- **注释与空行跟随其后第一个对象**（leading trivia），保证逐字节可重建。
- 行尾按文件探测（CRLF / LF）；混合行尾直接拒绝（交由调用方降级为整文件拷贝）。
"""
import hashlib
import os
import re

RE_EXPORT = re.compile(r"^export\s+(\S+)\s+is\s+(\S+)")
RE_BARE_IS = re.compile(r"^([A-Za-z_][\w]*)\s+is\s+(\S+)")
RE_UNNAMED = re.compile(r"^unnamed\s+(\S+)")

# 顶层 decl 只认这几类；其余非空行按「前一个对象的尾随内容 / 后一个对象的前导注释」处理
# 注意：① `is` 后可以没有类型名（`Alternatives_XXX is` 换行再跟 `[` / `(`）；
#       ② 前面可能带可见性修饰符（`private DamageResistanceParams is ...`）。
_DECL_LINE = re.compile(
    r"^(?:(?:export|private|public|protected|local)\s+)*"
    r"(?:unnamed\s+\S+|[A-Za-z_]\w*\s+is\b)")


def read_text(path):
    """读文件 → (text, eol, mixed)。eol ∈ {'CRLF','LF','NONE'}。"""
    raw = open(path, "rb").read()
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n")
    if lf == 0:
        eol = "NONE"
    elif crlf == lf:
        eol = "CRLF"
    elif crlf == 0:
        eol = "LF"
    else:
        eol = "MIXED"
    return raw.decode("utf-8", "replace"), eol, (eol == "MIXED")


def split_lines_keep(text):
    """→ (norm_lines, eols)。norm = 去掉行尾 CR/LF；eols[i] 是第 i 行原本的行尾串。"""
    norm, eols = [], []
    for L in text.splitlines(keepends=True):
        if L.endswith("\r\n"):
            norm.append(L[:-2]); eols.append("\r\n")
        elif L.endswith("\n"):
            norm.append(L[:-1]); eols.append("\n")
        elif L.endswith("\r"):
            norm.append(L[:-1]); eols.append("\r")
        else:
            norm.append(L); eols.append("")
    return norm, eols


def _scan(line, depth, quote):
    """推进括号深度，跳过引号内与 // 之后的内容。"""
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if quote:
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "'\"":
            quote = c
            i += 1
            continue
        if c == "/" and i + 1 < n and line[i + 1] == "/":
            break
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        i += 1
    return depth, quote


def split_units(lines):
    """→ units: [{'decl','start','end','lines':[...]}]，lines 含 leading trivia。

    leading trivia（对象前的注释/空行）并入该对象，保证拼接可逐字节还原。
    """
    units = []
    cur, start, depth, quote, opened = None, None, 0, None, False
    pending = []          # 尚未归属的非对象行（注释/空行/杂项）

    for i, raw_line in enumerate(lines):
        s = raw_line
        stripped = s.strip()
        if cur is None:
            is_decl = (bool(stripped) and not stripped.startswith(("//", "#"))
                       and not s[0].isspace() and bool(_DECL_LINE.match(s)))
            if is_decl:
                cur = stripped.split("(")[0].strip()
                start = i - len(pending)     # 把前导注释/空行算进来
                pending = []
                opened = False
            else:
                pending.append(i)
                continue
        depth, quote = _scan(s, depth, quote)
        if depth > 0:
            opened = True
        if opened and depth <= 0:
            units.append({"decl": cur, "start": start, "end": i,
                          "lines": lines[start:i + 1]})
            cur, start, depth, quote, opened = None, None, 0, None, False

    if cur is not None:      # 未闭合（异常文件）：整段收尾，调用方自行决定是否降级
        units.append({"decl": cur, "start": start, "end": len(lines) - 1,
                      "lines": lines[start:], "unterminated": True})
        pending = []
    return units, pending


class Doc(object):
    """解析结果：可逐字节还原原文。"""

    __slots__ = ("units", "tail", "eol", "final_newline")

    def __init__(self, units, tail, eol, final_newline):
        self.units = units
        self.tail = tail
        self.eol = eol
        self.final_newline = final_newline

    @property
    def sep(self):
        return "\r\n" if self.eol == "CRLF" else "\n"

    def text(self):
        lines = []
        for u in self.units:
            lines.extend(u["lines"])
        lines.extend(self.tail)
        out = self.sep.join(lines)
        if self.final_newline and lines:
            out += self.sep
        return out


def parse(text):
    """→ Doc(units, tail, eol, final_newline)。

    units[i]['lines'] 含该对象的 leading trivia（前导注释/空行），
    units[i]['body']/['sha'] 供比对用（body 不含 leading trivia 之外的改写）。
    """
    lines, eols = split_lines_keep(text)
    if not lines:
        return Doc([], [], "LF", False)
    if all(e == "\r\n" or e == "" for e in eols) and any(e == "\r\n" for e in eols):
        eol = "CRLF"
    elif all(e == "\n" or e == "" for e in eols):
        eol = "LF"
    elif not any(eols):
        eol = "NONE"
    else:
        eol = "MIXED"
    units, pending = split_units(lines)
    tail = [lines[i] for i in pending]
    for u in units:
        u["body"] = "\n".join(u["lines"])
        u["sha"] = hashlib.sha256(u["body"].encode("utf-8")).hexdigest()
    return Doc(units, tail, eol, text.endswith("\n"))


def unit_map(units):
    """decl → unit。重名时后者覆盖（并记录到 dup）。"""
    m, dup = {}, []
    for u in units:
        if u["decl"] in m:
            dup.append(u["decl"])
        m[u["decl"]] = u
    return m, dup


def split_lines_array(lines):
    """把一行字符串切成长度受限的行块（manifest 里做可读性分组，不参与匹配）。"""
    return lines


def norm_line(s):
    return s.rstrip()


def md5(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def find_block(lines, old, ctx_before=(), ctx_after=()):
    """在 lines 里找「旧行块 + 上下 N 行」的命中位置（起点索引）。

    old 为空时表示插入：位置 i 需满足 lines[i-len(cb):i] == cb 且 lines[i:i+len(ca)] == ca。
    导出端与注入端**必须共用这一份实现**，否则 occurrence / nth 口径会错位。
    """
    ctx_before, ctx_after = list(ctx_before), list(ctx_after)
    hits = []
    n_old = len(old)
    if n_old == 0:
        lo, hi = len(ctx_before), len(lines) - len(ctx_after)
        for i in range(lo, hi + 1):
            if lines[i - len(ctx_before):i] == ctx_before and \
               lines[i:i + len(ctx_after)] == ctx_after:
                hits.append(i)
        return hits
    for i in range(0, len(lines) - n_old + 1):
        if lines[i:i + n_old] != old:
            continue
        if ctx_before and lines[max(0, i - len(ctx_before)):i] != ctx_before:
            continue
        if ctx_after and lines[i + n_old:i + n_old + len(ctx_after)] != ctx_after:
            continue
        hits.append(i)
    return hits


def find_block_fuzzy(lines, old, ctx_before=(), ctx_after=(), slack=12):
    """容错版：允许「我们的上下文」与「旧行块」之间夹着官方新插入的行。

    真实升级里最常见的冲突形态不是同位置改写，而是**双方都往同一处插**：
    官方在 `UnitRuleList` 末尾加一条规则，我们也在末尾加一条 → 严格相邻匹配必失手，
    但语义上完全可以共存。

    三级优先，**先紧后松**（否则对称放宽会把同一处判成两个候选）：
      ① 前上下文紧邻、后上下文在 slack 行内 —— 官方插在我们后面
      ② 后上下文紧邻、前上下文在 slack 行内 —— 官方插在我们前面
      ③ 两侧都在 slack 行内
    """
    ctx_before, ctx_after = list(ctx_before), list(ctx_after)
    n_old = len(old)
    cands = []      # (i, grade)
    for i in range(0, len(lines) - n_old + 1):
        if lines[i:i + n_old] != old:
            continue
        b_adj = (not ctx_before) or (i >= len(ctx_before) and
                                     lines[i - len(ctx_before):i] == ctx_before)
        b_near = b_adj or (bool(ctx_before) and any(
            i - d - len(ctx_before) >= 0 and
            lines[i - d - len(ctx_before):i - d] == ctx_before
            for d in range(1, slack + 1)))
        j = i + n_old
        a_adj = (not ctx_after) or lines[j:j + len(ctx_after)] == ctx_after
        a_near = a_adj or (bool(ctx_after) and any(
            lines[j + d:j + d + len(ctx_after)] == ctx_after
            for d in range(1, slack + 1)))
        if b_adj and a_near:
            cands.append((i, 1))
        elif a_adj and b_near:
            cands.append((i, 2))
        elif b_near and a_near:
            cands.append((i, 3))
    for grade in (1, 2, 3):
        hits = [i for i, g in cands if g == grade]
        if hits:
            return hits
    return []


def read_bytes_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
