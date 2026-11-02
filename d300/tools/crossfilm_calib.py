#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""crossfilm_calib.py —— 跨底片映射：把「图像侧」的自由度显式拎出来，用一支滤镜现场标定。

诊断结论（本脚本上半部分会重跑一遍）
------------------------------------
`docs/25` 测到：同一个输入 RGB，官方在两张底片上的输出差 4.07 级，同图内部只差 0.65 级。
试过换输入域（把 LUT 的输入从「我们的成片」换成「不经过任何 PC 的中性锚点」），
跨底片差反而升到 4.80 —— 换域没用（`crossfilm_domain.py`，已否掉）。

结论：官方渲染除了吃「这个像素的 RGB」，还吃「这张图」。这一维不补，
任何逐像素查表都不可能跨底片 —— 这不是拟合算法的问题，是信息不在这。

本脚本的做法
------------
把「吃图」的这一维假设成一个**全局变换**（整图共用一个 3×4 颜色仿射），放在 LUT 前后：

    预补偿：  T ≈ LUT( g_pre(O) )       g_pre 作用在输入侧
    后补偿：  T ≈ g_post( LUT(O) )      g_post 作用在输出侧

它只有 12 个自由度，用一张图里十几万像素拟合，极度过定 —— 但**它需要一点真值**：
在要处理的新底片上，导一支参考滤镜的成片对，就能解出 g；然后 26 支共用这一个 g。

代价从「每支滤镜每张图各导一次」降到「每张图导一次」。这就是本脚本要验证的收益。

四组对照（全部留一底片：在 4484 上标定，拿到 8981 上打分，再反过来）
  · 直接套        —— 什么都不做（基线 3.33）
  · 后补偿 g_post —— 用一支参考滤镜现场解 g，其余 25 支共用
  · 预补偿 g_pre  —— 同上，g 作用在输入侧
  · 逐支 g        —— 每支各自解 g（这一族方法的上界，不是可交付方案）

    python tools/crossfilm_calib.py                       # 全 26 支
    python tools/crossfilm_calib.py --refs STANDARD,NEUTRAL,DREAM
    python tools/crossfilm_calib.py --dir 8981->4484      # 只跑一个方向
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
from lut_fit import fit_lut, interp, mask_of, _raw_metrics      # noqa: E402
from real_gap import load, find                                  # noqa: E402

SAMP = os.path.join(ROOT, 'samples')
UP = os.path.normpath(os.path.join(ROOT, '..'))

FILMS = {
    '4484': dict(odir=os.path.join(SAMP, 'real_v3'), tdir=os.path.join(SAMP, 'real_target'),
                 osuf='', tsuf=''),
    '8981': dict(odir=os.path.join(UP, '_validate_nef', '8981b'),
                 tdir=os.path.join(UP, '_validate_nef', '8981b'),
                 osuf='__O', tsuf='__T'),
}


# ------------------------------------------------------------------ 两个方向的仿射
def affine_apply(x, M, b):
    """x:(N,3) → x@M.T + b"""
    return np.clip(x @ M.T + b, 0.0, 255.0)


def fit_post(pred, tgt, iters=2):
    """解 g_post：tgt ≈ pred @ M.T + b（3×4 最小二乘，闭式）"""
    N = pred.shape[0]
    A = np.hstack([pred, np.ones((N, 1))])
    sol, *_ = np.linalg.lstsq(A, tgt, rcond=None)     # (4,3)
    return sol[:3].T, sol[3]


def fit_pre(grid, src, tgt, M=None, b=None, iters=3):
    """解 g_pre：tgt ≈ LUT( src @ M.T + b )

    LUT 非线性，所以用高斯-牛顿：残差对 12 个参数是线性的（用 LUT 的局部雅可比），
    解出来再迭代。初值是恒等，一般 2–3 轮收敛到 1e-3 量级。
    """
    if M is None:
        M, b = np.eye(3), np.zeros(3)
    for _ in range(iters):
        p = affine_apply(src, M, b)
        pred = interp(grid, p)
        r = tgt - pred                                  # (N,3)
        # 局部雅可比 J[i,c,d] = dLUT_c / dp_d
        J = np.empty((p.shape[0], 3, 3))
        for d in range(3):
            e = np.zeros(3)
            e[d] = 1.0
            J[:, :, d] = (interp(grid, np.clip(p + e, 0, 255))
                          - interp(grid, np.clip(p - e, 0, 255))) / 2.0
        z = np.hstack([p, np.ones((p.shape[0], 1))])     # (N,4)
        A = np.einsum('icd,ik->icdk', J, z).reshape(-1, 12)
        rhs = r.reshape(-1)
        H = A.T @ A + 1e-6 * np.eye(12)
        dv = np.linalg.solve(H, A.T @ rhs)
        dM = dv.reshape(3, 4)
        M = M + dM[:, :3]
        b = b + dM[:, 3]
        if np.abs(dv).max() < 1e-3:
            break
    return M, b


