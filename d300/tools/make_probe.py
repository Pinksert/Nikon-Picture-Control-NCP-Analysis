#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""标定探针：造两条「已知答案」的曲线，用来测定工坊到底怎么执行 NCP 里的曲线。

为什么需要
----------
首轮测试里，曲线两端的取值被精确执行了（14 / 22 / 242 全部对上），
但中间调比设计值暗 20–25 级，8 个滤镜一致。
这说明曲线「被读了」但「被换算了」——需要一次标定才能确定换算关系。

两个探针
--------
T01_IDENT   曲线 = 恒等（输入=输出，20 点等距）。
            期望：套用后与「原厂标准」几乎一样。
            若明显偏暗 → 说明引擎对曲线的解释与我的假设不同。
T02_INVERT  曲线 = 反相（输出 = 255 - 输入）。
            期望：套用后是一张干净的负片。
            若不是干净的负片，从偏差形状就能反推出它实际的换算方式。

用法：导入工坊 → 对同一张 NEF 各导出一张 JPG → 文件名里带 IDENT / INVERT。
"""
import os
import struct

OUT_MAX = 32767
HDR_LEN = 64
REC2_LEN = HDR_LEN + 257 * 2
HDR_PREFIX = bytes.fromhex('493000FF00FF0100')
SL_ZERO, SL_CURVE = 0x80, 0x01
BASE_STD = 0x0001


def build(name, base, pts, lut):
    """pts: [(x,y)] 控制点；lut: 257 项绝对 LUT（0..32767）"""
    nb = name.upper().encode('ascii')[:20]
    prof = bytearray(b'0100') + nb.ljust(20, b'\x00')
    prof += struct.pack('>H', base) + bytes([0, 0xFF])
    # 八个滑块：锐化 0 / 对比度与亮度交给曲线 / 饱和度色相 0 / 单色三项不适用
    prof += bytes([SL_ZERO, SL_CURVE, SL_CURVE, SL_ZERO, SL_ZERO, 0xFF, 0xFF, 0xFF])
    assert len(prof) == 36, len(prof)

    out = bytearray(b'NCP\x00') + struct.pack('>II', 1, 36) + prof

    h = bytearray(HDR_PREFIX)
    h.append(len(pts))
    for x, y in pts:
        h += bytes([x, y])
    h += b'\x00' * (HDR_LEN - len(h))
    assert len(h) == HDR_LEN

    data = bytes(h) + b''.join(struct.pack('>H', max(0, min(OUT_MAX, int(v))))
                               for v in lut)
    assert len(data) == REC2_LEN, len(data)
    out += struct.pack('>II', 2, REC2_LEN) + data
    out += struct.pack('>I', 0)
    return bytes(out)


def ident():
    # 20 点等距恒等
    pts = [(round(i * 255 / 19), round(i * 255 / 19)) for i in range(20)]
    lut = [round(i * OUT_MAX / 256) for i in range(257)]
    return pts, lut


def invert():
    # 反相：只有两个端点，输入 0 -> 255，输入 255 -> 0
    pts = [(0, 255), (255, 0)]
    lut = [round((255 - i) * OUT_MAX / 255) for i in range(257)]
    return pts, lut


def main():
    dst = os.path.dirname(os.path.abspath(__file__))
    for nm, fn in (('T01_IDENT', ident), ('T02_INVERT', invert)):
        pts, lut = fn()
        b = build(nm, BASE_STD, pts, lut)
        p = os.path.join(dst, nm + '.NCP')
        open(p, 'wb').write(b)
        print('%-12s %d 字节  控制点 %d 个  前两个 %s' % (nm, len(b), len(pts), pts[:2]))
    print()
    print('两个文件都在 %s' % dst)


if __name__ == '__main__':
    main()
