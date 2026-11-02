#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""real_gap.py —— 真渲染口径：我们自己导出的 NCP 与官方最新 NP3 差多少。

为什么需要它
------------
`audit_release.py` / `diag_residual.py` 用的是「模型」口径：拿标准直出样片，
套上文件里存的曲线和滑块，算出预测图，再和官方 NP3 的样片比。
这条链有两个假设：① 机身直出 = 预测函数；② 我们只有一个线性色彩模型。

真渲染口径不需要任何假设：同一个 NEF，同一台机器，同一个 NX Studio，
一次套我们的 NCP 导出，一次套官方 NP3 导出，然后逐像素相减。
NX Studio 的 LUT 重插值、JPEG 编码、锐化全都两边同等对待，差出来的
就只剩「滤镜本身不一样」。

差别在哪里要讲清楚：
  · 模型口径 5.98 级 = 「我们的模型以为差 5.98」
  · 真渲染口径 X 级 = 「NX Studio 实际渲出来差 X」
两者应当接近；如果差得多，说明模型有系统偏差，那才是要修的东西。

    python tools/real_gap.py                       # 默认 real_v3 vs real_target
    python tools/real_gap.py --csv out.csv         # 顺带落一份 csv
    python tools/real_gap.py --size 0             # 0 = 不缩放，用原尺寸（慢）
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from diag_residual import to_lab, de2000, hz, CMIN, CLIP          # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
SAMP = os.path.join(ROOT, 'samples')
NAMES = ['DREAM', 'MORNING', 'POP', 'SUNDAY', 'SOMBER', 'DRAMA', 'SILENCE',
         'BLEACH', 'MELANCHOLIC', 'PURE', 'DENIM', 'TOY', 'SEPIA', 'BLUE',
         'RED', 'PINK', 'CHARCOAL', 'GRAPHITE', 'BINARY', 'CARBON', 'FLAT',
         'FLAT_MONOCHROME', 'DEEPTONE_MONOCHROME', 'RICH_TONE_PORTRAIT',
         'FLEXIBLE_COLOR', 'LANDSCAPE', 'MONOCHROME', 'NEUTRAL', 'STANDARD', 'VIVID']
MONO = {17, 18, 19, 20, 22, 23, 27}          # 磁盘上确实是单色的支


def load(path, size):
    im = Image.open(path).convert('RGB')
    if size:
        r = size / max(im.size)
        if r < 1.0:
            im = im.resize((max(1, int(round(im.width * r))),
                            max(1, int(round(im.height * r)))), Image.LANCZOS)
    return np.asarray(im, dtype=np.float64)


def find(d, slot, name, suf=''):
    """后缀大小写都不一定，按「编号_名字」前缀找；suf 用来区分 __O / __T 这种同源两份"""
    if not os.path.isdir(d):
        return None
    stem = '%02d_%s%s' % (slot, name, suf)
    for f in os.listdir(d):
        b, _ = os.path.splitext(f)
        if b.upper() == stem.upper():
            return os.path.join(d, f)
    return None


