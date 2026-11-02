#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""oracle_global.py —— 机内这套工具的天花板到底在哪。

问题
----
v3 的 26 支真渲染平均差 6.45 级 / ΔE00 5.36，残差几乎全在彩度。文档里一直说
「这是引擎代际差异」，但那是解释，不是上界。真正该问的是：

  **把 D300 能给的三个旋钮（一条任意亮度曲线 + 一个全局饱和度倍率 +
    一个全局色相角）都拧到最优，最好能到多少？**

如果这个「最优」离 6.45 只差零点几级，那机内就没有继续优化的空间了，
剩下的 4 级差距只能靠后期（见 `lut_fit.py`）。

怎么做
------
不做整数档穷举（那是 v3 已经做过的，结论 0 支值得改），而是给足自由度：
  · 曲线：任意单调 LUT —— 直接按 L* 分位数匹配目标，等价于「曲线随便画」
  · 饱和度：连续倍率 k（不限 ±3 档）
  · 色相：连续转角 θ（不限 ±3 档）
三者交替优化（曲线 → 网格搜 k/θ → 再曲线），三轮收敛。得到的是**上界**，
真实机身只会更差（整数档、曲线还叠了 H 变换）。

    python tools/oracle_global.py                  # 26 支
    python tools/oracle_global.py --only TOY,DENIM
