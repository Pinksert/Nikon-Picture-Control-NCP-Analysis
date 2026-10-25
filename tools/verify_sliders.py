# -*- coding: utf-8 -*-
"""v3+滑块版验收：DREAM / SILENCE 套用后 vs 新系统目标
   并检查饱和度/色相滑块是否生效（对比上一轮的"还需"值）"""
import os, sys, glob
import numpy as np
from PIL import Image
sys.stdout.reconfigure(encoding='utf-8')

ROOT = r'C:\Users\admin\WorkBuddy\D300固件\ncp jpg'
STEP = 4


def load(p):
    a = np.asarray(Image.open(p).convert('RGB'), dtype=np.float64)[::STEP, ::STEP]
    return a, 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]


def lab(rgb):
    x = rgb / 255.0
    lin = np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = lin @ m.T
    r = xyz / np.array([0.95047, 1.0, 1.08883])
    f = np.where(r > 0.008856, np.cbrt(r), 7.787 * r + 16.0 / 116.0)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]),
                     200 * (f[..., 1] - f[..., 2])], axis=-1)


def find(sub):
    for f in glob.glob(os.path.join(ROOT, '*.JPG')):
        if sub.lower() in os.path.basename(f).lower():
            return f
    raise SystemExit('找不到 ' + sub)


CASES = [
    ('DREAM', 'v3ncp DREAM', 'new_10', '上轮还需: 饱和×0.873、色相+5.54°（-1档/色相+2档）'),
    ('SILENCE', 'v3ncp SILENCE', 'new_16', '上轮还需: 饱和×0.316、色相+0.52°（饱和-3档钳位）'),
]

for name, csub, tsub, note in CASES:
    C, LC = load(find(csub))
    T, LT = load(find(tsub))
    labC, labT = lab(C), lab(T)
    cC = np.hypot(labC[..., 1], labC[..., 2])
    cT = np.hypot(labT[..., 1], labT[..., 2])
    m = cT > 3
    ratio = float(np.mean(cT[m]) / np.mean(cC[m]))
    hC = np.degrees(np.arctan2(labC[..., 2], labC[..., 1]))[m]
    hT = np.degrees(np.arctan2(labT[..., 2], labT[..., 1]))[m]
    dh = (hT - hC + 180) % 360 - 180
    print('=' * 66)
    print(name, '  (' + note + ')')
    print('=' * 66)
    print('  亮度均值: C %.2f  T %.2f  (%+.2f)' % (LC.mean(), LT.mean(), LC.mean() - LT.mean()))
    print('  逐像素亮度差: %.2f / 255' % np.abs(LC - LT).mean())
    print('  饱和度: C/T = %.3f  （1.00 = 完美；<1 = 我们偏淡，>1 = 偏浓）' % ratio)
    print('  色相残差: %+.2f°' % float(dh.mean()))
    print('  色度绝对差: %.2f' % np.abs(cC - cT).mean())
    print()
