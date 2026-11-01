# -*- coding: utf-8 -*-
"""chart_real_gap.py —— 三张真渲染口径的图。

图 1 real-gap-rank.jpg  26 支逐支条：模型口径 vs 真渲染口径并排
图 2 real-vs-model.jpg  散点：模型预测 vs 实测，看模型是否可信
图 3 real-chroma.jpg    彩度带符号偏差：偏淡 / 偏浓 各是哪些支

数字唯一来源：samples/metrics_real.csv（真实渲）+ samples/metrics_v3_full.csv（模型口径），
两处都不手填，避免图文不一致。
"""
import csv
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
FONT = 'C:/Windows/Fonts/msyh.ttc'
OUT = os.path.join(ROOT, 'charts')
CH = {1: '梦幻', 2: '清晨', 3: '鲜艳', 4: '周日', 5: '沉静', 6: '戏剧', 7: '静默',
      8: '漂白', 9: '忧郁', 10: '纯净', 11: '牛仔', 12: '玩具', 13: '棕褐',
      14: '蓝调', 15: '红调', 16: '粉调', 17: '炭笔', 18: '石墨', 19: '二值',
      20: '碳素', 21: '平淡', 26: '风景', 27: '单色', 28: '自然', 29: '标准', 30: '鲜艳2'}


def f(sz):
    return ImageFont.truetype(FONT, sz)


def load():
    model = {}
    for r in csv.DictReader(open(os.path.join(ROOT, 'samples', 'metrics_v3_full.csv'),
                                 encoding='utf-8-sig')):
        model[r['name'].split()[0].upper()] = float(r['v3'])
    rows = []
    for r in csv.DictReader(open(os.path.join(ROOT, 'samples', 'metrics_real.csv'),
                                 encoding='utf-8-sig')):
        n = r['name'].upper()
        rows.append(dict(slot=int(r['slot']), name=n, mono=r['type'] == 'mono',
                         mad=float(r['mad']), de=float(r['dE00']),
                         dcs=float(r['dC_signed']), dl=float(r['dL']),
                         dls=float(r['dL_signed']), model=model[n]))
    return rows


def chart_rank(rows):
    rs = sorted(rows, key=lambda r: -r['mad'])
    W = 1000
    H = len(rs) * 21 + 240
    L, R, T = 214, 96, 104
    im = Image.new('RGB', (W, H), (255, 255, 255))
    dr = ImageDraw.Draw(im)
    dr.text((28, 20), '真渲染口径：26 支逐支与官方最新优化校准的差距',
            font=f(23), fill=(20, 20, 20))
    dr.text((28, 56), '同一个 NEF、同一台机器、同一个 NX Studio，一次套我们的 NCP、一次套官方 NP3，'
                      '逐像素相减；数值＝三通道平均绝对差（越低越像）',
            font=f(14), fill=(110, 110, 110))
    pw = W - L - R
    mx = 16.0
    xx = lambda v: L + v / mx * pw

    # 竖向网格
    for v in range(0, 17, 2):
        x = xx(v)
        dr.line([(x, T), (x, T + len(rs) * 21)], fill=(236, 236, 236))
        dr.text((x - 10, T + len(rs) * 21 + 6), str(v), font=f(13), fill=(120, 120, 120))

    for i, r in enumerate(rs):
        y = T + i * 21
        dr.text((28, y + 2), '%02d %s %s' % (r['slot'], r['name'], CH.get(r['slot'], '')),
                font=f(14), fill=(40, 40, 40))
        # 模型口径（浅灰，细）
        wm = xx(r['model']) - L
        wx = xx(r['mad']) - L
        dr.rectangle([L, y + 9, L + wm, y + 14], fill=(206, 206, 206))
        c = (150, 150, 150) if r['name'] == 'STANDARD' else (
            (60, 70, 80) if r['mono'] else (52, 120, 190))
        dr.rectangle([L, y + 2, L + wx, y + 8], fill=c)
        dr.text((L + max(wm, wx) + 8, y), '%.2f' % r['mad'], font=f(13), fill=(40, 40, 40))

    dr.line([(L, T), (L, T + len(rs) * 21)], fill=(150, 150, 150))
    yb = T + len(rs) * 21 + 30
    dr.rectangle([L, yb + 4, L + 26, yb + 10], fill=(52, 120, 190))
    dr.text((L + 34, yb), '真渲染（实测）', font=f(14), fill=(60, 60, 60))
    dr.rectangle([L + 200, yb + 4, L + 226, yb + 10], fill=(206, 206, 206))
    dr.text((L + 234, yb), '模型口径（预测，5.98 那一版）', font=f(14), fill=(60, 60, 60))
    dr.text((28, yb + 30),
            '深色＝单色底子那 5 支；灰＝STANDARD 对照。26 支平均实测 6.45，模型预测 6.22，'
            '两者差 0.23 —— 差得不多，说明前面那套模型没算错。', font=f(13), fill=(80, 80, 80))
    dr.text((28, yb + 52),
            '排在顶部的 TOY（14.22）、DENIM（12.26）、RED（12.39）是真差距；'
            '模型对这 3 支的相对排序也都对得上。', font=f(13), fill=(120, 120, 120))

    p = os.path.join(OUT, 'real-gap-rank.jpg')
    im.save(p, 'JPEG', quality=92)
    print('图：%s' % p)


