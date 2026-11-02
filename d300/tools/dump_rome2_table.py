#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dump_rome2_table.py —— 从 NX Studio 的 Rome2.dll 里 dump Picture Control 注册表。

为什么需要它：
    写一个不存在的底子编号进 NCP，NX Studio 会直接闪退（Rome2.dll +0x13d8f2）。
    崩的原因不是文件坏了，是它的查找函数在「查不到」时返回表长而不是 -1，
    调用方没做边界检查，拿表长当索引取出空指针就解引用。

    这个脚本把那张表原样读出来：每个合法编号、它属于哪个命名空间、叫什么名字。
    有了它，「能写哪些底子」就不用再靠崩溃去试。

用法：
    python d300/tools/dump_rome2_table.py
    python d300/tools/dump_rome2_table.py --csv samples/profile_table.csv
    python d300/tools/dump_rome2_table.py --asm 0x13d8f2     # 反汇编崩溃点附近

依赖：capstone（pip install capstone），只有 --asm 需要。
"""
import argparse
import os
import struct
import sys

DLL = r'C:\Program Files\Nikon\NXStudio\Rome2.dll'

# 这两个常量来自反汇编，不是猜的：
#   lea rax,[rip+0x1a6834] @ 0x13A19D（下一条指令 0x13A1A4）→ 表首 0x2E0970
#   lea r8, [rip+0x1a7d4b] @ 0x13A1A6（下一条指令 0x13A1AD）→ 表尾 0x2E18F8
TBL_RVA = 0x2E0970
TBL_END = 0x2E18F8
ENTRY = 0x68          # imul r9, r8, 0x68
PTR_OFF = 0x40        # mov rax,[r9+rcx+0x40]
IMAGE_BASE = 0x180000000


def sections(b):
    """返回 [(name, va, vsize, raw, rsize)]"""
    pe = struct.unpack_from('<I', b, 0x3C)[0]
    n = struct.unpack_from('<H', b, pe + 6)[0]
    opt = pe + 24
    so = opt + struct.unpack_from('<H', b, pe + 20)[0]
    out = []
    for i in range(n):
        o = so + i * 40
        name = b[o:o + 8].rstrip(b'\0').decode('latin1')
        vsize, va, rsize, raw = struct.unpack_from('<IIII', b, o + 8)
        out.append((name, va, vsize, raw, rsize))
    return out


def make_mapper(secs):
    def rva2off(rva):
        for name, va, vsize, raw, rsize in secs:
            if va <= rva < va + max(vsize, rsize):
                return raw + (rva - va)
        return None
    return rva2off


def read_table(b, rva2off):
    rows = []
    n = (TBL_END - TBL_RVA) // ENTRY
    base = rva2off(TBL_RVA)
    for i in range(n):
        o = base + i * ENTRY
        key = struct.unpack_from('<I', b, o)[0]
        ptr = struct.unpack_from('<Q', b, o + PTR_OFF)[0]
        fo = rva2off(ptr - IMAGE_BASE) if ptr else None
        name = '?'
        if fo:
            raw = b[fo:fo + 0x40].split(b'\0')[0]
            if raw and all(32 <= c < 127 for c in raw):
                name = raw.decode('latin1')
        rows.append(dict(idx=i, kind=key >> 16, num=key & 0xFFFF, name=name))
    return rows


def print_table(rows):
    print('%3s %-5s %-7s %s' % ('#', 'kind', 'num', '名字'))
    print('-' * 40)
    for r in rows:
        print('%3d %-5d 0x%04X  %s' % (r['idx'], r['kind'], r['num'], r['name']))
    print()
    for kd in sorted({r['kind'] for r in rows}):
        sub = [r for r in rows if r['kind'] == kd]
        print('kind=%d 共 %d 项：%s' % (kd, len(sub),
              ', '.join('0x%04X=%s' % (r['num'], r['name']) for r in sub)))
    print()
    print('默认命名空间（kind=1）可用编号：%s'
          % ', '.join('0x%04X(%s)' % (r['num'], r['name'])
                      for r in rows if r['kind'] == 1))


def disasm(b, rva2off, rva, span=0x40):
    try:
        import capstone
    except ImportError:
        raise SystemExit('需要 capstone：pip install capstone')
    off = rva2off(rva)
    if off is None:
        raise SystemExit('RVA %X 不在任何节里' % rva)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    start = rva - span
    for ins in md.disasm(b[rva2off(start):off + span], start):
        mark = '   <== 崩溃点' if ins.address == rva else ''
        print('%08X  %-18s %s%s' % (ins.address, ins.bytes.hex(),
                                    ins.mnemonic + ' ' + ins.op_str, mark))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dll', default=DLL)
    ap.add_argument('--csv', default=None, help='另存一份 csv')
    ap.add_argument('--asm', default=None, help='反汇编某个 RVA，如 0x13d8f2')
    a = ap.parse_args()

    if not os.path.exists(a.dll):
        raise SystemExit('找不到 %s' % a.dll)
    b = open(a.dll, 'rb').read()
    secs = sections(b)
    rva2off = make_mapper(secs)

    print('dll   %s' % a.dll)
    print('大小  %.1f MB  节 %s' % (len(b) / 1048576.0, ', '.join(s[0] for s in secs)))
    print('表    RVA 0x%X .. 0x%X，项长 0x%X' % (TBL_RVA, TBL_END, ENTRY))
    print()

    rows = read_table(b, rva2off)
    print_table(rows)

    if a.csv:
        with open(a.csv, 'w', encoding='utf-8-sig') as f:
            f.write('idx,kind,num,name\n')
            for r in rows:
                f.write('%d,%d,0x%04X,%s\n' % (r['idx'], r['kind'], r['num'], r['name']))
        print('\ncsv -> %s' % a.csv)

    if a.asm:
        print('\n--- 反汇编 RVA %s 附近 ---' % a.asm)
        disasm(b, rva2off, int(a.asm, 0))


if __name__ == '__main__':
    main()
