#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成一张可直接插卡的测试包（卡片包/），一次测完三件事：

  T-A 机身是否存在曲线前变换 H           -> T06 阶跃 / T04 补偿恒等 / T03 无曲线对照
  T-B 机身是否保留 20 个控制点           -> 把相机里的文件回存到卡，逐字节比对
  T-C 单色调的调色浓度该取多少           -> SEPIA 五档浓度 + 一个「不适用」

槽位与文件名严格用 PICCON%02d.NCP（D300 固件里唯一的路径格式）。
文件内嵌名字用 ASCII，机身菜单会显示它——所以名字就是标签。
"""
import os
import shutil
import struct

SRC = '.'
DST = '卡片包'

# 槽位 -> (源文件, 内嵌名字, 说明)
PLAN = [
    ('T06_STEP.NCP',  'T06 STEP',   '硬阶跃 v=128、未补偿：判定机身有无 H 的主探针'),
    ('T04_COMP.NCP',  'T04 COMP',   '补偿后的恒等曲线：机身有 H 时应≈机身标准'),
    ('T03_BASE.NCP',  'T03 BASE',   '52 字节无曲线：对照组，排除「文件根本没被读到」'),
    ('out/PICCON21.NCP', 'FLAT',     '平面：20 点连续曲线，肉眼最容易看出曲线是否生效'),
    ('out/PICCON19.NCP', 'BINARY',   '双色：阶跃位置，用来交叉验证 H'),
    ('out/PICCON13.NCP', 'SEPIA T0', '棕褐，调色浓度 0x80（最小）'),
    ('out/PICCON13.NCP', 'SEPIA T1', '棕褐，调色浓度 0x81'),
    ('out/PICCON13.NCP', 'SEPIA T2', '棕褐，调色浓度 0x82'),
    ('out/PICCON13.NCP', 'SEPIA T3', '棕褐，调色浓度 0x83'),
    ('out/PICCON13.NCP', 'SEPIA T4', '棕褐，调色浓度 0x84（当前版本，已知偏浓）'),
    ('out/PICCON13.NCP', 'SEPIA TNA', '棕褐，调色浓度 0xFF（不适用，尼康原厂的写法）'),
]

# ---- 二分诊断探针：把尼康原厂的 MONOCHROME.NCP（52 字节、无曲线）只改底子码 ----
# 若它能出现在机身「载入」列表里 → 底子 4 正确，问题只在「单色 + 638 字节曲线」这一组合
# 若它也不出现       → 底子 4 不对，或单色文件还有别的必填项
MONO_SRC = '../_ref/NCP-Analysis/presets/MONOCHROME.NCP'
BASE_OFF = 12 + 24       # rec1 头 12 + prof 内 版本4 + 名称20 = 36

# 棕褐五档 + 不适用：第 8 个滑块在文件里的偏移
# rec1 头 4+8=12 -> prof 起点 12；prof 内 版本4 + 名称20 + 底子2 + 两位2 = 28 -> 滑块 28..36
STRENGTH_OFF = 12 + 28 + 7   # = 47
NAME_OFF = 12 + 4            # = 16


def make_mono52():
    """原厂 MONOCHROME.NCP 原样搬过来，仅把 0x064D 改成 D300 认识的 0x0004"""
    b = bytearray(open(os.path.join(SRC, MONO_SRC), 'rb').read())
    assert len(b) == 52 and b[:4] == b'NCP\0', (len(b), b[:4])
    assert struct.unpack_from('>H', b, BASE_OFF)[0] == 0x064D
    struct.pack_into('>H', b, BASE_OFF, 0x0004)
    b[NAME_OFF:NAME_OFF + 20] = b'MONO 52'.ljust(20, b'\x00')
    return bytes(b)


def patch(raw, name, strength):
    b = bytearray(raw)
    assert b[0:4] == b'NCP\0' and len(b) in (52, 638), (len(b), b[:4])
    nb = name.upper().encode('ascii')[:20]
    b[NAME_OFF:NAME_OFF + 20] = nb.ljust(20, b'\x00')
    if strength is not None:
        b[STRENGTH_OFF] = strength
    return bytes(b)


def main():
    if os.path.isdir(DST):
        shutil.rmtree(DST)
    d = os.path.join(DST, 'NIKON', 'CUSTOMPC')
    os.makedirs(d)

    rows = []
    for i, (src, name, note) in enumerate(PLAN, 1):
        raw = open(os.path.join(SRC, src), 'rb').read()
        strength = None
        if 'SEPIA' in name:
            strength = {'SEPIA T0': 0x80, 'SEPIA T1': 0x81, 'SEPIA T2': 0x82,
                        'SEPIA T3': 0x83, 'SEPIA T4': 0x84, 'SEPIA TNA': 0xFF}[name]
        out = patch(raw, name, strength)
        fn = 'PICCON%02d.NCP' % i
        open(os.path.join(d, fn), 'wb').write(out)

        # 回读校验，防止偏移算错
        chk = open(os.path.join(d, fn), 'rb').read()
        nm = chk[NAME_OFF:NAME_OFF + 20].rstrip(b'\x00').decode('ascii')
        base = struct.unpack_from('>H', chk, 12 + 24)[0]
        sl = ' '.join('%02X' % c for c in chk[12 + 28:12 + 36])
        assert nm == name.upper()[:20], (nm, name)
        rows.append((fn, nm, base, sl, len(chk), note))

    # 二分探针：原厂单色 52 字节，只换底子码
    fn = 'PICCON%02d.NCP' % (len(PLAN) + 1)
    out = make_mono52()
    open(os.path.join(d, fn), 'wb').write(out)
    chk = open(os.path.join(d, fn), 'rb').read()
    rows.append((fn, chk[NAME_OFF:NAME_OFF + 20].rstrip(b'\x00').decode('ascii'),
                 struct.unpack_from('>H', chk, BASE_OFF)[0],
                 ' '.join('%02X' % c for c in chk[12 + 28:12 + 36]), len(chk),
                 '原厂单色只改底子码（二分诊断：单色这条路能不能走通）'))

    print('%-14s %-12s %-7s %-24s %-5s %s' %
          ('槽位文件', '内嵌名字', '底子', '八个滑块', '字节', '用途'))
    print('-' * 118)
    for fn, nm, base, sl, sz, note in rows:
        print('%-14s %-12s 0x%04X  %-24s %-5d %s' % (fn, nm, base, sl, sz, note))

    print()
    print('共 %d 个文件 -> %s' % (len(rows), d))
    print('注意：SEPIA 六档只有第 8 个滑块不同，曲线完全一致（唯一变量）。')


if __name__ == '__main__':
    main()
