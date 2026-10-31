#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""diag_residual.py —— 把 NCP 与 NP3 的残差拆成「亮度 / 彩度 / 色相」三份。

为什么需要它
------------
`audit_release.py` 只给一个数：RGB 三通道平均绝对差。这个数把两件完全不同的事
混在了一起 —— 影调错、颜色错。而 NCP 能给机身的东西只有「一条亮度曲线 + 饱和度
一个整数档 + 色相一个整数档（尼康优化校准都是 ±3）」，所以必须知道残差里
哪一份是曲线能吃的、哪一份是曲线根本碰不到的，否则「还能不能再优化」就只能靠猜。

这里换成 CIELAB 的口径：
  ΔL*  = 亮度差（曲线管的就是这个）
  ΔC*  = 彩度差（饱和度滑块管这个，但只有一个全局倍率）
  ΔH*  = 色相角差（色相滑块管这个，但只有一个全局角度）
  ΔE00 = 综合色差，人眼可辨阈值取 2.3（ΔE00 下 1.0 已属勉强可辨，2.3 是稳妥线）

再按 12 个色相扇区统计 ΔC*/ΔH*，看颜色差是「整体偏一个方向」（一个全局角度能救）
还是「各色相各偏各的」（一个全局角度救不了，这才是真正的天花板所在）。

    python tools/diag_residual.py              # 全 30 支
    python tools/diag_residual.py --top 6      # 顺带印出最差的 6 支的扇区分解
