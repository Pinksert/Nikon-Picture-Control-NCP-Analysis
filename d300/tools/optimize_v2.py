#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""optimize_v2.py —— 用 30 对成片反推「还能救的那部分」，产出第二版发布包。

为什么要有这一步
----------------
第一版（`ncp/release_v1/`）只做了影调：八个滑块里对比度/亮度交给曲线，
**饱和度与色相一律写 0x80（数值 0）= 没有动**。而 `samples/` 的 30 对成片显示，
彩色那几支的差距主要落在「彩度比 0.71–4.35×」和「偏色 −26…+32」两列上 ——
也就是颜色根本没调。这一版把这两个滑块真正用起来。

模型（怎么从已有成片预测改完之后的成片）
--------------------------------------
机身输出 O 满足  O = T(x) 的亮度映射（T = 该文件的有效曲线，x = 底子渲染的亮度），
彩度在曲线里不变（曲线只改亮度，彩度乘子由饱和度滑块给，色相由色相滑块转）。
所以对同一个 x：
    L_new = T_new(x),        彩度_new = 彩度_O × 1.13^n,   色相_new = 色相_O − 3.5°×m
于是只要能反解 x = T⁻¹(L_O)，就能预测任意 (T_new, n, m) 的结果，不用重新渲染。

三个参数的来源
--------------
· 饱和度每档 ×1.13     ←  `ncp jpg/` 里 SAT±1 标定图实测
                             （SAT-1 → SD 一档 1.1274；SAT-1 → SAT+1 两档 1.1351/档）
· 色相每档 3.5°        ←  同一组 HUE±1 标定图实测（两档 7.00°）
· 影调 T_new           ←  直接从中性像素的 (x, L_参考) 拟合，并限制相对现曲线的偏差

用法
----
    python optimize_v2.py                 # 评估 + 覆盖生成 ncp/release/（30 个）
    python optimize_v2.py --dry           # 只评估，不写文件
