#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_range_read.py —— 读 `_probe_range/` 导出的成片。

每个探针只改了释放版 NCP 的一个字节（饱和度档，或底子编号），
所以两件事可以同时读：

  vs 对照（`samples/real_v3/` 同槽号）  = 这个字节到底管不管用、力气多大
  vs 官方（`samples/real_target/` 同槽号）= 改了之后是不是**更接近 NP3**

第二列才是判据。改得多不等于改得对（`14-slider-calibration.md` 的教训）。

    python d300/tools/probe_range_read.py --dir d300/samples/probe_range
"""
import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from diag_residual import to_lab, de2000                        # noqa: E402
from real_gap import NAMES, load, find                          # noqa: E402
from lut_fit import mask_of                                     # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
SAMP = os.path.join(ROOT, 'samples')


def metr(a, b, m):
    la, lb = to_lab(a[m]), to_lab(b[m])
    ca = np.hypot(la[:, 1], la[:, 2])
    cb = np.hypot(lb[:, 1], lb[:, 2])
    return (float(np.abs(a[m] - b[m]).mean()), float(de2000(la, lb).mean()),
            float(ca.mean()), float(cb.mean()))


def load_map(d):
    """手工路线的 P1..P8 对照表；照旧支持 R1_SILENCE_sat-6 这种自解释文件名。

    sidecar 批处理没走通之后（2026-11-02），探针改成「导入 NCP + 手动套用」，
    导出文件名是 P1.JPG…，光看名字看不出槽号，所以让包带一张 probe_map.csv。
    """
    mp = {}
    p = os.path.join(d, 'probe_map.csv')
    if os.path.exists(p):
        import csv
        with open(p, encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                mp[os.path.splitext(r['file'])[0].upper()] = (int(r['slot']), r['ncp_name'])
    return mp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default=os.path.join(SAMP, 'probe_range'))
    ap.add_argument('--size', type=int, default=420)
    a = ap.parse_args()
    if not os.path.isdir(a.dir):
        raise SystemExit('没有这个目录：%s' % a.dir)

    pm = load_map(a.dir)
    print('%-22s %-6s %8s %8s %8s %9s %s'
          % ('探针', '槽', 'dE 对照', 'dE 官方', 'Δ(dE)', '彩度比', '结论'))
    print('-' * 84)
    for f in sorted(os.listdir(a.dir)):
        stem, ext = os.path.splitext(f)
        if ext.lower() not in ('.jpg', '.jpeg', '.tif', '.tiff'):
            continue
        if stem.upper() in pm:
            slot = pm[stem.upper()][0]
            name = NAMES[slot - 1]
        else:
            parts = stem.split('_')
            name = parts[1].upper() if len(parts) > 1 else stem.upper()
            if name not in NAMES:
                print('%-22s  跳过（名字认不出）' % stem)
                continue
            slot = NAMES.index(name) + 1
        pc = find(os.path.join(SAMP, 'real_v3'), slot, name)
        pt = find(os.path.join(SAMP, 'real_target'), slot, name)
        if not pc:
            print('%-22s  跳过（没有对照）' % stem)
            continue
        P = load(os.path.join(a.dir, f), a.size)
        C = load(pc, a.size)
        if P.shape != C.shape:
            print('%-22s  跳过（尺寸不一致）' % stem)
            continue
        m = mask_of(P, C)
        d_ctl, de_ctl, _, _ = metr(P, C, m)
        if pt:
            T = load(pt, a.size)
            m2 = mask_of(P, T)
            d_off, de_off, c_probe, c_official = metr(P, T, m2)
            _, de_ctl_off, _, _ = metr(C, T, m2)
            delta = de_off - de_ctl_off
            ratio = c_probe / max(1e-6, c_official)
            verdict = '更接近 %.2f 级' % -delta if delta < -0.15 else (
                '更远 %.2f 级' % delta if delta > 0.15 else '没差别')
            print('%-22s %-6d %8.2f %8.2f %+8.2f %9.3f %s'
                  % (stem, slot, de_ctl, de_off, delta, ratio, verdict))
        else:
            print('%-22s %-6d %8.2f %8s %8s %9s %s'
                  % (stem, slot, de_ctl, '—', '—', '—', '只读到了改动幅度'))

    print()
    print('读法：')
    print('  dE 对照 = 这一个字节把画面改了多少（改动幅度，不是好坏）')
    print('  dE 官方 = 改完之后离官方 NP3 还有多远（越小越好）')
    print('  Δ(dE)   = 与「不改」相比近/远了多少，负值才是收益')
    print('  彩度比  = 探针彩度 / 官方彩度，1.0 为刚好；>1 偏浓，<1 偏淡')


if __name__ == '__main__':
    main()
