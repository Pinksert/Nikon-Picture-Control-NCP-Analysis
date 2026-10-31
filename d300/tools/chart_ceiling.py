# -*- coding: utf-8 -*-
"""chart_ceiling.py —— 把「为什么调不动了」画成一张图。

机身能给的色彩自由度是一个**全局彩度倍率**（外加一个全局色相角），
也就是图上一条**水平线**。而目标（最新优化校准）要的是随亮度/彩度变的一条**曲线**。
两条东西不可能重合 —— 这就是天花板。
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import optimize_v2 as A                                   # noqa: E402
import probe_color_ceiling as P                           # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
FONT = 'C:/Windows/Fonts/msyh.ttc'
SLOTS = [1, 2, 11, 10, 29]          # DREAM / MORNING / DENIM / PURE / STANDARD（对照）
COL = [(232, 90, 60), (60, 130, 200), (110, 170, 70), (190, 100, 190), (150, 150, 150)]
W, H = 980, 560
L, R_, T, B = 92, 40, 96, 92


def f(sz):
    return ImageFont.truetype(FONT, sz)


def main():
    im = Image.new('RGB', (W, H), (255, 255, 255))
    dr = ImageDraw.Draw(im)
    dr.text((26, 20), '目标要的是「随亮度变的彩度曲线」，机身只能给一条水平线',
            font=f(22), fill=(20, 20, 20))
    dr.text((26, 52), '横轴＝画面亮度分 8 段（暗→亮），纵轴＝这一段「最贴合原版」需要的彩度倍率；'
                      '虚线＝机身真正能写进去的那个全局倍率',
            font=f(14), fill=(110, 110, 110))

    pw, ph = W - L - R_, H - T - B

    # 先扫一遍所有曲线段，纵轴上限取“能容下最高点”的 0.25 整数倍，
    # 否则像 DENIM 第一段（约 2.1×）会画出画布
    peak = 1.0
    segs = {}
    for slot in SLOTS:
        p = P.parts(slot)
        seg = P.segments(p, p['kind'], 'L', 8)
        segs[slot] = (p, seg)
        if len(seg) >= 3:
            peak = max(peak, max(s[1] for s in seg), A.SAT_STEP ** p['n'])
    y0, y1 = 0.25, float(np.ceil(peak * 4) / 4 + 0.05)
    yy = lambda v: T + ph - (v - y0) / (y1 - y0) * ph
    xx = lambda i, n: L + (i + 0.5) / n * pw

    # 网格线跳过 1.00（那条由下面的基线单独画 + 标注，避免两处文字叠在一起）
    v = y0
    while v <= y1 + 1e-9:
        if abs(v - 1.0) > 1e-6:
            y = yy(v)
            dr.line([(L, y), (L + pw, y)], fill=(232, 232, 232))
            dr.text((L - 52, y - 8), '%.2f×' % v, font=f(13), fill=(90, 90, 90))
        v += 0.25
    dr.line([(L, yy(1.0)), (L + pw, yy(1.0))], fill=(190, 190, 190), width=2)
    dr.text((L - 56, yy(1.0) - 8), '1.00×', font=f(13), fill=(60, 60, 60))
    dr.line([(L, T), (L, T + ph)], fill=(120, 120, 120))
    dr.line([(L, T + ph), (L + pw, T + ph)], fill=(120, 120, 120))
    dr.text((L, T + ph + 12), '暗部', font=f(14), fill=(80, 80, 80))
    dr.text((L + pw - 34, T + ph + 12), '亮部', font=f(14), fill=(80, 80, 80))

    for si, slot in enumerate(SLOTS):
        p, seg = segs[slot]
        if len(seg) < 3:
            continue
        xs = [xx(i, len(seg)) for i in range(len(seg))]
        ys = [yy(s[1]) for s in seg]
        c = COL[si]
        for i in range(len(xs) - 1):
            dr.line([(xs[i], ys[i]), (xs[i + 1], ys[i + 1])], fill=c, width=3)
        for x, y in zip(xs, ys):
            dr.ellipse([x - 3, y - 3, x + 3, y + 3], fill=c)
        # 机身能给的全局倍率（当前档位）
        g = A.SAT_STEP ** p['n']
        dr.line([(L, yy(g)), (L + pw, yy(g))], fill=c, width=1)
        lbl = '%s %s' % (A.NAMES[slot - 1], A.CN[slot - 1])
        # 图例放右上角：DENIM 首段 2.2× 顶在左上，左上角不能再放字
        dr.text((L + pw - 560 + (si % 3) * 190, T + 6 + (si // 3) * 24),
                '—— ' + lbl, font=f(14), fill=c)

    dr.text((L, T + ph + 38),
            '实线＝每段理论最优；同色虚线＝现在写进文件的那个倍率。'
            '差得越远，越说明不是没调好，是格式只有这么一个自由度。',
            font=f(13), fill=(70, 70, 70))
    dr.text((L, T + ph + 62),
            '注：STANDARD（灰）两条几乎重合 —— 越是平淡的滤镜越追得上；'
            'DREAM / MORNING / DENIM / PURE 这类有强烈色彩个性的，追不上。',
            font=f(13), fill=(120, 120, 120))

    out = os.path.join(ROOT, 'charts', 'color-ceiling.jpg')
    im.save(out, 'JPEG', quality=92)
    print('图：%s' % out)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
