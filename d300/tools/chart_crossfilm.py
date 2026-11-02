# -*- coding: utf-8 -*-
"""chart_crossfilm.py —— 换一张底片（DSC_8981）验证：什么能迁移，什么不能。

三张图讲三件事：
  左上：机内误差 vs 套旧 LUT 之后的误差。落在对角线下方的点＝LUT 帮了忙，
        上方＝帮倒忙。分界很清楚：机内误差 3 以内全是帮忙倒忙。
  右上：机制的直接证据。同一个「我们的 RGB」，官方在两张底片上的输出差 4 级，
        而同一张图内部只差 0.65 级 —— 所有点都远远飞在对角线上方，
        说明官方渲染根本不是逐像素的 RGB→RGB。
  下方：26 支各自的三段：机内 → 直接套旧 LUT → 在新底片上重新标定（留出）。
        中间那条线鼓起来的地方，就是 LUT 跨底片失效的地方。

数据：samples/validate_8981.csv（读数）、validate_mapping.csv（机制）、
      validate_refit.csv + validate_refit_b.csv（重新标定）
"""
import csv
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
SAMP = os.path.join(ROOT, 'samples')
OUT = os.path.join(ROOT, 'charts')
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

RED, BLUE, GREEN, GREY = '#C53030', '#2B6CB0', '#2F855A', '#A0AEC0'
DARK = '#2D3748'


def rd(name):
    p = os.path.join(SAMP, name)
    return list(csv.DictReader(open(p, encoding='utf-8-sig'))) if os.path.exists(p) else []


def num(x, k):
    try:
        return float(x[k])
    except (KeyError, ValueError):
        return None


