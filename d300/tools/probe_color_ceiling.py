# -*- coding: utf-8 -*-
"""probe_color_ceiling.py —— 彩色支「色彩差距」还剩多少可榨？

背景：影调已经打平（|ΔL*| 1.36），残差几乎全在彩度（|ΔC*| 4.09）。
而机身能给的色彩自由度只有两个整数：饱和度档 n（±3，每档 ×1.13）与色相档 m（±3，每档 3.5°）。
也就是能调的只有一个**全局彩度倍率**加一个**全局色相角**。

⚠️单色底子支（含 SEPIA/BLUE/RED/PINK 四支调色）是另一条路：文件里饱和度/色相两个滑块
恒为 FF（不适用），色彩只由 sl[7] 的「调色强度 k」控制，方向写死。两者不能混用。

四个实验
--------
  A  放开成连续域（倍率/角度不再受档位限制），看比现在好多少
     —— 放开后也没收益 ⇒ 不是没调好，是格式天花板
  B  按亮度分 8 段，每段单独求最优倍率
  C  按彩度分 6 段，同上
     —— 各段要的倍率不一样 ⇒ 目标用的是「随亮度/彩度变的彩度曲线」，全局倍率永远追不上
  D  按色相分 8 扇区，每扇区单独最优（倍率+角度）
     —— 量化「如果是逐色相调色能救多少」，也就是我们离天花板的距离

单位一律是 RGB 三通道平均绝对差（0–255 级），与 audit_release 同口径。
"""
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import optimize_v2 as A                                   # noqa: E402
import diag_residual as D                                 # noqa: E402
from compensate import H                                  # noqa: E402
from ncp_d300 import OUT_MAX                              # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
REL = os.path.join(ROOT, 'ncp', 'release', 'NIKON', 'CUSTOMPC')
NPX = 40000


def parts(slot):
    b = open(os.path.join(REL, 'PICCON%02d.NCP' % slot), 'rb').read()
    lut = np.array(struct.unpack_from('>257H', b, 120), dtype=float) / OUT_MAX * 255.0
    T = np.interp(H(np.arange(256, dtype=float)), np.arange(257, dtype=float), lut)
    sl = list(b[40:48])
    base = struct.unpack_from('>H', b, 36)[0]
    O = A.load('d300ncp', slot)
    R = A.load('workshop', slot)
    ic = A.inv_curve(A.target_curve(slot))
    f = np.interp(ic(np.arange(256, dtype=float)), np.arange(256.0), T)
    L = A.lum(O)
    c = O - L[..., None]
    Ln = np.interp(np.clip(L, 0, 255), np.arange(256.0), f)
    n = sl[3] - 0x80 if sl[3] != 0xFF else 0
    m = sl[4] - 0x80 if sl[4] != 0xFF else 0
    mono = base in (0x0004, 0x064D)
    k = (sl[7] - 0x80) / 4.0 if (mono and sl[7] != 0xFF and slot in A.TONED) else 1.0
    return dict(Ln=Ln, c=c, R=R, L=L, base=base, n=n, m=m, O=O,
                kind='mono' if mono else 'color', k=k)


def build(Ln, c, s, m):
    cc = c * s
    if abs(m) > 1e-9:
        cc = A.rot_hue(cc, m * A.HUE_STEP)
    return np.clip(Ln[..., None] + cc, 0, 255)


def build_mono(Ln, c, k):
    return np.clip(Ln[..., None] + c * k, 0, 255)


def err_of(P, R):
    return float(np.abs(P - R).mean())


def sample(p, seed=0):
    rng = np.random.default_rng(seed)
    h, w = p['Ln'].shape
    idx = rng.choice(h * w, min(NPX, h * w), replace=False)
    return dict(Ln=p['Ln'].ravel()[idx], c=p['c'].reshape(-1, 3)[idx],
                R=p['R'].reshape(-1, 3)[idx], L=p['L'].ravel()[idx])


def scan_color(sam):
    """彩色支：连续域网格搜最优 (倍率 s, 色相档 m)"""
    best = (1e9, 1.0, 0.0)
    for mm in np.arange(-6.0, 6.01, 0.25):
        cc = sam['c']
        if abs(mm) > 1e-9:
            cc = A.rot_hue(cc.reshape(-1, 1, 3), mm * A.HUE_STEP).reshape(-1, 3)
        Ln, tgt = sam['Ln'], sam['R']
        for s in np.arange(0.30, 2.41, 0.02):
            e = np.abs(np.clip(Ln[:, None] + cc * s, 0, 255) - tgt).mean()
            if e < best[0]:
                best = (float(e), float(s), float(mm))
    return best


