# -*- coding: utf-8 -*-
"""对比「尼康工坊 最新优化校准」与「D300 NCP 发布包」的成片差异。

同一张 NEF（DSC_3891）导出两套 30 张：
  工坊原版  = NX Studio 内置最新优化校准   → 测试图片/DSC_3891_30..59.JPG
  D300 NCP = 发布包里的补偿版 NCP（工坊载入） → 测试图片/DSC_3891_01..29.JPG（滤镜 02..30）
  滤镜 01 DREAM 的我方样片缺失（导出时没有 30 号），脚本会跳过并记录。

用法：
    python compare_samples.py            # 只算数据
    python compare_samples.py --images   # 顺便出图
"""
import csv
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

Image.MAX_IMAGE_PIXELS = None

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), '测试图片')
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '对比样片')
FONT_C = 'C:/Windows/Fonts/msyh.ttc'
FONT_B = 'C:/Windows/Fonts/msyhbd.ttc'

# (槽位, 英文名, 中文名, 底子)
FILTERS = [
    (1, 'DREAM', '梦幻', '标准'),
    (2, 'MORNING', '清晨', '标准'),
    (3, 'POP', '流行', '标准'),
    (4, 'SUNDAY', '星期天', '标准'),
    (5, 'SOMBER', '低沉', '标准'),
    (6, 'DRAMA', '戏剧', '标准'),
    (7, 'SILENCE', '静寂', '标准'),
    (8, 'BLEACH', '漂白', '标准'),
    (9, 'MELANCHOLIC', '忧郁', '标准'),
    (10, 'PURE', '纯净', '标准'),
    (11, 'DENIM', '牛仔布', '标准'),
    (12, 'TOY', '玩具', '标准'),
    (13, 'SEPIA', '棕褐色', '单色'),
    (14, 'BLUE', '蓝色', '单色'),
    (15, 'RED', '红色', '单色'),
    (16, 'PINK', '粉色', '单色'),
    (17, 'CHARCOAL', '木炭', '单色'),
    (18, 'GRAPHITE', '石墨', '单色'),
    (19, 'BINARY', '双色', '单色'),
    (20, 'CARBON', '黑碳', '单色'),
    (21, 'FLAT', '平面', '标准'),
    (22, 'FLAT_MONOCHROME', '平面单色', '单色'),
    (23, 'DEEPTONE_MONOCHROME', '深色调单色', '单色'),
    (24, 'RICH_TONE_PORTRAIT', '丰富色调人像', '标准'),
    (25, 'FLEXIBLE_COLOR', '灵活颜色', '标准'),
    (26, 'LANDSCAPE', '风景', '标准'),
    (27, 'MONOCHROME', '单色', '单色'),
    (28, 'NEUTRAL', '自然', '标准'),
    (29, 'STANDARD', '标准', '标准'),
    (30, 'VIVID', '鲜艳', '标准'),
]


def our_path(slot):
    if slot == 1:
        return None
    return os.path.join(SRC, 'DSC_3891_%02d.JPG' % (slot - 1))


def ref_path(slot):
    return os.path.join(SRC, 'DSC_3891_%02d.JPG' % (slot + 29))


def load_rgb(path):
    im = Image.open(path)
    im.draft('RGB', (4288, 2848))
    return np.asarray(im.convert('RGB'))


def luma(a):
    return 0.299 * a[:, :, 0] + 0.587 * a[:, :, 1] + 0.114 * a[:, :, 2]


def _box(x, r):
    """盒滤波（积分图实现）。"""
    k = 2 * r + 1
    p = np.pad(x, ((r, r), (r, r)), mode='edge')
    c = p.cumsum(0).cumsum(1)
    c = np.pad(c, ((1, 0), (1, 0)))
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)


def ssim(a, b, r=3):
    """单通道 SSIM，a/b 为 0..255 的 float。"""
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    ma, mb = _box(a, r), _box(b, r)
    va = _box(a * a, r) - ma * ma
    vb = _box(b * b, r) - mb * mb
    cov = _box(a * b, r) - ma * mb
    s = ((2 * ma * mb + c1) * (2 * cov + c2)) / ((ma ** 2 + mb ** 2 + c1) * (va + vb + c2))
    return float(s.mean())


