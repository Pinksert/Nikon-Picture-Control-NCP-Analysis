# -*- coding: utf-8 -*-
"""chart_mono.py —— 单色重拟合的两张图（合成一张）。

左图  5 支单色：现状 / 重拟合（全量）/ 2×2 留出 的 ΔE00
右图  BINARY 分歧像素的颜色成分 —— 「我们判白、官方判黑」与「官方判白、我们判黑」
      两组里，主导通道是 R / G / B 的比例。红白蓝黑就是这个样子。

数据：samples/mono_refit.csv（mono_refit.py）
      samples/mono_disagree.csv（mono_refit.py --evidence）
"""
import csv
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
OUT = os.path.join(ROOT, 'charts')
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

RED, BLUE, GREY, ORANGE, GREEN = '#C53030', '#2B6CB0', '#A0AEC0', '#B7791F', '#2F855A'


def load():
    rows = list(csv.DictReader(open(os.path.join(ROOT, 'samples', 'mono_refit.csv'),
                                    encoding='utf-8-sig')))
    ev = list(csv.DictReader(open(os.path.join(ROOT, 'samples', 'mono_disagree.csv'),
                                  encoding='utf-8-sig')))
    return rows, ev


def main():
    rows, ev = load()
    names = [r['name'] for r in rows]
    cur = [float(r['de_either_before']) for r in rows]
    fit = [float(r['de_either_after']) for r in rows]
    cv = [float(r['cv_either']) for r in rows]
    refit = [r['refit'] == '1' for r in rows]

    fig, ax = plt.subplots(1, 2, figsize=(13.2, 4.6),
                           gridspec_kw={'width_ratios': [1.75, 1]})

    # ---------------- 左：哑铃图（现状 → 拟合，另一个点 = 留出）
    y = np.arange(len(names))[::-1]
    for i, yy in enumerate(y):
        ax[0].plot([cur[i], max(fit[i], cv[i])], [yy, yy], color='#CBD5E0', lw=2.2, zorder=1)
        ax[0].scatter(cur[i], yy, s=95, color=GREY, zorder=3,
                      label='现状（release）' if i == 0 else None)
        ax[0].scatter(fit[i], yy, s=95, color=BLUE, zorder=3,
                      label='重拟合（全量）' if i == 0 else None)
        ax[0].scatter(cv[i], yy, s=115, facecolor='white', edgecolor=ORANGE,
                      linewidth=2.0, zorder=4,
                      label='2×2 留出（没见过的那块）' if i == 0 else None)
        ax[0].text(max(fit[i], cv[i]) + 0.4, yy,
                   '%.2f / %.2f%s' % (fit[i], cv[i], '' if refit[i] else '　不改'),
                   ha='left', va='center', fontsize=8.8,
                   color=(BLUE if refit[i] else RED))
    ax[0].set_yticks(y)
    ax[0].set_yticklabels(['%s%s   %.2f' % (n, '  •' if r else '', c)
                           for n, r, c in zip(names, refit, cur)], fontsize=9.5)
    ax[0].set_xlabel('ΔE00（只在两边都剪裁时排除）　← 越左越好')
    ax[0].set_title('单色 5 支：只有两支的留出点比现状更左（• 已改写）', fontsize=11, pad=12)
    ax[0].legend(fontsize=8.5, loc='upper right', frameon=False, handletextpad=0.4)
    ax[0].set_xlim(0, 13.4)
    ax[0].grid(axis='x', color='#E2E8F0', lw=0.8)
    ax[0].set_axisbelow(True)
    for sp in ('top', 'right', 'left'):
        ax[0].spines[sp].set_visible(False)
    ax[0].tick_params(axis='y', length=0)

    # ---------------- 右：分歧像素的颜色成分
    labels = [e['class'] for e in ev]
    r_ = [float(e['R']) for e in ev]
    g_ = [float(e['G']) for e in ev]
    b_ = [float(e['B']) for e in ev]
    x = np.arange(len(labels))
    w = 0.5
    ax[1].bar(x, r_, w, color=RED, label='R 主导')
    ax[1].bar(x, g_, w, bottom=r_, color=GREEN, label='G 主导')
    ax[1].bar(x, b_, w, bottom=np.array(r_) + np.array(g_), color=BLUE, label='B 主导')
    for i in range(len(labels)):
        for v, base, col in ((r_[i], 0, 'white'), (g_[i], r_[i], 'white'),
                             (b_[i], r_[i] + g_[i], 'white')):
            if v >= 7:
                ax[1].text(x[i], base + v / 2, '%.0f%%' % v, ha='center', va='center',
                           fontsize=9, color=col)
    ax[1].set_xticks(x)
    ax[1].set_xticklabels([s.replace(' ', '\n') for s in labels], fontsize=9)
    ax[1].set_ylabel('占该组像素的百分比')
    ax[1].set_ylim(0, 100)
    ax[1].set_title('BINARY 判得不一样的像素，颜色不同', fontsize=11, pad=10)
    ax[1].legend(fontsize=8.5, frameon=False, loc='upper center', ncol=3,
                 bbox_to_anchor=(0.5, -0.16))
    ax[1].grid(axis='y', color='#E2E8F0', lw=0.8)
    ax[1].set_axisbelow(True)
    for s in ('top', 'right'):
        ax[1].spines[s].set_visible(False)

    fig.tight_layout()
    fn = os.path.join(OUT, 'mono-refit.jpg')
    fig.savefig(fn, dpi=155, facecolor='white')
    print('->', fn)





def binary_pair():
    """charts/mono-binary-pair.jpg —— BINARY 的三联图。

    左：我们  |  中：官方  |  右：分歧图
    右图把「我们判白、官方判黑」涂红，「官方判白、我们判黑」涂蓝，其余用原图淡化作底。
    红蓝各占一边、而且互相咬合，就是第四节那张成分表的样子。
    """
    import mono_refit as M
    O, R = M.pair(19, 'BINARY')
    co, cr = O, R          # 用整幅：红蓝在整幅上的分布才有代表性
    gray_ = co.mean(2, keepdims=True)
    wo = co.min(2) > 253
    wr = cr.min(2) > 253
    diff = np.repeat(gray_ * 0.75 + 35, 3, axis=2)
    diff[wo & ~wr] = [197, 48, 48]
    diff[wr & ~wo] = [43, 108, 176]

    panels = [co, cr, diff]
    titles = ['我们（release）', '官方 NP3', '分歧：红=我们白/官方黑　蓝=官方白/我们黑']

    up = 2
    fig, ax = plt.subplots(1, 3, figsize=(13.0, 3.5))
    for a, img, t in zip(ax, panels, titles):
        a.imshow(np.clip(img, 0, 255).astype('uint8'),
                 interpolation='nearest')
        a.set_title(t, fontsize=10.5, pad=8)
        a.set_xticks([])
        a.set_yticks([])
        for s in a.spines.values():
            s.set_color('#CBD5E0')
    fig.tight_layout()
    fn = os.path.join(OUT, 'mono-binary-pair.jpg')
    fig.savefig(fn, dpi=160, facecolor='white')
    print('->', fn)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
    binary_pair()
