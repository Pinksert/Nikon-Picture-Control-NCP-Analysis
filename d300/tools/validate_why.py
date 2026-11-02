#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LUT 跨底片失效的机制定位 + 一个可能的廉价修法。

上一支脚本（validate_mapping.py）已经量出：同一个「我们的 RGB」在两张底片上，
官方的输出平均差 4.4 级，而同一张图内的噪声只有 0.56 级。所以逐像素假设不成立。
这里回答两件事：

  一、那 4.4 级是亮度差还是色彩差？
      亮度占主导 ⇒ 主因是两张底片曝光/影调不同，有廉价修法
      色彩占主导 ⇒ 主因是白平衡/色度映射不同，LUT 输入的基准就不对

  二、如果能靠「按底片做一次全局色调归一化」把 LUT 救回来，用户就不必重新拟合：
      O8 --g--> 4484 的色调分布 --4484的LUT--> --h--> 8981 的色调分布 == T8 ?
      g 用我们的两图输出通道分位数配准，h 用官方的两图输出配准。

用法：
    python tools/validate_why.py --only DREAM,STANDARD
"""
import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from real_gap import NAMES, load, find                 # noqa: E402
from lut_fit import mask_of, read_cube, apply_cube     # noqa: E402
from diag_residual import to_lab, de2000               # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
SAMP = os.path.join(ROOT, 'samples')
LUTD = os.path.join(ROOT, 'lut')


def cube_path(name):
    for f in os.listdir(LUTD):
        if f.lower().endswith('.cube') and name.lower() in f.lower():
            return os.path.join(LUTD, f)
    return None


def cells(A, B, N, K):
    m = mask_of(A, B)
    idx = np.clip((A.reshape(-1, 3) / 255. * (N - 1)).round().astype(int), 0, N - 1)
    flat = idx[:, 0] * N * N + idx[:, 1] * N + idx[:, 2]
    Br = B.reshape(-1, 3)
    ok = m.reshape(-1)
    cnt = np.bincount(flat[ok], minlength=N ** 3)
    return {int(c): Br[ok & (flat == c)].mean(0)
            for c in np.nonzero(cnt >= K)[0]}


def quantile_map(src, dst):
    """逐通道分位数配准：把 src 的分布映射到 dst 的分布。返回可调用的查找函数。"""
    q = np.linspace(0, 100, 512)
    out = []
    for c in range(3):
        s = np.percentile(src[..., c].reshape(-1), q)
        d = np.percentile(dst[..., c].reshape(-1), q)
        out.append((s, d))
    def f(x):
        r = np.empty_like(x)
        for c in range(3):
            r[..., c] = np.interp(x[..., c], out[c][0], out[c][1])
        return r
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default=os.path.normpath(
        os.path.join(ROOT, '..', '_validate_nef', '8981b')))
    ap.add_argument('--size', type=int, default=420)
    ap.add_argument('--grid', type=int, default=17)
    ap.add_argument('--min-px', type=int, default=12)
    ap.add_argument('--only', default=None)
    a = ap.parse_args()
    want = set(x.strip().upper() for x in a.only.split(',')) if a.only else None

    print('一、跨底片那 4.4 级偏差的成分（LAB 分解）')
    print('%-12s %6s %8s %8s %8s   %s' % ('滤镜', '共有格', 'ΔL', 'ΔC', 'ΔH°', '主因'))
    print('-' * 56)
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
        v4 = np.stack([c4[k] for k in keys]);
        v8 = np.stack([c8[k] for k in keys])
        L4, L8 = to_lab(v4), to_lab(v8)
        dl = float(np.abs(L4[:, 0] - L8[:, 0]).mean())
        c4c = np.hypot(L4[:, 1], L4[:, 2]); c8c = np.hypot(L8[:, 1], L8[:, 2])
        dc = float(np.abs(c4c - c8c).mean())
        h4 = np.degrees(np.arctan2(L4[:, 2], L4[:, 1]))
        h8 = np.degrees(np.arctan2(L8[:, 2], L8[:, 1]))
        dh = np.abs((h4 - h8 + 180) % 360 - 180)
        w = (c4c > 8) & (c8c > 8)          # 灰的色相无意义，只看有彩格
        dhm = float(dh[w].mean()) if w.sum() > 3 else float('nan')
        rows.append((name, len(keys), dl, dc, dhm))
        print('%-12s %6d %8.2f %8.2f %8.1f   %s'
              % (name, len(keys), dl, dc, dhm, '亮度' if dl > dc else '色彩'))
    print('-' * 56)
    if rows:
        print('均值  ΔL %.2f   ΔC %.2f   ⇒ %s占主导'
              % (np.mean([r[2] for r in rows]), np.mean([r[3] for r in rows]),
                 '亮度' if np.mean([r[2] for r in rows]) > np.mean([r[3] for r in rows]) else '色彩'))

    print()
    print('二、廉价修法：套 LUT 前先做一次全局色调归一化（通道分位数配准）')
    print('%-12s %8s %10s %10s' % ('滤镜', '机内', '直接套', '归一化后套'))
    print('-' * 44)
    rows2 = []
    for slot, name in enumerate(NAMES, 1):
        if want and name not in want:
            continue
        cp = cube_path(name)
        p4o, p4t = find(os.path.join(SAMP, 'real_v3'), slot, name), \
            find(os.path.join(SAMP, 'real_target'), slot, name)
        p8o, p8t = find(a.dir, slot, '%s__O' % name), find(a.dir, slot, '%s__T' % name)
        if not cp or not all([p4o, p4t, p8o, p8t]):
            continue
        A4, B4 = load(p4o, a.size), load(p4t, a.size)
        A8, B8 = load(p8o, a.size), load(p8t, a.size)
        m = mask_of(A8, B8)
        cube = read_cube(cp)
        d0 = float(de2000(to_lab(A8[m]), to_lab(B8[m])).mean())
        d1 = float(de2000(to_lab(apply_cube(A8, cube, 33)[m]), to_lab(B8[m])).mean())
        g = quantile_map(A8, A4)          # 我们的：8981 → 4484 影调
        h = quantile_map(B4, B8)          # 官方的：4484 → 8981 影调
        pred = h(apply_cube(g(A8), cube, 33))
        d2 = float(de2000(to_lab(np.clip(pred, 0, 255)[m]), to_lab(B8[m])).mean())
        rows2.append((name, d0, d1, d2))
        print('%-12s %8.2f %10.2f %10.2f' % (name, d0, d1, d2))
    print('-' * 44)
    if rows2:
        print('均值  机内 %.2f → 直接套 %.2f → 归一化后套 %.2f'
              % (np.mean([r[1] for r in rows2]), np.mean([r[2] for r in rows2]),
                 np.mean([r[3] for r in rows2])))
        print()
        print('若「归一化后」明显低于「直接套」，说明 LUT 可以通用，只需每批照片做一次')
        print('全局色调配准（几十毫秒、不需要重新拟合）；否则只能每张底片重新拟合。')


if __name__ == '__main__':
    main()
