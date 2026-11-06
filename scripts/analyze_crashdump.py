# -*- coding: utf-8 -*-
"""
CrashRpt minidump 解析器（零依赖）。

目的：WARNO 崩在游戏里、没有符号也没有 cdb 时，仍然能回答三件事——
  1. 精确位置：异常地址 - 模块基址 = RVA，再定位到 .pdata 里的函数区间
  2. 现场：异常码、读写了哪个地址、崩溃线程的寄存器（RCX=this 往往是关键）
  3. 归属：把栈上所有「指向代码段」的值映射成函数，再扫这些函数引用到的
     .rdata 字符串 —— 引擎没有导出符号，但字段名/类名/RTTI 都以字面量留在 exe 里，
     这等于给函数打了一堆「它认识什么」的标签。

用法：
  python analyze_crashdump.py <crashdump.dmp> [--exe <WARNO.exe>] [--top 25]
"""

import struct
import sys
import os
import bisect

# ---------- minidump 基本结构 ----------
HDR = struct.Struct("<IIIIIIQ")
DIRENT = struct.Struct("<III")

ST_THREADLIST = 3
ST_MODULELIST = 4
ST_MEMORYLIST = 5
ST_EXCEPTION = 6
ST_SYSTEMINFO = 7
ST_MEMORY64LIST = 9


