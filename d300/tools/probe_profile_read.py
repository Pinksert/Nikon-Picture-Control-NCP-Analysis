#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_profile_read.py —— 读 kind=1 命名空间里那 5 个从没用过的底子。

探针由 pack_profile_probe.py 生成：恒等曲线（影调不动）+ 只换底子编号。
所以渲出来的差别全部是底子本身造成的。

⭐ 这一轮的意义不一样：P1–P6 的编号全都在 Rome2.dll 的 kind=1 组里，
   查得到、不会崩，所以只要它们渲染出来不一样，就说明「底子」这一维
   是真能调的一格 —— 过去 26 支全都压在 STANDARD 上。

⚠️ 口径沿用 probe_baseid_read.py：共用 P0_STANDARD 的中间调遮罩，
   跨图比较不各自圈遮罩。

    python d300/tools/probe_profile_read.py --dir ../_probe_profile
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from diag_residual import to_lab, CLIP, de2000                # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
DEF = os.path.normpath(os.path.join(ROOT, '..', '_probe_profile'))

ORDER = ['P0_STANDARD', 'P1_PORTRAIT', 'P2_LANDSCAPE',
         'P3_D2XMODE1', 'P4_D2XMODE2', 'P5_D2XMODE3', 'P6_MONOCHROME']
CODE = {'P0_STANDARD': 0x0001, 'P1_PORTRAIT': 0x0486, 'P2_LANDSCAPE': 0x04C7,
        'P3_D2XMODE1': 0x0014, 'P4_D2XMODE2': 0x03D5, 'P5_D2XMODE3': 0x00D6,
        'P6_MONOCHROME': 0x064D}
NAME = {'P0_STANDARD': 'STANDARD', 'P1_PORTRAIT': 'PORTRAIT',
        'P2_LANDSCAPE': 'LANDSCAPE', 'P3_D2XMODE1': 'D2XMODE I',
        'P4_D2XMODE2': 'D2XMODE II', 'P5_D2XMODE3': 'D2XMODE III',
        'P6_MONOCHROME': 'MONOCHROME'}
REF = 'P0_STANDARD'
COLOR = ['P0_STANDARD', 'P1_PORTRAIT', 'P2_LANDSCAPE',
         'P3_D2XMODE1', 'P4_D2XMODE2', 'P5_D2XMODE3']


def load(p, size=480):
    im = Image.open(p).convert('RGB')
    r = size / max(im.size)
    if r < 1.0:
        im = im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))),
                       Image.LANCZOS)
    return np.asarray(im, dtype=np.float64)


def find(d, tag):
    want = tag.upper()
    for f in os.listdir(d):
        b = os.path.splitext(f)[0].upper()
        if b == want or b.endswith('_' + want):
            return os.path.join(d, f)
    return None


