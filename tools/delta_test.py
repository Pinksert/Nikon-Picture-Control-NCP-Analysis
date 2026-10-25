# -*- coding: utf-8 -*-
"""验证：把人像的 δ（v3 - v2 控制点差）当作通用预补偿，能否重现 v3
   如果成立，其他预设就不用各自闭环一轮，直接套这条 δ"""
import sys, json, struct
import numpy as np
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r'C:\Users\admin\WorkBuddy\D300固件\.workbuddy\tmp')
from np2ncp_curve import build_ncp, OUT_MAX, parse_ncp

ROOT = r'C:\Users\admin\WorkBuddy\D300固件'


def ctrl_pts(path):
    b = open(path, 'rb').read()
    off = 4
    while off + 8 <= len(b):
        t, ln = struct.unpack('>II', b[off:off + 8])
        if t == 2:
            d = b[off + 8:off + 8 + ln]
            n = d[8]
            return [(d[9 + 2 * i], d[10 + 2 * i]) for i in range(n)]
        if t == 0:
            break
        off += 8 + ln
    return None


v3p = ctrl_pts(ROOT + r'\curve_out\PORTRAIT_curve_v3.NCP')
# v2 的控制点可以由 v2 LUT 直接重算（v2 本来就是 20 点采样生成的）
v2lut = np.array(json.load(open(ROOT + r'\portrait_lut_v2.json'))['lut'], dtype=np.float64)
_qx = np.arange(257) / 256.0 * 255.0
v2p = [(round(k * 255.0 / 19), int(round(np.interp(k * 255.0 / 19, _qx, v2lut / OUT_MAX * 255.0))))
       for k in range(20)]
print('v2 控制点:', v2p)
print('v3 控制点:', v3p)
delta = [(x, y3 - y2) for (x, y2), (_, y3) in zip(v2p, v3p)]
print('\nδ（每个控制点 x 处的上移量）:')
print('  ' + ' '.join('%d:%+d' % (x, d) for x, d in delta))

# ---- 用 v2 LUT + δ 重建，看是否 ≈ v3 ----
v2 = np.array(json.load(open(ROOT + r'\portrait_lut_v2.json'))['lut'], dtype=np.float64)
xs = np.array([p[0] for p in v2p], dtype=np.float64)
old_y = np.interp(xs, np.arange(257) / 256.0 * 255.0, v2 / OUT_MAX * 255.0)
d20 = np.array([d for _, d in delta], dtype=np.float64)
new_y = np.clip(np.round(old_y + d20), 0, 255).astype(int)

hdr = bytearray(bytes.fromhex('493000FF00FF0100'))
hdr += bytes([len(xs)])
for x, y in zip(xs.astype(int), new_y):
    hdr += bytes([int(x), int(y)])
hdr += b'\x00' * (64 - len(hdr))

rebuilt = build_ncp('PORTRAIT', 0x0001, [0x82, 0x01, 0x01, 0x80, 0x80, 0xFF, 0xFF, 0xFF],
                    [int(v) for v in v2], bytes(hdr), 0)
v3raw = open(ROOT + r'\curve_out\PORTRAIT_curve_v3.NCP', 'rb').read()
same = rebuilt == v3raw
diff = [i for i in range(min(len(rebuilt), len(v3raw))) if rebuilt[i] != v3raw[i]]
print('\n用 v2 LUT + δ 重建 vs v3：逐字节 %s' % ('一致' if same else '不一致'))
if diff:
    print('  差异位置:', diff[:20])
    print('  控制点重建:', [(int(x), int(y)) for x, y in zip(xs, new_y)])

# 保存 δ 供批量使用
xd = [int(x) for x in xs]
yd = [int(d) for d in d20]
json.dump({'x': xd, 'delta': yd}, open(ROOT + r'\curve_out\delta_portrait.json', 'w'))
print('δ 已存 curve_out/delta_portrait.json')
