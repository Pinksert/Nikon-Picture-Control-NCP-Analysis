#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_monofilter_read.py —— 读单色滤镜探针（8 张 JPG）。

问题：BINARY 差 ~7 ΔE00，曲线修不动。归因是「哪些像素算白」判得不一样，
且与颜色相关（我们白/官方黑 73% 红主导，官方白/我们黑 69% 蓝主导）
⇒ 黑白通道混合权重不同，唯一能动的格子是「单色滤镜」(0x80/81/82/83)。

这批探针只回答一件事：**NX Studio 到底认不认这一格**。
  1. F1/F2/F3 与 F0 逐像素完全相同 → 应用态忽略该字节，必须去机身上试；
  2. 有差异 → 看差异落在哪些像素上：用同一场景的彩色渲染当参照，
     统计「被改动的像素」在参照图里是红主导还是蓝主导。
     如果 F1–F3 恰好把红/蓝两边分别往相反方向推，就是我们要的那一格。

用法：
    python tools/probe_monofilter_read.py [--dir ../d300/samples/probe_monofilter]
                                          [--ref ../d300/samples/real_target/29_STANDARD.JPG]
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
DEF_DIR = os.path.join(ROOT, 'samples', 'probe_monofilter')
DEF_REF = os.path.join(ROOT, 'samples', 'real_target', '29_STANDARD.JPG')

GROUPS = [('M19_BINA', 'BINARY'), ('M27_MONO', 'MONOCHROME')]
FILTERS = ['F0', 'F1', 'F2', 'F3']
FNAME = ['关(0x80)', '黄(0x81)', '橙(0x82)', '红(0x83)']


def load(p):
    im = Image.open(p).convert('RGB')
    return np.asarray(im, dtype=np.float32)


def find(root, stem, ext='.JPG'):
    """文件名大小写、导出时多加的后缀都容忍一下。"""
    cands = [stem + ext, stem + ext.lower(), stem + '.jpg', stem + '.jpeg',
             stem + '_01' + ext, stem + '-1' + ext]
    for c in cands:
        p = os.path.join(root, c)
        if os.path.exists(p):
            return p
    hits = [f for f in os.listdir(root) if f.upper().startswith(stem.upper())]
    return os.path.join(root, hits[0]) if len(hits) == 1 else None


def luma(a):
    return 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]


def ref_color(ref, shape):
    """彩色参照图缩放到探针尺寸（同场景，直接 cv 缩放即可对齐到像素级）。"""
    if ref.shape[:2] == shape[:2]:
        return ref
    im = Image.fromarray(ref.astype(np.uint8)).resize((shape[1], shape[0]),
                                                      Image.LANCZOS)
    return np.asarray(im, dtype=np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default=DEF_DIR)
    ap.add_argument('--ref', default=DEF_REF, help='同场景彩色渲染，用来判断改动像素的颜色倾向')
    ap.add_argument('--tol', type=int, default=2, help='灰度差超过几级算「变了」')
    a = ap.parse_args()

    d = os.path.abspath(a.dir)
    if not os.path.isdir(d):
        raise SystemExit('没有这个目录：%s' % d)

    ref_full = load(a.ref) if (a.ref and os.path.exists(a.ref)) else None

    print('目录：%s' % d)
    print('参照：%s\n' % (a.ref if ref_full is not None else '（无，只做互相比较）'))
    print('%-14s %-9s %-9s %-11s %-9s %-9s %s'
          % ('组', '档', '与F0不同', '平均|Δ|', '红主导', '蓝主导', '判读'))
    print('-' * 92)

    verdict = {}
    for stem, label in GROUPS:
        paths = [find(d, '%s_%s' % (stem, f)) for f in FILTERS]
        if any(p is None for p in paths):
            print('%-14s 缺图：%s' % (label, ' '.join(
                '%s_%s' % (stem, f) for f, p in zip(FILTERS, paths) if p is None)))
            continue
        imgs = [load(p) for p in paths]
        base = luma(imgs[0])
        h, w = base.shape
        rc = ref_full if ref_full is not None else None
        if rc is not None and rc.shape[:2] != (h, w):
            rc = ref_color(rc, base.shape)

        row = []
        for i in range(1, 4):
            lb = luma(imgs[i])
            delta = lb - base
            changed = np.abs(delta) > a.tol
            frac = changed.mean() * 100.0
            mad = float(np.abs(delta).mean())
            if rc is not None and changed.any():
                c = rc[changed]
                red = float(((c[:, 0] - c[:, 2]) > 12).mean() * 100)
                blue = float(((c[:, 2] - c[:, 0]) > 12).mean() * 100)
            else:
                red = blue = float('nan')
            if frac == 0.0:
                note = '一字不差'
            elif rc is not None and red > 55:
                note = '改在红区'
            elif rc is not None and blue > 55:
                note = '改在蓝区'
            elif frac > 50:
                note = '整体升降'
            else:
                note = '局部改动'
            print('%-14s %-9s %8.2f%% %10.2f %8.1f%% %8.1f%%  %s'
                  % (label, FNAME[i], frac, mad, red, blue, note))
            row.append((frac, mad, red, blue))
        verdict[label] = row
        print()

    print('-' * 92)
    for label, row in verdict.items():
        if all(r[0] == 0.0 for r in row):
            print('%s：F1/F2/F3 与 F0 逐像素相同 → NX Studio 应用态不认「单色滤镜」这一格。'
                  % label)
            print('        这一格只能在机身上试（相机内把 Filter 改档、存成 NCP 再导出）。')
        else:
            print('%s：有差异（最大 %.2f%% 像素被改动）→ 这一格在 NX Studio 里是活的。'
                  % (label, max(r[0] for r in row)))
    if not verdict:
        print('一张都没找到。确认导出的 JPG 已放进 %s，文件名保持 M19_BINA_F0.JPG 这种形态。' % d)


if __name__ == '__main__':
    main()
