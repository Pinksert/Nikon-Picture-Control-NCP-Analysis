# -*- coding: utf-8 -*-
"""v3 收敛验证：4484（有基准，可对比 v2 残差）+ 5658（泛化测试）"""
import sys
import numpy as np
from PIL import Image
sys.stdout.reconfigure(encoding='utf-8')

ROOT = r'C:\Users\admin\WorkBuddy\D300固件\ncp jpg'


def lum(p):
    a = np.asarray(Image.open(p).convert('RGB'), dtype=np.float64)
    return a, 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]


def srgb_to_lab(rgb):
    x = rgb / 255.0
    lin = np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = lin @ m.T
    r = xyz / np.array([0.95047, 1.0, 1.08883])
    f = np.where(r > 0.008856, np.cbrt(r), 7.787 * r + 16.0 / 116.0)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]),
                     200 * (f[..., 1] - f[..., 2])], axis=-1)


def report(tag, c_path, t_path):
    C, LC = lum(c_path)
    B, LB = lum(t_path)
    labC, labT = srgb_to_lab(C), srgb_to_lab(B)
    skin = (labC[..., 0] > 55) & (labC[..., 0] < 85)
    skinT = (labT[..., 0] > 55) & (labT[..., 0] < 85)
    print('— %s —' % tag)
    print('  亮度均值: C %.2f  T %.2f  (%+.2f)' % (LC.mean(), LB.mean(), LC.mean() - LB.mean()))
    print('  逐像素亮度差: %.2f / 255' % np.abs(LC - LB).mean())
    print('  a* 差 %.2f   b* 差 %.2f   饱和度差 %.2f' % (
        np.abs(labC[..., 1] - labT[..., 1]).mean(),
        np.abs(labC[..., 2] - labT[..., 2]).mean(),
        np.abs(np.hypot(labC[..., 1], labC[..., 2]) - np.hypot(labT[..., 1], labT[..., 2])).mean()))
    print('  肤色 b*: C %.2f  T %.2f  (正=偏黄)' % (labC[..., 2][skin].mean(), labT[..., 2][skinT].mean()))
    return LC, LB


print('=' * 70)
print('4484：v3 应用版 vs 新系统人像（v2 时残差是 9.48）')
print('=' * 70)
_, LC44 = report('4484', ROOT + r'\DSC_4484 d300 pt.JPG', ROOT + r'\DSC_4484 new pt.JPG')

print()
print('=' * 70)
print('5658：v3 应用版 vs 新系统人像（泛化测试，此图未参与校准）')
print('=' * 70)
_, LC56 = report('5658', ROOT + r'\DSC_5658 d300 pt.JPG', ROOT + r'\DSC_5658 new pt.JPG')

print()
print('=' * 70)
print('4484 亮度残差补偿（下一轮用，若有必要）')
print('=' * 70)
_, LA = lum(ROOT + r'\DSC_4484 D300 sd.JPG')
ai = np.clip(np.round(LA), 0, 255).astype(np.int32).ravel()
_, LT = lum(ROOT + r'\DSC_4484 new pt.JPG')
sums = np.bincount(ai, weights=LT.ravel(), minlength=256)
cnts = np.bincount(ai, minlength=256)
tmap = np.where(cnts > 50, sums / np.maximum(cnts, 1), np.nan)
sums2 = np.bincount(ai, weights=LC44.ravel(), minlength=256)
cmap = np.where(cnts > 50, sums2 / np.maximum(cnts, 1), np.nan)
d = tmap - cmap
have = ~np.isnan(d)
df = d.copy()
df[~have] = np.interp(np.where(~have)[0], np.where(have)[0], d[have])
for v in (16, 64, 128, 192, 240):
    print('  %3d: 目标 %6.2f  当前 %6.2f  补偿 %+6.2f' % (v, tmap[v], cmap[v], df[v]))
print('  残差绝对值均值: %.2f / 255' % np.nanmean(np.abs(df)))
