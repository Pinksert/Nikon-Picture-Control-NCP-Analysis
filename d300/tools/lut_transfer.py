#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lut_transfer.py —— 把「在标定底片上做出来的 LUT」搬到一张新底片上用。

背景
----
`lut/` 里那 26 个 `.cube` 是在 DSC_4484 上标的。直接套到别的图上会掉一半收益
（`docs/25`：2.13 → 3.33）。原因是官方渲染除了看「这个像素是什么颜色」，
还看「这张图整体是什么样」—— 换图之后，同一个输入色在官方那边会落到别处。

`tools/crossfilm_calib.py` 把这个「看整图」的部分测出来了：它几乎就是一个
**整图共用的 3×4 颜色仿射**（12 个参数）。逐支解出来能回到 2.14（同图留出的下限是 2.13），
也就是说换图多出来的那 1.2 分，12 个参数就能吃掉。

所以搬 LUT 的正确姿势不是「搬 .cube」，而是「搬 .cube + 现场解一个 g」。

怎么用
------
在要处理的那张底片上，随便挑**一支**滤镜，用 NX Studio 各导一次
（一次套我们的 NCP，一次套官方 NP3），得到一对参考图；本脚本用这对图解出 g，
然后把 26 支全部按 g 预补偿后再套各自的 cube。

    # 第一步：解 g（存成 json，之后可复用）
    python tools/lut_transfer.py --ref-cube lut/29_STANDARD.cube \
        --ref-ours  ref/29_STANDARD__O.jpg --ref-official ref/29_STANDARD__T.jpg \
        --save tmp/g.json

    # 第二步：批量套用
    python tools/lut_transfer.py --affine tmp/g.json \
        --cubes lut --in-dir ours/ --out-dir out/ --affine-suffix __O

`--in-dir` 里的文件名要是 `NN_名字.jpg` 这种，脚本按同名去 `lut/` 找 cube。
文件名后缀不干净时用 `--strip` 指定要剥掉的后缀（如 `__O`）。

    # 也可以一次只处理一张，不吃目录约定
    python tools/lut_transfer.py --affine tmp/g.json \
        --pair lut/01_DREAM.cube a.jpg b.jpg
