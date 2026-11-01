# -*- coding: utf-8 -*-
"""make_real_pairs.py —— 把「官方 / 我们」两张真渲染并排放，做成品红色差直观对照。

只挑差距最大的 6 支。左右各占一半，底部标名字与数值，避免读者分不清谁是谁。
"""
import csv
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
FONT = 'C:/Windows/Fonts/msyh.ttc'
OUTD = os.path.join(ROOT, 'samples', 'real_pairs')
TOP = ['TOY', 'RED', 'DENIM', 'MORNING', 'DREAM', 'PURE']
CH = {'DREAM': '梦幻', 'MORNING': '清晨', 'PURE': '纯净', 'DENIM': '牛仔',
      'RED': '红调', 'TOY': '玩具'}
PW, PH = 430, 286          # 单张缩略尺寸（保持 3:2）


def f(sz):
    return ImageFont.truetype(FONT, sz)


def find(d, slot, name):
    for fn in os.listdir(d):
        b, _ = os.path.splitext(fn)
        if b.upper() == ('%02d_%s' % (slot, name)).upper():
            return os.path.join(d, fn)
    return None


def main():
    os.makedirs(OUTD, exist_ok=True)
    meta = {}
    for r in csv.DictReader(open(os.path.join(ROOT, 'samples', 'metrics_real.csv'),
                                 encoding='utf-8-sig')):
        meta[r['name'].upper()] = r
    for name in TOP:
        r = meta[name]
        slot = int(r['slot'])
        pa = find(os.path.join(ROOT, 'samples', 'real_target'), slot, name)
        pb = find(os.path.join(ROOT, 'samples', 'real_v3'), slot, name)
        W = PW * 2 + 24
        H = PH + 62
        im = Image.new('RGB', (W, H), (255, 255, 255))
        dr = ImageDraw.Draw(im)
        for i, p in enumerate((pa, pb)):
            t = Image.open(p).convert('RGB').resize((PW, PH), Image.LANCZOS)
            im.paste(t, (i * (PW + 24), 34))
        dr.rectangle([0, 34, PW, 34 + PH], outline=(255, 255, 255))
        dr.rectangle([PW + 24, 34, W, 34 + PH], outline=(255, 255, 255))
        dr.text((4, 8), '官方最新优化校准（NP3）', font=f(15), fill=(30, 30, 30))
        dr.text((PW + 28, 8), '我们的 NCP（v3）', font=f(15), fill=(180, 70, 40))
        dr.text((4, PH + 40), '%02d %s %s　平均色差 %.2f 级 / ΔE00 %.2f'
                % (slot, name, CH.get(name, ''), float(r['mad']), float(r['dE00'])),
                font=f(14), fill=(60, 60, 60))
        out = os.path.join(OUTD, 'pair_%02d_%s.jpg' % (slot, name))
        im.save(out, 'JPEG', quality=92)
        print('图：%s' % out)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
