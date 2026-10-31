#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cv_split_test.py —— 交叉验证怎么切才不冤枉人。

问题
----
`optimize_v2.explore()` 用「上半幅拟合、下半幅打分」来决定一支槽位要不要动。
这个切法有个隐患：一张照片的上半幅常常是天、下半幅是地，两半的亮度分布和色相
分布根本不是同一套。拟合出来的曲线在下半幅打分自然没有收益，于是被判「维持原样」。

实测痕迹：槽 19 BINARY 的 |ΔL*| 有 5.89、槽 23 DEEPTONE 有 4.95（全 30 支平均只有
1.43），可这两支恰恰是「一步没动」的。影调差这么大却判平，说明不是真的没差，是
CV 没看见。

这里对比三种切法：
  half   上/下半幅（现行）
  quad   四个象限交错（2×2 棋盘）
  fine   8×8 棋盘交错（两半的亮度、色相分布几乎一致）

判据不是「CV 数字谁小」——CV 只是选结构的工具。真正要问的是：用它选出来的结构、
拿去全幅重拟合落地之后，全幅误差谁低。选结构的工具好不好，要看它选的东西落地效果。

    python tools/cv_split_test.py            # 三种切法全 30 支对比
    python tools/cv_split_test.py 19 23 2    # 只看指定槽位
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import optimize_v2 as A                                    # noqa: E402


def split(shape, mode):
    """返回 (拟合用 mask, 打分用 mask)"""
    h, w = shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    if mode == 'half':
        m = yy < h // 2
    elif mode == 'quad':
        m = ((yy // max(1, h // 2)) + (xx // max(1, w // 2))) % 2 == 0
    else:
        b = max(1, min(h, w) // 8)
        m = ((yy // b) + (xx // b)) % 2 == 0
    return m, ~m


def pick(slot, mode):
    """按指定切法复现 explore 的选结构过程，返回 (n, m, k, cv0, cv1)"""
    O, R = A.load('d300ncp', slot), A.load('workshop', slot)
    fm, ev = split(O.shape, mode)
    # 布尔 mask 索引会把 (h,w,3) 摊成 (N,3)，fit_map 要按轴 2 算通道极差，
    # 这里补一个长度为 1 的中间轴把形状找回来
    Of, Rf = O[fm][:, None, :], R[fm][:, None, :]

    def score(f, s=1.0, deg=0.0, k=1.0):
        return float(np.abs(A.predict(O, f, s, deg, k)[ev] - R[ev]).mean())

    e0 = score(A.ID)
    cands = [(e0, 'id', 0, 0, 1.0)]
    f = A._fit(slot, Of, Rf)
    cands.append((score(f), 'tone', 0, 0, 1.0))
    if slot in A.TONED:
        for kb in range(0x80, 0x8A):
            k = (kb - 0x80) / 4.0
            cands.append((score(f, 1.0, 0.0, k), 'tone', 0, 0, k))
    elif slot not in A.MONO:
        for n in range(-3, 4):
            for m in range(-3, 4):
                cands.append((score(f, A.SAT_STEP ** n, A.HUE_STEP * m), 'tone', n, m, 1.0))
    cands.sort(key=lambda c: c[0])
    b = cands[0]
    if b[0] > e0 - A.MIN_GAIN:
        b = (e0, 'id', 0, 0, 1.0)
    # 必须把 kind 一起带出去：kind='tone' 且 n=m=0 表示「只改曲线、不动滑块」，
    # 和 kind='id'（一步不动）是两种完全不同的动作，混为一谈会把 BINARY /
    # DEEPTONE 这类「差距全在影调」的槽位误判成不动。
    return b[1], b[2], b[3], b[4], e0, b[0]


def land(slot, kind, n, m, k):
    """结构定了之后用全幅重拟合，返回 (改前, 改后)"""
    O, R = A.load('d300ncp', slot), A.load('workshop', slot)
    e0 = float(np.abs(A.predict(O, A.ID) - R).mean())
    if kind == 'id':
        return e0, e0
    f = A._fit(slot, O, R)
    if slot in A.TONED:
        P = A.predict(O, f, 1.0, 0.0, k)
    elif slot in A.MONO:
        P = A.predict(O, f)
    else:
        P = A.predict(O, f, A.SAT_STEP ** n, A.HUE_STEP * m)
    return e0, float(np.abs(P - R).mean())


def main():
    slots = [int(x) for x in sys.argv[1:] if x.isdigit()] or list(range(1, 31))
    modes = ('half', 'quad', 'fine')
    print('%-4s %-20s %6s | %-22s %-22s %-22s'
          % ('槽', '滤镜', '全幅差', '上/下半幅', '2×2 棋盘', '8×8 棋盘'))
    print('-' * 104)
    tot = {m: [0.0, 0.0] for m in modes}
    for slot in slots:
        row = []
        for mode in modes:
            kind, n, m, k, cv0, cv1 = pick(slot, mode)
            e0, e1 = land(slot, kind, n, m, k)
            tot[mode][0] += e0
            tot[mode][1] += e1
            tag = 'id' if kind == 'id' else (
                'k%.2f' % k if slot in A.TONED else 'n%+d m%+d' % (n, m))
            row.append('%5.2f→%5.2f %-9s' % (e0, e1, tag))
        base = land(slot, 'id', 0, 0, 1.0)[0]
        print('%2d   %-20s %6.2f | %s %s %s'
              % (slot, A.NAMES[slot - 1], base, row[0], row[1], row[2]))
    print('-' * 104)
    k = len(slots)
    for mode in modes:
        e0, e1 = tot[mode]
        print('%-8s 全幅平均 %.2f → %.2f（降 %.1f%%）'
              % (mode, e0 / k, e1 / k, (1 - e1 / e0) * 100))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
