# -*- coding: utf-8 -*-
"""残差分析：兼容系统下套 v2 曲线的导出（C）与新系统人像目标（T）差在哪
   ①NCP 是否真的生效（sd -> C 的映射 vs 我们写入的 v2 LUT）
   ②C 与 T 的剩余差距：亮度 / 色彩各占多少
   ③如果亮度还有残差，算一条补偿曲线"""
import sys, json
import numpy as np
from PIL import Image
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r'C:\Users\admin\WorkBuddy\D300固件\.workbuddy\tmp')
from np2ncp_curve import OUT_MAX

SD = r'C:\Users\admin\WorkBuddy\D300固件\ncp jpg\DSC_4484 D300 sd.JPG'
C  = r'C:\Users\admin\WorkBuddy\D300固件\ncp jpg\DSC_4484 D300 pt.JPG'
T  = r'C:\Users\admin\WorkBuddy\D300固件\ncp jpg\DSC_4484 pt new.JPG'
v2 = json.load(open(r'C:\Users\admin\WorkBuddy\D300固件\portrait_lut_v2.json'))['lut']


def lum(p):
    a = np.asarray(Image.open(p).convert('RGB'), dtype=np.float64)
    return a, 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]

A, LA = lum(SD)   # 兼容标准
Cc, LC = lum(C)   # 兼容 + 我们的 NCP
B, LB = lum(T)    # 新系统人像（目标）

print('=' * 70)
print('① NCP 生效性检查：sd -> C 的实测映射 vs 我们写入的 v2 LUT')
print('=' * 70)
ai = np.clip(np.round(LA), 0, 255).astype(np.int32).ravel()
bi = LC.ravel()
sums = np.bincount(ai, weights=bi, minlength=256)
cnts = np.bincount(ai, minlength=256)
meas = np.where(cnts > 50, sums / np.maximum(cnts, 1), np.nan)
# 与 v2 LUT 比（都在 0..255 域）
v2_255 = np.array(v2, dtype=np.float64)[:256] / OUT_MAX * 255.0
diff = np.abs(meas - v2_255)
print('  有效分箱 %d/256，平均差 %.2f / 255，最大差 %.2f' %
      (int((cnts > 50).sum()), np.nanmean(diff), np.nanmax(diff)))
print('  （平均差小 = NCP 确实按我们写的曲线生效了）')

print()
print('=' * 70)
print('② C（套曲线后）与 T（新系统人像）的剩余差距')
print('=' * 70)
print('  亮度均值：C %.2f   T %.2f   (差 %+.2f)' % (LC.mean(), LB.mean(), LC.mean() - LB.mean()))
print('  逐像素亮度平均差：%.2f / 255' % np.abs(LC - LB).mean())

# 色彩：Lab a*/b*
def srgb_to_lab(rgb):
    x = rgb / 255.0
    lin = np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = lin @ m.T
    r = xyz / np.array([0.95047, 1.0, 1.08883])
    f = np.where(r > 0.008856, np.cbrt(r), 7.787 * r + 16.0 / 116.0)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]),
                     200 * (f[..., 1] - f[..., 2])], axis=-1)

labC = srgb_to_lab(Cc); labT = srgb_to_lab(B)
print('  a*（红绿）平均差：%.2f' % np.abs(labC[..., 1] - labT[..., 1]).mean())
print('  b*（黄蓝）平均差：%.2f' % np.abs(labC[..., 2] - labT[..., 2]).mean())
print('  肤色区域 b* 偏移：C %.2f  T %.2f  （正=偏黄）' %
      (labC[..., 2][(labC[..., 0] > 55) & (labC[..., 0] < 85)].mean(),
       labT[..., 2][(labT[..., 0] > 55) & (labT[..., 0] < 85)].mean()))

print()
print('=' * 70)
print('③ 亮度残差补偿曲线（若要再迭代一轮，叠到 v2 上）')
print('=' * 70)
ci = np.clip(np.round(LC), 0, 255).astype(np.int32).ravel()
ti = LB.ravel()
sums = np.bincount(ci, weights=ti, minlength=256)
cnts = np.bincount(ci, minlength=256)
comp = np.where(cnts > 50, sums / np.maximum(cnts, 1), np.nan)
have = ~np.isnan(comp)
comp2 = comp.copy()
idx = np.where(have)[0]
comp2[~have] = np.interp(np.where(~have)[0], idx, comp[idx])
comp2 = np.maximum.accumulate(comp2)          # 单调化
out = [int(round(min(255.0, max(0.0, c)) / 255.0 * OUT_MAX)) for c in comp2]
json.dump({'lut': out}, open(r'C:\Users\admin\WorkBuddy\D300固件\portrait_comp.json', 'w'))
print('  补偿量（输入亮度 -> 目标-当前，正=还需提亮）：')
for v in (16, 64, 128, 192, 240):
    print('    %3d: %+6.2f / 255' % (v, comp2[v] - v))
print('  补偿 LUT 已存 portrait_comp.json')
