#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_release.py —— 对 `ncp/release/` 里的 30 个文件做一次"不拟合"的独立体检。

和 optimize_v2.py 的区别：这里不搜索、不拟合，只把文件当成黑盒，
按文件里真实存的 LUT 重建机身会走的那条曲线，再拿去和 30 对样片比对。
所以它能抓住"优化脚本自说自话"的错误（偏移写错、补偿套错、滑块没落盘）。

历史版本（`ncp/release_v1/`、`ncp/release_v2/` …）会被自动发现并逐支并排对比。

    python tools/audit_release.py            # 体检 ncp/release/ 并与历史版本对比
    python tools/audit_release.py --only     # 只体检当前版本，不看历史
"""
import glob
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import optimize_v2 as A                                    # noqa: E402
from compensate import H                                   # noqa: E402
from ncp_d300 import OUT_MAX, verify_one                   # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))


def version_dirs():
    """自动发现 ncp/release_v* 历史版本，按版本号排序"""
    out = []
    for p in sorted(glob.glob(os.path.join(ROOT, 'ncp', 'release_v*'))):
        d = os.path.join(p, 'NIKON', 'CUSTOMPC')
        if os.path.isdir(d):
            out.append((os.path.basename(p).replace('release_', ''), d))
    return out


def read_curve(fn):
    b = open(fn, 'rb').read()
    lut = np.array(struct.unpack_from('>257H', b, 120), dtype=float) / OUT_MAX * 255.0
    return np.interp(H(np.arange(256, dtype=float)), np.arange(257, dtype=float), lut), b


def err(fn, slot):
    """按文件里真实存的曲线 + 真实存的滑块，重算与参考图的平均绝对误差"""
    T, b = read_curve(fn)
    sl = list(b[40:48])
    base = struct.unpack_from('>H', b, 36)[0]
    O, R = A.load('d300ncp', slot), A.load('workshop', slot)

    # 曲线定义在「机身直出亮度」上：新亮度 = T(T_old⁻¹(机身亮度))。
    # 这一步必须用第一版曲线反解，用 T 自己的反函数只会得到恒等映射（会低估改动）。
    Told = A.target_curve(slot)                     # 从 ncp/release_v1/ 读
    ic = A.inv_curve(Told)
    f = np.interp(ic(np.arange(256, dtype=float)), np.arange(256.0), T)
    if base in (0x0004, 0x064D):        # 单色底子：0x064D 是实拍验过的那个
        k = (sl[7] - 0x80) / 4.0 if (sl[7] != 0xFF and slot in A.TONED) else 1.0
        P = A.predict(O, f, 1.0, 0.0, k)
    else:
        n = sl[3] - 0x80 if sl[3] != 0xFF else 0
        m = sl[4] - 0x80 if sl[4] != 0xFF else 0
        P = A.predict(O, f, A.SAT_STEP ** n, A.HUE_STEP * m)
    return float(np.abs(P - R).mean()), b, T


def main():
    only = '--only' in sys.argv
    vdirs = [] if only else version_dirs()
    heads = ' '.join('%6s' % n.replace('_', '') for n, _ in vdirs)
    cur = 'v%d' % (len(vdirs) + 1)
    print('%-14s %-24s %4s %5s %-23s %s %6s  %s'
          % ('文件', '滤镜', '字节', '底子', '八滑块', heads, cur, '体检'))
    print('-' * (104 + 7 * len(vdirs)))
    rows = []
    bad = 0
    for fn in sorted(glob.glob(os.path.join(ROOT, 'ncp', 'release', 'NIKON', 'CUSTOMPC', '*.NCP'))):
        slot = int(os.path.basename(fn)[6:8])
        e3, b, T = err(fn, slot)
        base = struct.unpack_from('>H', b, 36)[0]
        sl = ' '.join('%02X' % v for v in b[40:48])
        prob = verify_one(fn)
        hist = []
        for _, d in vdirs:
            f2 = os.path.join(d, os.path.basename(fn))
            hist.append(err(f2, slot)[0] if os.path.exists(f2) else float('nan'))
        if prob:
            bad += 1
        rows.append((slot, hist, e3, base, sl))
        print('%-14s %-24s %4d 0x%04X %-23s %s %6.2f  %s'
              % (os.path.basename(fn), A.NAMES[slot - 1] + ' ' + A.CN[slot - 1],
                 len(b), base, sl,
                 ' '.join('%6.2f' % v for v in hist) if hist else '', e3,
                 'OK' if not prob else '；'.join(prob)))
    print('-' * (104 + 7 * len(vdirs)))
    n = len(rows)
    e3 = np.array([r[2] for r in rows])
    if vdirs:
        for i, (name, _) in enumerate(vdirs):
            e = np.array([r[1][i] for r in rows])
            ok = ~np.isnan(e)
            print('30 支平均：%s %.2f → %s %.2f（降 %.1f%%）；其中变好 %d / 不变 %d / 变差 %d'
                  % (name, np.nanmean(e), cur, e3.mean(),
                     (1 - e3.mean() / np.nanmean(e)) * 100,
                     int((e3[ok] < e[ok] - 0.05).sum()),
                     int((np.abs(e3[ok] - e[ok]) <= 0.05).sum()),
                     int((e3[ok] > e[ok] + 0.05).sum())))
    else:
        print('30 支平均 %.2f' % e3.mean())
    print('结构自检：%d 个不通过' % bad)

    # 这张表就是 README 里引用的数据源：全部从文件本身重算，不是优化脚本的自报数
    out = os.path.join(ROOT, 'samples', 'metrics.csv')
    vn = [n for n, _ in vdirs]
    with open(out, 'w', encoding='utf-8-sig', newline='') as f:
        f.write('slot,en,cn,base,sliders,%s,e_%s,delta\n'
                % (','.join('e_%s' % v for v in vn), cur))
        for slot, hist, e3, base, sl in rows:
            f.write('%d,%s,%s,0x%04X,%s,%s,%.2f,%+.2f\n'
                    % (slot, A.NAMES[slot - 1], A.CN[slot - 1], base, sl,
                       ','.join('%.2f' % v for v in hist), e3,
                       e3 - np.nanmean(hist) if hist else 0.0))
    print('数据表：%s' % out)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(main())