"""
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import optimize_v2 as A                                    # noqa: E402
from compensate import H                                   # noqa: E402
from ncp_d300 import OUT_MAX                               # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
REL = os.path.join(ROOT, 'ncp', 'release', 'NIKON', 'CUSTOMPC')
JND = 2.3                       # ΔE00 可辨阈值
CLIP = 2.0                      # 剪掉的通道量：接近纯黑/纯白的像素不参与统计
CMIN = 8.0                      # 彩度门限：C*<8 的像素色相角无意义，不计入角度统计

# ---------------------------------------------------------------- 色彩空间

_M = np.array([[0.4124564, 0.3575761, 0.1804375],
               [0.2126729, 0.7151522, 0.0721750],
               [0.0193339, 0.1191920, 0.9503041]])
_W = np.array([0.95047, 1.0, 1.08883])


def to_lab(a):
    """sRGB 0..255 -> CIELAB（D65 白点）"""
    c = np.asarray(a, dtype=np.float64) / 255.0
    s = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    t = (s @ _M.T) / _W
    d = 6.0 / 29.0
    f = np.where(t > d ** 3, np.cbrt(t), t / (3 * d * d) + 4.0 / 29.0)
    return np.stack([116.0 * f[..., 1] - 16.0,
                     500.0 * (f[..., 0] - f[..., 1]),
                     200.0 * (f[..., 1] - f[..., 2])], -1)


def de2000(p, q):
    """CIEDE2000 色差，逐像素。p/q 形状 (..., 3)"""
    L1, a1, b1 = p[..., 0], p[..., 1], p[..., 2]
    L2, a2, b2 = q[..., 0], q[..., 1], q[..., 2]
    C1, C2 = np.hypot(a1, b1), np.hypot(a2, b2)
    Cb = (C1 + C2) / 2.0
    G = 0.5 * (1.0 - np.sqrt(Cb ** 7 / (Cb ** 7 + 25.0 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360.0

    dLp = L2 - L1
    dCp = C2p - C1p
    dh = h2p - h1p
    dh = np.where(dh > 180.0, dh - 360.0, np.where(dh < -180.0, dh + 360.0, dh))
    dh = np.where(C1p * C2p < 1e-9, 0.0, dh)
    dHp = 2.0 * np.sqrt(C1p * C2p) * np.sin(np.radians(dh / 2.0))

    Lbp = (L1 + L2) / 2.0
    Cbp = (C1p + C2p) / 2.0
    hsum = h1p + h2p
    hbp = np.where(np.abs(h1p - h2p) > 180.0,
                   np.where(hsum < 360.0, (hsum + 360.0) / 2.0, (hsum - 360.0) / 2.0),
                   hsum / 2.0)
    hbp = np.where(C1p * C2p < 1e-9, hsum, hbp)

    T = (1.0 - 0.17 * np.cos(np.radians(hbp - 30.0))
         + 0.24 * np.cos(np.radians(2.0 * hbp))
         + 0.32 * np.cos(np.radians(3.0 * hbp + 6.0))
         - 0.20 * np.cos(np.radians(4.0 * hbp - 63.0)))
    dth = 30.0 * np.exp(-(((hbp - 275.0) / 25.0) ** 2))
    Rc = 2.0 * np.sqrt(Cbp ** 7 / (Cbp ** 7 + 25.0 ** 7))
    Sl = 1.0 + (0.015 * (Lbp - 50.0) ** 2) / np.sqrt(20.0 + (Lbp - 50.0) ** 2)
    Sc = 1.0 + 0.045 * Cbp
    Sh = 1.0 + 0.015 * Cbp * T
    Rt = -np.sin(np.radians(2.0 * dth)) * Rc
    return np.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2
                   + Rt * (dCp / Sc) * (dHp / Sh))


def hz(p):
    """色相角（度）与彩度"""
    return np.degrees(np.arctan2(p[..., 2], p[..., 1])) % 360.0, np.hypot(p[..., 1], p[..., 2])


# ---------------------------------------------------------------- 预测链

def predict_from_file(slot):
    """完全按文件里存的曲线与滑块重建机身输出（与 audit_release 同一口径）"""
    b = open(os.path.join(REL, 'PICCON%02d.NCP' % slot), 'rb').read()
    lut = np.array(struct.unpack_from('>257H', b, 120), dtype=float) / OUT_MAX * 255.0
    T = np.interp(H(np.arange(256, dtype=float)), np.arange(257, dtype=float), lut)
    sl = list(b[40:48])
    base = struct.unpack_from('>H', b, 36)[0]
    O = A.load('d300ncp', slot)
    ic = A.inv_curve(A.target_curve(slot))
    f = np.interp(ic(np.arange(256, dtype=float)), np.arange(256.0), T)
    if base in (0x0004, 0x064D):
        k = (sl[7] - 0x80) / 4.0 if (sl[7] != 0xFF and slot in A.TONED) else 1.0
        P = A.predict(O, f, 1.0, 0.0, k)
    else:
        n = sl[3] - 0x80 if sl[3] != 0xFF else 0
        m = sl[4] - 0x80 if sl[4] != 0xFF else 0
        P = A.predict(O, f, A.SAT_STEP ** n, A.HUE_STEP * m)
    return P, A.load('workshop', slot), base


def mask_of(O, R):
    """两边都没被剪裁的像素才参与统计：剪裁区的差异是机身截断，不是滤镜造成的"""
    return ((O.min(2) > CLIP) & (O.max(2) < 255 - CLIP)
            & (R.min(2) > CLIP) & (R.max(2) < 255 - CLIP))


def diag(slot):
    P, R, base = predict_from_file(slot)
    m = mask_of(P, R)
    if m.sum() < 5000:
        m = np.ones(P.shape[:2], bool)
    lp, lr = to_lab(P[m]), to_lab(R[m])
    de = de2000(lp, lr)
    hp, cp = hz(lp)
    hr, cr = hz(lr)
    # 色相角在接近中性处没有意义（C* 很小、a*/b* 都在零点附近飘），
    # 直接把低彩度像素的角差设成 nan，后面统一用 nanmean，否则统计出来的
    # 「色相平均偏 13°」全是灰部噪声——实测未加门限时连最准的 STANDARD 都有 13°。
    cm = (cr > CMIN) & (cp > CMIN)
    dh = (hr - hp + 180.0) % 360.0 - 180.0
    dh = np.where(cm, dh, np.nan)
    dhab = 2.0 * np.sqrt(np.maximum(cr, 0) * np.maximum(cp, 0)) * np.sin(np.radians(np.nan_to_num(dh) / 2.0))
    return dict(slot=slot, base=base, n=int(m.sum()),
                de=float(de.mean()), de_med=float(np.median(de)),
                pct=float((de > JND).mean() * 100.0),
                dL=float(np.abs(lr[:, 0] - lp[:, 0]).mean()),
                dL_bias=float((lr[:, 0] - lp[:, 0]).mean()),
                dC=float(np.abs(cr - cp).mean()),
                dC_bias=float((cr - cp).mean()),
                dH=float(np.nanmean(np.abs(dh))) if cm.any() else 0.0,
                dH_cov=float(cm.mean() * 100.0),
                dH_bias=float(np.nanmean(dh)) if cm.any() else 0.0,
                dhab=float(np.abs(dhab[cm]).mean()) if cm.any() else 0.0,
                rgb=float(np.abs(P[m] - R[m]).mean()),
                mask=m, dh=dh, dcp=cr - cp, cp=cp, cr=cr, hp=hp, de_arr=de)


def sectors(d, nb=12):
    """按参考图色相扇区统计彩度\色相偏差，看颜色差是不是集中在某几个色相"""
    out = []
    for i in range(nb):
        lo, hi = i * 360.0 / nb, (i + 1) * 360.0 / nb
        s = (d['hr_'] >= lo) & (d['hr_'] < hi)
        if s.sum() < max(400, d['n'] // 400):
            continue
        dhv = d['dh'][s]
        dhv = dhv[~np.isnan(dhv)]
        out.append((lo, hi, int(s.sum()), float(d['dcp'][s].mean()),
                    float(dhv.mean()) if dhv.size else float('nan'),
                    float(d['de_arr'][s].mean())))
    return out


def main():
    top = 6
    if '--top' in sys.argv:
        top = int(sys.argv[sys.argv.index('--top') + 1])
    print('%-4s %-22s %-6s %6s %6s %6s %6s %6s %6s %7s'
          % ('槽', '滤镜', '底子', 'ΔE00', '可辨%', '|ΔL*|', '偏ΔL*', '|ΔC*|',
             '|ΔH*ab|', '偏ΔH°'))
    print('-' * 96)
    rows = []
    for slot in range(1, 31):
        d = diag(slot)
        d['hr_'], d['cr_'] = hz(to_lab(A.load('workshop', slot)[d['mask']]))
        rows.append(d)
        print('%2d   %-20s 0x%04X %6.2f %5.1f%% %6.2f %+6.2f %6.2f %6.2f %+7.1f'
              % (slot, A.NAMES[slot - 1], d['base'], d['de'], d['pct'],
                 d['dL'], d['dL_bias'], d['dC'], d['dhab'], d['dH_bias']))
    a = np.array([[d['de'], d['pct'], d['dL'], d['dC'], d['dhab'], d['rgb']] for d in rows])
    print('-' * 96)
    print('30 支平均：ΔE00 %.2f ｜ 可辨像素 %.1f%% ｜ |ΔL*| %.2f ｜ |ΔC*| %.2f ｜ |ΔH*ab| %.2f ｜ RGB %.2f'
          % tuple(a.mean(0)))
    mono = [d for d in rows if d['base'] == 0x064D]
    col = [d for d in rows if d['base'] != 0x064D]
    for tag, g in (('单色底子', mono), ('彩色底子', col)):
        b = np.array([[d['de'], d['pct'], d['dL'], d['dC'], d['dhab']] for d in g])
        print('  %s %2d 支：ΔE00 %.2f ｜ 可辨 %.1f%% ｜ |ΔL*| %.2f ｜ |ΔC*| %.2f ｜ |ΔH*ab| %.2f'
              % (tag, len(g), b[:, 0].mean(), b[:, 1].mean(), b[:, 2].mean(),
                 b[:, 3].mean(), b[:, 4].mean()))

    print('')
    print('残差最大的 %d 支，按色相扇区分解（偏ΔC* / 偏ΔH° / ΔE00）' % top)
    worst = sorted(rows, key=lambda d: -d['de'])[:top]
    for d in worst:
        print('  槽%2d %-20s ΔE00 %5.2f  |ΔL*| %5.2f' % (d['slot'], A.NAMES[d['slot'] - 1],
                                                       d['de'], d['dL']))
        for lo, hi, n, dc, dh, de in sectors(d):
            print('      %3.0f–%3.0f°  n=%6d  偏ΔC* %+6.1f  偏ΔH° %+6.1f  ΔE00 %5.2f'
                  % (lo, hi, n, dc, dh, de))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
