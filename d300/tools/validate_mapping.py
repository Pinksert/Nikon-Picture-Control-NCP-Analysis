#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测一件根本的事：我们的 RGB → 官方 RGB，到底是不是一个确定的函数？

如果它是，那么在两张底片上「我们输出同一个 RGB」的像素，官方也该输出同一个 RGB，
4484 上拟合的 LUT 就能直接用到 8981 上。事实是 LUT 跨图从 2.13 掉到 3.33，
说明它不是。这个脚本量出「它不是」的程度。

做法：把 RGB 立方体切成 N³ 个格子，只保留两张底片都采集到 ≥K 个像素的格子，
比较格子内「官方 RGB 的平均值」在两图之间差多少。同时拿一个参照：
同一张图内部 2×2 分块之间的格子均值差（这是空间噪声的下界）。

用法：
    python tools/validate_mapping.py --only DREAM,STANDARD
"""
import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from real_gap import NAMES, load, find                 # noqa: E402
from lut_fit import mask_of                            # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
SAMP = os.path.join(ROOT, 'samples')


def cells(A, B, N, K):
    """返回 {格子: (官方RGB均值, 像素数)}"""
    m = mask_of(A, B)
    idx = np.clip((A.reshape(-1, 3) / 255. * (N - 1)).round().astype(int), 0, N - 1)
    flat = idx[:, 0] * N * N + idx[:, 1] * N + idx[:, 2]
    Br = B.reshape(-1, 3)
    ok = m.reshape(-1)
    out = {}
    cnt = np.bincount(flat[ok], minlength=N ** 3)
    for c in np.nonzero(cnt >= K)[0]:
        sel = ok & (flat == c)
        out[int(c)] = (Br[sel].mean(0), int(sel.sum()))
    return out


def within(A, B, N, K, seed=0):
    """同图内部的噪声下界：随机对半拆分，两半各自算格子均值再比。

    用随机拆分而不是空间分块，是因为分块会把每格的样本数砍成 1/4，
    均值噪声被抬高 2 倍，那样比出来的「同图内」是虚高的、不能当对照。
    """
    m = mask_of(A, B)
    ys, xs = np.nonzero(m)
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(ys))
    halves = []
    for half in (perm[:len(ys) // 2], perm[len(ys) // 2:]):
        sub = np.zeros_like(m)
        sub[ys[half], xs[half]] = True
        halves.append(cells(A * sub[..., None], B * sub[..., None], N, K))
    ds = []
    for k in set(halves[0]) & set(halves[1]):
        ds.append(np.abs(halves[0][k][0] - halves[1][k][0]).mean())
    return float(np.mean(ds)) if ds else float('nan')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default=os.path.normpath(
        os.path.join(ROOT, '..', '_validate_nef', '8981b')))
    ap.add_argument('--size', type=int, default=420)
    ap.add_argument('--grid', type=int, default=17)
    ap.add_argument('--min-px', type=int, default=12, help='格子至少多少像素才算数')
    ap.add_argument('--only', default=None)
    ap.add_argument('--csv', default=os.path.join(SAMP, 'validate_mapping.csv'))
    a = ap.parse_args()

    want = set(x.strip().upper() for x in a.only.split(',')) if a.only else None
    print('同一格子里，官方 RGB 的平均值在两张底片之间差多少级（0–255）')
    print('格子 %d³，只算两图都采到 ≥%d 像素的格子；对照＝同图内 2×2 分块之间的差'
          % (a.grid, a.min_px))
    print()
    print('%-12s %6s %8s %8s %8s' % ('滤镜', '共有格', '跨底片', '同图内', '倍数'))
    print('-' * 48)
    rows = []
    for slot, name in enumerate(NAMES, 1):
        if want and name not in want:
            continue
        p4o, p4t = find(os.path.join(SAMP, 'real_v3'), slot, name), \
            find(os.path.join(SAMP, 'real_target'), slot, name)
        p8o, p8t = find(a.dir, slot, '%s__O' % name), find(a.dir, slot, '%s__T' % name)
        if not all([p4o, p4t, p8o, p8t]):
            continue
        A4, B4 = load(p4o, a.size), load(p4t, a.size)
        A8, B8 = load(p8o, a.size), load(p8t, a.size)
        c4, c8 = cells(A4, B4, a.grid, a.min_px), cells(A8, B8, a.grid, a.min_px)
        keys = sorted(set(c4) & set(c8))
        if len(keys) < 8:
            continue
        cross = float(np.mean([np.abs(c4[k][0] - c8[k][0]).mean() for k in keys]))
        w4 = within(A4, B4, a.grid, a.min_px)
        w8 = within(A8, B8, a.grid, a.min_px)
        wavg = np.nanmean([w4, w8])
        print('%-12s %6d %8.2f %8.2f %7.1fx' % (name, len(keys), cross, wavg,
                                                cross / wavg if wavg > 1e-6 else float('nan')))
        rows.append((name, len(keys), cross, wavg))
    print('-' * 48)
    if rows:
        print('均值：跨底片 %.2f 级，同图内 %.2f 级 —— 跨底片是同图内的 %.1f 倍'
              % (np.mean([r[2] for r in rows]), np.nanmean([r[3] for r in rows]),
                 np.mean([r[2] for r in rows]) / np.nanmean([r[3] for r in rows])))
        print()
        print('判读：跨底片 ≈ 同图内 ⇒ 映射是确定的 RGB→RGB，LUT 本该能迁移；')
        print('      跨底片 >> 同图内 ⇒ 官方渲染还吃 RGB 之外的东西（邻域/场景/直方图），')
        print('      逐像素查表在原理上就补不齐，只能每张底片各标定一次。')

    if rows and a.csv:
        import csv as _csv
        with open(a.csv, 'w', newline='', encoding='utf-8-sig') as f:
            w = _csv.writer(f)
            w.writerow(['name', 'cells', 'cross_film', 'within_film'])
            for name, n, cross, wavg in rows:
                w.writerow([name, n, '%.4f' % cross, '%.4f' % wavg])
        print()
        print('CSV → %s' % a.csv)


if __name__ == '__main__':
    main()
