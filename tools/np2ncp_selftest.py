# -*- coding: utf-8 -*-
"""端到端自检：用 pc2.txt 还原出的 NP2/NP3 真字节跑 np2ncp.py，与真实 NCP 的 52 字节比。"""
import re, struct, sys
sys.path.insert(0, r'C:\Users\admin\WorkBuddy\D300固件\.workbuddy\tmp')
sys.stdout.reconfigure(encoding='utf-8')
from np2ncp import convert

TXT = open(r'C:\Users\admin\WorkBuddy\D300固件\.workbuddy\tmp\pc2.txt', encoding='utf-8').read()

# 真实 NCP（模板 + 名字 + 曲线号 + 8 滑块）
ncp = {}
for m in re.finditer(r'^(\w+)\.NCP\s+ver=\S+ curve=(\w+) (\w+) flag=\S+ unk39=\S+ sliders=([0-9A-F ]+)',
                     TXT, re.M):
    ncp[m.group(1)] = (int(m.group(2) + m.group(3), 16), [int(x, 16) for x in m.group(4).split()])

# 从 dump 重建 NP2/NP3 字节
raws = {}
cur = None
for line in TXT.splitlines():
    m = re.match(r'^--- (\w+)\.(NP2|NP3) \((\d+) bytes\)', line)
    if m:
        f = m.group(1) + '.' + m.group(2)
        raws[f] = bytearray(b'NCP\0'); cur = f; continue
    m = re.match(r'\s+type=([0-9A-F]{8}) len=(\d+)\s+(?:\[([0-9A-F ]+)\]|TEXT=\'(.*)\'|.*)', line)
    if m and cur:
        t = int(m.group(1), 16)
        ln = int(m.group(2))
        if m.group(3):
            d = bytes(int(x, 16) for x in m.group(3).split())
        else:
            s = m.group(4) or ''
            d = s.encode('utf-16-be')
            d = d + b'\x00' * (ln - len(d))
        raws[cur] += struct.pack('>II', t, ln) + d[:ln]
for f in raws:
    raws[f] += b'\x00\x00\x00\x00'

print("%-16s %-8s %s" % ('文件', '结果', '说明'))
print('-' * 78)
allhit = 0
for n in ['STANDARD', 'NEUTRAL', 'VIVID', 'PORTRAIT', 'LANDSCAPE', 'MONOCHROME']:
    curve, sl = ncp[n]
    exp = bytearray(52)
    exp[0:4] = b'NCP\0'
    struct.pack_into('>I', exp, 4, 1)
    struct.pack_into('>I', exp, 8, 36)
    exp[12:16] = b'0100'
    exp[16:16 + len(n)] = n.encode()
    struct.pack_into('>H', exp, 36, curve)
    exp[38] = 0
    exp[39] = 0xFF
    for i, s in enumerate(sl):
        exp[40 + i] = s
    for ext in ('NP2', 'NP3'):
        f = n + '.' + ext
        if f not in raws:
            continue
        got, rep = convert(bytes(raws[f]))
        hit = sum(1 for a, b in zip(got, exp) if a == b)
        allhit += 1
        print("%-16s %s %d/52 字节一致" % (f, 'OK  ' if got == exp else 'DIFF', hit))
        if got != exp:
            print('     期望:', bytes(exp).hex(' ').upper())
            print('     实得:', got.hex(' ').upper())
        for r in rep:
            print('     ' + r)

print()
print('=' * 78)
print('再看新格式独有的预设（NCP 里没有底子）')
print('=' * 78)
for f in ['FLAT.NP3', 'AUTO.NP3', 'DREAM.NP3', 'BLUE.NP3', 'BINARY.NP3']:
    if f not in raws:
        continue
    got, rep = convert(bytes(raws[f]))
    print('\n%s -> %s' % (f, got.hex(' ').upper()))
    for r in rep:
        print('     ' + r)