"""
import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from diag_residual import to_lab, de2000                      # noqa: E402
from real_gap import NAMES, MONO, load, find                  # noqa: E402
from lut_fit import mask_of                                   # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
SAMP = os.path.join(ROOT, 'samples')

_M = np.array([[0.4124564, 0.3575761, 0.1804375],
               [0.2126729, 0.7151522, 0.0721750],
               [0.0193339, 0.1191920, 0.9503041]])
_W = np.array([0.95047, 1.0, 1.08883])


def lab_to_srgb(lab):
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    fy = (L + 16.0) / 116.0
    fx = fy + a / 500.0
    fz = fy - b / 200.0
    d = 6.0 / 29.0
    f = np.stack([fx, fy, fz], -1)
    t = np.where(f > d, f ** 3, 3 * d * d * (f - 4.0 / 29.0))
    rgb = (t * _W) @ np.linalg.inv(_M).T
    c = np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * np.abs(rgb) ** (1 / 2.4) - 0.055)
    return np.clip(c * 255.0, 0, 255)


def quantile_curve(src_l, tgt_l, n=256):
    """按分位数把 src 的 L* 分布搬到 tgt —— 等价于「任意单调曲线」

    表以 256 格索引，第 i 格对应 L* = i × 100/255
    """
    s = np.sort(src_l)
    t = np.sort(tgt_l)
    grid = np.linspace(0.0, 100.0, n)
    pos = np.searchsorted(s, grid, side='left') / max(1, len(s) - 1)
    ys = np.quantile(t, np.clip(pos, 0.0, 1.0))
    return ys


def apply_op(lab, lut, k, deg):
    L = lab[..., 0]
    L2 = lut[np.clip(np.round(L * (255.0 / 100.0)), 0, 255).astype(np.int32)]
    C = np.hypot(lab[..., 1], lab[..., 2]) * k
    h = np.arctan2(lab[..., 2], lab[..., 1]) + np.deg2rad(deg)
    return np.stack([L2, C * np.cos(h), C * np.sin(h)], -1)


def fit_one(A, B, m, sub=40000, rng=None, kmin=0.70, kmax=1.45, dmax=6.0):
    """kmin/kmax/dmax 默认是「理想化上界」（不限档）；传实测可达区间就得到可达上界。"""
    rng = rng or np.random.default_rng(7)
    labA, labB = to_lab(A), to_lab(B)
    idx = np.flatnonzero(m.reshape(-1))
    if len(idx) > sub:
        idx = rng.choice(idx, sub, replace=False)
    la_s, lb_s = labA.reshape(-1, 3)[idx], labB.reshape(-1, 3)[idx]

    lut = np.linspace(0.0, 100.0, 256)                    # 恒等
    k, deg = 1.0, 0.0
    for _ in range(3):
        # 1) 曲线：在当前 (k,deg) 下把 L 分位匹配到目标
        cur = apply_op(la_s, lut, k, deg)
        lut = quantile_curve(cur[..., 0], lb_s[..., 0])

        # 2) 颜色：粗网格 + 局部细化
        def score(kk, dd):
            p = lab_to_srgb(apply_op(la_s, lut, kk, dd))
            return de2000(to_lab(p), lb_s).mean()

        coarse = [(score(kk, dd), kk, dd)
                  for kk in np.linspace(kmin, kmax, 16)
                  for dd in np.linspace(-dmax, dmax, 13)]
        _, k0, d0 = min(coarse)
        fine = [(score(kk, dd), kk, dd)
                for kk in np.clip(np.arange(k0 - 0.04, k0 + 0.041, 0.02), kmin, kmax)
                for dd in np.clip(np.arange(d0 - 0.8, d0 + 0.81, 0.2), -dmax, dmax)]
        _, k, deg = min(fine)

    # 用全像素复核
    p = lab_to_srgb(apply_op(to_lab(A), lut, k, deg))
    d = de2000(to_lab(p), to_lab(B))
    return dict(k=k, deg=deg, de=d.mean(), jnd=float((d > 2.3).mean() * 100.0),
                mad=float(np.abs(p[m] - B[m]).mean()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--size', type=int, default=420)
    ap.add_argument('--only', default=None)
    ap.add_argument('--kmin', type=float, default=0.70, help='饱和度倍率下限（实测 0.648）')
    ap.add_argument('--kmax', type=float, default=1.45, help='饱和度倍率上限（实测 1.275）')
    ap.add_argument('--dmax', type=float, default=6.0, help='色相转角上限，度（实测 ±11.5）')
    ap.add_argument('--csv', default='oracle_global.csv')
    a = ap.parse_args()
    want = set(x.strip().upper() for x in a.only.split(',')) if a.only else None

    rows = []
    print('%3s %-20s %9s %9s %7s %7s' % ('#', '滤镜', '级(现在)', '级(上界)', 'dE现在', 'dE上界'))
    for slot, name in enumerate(NAMES, 1):
        if want and name not in want:
            continue
        pa = find(os.path.join(SAMP, 'real_v3'), slot, name)
        pb = find(os.path.join(SAMP, 'real_target'), slot, name)
        if not pa or not pb:
            continue
        A, B = load(pa, a.size), load(pb, a.size)
        if A.shape != B.shape:
            continue
        m = mask_of(A, B)
        now_de = de2000(to_lab(A[m]), to_lab(B[m])).mean()
        now_mad = float(np.abs(A[m] - B[m]).mean())
        r = fit_one(A, B, m, kmin=a.kmin, kmax=a.kmax, dmax=a.dmax)
        rows.append(dict(slot=slot, name=name, mono=slot in MONO,
                         mad_now=now_mad, de_now=now_de,
                         mad_or=r['mad'], de_or=r['de'], k=r['k'], deg=r['deg']))
        print('%3d %-20s %9.3f %9.3f %7.2f %7.2f   k=%.2f θ=%+.1f°'
              % (slot, name, now_mad, r['mad'], now_de, r['de'], r['k'], r['deg']),
              flush=True)

    if rows:
        print('-' * 74)
        for tag, sel in (('全部', rows),
                         ('彩色', [r for r in rows if not r['mono']]),
                         ('单色', [r for r in rows if r['mono']])):
            if not sel:
                continue
            print('%-4s %2d 支   现在 %7.3f 级 / dE %5.2f  ->  上界 %7.3f 级 / dE %5.2f'
                  % (tag, len(sel),
                     np.mean([r['mad_now'] for r in sel]), np.mean([r['de_now'] for r in sel]),
                     np.mean([r['mad_or'] for r in sel]), np.mean([r['de_or'] for r in sel])))
        out = os.path.join(SAMP, a.csv)
        with open(out, 'w', encoding='utf-8-sig') as f:
            f.write('slot,name,type,mad_now,mad_oracle,dE00_now,dE00_oracle,k,deg\n')
            for r in rows:
                f.write('%d,%s,%s,%.4f,%.4f,%.4f,%.4f,%.4f,%.2f\n'
                        % (r['slot'], r['name'], 'mono' if r['mono'] else 'color',
                           r['mad_now'], r['mad_or'], r['de_now'], r['de_or'],
                           r['k'], r['deg']))
        print('csv -> samples/%s' % a.csv)


if __name__ == '__main__':
    main()
