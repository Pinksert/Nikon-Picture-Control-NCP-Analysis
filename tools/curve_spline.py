# -*- coding: utf-8 -*-
"""破解头部控制点 -> LUT 的插值算法：用 M.NCP 的 3 个控制点重建 LUT，跟它真实的 LUT 比"""
import sys, json, struct
import numpy as np
sys.stdout.reconfigure(encoding='utf-8')

ref = json.load(open(r'C:\Users\admin\WorkBuddy\D300固件\M_ref.json'))
PTS = [(0, 0), (73, 140), (255, 255)]        # 从字节 9 起，每点 2 字节 (x, y)
LUT = np.array(ref['lut'], dtype=np.float64)  # 实测
OUT_MAX = 32767.0

xs = np.array([p[0] for p in PTS], dtype=np.float64)
ys = np.array([p[1] for p in PTS], dtype=np.float64)
qx = np.arange(257) / 256.0 * 255.0          # LUT 的输入采样点


def linear(xs, ys, q):
    return np.interp(q, xs, ys)


def catmull_rom(xs, ys, q):
    """Catmull-Rom，端点用自身重复"""
    out = np.empty_like(q)
    xe = np.concatenate(([xs[0]], xs, [xs[-1]]))
    ye = np.concatenate(([ys[0]], ys, [ys[-1]]))
    for i, x in enumerate(q):
        j = np.searchsorted(xs, x) - 1
        j = max(0, min(j, len(xs) - 2))
        p0, p1, p2, p3 = ye[j], ye[j + 1], ye[j + 2], ye[j + 3]
        t = (x - xs[j]) / (xs[j + 1] - xs[j])
        t2, t3 = t * t, t * t * t
        out[i] = 0.5 * ((2 * p1) + (-p0 + p2) * t +
                        (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
                        (-p0 + 3 * p1 - 3 * p2 + p3) * t3)
    return out


def nat_cubic(xs, ys, q):
    """自然三次样条（二阶导端点为 0）"""
    n = len(xs)
    h = np.diff(xs)
    A = np.zeros((n, n)); b = np.zeros(n)
    A[0, 0] = 1; A[-1, -1] = 1
    for i in range(1, n - 1):
        A[i, i - 1] = h[i - 1]; A[i, i] = 2 * (h[i - 1] + h[i]); A[i, i + 1] = h[i]
        b[i] = 3 * ((ys[i + 1] - ys[i]) / h[i] - (ys[i] - ys[i - 1]) / h[i - 1])
    c = np.linalg.solve(A, b)
    out = np.empty_like(q)
    for i, x in enumerate(q):
        j = max(0, min(np.searchsorted(xs, x) - 1, n - 2))
        t = (x - xs[j]) / h[j]
        a = ys[j]; bb = (ys[j + 1] - ys[j]) / h[j] - h[j] * (2 * c[j] + c[j + 1]) / 3
        cc = c[j]; dd = (c[j + 1] - c[j]) / (3 * h[j])
        out[i] = a + bb * t + cc * t * t + dd * t * t * t
    return out


def pchip(xs, ys, q):
    """单调三次（Fritsch-Carlson 简化版）"""
    try:
        from scipy.interpolate import PchipInterpolator
        return PchipInterpolator(xs, ys)(q)
    except Exception:
        return None


print('=' * 70)
print('用 M.NCP 的控制点 %s 重建 LUT，跟它真实的 257 点比' % (PTS,))
print('=' * 70)
for name, fn in [('分段线性', linear), ('Catmull-Rom', catmull_rom),
                 ('自然三次样条', nat_cubic), ('单调三次 PCHIP', pchip)]:
    y = fn(xs, ys, qx) if fn is not pchip else pchip(xs, ys, qx)
    if y is None:
        print('  %-16s (scipy 不可用，跳过)' % name)
        continue
    pred = np.clip(y, 0, 255) / 255.0 * OUT_MAX
    err = np.abs(pred - LUT)
    print('  %-16s 平均差 %6.1f  最大差 %6.1f   (%d 点误差 <1%%)'
          % (name, err.mean(), err.max(), int((err < 328).sum())))
print()
print('参考：LUT 满量程 32767，1%% = 328')
