#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""crossfilm_family.py —— 跨底片补偿该用哪一族全局变换？

`crossfilm_calib.py` 用 3×4 仿射，全 26 支实测 3.58 → 3.05，只吃掉约三分之一。
原因很可能是仿射太硬：整图级的那一维如果是「随影调变化的曲线」，12 个自由度表达不了。

本脚本把几族「整图共用、参数很少」的变换放在一起比：

  post_affine      LUT 输出 → 3×4 仿射（12 参数）
  post_lin        同上，但在线性光域里做（sRGB 解码 → 仿射 → 编码）
  post_poly2      LUT 输出 → 二次多项式（30 参数，含交叉项）
  post_cube5      LUT 输出 → 5³ 三维表（125×3，三线性插值）
  pre_affine      LUT 输入侧 3×4 仿射（带 LM 阻尼，防单色支发散）

每种都算两行：
  · 逐支  = 每支各解一个（这一族能到多好，是上界）
  · 共用  = 只用一支参考滤镜解，其余 25 支共用

LUT 网格缓存到 `samples/.crossfilm_luts.npz`，第一次跑要 ~10 分钟，之后秒出。

    python tools/crossfilm_family.py                 # 全 26 支
    python tools/crossfilm_family.py --families post_affine,post_poly2 --refs STANDARD
