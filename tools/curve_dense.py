# -*- coding: utf-8 -*-
"""密集采样测试：从目标 LUT 取 N 个控制点，用各种插值还原，看误差能压到多小。
   如果 N=20 时各种算法误差都很小，就不用破解尼康的确切算法了。"""
import sys, json
import numpy as np
sys.stdout.reconfigure(encoding='utf-8')

ref = json.load(open(r'C:\Users\admin\WorkBuddy\D300固件\M_ref.json'))
LUT = np.array(ref['lut'], dtype=np.float64)
OUT_MAX = 32767.0
qx = np.arange(257) / 256.0 * 255.0


def catmull_rom(xs, ys, q):
    out = np.empty_like(q)
    xe = np.concatenate(([xs[0]], xs, [xs[-1]]))
    ye = np.concatenate(([ys[0]], ys, [ys[-1]]))
    for i, x in enumerate(q):
        j = max(0, min(np.searchsorted(xs, x) - 1, len(xs) - 2))
        p0, p1, p2, p3 = ye[j], ye[j + 1], ye[j + 2], ye[j + 3]
        t = (x - xs[j]) / (xs[j + 1] - xs[j])
        t2, t3 = t * t, t * t * t
        out[i] = 0.5 * ((2 * p1) + (-p0 + p2) * t +
                        (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
                        (-p0 + 3 * p1 - 3 * p2 + p3) * t3)
    return out


def pchip(xs, ys, q):
    """Fritsch-Carlson 单调三次"""
    n = len(xs); h = np.diff(xs); d = np.diff(ys) / h
    m = np.zeros(n)
    m[0] = d[0]; m[-1] = d[-1]
    for i in range(1, n - 1):
        if d[i - 1] * d[i] <= 0:
            m[i] = 0
        else:
            w1 = 2 * h[i] + h[i - 1]; w2 = h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])
    out = np.empty_like(q)
    for i, x in enumerate(q):
        j = max(0, min(np.searchsorted(xs, x) - 1, n - 2))
        t = (x - xs[j]) / h[j]; t2, t3 = t * t, t * t * t
        h00 = 2 * t3 - 3 * t2 + 1; h10 = t3 - 2 * t2 + t
        h01 = -2 * t3 + 3 * t2; h11 = t3 - t2
        out[i] = h00 * ys[j] + h10 * h[j] * m[j] + h01 * ys[j + 1] + h11 * h[j] * m[j + 1]
    return out


def linear(xs, ys, q):
    return np.interp(q, xs, ys)


print('=' * 74)
print('从 M.NCP 的真实 LUT 采 N 个控制点，再用各算法还原，看误差（满量程 32767）')
print('=' * 74)
print('  %-4s %-14s %-14s %-14s' % ('点数', '分段线性', 'Catmull-Rom', 'PCHIP'))
for N in (3, 5, 9, 13, 17, 20):
    xi = np.linspace(0, 255, N)
    yi = np.interp(xi, qx, LUT / OUT_MAX * 255.0)
    row = []
    for fn in (linear, catmull_rom, pchip):
        pred = np.clip(fn(xi, yi, qx), 0, 255) / 255.0 * OUT_MAX
        row.append(np.abs(pred - LUT).mean())
    print('  %-4d %-14.1f %-14.1f %-14.1f' % (N, row[0], row[1], row[2]))
print()
print('结论：点数够多时，算法差异的影响就被压到很小')
