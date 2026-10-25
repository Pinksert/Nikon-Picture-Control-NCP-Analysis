# -*- coding: utf-8 -*-
"""从 4 张标定图测出：饱和度每档增益 g、色相每档角度 d
   （线性对称假设下，+1/-1 的比值与差值即可解出，不需要 0 点基准）
   然后把 30 个预设的"还差多少"换算成滑块档位，重新生成 NCP"""
import os, sys, json, glob
import numpy as np
from PIL import Image
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r'C:\Users\admin\WorkBuddy\D300固件\.workbuddy\tmp')
from np2ncp_curve import build_ncp, OUT_MAX

ROOT = r'C:\Users\admin\WorkBuddy\D300固件'
SRC = os.path.join(ROOT, 'ncp jpg')
STEP = 4


def load(p):
    a = np.asarray(Image.open(p).convert('RGB'), dtype=np.float64)[::STEP, ::STEP]
    return a, 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]


def chroma_hue(rgb):
    L = lab(rgb)
    return np.hypot(L[..., 1], L[..., 2]), np.degrees(np.arctan2(L[..., 2], L[..., 1]))


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
    for f in glob.glob(os.path.join(SRC, '*.JPG')):
        if sub.lower() in os.path.basename(f).lower():
            return f
    raise SystemExit('找不到 ' + sub)


# ---------- 1. 饱和度增益 ----------
_, Lp = load(find('SATplus1'))
_, Lm = load(find('SATminus1'))
# 基准（滑块=0）：从 +1/-1 的对称平均重建（线性假设下）——但比值法更稳：
# 直接算同像素 chroma 比（逐像素，只取有彩度的）
Ap, LAp = load(find('SATplus1'))
Am, LAm = load(find('SATminus1'))
cp = np.hypot(*[lab(Ap)[..., 1], lab(Ap)[..., 2]])
cm = np.hypot(*[lab(Am)[..., 1], lab(Am)[..., 2]])
m = (cm > 5) & (cp > 5)
r_pix = cp[m] / cm[m]
g_sat = float((r_pix - 1).mean())            # 每档饱和度增益（+1 档 → chroma ×(1+g)）
print('饱和度：+1/-1 逐像素 chroma 比 中位 %.4f  → 每档增益 g = %+.4f（%.1f%%）'
      % (np.median(r_pix), g_sat, g_sat * 100))

# ---------- 2. 色相每档角度 ----------
Ap2, LHAp = load(find('HUEplus1'))
Am2, LHAm = load(find('HUEminus1'))
cP, hP = chroma_hue(Ap2)
cM, hM = chroma_hue(Am2)
m2 = (cP > 5) & (cM > 5)
dh = hP[m2] - hM[m2]
dh = (dh + 180) % 360 - 180
d_hue = float(dh.mean()) / 2.0               # +1 与 -1 的差 = 2 档
print('色相  ：+1 与 -1 的色相角差 中位 %.2f° → 每档 %.2f°' % (np.median(dh) * 1.0, d_hue))

json.dump({'g_sat_per_step': g_sat, 'hue_deg_per_step': d_hue},
          open(os.path.join(ROOT, 'curve_out', 'slider_calibration.json'), 'w'))

# ---------- 3. 换算 30 个预设并重新生成 ----------
need = json.load(open(os.path.join(ROOT, 'curve_out', 'sat_hue_need.json')))
MONO_BASE = {'MONOCHROME', 'FLAT_MONOCHROME', 'DEEPTONE_MONOCHROME', 'BINARY', 'CARBON',
             'CHARCOAL', 'GRAPHITE', 'BLUE', 'RED', 'SEPIA', 'PINK'}   # 用了单色底子 064D 的
print('\n%-22s %-10s %-10s' % ('预设', '饱和度档', '色相档'))
print('-' * 46)
results = []
for item in need:
    n = item['name']
    if n in MONO_BASE:
        results.append((n, 0, 0.0, 0, 0.0, ' '))
        print('%-22s %+4d (%5s)   %+3d (%5s)   [单色底子，无色彩滑块]' % (n, 0, '-', 0, '-'))
        continue
    s = np.log(item['sat_ratio']) / np.log(1 + g_sat) if item['sat_ratio'] > 0 else 0
    if np.isnan(s):
        s = 0.0
    s_sat = int(round(s))
    s_sat = max(-3, min(3, s_sat))            # D300 UI 范围 ±3
    clipped = '!' if abs(s - s_sat) > 0.3 else ' '
    hs = item['hue_shift_deg']
    h = 0 if (np.isnan(hs) or abs(d_hue) <= 0.05) else int(round(hs / d_hue))
    h_hue = max(-3, min(3, h))
    hc = '!' if (not np.isnan(hs)) and abs(hs / max(d_hue, 0.01) - h_hue) > 0.5 else ' '
    results.append((n, s_sat, s, h_hue, hs, clipped + hc))
    print('%-22s %+4d (%+5.2f)%s %+3d (%+6.1f°)%s' % (n, s_sat, s, clipped, h_hue,
                                                       hs / max(d_hue, 0.01), hc))

json.dump([{'name': n, 'sat_steps': s, 'hue_steps': h} for n, s, _, h, _, _ in results],
          open(os.path.join(ROOT, 'curve_out', 'slider_steps.json'), 'w'), indent=1)
print('\n档位表已存 curve_out/slider_steps.json（! = 超出 ±3 被钳位）')
