#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pack_probe_sidecars.py —— 把探针 NCP 塞进调整文件（sidecar），NX Studio 里可以「全选→导出」。

为什么要有这个
--------------
`docs/17` 那 8 个色彩机制探针，正常做法是在 NX Studio 里「导入自定义优化校准 → 逐个套用 → 导出」，
8 次手点。更省事的办法是：同一张 NEF 复制 8 份，每份配一个只差内嵌滤镜的 sidecar，
然后在 NX Studio 里全选、导出一次。

原理（2026-10-31 摸清）
----------------------
NX Studio 把「当前套用的优化校准」**整份嵌在 sidecar 里**，而且是两份：

    <Export><ExportData>…</ExportData><ExportDataSize>867</ExportDataSize></Export>   ← 当前应用态
    <Custom><CustomData>…</CustomData><CustomDataSize>867</CustomDataSize></Custom>   ← 滤镜原始定义

只换其中一份，NX Studio 会**静默回落成 STANDARD**（早期探针失败的真因）。
两份都换才生效。另外 `<PictureControl>` / `<SelectedPictureControl>` /
`SavedPicConProcess` / `SelectedPictureControlVersion2` 四个字段写 `1` 表示"自定义"，
写 `0` 是内置滤镜 —— 这个沿用模板，不动。

    python tools/pack_probe_sidecars.py \\
        --template "…/NKSC_PARAM/DSC_4513.NEF.nksc" \\
        --nef      "…/测试图片/DSC_4484.NEF" \\
        --out      "D:/Documents/Workbuddy/D300/_probe_color"

模板必须是 **NX Studio 自己写的、且当时套的是自定义 NCP** 的 sidecar
（`DSC_4513.NEF.nksc` 就是 —— 里面嵌的是 T02_INVERT）。

产物：

    _probe_color/
    ├── 01_C_CTRL.NEF … 08_M_DENS84.NEF      同一张底片的 8 份拷贝
    └── NKSC_PARAM/
        └── 01_C_CTRL.NEF.nksc …             每份配一个 sidecar

之后：NX Studio 打开 `_probe_color` → Ctrl+A → 导出 → OK。
"""
import argparse
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import sidecar_batch as S                                       # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
PROBE_DIR = os.path.join(ROOT, 'ncp', 'packs', '色彩机制', 'NIKON', 'CUSTOMPC')

NAMES = ['C_CTRL', 'C_TONE_Y', 'C_TONE_B', 'C_FILT_Y',
         'M_CTRL', 'M_SAT_P3', 'M_SAT_M3', 'M_DENS84']


def neutralize(txt):
    """模板是别的照片存出来的，可能带着它的调整量。只清这一项：

    <HueAdjustment>3</HueAdjustment> —— 全局色相转 3 档，会污染"色罩"的测量。
    其余（曝光/对比/色彩平衡/ADL）实测都是中性值 0，不动。
    """
    # 注意：sidecar 里的 XML 是**转义过**的（&lt;HueAdjustment&gt;3&lt;/HueAdjustment&gt;），
    # 直接按 <HueAdjustment> 匹配会一个都命不中 —— 踩过这个坑。
    out, n = re.subn(r'(HueAdjustment(?:&gt;|>))-?\d+', r'\g<1>0', txt)
    return out, n


def build_one(template_text, ncp_bytes):
    """把 NCP 同时写进 ExportData 和 CustomData，其余字段保持模板原样。"""
    txt, _ = S._embed_one(template_text, 'ExportData', ncp_bytes)
    txt, ok = S._embed_one(txt, 'CustomData', ncp_bytes)
    if not ok:
        raise SystemExit('模板里没有 <CustomData> —— 这个模板是用内置滤镜存出来的，不能用。\n'
                         '要用「当时套着自定义 NCP」存出来的 sidecar（例如 DSC_4513.NEF.nksc）。')
    return txt


def verify(path, ncp_bytes):
    """回读校验：两份内嵌数据必须逐字节等于源 NCP。"""
    raw = open(path, encoding='utf-8', errors='replace').read()
    e, c = S.export_data(raw), S.custom_data(raw)
    if e != ncp_bytes:
        return 'ExportData 与源文件不一致'
    if c != ncp_bytes:
        return 'CustomData 与源文件不一致'
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--template', required=True)
    ap.add_argument('--nef', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--only', default='', help='只做前 N 个（例如 3）')
    a = ap.parse_args()

    template = open(a.template, encoding='utf-8', errors='replace').read()
    template, n_hue = neutralize(template)
    print('模板里的全局色相调整已归零（%d 处）\n' % n_hue)
    os.makedirs(os.path.join(a.out, 'NKSC_PARAM'), exist_ok=True)

    n = int(a.only) if a.only else len(NAMES)
    print('%-14s %-10s %s' % ('输出', '滤镜', '校验'))
    print('-' * 60)
    bad = 0
    for i, name in enumerate(NAMES[:n], 1):
        src = os.path.join(PROBE_DIR, 'PICCON%02d.NCP' % i)
        ncp = open(src, 'rb').read()
        stem = '%02d_%s' % (i, name)
        nef_out = os.path.join(a.out, stem + '.NEF')
        sc_out = os.path.join(a.out, 'NKSC_PARAM', stem + '.NEF.nksc')

        shutil.copyfile(a.nef, nef_out)
        open(sc_out, 'w', encoding='utf-8').write(build_one(template, ncp))
        prob = verify(sc_out, ncp)
        bad += 1 if prob else 0
        print('%-14s %-10s %s' % (stem + '.NEF', name, prob or '两份数据一致 ✓'))

    print('\n输出目录：%s' % a.out)
    print('文件数：%d 个 NEF（各 %.1f MB）+ %d 个 sidecar'
          % (n, os.path.getsize(a.nef) / 1048576.0, n))
    if bad:
        return 1
    print('\n接下来：NX Studio 打开这个目录 → 全选 → 导出。')
    print('⚠️ 先点开 05_M_CTRL 看一眼：它必须是**黑白**的。')
    print('   如果是彩色，说明 sidecar 没生效（回落成 STANDARD 了），改用人工逐个套用。')
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(main())
