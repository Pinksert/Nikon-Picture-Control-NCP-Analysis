#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_read.py —— 读「新底片验证批次」，判断拟合是学到了规律还是记住了图。

判读的三条线
------------
1. **机内这一环**：同一张新底片上，我们的 NCP 与官方 NP3 差多少（ΔE00），
   与 DSC_4484 上的同一支比。若数量级相当 ⇒ 曲线/底子这套是规律；
   若新底片普遍翻倍 ⇒ 是在 4484 的直方图上凑出来的。
2. **后期这一环**：把 `lut/NN_名字.cube` 套到我们的成片上，看差距是否同样收敛。
   LUT 是在 4484 的 RGB 三元组上拟合的，换图还能收敛才是真的可迁移。
3. **批次是否生效**：`00_PLAIN` 与 `__T` 必须明显不同，否则说明 sidecar 没被读
   （症状是 52 张全一样，历史上踩过一次，是扫描时序）。

    python tools/validate_read.py --dir ../_validate_nef/8981
    python tools/validate_read.py --dir ../_validate_nef/8981 --size 700 --csv out.csv
"""
import argparse
import csv
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from diag_residual import to_lab, de2000, hz, CMIN, CLIP      # noqa: E402
from lut_fit import read_cube, apply_cube                     # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
SAMP = os.path.join(ROOT, 'samples')
LUTD = os.path.join(ROOT, 'lut')
META = os.path.join(SAMP, 'metrics_real.csv')
BASEO = os.path.join(SAMP, 'real_v3')          # 4484 上「我们」的成片
BASET = os.path.join(SAMP, 'real_target')      # 4484 上「官方」的成片


def load(path, size):
    im = Image.open(path).convert('RGB')
    if size:
        r = size / max(im.size)
        if r < 1.0:
            im = im.resize((max(1, int(round(im.width * r))),
                            max(1, int(round(im.height * r)))), Image.LANCZOS)
    return np.asarray(im, dtype=np.float64)


def metric(a, b):
    """与 real_gap.one 同一口径：剪裁区不参与 dE00，级差算全画面。"""
    if a.shape != b.shape:
        g = (min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1]))
        a, b = a[:g[0], :g[1]], b[:g[0], :g[1]]
    m = ((a.min(2) > CLIP) & (a.max(2) < 255 - CLIP)
         & (b.min(2) > CLIP) & (b.max(2) < 255 - CLIP))
    if m.sum() < 5000:
        m = np.ones(a.shape[:2], bool)
    la, lb = to_lab(a[m]), to_lab(b[m])
    return dict(mad=float(np.abs(a - b).mean()),
                de=float(de2000(la, lb).mean()),
                jnd=float((de2000(la, lb) > 2.3).mean() * 100.0),
                clip=float(100.0 * (1.0 - m.mean())))


def find(d, stem):
    if not os.path.isdir(d):
        return None
    for f in os.listdir(d):
        b, _ = os.path.splitext(f)
        if b.upper() == stem.upper():
            return os.path.join(d, f)
    return None


def cube_path(name):
    p = os.path.join(LUTD, '%02d_%s.cube' % (0, name))
    cands = [f for f in os.listdir(LUTD) if f.upper().endswith('.CUBE')
             and name.upper() in f.upper()]
    return os.path.join(LUTD, cands[0]) if cands else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--size', type=int, default=420)
    ap.add_argument('--csv', default=None)
    ap.add_argument('--no-lut', action='store_true')
    ap.add_argument('--ref-o', default=None,
                    help='上一批导出目录，用来核对两次导出设置是否一致（比对 O 侧）')
    a = ap.parse_args()

    order = [(int(r['slot']), r['name'])
             for r in csv.DictReader(open(META, encoding='utf-8-sig'))]

    rows, miss = [], []
    for slot, name in order:
        po = find(a.dir, '%02d_%s__O' % (slot, name))
        pt = find(a.dir, '%02d_%s__T' % (slot, name))
        if not po or not pt:
            miss.append((slot, name, '缺我方' if not po else '缺官方'))
            continue
        O, T = load(po, a.size), load(pt, a.size)
        r = metric(O, T)
        r.update(slot=slot, name=name)

        # 4484 基线：同一段代码、同一尺寸；LUT 也现场重算，保证两边用的是同一份 cube
        bo = find(BASEO, '%02d_%s' % (slot, name))
        bt = find(BASET, '%02d_%s' % (slot, name))
        r['de_4484'] = r['de_lut_4484'] = float('nan')
        if bo and bt:
            BO, BT = load(bo, a.size), load(bt, a.size)
            r['de_4484'] = metric(BO, BT)['de']
            cp0 = cube_path(name)
            if cp0 and os.path.exists(cp0):
                r['de_lut_4484'] = metric(apply_cube(BO, read_cube(cp0), 33), BT)['de']

        if not a.no_lut:
            cp = cube_path(name)
            if cp and os.path.exists(cp):
                r['de_lut'] = metric(apply_cube(O, read_cube(cp), 33), T)['de']
                r['lut'] = os.path.basename(cp)
            else:
                r['de_lut'] = float('nan')
        rows.append(r)

    print('新底片验证 —— 同一张 NEF，套我们的 NCP（O）与官方 NP3（T）各导一次')
    print('长边 %dpx，dE00 口径与 samples/metrics_real.csv 完全一致' % a.size)
    print()
    print('%3s %-12s %9s %8s %7s %9s %7s' %
          ('#', '滤镜', 'dE00@4484', 'dE00@新', '倍率', 'LUT:4484→新', 'LUT收益'))
    print('-' * 68)
    for r in rows:
        ratio = r['de'] / r['de_4484'] if r['de_4484'] > 1e-9 else float('nan')
        lb, ln = r.get('de_lut_4484', float('nan')), r.get('de_lut', float('nan'))
        gain_b = (1 - lb / r['de_4484']) * 100 if r['de_4484'] > 1e-9 else float('nan')
        gain_n = (1 - ln / r['de']) * 100 if r['de'] > 1e-9 else float('nan')
        print('%3d %-12s %9.2f %8.2f %6.2fx %5.2f→%-5.2f %6.0f%%/%3.0f%%'
              % (r['slot'], r['name'], r['de_4484'], r['de'], ratio, lb, ln, gain_b, gain_n))
    print('-' * 68)

    def mean(k, sel=None):
        v = [r[k] for r in (sel or rows) if r.get(k) is not None and not np.isnan(r[k])]
        return float(np.mean(v)) if v else float('nan')

    col = [r for r in rows if r['name'] not in
           ('CHARCOAL', 'GRAPHITE', 'BINARY', 'CARBON', 'MONOCHROME')]
    mono = [r for r in rows if r not in col]
    for lab, sel in (('全部', rows), ('彩色', col), ('单色', mono)):
        b, n = mean('de_4484', sel), mean('de', sel)
        lb, ln = mean('de_lut_4484', sel), mean('de_lut', sel)
        print('%s %2d 支  机内 %.2f → %.2f（%.2fx）   '
              '加 LUT %.2f → %.2f（收益 %.0f%% → %.0f%%）'
              % (lab, len(sel), b, n, n / b, lb, ln,
                 (1 - lb / b) * 100, (1 - ln / n) * 100))

    # 批次体检：PLAIN 锚点 + 各 T 之间必须互不相同 + 与上一批 O 的一致性
    pp = find(a.dir, '00_PLAIN')
    if pp and rows:
        P = load(pp, a.size)
        pm = P.reshape(-1, 3).mean(0)
        t0 = find(a.dir, '%02d_%s__T' % (rows[0]['slot'], rows[0]['name']))
        o0 = find(a.dir, '%02d_%s__O' % (rows[0]['slot'], rows[0]['name']))
        print()
        print('体检一（sidecar 是否生效）：')
        same = 0
        for r in rows:
            ft = find(a.dir, '%02d_%s__T' % (r['slot'], r['name']))
            dm = float(np.abs(load(ft, a.size).reshape(-1, 3).mean(0) - pm).max())
            if dm < 1.0:
                same += 1
                print('   ✗ %-12s 与 PLAIN 的 RGB 均值只差 %.2f 级 → 滤镜没套上' % (r['name'], dm))
        print('   %s：26 个官方渲染里 %d 个与「不套滤镜」相同（应为 0）'
              % ('通过' if same == 0 else '未通过', same))
        if t0 and o0:
            d_pt = metric(P, load(t0, a.size))['de']
            d_po = metric(P, load(o0, a.size))['de']
            print('   PLAIN vs 官方 %s = %.2f 级；PLAIN vs 我们 %s = %.2f 级'
                  % (rows[0]['name'], d_pt, rows[0]['name'], d_po))

    if a.ref_o:
        print('\n体检二（两次导出设置是否一致）：')
        ds = []
        for r in rows:
            f1 = find(a.dir, '%02d_%s__O' % (r['slot'], r['name']))
            f2 = find(a.ref_o, '%02d_%s__O' % (r['slot'], r['name']))
            if not f2:
                continue
            ds.append((r['name'], float(np.abs(load(f1, a.size)
                                               - load(f2, a.size)).mean())))
        if ds:
            for n, d in ds:
                print('   %-12s 新 vs 上一批 O：%.3f 级%s'
                      % (n, d, '' if d < 0.5 else '  ← 偏大，导出设置可能变了'))
            print('   最大 %.3f 级：%s' % (max(d for _, d in ds),
                                       '通过' if max(d for _, d in ds) < 0.5 else '未通过'))

    if miss:
        print('\n未参与 %d 支：%s' % (len(miss), miss))

    if a.csv:
        with open(a.csv, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['slot', 'name', 'dE00_4484', 'dE00_new', 'ratio',
                        'dE00_lut_4484', 'dE00_lut_new', 'lut'])
            for r in rows:
                w.writerow([r['slot'], r['name'], '%.4f' % r['de_4484'], '%.4f' % r['de'],
                            '%.3f' % (r['de'] / r['de_4484']),
                            '%.4f' % r.get('de_lut_4484', float('nan')),
                            '%.4f' % r.get('de_lut', float('nan')), r.get('lut', '')])
        print('\nCSV → %s' % a.csv)


if __name__ == '__main__':
    main()
