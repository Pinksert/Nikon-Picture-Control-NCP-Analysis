#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""filter_character.py —— 量每支滤镜"自己长什么样"，而不是"我们像不像"。

前面的第 13、14 节都在算「我们的 NCP 与原版的差」。这个脚本反过来：
把 30 张**原版**渲染（`samples/workshop/`）逐支和**原版 STANDARD**（槽 29）相减，
得到每支滤镜自己的位移量 —— 亮度、暗/中/高三分段的形状、彩度、色偏、反差。

这样得到的是一张"性格表"：哪些是低饱和、哪些是压暗部、哪些是加暖罩。
挑选滤镜时用它，评价还原度时用第 13/14 节。

    python tools/filter_character.py            # 算指标 + 出图

产物：
    samples/filter_character.csv                30 行指标
    charts/filter-character.jpg                 性格散点图（彩度 × 亮度位移）

口径：CIELAB（D65），遮罩取两张图都不溢出的像素（8 < min(RGB)、max(RGB) < 247），
同一批像素同时用于两张图，避免"换遮罩"造成的假差异（见 docs/14 第六节）。
"""
import csv
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

Image.MAX_IMAGE_PIXELS = None

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
SAMP = os.path.join(ROOT, 'samples', 'workshop')
OUT_CSV = os.path.join(ROOT, 'samples', 'filter_character.csv')
OUT_IMG = os.path.join(ROOT, 'charts', 'filter-character.jpg')
FONT_C = 'C:/Windows/Fonts/msyh.ttc'
FONT_B = 'C:/Windows/Fonts/msyhbd.ttc'

BASE_SLOT = 29          # STANDARD

NAMES = [
    'DREAM', 'MORNING', 'POP', 'SUNDAY', 'SOMBER', 'DRAMA', 'SILENCE', 'BLEACH',
    'MELANCHOLIC', 'PURE', 'DENIM', 'TOY', 'SEPIA', 'BLUE', 'RED', 'PINK',
    'CHARCOAL', 'GRAPHITE', 'BINARY', 'CARBON', 'FLAT', 'FLAT_MONOCHROME',
    'DEEPTONE_MONOCHROME', 'RICH_TONE_PORTRAIT', 'FLEXIBLE_COLOR', 'LANDSCAPE',
    'MONOCHROME', 'NEUTRAL', 'STANDARD', 'VIVID',
]
CN = [
    '梦幻', '清晨', '流行', '星期天', '低沉', '戏剧', '静寂', '漂白',
    '忧郁', '纯净', '牛仔布', '玩具', '棕褐色', '蓝色', '红色', '粉色',
    '木炭', '石墨', '双色', '黑碳', '平面', '平面单色', '深色调单色',
    '丰富色调人像', '灵活颜色', '风景', '单色', '自然', '标准', '鲜艳',
]


def path_of(slot):
    return os.path.join(SAMP, '%02d_%s.jpg' % (slot, NAMES[slot - 1]))


def load_rgb(p):
    return np.asarray(Image.open(p).convert('RGB'), dtype=np.float32)


def to_lab(rgb):
    c = rgb / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]], dtype=np.float32)
    xyz = c @ m.T
    t = xyz / np.array([0.95047, 1.0, 1.08883], dtype=np.float32)
    d = 6.0 / 29.0
    f = np.where(t > d ** 3, np.cbrt(t), t / (3 * d * d) + 4.0 / 29.0)
    L = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return L, a, b


def measure(fg, bg):
    """fg / bg: float32 HxWx3 0–255。返回该滤镜相对 STANDARD 的位移。"""
    n = fg.shape
    mask = (fg.min(2) > 8) & (fg.max(2) < 247) & (bg.min(2) > 8) & (bg.max(2) < 247)
    if mask.sum() < 20000:                     # 单色 + 极端曲线时兜底放宽
        mask = np.ones(n[:2], bool)

    Lf, af, bf = to_lab(fg)
    Lb, ab, bb = to_lab(bg)
    Cf = np.hypot(af, bf)
    Cb = np.hypot(ab, bb)

    dL = float((Lf[mask] - Lb[mask]).mean())
    zones = []
    for lo, hi in ((0, 33), (33, 66), (66, 100.1)):
        z = mask & (Lb >= lo) & (Lb < hi)
        zones.append(float((Lf[z] - Lb[z]).mean()) if z.sum() > 3000 else float('nan'))

    # 彩度倍率必须「对齐亮度」再比：C* 本身随 L* 变化，直接取全图均值会把
    # 「压暗」误读成「降饱和」（DRAMA 就这样被算成 0.33×）。
    # 做法：按基准亮度分 8 档，逐档算 Cf/Cb，取按像素数加权的中位数。
    bins = np.linspace(0, 100, 9)
    ratios, weights = [], []
    for i in range(8):
        z = mask & (Lb >= bins[i]) & (Lb < bins[i + 1])
        if z.sum() < 4000:
            continue
        cb = Cb[z].mean()
        if cb < 1.0:
            continue
        ratios.append(Cf[z].mean() / cb)
        weights.append(int(z.sum()))
    c_ratio = float(np.median(ratios)) if ratios else 1.0

    # 色偏：sRGB 三通道均值的相对位移，等价于白平衡的整体偏移
    mf, mb = fg.reshape(-1, 3)[mask.ravel()].mean(0), bg.reshape(-1, 3)[mask.ravel()].mean(0)
    cast_rb = float((mf[0] - mf[2]) - (mb[0] - mb[2]))
    cast_gb = float((mf[1] - mf[2]) - (mb[1] - mb[2]))

    p1f, p99f = np.percentile(Lf[mask], [1, 99])
    p1b, p99b = np.percentile(Lb[mask], [1, 99])
    return {
        'dL': dL,
        'dL_shadow': zones[0], 'dL_mid': zones[1], 'dL_high': zones[2],
        'dL_range': float(zones[2] - zones[0]) if not np.isnan(zones[0]) else float('nan'),
        'chroma_ratio': c_ratio,
        'cast_rb': cast_rb, 'cast_gb': cast_gb,
        'black': float(p1f - p1b), 'white': float(p99f - p99b),
        'contrast': float((p99f - p1f) / max(p99b - p1b, 1.0)),
        'mono': bool(Cf[mask].mean() < 3.0),
    }


def build():
    bg = load_rgb(path_of(BASE_SLOT))
    rows = []
    for slot in range(1, 31):
        fg = load_rgb(path_of(slot))
        m = measure(fg, bg)
        m.update(slot=slot, en=NAMES[slot - 1], cn=CN[slot - 1])
        rows.append(m)
        print('%2d %-20s ΔL%+6.1f  暗%+5.1f 中%+5.1f 高%+5.1f  彩度 %.2f×  色偏 %+5.1f'
              % (slot, m['en'], m['dL'], m['dL_shadow'], m['dL_mid'], m['dL_high'],
                 m['chroma_ratio'], m['cast_rb']))

    cols = ['slot', 'en', 'cn', 'mono', 'dL', 'dL_shadow', 'dL_mid', 'dL_high', 'dL_range',
            'chroma_ratio', 'cast_rb', 'cast_gb', 'black', 'white', 'contrast']
    with open(OUT_CSV, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(r[k], 3) if isinstance(r[k], float) else r[k]) for k in cols})
    print('\n数据表：%s' % OUT_CSV)
    return rows


# ---------------------------------------------------------------- 出图

def font(size, bold=False):
    return ImageFont.truetype(FONT_B if bold else FONT_C, size)


def chart(rows):
    """哑铃图：一行一支，左panel 亮度的暗/高两点 + 均值点，右panel 彩度倍率。"""
    RH, TOP = 23, 132
    N = len(rows)
    W = 1250
    H = TOP + N * RH + 96
    cv = Image.new('RGB', (W, H), (252, 252, 253))
    dr = ImageDraw.Draw(cv)
    dr.text((34, 26), '30 支滤镜的性格：相对「标准」的亮度、彩度与色偏',
            font=font(26, True), fill=(28, 30, 34))
    dr.text((34, 60), '同一张照片、同一批像素；全部数据取自尼康工坊「最新优化校准」的导出成片',
            font=font(14), fill=(120, 124, 130))

    # 面板 A：亮度哑铃
    A0, A1 = 330, 690
    B0, B1 = 760, 1000
    C0 = 1020
    y0, y1 = -26, 26

    def ax(v):
        return A0 + (A1 - A0) * (min(max(v, y0), y1) - y0) / (y1 - y0)

    dr.text((A0, TOP - 44), '影调：暗部 → 高光 落在哪里', font=font(14, True), fill=(70, 74, 80))
    dr.text((A0 - 4, TOP - 22), '线 = 从暗部位移到高光位移（线的斜率就是反差变化）',
            font=font(11), fill=(150, 154, 160))
    for v in range(-20, 21, 10):
        x = ax(v)
        dr.line([x, TOP - 4, x, TOP + N * RH - 4], fill=(236, 237, 240), width=1)
        dr.text((x, TOP + N * RH + 2), '%+d' % v, font=font(11), fill=(140, 144, 150), anchor='ma')
    xa = ax(0)
    dr.line([xa, TOP - 4, xa, TOP + N * RH - 4], fill=(196, 199, 205), width=1)
    dr.text((A0, TOP + N * RH + 32), '← 更暗', font=font(11), fill=(150, 154, 160))
    dr.text((A1, TOP + N * RH + 32), '更亮 →', font=font(11), fill=(150, 154, 160), anchor='ra')

    # 面板 B：彩度
    c0, c1 = 0.0, 2.4
    dr.text((B0, TOP - 44), '彩度倍率', font=font(14, True), fill=(70, 74, 80))
    dr.text((B0 - 4, TOP - 22), '1.00 = 与标准同浓', font=font(11), fill=(150, 154, 160))

    def bx(v):
        return B0 + (B1 - B0) * (min(max(v, c0), c1) - c0) / (c1 - c0)

    for v in (0.5, 1.0, 1.5, 2.0):
        x = bx(v)
        dr.line([x, TOP - 4, x, TOP + N * RH - 4],
                fill=(196, 199, 205) if v == 1.0 else (236, 237, 240), width=1)
        dr.text((x, TOP + N * RH + 2), '%.1f' % v, font=font(11), fill=(140, 144, 150), anchor='ma')

    dr.text((C0, TOP - 44), '色偏 R−B', font=font(14, True), fill=(70, 74, 80))
    dr.text((C0 - 4, TOP - 22), '正 = 偏暖　负 = 偏冷', font=font(11), fill=(150, 154, 160))

    for i, r in enumerate(rows):
        yc = TOP + i * RH + 10
        if i % 2 == 0:
            dr.rectangle([26, yc - 10, W - 26, yc + 11], fill=(247, 248, 250))
        name = '%02d %s' % (r['slot'], r['en'])
        dr.text((34, yc - 8), name, font=font(13), fill=(44, 48, 54))
        dr.text((36 + dr.textlength(name, font=font(13)) + 8, yc - 7), r['cn'],
                font=font(11), fill=(146, 150, 156))

        # 哑铃
        s, h, m = r['dL_shadow'], r['dL_high'], r['dL']
        warm = r['cast_rb'] > 3
        cool = r['cast_rb'] < -3
        col = (200, 116, 48) if warm else ((58, 110, 176) if cool else (96, 100, 108))
        if not (np.isnan(s) or np.isnan(h)):
            dr.line([ax(s), yc, ax(h), yc], fill=(206, 210, 218), width=3)
            dr.ellipse([ax(s) - 3, yc - 3, ax(s) + 3, yc + 3], fill=(176, 181, 190))
            dr.ellipse([ax(h) - 3, yc - 3, ax(h) + 3, yc + 3], fill=(176, 181, 190))
        dr.ellipse([ax(m) - 5, yc - 5, ax(m) + 5, yc + 5], fill=col)

        # 彩度
        cr = r['chroma_ratio']
        if r['mono']:
            dr.rectangle([B0 + 1, yc - 4, bx(c0) + 6, yc + 4], fill=(206, 210, 218))
            dr.text((bx(0) + 12, yc - 7), '单色', font=font(11), fill=(150, 154, 160))
        else:
            dr.rectangle([bx(1.0), yc - 4, bx(cr) if cr >= 1 else bx(1.0), yc + 4],
                         fill=col if cr >= 1 else (150, 154, 162))
            dr.text((bx(max(cr, 1.0)) + 6, yc - 7), '%.2f×' % cr, font=font(11), fill=(90, 94, 100))

        # 色偏
        cv_ = r['cast_rb']
        dr.text((C0 + 46, yc - 7), '%+.0f' % cv_, font=font(12), fill=col if abs(cv_) > 3 else (140, 144, 150),
                anchor='ra')
        if abs(cv_) > 3:
            dr.rectangle([C0 + 54, yc - 3, C0 + 54 + min(abs(cv_), 40) * 1.45, yc + 3],
                         fill=(200, 116, 48) if cv_ > 0 else (58, 110, 176))

    dr.text((34, H - 34), '灰点 = 暗部/高光位移（线越长反差变化越大）　实心点 = 平均亮度位移　'
                          '彩度按亮度分档对齐后取中位　数据：samples/filter_character.csv',
            font=font(11), fill=(150, 154, 160))
    os.makedirs(os.path.dirname(OUT_IMG), exist_ok=True)
    cv.save(OUT_IMG, quality=90, optimize=True)
    print('图：%s' % OUT_IMG)


def main():
    rows = build()
    if '--no-chart' not in sys.argv:
        chart(rows)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
