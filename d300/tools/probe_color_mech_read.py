#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_color_mech_read.py —— 读「色彩机制」卡包的 8 张实拍，直接给结论。

    python tools/probe_color_mech_read.py --dir <成片目录>

目录里放 8 张，文件名带 `01`…`08` 或带探针名（`C_CTRL`、`M_SAT_P3`…）都能认。
指标统一在 CIELAB（D65）上算，遮罩取「不过曝不死黑」的像素，**8 张共用同一批像素**
（以 01 C_CTRL 的遮罩为准），否则一改彩度就换了像素集，均值不可比（坑见 docs/14 第六节）。

输出四行判定：

    色罩   彩色底子 + 调色字节，会不会真的上一层色罩？
    单色   彩色底子 + 单色滤镜字节，会不会变成单色？
    加彩度 单色底子 + 饱和度，能不能改变着色浓度？
    浓度   调色浓度那个字节，一格到底值多少？
"""
import argparse
import glob
import os
import sys

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

NAMES = ['C_CTRL', 'C_TONE_Y', 'C_TONE_B', 'C_FILT_Y',
         'M_CTRL', 'M_SAT_P3', 'M_SAT_M3', 'M_DENS84']
CN = {
    'C_CTRL': '彩色基准（发布包写法）',
    'C_TONE_Y': '彩色底 + 黄色调色',
    'C_TONE_B': '彩色底 + 蓝色调色',
    'C_FILT_Y': '彩色底 + 单色滤镜字节',
    'M_CTRL': '单色着色基准（浓度 82）',
    'M_SAT_P3': '单色底 + 饱和度 +3',
    'M_SAT_M3': '单色底 + 饱和度 −3',
    'M_DENS84': '单色底 + 浓度 84',
}


def to_lab(rgb):
    c = rgb / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]], dtype=np.float32)
    t = (c @ m.T) / np.array([0.95047, 1.0, 1.08883], dtype=np.float32)
    d = 6.0 / 29.0
    f = np.where(t > d ** 3, np.cbrt(t), t / (3 * d * d) + 4.0 / 29.0)
    return 116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])


def load(path):
    im = Image.open(path)
    im.draft('RGB', (1600, 1600))
    return np.asarray(im.convert('RGB'), dtype=np.float32)


def find(d, key, idx):
    fs = [f for f in glob.glob(os.path.join(d, '*')) if os.path.splitext(f)[1].lower() in ('.jpg', '.jpeg', '.png')]
    stem_key = key.lower()
    for f in fs:
        b = os.path.basename(f).lower()
        if stem_key in b:
            return f
    for f in fs:
        if os.path.basename(f).startswith('%02d' % idx):
            return f
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    a = ap.parse_args()

    paths = [find(a.dir, n, i + 1) for i, n in enumerate(NAMES)]
    missing = [NAMES[i] for i, p in enumerate(paths) if p is None]
    if missing:
        print('缺 %d 张：%s' % (len(missing), ', '.join(missing)))
        if len(missing) == len(NAMES):
            return 1

    rgb, lab = {}, {}
    for n, p in zip(NAMES, paths):
        if p is None:
            continue
        rgb[n] = load(p)
        lab[n] = to_lab(rgb[n])

    ref = 'C_CTRL' if 'C_CTRL' in rgb else NAMES[0]
    shape = rgb[ref].shape[:2]
    mask = np.ones(shape, bool)
    for n in rgb:
        if rgb[n].shape[:2] != shape:
            print('⚠️ %s 尺寸不一致（%s vs %s），请用同一批导出'
                  % (n, rgb[n].shape[:2], shape))
            return 1
        mask &= (rgb[n].min(2) > 8) & (rgb[n].max(2) < 247)

    print('共用像素 %d 个\n' % mask.sum())
    print('%-10s %-22s %8s %8s %8s %8s' % ('探针', '说明', 'L*', 'C*', 'a*', 'R−B'))
    print('-' * 74)
    stat = {}
    for n in NAMES:
        if n not in rgb:
            continue
        L, A, B = lab[n]
        C = np.hypot(A, B)
        m = mask.ravel()
        r = rgb[n].reshape(-1, 3)[m].mean(0)
        stat[n] = dict(L=float(L[mask].mean()), C=float(C[mask].mean()),
                       a=float(A[mask].mean()), b=float(B[mask].mean()),
                       rb=float(r[0] - r[2]))
        print('%-10s %-22s %8.1f %8.2f %8.2f %8.1f'
              % (n, CN[n], stat[n]['L'], stat[n]['C'], stat[n]['a'], stat[n]['rb']))

    print('\n' + '=' * 74)
    ok = []

    def get(k):
        return stat.get(k)

    # 中性像素子集：控制图里 |a*|、|b*| 都很小的那批。着色一旦生效，这批像素**最先、最明显**变色，
    # 比全图均值灵敏得多（全图均值被大量彩色像素稀释）。
    neutral, nbase = None, None
    if 'C_CTRL' in lab:
        L0, A0, B0 = lab['C_CTRL']
        neutral = mask & (np.abs(A0) < 10) & (np.abs(B0) < 10)
        if neutral.sum() > 2000:
            nbase = (float(A0[neutral].mean()), float(B0[neutral].mean()))
            print('中性像素 %d 个（控制图 |a*|,|b*| < 10）—— 着色生效时这批最先变\n' % neutral.sum())
            print('%-10s %8s %8s %10s' % ('探针', 'a*', 'b*', 'Δ(相对00)'))
            for n in NAMES:
                if n in lab:
                    A, B = lab[n][1], lab[n][2]
                    a, b = float(A[neutral].mean()), float(B[neutral].mean())
                    print('%-10s %8.2f %8.2f %10.2f'
                          % (n, a, b, np.hypot(a - nbase[0], b - nbase[1])))
            print()

    c0, cy, cb = get('C_CTRL'), get('C_TONE_Y'), get('C_TONE_B')
    if c0 and cy and cb:
        dy, db = cy['rb'] - c0['rb'], cb['rb'] - c0['rb']
        print('【色罩】彩色底 + 调色字节：全图 R−B 位移  黄 %+.1f / 蓝 %+.1f 级' % (dy, db))
        nshift = 0.0
        if nbase is not None:
            shifts = []
            for n in ('C_TONE_Y', 'C_TONE_B'):
                A, B = lab[n][1], lab[n][2]
                shifts.append(np.hypot(float(A[neutral].mean()) - nbase[0],
                                       float(B[neutral].mean()) - nbase[1]))
            nshift = float(max(shifts))
            print('        中性像素上的位移：黄 %.2f / 蓝 %.2f（Δab，>2 就很明显）'
                  % (shifts[0], shifts[1]))
        hit = max(abs(dy), abs(db), nshift * 2)     # 中性像素位移按 2 倍权重参与判定
        if hit > 3.0:
            print('   ✅ 生效。彩色支可以做色罩了 —— 这是唯一能打破 r=0.80 的机制，值得重做 30 支。')
            ok.append('色罩')
        else:
            print('   ❌ 不生效。彩色底子确实只有饱和/色相两个旋钮，色罩这条路正式封死。')
    cf = get('C_FILT_Y')
    if c0 and cf:
        ratio = cf['C'] / max(c0['C'], 1e-6)
        print('【单色】彩色底 + 滤镜字节：C* %.2f → %.2f（%.2f×）' % (c0['C'], cf['C'], ratio))
        if ratio < 0.35:
            print('   ✅ 生效：彩色底也会被滤镜字节打成单色。')
            ok.append('单色滤镜')
        else:
            print('   ❌ 不生效，画面仍是彩色。')

    m0, mp, mm, md = get('M_CTRL'), get('M_SAT_P3'), get('M_SAT_M3'), get('M_DENS84')
    if m0 and mp and mm:
        rp, rm = mp['C'] / max(m0['C'], 1e-6), mm['C'] / max(m0['C'], 1e-6)
        print('【加彩度】单色底 + 饱和度：C* %+3d 档 %.3f× / %+3d 档 %.3f×' % (3, rp, -3, rm))
        if max(abs(rp - 1), abs(rm - 1)) > 0.05:
            print('   ✅ 生效。13–16 现在偏淡（SEPIA ΔC* −7.3 / RED −7.5），正好用这个补。')
            ok.append('单色底加彩度')
        else:
            print('   ❌ 不生效，单色支的彩度只能靠调色浓度。')
    if m0 and md:
        # 05 浓度 0x82，08 浓度 0x84
        step = (md['C'] / max(m0['C'], 1e-6)) ** 0.5 - 1.0
        print('【浓度】0x82 → 0x84：C* %.2f → %.2f（%.3f×，折合每档 %+.0f%%）'
              % (m0['C'], md['C'], md['C'] / max(m0['C'], 1e-6), step * 100))
        print('   模型按 ±25%%/档，之前那次探针量到 ~8%%/档 —— 现在有实数了，%+.0f%%/档。' % (step * 100))

    print('\n' + '=' * 74)
    print('生效的机制：%s' % ('、'.join(ok) if ok else '无（三条都封死）'))
    print('把这张判定表贴回 docs/17，就能决定下一版怎么改。')
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(main())
