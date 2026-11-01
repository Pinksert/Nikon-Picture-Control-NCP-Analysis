#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pack_base_probe.py —— 底子维度探针：同一支滤镜，只换底子编号。

由来：14-slider-calibration 里测出「底子字节会被 NX Studio 采纳」——
只改 offset 37（0x0001→0x00C3），曲线区一字未动，渲染结果 ΔE00 变化 2.36。
既然如此，「每支滤镜配哪个底子」就是一个从来没搜过的维度。

这个包只做一次方向验证，不追求最优：
  · 在 DSC_4484 上偏淡最狠的 4 支 → 换 VIVID（0x00C3），看彩度能不能补上来
  · 偏浓的 2 支                  → 换 NEUTRAL（0x03C2），看能不能压下去
对照基准直接用现成的 d300/samples/real_v3/（原底子版本），不用重渲。

    python d300/tools/pack_base_probe.py --out _probe_base
"""
import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sidecar_batch as S                                     # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
SRC = os.path.join(ROOT, 'ncp', 'release', 'NIKON', 'CUSTOMPC')
TPL = os.path.join(ROOT, '..', 'lightroom', 'NKSC_PARAM', 'DSC_4484.NEF.nksc')
NEF = os.path.join(ROOT, '..', 'lightroom', 'DSC_4484.NEF')

# 底子编号（大端 16 位，写在 NCP 的 offset 36-37）
BASES = {'STANDARD': 0x0001, 'VIVID': 0x00C3, 'NEUTRAL': 0x03C2, 'MONOCHROME': 0x064D}

# (槽位, 新底子, 备注, 是否干净实验)
#
# ⚠️ 30 支里有两套完全不同的调色机制，不能混在一起比：
#    彩色支   base=0x0001，用 offset 43 饱和度 / 44 色相
#    着色调支 base=0x064D MONOCHROME，43/44 是 FF（禁用），改用 46 着色色相 / 47 浓度
#    SEPIA(13) BLUE(14) RED(15) PINK(16) 就属于后者——它们名义上是单色底子，
#    实际靠着色档出颜色，所以「换 VIVID 底子」对它们是另一种东西，单独归为探索组。
PLAN = [
    (11, 'VIVID', '偏淡 −7.74，最狠', True),
    (12, 'VIVID', '偏淡 −7.58', True),
    (6, 'NEUTRAL', '偏浓 +4.44，已顶到 −3 档', True),
    (7, 'NEUTRAL', '偏浓 +4.38，已顶到 −3 档', True),
    (15, 'VIVID', '偏淡 −7.54，但它是着色调（探索）', False),
    (13, 'VIVID', '偏淡 −7.30，同上（探索）', False),
]


def set_base(b, code):
    b = bytearray(b)
    b[36] = (code >> 8) & 0xFF
    b[37] = code & 0xFF
    return bytes(b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(ROOT, '..', '_probe_base'))
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    side_dir = os.path.join(out, 'NKSC_PARAM')
    os.makedirs(side_dir, exist_ok=True)

    raw, txt = S.read_sidecar(TPL)
    print('模板 %s' % os.path.basename(TPL))
    print('%-22s %-10s %-9s %s' % ('输出名', '原底子', '新底子', '备注'))
    print('-' * 74)

    for i, (slot, base, why, clean) in enumerate(PLAN, 1):
        src = os.path.join(SRC, 'PICCON%02d.NCP' % slot)
        b = open(src, 'rb').read()
        old = (b[36] << 8) | b[37]
        nb = set_base(b, BASES[base])
        name = S.filt_name(b)
        stem = '%s%d_%s_%s' % ('' if clean else 'X', i, name, base)

        # 只改底子两个字节，其余逐字节核对
        diff = [k for k in range(len(b)) if b[k] != nb[k]]
        assert diff == [36, 37] or (diff == [37] and old >> 8 == 0), \
            '意外改动位置 %s（%s）' % (diff, name)

        src_nef = os.path.join(out, stem + '.NEF')
        shutil.copy2(NEF, src_nef)

        sc = S.embed_data(txt, nb, slot02=True)
        S.write_sidecar(os.path.join(side_dir, stem + '.NEF.nksc'), sc)

        # 往返校验：CustomData 必须与我们写进去的字节完全一致
        raw2, txt2 = S.read_sidecar(os.path.join(side_dir, stem + '.NEF.nksc'))
        c = S.custom_data(txt2)
        ok = (c == nb)
        print('%-22s 0x%04X     0x%04X     %s%s'
              % (stem, old, BASES[base], why, '' if ok else '  ✗ 往返不一致'))

    print()
    print('共 %d 份，目录 %s（约 %.0f MB）'
          % (len(PLAN), out, sum(os.path.getsize(os.path.join(out, f))
                                for f in os.listdir(out) if f.endswith('.NEF')) / 1e6))
    print('对照基准：d300/samples/real_v3/ 里同名支（原底子版本，不用重渲）')
    print('导出后放进 d300/samples/probe_base/')


if __name__ == '__main__':
    main()