def metrics(o, r):
    """o/r: uint8 HxWx3，几何完全对齐。"""
    h, w, _ = o.shape
    Lo, Lr = luma(o.astype(np.float32)), luma(r.astype(np.float32))

    # 逐块累计，避免 12MP 的浮点大数组
    tot_abs = 0.0
    tot_sq = 0.0
    pct8 = 0
    n = 0
    for y in range(0, h, 512):
        a = o[y:y + 512].astype(np.int16)
        b = r[y:y + 512].astype(np.int16)
        d = a - b
        tot_abs += float(np.abs(d).sum())
        tot_sq += float((d.astype(np.float32) ** 2).sum())
        pct8 += int((np.abs(d).max(2) > 8).sum())
        n += d.size

    dL = Lo - Lr
    of = o.astype(np.float32)
    rf = r.astype(np.float32)
    co = np.max(of, 2) - np.min(of, 2)
    cr = np.max(rf, 2) - np.min(rf, 2)

    # 全局偏色：三通道均值的相对位移（等价于白平衡偏移）
    m_o, m_r = of.reshape(-1, 3).mean(0), rf.reshape(-1, 3).mean(0)
    cast_r = float((m_o[0] - m_o[2]) - (m_r[0] - m_r[2]))      # 红-蓝 偏移
    cast_g = float((m_o[1] - m_o[2]) - (m_r[1] - m_r[2]))      # 绿-蓝 偏移

    # 去掉全局偏色后的「彩度」，才能区分「加了一层色罩」和「颜色更浓」
    go = of - (m_o - m_o.mean())
    gr = rf - (m_r - m_r.mean())
    ca_o = float((np.max(go, 2) - np.min(go, 2)).mean())
    ca_r = float((np.max(gr, 2) - np.min(gr, 2)).mean())

    # 影调传递：按参考亮度分 16 档，看中位输出偏离
    edges = np.arange(0, 257, 16)
    dev = []
    for i in range(16):
        m = (Lr >= edges[i]) & (Lr < edges[i + 1])
        if m.sum() < 5000:
            continue
        dev.append(float(np.median(Lo[m]) - np.median(Lr[m])))
    tone_rms = float(np.sqrt(np.mean(np.square(dev)))) if dev else 0.0

    # 小图做 SSIM，速度快也够说明问题
    step = max(1, int(round(max(h, w) / 900)))
    os_ = Lo[::step, ::step]
    rs_ = Lr[::step, ::step]

    return {
        'mean_abs': tot_abs / n,                       # 三通道平均绝对差（级）
        'rms': (tot_sq / n) ** 0.5,
        'pct_gt8': pct8 / (o.shape[0] * o.shape[1]) * 100.0,
        'L_mean_our': float(Lo.mean()),
        'L_mean_ref': float(Lr.mean()),
        'dL_mean': float(dL.mean()),
        'L_med_our': float(np.median(Lo)),
        'L_med_ref': float(np.median(Lr)),
        'L_std_our': float(Lo.std()),
        'L_std_ref': float(Lr.std()),
        'C_mean_our': float(co.mean()),
        'C_mean_ref': float(cr.mean()),
        'dC_mean': float(co.mean() - cr.mean()),
        'cast_RB': cast_r,
        'cast_GB': cast_g,
        'chroma_our': ca_o,
        'chroma_ref': ca_r,
        'chroma_ratio': ca_o / ca_r if ca_r > 0.5 else 1.0,
        'tone_rms': tone_rms,
        'ssim': ssim(os_, rs_),
    }


def grade(m):
    """按平均差给个口语化评级。"""
    if m['mean_abs'] < 2.0:
        return '几乎一致'
    if m['mean_abs'] < 4.0:
        return '很接近'
    if m['mean_abs'] < 7.0:
        return '接近'
    if m['mean_abs'] < 12.0:
        return '可辨差异'
    return '明显不同'


def compute():
    rows = []
    for slot, en, cn, base in FILTERS:
        op, rp = our_path(slot), ref_path(slot)
        if op is None or not os.path.exists(op):
            rows.append(dict(slot=slot, en=en, cn=cn, base=base, missing=True))
            print('%2d %-20s 我方样片缺失，跳过' % (slot, en))
            continue
        print('  计算 %2d %-20s ...' % (slot, en), end='', flush=True)
        m = metrics(load_rgb(op), load_rgb(rp))
        m.update(slot=slot, en=en, cn=cn, base=base, missing=False)
        m['grade'] = grade(m)
        rows.append(m)
        print(' 平均差 %.2f  SSIM %.4f  %s' % (m['mean_abs'], m['ssim'], m['grade']))
    return rows