# ------------------------------------------------------------------ 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--size', type=int, default=420)
    ap.add_argument('--grid', type=int, default=17)
    ap.add_argument('--iters', type=int, default=120)
    ap.add_argument('--trust', type=float, default=40.0)
    ap.add_argument('--refs', default='STANDARD,NEUTRAL,FLAT,DREAM,BINARY')
    ap.add_argument('--dir', default='both', help='both / 4484->8981 / 8981->4484')
    ap.add_argument('--only', default=None)
    ap.add_argument('--csv', default=os.path.join(SAMP, 'crossfilm_calib.csv'))
    a = ap.parse_args()
    refs = [x.strip().upper() for x in a.refs.split(',') if x.strip()]

    order = [(int(r['slot']), r['name'])
             for r in csv.DictReader(open(os.path.join(SAMP, 'metrics_real.csv'),
                                          encoding='utf-8-sig'))]
    want = set(x.strip().upper() for x in a.only.split(',')) if a.only else None

    CACHE = {}
    for f, c in FILMS.items():
        for slot, name in order:
            po = find(c['odir'], slot, '%s%s' % (name, c['osuf']))
            pt = find(c['tdir'], slot, '%s%s' % (name, c['tsuf']))
            if po and pt:
                O, T = load(po, a.size), load(pt, a.size)
                if O.shape == T.shape:
                    CACHE[(f, name)] = (O, T)
    names = [n for _, n in order if all((f, n) in CACHE for f in FILMS)]
    if want:
        names = [n for n in names if n in want]
    refs = [r for r in refs if r in names]
    print('%d 支 × %d 张底片参与' % (len(names), len(FILMS)))

    dirs = [('4484', '8981'), ('8981', '4484')] if a.dir == 'both' else [tuple(a.dir.split('->'))]
    rows = []
    for src, dst in dirs:
        t0 = time.time()
        mask = {f: {n: mask_of(*CACHE[(f, n)]) for n in names} for f in FILMS}
        # 1) 源底片上为每支拟合 LUT（这是「发货」的那批表）
        G = {}
        for n in names:
            O, T = CACHE[(src, n)]
            m = mask[src][n]
            G[n] = fit_lut(O[m], T[m], N=a.grid, iters=a.iters, trust=a.trust)
        # 2) 目标底片上：直接套
        pred = {}
        for n in names:
            O, T = CACHE[(dst, n)]
            m = mask[dst][n]
            pred[n] = np.clip(interp(G[n], O[m]), 0, 255)
        for n in names:
            rows.append(dict(dir='%s->%s' % (src, dst), name=n, kind='直接套',
                             ref='-', de=_raw_metrics(pred[n], CACHE[(dst, n)][1][mask[dst][n]])['de']))
        # 3) 逐支 g（上界）
        for n in names:
            T = CACHE[(dst, n)][1][mask[dst][n]]
            M, b = fit_post(pred[n], T)
            rows.append(dict(dir='%s->%s' % (src, dst), name=n, kind='逐支后补偿',
                             ref='-', de=_raw_metrics(affine_apply(pred[n], M, b), T)['de']))
            Om = CACHE[(dst, n)][0][mask[dst][n]]
            M2, b2 = fit_pre(G[n], Om, T)
            rows.append(dict(dir='%s->%s' % (src, dst), name=n, kind='逐支预补偿',
                             ref='-', de=_raw_metrics(
                                 np.clip(interp(G[n], affine_apply(Om, M2, b2)), 0, 255), T)['de']))
        # 4) 一支参考滤镜解 g，全部共用
        for ref in refs:
            if ref not in names:
                continue
            Tref = CACHE[(dst, ref)][1][mask[dst][ref]]
            M, b = fit_post(pred[ref], Tref)
            Om = CACHE[(dst, ref)][0][mask[dst][ref]]
            Mp, bp = fit_pre(G[ref], Om, Tref)
            for n in names:
                T = CACHE[(dst, n)][1][mask[dst][n]]
                rows.append(dict(dir='%s->%s' % (src, dst), name=n, kind='共用后补偿',
                                 ref=ref, de=_raw_metrics(affine_apply(pred[n], M, b), T)['de']))
                On = CACHE[(dst, n)][0][mask[dst][n]]
                rows.append(dict(dir='%s->%s' % (src, dst), name=n, kind='共用预补偿',
                                 ref=ref, de=_raw_metrics(
                                     np.clip(interp(G[n], affine_apply(On, Mp, bp)), 0, 255), T)['de']))
        print('%s->%s 完成，%.0fs' % (src, dst, time.time() - t0), flush=True)

    # ---- 汇总 ----
    print()
    print('%-10s %-12s %-10s %8s %8s' % ('方向', '方案', '参考滤镜', 'ΔE00', 'vs直接套'))
    print('-' * 56)
    keys = []
    for d in sorted(set(r['dir'] for r in rows)):
        base = np.mean([r['de'] for r in rows if r['dir'] == d and r['kind'] == '直接套'])
        for kind in ('直接套', '共用后补偿', '共用预补偿', '逐支后补偿', '逐支预补偿'):
            for ref in (['-'] if kind in ('直接套', '逐支后补偿', '逐支预补偿') else refs):
                sel = [r['de'] for r in rows
                       if r['dir'] == d and r['kind'] == kind and r['ref'] == ref]
                if not sel:
                    continue
                v = float(np.mean(sel))
                print('%-10s %-12s %-10s %8.2f %8.2f' % (d, kind, ref, v, v - base))
                keys.append((d, kind, ref, v))
        print('-' * 56)

    # 两个方向合起来的总均值（跨底片的正式数字）
    print()
    for kind in ('直接套', '共用后补偿', '共用预补偿', '逐支后补偿', '逐支预补偿'):
        for ref in (['-'] if kind in ('直接套', '逐支后补偿', '逐支预补偿') else refs):
            sel = [r['de'] for r in rows if r['kind'] == kind and r['ref'] == ref]
            if sel:
                print('%-12s %-10s 两个方向合计 %.2f' % (kind, ref, np.mean(sel)))

    if a.csv:
        with open(a.csv, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['dir', 'name', 'kind', 'ref', 'dE00'])
            for r in rows:
                w.writerow([r['dir'], r['name'], r['kind'], r['ref'], '%.4f' % r['de']])
        print('csv → %s' % a.csv)


if __name__ == '__main__':
    main()
