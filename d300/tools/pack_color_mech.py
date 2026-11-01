#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pack_color_mech.py —— 「色彩机制」卡包：一次测三件从没验过的事。

为什么还要测
------------
第 17 节量出来：残差和"这支滤镜自己的色罩强度"相关 **r = 0.80**，而且
`残差 ≈ 3.65 + 0.217×|色偏|` —— 3.65 级是地板，剩下的全是色罩。
彩色底子（`0x0001`）只有「饱和度 / 色相」两个全局旋钮，**都动不了灰轴**，所以色罩做不出来。

但文件里还有三个字节，我们一直按「彩色底子必须是 FF FF（不适用）」的**惯例**写成 FF，
从来没验过机身是不是真的忽略它们：

| 字节 | 名字 | 我们一直写 | 万一机身其实认？ |
|---|---|---|---|
| 45 | 单色滤镜（黄/橙/红/绿） | `FF` | 能给彩色支加一层偏色 |
| 46 | 调色色相 | `FF` | **能给彩色支造色罩 → 直接打破 r=0.80** |
| 47 | 调色浓度 | `FF` | 同上，还能调强弱 |

反过来还有一条：单色支（13–16）的 43/44 写的是 `FF FF`，如果机身其实认，
那 13–16 就能多出 7 档彩度 —— 它们现在实测**偏淡**（SEPIA ΔC\* −7.3、RED −7.5），正缺这个。

三条都没验过。这个卡包就是去验它们。

    python tools/pack_color_mech.py

产物：`ncp/packs/色彩机制/NIKON/CUSTOMPC/PICCON01..08.NCP`

怎么测（不用 NEF、不用 NX Studio）
----------------------------------
1. 把 `NIKON` 拷到卡根目录，机身「载入/保存 → 复制到相机」，列表里应有 8 个。
   **这一步本身就是一个结论**：如果 06/07 不出现，说明机身不接受"单色底 + 饱和度"。
2. 找一个**有颜色**的固定场景（色卡、杂志、窗外），三脚架或固定位置，
   从 C_CTRL 到 M_DENS84 各拍一张，**中间不要改曝光/白平衡**。
3. 把 8 张 JPG 放进一个目录，跑：

       python tools/probe_color_mech_read.py --dir <目录>

判读（脚本会直接给结论）：

| 对比 | 看什么 | 结论 |
|---|---|---|
| 02 / 03 vs 01 | 整体 R−B 有没有移动 | 移动 > 3 级 → **彩色底子能造色罩**，色罩不再无解 |
| 04 vs 01 | 画面有没有变成单色 | 彩度掉到 ~0 → 滤镜字节也生效 |
| 06 / 07 vs 05 | 平均 C\* 有没有变 | 变了 → 单色支可以靠饱和度加彩度，13–16 有救 |
| 08 vs 05 | 同一支只改浓度 | 得到浓度的真实斜率（现在模型 ±25%/档、探针 ~8%/档，差三倍） |

⚠️ 这 8 个文件**故意**违反「彩色底子 45–47 必须 FF」的惯例，所以 `ncp_d300.verify_one()`
会报它们不合格 —— 那是发布包的规矩，不是探针的。别拿它们做发布。
"""
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from compensate import precompensate                            # noqa: E402
from ncp_d300 import OUT_MAX, REC2_LEN, header_from_lut         # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
OUT = os.path.join(ROOT, 'ncp', 'packs', '色彩机制', 'NIKON', 'CUSTOMPC')

# 八滑块顺序：锐化 对比度 亮度 饱和度 色相 | 单色滤镜 调色色相 调色浓度
# 对比度/亮度写 01 01 = 交给曲线（否则 578 字节曲线被静默丢弃）
SL_COLOR = [0x83, 0x01, 0x01, 0x80, 0x80, 0xFF, 0xFF, 0xFF]
SL_MONO = [0x82, 0x01, 0x01, 0xFF, 0xFF, 0x80, 0x81, 0x82]

# 调色色相表（固件实测，docs/10）：80 B&W / 81 SEPIA / 82 CYANOTYPE / 83 RED
#                              84 YELLOW / 85 GREEN / 86 BLUE GREEN / 87 BLUE / 88 PURPLE BLUE / 89 RED PURPLE

PLAN = [
    # (文件后缀名, 底子, 滑块, 一句话)
    ('C_CTRL',     0x0001, SL_COLOR[:], '彩色基准：就是发布包的写法（45–47 = FF）'),
    ('C_TONE_Y',   0x0001, SL_COLOR[:5] + [0x80, 0x84, 0x82], '彩色底 + 黄色调色：会出暖罩吗'),
    ('C_TONE_B',   0x0001, SL_COLOR[:5] + [0x80, 0x87, 0x82], '彩色底 + 蓝色调色：会出冷罩吗'),
    ('C_FILT_Y',   0x0001, SL_COLOR[:5] + [0x84, 0xFF, 0xFF], '彩色底 + 单色滤镜字节（黄）'),
    ('M_CTRL',     0x064D, SL_MONO[:], '单色着色基准：13 号的写法（SEPIA 0x81，浓度 0x82）'),
    ('M_SAT_P3',   0x064D, SL_MONO[:3] + [0x83, 0x80, 0x80, 0x81, 0x82], '单色底 + 饱和度 +3'),
    ('M_SAT_M3',   0x064D, SL_MONO[:3] + [0x7D, 0x80, 0x80, 0x81, 0x82], '单色底 + 饱和度 −3'),
    ('M_DENS84',   0x064D, SL_MONO[:7] + [0x84], '单色底 + 浓度 0x84（第一版的水平）'),
]


def build(name, base, sliders):
    """自己拼字节：探针要故意写一些发布包不会写的组合，不走 build_ncp 的断言。"""
    lut = [int(round(v)) for v in precompensate(np.arange(257) / 256.0 * OUT_MAX, OUT_MAX)]
    prof = bytearray(b'0100')
    prof += name.upper().encode('ascii')[:20].ljust(20, b'\x00')
    prof += struct.pack('>H', base)
    prof += bytes([0x00, 0xFF])
    prof += bytes(sliders)

    data = header_from_lut(lut) + b''.join(struct.pack('>H', v) for v in lut)
    assert len(data) == REC2_LEN, len(data)
    out = bytearray(b'NCP\0')
    out += struct.pack('>II', 1, 36) + bytes(prof)
    out += struct.pack('>II', 2, REC2_LEN) + data
    out += struct.pack('>I', 0)
    assert len(out) == 638
    return bytes(out)


def main():
    os.makedirs(OUT, exist_ok=True)
    print('%-8s %-8s %-12s %-26s %s' % ('文件', '底子', '名字', '八滑块', '测什么'))
    print('-' * 104)
    for i, (name, base, sl, why) in enumerate(PLAN, 1):
        sl = list(sl)
        assert len(sl) == 8, (name, len(sl))
        open(os.path.join(OUT, 'PICCON%02d.NCP' % i), 'wb').write(build(name, base, sl))
        print('PICCON%02d  0x%04X  %-12s %-26s %s'
              % (i, base, name, ' '.join('%02X' % b for b in sl), why))
    print('\n卡片包：%s' % OUT)
    print('拷卡路径  NIKON\\CUSTOMPC\\PICCON01..08.NCP')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
