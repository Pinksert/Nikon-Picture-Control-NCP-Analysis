#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_monofilter_analyze.py —— 把滤镜探针按老口径量化，看哪一档真的缩了分歧。

只问三件事：
  1. 单色滤镜档 0x80→0x84 有没有让单色的 ΔE00 掉下来（主指标 dE_either，与
     mono_refit 同一把尺子，也同一张 420px 缩图）；
  2. 「纯白判决」分歧的像素数（min(RGB)>253 才算白，这是 BINARY 的判据）有没有减少；
  3. 分歧像素在彩色参照（同场景 DREAM 成片）里是红主导还是蓝主导 —— 滤镜档若把
     红/蓝分工改对了，红主导那一坨应该明显萎缩。

两批合起来读：`_probe_monofilter/`（F0–F3）+ `_probe_monofilter_green/`（G=0x84）。
G 是关键的一档：F1–F3 把「我们白/官方黑」那坨红像素越推越白，说明黄/橙/红都在
**提亮红**；尼康的绿滤镜方向相反（压红、提绿），是唯一还没试过的方向。

用法：python tools/probe_monofilter_analyze.py
"""
import argparse
import csv
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mono_refit import load, find, metrics, SAMP   # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
D1 = os.path.normpath(os.path.join(ROOT, '..', '_probe_monofilter'))
D2 = os.path.normpath(os.path.join(ROOT, '..', '_probe_monofilter_green'))
WHITE = 253.0
BASE = {19: 6.9863, 27: 1.1834}       # mono_refit 那一轮的历史基准

PLAN = [
    (19, 'BINARY', D1, 'M19_BINA_', ['F0', 'F1', 'F2', 'F3'], ['0x80', '0x81', '0x82', '0x83']),
    (19, 'BINARY', D2, 'M19_BINA_', ['G'], ['0x84']),
    (27, 'MONOCHROME', D1, 'M27_MONO_', ['F0', 'F1', 'F2', 'F3'], ['0x80', '0x81', '0x82', '0x83']),
    (27, 'MONOCHROME', D2, 'M27_MONO_', ['G'], ['0x84']),
]


def whitemask(a):
    return a.min(-1) > WHITE


def dom(px):
    ch = px.argmax(1)
    return 100 * np.array([(ch == 0).mean(), (ch == 1).mean(), (ch == 2).mean()])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-csv', action='store_true')
    a = ap.parse_args()

    C = load(find(os.path.join(SAMP, 'real_v3'), 1, 'DREAM'))

    print('%-12s %-5s %-8s %-8s %-7s | %7s %7s %8s %8s | %s'
          % ('组', '档', 'dE_either', 'dE_both', 'haze%',
             '都白', '都黑', '我白他黑', '他白我黑', '分歧像素的红/蓝主导'))
    print('-' * 122)

    rows = {}
    for slot, name, d, prefix, tags, bytes_ in PLAN:
        R = load(find(os.path.join(SAMP, 'real_target'), slot, name))
        wR = whitemask(R)
        for tag, byte in zip(tags, bytes_):
            p = os.path.join(d, '%s%s.JPG' % (prefix, tag))
            if not os.path.exists(p):
                continue
            P = load(p)
            m = metrics(P, R)
            wP = whitemask(P)
            pw, rw = wP & ~wR, wR & ~wP
            dp = dom(C[pw]) if pw.any() else np.zeros(3)
            dr = dom(C[rw]) if rw.any() else np.zeros(3)
            print('%-12s %-5s %8.3f %8.3f %7.2f | %7d %7d %8d %8d | 我白他黑 R%.0f/B%.0f ｜ 他白我黑 R%.0f/B%.0f'
                  % (name, '%s %s' % (tag, byte), m['de_either'], m['de_both'], m['haze'],
                     int((wP & wR).sum()), int((~wP & ~wR).sum()),
                     int(pw.sum()), int(rw.sum()), dp[0], dp[2], dr[0], dr[2]))
            rows[(slot, tag)] = (m['de_either'], int(pw.sum() + rw.sum()), byte)
        print('-' * 122)

    for slot, name in [(19, 'BINARY'), (27, 'MONOCHROME')]:
        if (slot, 'F0') not in rows:
            continue
        d0 = rows[(slot, 'F0')][0]
        allr = [(v[0], k[1]) for k, v in rows.items() if k[0] == slot]
        best = min(allr)
        print('%-11s F0 = %.3f（历史基准 %.3f，差 %+.2f → 批次可比性）｜ 全档最优 %s = %.3f'
              % (name, d0, BASE[slot], d0 - BASE[slot], best[1], best[0]))
        if (slot, 'G') in rows:
            g = rows[(slot, 'G')][0]
            print('            绿色档 0x84 = %.3f（相对 F0 %+.2f，相对最差档 %+.2f）'
                  % (g, g - d0, g - max(v[0] for k, v in rows.items() if k[0] == slot)))
    print('\n判读：0x80 若仍是全场最优，这一格就彻底封死 —— 曲线修不动 + 滤镜方向全错，'
          '\n      BINARY 的 7 个 ΔE00 属于「机身黑白混合权重」本身，NCP 层面无解。')

    if not a.no_csv:
        out = os.path.join(SAMP, 'probe_monofilter.csv')
        with open(out, 'w', encoding='utf-8-sig', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(['group', 'filter', 'byte45', 'de_either', 'disagree_px'])
            for (slot, tag), (de, nd, byte) in sorted(rows.items()):
                w.writerow(['BINARY' if slot == 19 else 'MONOCHROME', tag, byte,
                            '%.4f' % de, nd])
        print('csv -> samples/probe_monofilter.csv')


if __name__ == '__main__':
    main()
