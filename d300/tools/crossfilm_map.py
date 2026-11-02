#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""crossfilm_map.py —— 跨底片映射的最终方案与最终数字。

一句话结论
----------
**没有免费的跨底片映射；能免费拿回来的只有一块（约 20%），剩下的必须按图重标定。**

三件被逐一否掉/确认的事
------------------------
1. 换输入域（改成「不经过 Picture Control 的中性锚点」）—— **无效**，跨底片不确定性
   从 6.3 倍升到 4.8 倍（`crossfilm_domain.py`）。说明这一维不在「我们的成片」里丢的。
2. 3D LUT 的空格子 —— **确实是一块，而且能免费修**。表是在一张图上拟合的，源底片没采到的
   格子会保持恒等，新图落进去就等于没查表。把空格子按邻居扩散填上，26 支 × 2 方向
   合计 −0.29；与「未覆盖比例」的相关性 r = 0.76（`crossfilm_coverage.py`）。
3. 整图级补偿（把这维当成一张图共用的 3×4 仿射，用一支参考滤镜现场解）—— **逐支有效、
   共用无效**。逐支 −0.65，但一支参考滤镜解出来的 g 套到别的支上收益接近 0，
   甚至会把本来做得好的支弄坏（DREAM 1.33 → 2.89）。

本脚本把 2 和 3 叠起来，给一张自洽的最终表（同一套网格、同一个口径）。

    python tools/crossfilm_map.py                 # 最终表
    python tools/crossfilm_map.py --refs STANDARD
"""
import argparse
import csv
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, HERE)
from lut_fit import interp, mask_of, _raw_metrics                # noqa: E402
from real_gap import load, find                                   # noqa: E402
from crossfilm_calib import fit_pre, fit_post, affine_apply       # noqa: E402
from crossfilm_coverage import support, uncovered, fill_gaps      # noqa: E402

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--size', type=int, default=420)
    ap.add_argument('--grid', type=int, default=17)
    ap.add_argument('--fill-rounds', type=int, default=60)
    ap.add_argument('--min-sup', type=int, default=3)
    ap.add_argument('--refs', default='STANDARD,NEUTRAL')
    ap.add_argument('--csv', default=os.path.join(SAMP, 'crossfilm_map.csv'))
    a = ap.parse_args()
    refs = [x.strip().upper() for x in a.refs.split(',') if x.strip()]

    order = [(int(r['slot']), r['name'])
             for r in csv.DictReader(open(os.path.join(SAMP, 'metrics_real.csv'),
                                          encoding='utf-8-sig'))]
    names = [n for _, n in order]
    if not os.path.exists(CACHE):
        sys.exit('缺 LUT 缓存，先跑一次 tools/crossfilm_coverage.py')
    z = np.load(CACHE, allow_pickle=True)

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

    rows = []
    for src, dst in (('4484', '8981'), ('8981', '4484')):
        tag = '%s->%s' % (src, dst)
        grids = {}
        for n in names:
            if (src, n) not in D or (dst, n) not in D:
                continue
            g = z['%s|%s' % (src, n)]
            sup = support(D[(src, n)][0][M[src][n]], a.grid)
            grids[n] = fill_gaps(g, sup, a.grid, a.fill_rounds, a.min_sup)
            X = D[(dst, n)][0][M[dst][n]]
            T = D[(dst, n)][1][M[dst][n]]
            d0 = _raw_metrics(np.clip(interp(g, X), 0, 255), T)['de']
            d1 = _raw_metrics(np.clip(interp(grids[n], X), 0, 255), T)['de']
            rows.append([tag, n, '直接套', '-', d0])
            rows.append([tag, n, '补空洞', '-', d1])
            rows.append([tag, n, '未覆盖%', '-', uncovered(X, sup, a.grid, a.min_sup) * 100])

        # 整图补偿：叠在「补空洞」之上
        pred = {n: np.clip(interp(grids[n], D[(dst, n)][0][M[dst][n]]), 0, 255)
                for n in grids}
        TT = {n: D[(dst, n)][1][M[dst][n]] for n in grids}
        OO = {n: D[(dst, n)][0][M[dst][n]] for n in grids}
        mods = {}
        for n in grids:
            m = fit_post(pred[n], TT[n])
            rows.append([tag, n, '补+逐支后仿射', '-',
                         _raw_metrics(affine_apply(pred[n], *m), TT[n])['de']])
            mp = fit_pre(grids[n], OO[n], TT[n], iters=4)
            rows.append([tag, n, '补+逐支预仿射', '-',
                         _raw_metrics(np.clip(interp(grids[n], affine_apply(OO[n], *mp)),
                                              0, 255), TT[n])['de']])
            mods[n] = (m, mp)
        for ref in refs:
            if ref not in mods:
                continue
            m, mp = mods[ref]
            for n in grids:
                rows.append([tag, n, '补+共用后仿射', ref,
                             _raw_metrics(affine_apply(pred[n], *m), TT[n])['de']])
                rows.append([tag, n, '补+共用预仿射', ref,
                             _raw_metrics(np.clip(interp(grids[n],
                                                         affine_apply(OO[n], *mp)),
                                                  0, 255), TT[n])['de']])
        print('%s 完成' % tag, flush=True)

    def val(kind, ref='-', d=None, key=4):
        return [r[key] for r in rows if r[2] == kind and r[3] == ref
                and (d is None or r[0] == d)]

    base = np.mean(val('直接套'))
    print()
    print('%-20s %-10s %8s %8s %6s' % ('方案', '参考滤镜', 'ΔE00', 'vs直接套', '改善支数'))
    print('-' * 60)
    plan = [('直接套', '-')] + \
           [('补空洞', '-')] + \
           [('补+逐支后仿射', '-'), ('补+逐支预仿射', '-')] + \
           [(k, r) for r in refs for k in ('补+共用后仿射', '补+共用预仿射')]
    for kind, ref in plan:
        v = val(kind, ref)
        if not v:
            continue
        per = {}
        for r in rows:
            if r[2] == kind and r[3] == ref:
                per.setdefault(r[1], []).append(r[4])
        bl = {}
        for r in rows:
            if r[2] == '直接套':
                bl.setdefault(r[1], []).append(r[4])
        better = sum(1 for k in per if np.mean(per[k]) < np.mean(bl[k]) - 0.01)
        print('%-20s %-10s %8.2f %8.2f %5d/%d'
              % (kind, ref, np.mean(v), np.mean(v) - base, better, len(per)))
    print('-' * 60)

    # 与 docs/25 对齐的单方向口径
    print()
    for d in ('4484->8981', '8981->4484'):
        line = '  %s：' % d
        for kind, ref in (('直接套', '-'), ('补空洞', '-'), ('补+逐支后仿射', '-')):
            line += '%s %.2f   ' % (kind, np.mean(val(kind, ref, d)))
        print(line)

    if a.csv:
        with open(a.csv, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['dir', 'name', 'plan', 'ref', 'value'])
            for r in rows:
                w.writerow([r[0], r[1], r[2], r[3], '%.4f' % r[4]])
        print('csv → %s' % a.csv)


if __name__ == '__main__':
    main()
