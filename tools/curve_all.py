# -*- coding: utf-8 -*-
"""批量：DSC_4484_sd（兼容基准）+ 30 张新系统导出 → 30 个带曲线 NCP
   底子按预设名映射到 NCP 六个已知底子；控制点加 δ 预补偿"""
import os, sys, json, struct
import numpy as np
from PIL import Image
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r'C:\Users\admin\WorkBuddy\D300固件\.workbuddy\tmp')
from np2ncp_curve import build_ncp, OUT_MAX

ROOT = r'C:\Users\admin\WorkBuddy\D300固件'
SRC = os.path.join(ROOT, 'ncp jpg')
DST = os.path.join(ROOT, 'ncp_curve_all')
os.makedirs(DST, exist_ok=True)

BASE_MAP = {  # 预设名 -> NCP 六个底子里最接近的
    'STANDARD': 0x0001, 'NEUTRAL': 0x03C2, 'VIVID': 0x00C3,
    'PORTRAIT': 0x0486, 'RICH_TONE_PORTRAIT': 0x0486,
    'LANDSCAPE': 0x04C7, 'FLAT': 0x03C2, 'FLEXIBLE_COLOR': 0x0001,
    'MONOCHROME': 0x064D, 'FLAT_MONOCHROME': 0x064D, 'DEEPTONE_MONOCHROME': 0x064D,
    'AUTO': 0x0001,
    # 创意：黑白与调色类 -> 单色；其余彩色 -> 标准
    'BINARY': 0x064D, 'BLEACH': 0x0001, 'CARBON': 0x064D, 'CHARCOAL': 0x064D,
    'GRAPHITE': 0x064D, 'DREAM': 0x0001, 'MORNING': 0x0001, 'POP': 0x0001,
    'SUNDAY': 0x0001, 'SOMBER': 0x0001, 'DRAMA': 0x0001, 'SILENCE': 0x0001,
    'MELANCHOLIC': 0x0001, 'PURE': 0x0001, 'DENIM': 0x0001, 'TOY': 0x0001,
    'SEPIA': 0x064D, 'BLUE': 0x064D, 'RED': 0x064D, 'PINK': 0x064D,
}
TONING = {'SEPIA': 1, 'BLUE': 7, 'RED': 3, 'PINK': 9}   # 0x064D 底子的调色枚举


def lum(p):
    a = np.asarray(Image.open(p).convert('RGB'), dtype=np.float64)
    return a, 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]


def pc_info(path):
    b = open(path, 'rb').read(20000)
    i = b.find(b'03100310')
    if i < 0:
        return None, None
    return (b[i + 8:i + 28].rstrip(b'\x00').decode('latin1', 'replace'),
            struct.unpack('<H', b[i + 48:i + 50])[0])


STEPS = json.load(open(os.path.join(ROOT, 'curve_out', 'slider_steps.json')))
STEPS = {s['name']: (s['sat_steps'], s['hue_steps']) for s in STEPS}


def sliders_for(name):
    p = os.path.join(ROOT, 'ncp_approx', name + '_from_np3.NCP')
    if os.path.exists(p):
        sl = list(open(p, 'rb').read()[40:48])
    else:
        sl = [0x83, 0x80, 0x80, 0x80, 0x80, 0xFF, 0xFF, 0xFF]
    sl[1] = sl[2] = 0x01                       # 对比度/亮度交给曲线
    if name in TONING:                         # 调色类：写入调色枚举 + 强度+4
        sl[5] = 0x80
        sl[6] = 0x80 + TONING[name]
        sl[7] = 0x84
    if name in STEPS:                          # 饱和度/色相折算档位（标定过）
        sat, hue = STEPS[name]
        if sat:
            sl[3] = 0x80 + sat
        if hue:
            sl[4] = 0x80 + hue
    return sl


def measure(ai, tgt_lum):
    ai = ai.ravel()
    bi = tgt_lum.ravel()
    sums = np.bincount(ai, weights=bi, minlength=256)
    cnts = np.bincount(ai, minlength=256)
    m = np.where(cnts > 30, sums / np.maximum(cnts, 1), np.nan)
    have = ~np.isnan(m)
    m[~have] = np.interp(np.where(~have)[0], np.where(have)[0], m[have])
    m = np.maximum.accumulate(m)               # 单调化
    m[0] = 0.0
    lut = np.empty(257)
    lut[:256] = m / 255.0 * OUT_MAX
    lut[256] = OUT_MAX
    return [int(round(v)) for v in lut]


def hdr_with_delta(lut):
    d = json.load(open(os.path.join(ROOT, 'curve_out', 'delta_portrait.json')))
    dx = np.array(d['x'], dtype=np.float64)
    dy = np.array(d['delta'], dtype=np.float64)
    lut = np.array(lut, dtype=np.float64)
    xs = np.linspace(0, 255, 20)
    ys = np.clip(np.round(np.interp(xs, np.arange(257) / 256.0 * 255.0,
                                    lut / OUT_MAX * 255.0) + np.interp(xs, dx, dy)), 0, 255)
    h = bytearray(bytes.fromhex('493000FF00FF0100'))
    h += bytes([20])
    for x, y in zip(xs.astype(int), ys.astype(int)):
        h += bytes([int(x), int(y)])
    h += b'\x00' * (64 - len(h))
    return bytes(h)


# ---------- 主流程 ----------
import glob
files = sorted(set(glob.glob(os.path.join(SRC, '*.JPG')) + glob.glob(os.path.join(SRC, '*.jpg'))))
base_img, targets = None, {}
for f in files:
    n, b = pc_info(f)
    if n is None:
        base_img = f
    else:
        targets[f] = n
print('基准: %s   目标: %d 个' % (os.path.basename(base_img), len(targets)))

_, LA = lum(base_img)
ai = np.clip(np.round(LA), 0, 255).astype(np.int32)

done = 0
for f in sorted(targets, key=lambda f: targets[f]):
    name = targets[f]
    _, LT = lum(f)
    lut = measure(ai, LT)
    base = BASE_MAP.get(name, 0x0001)
    sl = sliders_for(name)
    hdr = hdr_with_delta(lut)
    out = build_ncp(name[:20], base, sl, lut, hdr, 0)
    open(os.path.join(DST, name + '_curve.NCP'), 'wb').write(out)
    done += 1
    print('  %-22s 底子 %04X  -> %s_curve.NCP' % (name, base, name))
print('\n完成 %d 个 -> %s' % (done, DST))