def mad(a, b, m):
    return float(np.abs(a[m] - b[m]).mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default=DEF)
    ap.add_argument('--csv', default=os.path.join(ROOT, 'samples', 'probe_profile.csv'))
    a = ap.parse_args()
    d = a.dir
    if not os.path.isdir(d):
        raise SystemExit('目录不存在：%s' % d)
    jpg = [f for f in os.listdir(d) if f.upper().endswith(('.JPG', '.JPEG'))]
    if not jpg:
        raise SystemExit('%s 里没有 JPEG。先在 NX Studio 里导出。' % d)

    img = {}
    for t in ORDER:
        p = find(d, t)
        if p:
            img[t] = load(p)
    if REF not in img:
        raise SystemExit('缺 %s（对照组）。' % REF)

    ref = img[REF]
    m = (ref.min(2) > CLIP) & (ref.max(2) < 255 - CLIP)
    lab0 = to_lab(ref[m])
    L0, C0 = lab0[:, 0], np.hypot(lab0[:, 1], lab0[:, 2])
    print('固定像素集 %d 个（%s 中间调）  基准 C* 均值 %.2f / 中位 %.2f'
          % (int(m.sum()), REF, C0.mean(), np.median(C0)))
    print('对照组：0x0001 STANDARD + 恒等曲线 = 我们发布版一直在用的底子')
    print()
    print('%-18s %-6s %-12s %s' % ('探针', '底子', '表里的名字', '与 STANDARD 的差'))
    print('-' * 78)

    rows = []
    for t in ORDER:
        if t not in img:
            print('%-18s （缺）' % t)
            continue
        lab = to_lab(img[t][m])
        L = lab[:, 0]
        C = np.hypot(lab[:, 1], lab[:, 2])
        de = de2000(lab0, lab)
        d_ = mad(img[t], ref, m)
        r = dict(tag=t, code=CODE[t], name=NAME[t], mad=d_,
                 de=float(de.mean()), jnd=float((de > 2.3).mean() * 100.0),
                 dL=float((L - L0).mean()), dC=float((C - C0).mean()),
                 c_ratio=float(C.mean() / C0.mean()),
                 sat=float(np.median(np.clip(
                     img[t][m] / np.maximum(ref[m], 1.0), 0, 4))))
        rows.append(r)
        flag = '← 对照' if t == REF else ''
        print('%-18s 0x%04X %-12s 平均差 %5.2f  ΔE00 %5.2f  超阈 %4.0f%%  '
              'ΔL* %+6.2f  ΔC* %+6.2f  C*比 %.3f %s'
              % (t, CODE[t], NAME[t], d_, r['de'], r['jnd'], r['dL'], r['dC'],
                 r['c_ratio'], flag))

    by = {r['tag']: r for r in rows}

    # ---------- 判定一：底子到底生不生效 ----------
    print()
    print('【判定 1】kind=1 的底子编号是否真的改变渲染')
    live, dead, mapped = [], [], []
    for t in COLOR[1:]:
        if t not in by:
            continue
        r = by[t]
        if r['mad'] < 0.35:
            dead.append(t)
            print('  ✗ %-14s 与 STANDARD 几乎一样（平均差 %.2f）→ 这个编号没生效'
                  % (NAME[t], r['mad']))
            continue
        best = min([b for b in COLOR if b in by and b != t],
                   key=lambda b: mad(img[t], img[b], m))
        same = mad(img[t], img[best], m)
        if same < 0.35:
            mapped.append((t, best))
            print('  ~ %-14s 不与 STANDARD 相同，但等价于 %s（差 %.2f）'
                  % (NAME[t], NAME[best], same))
        else:
            live.append(t)
            print('  ✓ %-14s 独立生效（vs STANDARD 差 %.2f，最像的 %s 也差 %.2f）'
                  % (NAME[t], r['mad'], NAME[best], same))
    print()
    print('  合计：独立生效 %d / 只是换了张皮 %d / 完全没反应 %d'
          % (len(live), len(mapped), len(dead)))

    # ---------- 判定二：这些底子把画面往哪推 ----------
    if live or mapped:
        print()
        print('【判定 2】各底子相对 STANDARD 的位移（谁最能救「偏淡」）')
        for r in sorted([r for r in rows if r['tag'] in COLOR[1:]],
                        key=lambda x: -x['dC']):
            print('  %-14s ΔC* %+6.2f（C* × %.3f）  ΔL* %+6.2f  ΔE00 %5.2f'
                  % (NAME[r['tag']], r['dC'], r['c_ratio'], r['dL'], r['de']))

    # ---------- 判定三：单色支 ----------
    if 'P6_MONOCHROME' in by:
        r = by['P6_MONOCHROME']
        print()
        print('【判定 3】MONOCHROME 对照（单色支一直在用的底子）')
        print('  与 STANDARD 平均差 %.2f / ΔE00 %.2f —— 这条链是熟的，'
              '数值只用来确认导出没串片。' % (r['mad'], r['de']))

    print()
    print('【怎么用】')
    if live:
        print('  底子这一格是活的：%s 都能独立生效。'
              % ' / '.join(NAME[t] for t in live))
        print('  下一步可以把 26 支按「最省力的底子」重配 —— 底子先把大方向推开，')
        print('  曲线只补剩下的残差，平均差应当比现在（全局 3.18 级）再降一截。')
    else:
        print('  底子这一格是死的：换编号不改变渲染，26 支只能继续压在 STANDARD 上，')
        print('  收益全部由曲线与后期 LUT 承担。')

    if a.csv:
        os.makedirs(os.path.dirname(a.csv), exist_ok=True)
        with open(a.csv, 'w', encoding='utf-8-sig') as f:
            f.write('tag,base,name,mad,dE00,jnd_pct,dL,dC,c_ratio\n')
            for r in rows:
                f.write('%s,0x%04X,%s,%.4f,%.4f,%.2f,%.4f,%.4f,%.4f\n'
                        % (r['tag'], r['code'], r['name'], r['mad'], r['de'],
                           r['jnd'], r['dL'], r['dC'], r['c_ratio']))
        print()
        print('已写 %s' % a.csv)


if __name__ == '__main__':
    main()
