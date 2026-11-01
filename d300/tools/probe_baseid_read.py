#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_baseid_read.py —— 读底子指纹探针，量出「每个底子自己干了什么」。

探针由 pack_baseid_probe.py 生成：恒等曲线（影调不动）+ 只改底子编号。
所以渲出来的差别，全部是底子本身造成的，跟曲线无关。

两件事一次答完：
  1. NCP 到底认不认 08xx 创意底子编号？—— 若某张 08xx 与 0001 的差 ≈ 0，
     说明它回落了，这条路封死。
  2. 每个底子相对 STANDARD 的位移有多大（亮度 / 彩度 / 色相），
     作为「按底子重配」的定量依据。

⚠️ 口径：所有图共用 B1_STANDARD 的中间调遮罩。跨图比较不能各自圈遮罩，
   上一轮滑块标定就栽在这里（遮罩随参数漂移，C* 出现假非单调）。

    python d300/tools/probe_baseid_read.py
    python d300/tools/probe_baseid_read.py --dir d300/samples/probe_baseid
"""
import argparse
import csv
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from diag_residual import to_lab, CLIP, de2000                # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
DEF = os.path.join(ROOT, 'samples', 'probe_baseid')

ORDER = ['B1_STANDARD', 'B2_NEUTRAL', 'B3_VIVID', 'B4_MONOCHROME',
         'B5_DREAM', 'B6_BLEACH', 'B7_DENIM', 'B8_BINARY']
CODE = {'B1_STANDARD': 0x0001, 'B2_NEUTRAL': 0x03C2, 'B3_VIVID': 0x00C3,
        'B4_MONOCHROME': 0x064D, 'B5_DREAM': 0x0801, 'B6_BLEACH': 0x0808,
        'B7_DENIM': 0x080B, 'B8_BINARY': 0x0813}
BASIC = ['B1_STANDARD', 'B2_NEUTRAL', 'B3_VIVID', 'B4_MONOCHROME']
CREATIVE = ['B5_DREAM', 'B6_BLEACH', 'B7_DENIM', 'B8_BINARY']


def load(p, size=420):
    im = Image.open(p).convert('RGB')
    r = size / max(im.size)
    if r < 1.0:
        im = im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))),
                       Image.LANCZOS)
    return np.asarray(im, dtype=np.float64)


def find(d, tag):
    """按标签找图。同时接受「B1_STANDARD」与「01_B1_STANDARD」两种命名。"""
    want = tag.upper()
    for f in os.listdir(d):
        b, _ = os.path.splitext(f)
        b = b.upper()
        if b == want or b.endswith('_' + want):
            return os.path.join(d, f)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default=DEF)
    ap.add_argument('--csv', default=os.path.join(ROOT, 'samples', 'probe_baseid.csv'))
    a = ap.parse_args()
    d = a.dir
    jpg = [f for f in os.listdir(d) if f.upper().endswith(('.JPG', '.JPEG', '.JPE'))] \
        if os.path.isdir(d) else []
    if not jpg:
        raise SystemExit('还没有导出结果：%s 里没有 JPEG。\n'
                         '先把 _probe_baseid 那 8 份导出，放进这个目录。' % d)

    img = {}
    for t in ORDER:
        p = find(d, t)
        if p:
            img[t] = load(p)
    if 'B1_STANDARD' not in img:
        raise SystemExit('缺 B1_STANDARD（对照组），无法比较。')

    ref = img['B1_STANDARD']
    m = (ref.min(2) > CLIP) & (ref.max(2) < 255 - CLIP)
    lab0 = to_lab(ref[m])
    L0 = lab0[:, 0]
    C0 = np.hypot(lab0[:, 1], lab0[:, 2])
    print('固定像素集 %d 个（B1_STANDARD 中间调）。基准 C* 均值 %.2f / 中位 %.2f'
          % (int(m.sum()), C0.mean(), np.median(C0)))
    print('对照组：底子 0x0001 STANDARD + 恒等曲线 = 我们发布版用的底子')
    print()

    rows = []
    for t in ORDER:
        if t not in img:
            print('%-15s （缺）' % t)
            continue
        lab = to_lab(img[t][m])
        L = lab[:, 0]
        C = np.hypot(lab[:, 1], lab[:, 2])
        de = de2000(lab0, lab)
        mad = float(np.abs(img[t][m] - ref[m]).mean())
        r = dict(tag=t, code=CODE[t], mad=mad, de=float(de.mean()),
                 jnd=float((de > 2.3).mean() * 100.0),
                 dL=float((L - L0).mean()), dC=float((C - C0).mean()),
                 c_ratio=float(C.mean() / C0.mean()))
        rows.append(r)
        flag = '← 对照' if t == 'B1_STANDARD' else ''
        print('%-15s 0x%04X  平均差 %5.2f  ΔE00 %5.2f  超阈 %4.0f%%  '
              'ΔL* %+6.2f  ΔC* %+6.2f  C*比 %.3f %s'
              % (t, CODE[t], mad, r['de'], r['jnd'], r['dL'], r['dC'],
                 r['c_ratio'], flag))

    # ---------- 判定 ----------
    by = {r['tag']: r for r in rows}
    print()
    print('【判定】NCP 是否认创意底子编号')
    accepted, mapped, fallen = [], [], []
    for t in CREATIVE:
        if t not in by:
            continue
        r = by[t]
        if r['mad'] < 0.35:
            fallen.append(t)
            print('  ✗ %-13s 与 STANDARD 几乎相同（平均差 %.2f）→ 回落了' % (t, r['mad']))
        else:
            # 找它最像哪个基础底子：也可能是映射到了别的编号
            best = min([b for b in BASIC if b in by],
                       key=lambda b: _mad(img[t], img[b], m))
            same = _mad(img[t], img[best], m)
            if same < 0.35:
                mapped.append((t, best))
                print('  ~ %-13s 不是原样生效，等价于底子 %s（差 %.2f）'
                      % (t, best, same))
            else:
                accepted.append(t)
                print('  ✓ %-13s 独立生效（与 STANDARD 差 %.2f，与最像的基础底子 %s 也差 %.2f）'
                      % (t, r['mad'], best, same))
    print()
    print('  合计：独立生效 %d 个 / 映射到别的底子 %d 个 / 回落成 STANDARD %d 个'
          % (len(accepted), len(mapped), len(fallen)))
    if accepted:
        print('  结论：创意底子编号在 NCP 里有效（%s）—— 「按底子重配」这条路可做。'
              % ' / '.join(accepted))
    elif mapped:
        print('  结论：创意底子编号在 NCP 里不原样生效，但会被映射到别的底子'
              '（%s）—— 重配只能在这些落点之间选。'
              % ' / '.join('%s→%s' % m for m in mapped))
    else:
        print('  结论：创意底子编号在 NCP 里全部回落 —— 只能在 4 个基础底子里选，'
              '升级空间限于 %s 之间。' % ' / '.join(BASIC))

    # ---------- 位移有多大 ----------
    print()
    print('【位移】相对 STANDARD 的彩度变化（决定它能补多少「偏淡」）')
    for r in sorted([r for r in rows if r['tag'] != 'B1_STANDARD'],
                    key=lambda x: -x['dC']):
        print('  %-15s ΔC* %+6.2f   C* 变成 %.3f 倍   ΔL* %+5.2f'
              % (r['tag'], r['dC'], r['c_ratio'], r['dL']))

    if a.csv:
        os.makedirs(os.path.dirname(a.csv), exist_ok=True)
        with open(a.csv, 'w', encoding='utf-8-sig') as f:
            f.write('tag,base,mad,dE00,jnd_pct,dL,dC,c_ratio\n')
            for r in rows:
                f.write('%s,0x%04X,%.4f,%.4f,%.2f,%.4f,%.4f,%.4f\n'
                        % (r['tag'], r['code'], r['mad'], r['de'], r['jnd'],
                           r['dL'], r['dC'], r['c_ratio']))
        print()
        print('已写 %s' % a.csv)


def _mad(a, b, m):
    return float(np.abs(a[m] - b[m]).mean())


if __name__ == '__main__':
    main()
