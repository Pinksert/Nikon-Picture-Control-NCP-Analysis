#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""np3_to_ncp.py —— 把任意 NP3 自动转成近似的 NCP（通用算法 + 网页数据源）。

为什么需要一个「通用」算法
------------------------
D300 不吃 NP3。市面上的 NP3（尼康官方 20 支创意 + 无数第三方）都是
「底子编号 + 22 张 2 字节参数卡」，而 NCP 只认 9 个基础底子 + 8 个滑块 + 一条曲线。

关键事实（本文档的立论基础，`--stats` 可复现）：

    59 份现成 NP3 里，对比度 / 亮度 / 饱和度 / 色相 **全部为 0**。
    会变的只有：底子编号、锐化、清晰度、快速锐化、效果级别。

而清晰度 / 快速锐化 / 效果级别 **NCP 格式里没有对应位置**。
所以「NP3 → NCP」在信息上退化成一句话：

    **转档结果只取决于底子编号。**

于是通用算法就是一张 **底子 → 配方** 表：配方 = (输出底子, 8 个滑块, 257 点曲线)。

配方从哪来
----------
26 支滤镜的配方已经用真渲染拟合好了（`ncp/release`，ΔE00 5.36）。
这 26 支恰好覆盖 **0x0801–0x0814 全部 20 个创意底子** + 6 个基础底子，
所以市面上见得到的 NP3，底子这一格基本都能命中。

三种情况：
    1. 底子在配方表里          → 直接用那张配方（曲线 + 滑块 + 底子）
    2. 底子是 9 个合法基础底子   → 恒等曲线 + 该底子（**几乎无损**，引擎自己干活）
    3. 都没命中（如 0x081F）    → 用编号最接近的配方，标记「估计」

用法
----
    python tools/np3_to_ncp.py --build-web          # 生成网页 + 配方数据
    python tools/np3_to_ncp.py --stats              # 覆盖率自检（扫全部 NP3）
    python tools/np3_to_ncp.py --verify             # 26 支回环比对发布版
    python tools/np3_to_ncp.py -i a.NP3 -o a.NCP    # 单个
    python tools/np3_to_ncp.py --dir in/ --out out/ # 整个目录
