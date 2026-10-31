# -*- coding: utf-8 -*-
"""真渲染成片的体检：把「实测」和「模型外推」放在一张表里对。

背景：v3 的 5.98 级是**按文件里的曲线与滑块外推**出来的预测值，没有真渲染。
现在拿 NX Studio 真渲的成片回来，可以同时回答两件事：
  1. v3 导出后到底差多少（真实值，不再靠外推）
  2. 模型外推本身准不准（预测成片 vs 真实成片的差）

用法：
    python real_render_check.py                    # 默认读 samples/real_v3/
    python real_render_check.py --dir real_v3_b    # 另一批（换 RAW 的那批）
    python real_render_check.py --target workshop  # 目标侧目录，默认 workshop
"""
import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import diag_residual as D                                  # noqa: E402
import optimize_v2 as A                                    # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
SAMP = os.path.join(ROOT, 'samples')


def load_dir(d, slot):
    p = os.path.join(SAMP, d, '%02d_%s.jpg' % (slot, A.NAMES[slot - 1]))
    if not os.path.exists(p):
        return None
    return A.load(d, slot)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default='real_v3', help='真渲染成片所在目录（samples/ 下）')
    ap.add_argument('--target', default='workshop', help='目标侧目录（samples/ 下）')
    ap.add_argument('--base', default='d300ncp', help='第一版真渲染成片目录（对照用）')
    a = ap.parse_args()

    src = os.path.join(SAMP, a.dir)
    if not os.path.isdir(src):
        raise SystemExit('找不到目录：%s（先建好并把 30 张图放进去）' % src)
    miss = [s for s in range(1, 31) if load_dir(a.dir, s) is None]
    if miss:
        raise SystemExit('缺 %d 张：%s' % (len(miss), miss))

    rows = []
    for slot in range(1, 31):
        Real = load_dir(a.dir, slot)
        R = load_dir(a.target, slot)
        O = load_dir(a.base, slot)
        P, _, base = D.predict_from_file(slot)          # 模型外推的成片
        mono = base in (0x0004, 0x064D)

        e_real = float(np.abs(Real - R).mean())         # 真渲染 vs 目标（全图口径）
        e_pred = float(np.abs(P - R).mean())            # 模型外推 vs 目标
        model = float(np.abs(P - Real).mean())          # 模型自己差多少
        m = D.mask_of(Real, R)
        lr, lt = D.to_lab(Real)[m], D.to_lab(R)[m]
        de = float(D.de2000(lr, lt).mean())
        dL = float(np.abs(lr[..., 0] - lt[..., 0]).mean())
        dC = float(np.abs(np.hypot(lr[..., 1], lr[..., 2])
                          - np.hypot(lt[..., 1], lt[..., 2])).mean())
        rows.append(dict(slot=slot, en=A.NAMES[slot - 1], cn=A.CN[slot - 1],
                         mono=mono, real=e_real, pred=e_pred, model=model,
                         de=de, dL=dL, dC=dC, v1=float(np.abs(O - R).mean()) if O is not None else float('nan')))

    er = np.array([r['real'] for r in rows])
    ep = np.array([r['pred'] for r in rows])
    em = np.array([r['model'] for r in rows])
    ev = np.array([r['v1'] for r in rows])
    mo = np.array([r['mono'] for r in rows])

    print('\n槽  滤镜                   v1实测  v3预测  v3真渲  模型误差  ΔE00  |ΔL*|  |ΔC*|')
    print('-' * 84)
    for r in rows:
        print('%2d  %-18s %6.2f  %6.2f  %6.2f  %7.2f  %5.2f  %5.2f  %5.2f'
              % (r['slot'], r['en'] + ' ' + r['cn'], r['v1'], r['pred'], r['real'],
                 r['model'], r['de'], r['dL'], r['dC']))
    print('-' * 84)
    print('平均：v1 %.2f ｜ v3 预测 %.2f ｜ v3 真渲 %.2f ｜ 模型误差 %.2f'
          % (ev.mean(), ep.mean(), er.mean(), em.mean()))
    print('单色 %d 支真渲 %.2f ｜ 彩色 %d 支真渲 %.2f'
          % (mo.sum(), er[mo].mean(), (~mo).sum(), er[~mo].mean()))
    print('ΔE00 平均 %.2f ｜ |ΔL*| %.2f ｜ |ΔC*| %.2f'
          % (np.mean([r['de'] for r in rows]), np.mean([r['dL'] for r in rows]),
             np.mean([r['dC'] for r in rows])))
    good = int((er < ev - 0.05).sum())
    print('相对第一版：真渲口径降 %.1f%%（%.2f → %.2f），变好 %d / 30'
          % ((1 - er.mean() / ev.mean()) * 100, ev.mean(), er.mean(), good))
    print()
    print('⚠️ 模型误差 %.2f 级 = 外推值 %.2f 与真渲 %.2f 的系统偏差；'
          % (em.mean(), ep.mean(), er.mean()))
    print('   这个数越小，说明「不重渲染也能估准」这件事越成立。')
    print('   真渲 %.2f 与预测 %.2f 差 %.2f 级%s'
          % (er.mean(), ep.mean(), er.mean() - ep.mean(),
             '（真渲更好）' if er.mean() < ep.mean() else '（真渲更差）'))

    import csv
    out = os.path.join(SAMP, 'real_%s.csv' % a.dir)
    with open(out, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['slot', 'en', 'cn', 'mono', 'v1', 'pred',
                                          'real', 'model', 'de00', 'dL', 'dC'])
        w.writeheader()
        for r in rows:
            w.writerow(dict(slot=r['slot'], en=r['en'], cn=r['cn'], mono=r['mono'],
                            v1=r['v1'], pred=r['pred'], real=r['real'], model=r['model'],
                            de00=r['de'], dL=r['dL'], dC=r['dC']))
    print('\n已存：%s' % out)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
