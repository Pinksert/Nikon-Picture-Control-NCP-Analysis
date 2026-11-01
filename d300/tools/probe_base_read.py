#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_base_read.py —— 读底子探针，看「换底子」到底有没有用。

对每一份探针，做两件事：
  1. 和原底子版本（real_v3 里的同一支）比 → 换底子把画面改了多少（ΔE00）
  2. 和官方最新版（real_target 里的同一支）比 → 离目标近了还是远了（平均差）

只有第 2 项下降，才算真收益。

    python d300/tools/probe_base_read.py --dir d300/samples/probe_base
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from diag_residual import to_lab, CLIP, de2000                # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
SAMP = os.path.join(ROOT, 'samples')
SIZE = 420

# 探针序号 → 原名（用来在 real_v3 / real_target 里找对照）
MAP = {
    'DENIM': 'DENIM', 'TOY': 'TOY', 'DRAMA': 'DRAMA',
    'SILENCE': 'SILENCE', 'RED': 'RED', 'SEPIA': 'SEPIA',
}


def load(p):
    im = ImageOps.exif_transpose(Image.open(p)).convert('RGB')
    r = SIZE / max(im.size)
    if r < 1.0:
        im = im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))),
                       Image.LANCZOS)
    return np.asarray(im, dtype=np.float64)


def find(d, name):
    if not os.path.isdir(d):
        return None
    best, bestk = None, 0
    for f in os.listdir(d):
        if not f.upper().endswith(('.JPG', '.JPEG')):
            continue
        k = sum(1 for a, b in zip(f.upper(), name.upper()) if a == b)
        if name.upper() in f.upper() and k > bestk:
            best, bestk = os.path.join(d, f), k
    return best


def cmp(a, b):
    m = ((a.min(2) > CLIP) & (a.max(2) < 255 - CLIP) &
         (b.min(2) > CLIP) & (b.max(2) < 255 - CLIP))
    la, lb = to_lab(a[m]), to_lab(b[m])
    ca = np.hypot(la[:, 1], la[:, 2]).mean()
    cb = np.hypot(lb[:, 1], lb[:, 2]).mean()
    return dict(mad=float(np.abs(a[m] - b[m]).mean()),
                de=float(de2000(la, lb).mean()),
                dc=float(ca - cb))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default=os.path.join(SAMP, 'probe_base'))
    a = ap.parse_args()
    d = a.dir
    if not os.path.isdir(d):
        raise SystemExit('还没有导出结果：%s' % d)

    rows = []
    for f in sorted(os.listdir(d)):
        if not f.upper().endswith(('.JPG', '.JPEG')):
            continue
        base = os.path.splitext(f)[0]
        hit = [v for k, v in MAP.items() if k in base.upper()]
        if not hit:
            continue
        name = hit[0]
        p_new = os.path.join(d, f)
        p_old = find(os.path.join(SAMP, 'real_v3'), name)
        p_tgt = find(os.path.join(SAMP, 'real_target'), name)
        if not p_old:
            print('跳过 %s：real_v3 里找不到 %s 的原版' % (f, name))
            continue
        A = load(p_new)
        O = load(p_old)
        T = load(p_tgt) if p_tgt else None
        r = dict(f=f, name=name, new=base)
        r['vs_old'] = cmp(A, O)
        if T is not None:
            r['new_t'] = cmp(A, T)
            r['old_t'] = cmp(O, T)
        rows.append(r)

    if not rows:
        raise SystemExit('%s 里没有认得出的探针图。' % d)

    print('%-22s %10s %10s %10s %10s %8s'
          % ('探针', 'ΔE00(改)', '距官方(旧)', '距官方(新)', '变化', '判定'))
    print('-' * 78)
    dn = do = 0
    for r in rows:
        if 'new_t' not in r:
            print('%-22s %10.2f %10s %10s %10s  缺官方对照'
                  % (r['new'], r['vs_old']['de'], '—', '—', '—'))
            continue
        dn += r['new_t']['de']
        do += r['old_t']['de']
        delta = r['new_t']['de'] - r['old_t']['de']
        mark = '✓ 更近' if delta < -0.10 else ('✗ 更远' if delta > 0.10 else '— 无差别')
        print('%-22s %10.2f %10.2f %10.2f %+10.2f  %s'
              % (r['new'], r['vs_old']['de'], r['old_t']['de'], r['new_t']['de'],
                 delta, mark))
    n = sum(1 for r in rows if 'new_t' in r)
    if n:
        print('-' * 78)
        print('均值：距官方 %.2f → %.2f（%+.2f）'
              % (do / n, dn / n, (dn - do) / n))


if __name__ == '__main__':
    main()
