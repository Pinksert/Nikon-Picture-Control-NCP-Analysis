#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lut_floor.py —— 后期这条路的下限在哪：同一种机内颜色，官方给了几种颜色？

为什么要有这一步
----------------
`lut_fit.py` 把 26 支的残差拟合成 33³ 表，做到 ΔE00 2.10。剩下那些还差的
（RED 6.4、PINK 5.8、SEPIA 4.6、BLUE 4.7）有两种完全不同的解释：

  A. 表不够好 —— 换更好的拟合、更大的表、更细的分区就能降下来；
  B. 信息在机内就没了 —— 两个不同的原版颜色在机内被压成同一个颜色，
     之后任何查表都拆不开。

分辨方法：拿机内那张图（我们）当索引，把官方图（目标）按 3D 网格分箱，
看**同一个箱里官方颜色的散布有多大**。这个散布就是「任何 LUT 都做不到」
的那部分——用 2×2 空间留出评估，避免自证。

判读
----
  floor33 ≈ 实际 after        → 到头了，是 B，后期没有余量
  floor33 << 实际 after       → 还有空间，是 A，该换拟合/加密度

用法
----
    python tools/lut_floor.py                       # 默认 6 支（含最差的 4 支）
    python tools/lut_floor.py --only 15_RED,16_PINK
    python tools/lut_floor.py --size 0              # 原尺寸（慢，结论更稳）
"""
import argparse
import csv
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from diag_residual import to_lab, de2000        # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
OURS = os.path.join(ROOT, 'samples', 'real_v3')
GOV = os.path.join(ROOT, 'samples', 'real_target')
CSV = os.path.join(ROOT, 'samples', 'metrics_lut.csv')

# 默认看这几支：最差的 4 支（红/粉/棕褐/蓝，残差全在彩度）+ 最好的 1 支 + 单色 1 支
DEFAULT = ['01_DREAM', '12_TOY', '13_SEPIA', '14_BLUE', '15_RED', '16_PINK', '19_BINARY']


def load(path, size):
    im = Image.open(path).convert('RGB')
    if size:
        r = size / max(im.size)
        if r < 1.0:
            im = im.resize((max(1, int(round(im.width * r))),
                            max(1, int(round(im.height * r)))), Image.LANCZOS)
    return np.asarray(im, dtype=np.float64)


def valid_mask(a, b):
    """两边都没剪裁的像素（与 lut_fit 同口径：任一通道 <8 或 >247 排除）"""
    ok = np.all((a >= 8) & (a <= 247), axis=-1) & np.all((b >= 8) & (b <= 247), axis=-1)
    return ok


def bins_of(rgb, N):
    """sRGB 0..255 → 0..N-1 的 N³ 网格索引"""
    q = np.clip((rgb * N // 256).astype(np.int64), 0, N - 1)
    return (q[..., 0] * N + q[..., 1]) * N + q[..., 2], N ** 3


def fit_cells(idx, lab, ncell):
    """每个格子累加目标 LAB，返回 (sum, count)"""
    cnt = np.bincount(idx, minlength=ncell).astype(np.float64)
    out = np.empty((ncell, 3))
    for k in range(3):
        out[:, k] = np.bincount(idx, weights=lab[..., k], minlength=ncell)
    with np.errstate(invalid='ignore', divide='ignore'):
        out = out / np.maximum(cnt, 1)[:, None]
    return out, cnt


def floor_holdout(A, B, N, ny=2, nx=2):
    """2×2 空间留出：3 块拟合、1 块打分；空格子退回恒等（不修正）"""
    LA, LB = to_lab(A), to_lab(B)
    m = valid_mask(A, B)
    idx, ncell = bins_of(A, N)
    h, w = m.shape
    ys = np.linspace(0, h, ny + 1).astype(int)
    xs = np.linspace(0, w, nx + 1).astype(int)
    tot_w = tot_e = 0.0
    for i in range(ny):
        for j in range(nx):
            test = np.zeros_like(m)
            test[ys[i]:ys[i + 1], xs[j]:xs[j + 1]] = True
            tr = m & ~test
            te = m & test
            if te.sum() < 500 or tr.sum() < 500:
                continue
            cells, cnt = fit_cells(idx[tr], LB[tr], ncell)
            i_te = idx[te]
            has = cnt[i_te] > 0
            pred = LA[te].copy()
            pred[has] = cells[i_te[has]]
            d = de2000(pred, LB[te])
            tot_e += d.sum()
            tot_w += d.size
    return tot_e / max(tot_w, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--size', type=int, default=420, help='长边像素，0=原尺寸')
    ap.add_argument('--levels', default='9,17,33,65', help='网格密度，逗号分隔')
    ap.add_argument('--only', default='', help='只跑这几支，逗号分隔，如 15_RED,16_PINK')
    ap.add_argument('--csv-out', default=os.path.join(ROOT, 'samples', 'lut_floor.csv'))
    a = ap.parse_args()

    levels = [int(x) for x in a.levels.split(',') if x.strip()]
    names = [x.strip() for x in a.only.split(',') if x.strip()] or DEFAULT

    # 现状（加 LUT 之后）的实测值
    actual = {}
    if os.path.exists(CSV):
        for r in csv.DictReader(open(CSV, encoding='utf-8-sig')):
            try:
                actual[r['name']] = float(r['dE00_after'])
            except (KeyError, ValueError):
                pass

    rows = []
    head = ['%-12s' % '预设', '%8s' % '不修正'] + ['%8s' % ('N=%d' % n) for n in levels] \
           + ['%8s' % '实际LUT']
    print(' '.join(head))
    for tag in names:
        p1 = os.path.join(OURS, tag + '.JPG')
        p2 = os.path.join(GOV, tag + '.JPG')
        if not (os.path.exists(p1) and os.path.exists(p2)):
            print('%-12s 缺文件，跳过' % tag)
            continue
        A, B = load(p1, a.size), load(p2, a.size)
        base = float(de2000(to_lab(A)[valid_mask(A, B)], to_lab(B)[valid_mask(A, B)]).mean())
        fl = [floor_holdout(A, B, n) for n in levels]
        nm = tag.split('_', 1)[1]
        rows.append((tag, nm, base, *fl, actual.get(nm, float('nan'))))
        print('%-12s %8.2f ' % (tag, base) + ' '.join('%8.2f' % x for x in fl)
              + ' %8.2f' % actual.get(nm, float('nan')))

    if rows:
        with open(a.csv_out, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['file', 'name', 'dE00_raw'] + ['floor_%d' % n for n in levels] + ['dE00_after_lut'])
            w.writerows(rows)
        print('\n已写 %s' % os.path.relpath(a.csv_out, ROOT))

    print('\n判读：floor33 与「实际LUT」接近 ⇒ 后期到顶，差的是机内丢掉的信息；'
          '\n      floor33 明显低于它 ⇒ 还有空间，是拟合/密度的问题。')


if __name__ == '__main__':
    main()