def save_data(rows):
    os.makedirs(OUT, exist_ok=True)
    cols = ['slot', 'en', 'cn', 'base', 'mean_abs', 'rms', 'pct_gt8', 'dL_mean',
            'L_mean_our', 'L_mean_ref', 'L_med_our', 'L_med_ref', 'L_std_our', 'L_std_ref',
            'C_mean_our', 'C_mean_ref', 'dC_mean', 'cast_RB', 'cast_GB',
            'chroma_our', 'chroma_ref', 'chroma_ratio', 'tone_rms', 'ssim', 'grade']
    with open(os.path.join(OUT, '对比数据.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            if r.get('missing'):
                continue
            w.writerow({k: (round(r[k], 4) if isinstance(r[k], float) else r[k]) for k in cols})
    with open(os.path.join(OUT, '对比数据.json'), 'w', encoding='utf-8') as f:
        json.dump([{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()} for r in rows],
                  f, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- 出图

def font(size, bold=False):
    return ImageFont.truetype(FONT_B if bold else FONT_C, size)


def make_pair_images(rows):
    """每对一张左右并排图，标题栏写关键数据。"""
    d1 = os.path.join(OUT, '工坊原版')
    d2 = os.path.join(OUT, 'D300_NCP')
    d3 = os.path.join(OUT, '对比图')
    for d in (d1, d2, d3):
        os.makedirs(d, exist_ok=True)

    PW, GAP, MG = 600, 14, 16
    for r in rows:
        if r.get('missing'):
            continue
        k = r['slot']
        name = '%02d_%s' % (k, r['en'])
        a = Image.open(our_path(k)).convert('RGB')
        b = Image.open(ref_path(k)).convert('RGB')
        ph = int(round(PW * a.height / a.width))
        a = a.resize((PW, ph), Image.LANCZOS)
        b = b.resize((PW, ph), Image.LANCZOS)
        a.save(os.path.join(d2, name + '.jpg'), quality=82, optimize=True)
        b.save(os.path.join(d1, name + '.jpg'), quality=82, optimize=True)

        W = PW * 2 + GAP + MG * 2
        TOP, CAP, BOT = 62, 34, 6
        H = TOP + ph + CAP + BOT
        cv = Image.new('RGB', (W, H), (250, 250, 250))
        dr = ImageDraw.Draw(cv)

        dr.rectangle([0, 0, W, TOP - 6], fill=(28, 30, 34))
        f1, f2, f3 = font(26, True), font(17), font(15)
        t1 = '%02d  %s' % (k, r['cn'])
        t3 = '平均差 %.1f · 影调 %+.1f · 彩度 %.2fx · 偏色 %+.1f · SSIM %.3f' % (
            r['mean_abs'], r['dL_mean'], r['chroma_ratio'], r['cast_RB'], r['ssim'])
        dr.text((MG, 10), t1, font=f1, fill=(255, 255, 255))
        x2 = MG + dr.textlength(t1, font=f1) + 14
        room = (W - MG) - dr.textlength(t3, font=f3) - x2 - 18
        t2 = r['en']
        while dr.textlength(t2, font=f2) > room and len(t2) > 4:
            t2 = t2[:-1]
        if t2 != r['en']:
            t2 = t2[:-1] + '…'
        dr.text((x2, 17), t2, font=f2, fill=(150, 155, 165))
        dr.text((W - MG, 13), t3, font=f3, fill=(235, 235, 240), anchor='ra')

        cv.paste(b, (MG, TOP))
        cv.paste(a, (MG + PW + GAP, TOP))
        y = TOP + ph + 8
        dr.text((MG, y), '尼康工坊 · 最新优化校准（原参考）', font=font(16), fill=(70, 70, 75))
        dr.text((MG + PW + GAP, y), 'D300 NCP · 发布包（补偿版）', font=font(16), fill=(70, 70, 75))
        dr.text((W - MG, y), r['grade'], font=font(16, True), fill=(150, 40, 40) if r['mean_abs'] > 7 else (40, 110, 60),
                anchor='ra')
        cv.save(os.path.join(d3, name + '_对比.jpg'), quality=80, optimize=True)


def make_chart(rows):
    """平均差条形图。"""
    rs = [r for r in rows if not r.get('missing')]
    rs.sort(key=lambda x: x['mean_abs'])
    W, L, R = 1180, 260, 90
    BH, G = 26, 8
    H = 90 + len(rs) * (BH + G) + 40
    cv = Image.new('RGB', (W, H), (255, 255, 255))
    dr = ImageDraw.Draw(cv)
    dr.text((30, 24), 'D300 NCP 发布包 与 尼康工坊最新优化校准 的成片差距', font=font(26, True), fill=(30, 30, 35))
    dr.text((30, 58), '平均绝对差（0–255 级，三通道均值），越小越像；灰色竖线 = 4 级', font=font(15), fill=(110, 110, 115))

    vmax = max(12.0, max(r['mean_abs'] for r in rs) * 1.05)
    pw = W - L - R
    x4 = L + pw * 4 / vmax
    dr.line([x4, 82, x4, H - 26], fill=(200, 200, 205), width=1)

    y = 88
    for r in rs:
        dr.text((L - 12, y + 4), '%02d %s' % (r['slot'], r['en']), font=font(15), fill=(50, 50, 55), anchor='ra')
        w = max(2, int(pw * r['mean_abs'] / vmax))
        col = (60, 130, 90) if r['mean_abs'] < 4 else ((200, 150, 40) if r['mean_abs'] < 7 else (185, 65, 55))
        dr.rectangle([L, y, L + w, y + BH], fill=col)
        dr.text((L + w + 8, y + 5), '%.1f' % r['mean_abs'], font=font(14), fill=(60, 60, 65))
        y += BH + G
    cv.save(os.path.join(OUT, '差距排行.png'), optimize=True)
    cv.convert('RGB').save(os.path.join(OUT, '差距排行.jpg'), quality=88, optimize=True)


def load_json():
    with open(os.path.join(OUT, '对比数据.json'), encoding='utf-8') as f:
        return json.load(f)


def main():
    if '--from-json' in sys.argv:
        rows = load_json()
    else:
        rows = compute()
        save_data(rows)
    if '--images' in sys.argv:
        make_pair_images(rows)
        make_chart(rows)
    print('\n输出目录：', OUT)


if __name__ == '__main__':
    main()