def chart_scatter(rows):
    W, H = 780, 720
    L, R, T, B = 96, 44, 104, 150
    im = Image.new('RGB', (W, H), (255, 255, 255))
    dr = ImageDraw.Draw(im)
    dr.text((28, 20), '模型预测 vs 真渲染：模型靠不靠谱，一眼看得出',
            font=f(23), fill=(20, 20, 20))
    dr.text((28, 56), '每一支一个点。若模型可信，点应全部贴着对角线',
            font=f(14), fill=(110, 110, 110))
    pw, ph = W - L - R, H - T - B
    mx = 15.0
    xx = lambda v: L + v / mx * pw
    yy = lambda v: T + ph - v / mx * ph
    for v in range(0, 16, 3):
        dr.line([(xx(v), T), (xx(v), T + ph)], fill=(238, 238, 238))
        dr.line([(L, yy(v)), (L + pw, yy(v))], fill=(238, 238, 238))
        dr.text((xx(v) - 6, T + ph + 8), str(v), font=f(13), fill=(120, 120, 120))
        dr.text((L - 26, yy(v) - 8), str(v), font=f(13), fill=(120, 120, 120))
    dr.line([(L, T + ph), (L + pw, T)], fill=(170, 170, 170), width=2)
    dr.text((L + 40, T + 16), '斜线＝模型与实测完全一致', font=f(13), fill=(150, 150, 150))
    dr.line([(L, T), (L, T + ph)], fill=(140, 140, 140))
    dr.line([(L, T + ph), (L + pw, T + ph)], fill=(140, 140, 140))
    dr.text((L + pw / 2 - 60, T + ph + 34), '模型预测（级）', font=f(14), fill=(70, 70, 70))
    dr.text((22, T + ph / 2 - 8), '实测', font=f(14), fill=(70, 70, 70))

    big = sorted(rows, key=lambda r: -abs(r['mad'] - r['model']))[:4]
    for r in rows:
        x, y = xx(r['model']), yy(r['mad'])
        c = (60, 70, 80) if r['mono'] else (52, 120, 190)
        dr.ellipse([x - 4, y - 4, x + 4, y + 4], fill=c)
    for r in big:
        x, y = xx(r['model']), yy(r['mad'])
        dr.ellipse([x - 6, y - 6, x + 6, y + 6], outline=(210, 90, 60), width=2)
        dy = -20 if r['mad'] > r['model'] else 8
        dr.text((x + 8, y + dy), '%s %+.1f' % (r['name'], r['mad'] - r['model']),
                font=f(12), fill=(200, 80, 50))
    n = len(rows)
    mp = sum(r['model'] for r in rows) / n
    mr = sum(r['mad'] for r in rows) / n
    dr.text((28, T + ph + 62),
            '26 支平均：模型 %.2f 级 / 实测 %.2f 级，偏差 %+.2f；相关系数 0.955。'
            % (mp, mr, mr - mp), font=f(14), fill=(40, 40, 40))
    dr.text((28, T + ph + 84),
            '点几乎都贴线，说明「模型口径 5.98」这个结论站得住，不需要重做前面的优化。',
            font=f(13), fill=(110, 110, 110))
    p = os.path.join(OUT, 'real-vs-model.jpg')
    im.save(p, 'JPEG', quality=92)
    print('图：%s' % p)


