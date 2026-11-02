#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""anchor_render.py —— 生成「与滤镜无关的中性锚点」，跨底片映射的公共输入域。

为什么要有这个东西
------------------
`docs/25` 第五节测出来：官方渲染不是「我们的 RGB → 官方 RGB」的逐像素函数。
同一个我们的 RGB，官方在两张底片上给出差 4.07 级的输出，而同一张图内部只差 0.65 级。
原因是「我们的 RGB」是经过我们的 NCP 渲出来的 —— NCP 把彩度塌缩、把彩色压成黑白，
信息已经丢了，同一个输出值对应许多种原色，条件均值自然随底片的色彩构成漂移。

换一个域就能绕开：用一张**不经过任何 Picture Control** 的中性渲染当输入。
它几乎是 raw 的双射（只丢掉高光溢出那一点），所以「锚点 → 官方成片」重新变成逐像素函数，
一张 LUT 就能跨底片。这就是本脚本要产出的东西。

三条硬约束（缺一条就退化回「一图一标定」）
------------------------------------------
1. **不能用逐图自适应**：rawpy 默认开 `auto_scale`（按本图最大值归一）和
   `auto_bright`（按本图直方图提亮）。两张底片 raw 最大值是 2593 和 4095，
   开着这两个，同一场景亮度的像素会被映到不同值 —— 跨图必崩。必须关掉。
2. **白电平必须是常数**：D300 是 12 位，满阱 4095。libraw 在 `no_auto_scale` 下
   把数据当 16 位处理（除以 65535），所以线性值要乘 16 才是「raw/4095」。
   这个 16 是相机常数，不是从图里量出来的。
3. **相机白平衡要照抄**：as-shot 白平衡是照片的元数据，NX Studio 也读同一份。
   它逐图不同，但两边一致，所以不引入歧义；反过来如果不用它，LUT 就得额外学白平衡。

输出
----
`A = 255 * sRGB_OETF( clip(v16 / 4095 * 2**EXPOSURE_STOPS, 0, 1) )`
其中 `v16` 是 rawpy 关掉一切自适应后的线性 sRGB（相机白平衡 + 机内色彩矩阵）。
再裁到 NX Studio 的成片尺寸（4288×2848），裁切偏移用 `--align` 搜一次后缓存。

    python tools/anchor_render.py --nef X.NEF --out anchor.jpg
    python tools/anchor_render.py --nef X.NEF --out a.jpg --align 参考图.jpg
    python tools/anchor_render.py --nef X.NEF --out a.jpg --crop 16,10
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))

# —— 相机常数（D300）：改相机才动这两行 ——
RAW_MAX = 4095.0        # 12 位满阱；libraw 按 65535 归一，故下面再乘 16
BIT_SHIFT = 65535.0 / RAW_MAX      # 16.0
EXPOSURE_STOPS = 0.0               # 不再额外增益：加 1 档就有 ~10% 像素顶到天花板，
                                   # 高光一信息就没了，跨底片也就无从谈起
CROP_FILE = os.path.join(HERE, 'anchor_crop.json')


def srgb_oetf(lin):
    """线性 0..1 → sRGB 0..1（IEC 61966-2-1）"""
    x = np.clip(lin, 0.0, 1.0)
    lo = x <= 0.0031308
    out = np.empty_like(x)
    out[lo] = 12.92 * x[lo]
    out[~lo] = 1.055 * np.power(x[~lo], 1.0 / 2.4) - 0.055
    return out


def render(nef, demosaic='AHD'):
    """读一张 NEF，返回线性 sRGB 的 float32 数组（0..1 已按相机常数归一）"""
    import rawpy
    algo = {'AHD': rawpy.DemosaicAlgorithm.AHD,
            'VNG': rawpy.DemosaicAlgorithm.VNG,
            'LINEAR': rawpy.DemosaicAlgorithm.LINEAR,
            'PPG': rawpy.DemosaicAlgorithm.PPG}.get(demosaic.upper(),
                                                     rawpy.DemosaicAlgorithm.AHD)
    raw = rawpy.imread(nef)
    v = raw.postprocess(
        use_camera_wb=True, use_auto_wb=False,
        no_auto_scale=True, no_auto_bright=True,
        user_black=0,
        output_bps=16, gamma=(1, 1),
        output_color=rawpy.ColorSpace.sRGB,
        demosaic_algorithm=algo,
        median_filter_passes=0,
        fbdd_noise_reduction=rawpy.FBDDNoiseReductionMode.Off,
        highlight_mode=rawpy.HighlightMode.Clip,
    )
    wb = list(raw.camera_whitebalance)
    raw.close()
    lin = v.astype(np.float32) * (BIT_SHIFT / 65535.0) * (2.0 ** EXPOSURE_STOPS)
    return np.clip(lin, 0.0, 1.0), wb


def to_u8(lin):
    return np.round(srgb_oetf(lin) * 255.0).astype(np.uint8)