"""
import argparse
import csv
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, HERE)
from lut_fit import fit_lut, interp, mask_of, _raw_metrics      # noqa: E402
from real_gap import load, find                                  # noqa: E402
from crossfilm_calib import fit_pre                             # noqa: E402

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


# ------------------------------------------------------------------ 色彩空间
def srgb_to_lin(v):
    x = v / 255.0
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(x):
    x = np.clip(x, 0.0, 1.0)
    return 255.0 * np.where(x <= 0.0031308, 12.92 * x,
                            1.055 * np.power(x, 1 / 2.4) - 0.055)


# ------------------------------------------------------------------ 各族的解与用
def feats(x, kind):
    r, g, b = x[:, 0], x[:, 1], x[:, 2]
    if kind == 'affine':
        return np.stack([np.ones_like(r), r, g, b], 1)
    if kind == 'poly2':
        return np.stack([np.ones_like(r), r, g, b, r * r, g * g, b * b,
                         r * g, r * b, g * b], 1)
    raise KeyError(kind)


def fit_post(pred, tgt, kind='affine', lin=False):
    if kind == 'cube5':
        return ('cube', fit_lut(pred, tgt, N=5, iters=40, trust=120.0, stages=()))
    p = srgb_to_lin(pred) if lin else pred
    t = srgb_to_lin(tgt) if lin else tgt
    A = feats(p, kind)
    sol, *_ = np.linalg.lstsq(A, t, rcond=None)
    return ('lsq', (kind, sol, lin))


def apply_post(pred, model):
    tag, m = model
    if tag == 'cube':
        return np.clip(interp(m, pred), 0, 255)
    kind, sol, lin = m
    p = srgb_to_lin(pred) if lin else pred
    y = feats(p, kind) @ sol
    return np.clip(lin_to_srgb(y) if lin else y, 0, 255)


FAMILIES = {
    'post_affine': lambda p, t: fit_post(p, t, 'affine', False),
    'post_lin': lambda p, t: fit_post(p, t, 'affine', True),
    'post_poly2': lambda p, t: fit_post(p, t, 'poly2', False),
    'post_cube5': lambda p, t: fit_post(p, t, 'cube5', False),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--size', type=int, default=420)
    ap.add_argument('--grid', type=int, default=17)
    ap.add_argument('--iters', type=int, default=120)
    ap.add_argument('--trust', type=float, default=40.0)
    ap.add_argument('--families', default='post_affine,post_lin,post_poly2,post_cube5,pre_affine')
    ap.add_argument('--refs', default='STANDARD,NEUTRAL,LANDSCAPE,MONOCHROME')
    ap.add_argument('--dir', default='both')
    ap.add_argument('--only', default=None)
    ap.add_argument('--csv', default=os.path.join(SAMP, 'crossfilm_family.csv'))
    a = ap.parse_args()

    order = [(int(r['slot']), r['name'])
             for r in csv.DictReader(open(os.path.join(SAMP, 'metrics_real.csv'),
                                          encoding='utf-8-sig'))]
    want = set(x.strip().upper() for x in a.only.split(',')) if a.only else None

    D = {}
    for f, c in FILMS.items():
        for slot, name in order:
            po = find(c['odir'], slot, '%s%s' % (name, c['osuf']))
            pt = find(c['tdir'], slot, '%s%s' % (name, c['tsuf']))
            if po and pt:
                O, T = load(po, a.size), load(pt, a.size)
                if O.shape == T.shape:
                    D[(f, name)] = (O, T)
    names = [n for _, n in order if all((f, n) in D for f in FILMS)]
    if want:
        names = [n for n in names if n in want]
    M = {f: {n: mask_of(*D[(f, n)]) for n in names} for f in FILMS}

    # ---- LUT 网格：缓存 ----
    keys = ['%s|%s' % (f, n) for f in FILMS for n in names]
    G = {}
    if os.path.exists(CACHE):
        z = np.load(CACHE, allow_pickle=True)
        if set(z.files) >= set(keys):
            G = {k: z[k] for k in keys}
            print('LUT 网格来自缓存 %s' % CACHE)
    if not G:
        for f in FILMS:
            for i, n in enumerate(names):
                O, T = D[(f, n)]
                G[(f, n)] = fit_lut(O[M[f][n]], T[M[f][n]], N=a.grid,
                                    iters=a.iters, trust=a.trust)
                print('  拟合 %s/%s ... (%d/%d)' % (f, n, i + 1, len(names)), flush=True)
        np.savez_compressed(CACHE, **{'%s|%s' % k: v for k, v in G.items()})
        print('LUT 网格 → %s' % CACHE)

    dirs = [('4484', '8981'), ('8981', '4484')] if a.dir == 'both' else [tuple(a.dir.split('->'))]
    fams = [x.strip() for x in a.families.split(',') if x.strip()]
    refs = [x.strip().upper() for x in a.refs.split(',') if x.strip() and x.strip().upper() in names]

    rows = []
    for src, dst in dirs:
        tag = '%s->%s' % (src, dst)
        pred = {n: np.clip(interp(G[(src, n)], D[(dst, n)][0][M[dst][n]]), 0, 255)
                for n in names}
        T = {n: D[(dst, n)][1][M[dst][n]] for n in names}
        O = {n: D[(dst, n)][0][M[dst][n]] for n in names}
        for n in names:
            rows.append((tag, '直接套', '-', n, _raw_metrics(pred[n], T[n])['de']))
        for fam in fams:
            # 逐支
            models = {}
            for n in names:
                if fam == 'pre_affine':
                    m = fit_pre(G[(src, n)], O[n], T[n], iters=4)
                    y = np.clip(interp(G[(src, n)], np.clip(O[n] @ m[0].T + m[1], 0, 255)), 0, 255)
                else:
                    m = FAMILIES[fam](pred[n], T[n])
                    y = apply_post(pred[n], m)
                models[n] = m
                rows.append((tag, fam, '逐支', n, _raw_metrics(y, T[n])['de']))
            # 共用（一支参考滤镜解）
            for ref in refs:
                if ref not in models:
                    continue
                for n in names:
                    if fam == 'pre_affine':
                        m = models[ref]
                        y = np.clip(interp(G[(src, n)], np.clip(O[n] @ m[0].T + m[1], 0, 255)), 0, 255)
                    else:
                        y = apply_post(pred[n], models[ref])
                    rows.append((tag, fam, ref, n, _raw_metrics(y, T[n])['de']))
        print('%s 完成' % tag, flush=True)

    print()
    base = np.mean([r[4] for r in rows if r[1] == '直接套'])
    print('直接套基线 %.2f' % base)
    print('%-13s %-11s %8s %8s %7s' % ('族', '参考', 'ΔE00', 'vs基线', '改善支数'))
    print('-' * 54)
    seen = []
    for fam in fams:
        for ref in ['逐支'] + refs:
            sel = [r for r in rows if r[1] == fam and r[2] == (ref if ref != '逐支' else '逐支')]
            if not sel:
                continue
            v = np.mean([r[4] for r in sel])
            pm = {}
            for r in sel:
                pm.setdefault(r[3], []).append(r[4])
            bl = {}
            for r in rows:
                if r[1] == '直接套':
                    bl.setdefault(r[3], []).append(r[4])
            better = sum(1 for k in pm if np.mean(pm[k]) < np.mean(bl[k]) - 0.01)
            print('%-13s %-11s %8.2f %8.2f %6d/%d'
                  % (fam, ref, v, v - base, better, len(pm)))
            seen.append((fam, ref, v, better))
        print('-' * 54)

    if a.csv:
        with open(a.csv, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['dir', 'family', 'ref', 'name', 'dE00'])
            for r in rows:
                w.writerow([r[0], r[1], r[2], r[3], '%.4f' % r[4]])
        print('csv → %s' % a.csv)


if __name__ == '__main__':
    main()
