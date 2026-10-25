# -*- coding: utf-8 -*-
"""量化 30 个预设：套上曲线后，与目标到底差多少？亮度差 + 色彩差分开算"""
import os, sys, json, struct, glob
import numpy as np
from PIL import Image
sys.stdout.reconfigure(encoding='utf-8')

ROOT = r'C:\Users\admin\WorkBuddy\D300固件'
SRC = os.path.join(ROOT, 'ncp jpg')
CURVE = os.path.join(ROOT, 'ncp_curve_all')
OUT_MAX = 32767.0
STEP = 4                      # 降采样，够统计用


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
    if i < 0:
        return None
    return b[i + 8:i + 28].rstrip(b'\x00').decode('latin1', 'replace')


def lut_of(ncp):
    b = open(ncp, 'rb').read()
    return np.array(struct.unpack('>257H', b[120:120 + 514]), dtype=np.float64) / OUT_MAX * 255.0


base = os.path.join(SRC, 'DSC_4484_sd.JPG')
A, LA = load(base)
rows = []
for f in sorted(glob.glob(os.path.join(SRC, '*.JPG'))):
    n = pc_name(f)
    if n is None:
        continue
    cp = os.path.join(CURVE, n + '_curve.NCP')
    if not os.path.exists(cp):
        continue
    B, LB = load(f)
    lut = lut_of(cp)
    pred = lut[np.clip(np.round(LA), 0, 256).astype(np.int32)]
    labB = lab(B)
    # 只改亮度、不动色相，用来分离"曲线能兑现"和"兑现不了"
    sc = np.where(LA > 1e-6, pred / np.maximum(LA, 1e-6), 1.0)[..., None]
    labP = lab(np.clip(A * sc, 0, 255))
    labA = lab(A)
    dl0 = np.abs(LA - LB).mean()
    dl1 = np.abs(pred - LB).mean()
    dc0 = np.abs(np.hypot(labA[..., 1], labA[..., 2]) - np.hypot(labB[..., 1], labB[..., 2])).mean()
    dc1 = np.abs(np.hypot(labP[..., 1], labP[..., 2]) - np.hypot(labB[..., 1], labB[..., 2])).mean()
    rows.append((n, dl0, dl1, (1 - dl1 / dl0) * 100 if dl0 else 0,
                 dc0, dc1, (1 - dc1 / dc0) * 100 if dc0 else 0))

print('%-22s %-18s %-18s' % ('预设', '亮度差 前→后', '色彩差 前→后'))
print('-' * 64)
for n, dl0, dl1, gl, dc0, dc1, gc in rows:
    print('%-22s %5.2f → %5.2f (%+4.0f%%)  %5.2f → %5.2f (%+4.0f%%)'
          % (n, dl0, dl1, gl, dc0, dc1, gc))
print()
print('亮度改善中位数 %.0f%%   色彩改善中位数 %.0f%%'
      % (np.median([r[3] for r in rows]), np.median([r[6] for r in rows])))
json.dump([{'name': r[0], 'luma_before': r[1], 'luma_after': r[2], 'luma_gain': r[3],
            'chroma_before': r[4], 'chroma_after': r[5], 'chroma_gain': r[6]} for r in rows],
          open(os.path.join(ROOT, 'curve_out', 'quality_report.json'), 'w'), ensure_ascii=False, indent=1)
print('报告已存 curve_out/quality_report.json')
