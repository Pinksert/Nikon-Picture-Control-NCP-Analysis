# -*- coding: utf-8 -*-
"""chart_mono_filter.py —— 单色滤镜五档的扫描曲线（BINARY / MONOCHROME）。

横轴是滤镜档（关/黄/橙/红/绿），纵轴 ΔE00（dE_either，与 mono_refit 同一把尺子）。
重点是那条 V 形：黄/橙/红一路恶化，绿突然掉头 —— 方向才是关键，档位强弱不是。

数据：samples/probe_monofilter.csv（probe_monofilter_analyze.py）
"""
import csv
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
OUT = os.path.join(ROOT, 'charts')
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

RED, BLUE, GREY = '#C53030', '#2B6CB0', '#A0AEC0'
LABELS = ['关\n0x80', '黄\n0x81', '橙\n0x82', '红\n0x83', '绿\n0x84']
ORDER = ['F0', 'F1', 'F2', 'F3', 'G']


def main():
    rows = list(csv.DictReader(open(os.path.join(ROOT, 'samples', 'probe_monofilter.csv'),
                                    encoding='utf-8-sig')))
    ser = {}
    for r in rows:
        ser.setdefault(r['group'], {})[r['filter']] = (float(r['de_either']),
                                                       int(r['disagree_px']))

    fig, axes = plt.subplots(1, 2, figsize=(12.6, 4.4),
                             gridspec_kw=dict(width_ratios=[1.25, 1]))
    ax = axes[0]
    for name, color, mk in [('BINARY', RED, 'o'), ('MONOCHROME', BLUE, 's')]:
        y = [ser[name][k][0] for k in ORDER]
        ax.plot(range(5), y, marker=mk, color=color, lw=2.2, ms=7, label=name, zorder=3)
        for i, v in enumerate(y):
            ax.annotate('%.2f' % v, (i, v), textcoords='offset points', xytext=(0, 16),
                        ha='center', fontsize=9, color=color)
        best = min(range(5), key=lambda i: y[i])
        ax.scatter([best], [y[best]], s=190, facecolors='none', edgecolors=color,
                   lw=1.6, zorder=1)
    ax.set_xticks(range(5))
    ax.set_xticklabels(LABELS, fontsize=9)
    ax.set_xlim(-0.35, 4.35)
    ax.set_ylabel('ΔE00（dE_either，越低越好）')
    ax.set_title('单色滤镜五档：三个越走越远，绿掉头', fontsize=11)
    ax.grid(axis='y', color=GREY, alpha=.4, lw=.8)
    ax.legend(frameon=False, loc='upper left')
    ax.set_ylim(0, 20.4)
    ax.text(0.5, -0.30, 'BINARY：关 6.98 → 绿 6.24（−0.74，−10.6%）｜ 黄 8.73 / 橙 14.67 / 红 17.86\n'
                        'MONOCHROME：关 1.18 最优 → 绿 1.31（绿只在 BINARY 上有效）',
            transform=ax.transAxes, ha='center', va='top', fontsize=8.8, color='#4A5568')

    ax2 = axes[1]
    w = .36
    for i, (name, color) in enumerate([('BINARY', RED), ('MONOCHROME', BLUE)]):
        n = [ser[name][k][1] for k in ORDER]
        ax2.bar([x + (i - .5) * w for x in range(5)], n, width=w, color=color,
                alpha=.85, label=name)
    ax2.set_xticks(range(5))
    ax2.set_xticklabels(LABELS, fontsize=9)
    ax2.set_ylabel('「白/黑」判决分歧像素数')
    ax2.set_title('分歧像素：绿档抹平了色偏，总数没降', fontsize=11)
    ax2.grid(axis='y', color=GREY, alpha=.4, lw=.8)
    ax2.legend(frameon=False)
    ax2.set_ylim(0, 8200)

    fig.subplots_adjust(bottom=0.26, top=0.9, wspace=0.28)
    p = os.path.join(OUT, 'mono-filter.jpg')
    fig.savefig(p, dpi=150, facecolor='white')
    print('-> %s' % p)


if __name__ == '__main__':
    main()
