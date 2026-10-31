#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_vs_np3.py —— 把发布包里的 NCP 逐个拆开，和它对应的原始 NP3 并列比对。

为什么要有这一步
----------------
30 对成片对比（audit_release.py）量的是「两张照片差多少像素」，回答不了
「文件里到底丢了什么」。这个脚本反过来：直接读 NP3 的参数卡和 NCP 的 8 个滑块，逐项标出
「一致 / 取整 / 钳位 / 跨代补偿 / 设计上转移给曲线 / 结构上没有这个位置」。

先看清一件事
------------
NP3 的对比度、亮度、饱和度、色相四个卡，在全部 26 支里**几乎全是 0 或「不适用」**。
真正带数值的只有：锐化、清晰度、效果级别、快速锐化、调色强度。
也就是说：**每支滤镜的影调与色彩个性，全都在底子曲线里**（0801–0814、0001、03C2、
00C3、0486、04C7、064D、028E），不在参数里。
这条事实决定了 NCP 的做法：参数能照搬的照搬，搬不了的只能靠一条自定义曲线去反推，
再拿饱和/色相两个滑块去补曲线补不出来的那部分颜色。

判定符号
--------
    =   数值完全一致
    ⊤   超出 NCP 的物理范围，被钳位（例如锐化下限 0）
    ×   跨代补偿：原版这一项是 0/不适用，NCP 必须给一个非零值才能靠近
    C   原版这一项是 0，NCP 写 `01` 表示「交给曲线」（设计上的转移，不是偏差）
    -   两边都是「不适用」
    ?   没有原始 NP3，无法核对

用法
----
    python tools/verify_vs_np3.py
