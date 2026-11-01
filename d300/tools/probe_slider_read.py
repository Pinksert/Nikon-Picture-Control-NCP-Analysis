#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_slider_read.py —— 读滑块探针，算出「一档到底值多少」。

探针由 probe_slider_pack.py 生成：同一张曲线，只改一个滑块字节
（名字段也会不同，但名字只用于显示、不进渲染）。

⚠️ 口径要害：所有图必须共用同一批像素。
   v1 版本每张图各自算遮罩，饱和度一变遮罩就变，
   结果 C* 从 −3 档到 +3 档呈现 8.49→11.38→9.95 的假非单调。
   正确做法是以 SAT+0 的中间调遮罩为固定像素集。

    python tools/probe_slider_read.py
    python tools/probe_slider_read.py --dir d300/samples/probe_slider
"""
import argparse
import csv
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from diag_residual import to_lab, CLIP, hz, de2000                # noqa: E402
import optimize_v2 as A                                           # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
DEF = os.path.join(ROOT, 'samples', 'probe_slider')

SAT_TAGS = ['SAT%+d' % k for k in range(-3, 4)]


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


def circ_mean(h, w):
    """加权圆平均色相，返回角度。"""
    r = np.deg2rad(h)
    s = np.sum(w * np.sin(r))
    c = np.sum(w * np.cos(r))
    return float(np.rad2deg(np.arctan2(s, c))) % 360.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default=DEF)
    ap.add_argument('--csv', default=os.path.join(ROOT, 'samples', 'probe_slider.csv'))
    a = ap.parse_args()
    d = a.dir
    if not os.path.isdir(d) or not any(f.upper().endswith(('.JPG', '.JPEG', '.JPE'))
                                       for f in os.listdir(d)):
        raise SystemExit('还没有导出结果：%s 里没有 JPEG。\n'
                         '先把 _probe_slider 那批导出，放进这个目录。' % d)

    # ---------- 载入 ----------
    img = {}
    for t in SAT_TAGS + ['HUE+3', 'BASEVIVID', 'TINT0', 'TINTP3']:
        p = find(d, t)
        if p:
            img[t] = load(p)
    if 'SAT+0' not in img:
        raise SystemExit('缺 SAT+0 基准图。')

    base = img['SAT+0']
    # 固定像素集：基准图中间调、非裁剪
    m = (base.min(2) > CLIP) & (base.max(2) < 255 - CLIP)

    def lab_of(t):
        lab = to_lab(img[t][m])
        return lab, lab[:, 0], np.hypot(lab[:, 1], lab[:, 2])

    lab0, L0, C0 = lab_of('SAT+0')
    # 三个分析层，由宽到窄：信号越来越强
    T1 = np.percentile(C0, 90)
    T2 = np.percentile(C0, 99)

    print('固定像素集 %d 个（基准图中间调）。C* 中位 %.2f / P90 %.2f / P99 %.2f'
          % (int(m.sum()), np.median(C0), T1, T2))
    RES = []

    # ---------- 1. 饱和度 ----------
    print()
    print('【一】饱和度滑块')
    print('%-8s %9s %9s %9s %9s' % ('探针', 'C*全像素', 'C*(P90+)', 'C*(P99+)', 'L*'))
    print('-' * 50)
    tab = {}
    for k in range(-3, 4):
        t = 'SAT%+d' % k
        if t not in img:
            print('%-8s （缺）' % t)
            continue
        lab, L, C = lab_of(t)
        r = (float(C.mean()), float(C[C0 >= T1].mean()), float(C[C0 >= T2].mean()),
             float(L.mean()))
        tab[k] = r
        print('%-8s %9.2f %9.2f %9.2f %9.2f' % (t, r[0], r[1], r[2], r[3]))
        RES.append(dict(kind='sat', level=k, c_all=r[0], c_p90=r[1], c_p99=r[2], L=r[3]))

    def fit(series):
        """log(C) ~ k 线性回归，返回 (每档倍率, R², 各档相对基准实测倍数)"""
        ks = [k for k in sorted(tab) if tab[k][series] > 0]
        if len(ks) < 3:
            return None
        y = np.log([tab[k][series] for k in ks])
        x = np.array(ks, dtype=float)
        sl, ic = np.polyfit(x, y, 1)
        pred = ic + sl * x
        ss = 1.0 - np.sum((y - pred) ** 2) / np.sum((y - y.mean()) ** 2)
        return float(np.exp(sl)), float(ss), {k: float(np.exp(sl * k)) for k in ks}

    best = None
    for name, s in (('全像素', 0), ('C*>P90', 1), ('C*>P99', 2)):
        r = fit(s)
        if r:
            print('  %-8s 每档 ×%.3f   线性拟合 R² = %.4f' % (name, r[0], r[1]))
            best = r
    print()
    print('  逐档实测（以 0 档为 1.000，取 C*>P90 层）:')
    print('    ' + '  '.join('%+d:%.3f' % (k, v) for k, v in best[2].items()))
    print('  模型假设 SAT_STEP = %.3f' % A.SAT_STEP)
    print('  ±3 档合计：实测 %.3f / %.3f 倍（下 / 上）' % (best[2][-3], best[2][3]))
    print('  亮度随档位变化 %.2f → %.2f（ΔL* = %+.2f）'
          % (tab[-3][3], tab[3][3], tab[3][3] - tab[-3][3]))
    for r in RES:
        if r['kind'] == 'sat':
            r['step'] = best[0]

    # ---------- 2. 色相 ----------
    if 'HUE+3' in img:
        print()
        print('【二】色相滑块（+3 档）')
        lab, L, C = lab_of('HUE+3')
        sel = C0 >= T2            # 只在浓色像素上比，避免中性像素方向随机
        h0 = circ_mean(hz(lab0)[0][sel], C0[sel])
        h1 = circ_mean(hz(lab)[0][sel], C0[sel])
        dh = (h1 - h0 + 180.0) % 360.0 - 180.0
        print('  基准色相 %.1f°  → +3 档 %.1f°   转 %+.1f°，每档 %+.2f°'
              % (h0, h1, dh, dh / 3.0))
        print('  模型假设 HUE_STEP = %+.1f°/档' % A.HUE_STEP)
        hh0 = hz(lab0)[0][sel]
        hh1 = hz(lab)[0][sel]
        dd = (hh1 - hh0 + 180.0) % 360.0 - 180.0
        print('  逐像素转向：中位 %+.1f°，四分位 %+.1f° / %+.1f°'
              % (np.median(dd), np.percentile(dd, 25), np.percentile(dd, 75)))
        print('  C* 同时 %.2f → %.2f（Δ%+.2f）' % (C0.mean(), C.mean(), C.mean() - C0.mean()))
        RES.append(dict(kind='hue', hue_deg=dh, hue_per_step=dh / 3.0,
                        c_all=float(C.mean()), median_deg=float(np.median(dd))))

    # ---------- 3. 底子 ----------
    if 'BASEVIVID' in img:
        print()
        print('【三】底子字节（STANDARD 0x0001 → VIVID 0x00C3）')
        lab, L, C = lab_of('BASEVIVID')
        de = de2000(lab0, lab)
        print('  C* 全像素 %.2f → %.2f（Δ%+.2f，%+.1f%%）'
              % (C0.mean(), C.mean(), C.mean() - C0.mean(),
                 100.0 * (C.mean() / C0.mean() - 1)))
        print('  L* %.2f → %.2f（Δ%+.2f）' % (L0.mean(), L.mean(), L.mean() - L0.mean()))
        print('  ΔE00 均值 %.2f，>2.3 的像素占 %.1f%%'
              % (de.mean(), 100.0 * (de > 2.3).mean()))
        if de.mean() < 1.0:
            print('  → 几乎没变：NX Studio 只认曲线，不认底子字节')
        elif de.mean() < 4.0:
            print('  → 有变化但很弱：底子字节只影响局部')
        else:
            print('  → 明显生效：底子字节被采纳')
        RES.append(dict(kind='base', c_all=float(C.mean()),
                        dc_pct=100.0 * (C.mean() / C0.mean() - 1),
                        dl=float(L.mean() - L0.mean()),
                        de=float(de.mean()), de_pct=100.0 * float((de > 2.3).mean())))

    # ---------- 4. 单色着色 ----------
    if 'TINT0' in img and 'TINTP3' in img:
        print()
        print('【四】单色着色（MONOCHROME 底子 0x064D）')
        for t in ('TINT0', 'TINTP3'):
            im_ = img[t]
            mm = (im_.min(2) > CLIP) & (im_.max(2) < 255 - CLIP)
            lab = to_lab(im_[mm])
            h, c = hz(lab)
            ok = c > 2.0
            tint = circ_mean(h[ok], c[ok]) if ok.any() else 0.0
            print('  %-8s C* %.2f  色相 %6.1f°  RGB %.1f / %.1f / %.1f'
                  % (t, c.mean(), tint, im_[mm][:, 0].mean(),
                     im_[mm][:, 1].mean(), im_[mm][:, 2].mean()))
            RES.append(dict(kind=t.lower(), c_all=float(c.mean()),
                            hue_mean=tint, L=float(lab[:, 0].mean())))
        print('  → 着色档改的是「浓度」：色相几乎不动，彩度降 %.1f%%'
              % (100.0 * (1.0 - c.mean() / 23.04)))

    # ---------- 落盘 ----------
    if a.csv:
        cols = ['kind', 'level', 'c_all', 'c_p90', 'c_p99', 'L', 'step',
                'hue_deg', 'hue_per_step', 'median_deg', 'dc_pct', 'dl',
                'de', 'de_pct', 'hue_mean']
        os.makedirs(os.path.dirname(os.path.abspath(a.csv)), exist_ok=True)
        with open(a.csv, 'w', encoding='utf-8-sig', newline='') as fh:
            wr = csv.DictWriter(fh, fieldnames=cols, extrasaction='ignore')
            wr.writeheader()
            for r in RES:
                out = {}
                for c in cols:
                    v = r.get(c, '')
                    out[c] = ('%.4f' % v) if isinstance(v, float) else v
                wr.writerow(out)
        print()
        print('已写入 %s（%d 行）' % (a.csv, len(RES)))


if __name__ == '__main__':
    main()
