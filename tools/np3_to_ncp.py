# -*- coding: utf-8 -*-
"""把滤镜目录里全部 28 个 NP3 转成 NCP（近似底子 + 参数照搬），
   并与之前用 dump 预演生成的 ncp_approx 做字节级交叉验证"""
import os, sys, json, struct
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r'C:\Users\admin\WorkBuddy\D300固件\.workbuddy\tmp')
from np2ncp import convert, KNOWN_BASE

SRC = r'C:\Users\admin\WorkBuddy\D300固件\滤镜'
DST = r'C:\Users\admin\WorkBuddy\D300固件\ncp_from_np3'
OLD = r'C:\Users\admin\WorkBuddy\D300固件\ncp_approx'
os.makedirs(DST, exist_ok=True)

files = sorted(f for f in os.listdir(SRC) if f.upper().endswith('.NP3'))
print('滤镜目录里的 NP3：%d 个' % len(files))

rows, cnt, same = [], {}, 0
for f in files:
    raw = open(os.path.join(SRC, f), 'rb').read()
    out, rep = convert(raw, approx=True)
    open(os.path.join(DST, f[:-4] + '_from_np3.NCP'), 'wb').write(out)
    base = struct.unpack('>H', out[36:38])[0]
    cnt[base] = cnt.get(base, 0) + 1
    # 与 dump 预演版比对
    oldp = os.path.join(OLD, f[:-4] + '_from_np3.NCP')
    if os.path.exists(oldp):
        same += (open(oldp, 'rb').read() == out)
    note = ''
    for r in rep:
        if r.startswith('[近似]'):
            note = r[4:]
    rows.append((f, base, KNOWN_BASE.get(base, '?'), ' '.join('%02X' % c for c in out[40:48]), note))

print('\n%-16s %-6s %-5s %-25s %s' % ('文件', '底子', '底子名', '八个滑块', '近似说明'))
print('-' * 108)
for f, b, bn, sl, note in rows:
    print('%-16s %04X  %-5s %-25s %s' % (f, b, bn, sl, note))

print('\n底子分布：' + '  '.join('%04X %s ×%d' % (b, KNOWN_BASE.get(b, '?'), n)
                                for b, n in sorted(cnt.items())))
print('共转换 %d 个 -> %s' % (len(files), DST))
print('与 dump 预演版逐字节一致的：%d / %d' % (same, len(files)))