"""
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRESET = os.path.join(os.path.dirname(ROOT), 'presets')     # 原始 NP3 在仓库顶层
if not os.path.isdir(PRESET):
    PRESET = os.path.join(ROOT, 'presets')

NAMES = ['DREAM', 'MORNING', 'POP', 'SUNDAY', 'SOMBER', 'DRAMA', 'SILENCE', 'BLEACH',
         'MELANCHOLIC', 'PURE', 'DENIM', 'TOY', 'SEPIA', 'BLUE', 'RED', 'PINK',
         'CHARCOAL', 'GRAPHITE', 'BINARY', 'CARBON', 'FLAT', 'FLAT_MONOCHROME',
         'DEEPTONE_MONOCHROME', 'RICH_TONE_PORTRAIT', 'FLEXIBLE_COLOR', 'LANDSCAPE',
         'MONOCHROME', 'NEUTRAL', 'STANDARD', 'VIVID']
CN = ['梦幻', '清晨', '流行', '星期天', '低沉', '戏剧', '静寂', '漂白', '忧郁', '纯净',
      '牛仔布', '玩具', '棕褐色', '蓝色', '红色', '粉色', '木炭', '石墨', '双色', '黑碳',
      '平面', '平面单色', '深色调单色', '丰富色调人像', '灵活颜色', '风景', '单色',
      '自然', '标准', '鲜艳']

# NCP 的 8 个滑块：(NCP 下标, 名字, 对应的 NP3 卡号)
SLOTS = [(0, '锐化', 6), (1, '对比度', 8), (2, '亮度', 9), (3, '饱和度', 10),
         (4, '色相', 11), (5, '滤镜效果', 12), (6, '调色', 13), (7, '调色强度', 14)]

# NP3 里 NCP 没有位置可放的卡（只列真的会带数值的）
LOST = {7: '清晰度', 21: '效果级别', 22: '快速锐化'}

BASE_SHORT = {0x0001: '标准', 0x03C2: '中性', 0x00C3: '鲜艳', 0x0486: '人像',
              0x04C7: '风景', 0x064D: '单色', 0x028E: '平面', 0x02CF: '自动'}
for _i in range(1, 21):
    BASE_SHORT[0x0800 + _i] = '创意%02d' % _i


def u32(b, o):
    return struct.unpack_from('>I', b, o)[0]


def parse_tlv(b):
    out, off = {}, 4
    while off + 8 <= len(b):
        t = u32(b, off)
        if t == 0:
            break
        t >>= 8
        ln = u32(b, off + 4)
        out[t] = b[off + 8: off + 8 + ln]
        off += 8 + ln
    return out


def card_val(d):
    """NP3 的 2 字节卡 -> (档数 或 None, 步进码, 原始两字节)"""
    if not d or len(d) < 2:
        return None, None, None
    v, st = d[0], d[1]
    if v == 0xFF:
        return None, st, d[:2]
    if st == 0:
        return float(v - 0x80), st, d[:2]          # 枚举，值就是 0x80+n
    return (v - 0x80) * st / 16.0, st, d[:2]


def read_np3(path):
    c = parse_tlv(open(path, 'rb').read())
    base = struct.unpack('>H', c[3][:2])[0] if 3 in c else None
    vals = {k: card_val(c[k]) for k in range(6, 23) if k in c}
    return dict(base=base, vals=vals)


def read_ncp(slot):
    p = os.path.join(ROOT, 'ncp', 'release', 'NIKON', 'CUSTOMPC', 'PICCON%02d.NCP' % slot)
    b = open(p, 'rb').read()
    return dict(base=struct.unpack_from('>H', b, 36)[0], raw=list(b[40:48]))


def ncp_val(byte, name):
    """NCP 单字节 -> ('auto'|'curve'|None|float)"""
    if byte == 0xFF:
        return None
    if name in ('对比度', '亮度') and byte == 0x01:
        return 'curve'
    if byte == 0x00:
        return 'auto'
    return float(byte - 0x80)


def judge(name, np_v, ncp_v):
    if name in ('对比度', '亮度'):
        if ncp_v == 'curve':
            return 'C', '写 01 = 交给曲线'
        if ncp_v is None:
            return '-', ''
        return '×', '未交曲线'
    if np_v is None and ncp_v is None:
        return '-', ''
    if np_v is None:
        if ncp_v == 'auto':
            return '×', '机身自定'
        return '×', '原版不适用，NCP 取 %+.2f' % ncp_v
    if ncp_v is None:
        return '-', 'NCP 留不适用'
    if ncp_v == 'auto':
        return '×', 'NCP 写自动'
    d = ncp_v - np_v
    if abs(d) < 1e-9:
        return '=', ''
    if name == '锐化' and np_v < 0 and ncp_v == 0:
        return '⊤', 'D300 锐化下限 0（原版 %+.2f）' % np_v
    if abs(d) <= 0.5 + 1e-9:
        return '~', '取整 %+.2f' % d
    return '×', '%+.2f' % d


def gather():
    rows = []
    for slot in range(1, 31):
        nm = NAMES[slot - 1]
        f = os.path.join(PRESET, nm + '.NP3')
        rows.append((slot, nm, read_np3(f) if os.path.exists(f) else None, read_ncp(slot)))
    return rows


def fv(v):
    if v is None:
        return '—'
    if v == 'auto':
        return '自动'
    if v == 'curve':
        return '曲线'
    return '%+.2f' % v


def main():
    rows = gather()
    print('=' * 122)
    print('%-3s %-20s %-11s %-11s %s' % ('槽', '滤镜', 'NP3 底子', 'NCP 底子',
                                        '   '.join('%-9s' % s[1] for s in SLOTS)))
    print('-' * 122)
    stat, miss = {}, []
    for slot, nm, np3, ncp in rows:
        if np3 is None:
            miss.append(nm)
            print('%2d  %-20s %-11s 0x%04X %-4s —— 没有原始 NP3 文件'
                  % (slot, nm, '—', ncp['base'], BASE_SHORT.get(ncp['base'], '')))
            continue
        cells = []
        for pos, name, card in SLOTS:
            npv = np3['vals'].get(card, (None,))[0]
            ncv = ncp_val(ncp['raw'][pos], name)
            sym, _ = judge(name, npv, ncv)
            stat[(name, sym)] = stat.get((name, sym), 0) + 1
            cells.append('%s %s' % (sym, fv(ncv)))
        mark = '' if np3['base'] == ncp['base'] else ' →'
        print('%2d  %-20s %-11s %-11s %s'
              % (slot, nm, '0x%04X %s' % (np3['base'], BASE_SHORT.get(np3['base'], '?')),
                 '0x%04X %s%s' % (ncp['base'], BASE_SHORT.get(ncp['base'], '?'), mark),
                 '  '.join('%-11s' % c for c in cells)))

    print()
    print('符号：= 一致　⊤ 钳位　× 跨代补偿　C 交给曲线　- 两边不适用')
    print('没有原始 NP3 的 %d 支：%s' % (len(miss), '、'.join(miss)))
    print()
    print('%-10s %s' % ('参数', '  '.join('%-5s' % s for s in '= ⊤ × C -'.split())))
    for _, name, _c in SLOTS:
        cnt = [stat.get((name, s), 0) for s in '= ⊤ × C -'.split()]
        if sum(cnt):
            print('%-10s %s' % (name, '  '.join('%-5d' % c for c in cnt)))

    print()
    print('结构性丢失（NCP 里没有这个位置）：')
    agg = {}
    for slot, nm, np3, _ncp in rows:
        if np3 is None:
            continue
        for card, label in LOST.items():
            v, st, raw = np3['vals'].get(card, (None, None, None))
            if v is None:
                continue
            if st == 4:
                agg.setdefault((card, label), []).append('%s%+.2f' % (nm[:7], v))
            else:
                agg.setdefault((card, label), []).append('%s[%02X%02X]' % (nm[:7], raw[0], raw[1]))
    for (card, label), items in sorted(agg.items()):
        print('  卡%-2d %-8s 共 %2d 支：%s' % (card, label, len(items),
                                            '、'.join(items[:8]) + (' …' if len(items) > 8 else '')))


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()
