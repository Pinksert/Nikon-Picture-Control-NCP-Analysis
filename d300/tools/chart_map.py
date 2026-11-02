# -*- coding: utf-8 -*-
"""chart_map.py —— 跨底片映射：三个假设被否/被确认的过程，和最后剩下的那一块。

四栏：
  左上  换输入域没用：域 O（我们的成片）4.07/0.65 = 6.3x，域 A（中性锚点）4.80/1.00 = 4.8x
  右上  覆盖不足是真的：未覆盖比例 vs 补空洞收益，r = 0.76
  左下  26 支的方案阶梯：直接套 → 补空洞（免费）→ 补+逐支整图补偿 → 按图重标定
  右下  单锚点自标定为什么不成立：一支参考滤镜解出的 g，套到别的支上会互相打架

数据：samples/crossfilm_domain.csv / crossfilm_coverage.csv /
      crossfilm_map.csv / validate_refit.csv
"""
import csv
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
SAMP = os.path.join(ROOT, 'samples')
OUT = os.path.join(ROOT, 'charts')
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

RED, BLUE, GREEN, GREY = '#C53030', '#2B6CB0', '#2F855A', '#A0AEC0'
ORANGE = '#B7791F'
DARK = '#2D3748'


def rd(name):
    p = os.path.join(SAMP, name)
    return list(csv.DictReader(open(p, encoding='utf-8-sig'))) if os.path.exists(p) else []


