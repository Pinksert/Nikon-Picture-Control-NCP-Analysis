# -*- coding: utf-8 -*-
"""搜索尼康样条的 tension 参数：用 M.NCP（3 点）和 S.NCP（4 点）验证
   CR_t(控制点) 是否能在某个统一 t 下精确重现它们的实测 LUT"""
import sys, json, struct, re
import numpy as np
sys.stdout.reconfigure(encoding='utf-8')


def cr_t(xs, ys, q, t):
    """tension 可调的 Catmull-Rom：t=1 标准，t=0 退化为分段线性"""
    out = np.empty_like(q)
    xe = np.concatenate(([xs[0]], xs, [xs[-1]]))
    ye = np.concatenate(([ys[0]], ys, [ys[-1]]))
    for i, x in enumerate(q):
        j = max(0, min(np.searchsorted(xs, x) - 1, len(xs) - 2))
        p0, p1, p2, p3 = ye[j], ye[j + 1], ye[j + 2], ye[j + 3]
        u = (x - xs[j]) / (xs[j + 1] - xs[j])
        u2, u3 = u * u, u * u * u
        out[i] = 0.5 * ((2 * p1) + t * (-p0 + p2) * u +
                        t * (2 * p0 - 5 * p1 + 4 * p2 - p3) * u2 +
                        t * (-p0 + 3 * p1 - 3 * p2 + p3) * u3)
    return out


def load(path):
    txt = open(path, encoding='utf-8').read()
    hexs = re.findall(r'^\s{5}[0-9A-F]{4}  ([0-9A-F ]+)$', txt, re.M)
    d = bytes.fromhex(''.join(hexs).replace(' ', ''))
    n = d[8]
    pts = [(d[9 + 2 * i], d[10 + 2 * i]) for i in range(n)]
    lut = list(struct.unpack('>257H', d[64:64 + 514]))
    return pts, np.array(lut, dtype=np.float64)


def pts_from_dump(path):
    txt = open(path, encoding='utf-8').read()
    hexs = re.findall(r'^\s{5}[0-9A-F]{4}  ([0-9A-F ]+)$', txt, re.M)
    d = bytes.fromhex(''.join(hexs).replace(' ', ''))
    n = d[8]
    return [(d[9 + 2 * i], d[10 + 2 * i]) for i in range(n)]


q = np.arange(257) / 256.0 * 255.0

print('=' * 72)
print('M.NCP（3 点） tensions 搜索')
print('=' * 72)
pm = pts_from_dump(r'C:\Users\admin\WorkBuddy\D300固件\M_dump.txt')
xm = np.array([p[0] for p in pm], dtype=np.float64)
ym = np.array([p[1] for p in pm], dtype=np.float64)
print('控制点:', pm)
# M 的实测 LUT 从 dump 里取（偏移 64 起 257×uint16）
dm = bytes.fromhex(re.findall(r'^\s{5}[0-9A-F]{4}  ([0-9A-F ]+)$',
                   open(r'C:\Users\admin\WorkBuddy\D300固件\M_dump.txt', encoding='utf-8').read(), re.M
                   ).__str__().replace('[','').replace(']','').replace("'",'').replace(',','').replace(' ',''), 'strict') if False else None
hexs = re.findall(r'^\s{5}[0-9A-F]{4}  ([0-9A-F ]+)$',
                  open(r'C:\Users\admin\WorkBuddy\D300固件\M_dump.txt', encoding='utf-8').read(), re.M)
dm = bytes.fromhex(''.join(hexs).replace(' ', ''))
lutM = np.array(struct.unpack('>257H', dm[64:64 + 514]), dtype=np.float64)
best = None
for t in np.arange(0.0, 2.01, 0.02):
    pred = np.clip(cr_t(xm, ym, q, t), 0, 255) / 255.0 * 32767.0
    e = np.abs(pred - lutM).mean()
    if best is None or e < best[1]:
        best = (t, e)
print('最佳 t = %.2f   平均差 %.1f / 32767' % best)
t = best[0]
pred = np.clip(cr_t(xm, ym, q, t), 0, 255) / 255.0 * 32767.0
e = np.abs(pred - lutM)
print('  最大差 %.1f  （量程 32767，即 %.2f%%）' % (e.max(), e.max() / 32767 * 100))

print()
print('=' * 72)
print('S.NCP（4 点）用同一 t 验证')
print('=' * 72)
ps = pts_from_dump(r'C:\Users\admin\WorkBuddy\D300固件\S_dump.txt')
xs = np.array([p[0] for p in ps], dtype=np.float64)
ys = np.array([p[1] for p in ps], dtype=np.float64)
print('控制点:', ps)
_, lutS = load(r'C:\Users\admin\WorkBuddy\D300固件\S_dump.txt')
pred = np.clip(cr_t(xs, ys, q, t), 0, 255) / 255.0 * 32767.0
e = np.abs(pred - lutS)
print('t=%.2f  平均差 %.1f  最大差 %.1f' % (t, e.mean(), e.max()))
# 也扫一下 S 单独的最佳 t，看是否与 M 一致
bestS = None
for t2 in np.arange(0.0, 2.01, 0.02):
    pred2 = np.clip(cr_t(xs, ys, q, t2), 0, 255) / 255.0 * 32767.0
    e2 = np.abs(pred2 - lutS).mean()
    if bestS is None or e2 < bestS[1]:
        bestS = (t2, e2)
print('S 单独最佳 t = %.2f  平均差 %.1f' % bestS)
