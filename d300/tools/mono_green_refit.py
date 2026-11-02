#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mono_green_refit.py —— 绿滤镜（0x84）打开之后，BINARY 的曲线还值不值得再修一次。

为什么值得再算一遍
------------------
`0x80` 时 BINARY 修不动，理由很硬：分歧像素一边倒偏红（我白他黑 73% 红主导），
一条单调曲线只能整体抬降，挑不出红色，所以怎么拟合都是记图（留出更差）。

绿滤镜把这一条前提改掉了：F0→G，我白他黑里红主导从 73% 掉到 44%，
色偏没了 ⇒ 「曲线只有一维自由度」这个限制不再致命，残差可能重新变成可映射的。
这一步就是验：拿绿档成片当输入 O、官方成片当目标 R，拟合单调映射 f，
再用 2×2 空间分块留出判它到底是规律还是记图。

成与不成都以留出为准（门限 +0.10），别拿拟合值刷自己。

用法：
    python tools/mono_green_refit.py --dry     # 只算，不写文件
    python tools/mono_green_refit.py           # 写 _probe_monofilter_green2/ 的验证包
"""
import argparse
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from compensate import precompensate                     # noqa: E402
from mono_refit import (load, find, gray, metrics, fit_f, render_f,   # noqa: E402
                        cv_score, lut_to_curve, X, SAMP, MIN_GAIN)
from ncp_d300 import OUT_MAX, build_ncp, verify_one      # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
PROBE = os.path.normpath(os.path.join(ROOT, '..', '_probe_monofilter_green'))
OUTDIR = os.path.normpath(os.path.join(ROOT, '..', '_probe_monofilter_green2'))

JOB = dict(slot=19, name='BINARY', src='M19_BINA_G.NCP', jpg='M19_BINA_G.JPG',
           new_name='BINARY G2')


def curve_of(path):
    """读文件里的 257 点 LUT，按 read_lut 同一口径归一到 0–255 再还原有效曲线。

    别直接把 16 位原值喂给 lut_to_curve：那样 T 在 0–65535 域、X 在 0–255 域，
    折叠 f 时会算出「改动 32512 级」这种明显不成立的数。
    """
    b = open(path, 'rb').read()
    lut = np.array(struct.unpack_from('>257H', b, 120), dtype=float) / OUT_MAX * 255.0
    return lut_to_curve(lut), b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()

    j = JOB
    ncp_path = os.path.join(PROBE, j['src'])
    O = load(os.path.join(PROBE, j['jpg']))
    R = load(find(os.path.join(SAMP, 'real_target'), j['slot'], j['name']))
    Tcur, src = curve_of(ncp_path)

    m0 = metrics(O, R)
    f = fit_f(gray(O), gray(R))
    if f is None:
        raise SystemExit('拟合不出单调映射（分档太少）')
    m1 = metrics(render_f(f, O), R)
    cv = cv_score(O, R)
    gain = m0['de_either'] - cv

    print('%s（绿滤镜 0x84）' % j['name'])
    print('  现状（绿档成片 vs 官方）   dE_either %.3f   dE_both %.3f   haze %.2f%%'
          % (m0['de_either'], m0['de_both'], m0['haze']))
    print('  重拟合后（同一张图内拟合） dE_either %.3f   dE_both %.3f   haze %.2f%%'
          % (m1['de_either'], m1['de_both'], m1['haze']))
    print('  2×2 空间分块留出           %.3f  → 收益 %+.2f（门限 +%.2f）'
          % (cv, gain, MIN_GAIN))

    T_new = np.interp(Tcur, X, f)
    print('  曲线改动幅度               %.1f 级（0–255 域）'
          % np.abs(T_new - Tcur).max())

    if gain < MIN_GAIN:
        print('\n结论：留出不通过 ⇒ 绿档已经把能给的给完了，曲线再修是记图。'
              '\n      收尾：BINARY 定为 0x84 原曲线（6.983 → %.3f）。' % m0['de_either'])
        return

    print('\n结论：留出通过，收益 %+.2f 是真的。' % gain)
    if a.dry:
        print('（--dry：没写文件）')
        return

    nm = j['new_name'].encode('ascii')[:20].ljust(20, b'\x00')
    base = struct.unpack_from('>H', src, 36)[0]
    sl = list(src[40:48])                    # 含第 45 字节 0x84，滤镜档跟着走
    tgt = [int(round(y / 255.0 * OUT_MAX)) for y in T_new]
    tgt.append(tgt[-1])
    tgt = [int(t) for t in np.maximum.accumulate(tgt)]
    comp = precompensate(tgt, OUT_MAX)
    new = build_ncp(nm.decode('latin1'), base, sl, comp)

    os.makedirs(OUTDIR, exist_ok=True)
    fn = os.path.join(OUTDIR, 'M19_BINA_G2.NCP')
    open(fn, 'wb').write(new)
    prob = verify_one(fn)
    print('  写入 %s（%d B）%s' % (os.path.basename(fn), len(new),
                                   '  校验通过' if not prob else '  校验报错 %s' % prob))

    # 回读：从文件里的 257 点 LUT 还原有效曲线，用它重新预测，杜绝「写进去的和算的不是一条」
    T_file = lut_to_curve(np.array(struct.unpack_from('>257H', new, 120), dtype=float)
                          / OUT_MAX * 255.0)
    keep = np.r_[True, np.diff(Tcur) > 1e-9]
    x = np.interp(np.clip(gray(O), Tcur[keep].min(), Tcur[keep].max()),
                  Tcur[keep], X[keep])
    P = np.clip(np.interp(x, X, T_file)[..., None] + (O - gray(O)[..., None]), 0, 255)
    print('  回读有效曲线最大偏差 %.1f 级，回读 dE_either %.3f'
          % (np.abs(T_file - T_new).max(), metrics(P, R)['de_either']))
    print('\n下一步：把这个 NCP 打 sidecar 包给用户验一张（tools/pack_sidecar_batch.py）。')


if __name__ == '__main__':
    main()