def main():
    dom = rd('crossfilm_domain.csv')
    cov = rd('crossfilm_coverage.csv')
    mp = rd('crossfilm_map.csv')
    ref = rd('validate_refit.csv')

    fig = plt.figure(figsize=(13.6, 10.2))
    gs = fig.add_gridspec(2, 2, hspace=0.34, wspace=0.26,
                          left=0.075, right=0.975, top=0.90, bottom=0.07)

    # ---------------- 左上：换输入域 ----------------
    ax = fig.add_subplot(gs[0, 0])
    lab = ['我们的成片\n（域 O）', '中性锚点\n（域 A）']
    cross = [np.mean([float(r['O_cross']) for r in dom]),
             np.mean([float(r['A_cross']) for r in dom])]
    within = [np.mean([float(r['O_within']) for r in dom]),
              np.mean([float(r['A_within']) for r in dom])]
    x = np.arange(2)
    ax.bar(x - 0.19, cross, 0.36, color=RED, label='跨底片')
    ax.bar(x + 0.19, within, 0.36, color=GREY, label='同图内（噪声下界）')
    for i in range(2):
        ax.text(x[i] - 0.19, cross[i] + 0.1, '%.2f' % cross[i], ha='center',
                fontsize=10, color=RED, fontweight='bold')
        ax.text(x[i] + 0.19, within[i] + 0.1, '%.2f' % within[i], ha='center',
                fontsize=10, color=DARK)
        ax.text(x[i] - 0.19, cross[i] * 0.5, '跨片/同图\n%.1f 倍'
                % (cross[i] / within[i]), ha='center', va='center',
                fontsize=10.5, color='white', fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(lab, fontsize=10)
    ax.set_ylim(0, 6.0)
    ax.set_xlim(-0.55, 1.55)
    ax.set_ylabel('同一格输入下，官方输出的格子均值差（级）', fontsize=10)
    ax.set_title('① 换输入域没用：不确定性不在「我们的成片」里丢的',
                 fontsize=12.5, fontweight='bold', color=DARK, loc='left')
    ax.legend(fontsize=9, frameon=False, loc='upper right')
    ax.grid(axis='y', alpha=0.25)
    ax.set_axisbelow(True)

    # ---------------- 右上：覆盖率 ----------------
    ax = fig.add_subplot(gs[0, 1])
    unc = np.array([float(r['uncovered']) * 100 for r in cov])
    gain = np.array([float(r['dE00_raw']) - float(r['dE00_fill']) for r in cov])
    ax.scatter(unc, gain, s=34, c=BLUE, alpha=0.75, edgecolor='white', linewidth=0.6)
    k, b = np.polyfit(unc, gain, 1)
    xs = np.linspace(0, unc.max() * 1.05, 20)
    ax.plot(xs, k * xs + b, color=RED, lw=1.6, ls='--')
    r = np.corrcoef(unc, gain)[0, 1]
    ax.text(0.04, 0.92, 'r = %.2f' % r, transform=ax.transAxes, fontsize=13,
            color=RED, fontweight='bold')
    ax.axhline(0, color=DARK, lw=0.8, alpha=0.4)
    ax.set_xlabel('目标底片落在「标定图没采到」的格子里的比例（%）', fontsize=10)
    ax.set_ylabel('补空洞带来的改善（ΔE00 减少）', fontsize=10)
    ax.set_title('② 空格子是真的一块：表没铺到的地方等于没查表',
                 fontsize=12.5, fontweight='bold', color=DARK, loc='left')
    ax.grid(alpha=0.25)
    ax.set_axisbelow(True)

    # ---------------- 左下：方案阶梯 ----------------
    ax = fig.add_subplot(gs[1, 0])
    plans = [('直接套', '直接套', GREY),
             ('补空洞', '补空洞\n（免费）', GREEN),
             ('补+逐支后仿射', '整图补偿\n（逐支）', BLUE),
             ('补+共用预仿射', '整图补偿\n（一支参考）', ORANGE)]
    vals = []
    for key, _, _ in plans:
        v = [float(x['value']) for x in mp if x['plan'] == key and x['ref'] in ('-', 'NEUTRAL')]
        vals.append(np.mean(v))
    # 按图重标定（留出）—— docs/25 的 2.16
    cv = [float(x['de_cv17']) for x in ref if x.get('de_cv17') not in (None, '', 'nan')]
    recal = float(np.mean(cv)) if cv else None
    names = [p[1] for p in plans] + (['按图重标定\n（26 支全导）'] if recal else [])
    heights = vals + ([recal] if recal else [])
    cols = [p[2] for p in plans] + ([RED] if recal else [])
    xs = np.arange(len(heights))
    ax.bar(xs, heights, 0.58, color=cols)
    for i, h in enumerate(heights):
        ax.text(xs[i], h + 0.06, '%.2f' % h, ha='center', fontsize=10,
                fontweight='bold', color=DARK)
    ax.set_xticks(xs)
    ax.set_xticklabels(names, fontsize=9)
    ax.set_ylim(0, max(heights) * 1.22)
    ax.set_ylabel('26 支 × 2 方向的平均 ΔE00', fontsize=10)
    ax.set_title('③ 能白拿的只有「补空洞」这一块，其余都得付导出成本',
                 fontsize=12.5, fontweight='bold', color=DARK, loc='left')
    ax.grid(axis='y', alpha=0.25)
    ax.set_axisbelow(True)

    # ---------------- 右下：单锚点为什么不行 ----------------
    ax = fig.add_subplot(gs[1, 1])
    def per(kind, ref_):
        d = {}
        for x in mp:
            if x['plan'] == kind and x['ref'] == ref_:
                d.setdefault(x['name'], []).append(float(x['value']))
        return {k: np.mean(v) for k, v in d.items()}
    b0 = per('补空洞', '-')
    bp = per('补+共用预仿射', 'NEUTRAL')
    names2 = sorted(b0, key=lambda n: b0[n])
    delta = np.array([bp[n] - b0[n] for n in names2])
    ys = np.arange(len(names2))
    cols2 = [GREEN if d < 0 else RED for d in delta]
    ax.barh(ys, delta, 0.62, color=cols2)
    ax.axvline(0, color=DARK, lw=0.9)
    ax.set_yticks(ys)
    ax.set_yticklabels(names2, fontsize=8)
    ax.set_ylim(-0.8, len(names2) - 0.2)
    ax.invert_yaxis()
    ax.set_xlabel('叠加「一支参考滤镜解出的整图 g」后的净变化（ΔE00，负=变好）', fontsize=9.5)
    ax.set_title('④ 一支参考滤镜解出的 g：%d 支变好、%d 支变坏'
                 % (int((delta < 0).sum()), int((delta > 0).sum())),
                 fontsize=12.5, fontweight='bold', color=DARK, loc='left')
    ax.grid(axis='x', alpha=0.25)
    ax.set_axisbelow(True)

    fig.suptitle('跨底片映射：三个假设，只有一个能免费兑现',
                 fontsize=15, fontweight='bold', color=DARK, y=0.965)
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, 'crossfilm_map.jpg')
    fig.savefig(p, dpi=150, facecolor='white')
    print('→ %s' % p)


if __name__ == '__main__':
    main()
