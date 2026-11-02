#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""crossfilm_domain.py —— 换输入域到底有没有把「不确定性」降下来？

`docs/25` 第五节在「我们的成片」这个输入域上量到：
同一个输入 RGB，官方在两张底片上的输出差 4.07 级，同图内部只差 0.65 级（6.3 倍）。
这个差值就是「逐像素查表在原理上补不齐的那一块」。

本脚本把同一个量法套到两个输入域上，看换域有没有把这块变小：

  · 域 O = 我们的成片（raw → 我们的 NCP → 成片），信息已被 NCP 压过
  · 域 A = 中性锚点（raw → 固定中性渲染 → 成片），不经过任何 Picture Control

量法与 `validate_mapping.py` 一致：把输入 RGB 立方体切成 N³ 格，只算两张底片都采到
≥K 像素的格子，比格子里官方 RGB 的均值；对照是同图内随机对半拆的格子均值差。
两个域用**同一套像素掩膜**（由 O vs T 决定），否则不可比。

    python tools/crossfilm_domain.py --only DREAM,STANDARD
    python tools/crossfilm_domain.py
"""
import argparse
import csv
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, HERE)
from real_gap import load, find                  # noqa: E402
from lut_fit import mask_of                      # noqa: E402

SAMP = os.path.join(ROOT, 'samples')
UP = os.path.normpath(os.path.join(ROOT, '..'))
ANCHOR = {'4484': os.path.join(UP, '_validate_nef', '4484_anchor.jpg'),
          '8981': os.path.join(UP, '_validate_nef', '8981_anchor.jpg')}


def cell_stats(X, T, m, N, K):
    """按输入 X 分格，返回 {格: (官方均值, 样本数)}"""
    flat = cell_index(X, N)
    ok = m.reshape(-1)
    Br = T.reshape(-1, 3)
    cnt = np.bincount(flat[ok], minlength=N ** 3)
    out = {}
    for c in np.nonzero(cnt >= K)[0]:
        sel = ok & (flat == c)
        out[int(c)] = (Br[sel].mean(0), int(sel.sum()))
    return out


def cell_index(X, N):
    idx = np.clip((X.reshape(-1, 3) / 255. * (N - 1)).round().astype(int), 0, N - 1)
    return idx[:, 0] * N * N + idx[:, 1] * N + idx[:, 2]


def within(X, T, m, N, K, seed=0):
    """同图内噪声下界：随机对半拆分（不是空间分块 —— 分块会把每格样本砍成 1/4）"""
    ys, xs = np.nonzero(m)
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(ys))
    halves = []
    for half in (perm[:len(ys) // 2], perm[len(ys) // 2:]):
        sub = np.zeros_like(m)
        sub[ys[half], xs[half]] = True
        halves.append(cell_stats(X * sub[..., None], T * sub[..., None],
                                 m & sub, N, K))
    ds = [np.abs(halves[0][k][0] - halves[1][k][0]).mean()
          for k in set(halves[0]) & set(halves[1])]
    return float(np.mean(ds)) if ds else float('nan')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default=os.path.join(UP, '_validate_nef', '8981b'))
    ap.add_argument('--size', type=int, default=420)
    ap.add_argument('--grid', type=int, default=17)
    ap.add_argument('--min-px', type=int, default=12)
    ap.add_argument('--only', default=None)
    ap.add_argument('--csv', default=os.path.join(SAMP, 'crossfilm_domain.csv'))
    a = ap.parse_args()

    order = [(int(r['slot']), r['name'])
             for r in csv.DictReader(open(os.path.join(SAMP, 'metrics_real.csv'),
                                          encoding='utf-8-sig'))]
    want = set(x.strip().upper() for x in a.only.split(',')) if a.only else None

    AN = {f: load(p, a.size) for f, p in ANCHOR.items()}

    print('格子里官方 RGB 的均值：跨底片差多少 vs 同图内差多少（两个域用同一套掩膜）')
    print('格子 %d³，每格 ≥%d 像素' % (a.grid, a.min_px))
    print()
    print('%-13s %6s | %7s %7s %6s | %7s %7s %6s'
          % ('滤镜', '共有格', 'O跨片', 'O同图', '倍数', 'A跨片', 'A同图', '倍数'))
    print('-' * 82)
    rows = []
    for slot, name in order:
        if want and name not in want:
            continue
        p4o = find(os.path.join(SAMP, 'real_v3'), slot, name)
        p4t = find(os.path.join(SAMP, 'real_target'), slot, name)
        p8o, p8t = find(a.dir, slot, '%s__O' % name), find(a.dir, slot, '%s__T' % name)
        if not all([p4o, p4t, p8o, p8t]):
            continue
        O = {'4484': load(p4o, a.size), '8981': load(p8o, a.size)}
        T = {'4484': load(p4t, a.size), '8981': load(p8t, a.size)}
        M = {f: mask_of(O[f], T[f]) for f in O}
        res = {}
        for dom, X in (('O', O), ('A', AN)):
            c4 = cell_stats(X['4484'], T['4484'], M['4484'], a.grid, a.min_px)
            c8 = cell_stats(X['8981'], T['8981'], M['8981'], a.grid, a.min_px)
            keys = sorted(set(c4) & set(c8))
            if len(keys) < 8:
                break
            cross = float(np.mean([np.abs(c4[k][0] - c8[k][0]).mean() for k in keys]))
            w = np.nanmean([within(X[f], T[f], M[f], a.grid, a.min_px) for f in ('4484', '8981')])
            res[dom] = (len(keys), cross, w)
        if len(res) < 2:
            continue
        rows.append((name, res))
        print('%-13s %6d | %7.2f %7.2f %5.1fx | %7.2f %7.2f %5.1fx'
              % (name, res['O'][0], res['O'][1], res['O'][2], res['O'][1] / res['O'][2],
                 res['A'][1], res['A'][2], res['A'][1] / res['A'][2]), flush=True)

    print('-' * 82)
    for dom, lab in (('O', '我们的成片'), ('A', '中性锚点')):
        c = np.mean([r[1][dom][1] for r in rows])
        w = np.nanmean([r[1][dom][2] for r in rows])
        print('%s（域 %s）：跨底片 %.2f 级，同图内 %.2f 级 —— %.1f 倍'
              % (lab, dom, c, w, c / w))
    print()
    print('判读：倍数越接近 1，说明这个输入域上「官方输出」越接近输入的确定函数，')
    print('      跨底片才可能在原理上成立。')

    if rows and a.csv:
        with open(a.csv, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['name', 'cells', 'O_cross', 'O_within', 'A_cross', 'A_within'])
            for name, res in rows:
                w.writerow([name, res['O'][0], '%.4f' % res['O'][1], '%.4f' % res['O'][2],
                            '%.4f' % res['A'][1], '%.4f' % res['A'][2]])
        print('CSV → %s' % a.csv)


if __name__ == '__main__':
    main()