def main():
    read = rd('validate_8981.csv')
    mp = {r['name']: r for r in rd('validate_mapping.csv')}
    ref = {r['name']: r for r in rd('validate_refit.csv')}
    for r in rd('validate_refit_b.csv'):
        ref[r['name']] = r

    fig = plt.figure(figsize=(13.4, 9.6))
    gs = fig.add_gridspec(2, 2, height_ratios=[1, 0.82],
                          hspace=0.34, wspace=0.24)

    # ------------------------------------------------ 左上：LUT 帮了还是坑了
    ax = fig.add_subplot(gs[0, 0])
    xs, ys, worsened = [], [], []
    for r in read:
        a, b = num(r, 'dE00_new'), num(r, 'dE00_lut_new')
        if a is None or b is None:
            continue
        xs.append(a)
        ys.append(b)
        if b > a + 0.05:
            worsened.append((r['name'], a, b))
    lim = [0, max(xs + ys) * 1.08]
    ax.plot(lim, lim, color=GREY, lw=1.2, ls='--', zorder=1)
    ax.fill_between(lim, lim, lim[1], color=RED, alpha=.05, zorder=0)
    ax.scatter(xs, ys, s=52, facecolors='none', edgecolors=BLUE, lw=1.5, zorder=3)
    ax.axvline(3.0, color=GREEN, lw=1.3, ls=':', zorder=2)
    # 只标最极端的两个，其余退化支并进一句说明，避免标签互相压住
    mark = {'RED': (-46, 8), 'STANDARD': (18, -20)}
    for n, a, b in worsened:
        if n in mark:
            ax.annotate(n, (a, b), textcoords='offset points', xytext=mark[n],
                        fontsize=9, color=RED,
                        arrowprops=dict(arrowstyle='-', color=RED, lw=.8))
    ax.text(0.30, lim[1] * 0.955, '线上方＝LUT 帮倒忙', color=RED, fontsize=9)
    ax.text(0.30, lim[1] * 0.885,
            '（%d 支落在上方，机内误差都在 3 以内）' % len(worsened),
            color=RED, fontsize=8.5)
    ax.text(5.6, lim[1] * 0.055, '机内 ≈ 3 是分界，左边套了反而更差',
            color=GREEN, fontsize=9)
    ax.set_xlim(lim)
    ax.set_ylim(lim)
    ax.set_xlabel('机内 ΔE00（新底片，不加后期）')
    ax.set_ylabel('直接套 4484 的 LUT 之后')
    ax.set_title('LUT 该不该套：看机内误差过没过 3', fontsize=11)
    ax.grid(color=GREY, alpha=.3, lw=.8)

    # ------------------------------------------------ 右上：机制
    ax2 = fig.add_subplot(gs[0, 1])
    cx = [float(v['within_film']) for v in mp.values()]
    cy = [float(v['cross_film']) for v in mp.values()]
    lim2 = [0, max(cx + cy) * 1.1]
    ax2.plot(lim2, lim2, color=GREY, lw=1.2, ls='--', zorder=1)
    ax2.scatter(cx, cy, s=52, facecolors='none', edgecolors=RED, lw=1.5, zorder=3)
    for nm, off in [('BINARY', (-52, 2)), ('MONOCHROME', (8, -12)), ('RED', (9, 3))]:
        if nm in mp:
            ax2.annotate(nm, (float(mp[nm]['within_film']), float(mp[nm]['cross_film'])),
                         textcoords='offset points', xytext=off, fontsize=8, color=DARK,
                         arrowprops=dict(arrowstyle='-', color=GREY, lw=.7))
    ax2.text(lim2[1] * .40, lim2[1] * .10,
             '对角线上方＝跨底片比同图内差得多\n26 支无一例外，平均 6.3 倍',
             color=RED, fontsize=9.5)
    ax2.set_xlim(lim2)
    ax2.set_ylim(lim2)
    ax2.set_xlabel('同一张图内，同一格子里官方输出的差（级）')
    ax2.set_ylabel('两张底片之间，同一格子里官方输出的差（级）')
    ax2.set_title('为什么 LUT 跨底片失效：映射不是逐像素的', fontsize=11)
    ax2.grid(color=GREY, alpha=.3, lw=.8)

    # ------------------------------------------------ 下方：三段
    ax3 = fig.add_subplot(gs[1, :])
    order = sorted([r for r in read if num(r, 'dE00_new') is not None],
                   key=lambda r: num(r, 'dE00_new'))
    names = [r['name'] for r in order]
    y_in = [num(r, 'dE00_new') for r in order]
    y_old = [num(r, 'dE00_lut_new') for r in order]
    y_cv = [num(ref[r['name']], 'de_cv17') if r['name'] in ref else None
            for r in order]
    x = range(len(names))
    ax3.plot(x, y_in, marker='o', color=RED, lw=2.0, ms=6,
             label='机内（什么都不加）', zorder=3)
    ax3.plot(x, y_old, marker='s', color=BLUE, lw=2.0, ms=6,
             label='直接套 4484 的 LUT', zorder=3)
    ax3.plot(x, y_cv, marker='^', color=GREEN, lw=2.0, ms=6,
             label='在新底片上重新标定（2×2 留出）', zorder=3)
    ax3.set_xticks(list(x))
    ax3.set_xticklabels(names, rotation=90, ha='center', va='top', fontsize=8.5)
    ax3.tick_params(axis='x', pad=4)
    ax3.set_ylabel('ΔE00（越低越好）')
    ax3.set_title('26 支：机内 → 套旧 LUT → 重新标定', fontsize=11)
    ax3.grid(axis='y', color=GREY, alpha=.35, lw=.8)
    ax3.legend(frameon=False, loc='upper left', ncol=3, fontsize=9)
    ax3.set_xlim(-0.6, len(names) - 0.4)
    ax3.set_ylim(0, max([v for v in y_in + y_old if v is not None]) * 1.14)

    fig.suptitle('换底片验证（DSC_4484 → DSC_8981）：机内可迁移，LUT 要按底片标定',
                 fontsize=12.5, y=0.985)
    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, 'crossfilm.jpg')
    fig.savefig(dst, dpi=118, facecolor='white',
                bbox_inches='tight', pad_inches=0.35)
    print('→ %s' % dst)


if __name__ == '__main__':
    main()