"""
import os
import struct
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from compensate import H, precompensate                 # noqa: E402
from ncp_d300 import OUT_MAX, build_ncp, verify_one     # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
SAMP = os.path.join(ROOT, 'samples')
REL = os.path.join(ROOT, 'ncp', 'release_v1', 'NIKON', 'CUSTOMPC')   # 优化起点 = 第一版
OUT = os.path.join(ROOT, 'ncp', 'release', 'NIKON', 'CUSTOMPC')      # 产物 = 正式发布包

SAT_STEP = 1.13          # 每档彩度倍率
HUE_STEP = 3.5           # 每档色相（度，负号见 rot_hue 约定）

NAMES = ['DREAM', 'MORNING', 'POP', 'SUNDAY', 'SOMBER', 'DRAMA', 'SILENCE', 'BLEACH',
         'MELANCHOLIC', 'PURE', 'DENIM', 'TOY', 'SEPIA', 'BLUE', 'RED', 'PINK',
         'CHARCOAL', 'GRAPHITE', 'BINARY', 'CARBON', 'FLAT', 'FLAT_MONOCHROME',
         'DEEPTONE_MONOCHROME', 'RICH_TONE_PORTRAIT', 'FLEXIBLE_COLOR', 'LANDSCAPE',
         'MONOCHROME', 'NEUTRAL', 'STANDARD', 'VIVID']
CN = ['梦幻', '清晨', '流行', '星期天', '低沉', '戏剧', '静寂', '漂白', '忧郁', '纯净',
      '牛仔布', '玩具', '棕褐色', '蓝色', '红色', '粉色', '木炭', '石墨', '双色', '黑碳',
      '平面', '平面单色', '深色调单色', '丰富色调人像', '灵活颜色', '风景', '单色',
      '自然', '标准', '鲜艳']
MONO = {13, 14, 15, 16, 17, 18, 19, 20, 22, 23, 27}
TONED = {13, 14, 15, 16}
PURE_MONO = MONO - TONED

SIZE = 420               # 搜索用分辨率（600px 样片再缩，快 2 倍）
MIN_GAIN = 0.25          # 收益小于这个数就不动，避免为噪声改文件

# 底子码：只允许 0x0001（彩色）与 0x064D（单色）。
# 注意 0x064D 是「新系统」编号，看着像错，其实是实拍跑通的那个：
# docs/07-camera-verification.md 第 63 行那条「0x0004 不出现」的结论，是在八个滑块
# 还写成 80 80（对比度/亮度没交出去）的轮次里得到的，不能单独归因到底子码；
# 而 0x064D 是在改成 01 01 之后用 29 张实拍验过的。所以这里保持原样，不做换算。
OK_BASE = (0x0001, 0x064D)



# ---------------------------------------------------------------- 图像

_CACHE = {}


def load(kind, slot, size=SIZE):
    key = (kind, slot, size)
    if key in _CACHE:
        return _CACHE[key]
    p = os.path.join(SAMP, kind, '%02d_%s.jpg' % (slot, NAMES[slot - 1]))
    im = Image.open(p).convert('RGB')
    if size:
        r = size / max(im.size)
        im = im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))), Image.LANCZOS)
    a = np.asarray(im, dtype=np.float64)
    _CACHE[key] = a
    return a


def lum(a):
    return 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]


def rot_hue(c, deg):
    """在 (R−G, B−G) 平面上旋转色相角。正角 = 画面整体色相往「红→黄」方向转。"""
    t = np.radians(deg)
    cg = c[..., 1]
    u, v = c[..., 0] - cg, c[..., 2] - cg
    cu = u * np.cos(t) - v * np.sin(t)
    cv = u * np.sin(t) + v * np.cos(t)
    out = c.copy()
    out[..., 0] = cg + cu
    out[..., 2] = cg + cv
    return out


def predict(O, f, s=1.0, deg=0.0, k_tint=1.0):
    """f 是定义在「机身输出亮度」上的映射：L_new = f(L_O)"""
    L = lum(O)
    Ln = np.interp(np.clip(L, 0, 255), np.arange(256.), f)
    c = (O - L[..., None]) * k_tint
    if abs(s - 1.0) > 1e-9:
        c = c * s
    if abs(deg) > 1e-9:
        c = rot_hue(c, deg)
    return np.clip(Ln[..., None] + c, 0, 255)


# ---------------------------------------------------------------- 曲线

def read_lut(slot, d=REL):
    b = open(os.path.join(d, 'PICCON%02d.NCP' % slot), 'rb').read()
    return np.array(struct.unpack_from('>257H', b, 120), dtype=float) / OUT_MAX * 255.0


def lut_to_curve(c):
    """文件里存的是 C = T∘H⁻¹，还原有效曲线 T(x) = C(H(x))"""
    return np.interp(H(np.arange(256, dtype=float)), np.arange(257, dtype=float), c)


def target_curve(slot):
    return lut_to_curve(read_lut(slot))



def inv_curve(t):
    keep = np.r_[True, np.diff(t) > 1e-9]
    return lambda v: np.interp(np.clip(v, 0, 255), t[keep], np.arange(256, dtype=float)[keep])


def fit_map(O, R, neutral_only, clamp=None, nb=44):
    """拟合 f：机身输出亮度 -> 参考亮度（257 点，单调）

    中性像素口径：只统计「近乎无色」的像素。彩色预设的差距里有很大一块是色罩，
    用全幅像素拟合会把色罩当成影调偏差吃进曲线，实测 MORNING 会从 11.8 反而涨到 12.5。
    clamp：相对「恒等」的最大偏差，防止为了迁就一张照片把曲线拉变形。
    """
    Lo, Lr = lum(O), lum(R)
    if neutral_only:
        m = (O.max(2) - O.min(2)) < 12
        if m.sum() < 8000:
            m = np.ones(Lo.shape, bool)
        Lo, Lr = Lo[m], Lr[m]
    oi = np.clip(np.round(Lo), 0, 255).astype(np.int32).ravel()
    ta = Lr.ravel()
    edges = np.linspace(0, 256, nb + 1)
    xs, ys = [], []
    for i in range(nb):
        s = (oi >= edges[i]) & (oi < edges[i + 1])
        if s.sum() < 250:
            continue
        xs.append((edges[i] + edges[i + 1]) / 2 - 0.5)
        ys.append(float(np.median(ta[s])))
    if len(xs) < 5:
        return np.arange(256, dtype=float)
    xs, ys = np.array(xs), np.array(ys)
    ys = np.convolve(np.pad(ys, 1, mode='edge'), [0.25, 0.5, 0.25], 'valid')
    ys = np.maximum.accumulate(ys)

    # 端点外推。最高／最低那几档常常凑不满 250 个像素、直接不参与拟合，
    # 若任由 np.interp 平推，顶上会压出一整段死平（实测 DRAMA 曾把 185 以上全压成 254，
    # 相当于丢掉两档高光）。这里按首／末两个有效档的斜率外推，保持曲线还在往上走。
    if xs[0] > 0 and len(xs) > 1:
        s0 = (ys[1] - ys[0]) / max(xs[1] - xs[0], 1e-6)
        xs = np.r_[0.0, xs]
        ys = np.r_[max(0.0, min(ys[0] - s0 * xs[1], ys[0])), ys]
    if xs[-1] < 255 and len(xs) > 1:
        s1 = (ys[-1] - ys[-2]) / max(xs[-1] - xs[-2], 1e-6)
        xs = np.r_[xs, 255.0]
        ys = np.r_[ys, min(255.0, max(ys[-1] + s1 * (255.0 - xs[-2]), ys[-1]))]
    f = np.interp(np.arange(256, dtype=float), xs, ys)

    if clamp is not None:
        d = np.clip(f - np.arange(256.0), -clamp, clamp)
        f = np.clip(np.maximum.accumulate(np.arange(256.0) + d), 0, 255)
    return f


def compose(Tcur, f):
    """把「输出域修正 f」折进曲线：T_new(x) = f(Tcur(x))"""
    x = np.arange(256, dtype=float)
    return np.clip(np.interp(Tcur, x, f), 0, 255)


# ---------------------------------------------------------------- 主流程

ID = np.arange(256, dtype=float)


def _fit(slot, O, R, clamp=None):
    """按预设类型选拟合口径；彩色只在中性像素上拟合，避免把色罩当影调吃进去"""
    if slot in MONO:
        return fit_map(O, R, neutral_only=False, clamp=clamp)
    return fit_map(O, R, neutral_only=True, clamp=6.0 if clamp is None else clamp)


def explore(slot):
    """第一步：只用上半幅拟合、只看下半幅打分，挑出「能在没见过的像素上复现」的结构。

    这一步是必需的。整幅拟合时 DEEPTONE 能从 12.23 降到 8.77，但把那根曲线拿到下半幅
    一验，收益归零 —— 说明降下去的其实是这张照片上下的亮度分布差，不是真正的影调差。
    """
    O, R = load('d300ncp', slot), load('workshop', slot)
    h = O.shape[0] // 2
    Of, Rf = O[:h], R[:h]
    ev = slice(h, None)

    def score(f, s=1.0, deg=0.0, k=1.0):
        return float(np.abs(predict(O, f, s, deg, k)[ev] - R[ev]).mean())

    e0 = score(ID)
    cands = [(e0, 'id', 0, 0, 1.0)]
    f = _fit(slot, Of, Rf)
    cands.append((score(f), 'tone', 0, 0, 1.0))
    if slot in TONED:
        for kb in range(0x80, 0x8A):
            k = (kb - 0x80) / 4.0
            cands.append((score(f, 1.0, 0.0, k), 'tone', 0, 0, k))
    elif slot not in MONO:
        for n in range(-3, 4):
            for m in range(-3, 4):
                cands.append((score(f, SAT_STEP ** n, HUE_STEP * m), 'tone', n, m, 1.0))

    cands.sort(key=lambda c: c[0])
    b = cands[0]
    if b[0] > e0 - MIN_GAIN:                       # 留出半幅上收益不够，就别动
        b = (e0, 'id', 0, 0, 1.0)
    return dict(kind=b[1], n=b[2], m=b[3], k=b[4], cv0=e0, cv1=b[0])


def optimize_slot(slot):
    """第二步：结构定了之后，用全幅重拟合曲线（选结构用 CV，落地用全量）"""
    O, R = load('d300ncp', slot), load('workshop', slot)
    Tcur = target_curve(slot)
    pl = explore(slot)

    e0 = float(np.abs(O - R).mean())
    if pl['kind'] == 'id':
        f = ID
        how = '维持原样'
    else:
        f = _fit(slot, O, R)
        how = '影调重拟合'
        if pl['n'] or pl['m']:
            how = '影调+饱和度%+d+色相%+d' % (pl['n'], pl['m'])
        elif slot in TONED:
            how = '调色强度 %02X' % (0x80 + int(round(pl['k'] * 4)))

    s = SAT_STEP ** pl['n']
    if slot in TONED:
        P = predict(O, f, 1.0, 0.0, pl['k'])
    elif slot in MONO:
        P = predict(O, f)
    else:
        P = predict(O, f, s, HUE_STEP * pl['m'])
    e1 = float(np.abs(P - R).mean())

    T = compose(Tcur, f)
    return dict(slot=slot, e0=e0, e1=e1, f=f, n=pl['n'], m=pl['m'], k=pl['k'],
                how=how, T=T, cv=(pl['cv0'], pl['cv1']),
                dev=float(np.abs(T - Tcur).max()))


def main():
    dry = '--dry' in sys.argv
    print('%-4s %-24s %-6s %-9s %-6s %-6s %-5s %s'
          % ('槽', '滤镜', '现状', '留出验证', '改后', '降幅', 'Δ曲线', '动作'))
    print('-' * 96)
    res = []
    for slot in range(1, 31):
        r = optimize_slot(slot)
        res.append(r)
        print('%2d   %-22s %6.2f %5.2f→%5.2f %6.2f %+6.2f %5.1f  %s'
              % (slot, NAMES[slot - 1] + ' ' + CN[slot - 1], r['e0'],
                 r['cv'][0], r['cv'][1], r['e1'], r['e1'] - r['e0'], r['dev'], r['how']))
    a = np.array([[r['e0'], r['e1']] for r in res])
    c = np.array([[r['cv'][0], r['cv'][1]] for r in res])
    print('-' * 96)
    print('30 支平均（整幅）%.2f → %.2f（降 %.1f%%）  跌幅总和 %.1f'
          % (a[:, 0].mean(), a[:, 1].mean(), (1 - a[:, 1].mean() / a[:, 0].mean()) * 100,
             (a[:, 0] - a[:, 1]).sum()))
    print('30 支平均（留出半幅）%.2f → %.2f（降 %.1f%%）   ← 不参与拟合的那一半，才是真收益'
          % (c[:, 0].mean(), c[:, 1].mean(), (1 - c[:, 1].mean() / c[:, 0].mean()) * 100))
    if dry:
        return

    os.makedirs(OUT, exist_ok=True)
    rows = []
    for r in res:
        slot = r['slot']
        src = open(os.path.join(REL, 'PICCON%02d.NCP' % slot), 'rb').read()
        name = src[16:36]
        base = struct.unpack_from('>H', src, 36)[0]
        assert base in OK_BASE, (slot, base)
        sl = list(src[40:48])
        if slot not in MONO:
            sl[3] = 0x80 + r['n']
            sl[4] = 0x80 + r['m']
        else:
            sl[3] = sl[4] = 0xFF                     # 单色底子上没有饱和度/色相
            if slot in TONED:
                sl[7] = 0x80 + int(round(r['k'] * 4))
        tgt = [int(round(v / 255.0 * OUT_MAX)) for v in r['T']]
        tgt.append(tgt[-1])                      # LUT 是 257 点（输入 0..256）
        tgt = [int(v) for v in np.maximum.accumulate(tgt)]
        new = build_ncp(name.decode('latin1').rstrip('\x00'), base, sl,
                        precompensate(tgt, OUT_MAX))
        fn = os.path.join(OUT, 'PICCON%02d.NCP' % slot)
        open(fn, 'wb').write(new)
        prob = verify_one(fn)
        assert not prob, (slot, prob)

        # 回读校验：把写进文件的曲线重新解出来，用同一套预测重算误差。
        # 这一步能抓住 build_ncp / precompensate 的任何偏移错误（曾经把 LUT 起点写成 128）。
        T_file = lut_to_curve(np.array(struct.unpack_from('>257H', new, 120), dtype=float)
                              / OUT_MAX * 255.0)
        ic = inv_curve(target_curve(slot))
        f_file = np.interp(ic(np.arange(256, dtype=float)), np.arange(256, dtype=float), T_file)
        if slot not in MONO:
            P = predict(load('d300ncp', slot), f_file, SAT_STEP ** r['n'], HUE_STEP * r['m'])
        elif slot in TONED:
            P = predict(load('d300ncp', slot), f_file, 1.0, 0.0, r['k'])
        else:
            P = predict(load('d300ncp', slot), f_file)
        e_file = float(np.abs(P - load('workshop', slot)).mean())

        rows.append((slot, NAMES[slot - 1], CN[slot - 1], base, sl, r['e0'], r['e1'],
                     e_file, r['how']))
        print('写出 %s  滑块=%s  预测 %.2f / 回读 %.2f'
              % (os.path.basename(fn), ' '.join('%02X' % v for v in sl), r['e1'], e_file))

    # 指标表由 audit_release.py 生成（它从文件本身反算，比这里的模型预测更可信）
    a = np.array([[r[5], r[7]] for r in rows])          # (v1 口径, 回读口径)
    print('')
    print('发布包：%s（%d 个）' % (OUT, len(rows)))
    print('模型预测：平均 %.2f → %.2f（降 %.1f%%）；实测口径请跑 tools/audit_release.py'
          % (a[:, 0].mean(), a[:, 1].mean(), (1 - a[:, 1].mean() / a[:, 0].mean()) * 100))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
