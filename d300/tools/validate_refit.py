#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在新底片（8981）上重新拟合后期 LUT，回答「LUT 是可迁移的方法，还是只能在这张图上用」。

三组数字，同一口径（420px、CLIP 掩膜、ΔE00）：
  1. 机内            —— 不加任何后期，我们 vs 官方
  2. 套 4484 的 LUT  —— 直接把在旧底片上拟合出来的 cube 拿过来用
  3. 在 8981 上重拟合 —— 分两种：
       in-sample：全图拟合、全图打分（会把「记住这张图」也算成收益，只能当上界）
       cv：      2×2 空间分块留出，拟合 3 块、打分第 4 块（这个才是可迁移的数）

如果「重拟合 cv」回到 4484 留出的水平（≈2.1），说明方法本身可迁移，
只是每张底片要各标定一次；如果重拟合 cv 仍停在 3.3，说明新底片本身更难。

用法：
    python tools/validate_refit.py                      # 全 26 支
    python tools/validate_refit.py --only DREAM,STANDARD
    python tools/validate_refit.py --grid 9 --grid 17   # 扫网格密度
"""
import argparse
import csv
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lut_fit import fit_lut, interp, folds, mask_of, _raw_metrics, read_cube, apply_cube  # noqa: E402
from real_gap import NAMES, MONO, load, find                                             # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
SAMP = os.path.join(ROOT, 'samples')
LUTD = os.path.join(ROOT, 'lut')


def cube_path(name):
    for f in os.listdir(LUTD):
        if f.lower().endswith('.cube') and name.lower() in f.lower():
            return os.path.join(LUTD, f)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default=os.path.normpath(
        os.path.join(ROOT, '..', '_validate_nef', '8981b')))
    ap.add_argument('--size', type=int, default=420)
    ap.add_argument('--grid', default='17', help='逗号分隔，可一次扫多个密度')
    ap.add_argument('--iters', type=int, default=120)
    ap.add_argument('--only', default=None)
    ap.add_argument('--csv', default=os.path.join(SAMP, 'validate_refit.csv'))
    a = ap.parse_args()

    grids = [int(x) for x in a.grid.split(',')]
    want = set(x.strip().upper() for x in a.only.split(',')) if a.only else None

    rows = []
    for slot, name in enumerate(NAMES, 1):
        if want and name not in want:
            continue
        po = find(a.dir, slot, '%s__O' % name)
        pt = find(a.dir, slot, '%s__T' % name)
        if not po or not pt:
            continue
        A, B = load(po, a.size), load(pt, a.size)
        if A.shape != B.shape:
            continue
        m = mask_of(A, B)
        src, dst = A[m], B[m]

        r = dict(slot=slot, name=name,
                 type='mono' if name in MONO else 'color',
                 px=int(m.sum()))
        r['de_in'] = _raw_metrics(src, dst)['de']

        cp = cube_path(name)
        if cp and os.path.exists(cp):
            O2 = apply_cube(A, read_cube(cp), 33)
            r['de_old'] = _raw_metrics(O2[m], dst)['de']
        else:
            r['de_old'] = float('nan')

        for N in grids:
            # in-sample：只当上界看
            G = fit_lut(src, dst, N=N, iters=a.iters)
            r['de_fit%d' % N] = _raw_metrics(np.clip(interp(G, src), 0, 255), dst)['de']
            # cv：2×2 空间留出
            des = []
            for fm in folds(A.shape):
                tr, te = m & ~fm, m & fm
                if te.sum() < 500 or tr.sum() < 5000:
                    continue
                Gc = fit_lut(A[tr], B[tr], N=N, iters=a.iters)
                des.append(_raw_metrics(np.clip(interp(Gc, A[te]), 0, 255),
                                        B[te])['de'])
            r['de_cv%d' % N] = float(np.mean(des)) if des else float('nan')
        rows.append(r)
        print('  %-12s 机内 %5.2f  套旧LUT %5.2f  重拟合 %5.2f  留出 %5.2f'
              % (name, r['de_in'], r['de_old'], r['de_fit%d' % grids[0]],
                 r['de_cv%d' % grids[0]]), flush=True)

    g = grids[0]
    print()
    print('%3s %-12s %7s %9s %9s %9s' % ('#', '滤镜', '机内', '套旧LUT', '重拟合', '留出'))
    print('-' * 52)
    for r in rows:
        print('%3d %-12s %7.2f %9.2f %9.2f %9.2f'
              % (r['slot'], r['name'], r['de_in'], r['de_old'],
                 r['de_fit%d' % g], r['de_cv%d' % g]))
    print('-' * 52)

    def mv(k, sub=None):
        v = [r[k] for r in (sub or rows) if r[k] == r[k]]
        return sum(v) / len(v) if v else float('nan')

    col = [r for r in rows if r['type'] == 'color']
    mono = [r for r in rows if r['type'] == 'mono']
    print('全部 %2d 支  机内 %.2f → 套旧LUT %.2f → 重拟合 %.2f（留出 %.2f）'
          % (len(rows), mv('de_in'), mv('de_old'), mv('de_fit%d' % g), mv('de_cv%d' % g)))
    print('彩色 %2d 支  机内 %.2f → 套旧LUT %.2f → 重拟合 %.2f（留出 %.2f）'
          % (len(col), mv('de_in', col), mv('de_old', col),
             mv('de_fit%d' % g, col), mv('de_cv%d' % g, col)))
    print('单色 %2d 支  机内 %.2f → 套旧LUT %.2f → 重拟合 %.2f（留出 %.2f）'
          % (len(mono), mv('de_in', mono), mv('de_old', mono),
             mv('de_fit%d' % g, mono), mv('de_cv%d' % g, mono)))

    if len(grids) > 1:
        print()
        print('网格密度扫描（留出均值）：')
        for N in grids:
            print('  N=%-3d 全部 %.2f   彩色 %.2f   单色 %.2f'
                  % (N, mv('de_cv%d' % N), mv('de_cv%d' % N, col), mv('de_cv%d' % N, mono)))

    if a.csv:
        keys = ['slot', 'name', 'type', 'px', 'de_in', 'de_old']
        for N in grids:
            keys += ['de_fit%d' % N, 'de_cv%d' % N]
        with open(a.csv, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(keys)
            for r in rows:
                w.writerow([r.get(k, '') for k in keys])
        print()
        print('CSV → %s' % a.csv)


if __name__ == '__main__':
    main()
