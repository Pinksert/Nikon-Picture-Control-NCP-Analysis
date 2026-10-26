#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 H⁻¹ 预补偿，重新生成 /out 全部文件到 /out_comp，并产出三个探针。

为什么要重做
------------
out/ 那批在工坊里实测：中间调暗 18 级（H 已量化）。补偿后引擎执行
C'(H(x)) = T(H⁻¹(H(x))) = T(x)，即回到设计目标。

产物
----
T03_BASE    52 字节、无曲线、底子 0x0001（与尼康原厂 STANDARD.NCP 同构）
            工坊里应≈机身，用来确认「52 字节这条路」本身没问题
T04_COMP    曲线 = H⁻¹，套用后应≈机身（恒等）——把补偿的效果直接看出来
T06_STEP    v=128 处硬阶跃，不补偿。插卡拍一张即可判定机身有没有 H：
            机身若与工坊一致，阶跃会出现在输入≈146 处；若无 H，就在 128 处
"""
import glob
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compensate import H, H_inv, precompensate, simulate   # noqa: E402
from ncp_d300 import OUT_MAX, build_ncp                      # noqa: E402

BASE_STD = 0x0001
from cmp_ncp import read_ncp, to255                          # noqa: E402

SL_FACTORY_STD = [0x83, 0x80, 0x80, 0x80, 0x80, 0xFF, 0xFF, 0xFF]


def read_profile(path):
    """从已有 NCP 取出 名称/底子/滑块/曲线LUT"""
    b = open(path, 'rb').read()
    assert b[:4] == b'NCP\0'
    name = b[16:36].rstrip(b'\x00').decode('latin1')
    base = struct.unpack_from('>H', b, 36)[0]
    sliders = list(b[40:48])
    lut = None
    if len(b) > 100:
        lut = list(struct.unpack_from('>257H', b, 120))
    return name, base, sliders, lut


def main():
    D = os.path.dirname(os.path.abspath(__file__))
    src = os.path.join(D, 'out')
    dst = os.path.join(D, 'out_comp')
    os.makedirs(dst, exist_ok=True)

    print('=' * 70)
    print('重新生成 30 个文件（预补偿）')
    print('=' * 70)
    print('%-14s %-22s %-8s %s' % ('文件', '名称', '底子', '补偿后模拟残差'))
    worst = 0.0
    for p in sorted(glob.glob(os.path.join(src, '*.NCP'))):
        name, base, sliders, lut = read_profile(p)
        new = precompensate(lut, OUT_MAX)
        out = build_ncp(name, base, sliders, new)
        fn = os.path.join(dst, os.path.basename(p))
        open(fn, 'wb').write(out)

        # 自检：模拟引擎执行 C'(H(x))，与目标 T(x) 比
        _, got, tgt = simulate(lut, OUT_MAX)
        err = float(np.abs(got - tgt).max())
        worst = max(worst, err)
        flag = '' if err <= 1.0 else '  **超出1级**'
        print('%-14s %-22s 0x%04X   %.2f/255%s'
              % (os.path.basename(p), name, base, err, flag))
    print('\n30 个文件最大模拟残差 %.2f/255（=%.2f%% 的亮度量程）'
          % (worst, worst / 255 * 100))

    # ---------------- 探针 ----------------
    print()
    print('=' * 70)
    print('探针')
    print('=' * 70)

    # T03：52 字节，无曲线
    t03 = build_ncp('T03_BASE', BASE_STD, SL_FACTORY_STD, None)
    open(os.path.join(D, 'T03_BASE.NCP'), 'wb').write(t03)
    ref = open(os.path.join(D, '..', '_ref', 'NCP-Analysis', 'presets',
                           'STANDARD.NCP'), 'rb').read()
    print('T03_BASE   %d 字节  与尼康原厂 STANDARD.NCP 逐字节%s'
          % (len(t03), '相同' if t03 == ref else '不同（见下）'))
    if t03 != ref:
        diff = [i for i in range(min(len(t03), len(ref))) if t03[i] != ref[i]]
        print('          差异字节位置 %s  我方=%s 原厂=%s'
              % (diff, t03[16:36], ref[16:36]))

    # T04：曲线 = H⁻¹（补偿后的恒等）
    ident = [int(round(i * OUT_MAX / 255.0)) for i in range(257)]
    t04 = build_ncp('T04_COMP', BASE_STD, SL_FACTORY_STD,
                    precompensate(ident, OUT_MAX))
    open(os.path.join(D, 'T04_COMP.NCP'), 'wb').write(t04)
    c = read_ncp(os.path.join(D, 'T04_COMP.NCP'))['curve']
    print('T04_COMP   %d 字节  点数%d  补偿曲线采样 v=0,64,128,192,255 → %s'
          % (len(t04), c['n'],
             [round(to255(c['lut'][v])) for v in (0, 64, 128, 192, 255)]))
    print('           期望：套用后≈机身（因为 H⁻¹ 抵消了 H）')

    # T06：硬阶跃 v=128，故意不补偿
    step = [0] * 128 + [OUT_MAX] * 129
    t06 = build_ncp('T06_STEP', BASE_STD, SL_FACTORY_STD, step)
    # 自适应布点会插一个 (127,127) 的中间点，把阶跃抹成 1 级宽的斜坡。
    # 判定要用最硬的边缘，所以直接改写成 4 个点。
    pts = [(0, 0), (126, 0), (128, 255), (255, 255)]
    h = bytearray(b'\x49\x30\x00\xFF\x00\xFF\x01\x00')
    h.append(len(pts))
    for x, y in pts:
        h += bytes([x, y])
    h += b'\x00' * (64 - len(h))
    t06 = t06[:56] + bytes(h[:64]) + t06[120:]
    open(os.path.join(D, 'T06_STEP.NCP'), 'wb').write(t06)
    c = read_ncp(os.path.join(D, 'T06_STEP.NCP'))['curve']
    print('T06_STEP   %d 字节  点数%d  控制点=%s  阶跃在 v=128（未补偿）'
          % (len(t06), c['n'], c['pts']))
    print('           工坊里阶跃应出现在输入≈%.0f 处（因 H）；'
          '机身若同款引擎则在≈%.0f，否则在 128' % (H_inv(128), H_inv(128)))

    print()
    print('滑块对照（T03/T04/T06 均用尼康原厂 STANDARD 的 83 80 80 80 80 FF FF FF）：')
    for f in ('T03_BASE.NCP', 'T04_COMP.NCP', 'T06_STEP.NCP'):
        nm, base, sl, lut = read_profile(os.path.join(D, f))
        print('  %-14s base=0x%04X 滑块=%s %s'
              % (f, base, ' '.join('%02X' % v for v in sl),
                 '有曲线' if lut else '无曲线（52 字节）'))


if __name__ == '__main__':
    main()