"""
import argparse
import base64
import glob
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
PROJ = os.path.normpath(os.path.join(ROOT, '..'))
sys.path.insert(0, os.path.join(PROJ, 'np3tool'))

import np3core as C                                            # noqa: E402

RELEASE = os.path.join(ROOT, 'ncp', 'release', 'NIKON', 'CUSTOMPC')
NP3_DIR = os.path.join(PROJ, '_filters_np3')
WEB = os.path.join(ROOT, 'web', 'np3-to-ncp')

# NCP 里被允许写进去的底子（Rome2.dll 注册表 kind=1，见 docs/18）
LEGAL = [0x0001, 0x00C3, 0x03C2, 0x0486, 0x04C7, 0x064D, 0x0014, 0x03D5, 0x00D6]
MONO_BASES = {0x064D}

NAME_OFF, BASE_OFF, SLIDER_OFF = 16, 36, 40
CURVE_OFF = 56 + C.HDR_LEN                                      # 记录 2 的曲线起点


# ---------------------------------------------------------------- 配方表

def build_priors():
    """扫 26 支的 NP3 与发布版 NCP，凑成 底子 → 配方。"""
    table = {}
    for p in sorted(glob.glob(os.path.join(NP3_DIR, '*.NP3'))):
        slot = int(os.path.basename(p)[-6:-4])
        ncp = os.path.join(RELEASE, 'PICCON%02d.NCP' % slot)
        if not os.path.exists(ncp):
            continue
        np3 = C.parse_np(open(p, 'rb').read())
        raw = open(ncp, 'rb').read()
        d = C.read_ncp(raw)
        assert raw[:4] == b'NCP\0' and len(raw) == 638, ncp
        table[np3['base']] = dict(
            slot=slot, np3_name=np3['name'], base=d['base'],
            sliders=d['sliders'], ncp=raw)
    return table


IDENTITY = None


def identity_template():
    """恒等曲线 + 底子 0001 + 默认滑块，用来给「合法底子」当底版。"""
    global IDENTITY
    if IDENTITY is None:
        import numpy as np
        IDENTITY = C.make_ncp('NP3 CONVERT', 0x0001,
                              C.sliders_for(False), np.arange(256, dtype=np.float64))
    return IDENTITY


def nearest_base(base, table):
    """没命中时按编号距离挑最近配方；创意组优先在 0x08xx 里挑。"""
    same = [b for b in table if (b >= 0x0800) == (base >= 0x0800)]
    pool = same or list(table)
    return min(pool, key=lambda b: (abs(b - base), b))


# ---------------------------------------------------------------- 转换

def convert(raw_np3, table=None):
    """NP3 字节 → (NCP 字节, 报告 dict)。"""
    table = table if table is not None else build_priors()
    p = C.parse_np(raw_np3)
    base = p['base']
    name = (p['name'] or 'CONVERTED').upper().encode('ascii', 'replace')[:20]

    if base in table:
        rec = table[base]
        out = bytearray(rec['ncp'])
        out[NAME_OFF:NAME_OFF + 20] = name.ljust(20, b'\x00')
        how = '配方'
        note = '底子 0x%04X 有实测配方（槽 %d / %s）' % (base, rec['slot'], rec['np3_name'])
        base_out = rec['base']
    elif base in LEGAL:
        out = bytearray(identity_template())
        out[NAME_OFF:NAME_OFF + 20] = name.ljust(20, b'\x00')
        out[BASE_OFF:BASE_OFF + 2] = struct.pack('>H', base)
        out[SLIDER_OFF:SLIDER_OFF + 8] = bytes(_sliders_from_np3(p, base))
        how = '直搬'
        note = '底子 0x%04X 是 NCP 认可的 9 个之一，恒等曲线，几乎无损' % base
        base_out = base
    else:
        nb = nearest_base(base, table)
        rec = table[nb]
        out = bytearray(rec['ncp'])
        out[NAME_OFF:NAME_OFF + 20] = name.ljust(20, b'\x00')
        how = '估计'
        note = '底子 0x%04X 没有配方，借用最接近的 0x%04X（%s）' % (base, nb, rec['np3_name'])
        base_out = rec['base']

    return bytes(out), dict(name=p['name'], base_in=base, base_out=base_out,
                            how=how, note=note, params=p['params'])


def _sliders_from_np3(p, base):
    """合法底子走直搬时，按 NP3 的参数拼 8 个滑块。"""
    v = p['params']
    sharp = v.get('sharp')
    sb = 0x80 + int(round(sharp)) if sharp not in (None,) else 0x80
    sb = max(0x00, min(0xFF, sb))
    mono = base in MONO_BASES
    sat = _clamp_slider(v.get('saturation'))
    hue = _clamp_slider(v.get('hue'))
    tone = v.get('tone')
    strength = v.get('tone_strength')
    if mono:
        tb = C.SL_ZERO + int(tone) if tone not in (None, 0) else C.SL_NA
        kb = C.SL_NA
        if strength not in (None, 0):
            kb = C.SL_ZERO + int(round(min(1.0, max(0.0, strength / 4.0)) * 4))
        return [sb, C.SL_CURVE, C.SL_CURVE, C.SL_NA, C.SL_NA, C.SL_NA, tb, kb]
    return [sb, C.SL_CURVE, C.SL_CURVE,
            C.SL_ZERO + sat if sat else C.SL_ZERO,
            C.SL_ZERO + hue if hue else C.SL_ZERO,
            C.SL_NA, C.SL_NA, C.SL_NA]


def _clamp_slider(x, lim=3):
    if x in (None, 0, 0.0):
        return 0
    return max(-lim, min(lim, int(round(x))))


# ---------------------------------------------------------------- 自检

def cmd_stats(table):
    files = sorted(glob.glob(os.path.join(PROJ, '**', '*.NP3'), recursive=True))
    hit = {}
    for p in files:
        try:
            d = C.parse_np(open(p, 'rb').read())
        except Exception:
            continue
        _, rep = convert(open(p, 'rb').read(), table)
        hit.setdefault(rep['how'], []).append(rep['base_in'])
    print('扫到 %d 份 NP3' % len(files))
    for how in ('配方', '直搬', '估计'):
        v = hit.get(how, [])
        bases = sorted(set(v))
        print('  %-4s %2d 份   底子 %s' % (how, len(v), ' '.join('%04X' % b for b in bases)))
    unseen = sorted({b for v in hit.values() for b in v} - set(table) - set(LEGAL))
    print('配方表覆盖创意底子：%s' % ' '.join('%04X' % b for b in sorted(table) if b >= 0x0800))
    print('既非配方又非合法：%s' % (' '.join('%04X' % b for b in unseen) or '无'))


def cmd_verify(table):
    print('%-4s %-12s %-7s %-5s %s' % ('槽', '名字', '底子', '模式', '回环比对'))
    bad = 0
    for p in sorted(glob.glob(os.path.join(NP3_DIR, '*.NP3'))):
        slot = int(os.path.basename(p)[-6:-4])
        ref = open(os.path.join(RELEASE, 'PICCON%02d.NCP' % slot), 'rb').read()
        out, rep = convert(open(p, 'rb').read(), table)
        diff = sum(1 for a, b in zip(out, ref) if a != b)
        # 名字可能与发布版不同，单独统计
        ndiff = sum(1 for a, b in zip(out[NAME_OFF:NAME_OFF + 20],
                                      ref[NAME_OFF:NAME_OFF + 20]) if a != b)
        ok = '完全一致' if diff == 0 else ('差 %d 字节（其中名字 %d）' % (diff, ndiff))
        if diff:
            bad += 1
        print('%-4d %-12s 0x%04X  %-4s %s' % (slot, rep['name'], rep['base_in'], rep['how'], ok))
    print('\n有差异 %d / %d' % (bad, len(glob.glob(os.path.join(NP3_DIR, '*.NP3')))))
    print('（配方模式本应逐字节等于发布版；名字差异来自 NP3 改名，属正常）')


# ---------------------------------------------------------------- 网页

def build_web(table):
    os.makedirs(WEB, exist_ok=True)
    recipes = {}
    for base, rec in table.items():
        recipes['%04X' % base] = dict(
            ncp=base64.b64encode(rec['ncp']).decode('ascii'),
            slot=rec['slot'], src=rec['np3_name'], base_out='%04X' % rec['base'],
            sliders=' '.join('%02X' % b for b in rec['sliders']))
    data = dict(
        legal=['%04X' % b for b in LEGAL],
        identity=base64.b64encode(identity_template()).decode('ascii'),
        recipes=recipes,
    )
    tpl = os.path.join(WEB, 'template.html')
    if not os.path.exists(tpl):
        raise SystemExit('缺模板 %s' % tpl)
    html = open(tpl, encoding='utf-8').read()
    blob = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    html = html.replace('/*__PRIORS__*/null', blob)
    out = os.path.join(WEB, 'index.html')
    open(out, 'w', encoding='utf-8').write(html)
    print('网页 -> %s  (%.1f KB, 配方 %d 条)' % (out, os.path.getsize(out) / 1024.0, len(recipes)))


# ---------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-i', '--in', dest='inp')
    ap.add_argument('-o', '--out', dest='out')
    ap.add_argument('--dir', dest='indir')
    ap.add_argument('--outdir', dest='outdir', default='ncp_converted')
    ap.add_argument('--stats', action='store_true')
    ap.add_argument('--verify', action='store_true')
    ap.add_argument('--build-web', action='store_true')
    a = ap.parse_args()

    table = build_priors()
    if a.stats:
        cmd_stats(table)
    if a.verify:
        cmd_verify(table)
    if a.build_web:
        build_web(table)
    if a.inp:
        out, rep = convert(open(a.inp, 'rb').read(), table)
        dst = a.out or os.path.splitext(a.inp)[0] + '.NCP'
        open(dst, 'wb').write(out)
        print('%s -> %s\n  %s：%s' % (a.inp, dst, rep['how'], rep['note']))
    if a.indir:
        os.makedirs(a.outdir, exist_ok=True)
        n = 0
        for p in sorted(glob.glob(os.path.join(a.indir, '*.NP3'))):
            out, rep = convert(open(p, 'rb').read(), table)
            dst = os.path.join(a.outdir, os.path.splitext(os.path.basename(p))[0] + '.NCP')
            open(dst, 'wb').write(out)
            print('%-14s 0x%04X  %-4s %s' % (rep['name'], rep['base_in'], rep['how'], rep['note']))
            n += 1
        print('\n共 %d 份 -> %s' % (n, a.outdir))
    if not any([a.stats, a.verify, a.build_web, a.inp, a.indir]):
        ap.print_help()


if __name__ == '__main__':
    main()
