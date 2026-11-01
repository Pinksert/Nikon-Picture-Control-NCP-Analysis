#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pack_baseid_camera.py —— 底子编号的「机身准入」卡包（8 个文件，30 秒就能测完）。

背景：`docs/15-picture-control-base.md` 想用 8 份恒等曲线探针，判定"创意底子 0x0801–0x0814
在 NCP 里到底有没有效"。那需要用户在 NX Studio 里导出 8 张 NEF —— 成本不低。

但有一个更便宜的前置问题：**这些底子码，机身肯不肯让文件进「载入」列表？**

第 12 节已经记过：底子写 `0x03C2 / 0x00C3 / 0x0486 / 0x04C7`（滑块也一致）时，
**机内列表里根本不出现**；只有彩色 `0x0001`、单色 `0x064D` 会列出。
如果 08xx 也一样进不来，那"渲染 8 张、量底子位移"就无从谈起 —— 文件根本装不进相机。

所以先做这个卡包：8 个文件，曲线是恒等（机身执行 C(H(x)) = x，影调一个字不改），
只改底子编号，插卡看列表里出现几个。

    python tools/pack_baseid_camera.py

判读：

| 列表里出现 | 结论 |
|---|---|
| 2 个（01 / 04） | 机身白名单就是 `0001` / `064D`，08xx 这条路封死，docs/15 的渲染实验可以不做 |
| 3–4 个（含 02 / 03） | 机身认基础底子、只拒创意底子 → 仍是「四选一」，但至少能试 |
| 8 个 | 08xx 能导入，才值得去做 docs/15 的 NX Studio 渲染 |

产物：`ncp/packs/底子探针/NIKON/CUSTOMPC/PICCON01..08.NCP`
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
OUT = os.path.join(ROOT, 'ncp', 'packs', '底子探针', 'NIKON', 'CUSTOMPC')

# 滑块：彩色底子 / 单色底子两套中性值，档位全在 0
SL_COLOR = [0x83, 0x01, 0x01, 0x80, 0x80, 0x80, 0xFF, 0xFF]
SL_MONO = [0x82, 0x01, 0x01, 0xFF, 0xFF, 0x80, 0x80, 0xFF]

# (底子编号, 名字, 彩色/单色, 为什么放进来)
PLAN = [
    (0x0001, 'STANDARD', 'color', '对照：发布版用的就是它，必须出现'),
    (0x03C2, 'NEUTRAL', 'color', '基础底子·最淡；第 12 节实测「不出现」'),
    (0x00C3, 'VIVID', 'color', '基础底子·最浓；第 12 节实测「不出现」'),
    (0x064D, 'MONOCHROME', 'mono', '对照：单色唯一可用码，必须出现'),
    (0x0801, 'DREAM', 'color', '创意底子·实测偏淡最狠'),
    (0x0808, 'BLEACH', 'color', '创意底子·实测偏浓'),
    (0x080B, 'DENIM', 'color', '创意底子·实测偏淡最狠'),
    (0x0813, 'BINARY', 'mono', '创意底子·单色（我们一直用 064D 顶替）'),
]


def build(name, base, mono):
    """自己拼字节，不走 build_ncp —— 它会把「机身不认的底子码」挡在断言里，
    而这里正是要故意写那些码。"""
    lut = [int(round(v)) for v in precompensate(np.arange(257) / 256.0 * OUT_MAX, OUT_MAX)]
    prof = bytearray(b'0100')
    prof += name.upper().encode('ascii')[:20].ljust(20, b'\x00')
    prof += struct.pack('>H', base)
    prof += bytes([0x00, 0xFF])
    prof += bytes(SL_MONO if mono else SL_COLOR)

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
    print('%-12s %-8s %-12s %s' % ('文件', '底子', '名字', '说明'))
    print('-' * 76)
    for i, (base, name, kind, why) in enumerate(PLAN, 1):
        open(os.path.join(OUT, 'PICCON%02d.NCP' % i), 'wb').write(build(name, base, kind == 'mono'))
        print('PICCON%02d    0x%04X  %-12s %s' % (i, base, name, why))
    print('\n卡片包：%s' % OUT)
    print('拷到卡上后路径应为  NIKON\\CUSTOMPC\\PICCON01..08.NCP')
    print('然后：拍摄菜单 → 管理优化校准 → 载入/保存 → 复制到相机，数一数列表里有几个')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
