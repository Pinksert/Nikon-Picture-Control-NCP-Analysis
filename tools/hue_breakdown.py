# -*- coding: utf-8 -*-
"""按色相区域分解 DREAM 的剩余差异：
   如果各色相带的差异不是恒定的，就证明是选择性色彩运算（色彩矩阵），
   全局滑块（饱和度/色相）在原理上表达不了。"""
import os, sys, glob
import numpy as np
from PIL import Image
sys.stdout.reconfigure(encoding='utf-8')

ROOT = r'C:\Users\admin\WorkBuddy\D300固件\ncp jpg'
STEP = 4


def load(p):
    a = np.asarray(Image.open(p).convert('RGB'), dtype=np.float64)[::STEP, ::STEP]
    return a


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


A = load(find('_sd.JPG')) if glob.glob(os.path.join(ROOT, '*_sd.JPG')) else None
C = load(find('v3ncp DREAM'))        # 我们的 DREAM 应用结果
T = load(find('new_10'))             # 新系统梦幻目标
labC, labT = lab(C), lab(T)
labA = lab(A) if A is not None else None

chA = np.hypot(labA[..., 1], labA[..., 2])
hA = (np.degrees(np.arctan2(labA[..., 2], labA[..., 1])) + 360) % 360
chC = np.hypot(labC[..., 1], labC[..., 2])
hC = (np.degrees(np.arctan2(labC[..., 2], labC[..., 1])) + 360) % 360
chT = np.hypot(labT[..., 1], labT[..., 2])
hT = (np.degrees(np.arctan2(labT[..., 2], labT[..., 1])) + 360) % 360

rows = []
print('按色相区域分解（目标 vs 我们的输出，亮度中位差 + 色度差）')
print('色相带           像素%   目标色度  我们色度  色度差   色相偏移  亮度差')
print('-' * 78)
hue_names = ['红(345-15)', '橙(15-45)', '黄(45-75)', '黄绿(75-105)', '绿(105-150)',
             '青(150-195)', '蓝(195-255)', '紫(255-300)', '品红(300-345)']
edges = [345, 15, 45, 75, 105, 150, 195, 255, 300, 345]
for i in range(9):
    lo, hi = edges[i], edges[i + 1]
    if lo < hi:
        mB = (hT >= lo) & (hT < hi)
        mC = (hC >= lo) & (hC < hi)
    else:
        mB = (hT >= lo) | (hT < hi)
        mC = (hC >= lo) | (hC < hi)
    n = mB.sum()
    if n < 200:
        continue
    pct = n / mB.size * 100
    dc = chT[mB].mean() - chC[mC].mean()
    dh = np.degrees(np.arctan2(labT[..., 2][mB], labT[..., 1][mB]).mean() -
                    np.arctan2(labC[..., 2][mC], labC[..., 1][mC]).mean())
    dl = labT[..., 0][mB].mean() - labC[..., 0][mC].mean()
    rows.append({'band':hue_names[i],'pct':round(pct,1),'chroma_target':round(float(chT[mB].mean()),2),'chroma_ours':round(float(chC[mC].mean()),2),'chroma_diff':round(float(dc),2),'hue_shift_deg':round(float(dh),2),'luma_diff':round(float(dl),2)})
    print('%-14s %5.1f%%  %8.2f  %8.2f  %+7.2f  %+8.2f  %+6.2f' %
          (hue_names[i], pct, chT[mB].mean(), chC[mC].mean(), dc, dh, dl))

print()
print('判读：如果\"色度差\"在各色相带之间差别很大（不是同一个数），')
print('      就说明差异是选择性色彩运算——全局饱和度/色相滑块在原理上表达不了。')
import json
json.dump(rows, open(r'C:////Users////admin////WorkBuddy////D300固件////curve_out////hue_breakdown.json','w'), ensure_ascii=False, indent=1)
print('已存 curve_out/hue_breakdown.json')