def one(pa, pb, size):
    a, b = load(pa, size), load(pb, size)
    if a.shape != b.shape:
        return None
    # 剪裁区不参与统计：两边都被机身/导出截断了，那一块的差异不反映滤镜
    m = ((a.min(2) > CLIP) & (a.max(2) < 255 - CLIP)
         & (b.min(2) > CLIP) & (b.max(2) < 255 - CLIP))
    if m.sum() < 5000:
        m = np.ones(a.shape[:2], bool)
    la, lb = to_lab(a[m]), to_lab(b[m])
    de = de2000(la, lb)
    ha, ca = hz(la)
    hb, cb = hz(lb)
    dh = (hb - ha + 180.0) % 360.0 - 180.0
    cm = (ca > CMIN) & (cb > CMIN)
    return dict(
        mad=float(np.abs(a - b).mean()),                       # 级：三通道平均绝对差
        de=float(de.mean()),
        jnd=float((de > 2.3).mean() * 100.0),
        dl=float(np.abs(la[:, 0] - lb[:, 0]).mean()),
        dc=float(np.abs(ca - cb).mean()),
        dcs=float((ca - cb).mean()),            # 带符号：<0 我方偏淡，>0 我方偏浓
        dls=float((la[:, 0] - lb[:, 0]).mean()),
        dh=float(np.nanmean(np.where(cm, np.abs(dh), np.nan))) if cm.any() else 0.0,
        clip=float(100.0 * (1.0 - m.mean())),
        px=int(m.sum()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--v3', default=os.path.join(SAMP, 'real_v3'))
    ap.add_argument('--target', default=os.path.join(SAMP, 'real_target'))
    ap.add_argument('--size', type=int, default=420)
    ap.add_argument('--csv', default=None)
    a = ap.parse_args()

    rows, miss = [], []
    for slot, name in enumerate(NAMES, 1):
        pa, pb = find(a.v3, slot, name), find(a.target, slot, name)
        if not pa or not pb:
            miss.append((slot, name, '我方缺失' if not pa else '目标侧无 NP3'))
            continue
        r = one(pa, pb, a.size)
        if r is None:
            miss.append((slot, name, '尺寸不一致'))
            continue
        r.update(slot=slot, name=name, mono=slot in MONO)
        rows.append(r)

    print('真渲染口径 —— 我方 NCP vs 官方最新 NP3')
    print('同底片、同机、同 NX Studio、同尺寸 %s' % ('原尺寸' if not a.size else '%dpx 长边' % a.size))
    print()
    print('%3s %-20s %5s %7s %6s %6s %6s %6s %5s'
          % ('#', '滤镜', '类型', '级', 'dE00', '可辨%', '|dL*|', '|dC*|', 'dH°'))
    print('-' * 80)
    for r in rows:
        print('%3d %-20s %5s %7.3f %6.2f %6.1f %6.2f %6.2f %5.2f'
              % (r['slot'], r['name'], '单色' if r['mono'] else '彩色',
                 r['mad'], r['de'], r['jnd'], r['dl'], r['dc'], r['dh']))
    print('-' * 80)

    def avg(sel):
        return {k: float(np.mean([r[k] for r in sel]))
                for k in ('mad', 'de', 'jnd', 'dl', 'dc', 'dh')}

    allm, colm, monm = avg(rows), avg([r for r in rows if not r['mono']]), avg([r for r in rows if r['mono']])
    print('%3s %-20s %5s %7.3f %6.2f %6.1f %6.2f %6.2f %5.2f'
          % ('', '全部 %d 支' % len(rows), '', allm['mad'], allm['de'], allm['jnd'],
             allm['dl'], allm['dc'], allm['dh']))
    print('%3s %-20s %5s %7.3f %6.2f %6.1f %6.2f %6.2f %5.2f'
          % ('', '  彩色 %d 支' % len(colm and [r for r in rows if not r['mono']]), '',
             colm['mad'], colm['de'], colm['jnd'], colm['dl'], colm['dc'], colm['dh']))
    print('%3s %-20s %5s %7.3f %6.2f %6.1f %6.2f %6.2f %5.2f'
          % ('', '  单色 %d 支' % len([r for r in rows if r['mono']]), '',
             monm['mad'], monm['de'], monm['jnd'], monm['dl'], monm['dc'], monm['dh']))

    if miss:
        print()
        print('未参与（%d 支）：' % len(miss))
        for slot, name, why in miss:
            print('  %02d %-22s %s' % (slot, name, why))

    if a.csv:
        with open(a.csv, 'w', encoding='utf-8-sig') as f:
            f.write('slot,name,type,mad,dE00,jnd_pct,dL,dC,dC_signed,dL_signed,dH,clip_pct\n')
            for r in rows:
                f.write('%d,%s,%s,%.4f,%.4f,%.2f,%.4f,%.4f,%.4f,%.4f,%.4f,%.2f\n'
                        % (r['slot'], r['name'], 'mono' if r['mono'] else 'color',
                           r['mad'], r['de'], r['jnd'], r['dl'], r['dc'],
                           r['dcs'], r['dls'], r['dh'], r['clip']))
        print()
        print('csv -> %s' % a.csv)


if __name__ == '__main__':
    main()
