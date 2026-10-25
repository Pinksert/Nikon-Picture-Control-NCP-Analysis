# -*- coding: utf-8 -*-
"""测量：套曲线后，每个预设相对目标还差多少饱和度 / 色相
   同时生成两个标定 NCP（饱和度+1、色相+1），供用户导出标定图后精确换算档位"""
import os, sys, json, struct, glob
import numpy as np
from PIL import Image
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r'C:\Users\admin\WorkBuddy\D300固件\.workbuddy\tmp')
from np2ncp_curve import build_ncp, OUT_MAX

ROOT = r'C:\Users\admin\WorkBuddy\D300固件'
SRC = os.path.join(ROOT, 'ncp jpg')
CURVE = os.path.join(ROOT, 'ncp_curve_all')
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


def pc_name(path):
    b = open(path, 'rb').read(20000)
    i = b.find(b'03100310')
    return None if i < 0 else b[i + 8:i + 28].rstrip(b'\x00').decode('latin1', 'replace')


def lut_of(ncp):
    b = open(ncp, 'rb').read()
    return np.array(struct.unpack('>257H', b[120:120 + 514]), dtype=np.float64) / OUT_MAX * 255.0


# ---------- 1. 测量各预设还差多少 ----------
base = os.path.join(SRC, 'DSC_4484_sd.JPG')
A, LA = load(base)
rows = []
for f in sorted(glob.glob(os.path.join(SRC, '*.JPG'))):
    n = pc_name(f)
    cp = os.path.join(CURVE, n + '_curve.NCP') if n else None
    if not n or not os.path.exists(cp):
        continue
    B, LB = load(f)
    lut = lut_of(cp)
    pred = lut[np.clip(np.round(LA), 0, 256).astype(np.int32)]
    sc = np.where(LA > 1e-6, pred / np.maximum(LA, 1e-6), 1.0)[..., None]
    labP = lab(np.clip(A * sc, 0, 255))          # 只套曲线后的状态
    labB = lab(B)                                 # 真正的目标

    cP = np.hypot(labP[..., 1], labP[..., 2])
    cB = np.hypot(labB[..., 1], labB[..., 2])
    m = cB > 3                                    # 只统计有彩度的像素
    ratio = float(np.mean(cB[m]) / np.mean(cP[m]))
    dP = np.degrees(np.arctan2(labP[..., 2], labP[..., 1]))[m]
    dB = np.degrees(np.arctan2(labB[..., 2], labB[..., 1]))[m]
    dh = dB - dP
    dh = (dh + 180) % 360 - 180                   # 环绕处理
    rows.append((n, ratio, float(np.mean(dh))))

print('%-22s %-16s %-12s' % ('预设', '还需饱和度倍率', '还需色相偏移'))
print('-' * 54)
for n, r, h in rows:
    print('%-22s %-16.3f %+7.2f 度' % (n, r, h))
json.dump([{'name': n, 'sat_ratio': r, 'hue_shift_deg': h} for n, r, h in rows],
          open(os.path.join(ROOT, 'curve_out', 'sat_hue_need.json'), 'w'),
          ensure_ascii=False, indent=1)
print('\n已存 curve_out/sat_hue_need.json')

# ---------- 2. 生成标定 NCP ----------
CAL = os.path.join(ROOT, 'ncp_curve_all')
for tag, sl, desc in [
    ('SATPLUS1', [0x83, 0x80, 0x80, 0x81, 0x80, 0xFF, 0xFF, 0xFF], '饱和度 +1'),
    ('SATMINUS1', [0x83, 0x80, 0x80, 0x7F, 0x80, 0xFF, 0xFF, 0xFF], '饱和度 -1'),
    ('HUEPLUS1', [0x83, 0x80, 0x80, 0x80, 0x81, 0xFF, 0xFF, 0xFF], '色相 +1'),
    ('HUEMINUS1', [0x83, 0x80, 0x80, 0x80, 0x7F, 0xFF, 0xFF, 0xFF], '色相 -1'),
]:
    out = build_ncp(tag[:20], 0x0001, sl)
    open(os.path.join(CAL, tag + '_calib.NCP'), 'wb').write(out)
    print('标定文件 %s_calib.NCP  (%s)' % (tag, desc))