"""
import argparse
import glob
import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lut_fit import read_cube, interp, apply_cube            # noqa: E402
from crossfilm_calib import fit_pre, affine_apply            # noqa: E402


def load(path, size=0):
    im = Image.open(path).convert('RGB')
    if size and max(im.size) > size:
        r = size / max(im.size)
        im = im.resize((max(1, int(round(im.width * r))),
                        max(1, int(round(im.height * r)))), Image.LANCZOS)
    return np.asarray(im, dtype=np.float64)


def load_cube255(path):
    """read_cube 给的是 0..1，interp 要 0..255 的网格 —— 乘回去，别忘（忘过一次，
    g 直接发散到 1000 倍）"""
    return read_cube(path) * 255.0


def save(img, path, q=95):
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    Image.fromarray(np.uint8(np.round(np.clip(img, 0, 255)))).save(path, quality=q)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ref-cube', help='参考滤镜的 cube（要有，才能把 g 解在同一个输入域里）')
    ap.add_argument('--ref-ours', help='参考滤镜：我们 NCP 的成片')
    ap.add_argument('--ref-official', help='参考滤镜：官方 NP3 的成片')
    ap.add_argument('--save', help='把解出来的 g 存成 json')
    ap.add_argument('--affine', help='直接读一份已解好的 g（跳过求解）')
    ap.add_argument('--cubes', help='cube 目录')
    ap.add_argument('--in-dir', help='待处理图目录')
    ap.add_argument('--out-dir', help='输出目录')
    ap.add_argument('--strip', default='', help='输入文件名里要剥掉的后缀，如 __O')
    ap.add_argument('--pair', nargs=3, action='append', default=[],
                    metavar=('CUBE', 'IN', 'OUT'))
    ap.add_argument('--fit-size', type=int, default=700,
                    help='解 g 时把参考图缩到这个长边（g 只有 12 个参数，700 够了；'
                         '整幅 12M 像素跑高斯-牛顿会跑到天荒地老）')
    ap.add_argument('--pure-ours', action='store_true',
                    help='输出「只做了 g 预补偿、不套 cube」的图，用来看 g 本身的作用')
    a = ap.parse_args()

    # ---- 1) 拿到 g ----
    if a.affine:
        d = json.load(open(a.affine, encoding='utf-8'))
        M, b = np.array(d['M'], float), np.array(d['b'], float)
        print('读入 g：\n%s\n%s' % (np.array2string(M, precision=4),
                                   np.array2string(b, precision=3)))
    elif a.ref_cube and a.ref_ours and a.ref_official:
        cube = load_cube255(a.ref_cube)
        O, T = load(a.ref_ours, a.fit_size), load(a.ref_official, a.fit_size)
        if O.shape != T.shape:
            h = min(O.shape[0], T.shape[0])
            w = min(O.shape[1], T.shape[1])
            O, T = O[:h, :w], T[:h, :w]
        print('参考：%s  %s vs %s'
              % (os.path.basename(a.ref_cube), os.path.basename(a.ref_ours),
                 os.path.basename(a.ref_official)))
        print('  套 cube 前的差 %.2f 级' % np.abs(O - T).mean())
        # 只用中间调拟合：两端剪裁像素对 g 没有信息，还会把仿射往外拽
        m = (O.min(2) > 2) & (O.max(2) < 253) & (T.min(2) > 2) & (T.max(2) < 253)
        if m.sum() < 20000:
            m = np.ones(O.shape[:2], bool)
        M, b = fit_pre(cube, O[m], T[m], iters=6)
        pred = np.clip(interp(cube, affine_apply(O[m], M, b)), 0, 255)
        print('  解出 g 之后 %.2f 级（拟合用的 %d 个像素）'
              % (np.abs(pred - T[m]).mean(), int(m.sum())))
        print('  M =\n%s\n  b = %s' % (np.array2string(M, precision=4),
                                       np.array2string(b, precision=2)))
        if a.save:
            os.makedirs(os.path.dirname(os.path.abspath(a.save)) or '.', exist_ok=True)
            json.dump({'M': M.tolist(), 'b': b.tolist(),
                       'ref_cube': os.path.basename(a.ref_cube)},
                      open(a.save, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
            print('  → %s' % a.save)
    else:
        ap.error('要么给 --affine，要么给 --ref-cube/--ref-ours/--ref-official')

    # ---- 2) 套用 ----
    jobs = [(c, i, o) for c, i, o in a.pair]
    if a.cubes and a.in_dir and a.out_dir:
        for f in sorted(os.listdir(a.in_dir)):
            stem, ext = os.path.splitext(f)
            if ext.lower() not in ('.jpg', '.jpeg', '.png', '.tif', '.tiff'):
                continue
            key = stem[:-len(a.strip)] if a.strip and stem.endswith(a.strip) else stem
            hits = glob.glob(os.path.join(a.cubes, '*%s.cube' % key)) + \
                glob.glob(os.path.join(a.cubes, '*%s.CUBE' % key))
            if not hits:
                print('  跳过 %s（没有同名 cube）' % f)
                continue
            jobs.append((hits[0], os.path.join(a.in_dir, f),
                         os.path.join(a.out_dir, stem + '.jpg')))
    if not jobs:
        print('没有要处理的文件。')
        return

    def run(x, cube):
        """整幅 12M 像素一次性 interp 会吃掉几个 G，分块走"""
        flat = x.reshape(-1, 3)
        out = np.empty_like(flat)
        step = 1500000
        for s in range(0, flat.shape[0], step):
            e = min(s + step, flat.shape[0])
            y = affine_apply(flat[s:e], M, b)
            out[s:e] = y if cube is None else interp(cube, y)
        return np.clip(out.reshape(x.shape), 0, 255)

    for cube_p, in_p, out_p in jobs:
        cube = None if a.pure_ours else load_cube255(cube_p)
        save(run(load(in_p), cube), out_p)
        print('  %-34s → %s' % (os.path.basename(in_p), out_p))


if __name__ == '__main__':
    main()