def scan_mono(sam):
    """单色支：只有一个自由度 k（调色强度）"""
    best = (1e9, 1.0)
    for k in np.arange(-1.0, 3.01, 0.05):
        e = np.abs(np.clip(sam['Ln'][:, None] + sam['c'] * k, 0, 255) - sam['R']).mean()
        if e < best[0]:
            best = (float(e), float(k))
    return best


def segments(p, pkind, key, nb):
    """实验 B/C：按 key（亮度 L 或彩度 C*）分 nb 段，每段单独求最优倍率"""
    Ln, c, R, L = p['Ln'], p['c'], p['R'], p['L']
    lab = D.to_lab(p['O'])
    C = np.hypot(lab[..., 1], lab[..., 2])
    k = L if key == 'L' else C
    edges = np.quantile(k.ravel(), np.linspace(0, 1, nb + 1))
    out = []
    for i in range(nb):
        lo, hi = edges[i], edges[i + 1]
        msk = (k >= lo) & (k < hi if i < nb - 1 else k <= hi)
        # 彩度太低的像素，倍率怎么调都无所谓（噪声），不计入
        msk &= (C > 6.0)
        if msk.sum() < 2000:
            continue
        cc, tgt, lnn = c[msk], R[msk], Ln[msk]
        best = (1e9, 1.0)
        for s in np.arange(0.30, 2.41, 0.02):
            e = np.abs(np.clip(lnn[:, None] + cc * s, 0, 255) - tgt).mean()
            if e < best[0]:
                best = (float(e), float(s))
        out.append((float(k[msk].mean()), best[1], best[0], int(msk.sum())))
    return out


def sectors(p, nb=8):
    """实验 D：按目标色相分扇区，每扇区单独最优（倍率+任意角度）"""
    Ln, c, R = p['Ln'], p['c'], p['R']
    hr, cr = D.hz(D.to_lab(R))
    tot, wsum = 0.0, 0
    rows = []
    for i in range(nb):
        lo, hi = i * 360.0 / nb, (i + 1) * 360.0 / nb
        msk = (hr >= lo) & (hr < hi) & (cr > 6.0)
        if msk.sum() < 1500:
            continue
        cc, tgt, lnn = c[msk], R[msk], Ln[msk]
        best = (1e9, 1.0, 0.0)
        for deg in np.arange(-40.0, 40.1, 5.0):
            cd = A.rot_hue(cc.reshape(-1, 1, 3), deg).reshape(-1, 3) if abs(deg) > 1e-9 else cc
            for s in np.arange(0.30, 2.01, 0.05):
                e = np.abs(np.clip(lnn[:, None] + cd * s, 0, 255) - tgt).mean()
                if e < best[0]:
                    best = (float(e), float(s), float(deg))
        tot += best[0] * int(msk.sum())
        wsum += int(msk.sum())
        rows.append((lo, best[1], best[2], best[0], int(msk.sum())))
    return (tot / wsum if wsum else float('nan')), rows


def highfreq(a, r=2.0):
    """高频（细节）能量：原图与高斯模糊之差的平均绝对值"""
    from PIL import Image, ImageFilter
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    b = np.asarray(im.filter(ImageFilter.GaussianBlur(r)), dtype=np.float64)
    return float(np.abs(a - b).mean())


