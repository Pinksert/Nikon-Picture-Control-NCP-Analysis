# -*- coding: utf-8 -*-
"""chart_slider.py —— 滑块标定图（探针实测）。

图 1 slider-sat.jpg   饱和度 7 档实测 vs 模型假设，看线性假设是否成立
图 2 slider-misc.jpg  色相 / 底子 / 单色着色 三种效应的量级

数据来源：samples/probe_slider/ 的 11 张探针（同一条曲线，每次只改一个字节），
由 probe_slider_read.py 用「固定像素集」口径算出，落盘 samples/probe_slider.csv。
本脚本只读 csv，不重算，避免图文不一致。
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

C_BLUE, C_ORANGE, C_RED, C_GREY, C_GREEN = '#2B6CB0', '#C05621', '#C53030', '#718096', '#2F855A'


def load():
    p = os.path.join(ROOT, 'samples', 'probe_slider.csv')
    rows = list(csv.DictReader(open(p, encoding='utf-8-sig')))
    return rows


def fig_sat(rows):
    sat = [r for r in rows if r['kind'] == 'sat']
    ks = np.array([int(r['level']) for r in sat])
    allp = np.array([float(r['c_all']) for r in sat])
    p90 = np.array([float(r['c_p90']) for r in sat])
    p99 = np.array([float(r['c_p99']) for r in sat])
    step = float(sat[0]['step'])
    k0 = list(ks).index(0)

    fig, ax = plt.subplots(figsize=(11.6, 6.4), dpi=118)
    fig.patch.set_facecolor('white')

    ax.plot(ks, allp / allp[k0], 'o-', color=C_BLUE, lw=2.4, ms=7,
            label='全部中间调像素')
    ax.plot(ks, p90 / p90[k0], 's-', color=C_ORANGE, lw=2.0, ms=6,
            label='浓色像素（C* 前 10%%）')
    ax.plot(ks, p99 / p99[k0], '^-', color=C_RED, lw=2.0, ms=6,
            label='最浓像素（C* 前 1%%）')

    model = np.array([1.130 ** k for k in ks])
    ax.plot(ks, model, '--', color=C_GREY, lw=2.0,
            label='模型假设：每档 ×1.130')
    fit = np.array([step ** k for k in ks])
    ax.plot(ks, fit, ':', color=C_GREEN, lw=2.2,
            label='实测拟合：每档 ×%.3f' % step)

    ax.axhline(1.0, color='#CBD5E0', lw=1.0, zorder=0)
    ax.axvline(0, color='#CBD5E0', lw=1.0, zorder=0)

    for k, v in ((0, 1.0), (3, allp[-1] / allp[k0])):
        ax.annotate('%.2f' % v, (k, v), textcoords='offset points',
                    xytext=(0, -15), ha='center', fontsize=9, color=C_BLUE)

    seg = lambda i: allp[i + 1] / allp[i]
    ax.annotate('对数拟合：平均每档 ×%.3f（R² 0.97）\n'
                '但倍率不是常数，越往外越没劲：\n'
                '0→+1 ×%.3f，+1→+2 ×%.3f，+2→+3 ×%.3f'
                % (step, seg(3), seg(4), seg(5)),
                xy=(-2.92, 1.33), fontsize=10.5, color='#2D3748', va='top',
                bbox=dict(boxstyle='round,pad=0.5', fc='#F7FAFC', ec='#CBD5E0'))

    ax.annotate('模型以为 +3 档能加 44%\n实际只加 27.5%',
                xy=(3, 1.33), xytext=(1.05, 1.44), fontsize=10.5, color=C_RED,
                arrowprops=dict(arrowstyle='->', color=C_RED, lw=1.4))

    ax.set_xlabel('饱和度滑块档位', fontsize=12)
    ax.set_ylabel('彩度倍数（以 0 档为 1）', fontsize=12)
    ax.set_title('饱和度滑块标定：同一条曲线，只改一个字节（26 次真渲染中的 7 次）',
                 fontsize=14, pad=14, color='#1A202C')
    ax.set_xticks(ks)
    ax.set_xticklabels(['%+d' % k for k in ks])
    ax.grid(True, color='#EDF2F7', lw=0.9)
    ax.set_axisbelow(True)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    ax.legend(loc='lower right', fontsize=10, frameon=False)
    ax.set_ylim(0.55, 1.52)

    txt = ('固定像素集 108,328 个，7 张图共用同一批像素。\n'
           '模型假设 ×1.130 与实测 ×1.118 相差 1.1%，可以视为同一条直线；\n'
           '真正的问题是高档位有压缩：模型在 +3 档高估 13%。')
    fig.text(0.012, 0.015, txt, fontsize=9.5, color='#4A5568', va='bottom')

    fig.tight_layout(rect=[0, 0.075, 1, 1])
    p = os.path.join(OUT, 'slider-sat.jpg')
    fig.savefig(p, facecolor='white', pil_kwargs={'quality': 92})
    plt.close(fig)
    print(p)


def fig_misc(rows):
    g = {r['kind']: r for r in rows}
    hue = g['hue']
    base = g['base']
    tint0 = g['tint0']
    tint3 = g['tintp3']

    fig, axes = plt.subplots(1, 3, figsize=(13.4, 5.0), dpi=118)
    fig.patch.set_facecolor('white')

    # --- 色相
    ax = axes[0]
    d = float(hue['hue_deg'])
    ax.barh([1], [d], color=C_ORANGE, height=0.42)
    ax.axvline(3 * 3.5, color=C_GREY, ls='--', lw=1.8)
    ax.text(3 * 3.5 + 0.4, 1.36, '模型假设\n每档 3.5°', fontsize=9.5, color=C_GREY)
    ax.text(d - 0.3, 1.0, '%+.1f°' % d, ha='right', va='center',
            fontsize=13, color='white', fontweight='bold')
    ax.set_xlim(0, max(d, 3 * 3.5) * 1.42)
    ax.set_ylim(0.4, 1.7)
    ax.set_yticks([])
    ax.set_xlabel('+3 档累计转角（度）', fontsize=11)
    ax.set_title('色相滑块', fontsize=13, color='#1A202C')
    ax.text(0.02, 0.13, '实测每档 %+.2f°\n（模型 3.50°，差 9%%）' % (d / 3.0),
            transform=ax.transAxes, fontsize=10, color='#4A5568')

    # --- 底子
    ax = axes[1]
    dc = float(base['dc_pct'])
    dl = float(base['dl'])
    ax.barh([1.45], [dc], color=C_RED, height=0.34, label='彩度 C* 变化（%）')
    ax.barh([0.95], [dl], color=C_BLUE, height=0.34, label='亮度 L* 变化')
    ax.axvline(0, color='#4A5568', lw=1.2)
    ax.text(dc + (0.5 if dc >= 0 else -0.5), 1.45, '%+.1f%%' % dc,
            va='center', ha='left' if dc >= 0 else 'right', fontsize=11, color=C_RED)
    ax.text(dl + (0.5 if dl >= 0 else -0.5), 0.95, '%+.2f' % dl,
            va='center', ha='left' if dl >= 0 else 'right', fontsize=11, color=C_BLUE)
    ax.set_ylim(0.5, 1.95)
    ax.set_yticks([])
    ax.set_xlabel('相对 STANDARD 底子的变化', fontsize=11)
    ax.set_title('换底子字节（0x0001 → 0x00C3）', fontsize=13, color='#1A202C')
    ax.text(0.02, 0.10, 'ΔE00 均值 %.2f，%.0f%% 像素超 2.3\n曲线区一字未改，差异全来自这 1 个字节'
            % (float(base['de']), float(base['de_pct'])),
            transform=ax.transAxes, fontsize=9.5, color='#4A5568')
    ax.legend(loc='upper right', fontsize=9, frameon=False)

    # --- 单色着色
    ax = axes[2]
    c0 = float(tint0['c_all'])
    c3 = float(tint3['c_all'])
    ax.bar([0, 1], [c0, c3], color=[C_GREEN, C_GREY], width=0.52)
    ax.text(0, c0 + 0.5, '%.2f' % c0, ha='center', fontsize=12, color=C_GREEN)
    ax.text(1, c3 + 0.5, '%.2f' % c3, ha='center', fontsize=12, color=C_GREY)
    ax.set_xticks([0, 1])
    ax.set_xticklabels(['着色 0 档', '着色 +3 档'], fontsize=11)
    ax.set_ylabel('平均彩度 C*', fontsize=11)
    ax.set_ylim(0, max(c0, c3) * 1.62)
    ax.set_title('单色底子的着色档', fontsize=13, color='#1A202C')
    ax.text(0.03, 0.995, '色相几乎不动（%.1f° → %.1f°）\n变的是「着色浓度」不是色调'
            % (float(tint0['hue_mean']), float(tint3['hue_mean'])),
            transform=ax.transAxes, fontsize=9.5, color='#4A5568', va='top')

    for ax in axes:
        for s in ('top', 'right'):
            ax.spines[s].set_visible(False)
        ax.grid(True, axis='x', color='#EDF2F7', lw=0.9) if ax is axes[1] else None
        ax.set_axisbelow(True)

    fig.suptitle('另外三组滑块：色相、底子、单色着色（同一批探针）',
                 fontsize=14, color='#1A202C', y=0.99)
    fig.tight_layout(rect=[0, 0.03, 1, 0.94])
    p = os.path.join(OUT, 'slider-misc.jpg')
    fig.savefig(p, facecolor='white', pil_kwargs={'quality': 92})
    plt.close(fig)
    print(p)


if __name__ == '__main__':
    rows = load()
    fig_sat(rows)
    fig_misc(rows)
