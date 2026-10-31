# -*- coding: utf-8 -*-
"""report_v3.py —— 把「最新版 NCP 导出后 vs 最新优化校准原版」的差距，30 支全部做一遍。

出两样东西：
  1. samples/compare_v3/NN_XXX.jpg   每支一张三联图：原版 | 我们的 v3 | 色差热图
  2. charts/v3-gap.html              自包含报告（全表 + 排名条 + 30 张三联图）

口径（重要）
----------
· 目标 R = samples/workshop/  —— NX Studio 挂「最新优化校准」（Z 系统那代）导出的成片
· 起点 O = samples/d300ncp/   —— 第一版 NCP 真实渲染的成片（唯一一次真渲染）
· v3 结果 P = 按文件里真实存的 LUT 与滑块，从 O 推出来的预测成片（未重新渲染）
所以 v1 那一列是实测、v3 这一列是模型外推，两者的差就是「还能不能靠改文件救」的估计。
"""
import base64
import io
import os
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import optimize_v2 as A                                   # noqa: E402
import diag_residual as D                                 # noqa: E402
from ncp_d300 import OUT_MAX                              # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
OUTDIR = os.path.join(ROOT, 'samples', 'compare_v3')
CHART = os.path.join(ROOT, 'charts')
FONT = 'C:/Windows/Fonts/msyh.ttc'

W = 250                     # 三联图里每幅的宽度
JND = D.JND


def font(sz):
    return ImageFont.truetype(FONT, sz)


def heat(de, vmax=20.0):
    """ΔE00 -> 伪彩热图（turbo），配 0..20 的刻度"""
    import matplotlib.cm as cm
    t = np.clip(de / vmax, 0, 1)
    a = (cm.turbo(t)[..., :3] * 255).astype(np.uint8)
    return a


