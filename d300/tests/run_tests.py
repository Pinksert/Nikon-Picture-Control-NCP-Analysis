#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_tests.py —— 把「花了三轮真机才逼出来的那几条不变量」钉成测试。

为什么要这一份：这个仓库的结论几乎全是"某个字节写错了，整条路就废掉"。
被踩过的坑都有明确的代价：

    滑块 41/42 写成 80 80  → 578 字节曲线被机身**静默丢弃**（白折腾三轮）
    单色底子写 0x0004      → 22 个文件在机内列表里根本不出现
    彩色底子配 FF FF       → 同样不出现

这些都不是单元测试能"发明"出来的，只能从实测里抄下来。这里把它们抄成断言，
以后改生成器若不小心改回去，`python tests/run_tests.py` 会立刻红。

    python tests/run_tests.py          # 全跑
    python tests/run_tests.py -v       # 每项都打印

只依赖 numpy；没有 pytest 也能跑。
"""
import csv
import glob
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
TOOLS = os.path.join(ROOT, 'tools')
sys.path.insert(0, TOOLS)

REL_DIR = os.path.join(ROOT, 'ncp', 'release', 'NIKON', 'CUSTOMPC')

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


# ------------------------------------------------------------------ 工具

def parse_ncp(path):
    """独立解析器。故意不 import 生产代码 —— 测试要和被测代码各写一遍才有意义。"""
    raw = open(path, 'rb').read()
    if raw[:4] != b'NCP\x00':
        raise ValueError('%s: 魔数不是 NCP\\0' % path)
    recs, off = {}, 4
    while off + 8 <= len(raw):
        t, ln = struct.unpack_from('>II', raw, off)
        recs[t] = raw[off + 8: off + 8 + ln]
        if t == 0:
            break
        off += 8 + ln
    return raw, recs


# ------------------------------------------------------------------ 用例

@case
def test_release_layout():
    """发布包 30 个文件的结构不变量（全部来自真机实测）"""
    bad = []
    files = sorted(glob.glob(os.path.join(REL_DIR, '*.NCP')))
    if len(files) != 30:
        bad.append('发布包应有 30 个文件，实际 %d' % len(files))

    seen = {}
    for fn in files:
        tag = os.path.basename(fn)
        raw, recs = parse_ncp(fn)
        if len(raw) != 638:
            bad.append('%s: 长度 %d，带曲线的必须是 638' % (tag, len(raw)))
            continue
        d1 = recs.get(1, b'')
        if len(d1) != 36:
            bad.append('%s: 记录 1 长度 %d ≠ 36' % (tag, len(d1)))
            continue
        if d1[:4] != b'0100':
            bad.append('%s: 版本串不是 0100' % tag)

        name = d1[4:24].rstrip(b'\x00')
        if not name:
            bad.append('%s: 名字为空' % tag)
        elif any(not (0x20 <= b <= 0x7E) for b in name):
            bad.append('%s: 名字含非 ASCII（机内显示乱码）' % tag)
        elif name != name.upper():
            bad.append('%s: 名字不是大写（尼康自己的文件都是大写）' % tag)
        if name in seen:
            bad.append('%s: 名字与 %s 重复' % (tag, seen[name]))
        seen[name] = tag

        base = struct.unpack_from('>H', d1, 24)[0]
        sl = list(d1[28:36])
        if base not in (0x0001, 0x064D):
            bad.append('%s: 底子 0x%04X 不在已证可用的两个码里' % (tag, base))
        # ★ 曲线开关：41/42 必须 01 01；写 80 80 会让 578 字节曲线被静默丢弃
        if sl[1:3] != [0x01, 0x01]:
            bad.append('%s: 滑块 41/42 = %02X %02X，曲线会被机身丢弃（必须 01 01）'
                       % (tag, sl[1], sl[2]))
        if base == 0x064D:
            if sl[3:5] != [0xFF, 0xFF]:
                bad.append('%s: 单色底子但饱和度/色相不是 FF FF' % tag)
        else:
            if sl[5:7] != [0xFF, 0xFF]:
                bad.append('%s: 彩色底子但滤镜/调色不是 FF FF' % tag)
        if not (0x7D <= sl[3] <= 0x83 or sl[3] == 0xFF):
            bad.append('%s: 饱和度档 %02X 超出 −3…+3 / 不适用' % (tag, sl[3]))
        if not (0x7D <= sl[4] <= 0x83 or sl[4] == 0xFF):
            bad.append('%s: 色相档 %02X 超出 −3…+3 / 不适用' % (tag, sl[4]))

        d2 = recs.get(2, b'')
        if len(d2) != 578:
            bad.append('%s: 记录 2 长度 %d ≠ 578' % (tag, len(d2)))
            continue
        lut = np.frombuffer(raw, dtype='>u2', count=257, offset=120)
        if lut.min() < 0 or lut.max() > 32767:
            bad.append('%s: LUT 超出 15 位量程' % tag)
        if raw[634:].hex() != '00000000':
            bad.append('%s: 文件尾不是 4 个零字节' % tag)
    return bad


@case
def test_slider_codec():
    """滑块编码：值 v 写成 0x80+v，越界要钳到档位边界"""
    import ncp_d300 as N
    bad = []
    for kind in N.RANGE:
        lo, hi = N.RANGE[kind]
        for v in range(lo, hi + 1):
            got = N.slider_byte(v, kind)
            if got != (0x80 + v) & 0xFF:
                bad.append('%s: %d 编成 %02X' % (kind, v, got))
        if N.slider_byte(hi + 3, kind) != 0x80 + hi:
            bad.append('%s: 上越界没有钳位' % kind)
        if N.slider_byte(lo - 3, kind) != 0x80 + lo:
            bad.append('%s: 下越界没有钳位' % kind)
    return bad


@case
def test_engine_transform():
    """H 与 H⁻¹ 互逆；预补偿后引擎执行 C(H(x)) 应还原目标曲线"""
    import compensate as C
    bad = []
    x = np.arange(256, dtype=float)
    back = C.H_inv(C.H(x))
    e = float(np.abs(back - x).max())
    if e > 1.5:
        bad.append('H⁻¹(H(x)) 最大偏差 %.2f 级（应 < 1.5）' % e)

    # 中间调 −18 是 H 的实测特征，写死一个区间当护栏
    mid = float(C.H(np.array([128.0]))[0]) - 128.0
    if not (-20.0 < mid < -16.0):
        bad.append('H(128) 位移 %.2f，与实测「中间调 −18」不符' % mid)

    target = np.arange(257, dtype=float) / 256.0 * 32767
    _, out, tgt = C.simulate(target, 32767)
    r = float(np.abs(out - tgt).max())
    if r > 2.0:
        bad.append('恒等曲线预补偿残差 %.2f 级（应 < 2.0）' % r)
    return bad


@case
def test_golden_metrics():
    """版本回归护栏：v1 7.94 → v3 5.98，25 支变好、0 支变差"""
    bad = []
    path = os.path.join(ROOT, 'samples', 'metrics.csv')
    rows = list(csv.DictReader(open(path, encoding='utf-8-sig')))
    if len(rows) != 30:
        return ['metrics.csv 应 30 行，实际 %d' % len(rows)]
    v1 = np.array([float(r['e_v1']) for r in rows])
    v2 = np.array([float(r['e_v2']) for r in rows])
    v3 = np.array([float(r['e_v3']) for r in rows])
    if abs(v1.mean() - 7.94) > 0.03:
        bad.append('v1 平均 %.2f，文档写 7.94' % v1.mean())
    if abs(v2.mean() - 6.17) > 0.03:
        bad.append('v2 平均 %.2f，文档写 6.17' % v2.mean())
    if abs(v3.mean() - 5.98) > 0.03:
        bad.append('v3 平均 %.2f，文档写 5.98' % v3.mean())
    better = int((v3 < v1 - 0.05).sum())
    worse = int((v3 > v1 + 0.05).sum())
    if better != 25 or worse != 0:
        bad.append('v1 → v3 变好 %d 支 / 变差 %d 支，文档写 25 / 0' % (better, worse))
    return bad


@case
def test_filter_character():
    """性格表：30 行；STANDARD 相对自己必须全零；单色支彩度必须是 0"""
    bad = []
    path = os.path.join(ROOT, 'samples', 'filter_character.csv')
    rows = {int(r['slot']): r for r in csv.DictReader(open(path, encoding='utf-8-sig'))}
    if len(rows) != 30:
        return ['filter_character.csv 应 30 行，实际 %d' % len(rows)]
    std = rows[29]
    for k in ('dL', 'dL_shadow', 'dL_mid', 'dL_high', 'cast_rb', 'cast_gb'):
        if abs(float(std[k])) > 1e-6:
            bad.append('STANDARD 的 %s = %s，应为 0' % (k, std[k]))
    if abs(float(std['chroma_ratio']) - 1.0) > 1e-6:
        bad.append('STANDARD 彩度比 %.3f，应为 1.000' % float(std['chroma_ratio']))
    # 13–16 是「单色底 + 着色」，成片是双色调、彩度不为零，不在本用例范围
    for s in (17, 18, 19, 20, 22, 23, 27):
        r = rows[s]
        if r['mono'] != 'True':
            bad.append('槽 %d 应判为单色' % s)
        if float(r['chroma_ratio']) != 0.0:
            bad.append('槽 %d 彩度比 %.3f，单色应为 0' % (s, float(r['chroma_ratio'])))
    return bad


@case
def test_sample_sets():
    """三套样片目录必须各有 30 张，且槽号连续"""
    bad = []
    for sub in ('workshop', 'd300ncp', 'compare', 'compare_v3'):
        d = os.path.join(ROOT, 'samples', sub)
        fs = sorted(glob.glob(os.path.join(d, '*.jpg')))
        if len(fs) != 30:
            bad.append('samples/%s 有 %d 张，应为 30' % (sub, len(fs)))
            continue
        slots = [int(os.path.basename(f)[:2]) for f in fs]
        if slots != list(range(1, 31)):
            bad.append('samples/%s 槽号不连续：%s' % (sub, slots))
    return bad


@case
def test_probe_packs():
    """两个卡包：各 8 个文件、638 字节、曲线开关 01 01；色彩机制包的字节组合要对得上"""
    bad = []
    packs = {
        '底子探针': {'bases': [0x0001, 0x03C2, 0x00C3, 0x064D, 0x0801, 0x0808, 0x080B, 0x0813]},
        '色彩机制': {'bases': [0x0001] * 4 + [0x064D] * 4},
    }
    for name, cfg in packs.items():
        d = os.path.join(ROOT, 'ncp', 'packs', name, 'NIKON', 'CUSTOMPC')
        fs = sorted(glob.glob(os.path.join(d, '*.NCP')))
        if len(fs) != 8:
            bad.append('%s: %d 个文件，应为 8' % (name, len(fs)))
            continue
        for i, fn in enumerate(fs):
            raw, recs = parse_ncp(fn)
            tag = '%s/%s' % (name, os.path.basename(fn))
            if len(raw) != 638:
                bad.append('%s: 长度 %d' % (tag, len(raw)))
                continue
            sl = list(recs[1][28:36])
            base = struct.unpack_from('>H', recs[1], 24)[0]
            if base != cfg['bases'][i]:
                bad.append('%s: 底子 0x%04X，应为 0x%04X' % (tag, base, cfg['bases'][i]))
            if sl[1:3] != [0x01, 0x01]:
                bad.append('%s: 41/42 = %02X %02X，曲线会被丢弃' % (tag, sl[1], sl[2]))
    # 色彩机制包：01 必须是"45–47 全 FF"的基准，02 必须真的写上了调色字节
    d = os.path.join(ROOT, 'ncp', 'packs', '色彩机制', 'NIKON', 'CUSTOMPC')
    _, r1 = parse_ncp(os.path.join(d, 'PICCON01.NCP'))
    _, r2 = parse_ncp(os.path.join(d, 'PICCON02.NCP'))
    if list(r1[1][28:36])[5:] != [0xFF, 0xFF, 0xFF]:
        bad.append('色彩机制/01 应是 45–47 全 FF 的彩色基准')
    if list(r2[1][28:36])[5:] == [0xFF, 0xFF, 0xFF]:
        bad.append('色彩机制/02 没写调色字节，等于和 01 重复')
    return bad


@case
def test_presets_parse():
    """把 presets/ 里每个 NP2/NP3 都解析一遍，名字/底子/参数不能崩"""
    import ncp_d300 as N
    bad = []
    fs = sorted(glob.glob(os.path.join(ROOT, '..', 'presets', '*.NP[23]')))
    if len(fs) < 26:
        return ['presets/ 只有 %d 个 NP2/NP3，应 ≥ 26' % len(fs)]
    for fn in fs:
        tag = os.path.basename(fn)
        name, base, vals = N.preset_from_np(open(fn, 'rb').read())
        if not name or name != name.upper():
            bad.append('%s: 名字 "%s" 异常' % (tag, name))
        if base == 0:
            bad.append('%s: 底子编号为 0' % tag)
        for k in ('sharp', 'contrast', 'brightness', 'saturation', 'hue',
                  'tone', 'tone_strength'):
            if k not in vals:
                bad.append('%s: 缺参数 %s' % (tag, k))
    return bad


@case
def test_release_readme_numbers():
    """发布包自带的 README 必须写对版本号与平均差（曾经停在第二版忘了改）"""
    bad = []
    p = os.path.join(ROOT, 'ncp', 'release', 'README.md')
    txt = open(p, encoding='utf-8').read()
    if '第三版' not in txt:
        bad.append('ncp/release/README.md 没有写「第三版」')
    if '5.98' not in txt:
        bad.append('ncp/release/README.md 没写 5.98')
    if '6.17' in txt and '7.94' in txt and '5.98' not in txt:
        bad.append('ncp/release/README.md 还在写第二版的 6.17')
    return bad


# ------------------------------------------------------------------ 跑

def main():
    verbose = '-v' in sys.argv
    fails = 0
    for fn in CASES:
        name = fn.__name__
        try:
            bad = fn() or []
        except Exception as e:                       # noqa: BLE001
            bad = ['异常：%s: %s' % (type(e).__name__, e)]
        if bad:
            fails += 1
            print('FAIL  %s' % name)
            for b in bad:
                print('        - %s' % b)
        elif verbose:
            print('ok    %s  %s' % (name, (fn.__doc__ or '').strip().splitlines()[0]))
    print('\n%d 项用例，%d 项失败' % (len(CASES), fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(main())
