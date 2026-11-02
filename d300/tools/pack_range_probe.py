#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pack_range_probe.py —— 两组「机内还剩没剩」的探针，一轮导出全答。

为什么要做
----------
`lut_fit.py` 拟出的三维残差说明：机内那三个旋钮（曲线 / 饱和度 / 色相）是
全局的，救不了逐色相的颜色重排。但 `oracle_global.py` 顺带暴露了两件**可能还没试过**的事：

1. **滑块字节的范围**。NCP 里饱和度是 `数值 + 0x80` 的有符号字节，格式上到 ±126，
   而菜单只给 ±3。SILENCE 这类「偏浓」的支，oracle 要把彩度再乘 0.64，
   折算下来是 −6 档 —— 如果机身认 0x7A（−6），它们还能再压一大截。
   文档里所有探针都只走到 ±3，这一格从没越过。

2. **底子编号**。实测「同曲线只改底子」在 NX Studio 里 ΔE00 2.36、彩度 +8.1%，
   而 16 支创意底·彩色的实测残差全是偏淡。换底子是不是能凭空调出彩度？
   8 份恒等曲线探针（`_probe_baseid/`）验的是「底子自己干什么」，
   这份验的是「换到真滤镜上有没有用」——两件事不一样。

做法
----
直接拿 `ncp/release/` 里现成的 NCP 改**一个字节**，其余字节（含 578 B 曲线）原样不动，
再套上官方 sidecar 模板。每个探针都能跟 `samples/real_v3/` 同槽号的成片 A/B，
只差那一个字节，所以读数没有混杂。

    python d300/tools/pack_range_probe.py --out _probe_range
    # NX Studio 打开 _probe_range → Ctrl+A 导出 → 放进 d300/samples/probe_range/
    python d300/tools/probe_range_read.py --dir d300/samples/probe_range