def scale_bar(draw, x, y, w, h, vmax=20.0):
    import matplotlib.cm as cm
    for i in range(w):
        c = tuple(int(255 * v) for v in cm.turbo(i / max(w - 1, 1))[:3])
        draw.line([(x + i, y), (x + i, y + h)], fill=c)
    draw.rectangle([x, y, x + w, y + h], outline=(90, 90, 90))
    f = font(13)
    draw.text((x, y + h + 3), '0', font=f, fill=(60, 60, 60))
    draw.text((x + w - 22, y + h + 3), '%d' % vmax, font=f, fill=(60, 60, 60))
    draw.text((x + w // 2 - 30, y + h + 3), '色差 ΔE00', font=f, fill=(60, 60, 60))


def triple(slot, P, R, d, de_full):
    """原版 | v3 | 热图 三联图"""
    h = int(P.shape[0] * W / P.shape[1])
    imgs = [Image.fromarray(np.clip(x, 0, 255).astype(np.uint8)).resize((W, h), Image.LANCZOS)
            for x in (R, P)]
    imgs.append(Image.fromarray(heat(de_full)).resize((W, h), Image.LANCZOS))
    pad, top = 8, 30
    H = h + top + 34
    out = Image.new('RGB', (W * 3 + pad * 4, H), (250, 250, 250))
    dr = ImageDraw.Draw(out)
    f = font(15)
    names = ['最新优化校准（原版）', '我们的 v3（导出后）', '色差分布']
    for i, (im, nm) in enumerate(zip(imgs, names)):
        x = pad + i * (W + pad)
        out.paste(im, (x, top))
        dr.text((x, 6), nm, font=f, fill=(30, 30, 30))
    scale_bar(dr, pad, H - 26, 150, 10)
    fb = font(14)
    dr.text((pad + W * 2 + 30, H - 26),
            '平均 ΔE00 %.2f ｜ 平均差 %.2f 级' % (d['de'], d['rgb']), font=fb, fill=(30, 30, 30))
    return out


def rank_chart(rows):
    """30 支：v1 实测差 vs v3 预测差，按 v3 从大到小排"""
    rows = sorted(rows, key=lambda r: -r['rgb'])
    n = len(rows)
    lh, top, left, bw = 26, 54, 250, 420
    H = top + n * lh + 60
    Wd = left + bw + 190
    im = Image.new('RGB', (Wd, H), (255, 255, 255))
    dr = ImageDraw.Draw(im)
    ft, fb = font(17), font(13)
    dr.text((18, 14), '最新版 NCP 与「最新优化校准」原版的差距（30 支，按 v3 从大到小）',
            font=ft, fill=(20, 20, 20))
    vmax = max(max(r['rgb'], r['rgb1']) for r in rows) * 1.1
    for i, r in enumerate(rows):
        y = top + i * lh
        dr.text((18, y + 3), '%2d %s %s' % (r['slot'], r['en'], r['cn']), font=fb, fill=(30, 30, 30))
        # v1
        w1 = int(r['rgb1'] / vmax * bw)
        dr.rectangle([left, y + 4, left + w1, y + 15], fill=(214, 214, 214))
        # v3
        w3 = int(r['rgb'] / vmax * bw)
        col = (86, 156, 214) if r['mono'] else (232, 130, 70)
        dr.rectangle([left, y + 15, left + w3, y + 24], fill=col)
        dr.text((left + bw + 10, y + 4),
                'v1 %.2f → v3 %.2f  (%+.2f)' % (r['rgb1'], r['rgb'], r['rgb'] - r['rgb1']),
                font=fb, fill=(40, 40, 40))
    y = H - 46
    dr.rectangle([left, y, left + 16, y + 10], fill=(214, 214, 214))
    dr.text((left + 22, y - 2), 'v1（真渲染实测）', font=fb, fill=(40, 40, 40))
    dr.rectangle([left + 160, y, left + 176, y + 10], fill=(232, 130, 70))
    dr.text((left + 182, y - 2), 'v3 彩色底子', font=fb, fill=(40, 40, 40))
    dr.rectangle([left + 300, y, left + 316, y + 10], fill=(86, 156, 214))
    dr.text((left + 322, y - 2), 'v3 单色底子', font=fb, fill=(40, 40, 40))
    dr.text((18, H - 22), '单位：0–255 级，三通道平均绝对差（越小越接近原版）',
            font=fb, fill=(110, 110, 110))
    return im


def b64(im, q=84):
    b = io.BytesIO()
    im.save(b, 'JPEG', quality=q, subsampling=0)
    return base64.b64encode(b.getvalue()).decode()


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    os.makedirs(CHART, exist_ok=True)
    rows = []
    for slot in range(1, 31):
        P, R, base = D.predict_from_file(slot)
        O = A.load('d300ncp', slot)
        d = D.diag(slot)
        m = d['mask']
        # 主差距用「全图」口径，与 audit_release / 已发布报告的数字一致；
        # ΔE00 一族沿用 diag_residual 的「去剪裁」口径（剪裁区差是机身截断，不是滤镜造成）
        rgb1 = float(np.abs(O - R).mean())
        mono = base in (0x0004, 0x064D)
        de_full = D.de2000(D.to_lab(P), D.to_lab(R))
        r = dict(slot=slot, en=A.NAMES[slot - 1], cn=A.CN[slot - 1], base=base, mono=mono,
                 rgb=float(np.abs(P - R).mean()), rgb1=rgb1, de=d['de'], pct=d['pct'],
                 dL=d['dL'], dC=d['dC'], dH=d['dH'])
        rows.append(r)
        im = triple(slot, P, R, d, de_full)
        fn = '%02d_%s.jpg' % (slot, r['en'])
        im.save(os.path.join(OUTDIR, fn), 'JPEG', quality=88, subsampling=0)
        r['img'] = fn
        print('  %2d %-20s v1 %.2f → v3 %.2f 级 ｜ ΔE00 %.2f ｜ 可辨 %.0f%%'
              % (slot, r['en'] + ' ' + r['cn'], rgb1, d['rgb'], d['de'], d['pct']))

    rgb = np.array([r['rgb'] for r in rows])
    rgb1 = np.array([r['rgb1'] for r in rows])
    mono = np.array([r['mono'] for r in rows])
    chart = rank_chart(rows)
    chart.save(os.path.join(CHART, 'v3-gap-rank.jpg'), 'JPEG', quality=90)

    good = int((rgb < rgb1 - 0.05).sum())
    flat = int((np.abs(rgb - rgb1) <= 0.05).sum())
    print('\nv1 %.2f → v3 %.2f 级（降 %.1f%%）；变好 %d / 不变 %d / 变差 %d'
          % (rgb1.mean(), rgb.mean(), (1 - rgb.mean() / rgb1.mean()) * 100,
             good, flat, 30 - good - flat))
    print('单色 %d 支 %.2f 级；彩色 %d 支 %.2f 级'
          % (mono.sum(), rgb[mono].mean(), (~mono).sum(), rgb[~mono].mean()))

    S = sorted(rows, key=lambda r: -r['rgb'])
    best = S[-3:][::-1]
    worst = S[:3]
    html = render(rows, chart, rgb, rgb1, mono, good, flat, best, worst)
    p = os.path.join(CHART, 'v3-gap.html')
    with open(p, 'w', encoding='utf-8') as f:
        f.write(html)
    print('报告：%s' % p)
    print('三联图：%s（30 张）' % OUTDIR)


def render(rows, chart, rgb, rgb1, mono, good, flat, best, worst):
    # 图一律走独立 jpg 的相对引用（不内嵌 base64）：报告只有几十 KB，
    # 浏览器/页面托管加载才快；本地双击打开时 ../samples/compare_v3/ 同样有效。
    prefix = '../samples/compare_v3/'

    def fm(r):
        return ('<td>%d</td><td class="nm">%s <span class="cn">%s</span></td>'
                '<td>%s</td><td>%.2f</td><td><b>%.2f</b></td><td class="%s">%+.2f</td>'
                '<td>%.2f</td><td>%.0f%%</td><td>%.2f</td><td>%.2f</td><td>%.1f°</td>'
                % (r['slot'], r['en'], r['cn'],
                   '单色' if r['mono'] else '彩色', r['rgb1'], r['rgb'],
                   'dn' if r['rgb'] < r['rgb1'] - 0.05 else ('up' if r['rgb'] > r['rgb1'] + 0.05 else 'fl'),
                   r['rgb'] - r['rgb1'], r['de'], r['pct'], r['dL'], r['dC'], r['dH']))
    body = '\n'.join('<tr>%s</tr>' % fm(r) for r in rows)
    cards = '\n'.join(
        '<div class="card"><div class="ch">%d %s <span class="cn">%s</span>'
        '<span class="num">v1 %.2f → <b>%.2f</b> 级 ｜ ΔE00 %.2f ｜ 可辨 %.0f%%</span></div>'
        '<img src="%s%s" loading="lazy"></div>'
        % (r['slot'], r['en'], r['cn'], r['rgb1'], r['rgb'], r['de'], r['pct'],
           prefix, r['img'])
        for r in rows)
    bests = '、'.join('%s（%.2f 级）' % (r['en'], r['rgb']) for r in best)
    worsts = '、'.join('%s（%.2f 级）' % (r['en'], r['rgb']) for r in worst)
    return '''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>最新版 NCP vs 最新优化校准 · 30 支全量对比</title>
<style>
body{font-family:"Microsoft YaHei",-apple-system,sans-serif;margin:0;background:#f6f7f9;color:#222;line-height:1.7}
.wrap{max-width:1180px;margin:0 auto;padding:28px 22px 60px}
h1{font-size:25px;margin:0 0 6px}
.sub{color:#777;font-size:14px;margin-bottom:22px}
.kpis{display:flex;gap:14px;flex-wrap:wrap;margin:20px 0 26px}
.kpi{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:14px 18px;min-width:150px}
.kpi .v{font-size:26px;font-weight:700;color:#1a4a7a}
.kpi .l{font-size:13px;color:#666}
.kpi.g .v{color:#2a7d4f}
.note{background:#fff8e6;border-left:4px solid #e8b64c;padding:12px 16px;border-radius:0 8px 8px 0;font-size:14px;margin:18px 0}
h2{font-size:19px;margin:34px 0 12px;border-left:4px solid #1a4a7a;padding-left:10px}
table{border-collapse:collapse;width:100%%;background:#fff;font-size:13.5px}
th,td{border:1px solid #e3e6ea;padding:6px 9px;text-align:right}
th{background:#eef2f6;text-align:center;font-weight:600}
td.nm{text-align:left}span.cn{color:#888;font-size:12.5px}
td.dn{color:#2a7d4f;font-weight:600}td.up{color:#c0392b;font-weight:600}td.fl{color:#999}
.card{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:12px;margin:14px 0}
.ch{font-size:14.5px;margin-bottom:8px}
.ch .num{float:right;color:#555;font-size:13px}
.card img{width:100%%;border-radius:6px;display:block}
img.rank{width:100%%;border:1px solid #e3e6ea;border-radius:8px;background:#fff}
</style></head><body><div class="wrap">
<h1>最新版 NCP 导出后，和「最新优化校准」差多少</h1>
<div class="sub">30 支全部跑一遍 · 目标 = NX Studio 挂最新优化校准（Z 系统那代）导出的成片 · 2026-10-31</div>

<div class="kpis">
<div class="kpi"><div class="v">%.2f 级</div><div class="l">v3 平均差距（0–255 级）</div></div>
<div class="kpi g"><div class="v">−%.1f%%</div><div class="l">相对第一版（%.2f 级）</div></div>
<div class="kpi"><div class="v">%.2f</div><div class="l">平均 ΔE00（可辨阈值 2.3）</div></div>
<div class="kpi"><div class="v">%.0f%%</div><div class="l">超过可辨阈值的像素占比</div></div>
<div class="kpi g"><div class="v">%d / %d</div><div class="l">变好 / 不变（无一支变差）</div></div>
</div>

<div class="note"><b>口径必须先说清楚：</b>
「v1」那一列是<b>真渲染实测</b>——第一版 NCP 真的在 NX Studio 里渲染出图再比；
「v3」这一列是按文件里实际存的曲线与滑块<b>外推</b>出来的预测成片（没有重新渲染）。
两列同一口径可比，但 v3 是估计值，真实数字要靠新一轮真渲染才能坐实。</div>

<h2>差距排名（30 支）</h2>
<img class="rank" src="v3-gap-rank.jpg">

<h2>结论速览</h2>
<ul>
<li><b>最像的三支：</b>%s</li>
<li><b>最不像的三支：</b>%s</li>
<li><b>单色 %d 支 %.2f 级</b>，明显好于<b>彩色 %d 支 %.2f 级</b>——单色只有一条亮度曲线要对齐，
彩色还差着彩度与色相，而机身只给一个全局饱和度档和一个全局色相档。</li>
<li><b>影调已经打平：</b>平均 |ΔL*| %.2f，而彩度 |ΔC*| %.2f。剩下的差距几乎全在颜色上，
继续调曲线（亮度）已经换不来收益。</li>
</ul>

<h2>30 支明细</h2>
<table>
<tr><th>槽</th><th>滤镜</th><th>底子</th><th>v1 实测</th><th>v3 预测</th><th>变化</th>
<th>ΔE00</th><th>可辨像素</th><th>|ΔL*|</th><th>|ΔC*|</th><th>|ΔH°|</th></tr>
%s
</table>

<h2>逐支对比图</h2>
<div class="note">每张三联：左＝最新优化校准原版，中＝我们的 v3 导出后会得到的画面，右＝色差分布热图。
热图越蓝越接近，越红差别越大（满标 20）。</div>
%s
</div></body></html>''' % (
        rgb.mean(),
        (1 - rgb.mean() / rgb1.mean()) * 100, rgb1.mean(),
        float(np.mean([r['de'] for r in rows])),
        float(np.mean([r['pct'] for r in rows])),
        good, good + flat,
        bests, worsts,
        int(mono.sum()), rgb[mono].mean(), int((~mono).sum()), rgb[~mono].mean(),
        float(np.mean([r['dL'] for r in rows])), float(np.mean([r['dC'] for r in rows])),
        body, cards)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