def crop_to(lin, shape, dx, dy):
    h, w = shape
    return lin[dy:dy + h, dx:dx + w]


def load_crop():
    if os.path.exists(CROP_FILE):
        try:
            return json.load(open(CROP_FILE, encoding='utf-8'))
        except Exception:
            pass
    return {}


def save_crop(key, dx, dy, h, w):
    d = load_crop()
    d[key] = [dx, dy, h, w]
    with open(CROP_FILE, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def small(im, n=256):
    a = np.asarray(Image.fromarray(im).resize((n, n * im.shape[0] // im.shape[1]),
                                              Image.BILINEAR), dtype=np.float64)
    return a


def align_search(lin, ref_shape, ref_u8, n=320):
    """搜裁切偏移。

    打分不用平均绝对差 —— 锚点是线性直出、参考图是 NX 的成片，两者影调差一大截，
    绝对差主要反映影调差而不是对齐。用**亮度相关系数**：错位几像素相关性就掉，
    影调差异（单调函数）不影响相关性。
    """
    H, W = lin.shape[:2]
    h, w = ref_shape
    ref = small(ref_u8, n)
    refY = ref.mean(2)

    def score(dx, dy):
        s = small(to_u8(crop_to(lin, (h, w), dx, dy)), n)
        if s.shape != ref.shape:
            return -2.0
        y = s.mean(2)
        a = y - y.mean()
        b = refY - refY.mean()
        den = float(np.sqrt((a * a).sum() * (b * b).sum()))
        return float((a * b).sum() / den) if den > 1e-9 else -2.0

    best = (-2.0, 0, 0)
    for dy in range(0, H - h + 1, 2):
        for dx in range(0, W - w + 1, 2):
            s = score(dx, dy)
            if s > best[0]:
                best = (s, dx, dy)
    _, dx, dy = best
    for ddy in range(-2, 3):
        for ddx in range(-2, 3):
            x, y = dx + ddx, dy + ddy
            if x < 0 or y < 0 or y + h > H or x + w > W:
                continue
            s = score(x, y)
            if s > best[0]:
                best = (s, x, y)
    return best[1], best[2], best[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--nef', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--align', default=None, help='参考图（成片），搜裁切偏移')
    ap.add_argument('--crop', default=None, help='dx,dy —— 直接指定裁切偏移')
    ap.add_argument('--size', type=int, default=0, help='>0 时另存一张长边 N 的小图')
    ap.add_argument('--demosaic', default='AHD')
    a = ap.parse_args()

    lin, wb = render(a.nef, a.demosaic)
    print('%s  线性锚点 %dx%d  相机白平衡 %s'
          % (os.path.basename(a.nef), lin.shape[1], lin.shape[0],
             [round(x, 3) for x in wb[:4]]))
    print('  线性中位 %.4f / 99分位 %.4f / 溢出 %.2f%%'
          % (np.median(lin), np.percentile(lin, 99),
             100.0 * (lin.max(2) >= 1.0).mean()))

    key = os.path.basename(a.nef)
    h = w = 0
    if a.crop:
        dx, dy = [int(x) for x in a.crop.split(',')]
        h, w = 2848, 4288
        if lin.shape[0] > lin.shape[1]:        # 竖幅
            h, w = 4288, 2848
    elif a.align:
        ru = np.asarray(Image.open(a.align).convert('RGB'))
        h, w = ru.shape[:2]
        dx, dy, r = align_search(lin, (h, w), ru)
        print('  对齐：偏移 (%d,%d)，亮度相关系数 %.4f' % (dx, dy, r))
        save_crop(key, dx, dy, h, w)
    else:
        c = load_crop().get(key, [0, 0, 0, 0])
        dx, dy, h, w = c
        if h:
            print('  用缓存的裁切偏移 (%d,%d)，目标 %dx%d' % (dx, dy, w, h))

    img = to_u8(lin)
    if h and w:
        img = img[dy:dy + h, dx:dx + w]
    unused = (lin.shape[0] - img.shape[0], lin.shape[1] - img.shape[1])
    print('  裁掉 %d 行 / %d 列（应为 32 / 20）' % unused)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or '.', exist_ok=True)
    Image.fromarray(img).save(a.out, quality=95)
    print('  → %s  %dx%d' % (a.out, img.shape[1], img.shape[0]))

    if a.size:
        r = a.size / max(img.shape[:2])
        sm = Image.fromarray(img).resize((max(1, int(round(img.shape[1] * r))),
                                          max(1, int(round(img.shape[0] * r)))),
                                         Image.LANCZOS)
        stem, ext = os.path.splitext(a.out)
        sm.save('%s_%d%s' % (stem, a.size, ext or '.jpg'), quality=95)
        print('  → %s_%d%s' % (stem, a.size, ext or '.jpg'))


if __name__ == '__main__':
    main()
