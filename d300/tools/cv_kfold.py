#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cv_kfold.py —— 用 K 折交叉验证替换「上下半幅」，看能不能既救回被冤枉的槽位，又不放水。

为什么要换
----------
`optimize_v2.explore()` 现行的做法是：上半幅拟合曲线、下半幅打分，收益不够就不动。
这是一个 50/50 的单次切分。单次切分的问题在于它只有一个样本，构图一偏就偏到底：
上半幅是天、下半幅是地的时候，两半的亮度分布不是同一套，曲线在下半幅上自然没收益。

实测痕迹：槽 23 DEEPTONE 被这个切法判「不动」，但它的 |ΔL*| 有 4.95（30 支平均 1.43），
是全场影调差最大的两支之一。换 2×2 或 8×8 棋盘切分后同一支能降到 8.76。

但 8×8 棋盘是反方向的错：块内的像素高度相关，训练集和测试集几乎一样，CV 就退化成
自己考自己了。所以正解是标准 K 折 —— 把画面切成 2×4 共 8 个块，每次留一块做测试、
其余七块训练，轮流 8 次，按「每个候选结构在 8 折上的平均测试收益」排序。

这样既避免了单次切分的构图偏置，又保证训练/测试是真正不相交的两批像素。

    python tools/cv_kfold.py               # 全 30 支，对比 半幅 / 8×8棋盘 / 8折
    python tools/cv_kfold.py 19 23 1       # 只看指定槽位
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import optimize_v2 as A                                    # noqa: E402

NY, NX = 2, 4                    # K 折 = NY×NX = 8 块


def cells(shape, ny=NY, nx=NX):
    """把画面切成 ny×nx 个互不相交的块，返回每个块的布尔 mask"""
    h, w = shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    ey = np.linspace(0, h, ny + 1).astype(int)
    ex = np.linspace(0, w, nx + 1).astype(int)
    out = []
    for i in range(ny):
        for j in range(nx):
            out.append((yy >= ey[i]) & (yy < ey[i + 1]) & (xx >= ex[j]) & (xx < ex[j + 1]))
    return out


def candidates(slot):
    """与 explore 完全一致的候选集：(n, m, k)；结构由槽位类型决定"""
    c = [(0, 0, 1.0)]
    if slot in A.TONED:
        for kb in range(0x80, 0x8A):
            c.append((0, 0, (kb - 0x80) / 4.0))
    elif slot not in A.MONO:
        for n in range(-3, 4):
            for m in range(-3, 4):
                c.append((n, m, 1.0))
    return c


def render(O, f, slot, n, m, k):
    if slot in A.TONED:
        return A.predict(O, f, 1.0, 0.0, k)
    if slot in A.MONO:
        return A.predict(O, f)
    return A.predict(O, f, A.SAT_STEP ** n, A.HUE_STEP * m)


def pick_kfold(slot):
    """返回 (n, m, k, 平均测试收益)；收益为负表示改完比不改好"""
    O, R = A.load('d300ncp', slot), A.load('workshop', slot)
    cs = candidates(slot)
    acc = np.zeros(len(cs))
    base = 0.0
    ms = cells(O.shape)
    for msk in ms:
        test = msk
        tr = ~msk
        Of, Rf = O[tr][:, None, :], R[tr][:, None, :]
        f = A._fit(slot, Of, Rf)
        e0 = float(np.abs(A.predict(O, A.ID)[test] - R[test]).mean())
        base += e0
        for i, (n, m, k) in enumerate(cs):
            acc[i] += float(np.abs(render(O, f, slot, n, m, k)[test] - R[test]).mean())
    acc /= len(ms)
    base /= len(ms)
    best = int(np.argmin(acc))
    return cs[best][0], cs[best][1], cs[best][2], float(acc[best] - base)


def land(slot, n, m, k, use_curve=True):
    """结构定了之后全幅重拟合落地，返回 (改前, 改后)

    use_curve 单独给：候选 (0,0,1.0) 的意思是「只改曲线、滑块不动」，
    它和「什么都不做」不是一回事，不能拿 n/m/k 是不是默认值来判断。
    """
    O, R = A.load('d300ncp', slot), A.load('workshop', slot)
    e0 = float(np.abs(A.predict(O, A.ID) - R).mean())
    if not use_curve:
        return e0, e0
    f = A._fit(slot, O, R)
    return e0, float(np.abs(render(O, f, slot, n, m, k) - R).mean())


def main():
    slots = [int(x) for x in sys.argv[1:] if x.isdigit()] or list(range(1, 31))
    print('%-4s %-20s %6s | %-14s %-14s %-14s'
          % ('槽', '滤镜', '全幅差', '8折结构', '8折收益', '落地后'))
    print('-' * 84)
    tot0 = tot1 = 0.0
    moved = 0
    for slot in slots:
        n, m, k, gain = pick_kfold(slot)
        keep = gain <= -A.MIN_GAIN
        e0, e1 = land(slot, n, m, k, keep)
        if keep:
            moved += 1
        tot0 += e0
        tot1 += e1
        tag = ('id' if not keep else
               ('k%.2f' % k if slot in A.TONED else 'n%+d m%+d' % (n, m)))
        print('%2d   %-20s %6.2f | %-14s %+14.2f %6.2f→%5.2f %s'
              % (slot, A.NAMES[slot - 1], e0, tag, gain, e0, e1,
                 '' if keep else '（收益不足，不动）'))
    n = len(slots)
    print('-' * 84)
    print('8 折：全幅平均 %.2f → %.2f（降 %.1f%%），动用 %d 支'
          % (tot0 / n, tot1 / n, (1 - tot1 / tot0) * 100, moved))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
