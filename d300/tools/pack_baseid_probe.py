#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pack_baseid_probe.py —— 底子「指纹」探针：恒等曲线 + 只换底子编号。

为什么要做这个：
    26 支真渲染对照里，「官方用创意底子（0801-0814）」的 16 支平均差 8.21 级，
    「官方用基础底子」的 6 支只有 3.71 级；而同样来自创意底子的 4 支单色只有 3.55 级。
    差别在调色：单色支的彩度偏差标准差只有 0.08，彩色支是 4.41。
    也就是说，我们的单条曲线能搬影调，搬不动创意底子那层色彩变换。

    但这是相关性，不是因果——也可能只是「这几支本来就更极端」。
    要拆开，只能用最干净的一组：恒等曲线（不搬任何影调）+ 只改底子编号。
    渲染出来就是「底子自己干的活」，跟曲线无关。

    ⚠️ 这个实验同时回答一个更关键的问题：NCP 到底认不认 08xx 创意底子编号。
       如果 8 张渲出来只有 3 种结果（0001/03C2/00C3 各一种，08xx 全部等于 0001），
       说明创意底子写进 NCP 无效，这条升级路直接封死，只剩「在 4 个基础底子里选」。

    python d300/tools/pack_baseid_probe.py --out _probe_baseid
"""
import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..', 'np3tool')))

import numpy as np                                            # noqa: E402
import np3core as C                                           # noqa: E402
import sidecar_batch as S                                     # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
TPL = os.path.join(ROOT, '..', 'lightroom', 'NKSC_PARAM', 'DSC_4484.NEF.nksc')
NEF = os.path.join(ROOT, '..', 'lightroom', 'DSC_4484.NEF')

# 滑块：普通彩色底子 / 单色底子两套中性值（与发布版同款写法，只是档位全在 0）
SL_COLOR = [0x83, 0x01, 0x01, 0x80, 0x80, 0x80, 0xFF, 0xFF]
SL_MONO = [0x82, 0x01, 0x01, 0xFF, 0xFF, 0x80, 0x80, 0xFF]

# (底子编号, 名字, 归类, 为什么放进来)
PLAN = [
    (0x0001, 'STANDARD',   'color', '对照：我们自己用的就是它'),
    (0x03C2, 'NEUTRAL',    'color', '基础底子里最淡的一支'),
    (0x00C3, 'VIVID',      'color', '基础底子里最浓的一支'),
    (0x064D, 'MONOCHROME', 'mono',  '基础底子·单色'),
    (0x0801, 'DREAM',      'color', '创意底子·实测偏淡最狠的 DREAM'),
    (0x0808, 'BLEACH',     'color', '创意底子·实测偏浓的 BLEACH'),
    (0x080B, 'DENIM',      'color', '创意底子·实测偏淡最狠的 DENIM'),
    (0x0813, 'BINARY',     'mono',  '创意底子·单色（我们一直用 064D 顶替）'),
]


def make_identity_ncp(name, base, mono):
    """恒等曲线：机身执行 C(H(x)) = x，影调一个字都不改。"""
    curve = np.arange(256, dtype=np.float64)
    ncp = C.make_ncp(name, base, SL_MONO if mono else SL_COLOR, curve)
    # 往返核对：曲线必须单调且近似恒等
    d = C.read_ncp(ncp)
    assert d['base'] == base, '底子写错 %04X' % d['base']
    got = C.H(d['lut'])     # 机身执行 C(H(x))，所以要回到「有效曲线」再比
    err = float(np.abs(got - np.arange(257)).max())
    assert err < 1.5, '恒等曲线偏差过大 %.2f' % err
    return ncp, err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(ROOT, '..', '_probe_baseid'))
    ap.add_argument('--nef', default=NEF)
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    side = os.path.join(out, 'NKSC_PARAM')
    os.makedirs(side, exist_ok=True)

    raw, txt = S.read_sidecar(TPL)
    for f in os.listdir(side):
        os.remove(os.path.join(side, f))

    print('模板 %s' % os.path.basename(TPL))
    print('底片 %s' % os.path.basename(a.nef))
    print()
    print('%-6s %-14s %-10s %-6s %s' % ('输出', '底子', '编号', '类别', '说明'))
    print('-' * 78)
    for i, (code, nm, kind, why) in enumerate(PLAN, 1):
        stem = 'B%d_%s' % (i, nm)
        ncp, err = make_identity_ncp('P%04X' % code, code, kind == 'mono')
        shutil.copy2(a.nef, os.path.join(out, stem + '.NEF'))
        sc = S.embed_data(txt, ncp, slot02=True)
        S.write_sidecar(os.path.join(side, stem + '.NEF.nksc'), sc)

        # 往返核对：sidecar 里的 CustomData 必须逐字节等于我们生成的 NCP
        import base64
        import re
        _, t2 = S.read_sidecar(os.path.join(side, stem + '.NEF.nksc'))
        c = base64.b64decode(re.search(r'<CustomData>(.*?)</CustomData>', t2, re.S).group(1).strip())
        assert c == ncp, '%s 往返不一致' % stem
        print('%-6s %-14s 0x%04X     %-6s %s' % (stem, nm, code, kind, why))

    nefs = [f for f in os.listdir(out) if f.upper().endswith('.NEF')]
    mb = sum(os.path.getsize(os.path.join(out, f)) for f in nefs) / 1e6
    print()
    print('生成 %d 份 NEF（%.0f MB）+ %d 个 sidecar（%d B / 个，含两处内嵌）'
          % (len(nefs), mb, len(os.listdir(side)), os.path.getsize(
              os.path.join(side, os.listdir(side)[0]))))
    print('导出到 d300/samples/probe_baseid/ 后跑：')
    print('  python d300/tools/probe_baseid_read.py --dir d300/samples/probe_baseid')


if __name__ == '__main__':
    main()
