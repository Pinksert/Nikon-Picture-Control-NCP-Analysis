#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_slider_pack.py —— 滑块标定探针：一档到底值多少？

为什么需要它
------------
`optimize_v2.py` 里把机身那两个滑块写成常量：饱和度每档 ×1.13、色相每档 3.5°。
这两个数是**反推**出来的，不是实测的。2026-11-01 真渲染结果暴露出可疑之处：
26 支里有 16 支我们偏淡、5 支偏浓，而且偏淡的幅度远超「台阶不够细」能解释的范围
（DENIM / TOY / RED / SEPIA 差了 7 个彩度单位）。所以必须把这两个常量钉死。

探针设计（关键：同一张曲线，只改一个字节）
------------------------------------------
全部基于我们 v3 的 STANDARD（PICCON29，base=0x0001，曲线近似恒等），保证
「曲线这一项完全相同」，那么渲染出来的彩度差异就只可能来自滑块本身。

  01–07  sat = −3 … +3        → 直接量出「一档几倍」
  08     hue = +3（sat 0）     → 量出色相一档几度
  09     base 换成 VIVID        → 检验 NX Studio 到底认不认文件里的底子字节
  10–11 单色底子 tint = 0 / +3  → 单色那 7 支的着色深浅，现在普遍偏浅

用法
----
    python tools/probe_slider_pack.py --nef NEF/DSC_3891.NEF --out _probe_slider
然后在 NX Studio 打开 `_probe_slider`，先看 11 张缩略图的名字（应该是
SAT-3 … TINT+3），Ctrl+A 导出（sRGB / 与原片同尺寸或长边 600px 都行），
JPEG 放进 d300/samples/probe_slider/，我这边就能算出真实的每档增益。
"""
import argparse
import os
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sidecar_batch as SB                                  # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
REL = os.path.join(ROOT, 'ncp', 'release', 'NIKON', 'CUSTOMPC')
TEMPLATE = os.path.join(ROOT, '..', 'lightroom', 'NKSC_PARAM', 'DSC_4484.NEF.nksc')

NAME_OFF, NAME_LEN = 16, 20          # 名字在 NCP 里的位置（20 字节，NUL 补齐）
BASE_OFF = 36                        # 底子编号
SL_OFF = 40                          # 8 个滑块字节的起点


def base_ncp(slot=29):
    b = bytearray(open(os.path.join(REL, 'PICCON%02d.NCP' % slot), 'rb').read())
    assert b[4:8] == b'\x00\x00\x00\x01', '不是 NCP 布局'
    return b


def mutate(b, name, base=None, sat=None, hue=None, tint=None, tint_slot=13):
    """在副本上改名 + 改一个字段；tint 走单色底子的那个文件"""
    if tint is not None:
        b = bytearray(open(os.path.join(REL, 'PICCON%02d.NCP' % tint_slot), 'rb').read())
    b = bytearray(b)
    nm = name.encode('ascii')
    assert len(nm) <= NAME_LEN
    b[NAME_OFF:NAME_OFF + NAME_LEN] = nm + b'\x00' * (NAME_LEN - len(nm))
    if base is not None:
        struct.pack_into('>H', b, BASE_OFF, base)
    if sat is not None:
        b[SL_OFF + 3] = (0x80 + sat) & 0xFF
    if hue is not None:
        b[SL_OFF + 4] = (0x80 + hue) & 0xFF
    if tint is not None:
        b[SL_OFF + 7] = (0x80 + tint) & 0xFF
    return bytes(b)


def plan():
    p = []
    for k in range(-3, 4):
        p.append(('SAT%+d' % k, dict(sat=k), 'sat %+d' % k))
    p.append(('HUE+3', dict(hue=3), 'hue +3（sat 0）'))
    p.append(('BASEVIVID', dict(base=0x00C3), '底子改 VIVID（验是否被认）'))
    p.append(('TINT0', dict(tint=0), '单色 tint 0'))
    p.append(('TINTP3', dict(tint=3), '单色 tint +3'))
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--nef', default=os.path.join(ROOT, '..', 'NEF', 'DSC_3891.NEF'))
    ap.add_argument('--out', default='_probe_slider')
    ap.add_argument('--template', default=TEMPLATE)
    a = ap.parse_args()

    if not os.path.exists(a.nef):
        raise SystemExit('源 NEF 不存在：%s' % a.nef)
    raw, _ = SB.read_sidecar(a.template)
    out = os.path.abspath(a.out)
    nd = os.path.join(out, 'NKSC_PARAM')
    os.makedirs(nd, exist_ok=True)

    std = base_ncp()
    rows = []
    for i, (name, kw, desc) in enumerate(plan(), 1):
        filt = mutate(std, name, **kw)
        stem = '%02d_%s' % (i, name)
        nef_dst = os.path.join(out, stem + '.NEF')
        if not os.path.exists(nef_dst):
            shutil.copy2(a.nef, nef_dst)
        txt = SB.embed_data(raw, filt)
        SB.write_sidecar(os.path.join(nd, stem + '.NEF.nksc'), txt)
        sat = filt[SL_OFF + 3] - 0x80 if filt[SL_OFF + 3] != 0xFF else None
        hue = filt[SL_OFF + 4] - 0x80 if filt[SL_OFF + 4] != 0xFF else None
        tint = filt[SL_OFF + 7] - 0x80 if filt[SL_OFF + 7] != 0xFF else None
        rows.append((stem, desc, len(filt), sat, hue, tint,
                     struct.unpack_from('>H', filt, BASE_OFF)[0]))

    print('%d 份探针 -> %s' % (len(rows), out))
    print('%-16s %-24s %5s %5s %5s %5s %7s'
          % ('文件', '说明', '字节', 'sat', 'hue', 'tint', '底子'))
    for stem, desc, ln, sat, hue, tint, bs in rows:
        print('%-16s %-24s %5d %5s %5s %5s  0x%04X'
              % (stem, desc, ln,
                 '—' if sat is None else '%+d' % sat,
                 '—' if hue is None else '%+d' % hue,
                 '—' if tint is None else '%+d' % tint, bs))
    print()
    print('源 NEF：%s（%.1f MB × %d）' % (a.nef, os.path.getsize(a.nef) / 1e6, len(rows)))
    print('下一步：NX Studio 打开 %s → 先看缩略图名字 → Ctrl+A 导出 → '
          'JPEG 放进 d300/samples/probe_slider/' % out)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
