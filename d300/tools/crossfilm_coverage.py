#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""crossfilm_coverage.py —— 换底片掉的那 1.2 分，有多少只是「表没铺到」？

这个假设必须先排除，因为它最容易被忽略、也最容易修。

3D LUT 是在一张图上拟合的：网格里只有**被那张图采到过的格子**才有值。
`lut_fit.splat_avg()` 的规则是「该格附近样本少于 0.02 就当 0」——也就是**保持恒等**。
换一张图，只要它的颜色落在这些空格子里，查表就等于什么都没做。
这不是「映射不确定」，纯粹是**覆盖不足**，是能修的：把空格子按邻居扩散填上就行。

本脚本量三件事：
  1. 目标底片有多少像素落在「源底片没采到」的格子里（coverage 缺口）
  2. 直接套 vs 空洞填充后的 ΔE00
  3. 缺口大小与掉分多少的相关性 —— 如果强相关，说明这一块就是主因

    python tools/crossfilm_coverage.py                 # 全 26 支
    python tools/crossfilm_coverage.py --fill-rounds 80
"""
import argparse
import csv
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, HERE)
from lut_fit import (fit_lut, interp, mask_of, identity_grid, _raw_metrics,   # noqa: E402
                     grid_support, fill_grid_gaps)
from real_gap import load, find                                              # noqa: E402

SAMP = os.path.join(ROOT, 'samples')
UP = os.path.normpath(os.path.join(ROOT, '..'))
CACHE = os.path.join(SAMP, '.crossfilm_luts.npz')

FILMS = {
    '4484': dict(odir=os.path.join(SAMP, 'real_v3'), tdir=os.path.join(SAMP, 'real_target'),
                 osuf='', tsuf=''),
    '8981': dict(odir=os.path.join(UP, '_validate_nef', '8981b'),
                 tdir=os.path.join(UP, '_validate_nef', '8981b'),
                 osuf='__O', tsuf='__T'),
}


support = grid_support


def uncovered(dst, sup, N, k=3):
    """目标底片有多少比例的像素落在「源底片样本 < k」的格子里"""
    idx = np.clip((dst / 255.0 * (N - 1)).round().astype(int), 0, N - 1)
    hit = sup[idx[:, 0], idx[:, 1], idx[:, 2]] < k
    return float(hit.mean())


def fill_gaps(G, sup, N, rounds=60, k=3):
    """（实现已挪到 lut_fit.fill_grid_gaps，标定流程也要用）"""
    return fill_grid_gaps(G, sup, rounds=rounds, k=k)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--size', type=int, default=420)
    ap.add_argument('--grid', type=int, default=17)
    ap.add_argument('--iters', type=int, default=120)
    ap.add_argument('--trust', type=float, default=40.0)
    ap.add_argument('--min-sup', type=int, default=3)
    ap.add_argument('--fill-rounds', type=int, default=60)
    ap.add_argument('--only', default=None)
    ap.add_argument('--csv', default=os.path.join(SAMP, 'crossfilm_coverage.csv'))
    a = ap.parse_args()

    order = [(int(r['slot']), r['name'])
             for r in csv.DictReader(open(os.path.join(SAMP, 'metrics_real.csv'),
                                          encoding='utf-8-sig'))]
    want = set(x.strip().upper() for x in a.only.split(',')) if a.only else None
    names = [n for _, n in order if not want or n in want]

    D = {}
    for f, c in FILMS.items():
        for slot, n in order:
            po = find(c['odir'], slot, '%s%s' % (n, c['osuf']))
            pt = find(c['tdir'], slot, '%s%s' % (n, c['tsuf']))
            if po and pt:
                O, T = load(po, a.size), load(pt, a.size)
                if O.shape == T.shape:
                    D[(f, n)] = (O, T)
    M = {f: {n: mask_of(*D[(f, n)]) for n in names if (f, n) in D} for f in FILMS}

    keys = ['%s|%s' % (f, n) for f in FILMS for n in names]
    G = {}
    if os.path.exists(CACHE):
        z = np.load(CACHE, allow_pickle=True)
        G = {k: z[k] for k in keys if k in z.files}
        if G:
            print('LUT 网格：缓存里拿到 %d/%d' % (len(G), len(keys)))
    for f in FILMS:
        for i, n in enumerate(names):
            if (f, n) not in D or '%s|%s' % (f, n) in G:
                continue
            O, T = D[(f, n)]
            G['%s|%s' % (f, n)] = fit_lut(O[M[f][n]], T[M[f][n]], N=a.grid,
                                          iters=a.iters, trust=a.trust)
            print('  拟合 %s/%s (%d/%d)' % (f, n, i + 1, len(names)), flush=True)
    np.savez_compressed(CACHE, **G)

    rows = []
    for src, dst in (('4484', '8981'), ('8981', '4484')):
        for n in names:
            if (src, n) not in D or (dst, n) not in D:
                continue
            g = G['%s|%s' % (src, n)]
            sup = support(D[(src, n)][0][M[src][n]], a.grid)
            gf = fill_gaps(g, sup, a.grid, a.fill_rounds, a.min_sup)
            X = D[(dst, n)][0][M[dst][n]]
            T = D[(dst, n)][1][M[dst][n]]
            d0 = _raw_metrics(np.clip(interp(g, X), 0, 255), T)['de']
            d1 = _raw_metrics(np.clip(interp(gf, X), 0, 255), T)['de']
            uc = uncovered(D[(dst, n)][0][M[dst][n]], sup, a.grid, a.min_sup)
            rows.append((src, dst, n, uc, d0, d1))
            print('%-4s %-14s 未覆盖 %4.0f%%  直接套 %5.2f  补空洞 %5.2f  %+.2f'
                  % (dst, n, uc * 100, d0, d1, d1 - d0), flush=True)

    print()
    b = np.mean([r[4] for r in rows])
    c = np.mean([r[5] for r in rows])
    print('26 支 × 2 方向：直接套 %.2f → 补空洞 %.2f（%+.2f）' % (b, c, c - b))
    uc = np.array([r[3] for r in rows])
    imp = np.array([r[4] - r[5] for r in rows])
    if uc.std() > 1e-6:
        print('未覆盖率与「补空洞收益」的相关系数 r = %.2f'
              % float(np.corrcoef(uc, imp)[0, 1]))
    # 仅看单方向（4484->8981），口径和 docs/25 的 3.33 一致
    one = [r for r in rows if r[0] == '4484' and r[1] == '8981']
    if one:
        print('仅 4484→8981：%.2f → %.2f' % (np.mean([r[4] for r in one]),
                                             np.mean([r[5] for r in one])))

    if a.csv:
        with open(a.csv, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['src', 'dst', 'name', 'uncovered', 'dE00_raw', 'dE00_fill'])
            for r in rows:
                w.writerow([r[0], r[1], r[2], '%.4f' % r[3], '%.4f' % r[4], '%.4f' % r[5]])
        print('csv → %s' % a.csv)


if __name__ == '__main__':
    main()
