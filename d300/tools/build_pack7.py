#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第七轮卡片包：曲线确认可用之后，判「机身有没有 H 前置变换」。

【第七批照片（DSC_5295–5298 = 01STD / 02GAM / 03MNCP / 04SNCP）结论】
  02 GAM 与 01 STD 逐像素几乎相同（meanabs 1.49）→ 我方曲线没执行
  03 MNCP 平均差 21.89、L 均值 54.6→76.4          → 原厂 M.NCP 的曲线执行了
  04 SNCP 平均差 38.44、中段反向                   → 原厂 S.NCP 的曲线执行了

→ 机身能执行 NCP 曲线。差别只有一个字节对：
    原厂 638B 文件：[41][42] = 01 01
    我方探针文件   ：[41][42] = 80 80
  统计 116 个原厂文件：52B 一律 80 80，638B 一律 01 01，无一例外。
  0x01 = 「对比度/亮度交给曲线」，0x80 = 数值 0（线性）。写了 80 80 机身就
  按线性对比度出图，把 638 字节曲线块直接忽略。

  ⚠️ 好消息：`out/` 和 `out_comp/` 里 60 个正式滤镜本来写的就是 01 01
     （走的是 sliders_for(has_curve=True)），所以它们从没坏过，只是没被测到。

本轮 8 槽（全部 01 01）：
  01 STD   52B 对照
  02 STEP  ★硬阶跃 v=128：判 H —— 阶跃落在 128 = 机身无 H（用 out/）
                                      落在 ≈146 = 机身有 H（用 out_comp/）
  03 GAM   我方 gamma 0.45（20 点自适应）：曲线是否真的执行
  04 U-POP out/PICCON03（未补偿）
  05 C-POP out_comp/PICCON03（补偿版）
  06 U-BIN out/PICCON19 双色（未补偿，曲线最极端）
  07 C-BIN out_comp/PICCON19 双色（补偿版）
  08 U-SEP out/PICCON13 棕褐（单色底子 + 曲线，验证单色也能带曲线）
"""
import os
import shutil
import struct

HERE = os.path.dirname(os.path.abspath(__file__))


def _pick(*rel):
    for r in rel:
        p = os.path.normpath(os.path.join(HERE, r))
        if os.path.isdir(p):
            return p
    raise SystemExit('找不到目录：' + ' / '.join(rel))


# 兼容两种布局：
#   开发目录  D300_NCP/*.py              → out/ out_comp/ 就在旁边，presets 在 ../_ref/NCP-Analysis/presets
#   仓库目录  d300/tools/build_pack7.py  → out/ out_comp/ 在 ../ncp/，presets 在 ../../presets
NCPROOT = _pick('../ncp', '.')
IN_REPO = os.path.normpath(NCPROOT) != os.path.normpath(HERE)
PRESETS = _pick('../_ref/NCP-Analysis/presets', '../../presets', '../presets')
PACKDIR = os.path.join(NCPROOT, 'packs', '卡片包7') if IN_REPO else os.path.join(HERE, '卡片包7')

SRC = NCPROOT
DST = PACKDIR
REPO = PRESETS

OUT_MAX = 32767
NAME_OFF = 16
BASE_OFF = 36
SL_OFF = 40
LUT_HDR = 56

# 638B（带曲线）必须写 01 01
SL_STD = [0x83, 0x01, 0x01, 0x80, 0x80, 0xFF, 0xFF, 0xFF]


def lut_from(fn):
    return [int(round(fn(i) * OUT_MAX / 255.0)) for i in range(257)]


def rename(raw, name):
    b = bytearray(raw)
    b[NAME_OFF:NAME_OFF + 20] = name.upper().encode('ascii')[:20].ljust(20, b'\x00')
    return bytes(b)


def rewrite_header(ncp, pts, aria2=0x30):
    """替换 64 字节 LUT 头（控制点/AriaID），LUT 本体不动。
    自适应布点会在阶跃处插进多余的点，把硬阶跃抹成斜坡，所以 STEP 要手写 4 个点。"""
    b = bytearray(ncp)
    assert len(b) == 638 and b[LUT_HDR] == 0x49
    h = bytearray(b'\x49' + bytes([aria2]) + bytes([0x00, 0xFF, 0x00, 0xFF, 0x01, 0x00]))
    h.append(len(pts))
    for x, y in pts:
        h += bytes([x, y])
    h += b'\x00' * (64 - len(h))
    b[LUT_HDR:LUT_HDR + 64] = h[:64]
    return bytes(b)


def main():
    import ncp_d300

    std52 = open(os.path.join(REPO, 'STANDARD.NCP'), 'rb').read()
    gam45 = lut_from(lambda v: 255.0 * (v / 255.0) ** 0.45)
    step = [0] * 128 + [OUT_MAX] * 129
    # 硬阶跃只给 4 个点，(0,0)(127,0)(128,255)(255,255)：任何插值方式出来的都是陡壁
    step4 = rewrite_header(ncp_d300.build_ncp('02 STEP', 1, SL_STD, step),
                           [(0, 0), (127, 0), (128, 255), (255, 255)])

    plan = [
        ('STD',   rename(std52, '01 STD'),                                   52),
        ('STEP',  step4,                                                    638),
        ('GAM',   ncp_d300.build_ncp('03 GAM', 1, SL_STD, gam45),           638),
        ('U-POP', rename(open(os.path.join(SRC, 'out', 'PICCON03.NCP'), 'rb').read(), '04 U-POP'), 638),
        ('C-POP', rename(open(os.path.join(SRC, 'out_comp', 'PICCON03.NCP'), 'rb').read(), '05 C-POP'), 638),
        ('U-BIN', rename(open(os.path.join(SRC, 'out', 'PICCON19.NCP'), 'rb').read(), '06 U-BIN'), 638),
        ('C-BIN', rename(open(os.path.join(SRC, 'out_comp', 'PICCON19.NCP'), 'rb').read(), '07 C-BIN'), 638),
        ('U-SEP', rename(open(os.path.join(SRC, 'out', 'PICCON13.NCP'), 'rb').read(), '08 U-SEP'), 638),
    ]

    if os.path.isdir(DST):
        shutil.rmtree(DST)
    d = os.path.join(DST, 'NIKON', 'CUSTOMPC')
    os.makedirs(d)

    print('%-14s %-11s %-7s %-5s %-24s %-4s' % ('槽位', '名字', '底子', '字节', '八个滑块', '点数'))
    print('-' * 80)
    for i, (tag, raw, size) in enumerate(plan, 1):
        fn = 'PICCON%02d.NCP' % i
        open(os.path.join(d, fn), 'wb').write(raw)
        b = raw
        assert len(b) == size, (fn, len(b), size)
        nm = b[NAME_OFF:NAME_OFF + 20].rstrip(b'\x00').decode('ascii')
        base = struct.unpack_from('>H', b, BASE_OFF)[0]
        sl = ' '.join('%02X' % v for v in b[SL_OFF:SL_OFF + 8])
        npt = b[LUT_HDR + 8] if len(b) > 100 else 0
        flag = ''
        if len(b) > 100 and (b[41] != 0x01 or b[42] != 0x01):
            flag = '  ⚠️曲线标志位不是 01 01！'
        print('%-14s %-11s 0x%04X  %-5d %-24s %-4d%s' % (fn, nm, base, len(b), sl, npt, flag))

    print('\n生成于', d)


if __name__ == '__main__':
    main()
