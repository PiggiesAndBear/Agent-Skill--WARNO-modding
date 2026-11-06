#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ndfq.py — WARNO / Eugen NDF 只读查询器（不改文件）

为什么需要它：这类文件 5k~70万行，对象靠缩进与括号嵌套，肉眼 grep 很容易把
嵌套字段当成对象字段、或把子对象算进父对象。这个脚本做三件事：
  1. 按「括号配平」切对象（不是按行数猜窗口）
  2. 只取**最浅缩进**的那次字段出现（避免把子层字段当父层）
  3. 直接给「此类对象里这个字段有哪些取值」的直方图 → 判断自己的取值是否越界/有无先例

用法
  ndfq.py eol    <file> [file2 ...]                    探行尾/BOM
  ndfq.py objects <file> [--is TYPE] [--grep S]        列对象名
  ndfq.py show   <file> <name> [--raw]                 打印某个完整对象块
  ndfq.py stat   <file> [--is TYPE] --group F1,F2 [--where F=V] [--limit N]
  ndfq.py find   <file> [--is TYPE] --where F=V[,F2=V2] [--show F1,F2]
  ndfq.py fields <file> [--is TYPE]                    该类型里出现过的字段名 + 最浅缩进

示例
  ndfq.py stat Ammunition.ndf --is TAmmunitionDescriptor --group MinMaxCategory,ProjectileType
  ndfq.py find Ammunition.ndf --is TAmmunitionDescriptor --where CanShootOnPosition=True \
         --show MinMaxCategory,WeaponCursorType,NbSalvosShootOnPosition
  ndfq.py show UniteDescriptor.ndf Descriptor_Unit_LAV_25_US