"""
import argparse
import base64
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..', 'np3tool')))

import sidecar_batch as S                                     # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
REL = os.path.join(ROOT, 'ncp', 'release', 'NIKON', 'CUSTOMPC')
TPL = os.path.join(ROOT, '..', 'lightroom', 'NKSC_PARAM', 'DSC_4484.NEF.nksc')
NEF = os.path.join(ROOT, '..', 'lightroom', 'DSC_4484.NEF')

# (输出名, 槽号, {偏移: 新值}, 想验证什么)
PLAN = [
    ('R1_SILENCE_sat-6', 7, {43: 0x7A}, '饱和度越过 −3：字节范围到底认到哪'),
    ('R2_SILENCE_sat-9', 7, {43: 0x77}, '同上，再往外走两档看有没有线性延伸'),
    ('R3_DENIM_sat+6', 11, {43: 0x86}, '反方向：偏淡的支能不能加过头'),
    ('R4_TOY_sat+6', 12, {43: 0x86}, 'TOY 现在 −2，一步跨到 +6'),
    ('R5_DENIM_VIVID', 11, {36: 0x00, 37: 0xC3}, '底子换 VIVID（曲线不动）'),
    ('R6_TOY_VIVID', 12, {36: 0x00, 37: 0xC3}, '底子换 VIVID'),
    ('R7_DREAM_VIVID', 1, {36: 0x00, 37: 0xC3}, '底子换 VIVID'),
    ('R8_DRAMA_NEUTRAL', 6, {36: 0x03, 37: 0xC2}, '偏浓的支换 NEUTRAL'),
]


# 2026-11-02 实测：sidecar 批处理这条路在「自定义优化校准(NCP)」上没走通 ——
# 8 份 sidecar 的内嵌数据各不相同（名字 SILENCE/DENIM/TOY/DREAM/DRAMA），
# NX Studio 却把 8 张全解析成同一个滤镜（面板都写 SILENCE）。见 docs/13 的「实机行为未验证」。
# 所以另出一条「手工可套」的口子：把 8 个探针存成 8 个 NCP，导入 NX Studio 逐个套。
NCP_NAME = {
    'R1_SILENCE_sat-6': 'P1 SIL-6',
    'R2_SILENCE_sat-9': 'P2 SIL-9',
    'R3_DENIM_sat+6':   'P3 DEN+6',
    'R4_TOY_sat+6':     'P4 TOY+6',
    'R5_DENIM_VIVID':   'P5 DEN-VIV',
    'R6_TOY_VIVID':     'P6 TOY-VIV',
    'R7_DREAM_VIVID':   'P7 DRE-VIV',
    'R8_DRAMA_NEUTRAL': 'P8 DRA-NEU',
}


def stamp_name(b, name):
    """写 NCP 的名字卡：第 16–35 字节，20 字节 ASCII，尾部补 0。

    只改名字，不碰其余字节 —— 曲线、滑块、底子编号一律原样。
    """
    raw = name.encode('ascii')
    assert len(raw) <= 20, name
    b[16:36] = raw + b'\x00' * (20 - len(raw))
    return b


def write_ncps(out, tag):
    """把 8 个探针另存为可直接导入的 NCP，并写一张对照表。"""
    d = os.path.join(out, 'ncp')
    os.makedirs(d, exist_ok=True)
    rows = []
    for stem, slot, patch, why in PLAN:
        src = os.path.join(REL, 'PICCON%02d.NCP' % slot)
        b = bytearray(open(src, 'rb').read())
        for off, val in patch.items():
            b[off] = val
        name = NCP_NAME[stem]
        stamp_name(b, name)
        fn = '%s.NCP' % name
        open(os.path.join(d, fn), 'wb').write(bytes(b))
        rows.append((fn, name, slot, patch, why))

    with open(os.path.join(d, 'probe_map.csv'), 'w', encoding='utf-8-sig') as f:
        f.write('file,ncp_name,slot,change,why\n')
        for fn, name, slot, patch, why in rows:
            f.write('%s,%s,%d,%s,%s\n' % (
                fn, name, slot,
                ' '.join('%d:%02X' % (o, v) for o, v in patch.items()), why))

    print('NCP → %s' % d)
    print('%-12s %-4s %-22s %s' % ('文件', '槽', '改动', '验什么'))
    print('-' * 78)
    for fn, name, slot, patch, why in rows:
        print('%-12s %-4d %-22s %s' % (fn, slot,
                                       ' '.join('%d→%02X' % (o, v) for o, v in patch.items()),
                                       why))

    # 手工路线还要配 8 张底片：NX Studio 导出时按 NEF 文件名出图，
    # 所以 NEF 就叫 P1..P8，导出来自然是 P1.JPG …，读数不用猜。
    man = os.path.join(out, 'manual')
    os.makedirs(man, exist_ok=True)
    for i in range(1, len(rows) + 1):
        dst = os.path.join(man, 'P%d.NEF' % i)
        if not os.path.exists(dst):
            shutil.copy2(NEF, dst)
    with open(os.path.join(man, 'probe_map.csv'), 'w', encoding='utf-8-sig') as f:
        f.write('file,ncp_name,slot,change,why\n')
        for i, (fn, name, slot, patch, why) in enumerate(rows, 1):
            f.write('P%d,%s,%d,%s,%s\n' % (i, name, slot,
                                           ' '.join('%d:%02X' % (o, v) for o, v in patch.items()),
                                           why))
    print('\n底片 → %s（P1.NEF … P%d.NEF）' % (man, len(rows)))
    print('导入：NX Studio → 文件 → 导入自定义优化校准 → 从文件导入 → 选这 8 个')
    print('套用：打开 manual\\P1.NEF → 优化校准 选 P1 SIL-6 → 下一张 P2 → … → Ctrl+A 导出')
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(ROOT, '..', '_probe_range'))
    ap.add_argument('--nef', default=NEF)
    ap.add_argument('--ncp-only', action='store_true',
                    help='只生成可导入的 NCP（sidecar 那条路走不通时用）')
    a = ap.parse_args()
    if a.ncp_only:
        write_ncps(os.path.abspath(a.out), None)
        return
    out = os.path.abspath(a.out)
    side = os.path.join(out, 'NKSC_PARAM')
    os.makedirs(side, exist_ok=True)
    for f in os.listdir(side):
        os.remove(os.path.join(side, f))

    txt = S.template_text(TPL)
    print('%-20s %-6s %-24s %s' % ('输出', '槽位', '改动', '验什么'))
    print('-' * 84)
    for stem, slot, patch, why in PLAN:
        src = os.path.join(REL, 'PICCON%02d.NCP' % slot)
        raw = open(src, 'rb').read()
        b = bytearray(raw)
        for off, val in patch.items():
            b[off] = val
        diff = [i for i, v in enumerate(b) if v != raw[i]]
        assert set(diff) <= set(patch), '%s 改到了计划外的字节：%s' % (stem, diff)
        ncp = bytes(b)

        shutil.copy2(a.nef, os.path.join(out, stem + '.NEF'))
        S.write_sidecar(os.path.join(side, stem + '.NEF.nksc'),
                        S.embed_data(txt, ncp, slot02=True))

        raw2, t2 = S.read_sidecar(os.path.join(side, stem + '.NEF.nksc'))
        assert '&lt;userData&gt;' in raw2 and '<userData>' not in raw2
        c = base64.b64decode(re.search(r'<CustomData>(.*?)</CustomData>', t2, re.S)
                             .group(1).strip())
        assert c == ncp, '%s 往返不一致' % stem
        print('%-20s %-6d %-24s %s'
              % (stem, slot,
                 ' '.join('%d:%02X→%02X' % (o, raw[o], v) for o, v in patch.items()),
                 why))

    print()
    print('生成 %d 份（%.0f MB）。导出到 d300/samples/probe_range/ 后：'
          % (len(PLAN), sum(os.path.getsize(os.path.join(out, f))
                            for f in os.listdir(out) if f.upper().endswith('.NEF')) / 1e6))
    print('  python d300/tools/probe_range_read.py --dir d300/samples/probe_range')


if __name__ == '__main__':
    main()
