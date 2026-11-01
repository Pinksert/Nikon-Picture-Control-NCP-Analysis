#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pack_toning_sweep.py —— 调色浓度（offset 47）扫描包：把 13–16 的"太淡/太浓"定死。

背景（2026-11-01 实测）
----------------------
`samples/probe_color` 那 8 张探针给出了三条硬结论（见 docs/17）：

    彩色底 + 45/46/47      → 完全不起作用（四个字节怎么改，画面一模一样）
    单色底 + 43/44 饱和度   → 也不起作用
    单色底 + 47 调色浓度    → **起作用，而且很猛：0x82 → 0x84 彩度 ×2.08（每档 ×1.44）**

模型里原来按 ±25%/档 算，实测是 ±44%/档 —— 差了近一倍。这意味着 13–16 现在的浓度档位
是按一把短尺子选的，值不值得改必须实测。

怎么测
------
一支滤镜在同一张底片上跑 2–3 个浓度，和**官方同帧渲染**比彩度，谁近选谁。
底片用 `DSC_3891` —— 因为官方那 30 张（`samples/workshop/`）就是这张，像素严格对齐，
不用额外再渲一遍目标侧。

    python tools/pack_toning_sweep.py \\
        --template "…/NKSC_PARAM/DSC_4513.NEF.nksc" \\
        --nef      "…/测试图片/DSC_3891.NEF" \\
        --out      "D:/Documents/Workbuddy/D300/_probe_toning"

产物：8 份 NEF 拷贝 + 对应 sidecar，NX Studio 里 Ctrl+A 一次导出。
"""
import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import sidecar_batch as S                                       # noqa: E402
from pack_probe_sidecars import build_one, neutralize, verify   # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
REL = os.path.join(ROOT, 'ncp', 'release', 'NIKON', 'CUSTOMPC')

# (槽位, 滤镜名, [要试的浓度字节…])；第一项 = 发布包当前值，作为基准
PLAN = [
    (13, 'SEPIA', [0x81, 0x82, 0x83]),
    (15, 'RED',   [0x82, 0x83, 0x84]),
    (16, 'PINK',  [0x82, 0x83]),
    (14, 'BLUE',  [0x82, 0x81]),
]


def patch_density(ncp, b):
    """offset 47 = 第八个滑块 = 调色浓度。只改这一个字节。"""
    out = bytearray(ncp)
    assert out[47] != 0xFF, '这支不是调色支（45–47 里没有浓度）'
    out[47] = b
    return bytes(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--template', required=True)
    ap.add_argument('--nef', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()

    template = open(a.template, encoding='utf-8', errors='replace').read()
    template, n_hue = neutralize(template)
    print('模板里的全局色相调整已归零（%d 处）\n' % n_hue)
    os.makedirs(os.path.join(a.out, 'NKSC_PARAM'), exist_ok=True)

    print('%-6s %-8s %-6s %-6s %s' % ('文件', '滤镜', '浓度', '现值', '说明'))
    print('-' * 62)
    k = 0
    for slot, name, dens in PLAN:
        src = open(os.path.join(REL, 'PICCON%02d.NCP' % slot), 'rb').read()
        cur = src[47]
        for b in dens:
            k += 1
            ncp = patch_density(src, b)
            stem = '%02d_%s_%02X' % (k, name, b)
            shutil.copyfile(a.nef, os.path.join(a.out, stem + '.NEF'))
            sc = os.path.join(a.out, 'NKSC_PARAM', stem + '.NEF.nksc')
            open(sc, 'w', encoding='utf-8').write(build_one(template, ncp))
            prob = verify(sc, ncp)
            print('%-6s %-8s 0x%02X   %-6s %s'
                  % ('%02d_%s' % (k, name), name, b,
                     '当前' if b == cur else '',
                     prob or '两份数据一致 ✓'))
    print('\n输出目录：%s' % a.out)
    print('NX Studio 打开 → 全选 → 导出，然后跑：')
    print('  python tools/probe_toning_read.py --dir %s' % a.out)
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(main())