def ru32(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


def ru64(buf, off):
    return struct.unpack_from("<Q", buf, off)[0]


def rd_string(buf, rva):
    n = ru32(buf, rva)
    raw = buf[rva + 4:rva + 4 + n]
    try:
        return raw.decode("utf-16-le")
    except UnicodeDecodeError:
        return raw.decode("utf-16-le", "replace")


class Dump:
    def __init__(self, path):
        self.buf = open(path, "rb").read()
        b = self.buf
        sig, ver, nstreams, dirrva, chk, ts, flags = HDR.unpack_from(b, 0)
        if sig != 0x504D444D:
            raise SystemExit("不是 minidump（签名 %08x）" % sig)
        self.time = ts
        self.streams = {}
        for i in range(nstreams):
            o = dirrva + i * 12
            st, size, rva = DIRENT.unpack_from(b, o)
            self.streams.setdefault(st, []).append((size, rva))

    def get(self, st):
        v = self.streams.get(st)
        return v[0] if v else None

    # --- 模块表 ---
    def modules(self):
        out = []
        loc = self.get(ST_MODULELIST)
        if not loc:
            return out
        _, rva = loc
        n = ru32(self.buf, rva)
        o = rva + 4
        # sizeof(MINIDUMP_MODULE) = 8+4+4+4+4+52+8+8+8+8 = 108
        for i in range(n):
            p = o + i * 108
            base = ru64(self.buf, p)
            size = ru32(self.buf, p + 8)
            name_rva = ru32(self.buf, p + 20)
            out.append((base, size, rd_string(self.buf, name_rva)))
        return out

    # --- 线程表 ---
    def threads(self):
        out = []
        loc = self.get(ST_THREADLIST)
        if not loc:
            return out
        _, rva = loc
        n = ru32(self.buf, rva)
        o = rva + 4
        # sizeof(MINIDUMP_THREAD) = 4+4+4+4+8+ (8+4+4) + (4+4) = 48
        for i in range(n):
            p = o + i * 48
            tid = ru32(self.buf, p)
            stack_start = ru64(self.buf, p + 24)
            stack_size = ru32(self.buf, p + 32)
            stack_rva = ru32(self.buf, p + 36)
            ctx_size = ru32(self.buf, p + 40)
            ctx_rva = ru32(self.buf, p + 44)
            out.append(dict(tid=tid, stack_start=stack_start, stack_size=stack_size,
                            stack_rva=stack_rva, ctx_size=ctx_size, ctx_rva=ctx_rva))
        return out

    # --- 异常 ---
    def exception(self):
        loc = self.get(ST_EXCEPTION)
        if not loc:
            return None
        _, rva = loc
        tid = ru32(self.buf, rva)
        code = ru32(self.buf, rva + 8)
        addr = ru64(self.buf, rva + 24)
        nparams = ru32(self.buf, rva + 32)
        params = [ru64(self.buf, rva + 40 + 8 * i) for i in range(min(nparams, 15))]
        ctx_size = ru32(self.buf, rva + 160)
        ctx_rva = ru32(self.buf, rva + 164)
        return dict(tid=tid, code=code, addr=addr, params=params,
                    ctx_size=ctx_size, ctx_rva=ctx_rva)

    # --- 任意 RVA 处的内存 ---
    def mem(self, addr, size):
        for st in (ST_MEMORY64LIST,):
            loc = self.get(st)
            if not loc:
                continue
            _, rva = loc
            n = ru64(self.buf, rva)
            basedata = ru64(self.buf, rva + 8)
            ranges = []
            for i in range(n):
                start = ru64(self.buf, rva + 16 + 16 * i)
                sz = ru64(self.buf, rva + 24 + 16 * i)
                ranges.append((start, sz))
            off = basedata
            for start, sz in ranges:
                if start <= addr < start + sz:
                    delta = addr - start
                    return self.buf[off + delta:off + delta + size]
                off += sz
        loc = self.get(ST_MEMORYLIST)
        if loc:
            _, rva = loc
            n = ru32(self.buf, rva)
            for i in range(n):
                p = rva + 4 + i * 16
                start = ru64(self.buf, p)
                sz = ru32(self.buf, p + 8)
                rrva = ru32(self.buf, p + 12)
                if start <= addr < start + sz:
                    d = addr - start
                    return self.buf[rrva + d:rrva + d + size]
        return None


# ---------- PE：段表 / .pdata ----------
class PE:
    def __init__(self, path):
        self.data = open(path, "rb").read()
        d = self.data
        pe = ru32(d, 0x3C)
        nsec = struct.unpack_from("<H", d, pe + 6)[0]
        optsz = struct.unpack_from("<H", d, pe + 20)[0]
        opt = pe + 24
        self.imagebase = struct.unpack_from("<Q", d, opt + 24)[0]
        self.secs = []
        so = opt + optsz
        for i in range(nsec):
            o = so + i * 40
            name = d[o:o + 8].rstrip(b"\x00").decode("latin1")
            vsz, va, rsz, ra = struct.unpack_from("<IIII", d, o + 8)
            self.secs.append(dict(name=name, va=va, vsz=vsz, ra=ra, rsz=rsz))
        self.pdata = self._pdata()

    def rva2off(self, rva):
        for s in self.secs:
            if s["va"] <= rva < s["va"] + max(s["vsz"], s["rsz"]):
                return s["ra"] + (rva - s["va"])
        return None

    def read(self, rva, n):
        o = self.rva2off(rva)
        if o is None:
            return None
        return self.data[o:o + n]

    def _pdata(self):
        # 数据目录第 4 项 = Exception directory
        d = self.data
        pe = ru32(d, 0x3C)
        opt = pe + 24
        nrva = ru32(d, opt + 108)
        if nrva < 4:
            return []
        # 数据目录：0 Export / 1 Import / 2 Resource / 3 Exception / 4 Certificate / 5 Reloc / 6 Debug
        er, esz = struct.unpack_from("<II", d, opt + 112 + 3 * 8)
        if not er:
            return []
        o = self.rva2off(er)
        out = []
        for i in range(esz // 12):
            b, e, u = struct.unpack_from("<III", d, o + i * 12)
            out.append((b, e))
        out.sort()
        return out

    def func_of(self, rva):
        starts = [x[0] for x in self.pdata]
        i = bisect.bisect_right(starts, rva) - 1
        if i < 0:
            return None
        b, e = self.pdata[i]
        if b <= rva < e:
            return (b, e)
        return None

    # --- 粗粒度「这个函数认识什么字符串」 ---
    def strings_in_func(self, begin, end, limit=6):
        n = min(end - begin, 0x2000)
        code = self.read(begin, n)
        if not code:
            return []
        hits = []
        i = 0
        while i + 7 < len(code):
            # 48/4c 8d / 05|0d|15|1d|25|2d|35|3d  = LEA reg, [rip+disp32]
            if code[i] in (0x48, 0x4C) and code[i + 1] == 0x8D and (code[i + 2] & 0xC7) == 0x05:
                disp = struct.unpack_from("<i", code, i + 3)[0]
                tgt = begin + i + 7 + disp
                s = self.cstring_at(tgt)
                if s:
                    hits.append(s)
                i += 7
                continue
            i += 1
        seen, out = set(), []
        for s in hits:
            if s not in seen:
                seen.add(s)
                out.append(s)
        return out[:limit]

    def cstring_at(self, rva, maxlen=64):
        raw = self.read(rva, maxlen)
        if not raw:
            return None
        z = raw.find(b"\x00")
        if z < 6:
            return None
        s = raw[:z]
        try:
            t = s.decode("ascii")
        except UnicodeDecodeError:
            return None
        if not all(32 <= ord(c) < 127 for c in t):
            return None
        return t


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    dmp_path = sys.argv[1]
    exe = None
    for i, a in enumerate(sys.argv):
        if a == "--exe":
            exe = sys.argv[i + 1]
    top = 25
    for i, a in enumerate(sys.argv):
        if a == "--top":
            top = int(sys.argv[i + 1])

    d = Dump(dmp_path)
    mods = d.modules()
    ex = d.exception()

    print("=== dump 基本信息 ===")
    print("文件:", os.path.basename(dmp_path), "大小", os.path.getsize(dmp_path))
    print("模块数:", len(mods))
    main_mod = None
    for base, size, name in mods:
        if name.lower().endswith("warno.exe"):
            main_mod = (base, size, name)
    if not main_mod:
        raise SystemExit("模块表里找不到 WARNO.exe")
    base, size, name = main_mod
    print("主模块:", name)
    print("  基址 %#x  大小 %#x" % (base, size))
    if not exe:
        exe = name
    pe = PE(exe)
    print("  磁盘映像 imagebase %#x（ASLR 偏移 %#x）" % (pe.imagebase, base - pe.imagebase))

    print("\n=== 异常现场 ===")
    if not ex:
        print("无 ExceptionStream（不是异常退出？）")
        return
    rva = ex["addr"] - base
    print("线程 tid %d  异常码 %#x  异常地址 %#x  → RVA %#x" %
          (ex["tid"], ex["code"], ex["addr"], rva))
    names = {0xC0000005: "ACCESS_VIOLATION", 0xC0000094: "INT_DIVIDE_BY_ZERO",
             0xC00000FD: "STACK_OVERFLOW", 0xC0000409: "STACK_BUFFER_OVERRUN",
             0x80000003: "BREAKPOINT", 0xE06D7363: "CPP_EXCEPTION"}
    print("  类型:", names.get(ex["code"], hex(ex["code"])))
    if ex["code"] == 0xC0000005 and len(ex["params"]) >= 2:
        how = {0: "读", 1: "写", 8: "执行"}.get(ex["params"][0], str(ex["params"][0]))
        print("  访问方式: %s 地址 %#x" % (how, ex["params"][1]))
    fn = pe.func_of(rva)
    print("  所属函数区间:", ("%#x..%#x（函数内偏移 +%#x）" % (fn[0], fn[1], rva - fn[0])) if fn else "未在 .pdata 命中")

    # 寄存器
    ctx = None
    for t in d.threads():
        if t["tid"] == ex["tid"]:
            ctx = t
    # 寄存器：必须用 ExceptionStream 里的 ThreadContext（真正的崩溃现场）；
    # ThreadList 里的 context 是「抓 dump 那一刻」的，已落在异常处理函数里。
    regs = {}
    cbuf = d.buf[ex["ctx_rva"]:ex["ctx_rva"] + min(ex["ctx_size"], 0x4D0)]
    if len(cbuf) >= 0x100:
        regs = {
            "Rax": ru64(cbuf, 0x78), "Rcx": ru64(cbuf, 0x80), "Rdx": ru64(cbuf, 0x88),
            "Rbx": ru64(cbuf, 0x90), "Rsp": ru64(cbuf, 0x98), "Rbp": ru64(cbuf, 0xA0),
            "Rsi": ru64(cbuf, 0xA8), "Rdi": ru64(cbuf, 0xB0), "R8": ru64(cbuf, 0xB8),
            "R9": ru64(cbuf, 0xC0), "Rip": ru64(cbuf, 0xF8),
        }
        print("\n=== 崩溃线程寄存器 ===")
        print("  Rip %#x (RVA %#x)  Rsp %#x  Rbp %#x" %
              (regs["Rip"], regs["Rip"] - base, regs["Rsp"], regs["Rbp"]))
        print("  Rcx %#x  Rdx %#x  R8 %#x  R9 %#x" % (regs["Rcx"], regs["Rdx"], regs["R8"], regs["R9"]))
        print("  Rax %#x  Rbx %#x  Rsi %#x  Rdi %#x" % (regs["Rax"], regs["Rbx"], regs["Rsi"], regs["Rdi"]))
        print("  （x64 前四个参数：Rcx / Rdx / R8 / R9；成员函数 Rcx = this）")

    # 栈扫描：从 Rsp 往上扫（下面全是旧帧残留，会污染结果）
    if ctx and ctx["stack_size"]:
        raw = d.buf[ctx["stack_rva"]:ctx["stack_rva"] + ctx["stack_size"]]
        start = 0
        if regs.get("Rsp") and ctx["stack_start"] <= regs["Rsp"] < ctx["stack_start"] + ctx["stack_size"]:
            start = regs["Rsp"] - ctx["stack_start"]
        cands = []
        for off in range(start - start % 8, len(raw) - 8, 8):
            v = struct.unpack_from("<Q", raw, off)[0]
            if base <= v < base + size:
                r = v - base
                f = pe.func_of(r)
                cands.append((off, v, r, f))
        print("\n=== 栈上的代码地址（帧偏移 → RVA → 函数）===")
        seen = set()
        shown = 0
        for off, v, r, f in cands:
            key = (f[0] if f else r)
            if key in seen:
                continue
            seen.add(key)
            shown += 1
            tag = ("%#x..%#x +%#x" % (f[0], f[1], r - f[0])) if f else "?"
            print("  栈+%#06x  RVA %#08x  →  函数 %s" % (off, r, tag))
            if shown >= top:
                break

        print("\n=== 这些函数认识哪些字符串（引擎无符号，用字面量反推归属）===")
        seen = set()
        shown = 0
        for off, v, r, f in cands:
            if not f or f[0] in seen:
                continue
            seen.add(f[0])
            ss = pe.strings_in_func(f[0], f[1])
            if not ss:
                continue
            shown += 1
            print("  [RVA %#08x] %s" % (f[0], " | ".join(ss)))
            if shown >= top:
                break


if __name__ == "__main__":
    main()