"""
import argparse
import io
import os
import re
import sys
from collections import Counter, OrderedDict

HEAD_RE = re.compile(r'^(?:export\s+)?(\S+)\s+is\s+(\S+)\s*$')
FIELD_RE = re.compile(r'^( *)([A-Za-z_]\w*)\s*=\s*(.*?)\s*$')
TOKEN_RE = re.compile(r'\b([A-Z]{10})\b')


def read_lines(path):
    raw = open(path, 'rb').read()
    txt = raw.decode('utf-8', errors='replace')
    return raw, txt.split('\n')


def strip_comment(line):
    # 行内注释只处理 // 在引号外的情况；NDF 里出现频率很低
    if '//' in line:
        i = line.find('//')
        head = line[:i]
        if head.count('"') % 2 == 0:
            return head
    return line


def parse_objects(path):
    """返回 [(name, type, block_text, start_line)]，按括号配平切块。"""
    _, lines = read_lines(path)
    objs = []
    i, n = 0, len(lines)
    while i < n:
        m = HEAD_RE.match(strip_comment(lines[i]).rstrip())
        if not m:
            i += 1
            continue
        name, typ = m.group(1), m.group(2)
        start = i
        depth, j, opened = 0, i, False
        while j < n:
            s = strip_comment(lines[j])
            depth += s.count('(') - s.count(')')
            if '(' in s:
                opened = True
            if opened and depth <= 0:
                break
            j += 1
        block = '\n'.join(lines[start:j + 1])
        objs.append((name, typ, block, start + 1))
        i = j + 1
    return objs


def norm(v):
    v = v.strip().rstrip(',').strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
        v = v[1:-1]
    return v


def fields(block):
    """dict: 字段名 -> 最浅缩进那次出现的值（已归一化）。"""
    best = {}
    for line in block.split('\n'):
        m = FIELD_RE.match(strip_comment(line).rstrip())
        if not m:
            continue
        indent, fname, val = len(m.group(1)), m.group(2), norm(m.group(3))
        if fname not in best or indent < best[fname][0]:
            best[fname] = (indent, val)
    return {k: v for k, (_, v) in best.items()}


def match_where(fd, conds):
    for k, want in conds.items():
        got = fd.get(k)
        if got is None:
            return False
        if got != want and got.split('/')[-1] != want:
            return False
    return True


def select(path, is_type=None):
    objs = parse_objects(path)
    if is_type:
        objs = [o for o in objs if o[1] == is_type or o[1].split('(')[0] == is_type]
    return objs


def main(argv=None):
    ap = argparse.ArgumentParser(add_help=True)
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('eol')
    p.add_argument('files', nargs='+')

    p = sub.add_parser('objects')
    p.add_argument('file')
    p.add_argument('--is', dest='is_type')
    p.add_argument('--grep')

    p = sub.add_parser('show')
    p.add_argument('file')
    p.add_argument('name')
    p.add_argument('--line', action='store_true', help='带行号')

    p = sub.add_parser('stat')
    p.add_argument('file')
    p.add_argument('--is', dest='is_type')
    p.add_argument('--group', required=True)
    p.add_argument('--where')
    p.add_argument('--limit', type=int, default=30)
    p.add_argument('--missing', action='store_true', help='把缺字段也算一类')

    p = sub.add_parser('find')
    p.add_argument('file')
    p.add_argument('--is', dest='is_type')
    p.add_argument('--where')
    p.add_argument('--show')
    p.add_argument('--limit', type=int, default=200)

    p = sub.add_parser('fields')
    p.add_argument('file')
    p.add_argument('--is', dest='is_type')

    a = ap.parse_args(argv)

    if a.cmd == 'eol':
        for f in a.files:
            raw = open(f, 'rb').read()
            crlf = raw.count(b'\r\n')
            lf = raw.count(b'\n') - crlf
            print('%-60s size=%9d  CRLF=%7d  bareLF=%7d  BOM=%s  -> %s'
                  % (os.path.basename(f), len(raw), crlf, lf,
                     raw.startswith(b'\xef\xbb\xbf'),
                     'CRLF' if crlf and not lf else ('LF' if lf and not crlf else 'MIXED')))
        return 0

    if not os.path.exists(a.file):
        print('no such file: %s' % a.file, file=sys.stderr)
        return 2

    if a.cmd == 'objects':
        objs = select(a.file, getattr(a, 'is_type', None))
        for name, typ, _, ln in objs:
            if a.grep and a.grep.lower() not in name.lower():
                continue
            print('%-6d %-44s %s' % (ln, name, typ))
        print('--- total %d' % len(objs))
        return 0

    if a.cmd == 'show':
        for name, typ, block, ln in parse_objects(a.file):
            if name == a.name:
                if a.line:
                    for k, l in enumerate(block.split('\n')):
                        print('%6d  %s' % (ln + k, l))
                else:
                    print(block)
                return 0
        print('object not found: %s' % a.name, file=sys.stderr)
        return 3

    conds = {}
    if getattr(a, 'where', None):
        for part in a.where.split(','):
            if '=' not in part:
                print('bad --where item: %s' % part, file=sys.stderr)
                return 2
            k, v = part.split('=', 1)
            conds[k.strip()] = v.strip()

    if a.cmd == 'stat':
        keys = [k.strip() for k in a.group.split(',') if k.strip()]
        c = Counter()
        total = 0
        for name, typ, block, _ in select(a.file, a.is_type):
            fd = fields(block)
            if conds and not match_where(fd, conds):
                continue
            total += 1
            row = []
            for k in keys:
                v = fd.get(k)
                row.append('<missing>' if v is None else v)
            c[tuple(row)] += 1
        print('matched objects: %d' % total)
        for row, n in c.most_common(a.limit):
            print('  %5d  %s' % (n, ' | '.join(row)))
        if len(c) > a.limit:
            print('  ... %d more combos' % (len(c) - a.limit))
        return 0

    if a.cmd == 'find':
        shows = [s.strip() for s in (a.show or '').split(',') if s.strip()]
        n = 0
        for name, typ, block, _ in select(a.file, a.is_type):
            fd = fields(block)
            if conds and not match_where(fd, conds):
                continue
            n += 1
            if n > a.limit:
                continue
            if shows:
                print('  %-46s %s' % (name, ' | '.join(
                    '%s=%s' % (s, fd.get(s, '<missing>')) for s in shows)))
            else:
                print('  ' + name)
        print('--- matched %d%s' % (n, '' if n <= a.limit else ' (printed %d)' % a.limit))
        return 0

    if a.cmd == 'fields':
        dep = {}
        for _, _, block, _ in select(a.file, a.is_type):
            for line in block.split('\n'):
                m = FIELD_RE.match(strip_comment(line).rstrip())
                if m:
                    k, ind = m.group(2), len(m.group(1))
                    dep[k] = min(dep.get(k, 99), ind)
        for k, ind in sorted(dep.items(), key=lambda x: (x[1], x[0])):
            print('  indent=%-3d %s' % (ind, k))
        print('--- %d distinct field names' % len(dep))
        return 0

    return 1


if __name__ == '__main__':
    sys.exit(main())
