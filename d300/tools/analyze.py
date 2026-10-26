#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对比「我的 NCP」与「尼康原厂新版优化校准」的渲染差异。

输入：同一张 NEF 用两种方式导出的 JPG，成对出现。
输出：逐项量化指标 + 逼近程度评级 + 拼版图。

指标说明
  L均值/标准差   静物影调的位置与反差
  饱和度         彩色饱和程度（HSV 平均 S）
  C*ab           明度无关的色度（Lab），单色照片应接近 0
  a*/b*          色偏方向：a 正=偏红、b 正=偏黄
  黑场截断/白场截断  各有多少像素压在两端
"""
import glob
import os
import sys

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None


def load(path, maxw=1000):
    im = Image.open(path).convert('RGB')
    if im.width > maxw:
        im = im.resize((maxw, round(im.height * maxw / im.width)), Image.LANCZOS)
    return np.asarray(im).astype(np.float32) / 255.0


def luma(a):
    return a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722


def to_lab(a):
    """sRGB(0..1) -> CIE L*a*b*，D65。只需要相对比较，用简化矩阵即可。"""
    lin = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124, 0.3576, 0.1805],
                  [0.2126, 0.7152, 0.0722],
                  [0.0193, 0.1192, 0.9505]], dtype=np.float32)
    xyz = lin @ m.T
    wp = np.array([0.95047, 1.0, 1.08883], dtype=np.float32)
    t = xyz / wp
    f = np.where(t > 0.008856, np.cbrt(t), 7.787 * t + 16 / 116)
    L = 116 * f[..., 1] - 16
    A = 500 * (f[..., 0] - f[..., 1])
    B = 200 * (f[..., 1] - f[..., 2])
    return L, A, B


def stats(path):
    a = load(path)
    L = luma(a)
    Ls = L * 100.0
    la, aa, bb = to_lab(a)
    mx, mn = a.max(axis=2), a.min(axis=2)
    sat = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0)
    return {
        'path': path, 'L': Ls, 'a': a, 'path_': path,
        'Lmean': float(la.mean()), 'Lstd': float(la.std()),
        'sat': float(sat.mean()), 'C': float(np.hypot(aa, bb).mean()),
        'a_mean': float(aa.mean()), 'b_mean': float(bb.mean()),
        'clip_b': float((Ls < 3).mean() * 100), 'clip_w': float((Ls > 97).mean() * 100),
        'Lmed': float(np.median(Ls)),
    }


def compare(s1, s2):
    """s1=我的NCP，s2=原厂参考"""
    L1, L2 = s1['L'], s2['L']
    if L1.shape != L2.shape:
        n = min(L1.shape[0], L2.shape[0]), min(L1.shape[1], L2.shape[1])
        L1, L2 = L1[:n[0], :n[1]], L2[:n[0], :n[1]]
        a1 = s1['a'][:n[0], :n[1]] * 255
        a2 = s2['a'][:n[0], :n[1]] * 255
    else:
        a1, a2 = s1['a'] * 255, s2['a'] * 255
    d = L1 - L2
    rgb_mae = float(np.abs(a1 - a2).mean())
    corr = float(np.corrcoef(L1.ravel()[::7], L2.ravel()[::7])[0, 1])
    return {
        'dL': float(d.mean()), 'dL_rms': float(np.sqrt((d ** 2).mean())),
        'dL_p95': float(np.percentile(np.abs(d), 95)),
        'rgb_mae': rgb_mae, 'corr': corr,
        'dLstd': s1['Lstd'] - s2['Lstd'],
        'dsat': s1['sat'] - s2['sat'],
        'dC': s1['C'] - s2['C'],
        'da': s1['a_mean'] - s2['a_mean'],
        'db': s1['b_mean'] - s2['b_mean'],
    }


def grade(c):
    """逼近程度分级：看影调（L）为主，色度单列"""
    e = abs(c['dL'])
    r = c['dL_rms']
    if e <= 2.0 and r <= 4.0:
        return 'A 很接近'
    if e <= 4.0 and r <= 7.0:
        return 'B 接近'
    if e <= 7.0 and r <= 11.0:
        return 'C 看得出差别'
    return 'D 差得远'


def main():
    files = sorted(glob.glob(os.path.join('原始', '*.jpg')))
    if not files:
        print('没找到 原始/*.jpg')
        return 1
    S = [stats(f) for f in files]
    print('%-9s %7s %6s %6s %6s %7s %7s %6s %6s'
          % ('文件', 'L均值', 'L标准差', '饱和度', 'C*ab', 'a*', 'b*', '黑截断', '白截断'))
    for i, s in enumerate(S):
        print('img%02d    %7.1f %6.1f %6.3f %6.1f %7.1f %7.1f %5.1f%% %5.1f%%'
              % (i + 1, s['Lmean'], s['Lstd'], s['sat'], s['C'],
                 s['a_mean'], s['b_mean'], s['clip_b'], s['clip_w']))
    return S


if __name__ == '__main__':
    main()
