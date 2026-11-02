#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pack_profile_probe.py —— 把 NX Studio 里真正注册过的底子编号扫一遍。

为什么做这个：
    从 Rome2.dll 里把 Picture Control 注册表 dump 出来了（见
    docs/18-ncp-crash-and-profile-table.md）。默认命名空间（kind=1）下
    一共只有 9 个合法编号，我们过去只用了 0001（彩色）和 064D（单色），
    另外 5 个 —— PORTRAIT / LANDSCAPE / D2XMODE I/II/III —— 从来没试过。
    这 5 个都在表里，写进 NCP 不会让 NX Studio 崩，可以放心整包跑。

    对照：0x0801–0x080D 那批创意底子只存在于 kind=8 命名空间；
    写进默认命名空间会查不到 → 越界 → Rome2.dll 崩（2026-11-02 实测）。

用法：
    python d300/tools/pack_profile_probe.py
    # 然后 NX Studio 打开 _probe_profile，Ctrl+A 导出到 d300/samples/probe_profile
"""
import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..', 'np3tool')))

import np3core as C                                            # noqa: E402
import sidecar_batch as S                                      # noqa: E402
import pack_sidecar_batch as B                                 # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
NEF = os.path.join(ROOT, '..', 'lightroom', 'DSC_4484.NEF')
TPL = os.path.join(ROOT, '..', 'lightroom', 'NKSC_PARAM', 'DSC_4484.NEF.nksc')

# 与 pack_baseid_probe.py 同款中性滑块（档位全 0）
SL_COLOR = [0x83, 0x01, 0x01, 0x80, 0x80, 0x80, 0xFF, 0xFF]

# (编号, 输出名, 表里的名字, 说明)
PLAN = [
    (0x0001, 'P0_STANDARD',  'STANDARD',  '对照：我们一直用的那个'),
    (0x0486, 'P1_PORTRAIT',  'PORTRAIT',  '基础底子·人像（从没用过）'),
    (0x04C7, 'P2_LANDSCAPE', 'LANDSCAPE', '基础底子·风景（从没用过）'),
    (0x0014, 'P3_D2XMODE1',  'D2XMODEI',  'D2X 模式 I（从没用过）'),
    (0x03D5, 'P4_D2XMODE2',  'D2XMODEII', 'D2X 模式 II（从没用过）'),
    (0x00D6, 'P5_D2XMODE3',  'D2XMODEIII', 'D2X 模式 III（从没用过）'),
    (0x064D, 'P6_MONOCHROME', 'MONOCHROME', '对照：单色支一直用的那个'),
]


def make_identity_ncp(name, base):
    """恒等曲线：机身执行 C(H(x)) = x，只让底子自己干活。"""
    import numpy as np
    ncp = C.make_ncp(name, base, SL_COLOR, np.arange(256, dtype=np.float64))
    d = C.read_ncp(ncp)
    assert d['base'] == base, '底子写错 %04X' % d['base']
    got = C.H(d['lut'])
    err = float(np.abs(got - np.arange(257)).max())
    assert err < 1.5, '恒等曲线偏差过大 %.2f' % err
    return ncp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(ROOT, '..', '_probe_profile'))
    ap.add_argument('--nef', default=NEF)
    ap.add_argument('--template', default=TPL)
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    ncpdir = os.path.join(out, '_ncp')
    if os.path.isdir(ncpdir):
        shutil.rmtree(ncpdir)
    os.makedirs(ncpdir)

    print('%-16s %-6s %-11s %s' % ('输出', '底子', '表里的名字', '说明'))
    print('-' * 72)
    for base, stem, official, why in PLAN:
        ncp = make_identity_ncp(stem, base)
        with open(os.path.join(ncpdir, stem + '.NCP'), 'wb') as f:
            f.write(ncp)
        print('%-16s 0x%04X %-11s %s' % (stem, base, official, why))

    print()
    B.build(ncpdir, out, a.nef, a.template, keep_old=False)
    print()
    print('判据：P1–P5 只要有两张渲出来不一样，说明底子这一层还能挑；')
    print('      六张如果全都一样，说明默认命名空间下换底子对 D300 曲线没有额外收益。')


if __name__ == '__main__':
    main()
