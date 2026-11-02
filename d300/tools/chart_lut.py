# -*- coding: utf-8 -*-
"""chart_lut.py —— 「颜色这一层交给后期」的三张图。

图 1  lut-gap-rank.jpg  26 支逐支：现在 vs 套上残差 LUT 之后（ΔE00）
图 2  lut-ceiling.jpg   三层天花板：现在的机内 / 机内同类工具的上界 / 曲线 + LUT
图 3  lut-chroma.jpg    彩度残差：现在 vs 上界 vs LUT（带符号，看往哪边偏）

数据：samples/metrics_lut.csv（lut_fit.py）、samples/oracle_global.csv（oracle_global.py）、
      samples/metrics_real.csv（现状，report_real.py 产）
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

C_RED, C_GREEN, C_BLUE, C_GREY, C_ORANGE = '#C53030', '#2F855A', '#2B6CB0', '#A0AEC0', '#B7791F'


def rd(name):
    p = os.path.join(ROOT, 'samples', name)
    if not os.path.exists(p):
        print('缺数据：%s' % p)
        return []
    return list(csv.DictReader(open(p, encoding='utf-8-sig')))


def fig_rank(rows):
    rows = sorted(rows, key=lambda r: -float(r['dE00_before']))
    lab = [r['name'] for r in rows]
    b = np.array([float(r['dE00_before']) for r in rows])
    a = np.array([float(r['dE00_after']) for r in rows])
    y = np.arange(len(rows))[::-1]
    fig, ax = plt.subplots(figsize=(8.6, 0.30 * len(rows) + 1.5), dpi=170)
    ax.barh(y + 0.19, b, height=0.36, color=C_GREY, label='现在的 NCP（机内）')
    ax.barh(y - 0.19, a, height=0.36, color=C_BLUE, label='NCP + 残差 3D LUT（后期）')
    ax.set_yticks(y, lab, fontsize=8)
    ax.set_xlabel('ΔE00（越小越好，2.3 为可辨阈值）', fontsize=9)
    ax.axvline(2.3, color=C_RED, lw=0.8, ls='--')
    ax.axvline(b.mean(), color=C_GREY, lw=0.8, ls=':')
    ax.axvline(a.mean(), color=C_BLUE, lw=0.8, ls=':')
    ax.text(b.mean(), len(rows) - 0.2, ' 均值 %.2f' % b.mean(), color=C_GREY, fontsize=8)
    ax.text(a.mean(), -1.2, ' 均值 %.2f' % a.mean(), color=C_BLUE, fontsize=8)
    ax.legend(loc='lower right', fontsize=8, frameon=False)
    ax.set_title('26 支：机内做不完的颜色，用一张残差 LUT 补回来', fontsize=11)
    ax.spines[['top', 'right']].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, 'lut-gap-rank.jpg'))
    plt.close(fig)


def fig_ceiling(lut, orc):
    groups = [('全部', None), ('彩色', 'color'), ('单色', 'mono')]
    now, up, lutv = [], [], []
    for tag, kind in groups:
        L = [r for r in lut if kind is None or r['type'] == kind]
        O = [r for r in orc if kind is None or r['type'] == kind]
        now.append(np.mean([float(r['dE00_before']) for r in L]))
        up.append(np.mean([float(r['dE00_oracle']) for r in O]))
        lutv.append(np.mean([float(r['dE00_after']) for r in L]))
    x = np.arange(len(groups))
    fig, ax = plt.subplots(figsize=(6.4, 4.0), dpi=170)
    w = 0.26
    ax.bar(x - w, now, w, color=C_GREY, label='现在（机内 NCP）')
    ax.bar(x, up, w, color=C_ORANGE, label='机内同类工具的连续上界')
    ax.bar(x + w, lutv, w, color=C_BLUE, label='NCP + 残差 LUT')
    for xi, v in zip(x - w, now):
        ax.text(xi, v + 0.15, '%.1f' % v, ha='center', fontsize=8, color='#4A5568')
    for xi, v in zip(x, up):
        ax.text(xi, v + 0.15, '%.1f' % v, ha='center', fontsize=8, color='#4A5568')
    for xi, v in zip(x + w, lutv):
        ax.text(xi, v + 0.15, '%.1f' % v, ha='center', fontsize=8, color='#4A5568')
    ax.set_xticks(x, [g[0] for g in groups])
    ax.set_ylabel('平均 ΔE00', fontsize=9)
    ax.axhline(2.3, color=C_RED, lw=0.8, ls='--')
    ax.text(-0.42, 2.42, '可辨阈值 2.3', color=C_RED, fontsize=7.5)
    ax.legend(fontsize=8, frameon=False)
    ax.set_title('两道天花板：机内的三个旋钮 vs 后期的一张表', fontsize=11)
    ax.spines[['top', 'right']].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, 'lut-ceiling.jpg'))
    plt.close(fig)


def fig_chroma(realm, lut, orc):
    """彩度残差带符号：负=我们偏淡，正=我们偏浓"""
    lutm = {r['name']: r for r in lut}
    orcm = {r['name']: r for r in orc}
    rows = [r for r in realm if r['name'] in lutm]
    rows.sort(key=lambda r: float(r['dC_signed']))
    lab = [r['name'] for r in rows]
    now = np.array([float(r['dC_signed']) for r in rows])
    y = np.arange(len(rows))[::-1]
    fig, ax = plt.subplots(figsize=(6.8, 0.28 * len(rows) + 1.2), dpi=170)
    ax.barh(y, now, height=0.55, color=[
        C_RED if v < 0 else C_GREEN for v in now])
    ax.axvline(0, color='#2D3748', lw=0.9)
    ax.set_yticks(y, lab, fontsize=7.5)
    ax.set_xlabel('ΔC*（现状，负 = 我们偏淡）', fontsize=9)
    nlo = int((now < -0.5).sum())
    nhi = int((now > 0.5).sum())
    ax.set_title('%d 支偏淡、%d 支偏浓：方向都不一样，一个全局倍率补不回来'
                 % (nlo, nhi), fontsize=10)
    ax.spines[['top', 'right']].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, 'lut-chroma.jpg'))
    plt.close(fig)


def main():
    lut = rd('metrics_lut.csv')
    orc = rd('oracle_global.csv')
    real = rd('metrics_real.csv')
    if not lut:
        raise SystemExit('先跑 tools/lut_fit.py')
    fig_rank(lut)
    if orc:
        fig_ceiling(lut, orc)
    if real:
        fig_chroma(real, lut, orc)
    print('图 -> %s' % OUT)


if __name__ == '__main__':
    main()