def run(slot, full=False):
    p = parts(slot)
    sam = sample(p)
    d = D.diag(slot)
    if p['kind'] == 'color':
        cur = build(p['Ln'], p['c'], A.SAT_STEP ** p['n'], p['m'])
        e_cur = err_of(cur, p['R'])
        _, s_b, m_b = scan_color(sam)
        P_b = build(p['Ln'], p['c'], s_b, m_b)
        now = '饱和 %+d 档（×%.3f）/ 色相 %+d 档' % (p['n'], A.SAT_STEP ** p['n'], p['m'])
        opt = '倍率 ×%.3f（=%.2f 档）/ 色相 %+.2f 档' % (
            s_b, np.log(max(s_b, 1e-3)) / np.log(A.SAT_STEP), m_b)
    else:
        cur = build_mono(p['Ln'], p['c'], p['k'])
        e_cur = err_of(cur, p['R'])
        _, k_b = scan_mono(sam)
        P_b = build_mono(p['Ln'], p['c'], k_b)
        now = '调色强度 k=%.2f' % p['k']
        opt = '调色强度 k=%.2f' % k_b

    e_best = err_of(P_b, p['R'])
    lp, lr = D.to_lab(P_b), D.to_lab(p['R'])
    de_b = float(D.de2000(lp, lr).mean())
    cp = np.hypot(lp[..., 1], lp[..., 2])
    cr = np.hypot(lr[..., 1], lr[..., 2])
    dc_b = float(np.abs(cr - cp).mean())

    print('\n槽 %2d %s %s   底子 0x%04X（%s）' % (
        slot, A.NAMES[slot - 1], A.CN[slot - 1], p['base'],
        '单色·调色' if p['kind'] == 'mono' else '彩色'))
    print('  现在  ：%s  →  %.2f 级 ｜ ΔE00 %.2f ｜ |ΔC*| %.2f' % (now, e_cur, d['de'], d['dC']))
    print('  放开后：%s  →  %.2f 级 ｜ ΔE00 %.2f ｜ |ΔC*| %.2f' % (opt, e_best, de_b, dc_b))
    print('  连续域收益：%.2f 级（%.1f%%）%s' % (
        e_cur - e_best, (1 - e_best / max(e_cur, 1e-9)) * 100,
        '' if e_cur - e_best > 0.05 else '  ← 几乎为零，已经在最优档位上'))
    # 实验 E：原版是不是做了「点运算做不了的空间效果」（柔光/雾化/局部对比度压缩）
    hp, hr = highfreq(cur), highfreq(p['R'])
    ratio = hr / max(hp, 1e-9)
    print('  细节量：原版 %.2f / 我们的 %.2f = %.2f×%s' % (
        hr, hp, ratio,
        '  ← 原版明显更柔，这是邻域运算，一条逐像素的 LUT 做不出来'
        if ratio < 0.88 else ('  ← 原版更锐' if ratio > 1.12 else '  ← 两边细节量相当')))
    if p['kind'] == 'mono':
        return dict(slot=slot, en=A.NAMES[slot - 1], cn=A.CN[slot - 1], kind='mono',
                    e_cur=e_cur, e_best=e_best, de_cur=d['de'], de_best=de_b)
    if not full:
        return dict(slot=slot, en=A.NAMES[slot - 1], cn=A.CN[slot - 1], kind='color',
                    e_cur=e_cur, e_best=e_best, de_cur=d['de'], de_best=de_b)
    for key, lab, nbin in (('L', '亮度', 8), ('C', '彩度', 6)):
        seg = segments(p, p['kind'], key, nbin)
        ss = [x[1] for x in seg]
        spread = max(ss) / max(min(ss), 1e-6)
        print('  按%s分 %d 段最优倍率：%s' % (lab, len(seg), ' '.join('%.2f' % s for s in ss)))
        print('     各段各调各的 → %.2f 级（极差 %.2f×）%s' % (
            sum(x[2] * x[3] for x in seg) / sum(x[3] for x in seg), spread,
            '：目标要的是随%s变的彩度曲线，全局倍率是硬天花板' % lab if spread > 1.4
            else '：基本是常数，全局倍率够用'))
    tot, rows = sectors(p)
    print('  按色相分 8 扇区，各扇区各调各的 → %.2f 级（比全局最优再降 %.2f 级）' % (
        tot, e_best - tot))
    print('     每扇区最优（倍率/角度）：%s' % ' '.join('%.0f°:%.2f/%+.0f°' % (r[0], r[1], r[2]) for r in rows))
    return dict(slot=slot, en=A.NAMES[slot - 1], cn=A.CN[slot - 1], kind='color',
                e_cur=e_cur, e_best=e_best, de_cur=d['de'], de_best=de_b, sector=tot)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    full = '--full' in sys.argv
    if args:
        for a in args:
            run(int(a), full=True)
    else:
        rows = []
        for slot in range(1, 31):
            rows.append(run(slot, full=full))
        print('\n' + '=' * 84)
        print('%-22s %5s %7s %7s %7s %8s' % ('滤镜', '类型', '现在', '放开后', '收益', 'ΔE00→'))
        tc = tb = 0.0
        for r in sorted(rows, key=lambda x: -(x['e_cur'] - x['e_best'])):
            print('%-22s %5s %7.2f %7.2f %+7.2f   %.2f → %.2f'
                  % (r['en'] + ' ' + r['cn'], r['kind'], r['e_cur'], r['e_best'],
                     r['e_best'] - r['e_cur'], r['de_cur'], r['de_best']))
            tc += r['e_cur']; tb += r['e_best']
        n = len(rows)
        print('-' * 84)
        print('30 支平均 %.2f → %.2f 级（放开连续域还能再降 %.1f%%）'
              % (tc / n, tb / n, (1 - tb / tc) * 100))
