# -*- coding: utf-8 -*-
"""probe_int_grid.py —— 机身真正能写进去的只有整数档（饱和 ±3、色相 ±3），
那就把 7×7 = 49 种组合全部试一遍，看现在的档位是不是已经是最好的。

为什么还要单独做一遍：v2/v3 的档位是从「实测彩度比 / 色相偏」反算再取整的，
不是在这 49 个格子里穷举出来的。两者不一定重合 —— 比如色相需要 +4.75 档时，
取整会落到别处，而真正最优的整数可能差着一两档。

⚠️防过拟合：只挑「留出也变好」的。用 2×4 = 8 折：每次用 7 块挑最优档，
在剩下那 1 块上算误差，八折平均。基线（当前档位）不参与挑选，直接算同样的八块平均。
留出误差下降才算真收益，否则只是把噪声当成了改进。
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
NS = range(-3, 4)
MS = range(-3, 4)


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
    return dict(Ln=Ln, c=c, R=R, base=base, n=n, m=m)


def blocks(shape, nx=4, ny=2):
    """2×4 = 8 折：返回 8 个布尔掩膜"""
    h, w = shape
    out = []
    for iy in range(ny):
        for ix in range(nx):
            m = np.zeros((h, w), bool)
            m[iy * h // ny:(iy + 1) * h // ny, ix * w // nx:(ix + 1) * w // nx] = True
            out.append(m)
    return out


def run(slot):
    p = parts(slot)
    if p['base'] in (0x0004, 0x064D):
        return None
    Ln, c, R = p['Ln'], p['c'], p['R']
    grid = {}
    for m in MS:
        cc = A.rot_hue(c, m * A.HUE_STEP) if m else c
        for n in NS:
            P = np.clip(Ln[..., None] + cc * (A.SAT_STEP ** n), 0, 255)
            grid[(n, m)] = np.abs(P - R).mean(2)      # 每像素三通道平均，留着按块取
    bl = blocks(Ln.shape)
    H_, W_ = Ln.shape

    def blk_err(a, m):
        return np.concatenate([a[m].ravel() for m in [m]]).mean()

    full = {k: float(v.mean()) for k, v in grid.items()}
    cur = (p['n'], p['m'])
    # 八折留出：每折用「除这一块以外」的平均误差挑最优档，再在这一块上评分
    hold = 0.0
    picks = []
    area = np.ones((H_, W_))
    for i, bm in enumerate(bl):
        outside = ~bm
        best = min(grid, key=lambda k: grid[k][outside].mean())
        hold += grid[best][bm].mean()
        picks.append(best)
    hold /= len(bl)
    hold_cur = float(np.mean([grid[cur][bm].mean() for bm in bl]))
    best_full = min(full, key=full.get)
    return dict(slot=slot, en=A.NAMES[slot - 1], cn=A.CN[slot - 1], cur=cur,
                e_cur=full[cur], best=best_full, e_best=full[best_full],
                hold_cur=hold_cur, hold=hold, picks=picks)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    rows = []
    for slot in range(1, 31):
        r = run(slot)
        if r:
            rows.append(r)
    print('%-22s %10s %10s %8s %8s %8s' % ('滤镜', '现在档位', '穷举最优', '全图', '八折留出', '判定'))
    print('-' * 84)
    tot_c = tot_h = tot_hc = 0.0
    gain = []
    for r in rows:
        d_full = r['e_best'] - r['e_cur']
        d_hold = r['hold'] - r['hold_cur']
        ok = (r['best'] != r['cur']) and d_full < -0.05 and d_hold < -0.02
        if ok:
            gain.append(r)
        tot_c += r['e_cur']
        tot_h += r['hold']
        tot_hc += r['hold_cur']
        print('%-22s %4s→%-5s %.2f→%.2f  %+7.2f  %+7.2f  %s'
              % (r['en'] + ' ' + r['cn'],
                 '%+d/%+d' % r['cur'], '%+d/%+d' % r['best'],
                 r['e_cur'], r['e_best'], d_full, d_hold,
                 '✓ 可改' if ok else ('— 已在最优' if r['best'] == r['cur'] else '— 留出不支持')))
    n = len(rows)
    print('-' * 84)
    print('彩色 19 支：全图 %.2f → %.2f 级；八折留出 %.2f → %.2f 级'
          % (tot_c / n, sum(r['e_best'] for r in rows) / n, tot_hc / n, tot_h / n))
    print('\n真正值得改的 %d 支：' % len(gain))
    for r in gain:
        print('  %-20s 档位 %+d/%+d → %+d/%+d   全图 %.2f→%.2f（%+.2f） 留出 %+.2f'
              % (r['en'] + ' ' + r['cn'], r['cur'][0], r['cur'][1],
                 r['best'][0], r['best'][1], r['e_cur'], r['e_best'],
                 r['e_best'] - r['e_cur'], r['hold'] - r['hold_cur']))