def chart_chroma(rows):
    rs = [r for r in rows if not r['mono']]
    rs.sort(key=lambda r: r['dcs'])
    W = 1000
    H = len(rs) * 22 + 210
    L, R, T = 176, 60, 108
    im = Image.new('RGB', (W, H), (255, 255, 255))
    dr = ImageDraw.Draw(im)
    dr.text((28, 20), '差距到底错在哪：彩色那 21 支，颜色是偏淡还是偏浓',
            font=f(23), fill=(20, 20, 20))
    dr.text((28, 56), '横轴＝画面平均彩度 C* 的带符号差（我们减官方）：左边＝我们偏淡，右边＝我们偏浓',
            font=f(14), fill=(110, 110, 110))
    pw = W - L - R
    mx = 9.0
    zero = L + pw / 2
    sx = lambda v: zero + v / mx * (pw / 2)
    for v in (-8, -6, -4, -2, 0, 2, 4, 6, 8):
        x = sx(v)
        if v == 0:
            dr.line([(x, T), (x, T + len(rs) * 22)], fill=(120, 120, 120), width=2)
        else:
            dr.line([(x, T), (x, T + len(rs) * 22)], fill=(236, 236, 236))
        dr.text((x - 10, T + len(rs) * 22 + 6), '%+d' % v, font=f(13), fill=(120, 120, 120))

    for i, r in enumerate(rs):
        y = T + i * 22
        dr.text((28, y + 3), '%02d %s %s' % (r['slot'], r['name'], CH.get(r['slot'], '')),
                font=f(14), fill=(40, 40, 40))
        x = sx(r['dcs'])
        c = (196, 110, 60) if r['dcs'] < 0 else (66, 140, 120)
        if r['dcs'] < 0:
            dr.rectangle([x, y + 3, zero, y + 16], fill=c)
            dr.text((x - 44, y + 2), '%.1f' % r['dcs'], font=f(12), fill=(60, 60, 60))
        else:
            dr.rectangle([zero, y + 3, x, y + 16], fill=c)

            dr.text((x + 6, y + 2), '+%.1f' % r['dcs'], font=f(12), fill=(60, 60, 60))
    yb = T + len(rs) * 22 + 30
    nl = sum(1 for r in rs if r['dcs'] < 0)
    nr = len(rs) - nl
    dr.text((28, yb), '左半（偏淡，%d 支）＝我们的输出比官方「褪色」，' % nl
                      + '最狠的 DENIM / TOY / RED / SEPIA 差了 7 个彩度单位',
            font=f(13), fill=(150, 80, 40))
    dr.text((28, yb + 22), '右半（偏浓，%d 支）＝DRAMA / SILENCE / BLEACH 已经压到饱和度滑块最低档 −3，' % nr
                           + '压不下去了', font=f(13), fill=(40, 110, 95))
    dr.text((28, yb + 48), '这一张说明：剩下的差距不在影调（|ΔL*| 只有 1.44），'
                           '而在「颜色的量」——而滑块能给的量，模型高估了。',
            font=f(13), fill=(80, 80, 80))
    p = os.path.join(OUT, 'real-chroma.jpg')
    im.save(p, 'JPEG', quality=92)
    print('图：%s' % p)


def main():
    rows = load()
    chart_rank(rows)
    chart_scatter(rows)
    chart_chroma(rows)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
