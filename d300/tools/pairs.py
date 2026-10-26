#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""成对比较：我的 NCP 版 vs 原厂新版参考。

关键诊断：把差异按参考图的亮度分档看。
  各档差值都差不多 → 是全局引擎差异（与照相机兼容 / 最新系统 两个渲染模式）
  差值随亮度单调变化 → 是我的曲线没拟合对
"""
import os

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
W = 900

PAIRS = [
    ('sd',       '标准(新系统版)', 1, 2),
    ('sepia',    '棕褐色',        3, 4),
    ('binary',   '双色',          5, 6),
    ('charcoal', '木炭',          7, 8),
    ('dream',    '梦幻',          9, 10),
    ('fl',       '平面',         11, 12),
    ('pink',     '粉色',         13, 14),
    ('pop',      '流行',         15, 16),
]


def load(i):
    p = os.path.join('原始', 'img%02d.jpg' % i)
    im = Image.open(p).convert('RGB')
    im = im.resize((W, round(im.height * W / im.width)), Image.LANCZOS)
    return np.asarray(im).astype(np.float32) / 255.0


def lab(a):
    lin = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124, .3576, .1805], [.2126, .7152, .0722],
                  [.0193, .1192, .9505]], np.float32)
    t = (lin @ m.T) / np.array([.95047, 1.0, 1.08883], np.float32)
    f = np.where(t > 0.008856, np.cbrt(t), 7.787 * t + 16 / 116)
    return 116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])


def main():
    print('%-14s %7s %7s %7s %8s %8s %6s %6s'
          % ('滤镜', 'ΔL均值', 'ΔL残差', 'RMS', 'Δ对比度', 'ΔC*ab', 'Δa*', 'Δb*'))
    print('-' * 78)
    rows = []
    for key, cn, ia, ib in PAIRS:
        A = load(ia)          # 我的 NCP
        B = load(ib)          # 原厂参考
        La, aa, ba = lab(A)
        Lb, ab, bb = lab(B)
        d = La - Lb
        Ca = np.hypot(aa, ba).mean()
        Cb = np.hypot(ab, bb).mean()
        rows.append(dict(key=key, cn=cn, dL=d.mean(), rms=np.sqrt((d ** 2).mean()),
                         dstd=La.std() - Lb.std(), dC=Ca - Cb,
                         da=aa.mean() - ab.mean(), db=ba.mean() - bb.mean(),
                         Lb=Lb, d=d))
    off = np.median([r['dL'] for r in rows])
    for r in rows:
        print('%-14s %+7.1f %+7.1f %7.1f %+8.1f %+8.1f %+6.1f %+6.1f'
              % (r['cn'], r['dL'], r['dL'] - off, r['rms'], r['dstd'],
                 r['dC'], r['da'], r['db']))
    print('-' * 78)
    print('全部 8 对的 ΔL 中位数 = %+.1f  ← 当作「引擎整体偏移」的估计' % off)
    print()

    print('按参考图亮度分档的差值（判断是平移还是曲线没拟合对）')
    print('%-12s %s' % ('滤镜', ' '.join('%6s' % ('%d-%d' % (k * 10, k * 10 + 10))
                                        for k in range(10))))
    for r in rows:
        Lb, d = r['Lb'], r['d']
        cells = []
        for k in range(10):
            m = (Lb >= k * 10) & (Lb < (k + 1) * 10)
            cells.append('%+6.1f' % d[m].mean() if m.sum() > 500 else '     -')
        print('%-12s %s' % (r['cn'], ' '.join(cells)))
    return rows


if __name__ == '__main__':
    main()
