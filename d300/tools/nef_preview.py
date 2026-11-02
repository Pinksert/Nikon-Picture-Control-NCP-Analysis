#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""nef_preview.py —— 从 NEF 里抽出内嵌的 JPEG 预览，用来「看片选样」。

没有 rawpy 也能用：NEF 是 TIFF 容器，尼康在里面塞了一张全尺寸 JPEG 预览
（MakerNote 的 PreviewIFD）。这里不解析 IFD，直接扫全文件的 JPEG 头
（FFD8FFxx），把能解码、且面积最大的那张拿出来 —— 对 D300 实测就是 4288×2848。

用法：
    python tools/nef_preview.py --dir "D:/某目录" --limit 12 --out .workbuddy/tmp/pv
    python tools/nef_preview.py --file a.NEF --out .workbuddy/tmp/pv
带 --sheet 会拼一张带文件名的联系表。
"""
import argparse
import io
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT = 'C:/Windows/Fonts/msyh.ttc'


def embedded_jpeg(path):
    """返回 NEF 内最大的一张可解码 JPEG（bytes），失败返回 None。"""
    data = open(path, 'rb').read()
    best, best_px = None, 0
    i = 0
    n = len(data)
    while True:
        i = data.find(b'\xff\xd8\xff', i)
        if i < 0:
            break
        # 候选片段：从 SOI 到下一个 EOI
        j = data.find(b'\xff\xd9', i + 3)
        if j > 0:
            seg = data[i:j + 2]
            if len(seg) > 20000:                    # 缩略图太小，跳过
                try:
                    im = Image.open(io.BytesIO(seg))
                    im.load()
                    px = im.size[0] * im.size[1]
                    if px > best_px:
                        best, best_px = seg, px
                except Exception:
                    pass
            i = j + 2
        else:
            break
    return best


def thumb(path, long_side=560):
    seg = embedded_jpeg(path)
    if seg is None:
        return None
    im = Image.open(io.BytesIO(seg)).convert('RGB')
    w, h = im.size
    s = long_side / max(w, h)
    return im.resize((int(w * s), int(h * s)), Image.LANCZOS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--file')
    ap.add_argument('--dir')
    ap.add_argument('--pattern', default='*.NEF')
    ap.add_argument('--limit', type=int, default=0, help='每隔 N 个取一张；0=全取')
    ap.add_argument('--out', required=True)
    ap.add_argument('--sheet', action='store_true')
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    if a.file:
        files = [a.file]
    else:
        import glob
        files = sorted(glob.glob(os.path.join(a.dir, a.pattern)))
        if a.limit and len(files) > a.limit:
            step = len(files) / float(a.limit)
            files = [files[int(k * step)] for k in range(a.limit)]

    tiles = []
    for p in files:
        try:
            t = thumb(p)
        except Exception as e:
            print('X %s %s' % (os.path.basename(p), e))
            continue
        if t is None:
            print('X %s 没有内嵌预览' % os.path.basename(p))
            continue
        name = os.path.splitext(os.path.basename(p))[0]
        dst = os.path.join(a.out, name + '.jpg')
        t.save(dst, 'JPEG', quality=88)
        tiles.append((name, t, dst))
        print('• %-14s %dx%d → %s' % (name, t.size[0], t.size[1], dst))

    if a.sheet and tiles:
        W = 4
        tw = max(t.size[0] for _, t, _ in tiles)
        th = max(t.size[1] for _, t, _ in tiles)
        rows = (len(tiles) + W - 1) // W
        pad, cap = 10, 26
        sheet = Image.new('RGB', (W * (tw + pad) + pad, rows * (th + cap + pad) + pad),
                          (24, 24, 26))
        dr = ImageDraw.Draw(sheet)
        f = ImageFont.truetype(FONT, 15)
        for k, (name, t, _) in enumerate(tiles):
            c, r = k % W, k // W
            x = pad + c * (tw + pad)
            y = pad + r * (th + cap + pad)
            sheet.paste(t, (x, y))
            dr.text((x + 2, y + th + 4), name, font=f, fill=(230, 230, 230))
        dst = os.path.join(a.out, '_sheet.jpg')
        sheet.save(dst, 'JPEG', quality=92)
        print('联系表 → %s' % dst)


if __name__ == '__main__':
    main()
