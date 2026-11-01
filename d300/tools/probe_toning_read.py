#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_toning_read.py —— 读调色浓度扫描包：每支选哪个浓度最贴官方。

    python tools/probe_toning_read.py --dir D:/Documents/Workbuddy/D300/_probe_toning

输入的 10 张由 `pack_toning_sweep.py` 生成，文件名形如 `01_SEPIA_81.JPG`
（`序号_滤镜_浓度`）。官方同帧渲染取 `samples/workshop/NN_滤镜.jpg` —— 同一张 DSC_3891，
所以可以直接比彩度。

输出三列：我们的 C\*、官方的 C\*、差（负 = 我们偏淡）。每支最后给一句"选哪个浓度"。
"""
import argparse
import csv
import glob
import os
import re
import sys

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
WORKSHOP = os.path.join(ROOT, 'samples', 'workshop')

SLOT = {'SEPIA': 13, 'BLUE': 14, 'RED': 15, 'PINK': 16}


def lab(rgb):
    c = rgb / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]], dtype=np.float32)
    t = (c @ m.T) / np.array([0.95047, 1.0, 1.08883], dtype=np.float32)
    d = 6.0 / 29.0
    f = np.where(t > d ** 3, np.cbrt(t), t / (3 * d * d) + 4.0 / 29.0)
    return 116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])


def load(path, size=None):
    im = Image.open(path).convert('RGB')
    if size is not None and im.size != size:
        im = im.resize(size, Image.LANCZOS)
    return np.asarray(im, dtype=np.float32)


def stats(rgb, mask):
    L, A, B = lab(rgb)
    C = np.hypot(A, B)
    return float(L[mask].mean()), float(C[mask].mean()), float(A[mask].mean()), float(B[mask].mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    a = ap.parse_args()

    fs = [f for f in glob.glob(os.path.join(a.dir, '*'))
          if os.path.splitext(f)[1].lower() in ('.jpg', '.jpeg')]
    rows = []
    for f in fs:
        m = re.match(r'^(\d+)_([A-Z]+)_([0-9A-F]{2})$', os.path.splitext(os.path.basename(f))[0].upper())
        if m:
            rows.append((int(m.group(1)), m.group(2), int(m.group(3), 16), f))
    if not rows:
        print('没找到形如 01_SEPIA_81.JPG 的文件')
        return 1
    rows.sort()

    print('%-6s %-7s %-4s %7s %7s %7s %7s %7s'
          % ('文件', '滤镜', '浓度', '我 C*', '官方 C*', 'ΔC*', 'Δa*', 'Δb*'))
    print('-' * 62)
    res = {}
    for idx, name, dens, f in rows:
        off_path = os.path.join(WORKSHOP, '%02d_%s.jpg' % (SLOT[name], name))
        if not os.path.exists(off_path):
            print('缺官方样片 %s' % off_path)
            return 1
        off = load(off_path)
        ours = load(f, size=(off.shape[1], off.shape[0]))
        mask = ((off.min(2) > 8) & (off.max(2) < 247) &
                (ours.min(2) > 8) & (ours.max(2) < 247))
        Lo, Co, ao, bo = stats(ours, mask)
        Lr, Cr, ar, br = stats(off, mask)
        res.setdefault(name, []).append((dens, Co, Cr, ao - ar, bo - br))
        print('%-6s %-7s 0x%02X %7.2f %7.2f %+7.2f %+7.2f %+7.2f'
              % ('%02d' % idx, name, dens, Co, Cr, Co - Cr, ao - ar, bo - br))

    print('\n' + '=' * 62)
    pick = {}
    for name, lst in res.items():
        best = min(lst, key=lambda t: abs(t[1] - t[2]))
        pick[name] = best[0]
        print('%-6s 官方 C*=%.2f ｜ ' % (name, lst[0][2])
              + '  '.join('0x%02X:%.2f(%+.2f)' % (d, c, c - r) for d, c, r, _, _ in lst)
              + '  → 选 0x%02X' % best[0])
    print('\n建议的改法（只动 offset 47）：')
    for name, d in pick.items():
        print('  PICCON%02d %-5s → 0x%02X' % (SLOT[name], name, d))

    out = os.path.join(a.dir, 'toning_sweep.csv')
    with open(out, 'w', encoding='utf-8-sig', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['filter', 'density', 'C_ours', 'C_official', 'dC', 'da', 'db'])
        for name, lst in res.items():
            for d, c, r, da, db in lst:
                w.writerow([name, '0x%02X' % d, round(c, 3), round(r, 3),
                            round(c - r, 3), round(da, 3), round(db, 3)])
    print('\n数据表：%s' % out)
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(main())
