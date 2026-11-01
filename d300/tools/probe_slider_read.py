#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_slider_read.py —— 读 11 张滑块探针，算出「一档到底值多少」。

探针由 probe_slider_pack.py 生成：同一张曲线，只改一个字节。
所以渲染结果之间的彩度差，就是滑块本身的力量，没有曲线混淆。

    python tools/probe_slider_read.py
    python tools/probe_slider_read.py --dir d300/samples/probe_slider
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from diag_residual import to_lab, CLIP, CMIN, hz                    # noqa: E402
import optimize_v2 as A                                             # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
DEF = os.path.join(ROOT, 'samples', 'probe_slider')


def load(p, size=420):
    im = Image.open(p).convert('RGB')
    r = size / max(im.size)
    if r < 1.0:
        im = im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))),
                       Image.LANCZOS)
    return np.asarray(im, dtype=np.float64)


def find(d, tag):
    for f in os.listdir(d):
        b, _ = os.path.splitext(f)
        if b.upper().endswith('_' + tag.upper()):
            return os.path.join(d, f)
    return None


def stats(p):
    a = load(p)
    m = (a.min(2) > CLIP) & (a.max(2) < 255 - CLIP)
    if m.sum() < 5000:
        m = np.ones(a.shape[:2], bool)
    lab = to_lab(a[m])
    h, c = hz(lab)
    return dict(C=float(c.mean()), L=float(lab[:, 0].mean()),
                h=float(np.median(h[c > CMIN])) if (c > CMIN).any() else 0.0,
                rgb=a.reshape(-1, 3).mean(0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default=DEF)
    a = ap.parse_args()
    d = a.dir
    if not os.path.isdir(d) or not any(f.upper().endswith(('.JPG', '.JPEG', '.JPE'))
                                       for f in os.listdir(d)):
        raise SystemExit('还没有导出结果：%s 里没有 JPEG。\n'
                         '先把 _probe_slider 那批导出，放进这个目录。' % d)

    tags = ['SAT%+d' % k for k in range(-3, 4)] + ['HUE+3', 'BASEVIVID', 'TINT0', 'TINTP3']
    got = {}
    for t in tags:
        p = find(d, t)
        if p:
            got[t] = stats(p)

    print('%-10s %8s %8s %8s   %s' % ('探针', '彩度C*', '亮度L*', '色相°', 'RGB 均值'))
    print('-' * 62)
    for t in tags:
        if t not in got:
            print('%-10s   （缺）' % t)
            continue
        s = got[t]
        print('%-10s %8.2f %8.2f %8.1f   %.1f / %.1f / %.1f'
              % (t, s['C'], s['L'], s['h'], s['rgb'][0], s['rgb'][1], s['rgb'][2]))

    # ---- 饱和度：log(C) 对档位线性回归，斜率取指数 = 每档倍率
    xs, ys = [], []
    for k in range(-3, 4):
        t = 'SAT%+d' % k
        if t in got:
            xs.append(k)
            ys.append(np.log(got[t]['C']))
    if len(xs) >= 3:
        slope, icpt = np.polyfit(xs, ys, 1)
        step = float(np.exp(slope))
        pred = np.exp(icpt + slope * np.array(xs))
        rms = float(np.sqrt(np.mean((np.exp(ys) - pred) ** 2)))
        print()
        print('饱和度：实测每档 ×%.3f（模型假设 ×%.3f）' % (step, A.SAT_STEP))
        print('        拟合残差 RMS %.3f 个彩度单位；单极值 %.2f → %.2f'
              % (rms, min(np.exp(ys)), max(np.exp(ys))))
        print('        → 建议把 SAT_STEP 由 %.3f 改为 %.3f' % (A.SAT_STEP, step))
        print('        注意：±3 档才 %.2f 倍，若目标需要更多颜色，滑块根本给不了。'
              % (step ** 3))

    # ---- 色相：+3 档相对 0 档转了几度
    if 'HUE+3' in got and 'SAT+0' in got:
        dh = (got['HUE+3']['h'] - got['SAT+0']['h'] + 180.0) % 360.0 - 180.0
        print()
        print('色相：+3 档转了 %+.1f°，即每档 %+.2f°（模型假设 %+.1f°）'
              % (dh, dh / 3.0, A.HUE_STEP))

    # ---- 底子：VIVID 与 STANDARD 是否真的一样
    if 'BASEVIVID' in got and 'SAT+0' in got:
        dv = np.abs(got['BASEVIVID']['rgb'] - got['SAT+0']['rgb']).mean()
        print()
        print('底子：换成 VIVID 后平均 RGB 差 %.2f' % dv)
        print('      %s' % ('几乎没变 → NX Studio 导入时无视底子字节，底子只认文件里那条曲线'
                            if dv < 1.0 else '变了 → 底子字节被认，换底子这条路是通的'))

    # ---- 单色 tint
    if 'TINT0' in got and 'TINTP3' in got:
        print()
        print('单色 tint：0 档 C*=%.2f，+3 档 C*=%.2f，每档 +%.2f 个彩度单位'
              % (got['TINT0']['C'], got['TINTP3']['C'],
                 (got['TINTP3']['C'] - got['TINT0']['C']) / 3.0))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
