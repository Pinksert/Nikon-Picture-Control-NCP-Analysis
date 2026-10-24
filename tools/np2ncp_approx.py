# -*- coding: utf-8 -*-
"""生成近似版 NCP：底子换成 NCP 六个已知底子里最接近的，参数照搬。
   数据源同 np2ncp_full.py（pc2.txt 的真实 dump）。"""
import re, struct, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')
from np2ncp import convert, KNOWN_BASE

HERE = os.path.dirname(os.path.abspath(__file__))
TXT = open(os.path.join(HERE, 'pc2.txt'), encoding='utf-8').read()
OUT = os.path.join(HERE, 'ncp_approx')
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
lines = ['近似版 NCP：底子换成 NCP 六个已知底子里最接近的，参数照搬', '=' * 78, '']
cnt = {}
for f in files:
    got, rep = convert(bytes(raws[f]), approx=True)
    open(os.path.join(OUT, f[:-4] + '_from_' + f[-3:].lower() + '.NCP'), 'wb').write(got)
    base = struct.unpack('>H', got[36:38])[0]
    cnt[base] = cnt.get(base, 0) + 1
    lines.append('%-16s 底子 %04X (%-4s)  滑块 %s' % (f, base, KNOWN_BASE.get(base, '?'),
                 ' '.join('%02X' % c for c in got[40:48])))
    for r in rep:
        if r.startswith('[近似]'):
            lines.append('      ' + r)

lines += ['', '=' * 78, '底子分布：' + '  '.join('%04X %s ×%d' % (b, KNOWN_BASE.get(b, '?'), n)
                                                for b, n in sorted(cnt.items())),
          '共 %d 个，全部落在 NCP 认得的底子上' % len(files),
          'NCP 文件已生成到：%s' % OUT]
txt = '\n'.join(lines)
open(os.path.join(HERE, 'ncp_approx_report.txt'), 'w', encoding='utf-8').write(txt)
print(txt)
