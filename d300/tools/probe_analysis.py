#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探针分析：测定工坊「与照相机兼容」引擎到底怎么执行 NCP 里的曲线。

基准 = NEF 内嵌 JPEG（机身自己的 STANDARD 渲染）。
上一轮已验证：不加曲线的导出与内嵌 JPEG 几乎一致（RMS 2.7），所以它可以当基准。

判读思路：
  T01 = 恒等曲线。若引擎忠实执行，输出应≈机身。
  T02 = 反相曲线。若是逐通道反相，饱和色相会翻转（粉→绿）。
"""
import os
import sys

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'D300_NCP'))
from cmp_ncp import read_ncp, lut_sample, to255  # noqa: E402


def load(p, W=960):
    im = Image.open(p).convert('RGB')
    if im.width != W:
        im = im.resize((W, round(im.height * W / im.width)), Image.LANCZOS)
    return np.asarray(im).astype(np.float32)


def luma(a):
    return a[..., 0] * .2126 + a[..., 1] * .7152 + a[..., 2] * .0722


def chroma(a):
    mx, mn = a.max(2), a.min(2)
    return np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)


def binned(x_in, y_out, edges):
    """按输入分档取中位数，返回 (档中心, 中位输出, 样本数)"""
    c, m, n = [], [], []
    for i in range(len(edges) - 1):
        sel = (x_in >= edges[i]) & (x_in < edges[i + 1])
        k = int(sel.sum())
        n.append(k)
        c.append((edges[i] + edges[i + 1]) / 2)
        m.append(float(np.median(y_out[sel])) if k > 200 else np.nan)
    return np.array(c), np.array(m), np.array(n)


def main():
    D = os.path.dirname(__file__)
    cam = load(os.path.join(D, 'NEF内嵌预览.jpg'))
    t1 = load(os.path.join(D, '原始/img17_t01.jpg'))
    t2 = load(os.path.join(D, '原始/img18_t02.jpg'))
    Lc, L1, L2 = luma(cam), luma(t1), luma(t2)

    print('=' * 66)
    print('A. T01 恒等曲线 —— 引擎是否忠实执行')
    print('=' * 66)
    edges = np.arange(0, 256, 16)
    xs, ys, ns = binned(Lc, L1, edges)
    print('%-8s %-9s %-9s %-8s' % ('机身值', 'T01 实测', '理想(恒等)', '偏差'))
    for x, y, n in zip(xs, ys, ns):
        if np.isnan(y):
            continue
        print('%-8.0f %-9.1f %-9.0f %+8.1f' % (x, y, x, y - x))

    # 中性像素上单独看（排除色彩影响）
    ch = chroma(cam)
    neutral = ch < 0.12
    print('\n只看中性像素（色度<0.12，占 %.0f%%）：' % (neutral.mean() * 100))
    xs2, ys2, _ = binned(Lc[neutral], L1[neutral], edges)
    for x, y in zip(xs2, ys2):
        if not np.isnan(y):
            print('   机身 %3.0f → T01 %5.1f  (%+.1f)' % (x, y, y - x))

    print()
    print('=' * 66)
    print('B. T02 反相曲线 —— 是否逐通道反相')
    print('=' * 66)
    # 用中性像素回答「通道是否各自反相」（中性像素不受色度保持影响）
    print('中性像素（灰阶部分）：')
    print('%-8s %-9s %-9s %-11s' % ('机身值', 'T02 实测', '理想255-x', '偏差'))
    xs3, ys3, _ = binned(Lc[neutral], L2[neutral], edges)
    for x, y in zip(xs3, ys3):
        if not np.isnan(y):
            print('%-8.0f %-9.1f %-9.1f %+11.1f' % (x, y, 255 - x, y - (255 - x)))

    # 饱和像素：如果逐通道反相，色相会翻转
    print('\n饱和像素（色度>0.35）的平均 RGB：')
    sat = ch > 0.35
    print('  占比 %.1f%%' % (sat.mean() * 100))
    print('  %-8s %-22s %-22s' % ('', '实测 RGB', '逐通道反相后应有'))
    for nm, a in (('机身', cam), ('T01', t1), ('T02', t2)):
        v = a[sat].mean(0)
        print('  %-8s (%5.1f,%5.1f,%5.1f)    (%5.1f,%5.1f,%5.1f)'
              % (nm, v[0], v[1], v[2], 255 - v[0], 255 - v[1], 255 - v[2]))

    # 具体到粉红上衣
    pink = (cam[..., 0] > 190) & (cam[..., 1] < 110) & (cam[..., 2] > 90) & (cam[..., 2] < 210)
    if pink.sum() > 300:
        print('\n粉红上衣（%d 像素）平均 RGB：' % pink.sum())
        for nm, a in (('机身', cam), ('T01', t1), ('T02', t2)):
            v = a[pink].mean(0)
            print('  %-6s (%5.1f,%5.1f,%5.1f)' % (nm, v[0], v[1], v[2]))
        print('  若逐通道反相应为 (%5.1f,%5.1f,%5.1f) → 是绿色'
              % tuple(255 - cam[pink].mean(0)))

    print()
    print('=' * 66)
    print('C. 与上一轮 PICCON29（标准·近恒等曲线）的偏差形状对照')
    print('=' * 66)
    p29 = load(os.path.join(D, '原始/img01.jpg'))
    Lp = luma(p29)
    xs4, ys4, _ = binned(Lc, Lp, edges)
    print('%-8s %-10s %-10s %-10s' % ('机身值', 'T01偏差', 'P29偏差', '两者差'))
    for x, a, b in zip(xs, ys - xs, ys4 - xs4):
        if not np.isnan(a) and not np.isnan(b):
            print('%-8.0f %+10.1f %+10.1f %+10.1f' % (x, a, b, b - a))

    # 探针自身的理想映射
    for f in ('T01_IDENT.NCP', 'T02_INVERT.NCP'):
        c = read_ncp(os.path.join(D, '..', 'D300_NCP', f))['curve']
        print('\n%s 设计映射 x=0,64,128,192,255 → %s'
              % (f, [round(to255(lut_sample(c['lut'], v))) for v in (0, 64, 128, 192, 255)]))


if __name__ == '__main__':
    main()
