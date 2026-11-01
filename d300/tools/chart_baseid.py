# -*- coding: utf-8 -*-
"""chart_baseid.py —— 「底子这一层被曲线吞掉了」的证据图。

只画一件事：26 支按「官方用的底子」分成三组，看残差怎么分布。

  创意底·彩色  官方底子 0x0801-0x0814，我们换成 0x0001 STANDARD   → 16 支
  创意底·单色  官方底子 0x0811-0x0814，我们换成 0x064D MONOCHROME → 4 支
  基础底       官方底子本来就是 0001/03C2/00C3/028E/04C7/064D     → 6 支

左图：平均差。右图：彩度偏差（带符号）。右图才是要害——单色组几乎落在 0 上，
彩色组向两侧散开，说明「影调搬得动、色彩搬不动」。

数据：samples/metrics_real.csv（真渲染实测）+ 滤镜/*.NP3（官方底子编号）
"""
import csv
import glob
import os
import struct
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(ROOT, '..', 'np3tool'))
sys.path.insert(0, HERE)
import np3core as C                                            # noqa: E402
import optimize_v2 as A                                        # noqa: E402

OUT = os.path.join(ROOT, 'charts')
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

C_RED, C_GREEN, C_BLUE, C_GREY = '#C53030', '#2F855A', '#2B6CB0', '#718096'
GROUPS = [
    ('创意底·彩色', C_RED, '官方底子 0x0801–0x080C\n我们一律换成 STANDARD'),
    ('创意底·单色', C_GREEN, '官方底子 0x0811–0x0814\n我们换上 MONOCHROME'),
    ('基础底', C_BLUE, '官方底子本来就是基础底子\n我们没换'),
]
MONO = ('CHARCOAL', 'GRAPHITE', 'BINARY', 'CARBON')


def load():
    real = {}
    for r in csv.DictReader(open(os.path.join(ROOT, 'samples', 'metrics_real.csv'),
                                 encoding='utf-8-sig')):
        real[r['name'].upper()] = r
    rows = []
    for f in sorted(glob.glob(os.path.join(ROOT, '..', '滤镜', '*.NP3'))):
        d = C.parse_np(open(f, 'rb').read())
        nm = d['name'].upper()
        r = real.get(nm)
        if not r:
            continue
        base = d['base']
        if 0x0801 <= base <= 0x0814:
            g = 1 if nm in MONO else 0
        else:
            g = 2
        rows.append(dict(name=nm, base=base, g=g,
                         mad=float(r['mad']), dC=float(r['dC_signed'])))
    return rows


def panel(ax, rows, key, title, ylab, zero=False, label_n=1):
    means = []
    for i, (gname, col, _) in enumerate(GROUPS):
        v = np.array([r[key] for r in rows if r['g'] == i])
        if not len(v):
            means.append(0.0)
            continue
        x = i + np.linspace(-0.17, 0.17, len(v))
        ax.scatter(x, v, s=58, color=col, alpha=0.85, edgecolor='white',
                   linewidth=0.9, zorder=3)
        mu = v.mean()
        means.append(mu)
        ax.hlines(mu, i - 0.36, i + 0.36, color=col, lw=3.2, zorder=4)
        # 只标最极端的一支，横向错开，避免与其它标注打架
        order = np.argsort(-np.abs(v))[:label_n]
        sub = [r for r in rows if r['g'] == i]
        for k, j in enumerate(order):
            ax.annotate(sub[j]['name'], (x[j], v[j]), textcoords='offset points',
                        xytext=(0 if label_n == 1 else (-30 if k == 0 else 30),
                                10 if v[j] > mu else -17),
                        ha='center', fontsize=8.6, color=col, fontweight='bold')

    if zero:
        ax.axhline(0, color='#A0AEC0', lw=1.3, zorder=1)
    ax.set_xticks(range(len(GROUPS)))
    ax.set_xticklabels(['%s\n%d 支 · 均值 %s'
                        % (g[0], sum(1 for r in rows if r['g'] == i),
                           ('%.2f' if key == 'mad' else '%+.2f') % means[i])
                        for i, g in enumerate(GROUPS)], fontsize=10.2)
    ax.set_title(title, fontsize=13.5, color='#1A202C', pad=10)
    ax.set_ylabel(ylab, fontsize=11.5)
    ax.set_xlim(-0.55, len(GROUPS) - 0.45)
    ax.grid(axis='y', color='#E2E8F0', lw=0.9)
    ax.set_axisbelow(True)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    ax.spines['left'].set_color('#CBD5E0')
    ax.spines['bottom'].set_color('#CBD5E0')


def main():
    rows = load()
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12.4, 6.1), dpi=118)
    fig.patch.set_facecolor('white')

    panel(a1, rows, 'mad', '平均差（级）：创意底子的支普遍更差', '三通道平均绝对差（级）')
    a1.set_ylim(0, max(r['mad'] for r in rows) * 1.22)

    panel(a2, rows, 'dC', '彩度偏差（带符号）：只有彩色创意底子向两侧散开',
          '我们的 C* − 官方的 C*（单位：彩度）', zero=True)
    a2.set_ylim(-10.2, 8.2)

    # 每组标准差，写在右图下方
    sd = [np.std([r['dC'] for r in rows if r['g'] == i], ddof=1) for i in range(3)]
    a2.text(0.02, 0.03, 'ΔC* 标准差：' + ' / '.join(
        '%s %.2f' % (GROUPS[i][0].split('·')[-1], sd[i]) for i in range(3)),
        transform=a2.transAxes, fontsize=10, color='#4A5568')

    fig.text(0.5, 0.012,
             '26 支真渲染实测（DSC_4484，NX Studio 1.7.1）。'
             '左图看总体，右图看机制：单色组落在 0 附近 → 曲线能搬影调；'
             '彩色创意底子组散开 → 曲线搬不动底子那层色彩变换。',
             ha='center', fontsize=10, color='#4A5568')
    fig.subplots_adjust(left=0.075, right=0.985, top=0.87, bottom=0.255, wspace=0.22)

    p = os.path.join(OUT, 'baseid-gap.jpg')
    fig.savefig(p, facecolor='white', pil_kwargs={'quality': 93})
    print('已写 %s' % p)
    for i, g in enumerate(GROUPS):
        v = [r['mad'] for r in rows if r['g'] == i]
        c = [r['dC'] for r in rows if r['g'] == i]
        print('  %-12s %2d 支  平均差 %.2f  ΔC* %+.2f  标准差 %.2f'
              % (g[0], len(v), np.mean(v), np.mean(c), np.std(c, ddof=1)))


if __name__ == '__main__':
    main()
