#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chart_profile_bases.py —— 把 6 个底子的渲染结果并排放，肉眼可判。

为什么需要：sidecar 批量那套写法里，NX Studio 的「优化校准」栏显示的名字
**永远是第一张的名字**（第 38 字节/`<PictureControl>` 都沿用模板的 1），
所以六张 NEF 在信息栏里看着都叫 P0 STANDARD。名字不可信，但像素是可查的 ——
这个脚本就把像素摆出来：同一处 1:1 裁切 + 差值的 8 倍放大。

    python d300/tools/chart_profile_bases.py --dir ../_probe_profile
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
DEF = os.path.normpath(os.path.join(ROOT, '..', '_probe_profile'))

ORDER = [('P0_STANDARD', 'STANDARD 0x0001'),
         ('P1_PORTRAIT', 'PORTRAIT 0x0486'),
         ('P2_LANDSCAPE', 'LANDSCAPE 0x04C7'),
         ('P3_D2XMODE1', 'D2XMODE I 0x0014'),
         ('P4_D2XMODE2', 'D2XMODE II 0x03D5'),
         ('P5_D2XMODE3', 'D2XMODE III 0x00D6')]

BOX = 380          # 每格边长
ZOOM = 8           # 差值放大倍数
PANEL = (40, 52)   # 顶部留白画标签


def load(p):
    return np.asarray(Image.open(p).convert('RGB'), dtype=np.float64)


def crop(a, box):
    h, w = a.shape[:2]
    cy, cx = h // 2, w // 2
    y0, x0 = cy - box // 2, cx - box // 2
    return a[y0:y0 + box, x0:x0 + box]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default=DEF)
    ap.add_argument('--out', default=os.path.join(ROOT, 'charts', 'profile-bases.jpg'))
    a = ap.parse_args()

    ref = crop(load(os.path.join(a.dir, 'P0_STANDARD.JPG')), BOX)
    tiles = []
    for stem, label in ORDER:
        p = os.path.join(a.dir, stem + '.JPG')
        if not os.path.exists(p):
            continue
        img = crop(load(p), BOX)
        diff = np.clip((img - ref) * ZOOM + 128, 0, 255)
        tiles.append((label, img, diff))

    W = BOX * len(tiles)
    H = BOX * 2 + PANEL[1]
    sheet = Image.new('RGB', (W, H), (18, 18, 20))
    d = ImageDraw.Draw(sheet)
    for i, (label, img, diff) in enumerate(tiles):
        x = i * BOX
        sheet.paste(Image.fromarray(img.astype(np.uint8)), (x, PANEL[1]))
        sheet.paste(Image.fromarray(diff.astype(np.uint8)), (x, PANEL[1] + BOX))
        d.text((x + 10, 14), label, fill=(235, 235, 235))
        if i:
            m = float(np.abs(img - ref).mean())
            d.text((x + 10, 30), 'mean|diff| %.2f' % m, fill=(150, 200, 255))
    d.text((10, PANEL[1] + BOX - 22), '', fill=(200, 200, 200))
    d.text((10, H - 18), 'top: 1:1 crop   bottom: (img - STANDARD) x%d + 128   128 = identical'
           % ZOOM, fill=(160, 160, 160))

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    sheet.save(a.out, quality=92)
    print('%-16s %-22s %s' % ('探针', '标签', 'mean|diff| vs P0'))
    print('-' * 52)
    for i, (label, img, _) in enumerate(tiles):
        print('%-16s %-22s %6.2f' % (ORDER[i][0], label,
                                     float(np.abs(img - ref).mean())))
    print()
    print('→ %s  (%dx%d)' % (a.out, W, H))


if __name__ == '__main__':
    main()
