# -*- coding: utf-8 -*-
"""修复被头部错位破坏的 DREAM / SILENCE_sat-2：
   LUT 值仍取自坏文件（LUT 值本身是对的），头部用 hdr_with_delta() 重新生成
   （与批量流程完全一致），滑块按修正后的档位。"""
import os, sys, json, struct
import numpy as np
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r'C:\Users\admin\WorkBuddy\D300固件\.workbuddy\tmp')
from np2ncp_curve import build_ncp, OUT_MAX

ROOT = r'C:\Users\admin\WorkBuddy\D300固件'
D = os.path.join(ROOT, 'ncp_curve_all')
d = json.load(open(os.path.join(ROOT, 'curve_out', 'delta_portrait.json')))
dx = np.array(d['x'], dtype=np.float64)
dy = np.array(d['delta'], dtype=np.float64)


def hdr_with_delta(lut):
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


def fix(src_name, out_name, sliders, toning_note=''):
    b = open(os.path.join(D, src_name), 'rb').read()
    lut = list(struct.unpack('>257H', b[120:120 + 514]))   # LUT 值（坏文件的 LUT 值本身是对的）
    hdr = hdr_with_delta(lut)
    name = out_name.split('_curve')[0]
    out = build_ncp(name[:20], 0x0001, sliders, lut, hdr, 0)
    open(os.path.join(D, out_name), 'wb').write(out)
    # 自检：结构 + 控制点与 LUT 的一致性（控制点应等于 LUT 采样 + δ）
    b2 = open(os.path.join(D, out_name), 'rb').read()
    n = b2[64]
    pts = [(b2[65 + 2 * i], b2[66 + 2 * i]) for i in range(n)]
    check = all(abs(y - np.interp(x, np.arange(257) / 256.0 * 255.0,
                                  np.array(lut) / OUT_MAX * 255.0) - np.interp(x, dx, dy)) < 1.6
                for x, y in pts)
    print('%s: %d 字节, %d 点, 控制点与 LUT+δ 一致: %s' % (out_name, len(b2), n, check))
    return check


ok1 = fix('DREAM_curve.NCP', 'DREAM_curve.NCP',
          [0x83, 0x01, 0x01, 0x80, 0x82, 0xFF, 0xFF, 0xFF])
ok2 = fix('SILENCE_curve.NCP', 'SILENCE_curve_sat-2.NCP',
          [0x83, 0x01, 0x01, 0x7E, 0x80, 0xFF, 0xFF, 0xFF])
print('两个都修复' if ok1 and ok2 else '仍有问题')
