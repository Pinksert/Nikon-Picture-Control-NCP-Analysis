# -*- coding: utf-8 -*-
"""全量预演：用 pc2.txt 里 42 个文件的完整字节 dump 重建 NP2/NP3，跑 np2ncp.convert，
   输出 36 个文件的转换清单，并把生成的 NCP 落到 ncp_out/。
   （本轮沙箱读不了「滤镜」目录，故走 dump；在能读的机器上直接 python np2ncp.py 即可）"""
import re, struct, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')
from np2ncp import convert, KNOWN_BASE

HERE = os.path.dirname(os.path.abspath(__file__))
TXT = open(os.path.join(HERE, 'pc2.txt'), encoding='utf-8').read()
OUT = os.path.join(HERE, 'ncp_out')
os.makedirs(OUT, exist_ok=True)

raws, cur = {}, None
for line in TXT.splitlines():
    m = re.match(r'^--- (\w+)\.(NP2|NP3) \((\d+) bytes\)', line)
    if m:
        f = m.group(1) + '.' + m.group(2)
        raws[f] = bytearray(b'NCP\0'); cur = f; continue
    m = re.match(r'\s+type=([0-9A-F]{8}) len=(\d+)\s+(?:\[([0-9A-F ]+)\]|TEXT=\'(.*)\'|.*)', line)
    if m and cur:
        t, ln = int(m.group(1), 16), int(m.group(2))
        if m.group(3):
            d = bytes(int(x, 16) for x in m.group(3).split())
        else:
            d = (m.group(4) or '').encode('utf-16-be')
            d += b'\x00' * (ln - len(d))
        raws[cur] += struct.pack('>II', t, ln) + d[:ln]
for f in raws:
    raws[f] += b'\x00\x00\x00\x00'

order = {'NP2': 0, 'NP3': 1}
files = sorted(raws, key=lambda f: (order[f[-3:]], f))
ok = warn = 0
lines = []
for f in files:
    got, rep = convert(bytes(raws[f]))
    open(os.path.join(OUT, f[:-4] + '_from_' + f[-3:].lower() + '.NCP'), 'wb').write(got)
    sl = ' '.join('%02X' % c for c in got[40:48])
    base = struct.unpack('>H', got[36:38])[0]
    known = base in KNOWN_BASE
    ok += known; warn += (not known)
    lines.append('%-16s 底子 %04X %-6s 滑块 %s' % (f, base,
                 '可用' if known else '无曲线', sl))
    for r in rep:
        lines.append('      ' + r)

head = ['NP2 / NP3 全量转 NCP 预演（%d 个文件）' % len(files),
        '=' * 78, '']
tail = ['', '=' * 78,
        '底子在 NCP 六个底子内、老机身真能用：%d 个' % ok,
        '底子 NCP 不认（文件能生成但没曲线）：%d 个' % warn,
        'NCP 文件已生成到：%s' % OUT]
txt = '\n'.join(head + lines + tail)
open(os.path.join(HERE, 'np2ncp_full_report.txt'), 'w', encoding='utf-8').write(txt)
print(txt)
