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


CV_GRID = (2, 4)          # 交叉验证折数 = 2×4 = 8


def cv_cells(shape, ny=CV_GRID[0], nx=CV_GRID[1]):
    """把画面切成 ny×nx 个互不相交的块，返回每块的布尔 mask

    按块切而不是按上下半幅切，是为了不让「上半天、下半天」这种构图差异
    被当成「曲线不泛化」的证据。每块横跨全宽、纵向 1/ny 高，分布更均匀。
    """
    h, w = shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    ey = np.linspace(0, h, ny + 1).astype(int)
    ex = np.linspace(0, w, nx + 1).astype(int)
    return [(yy >= ey[i]) & (yy < ey[i + 1]) & (xx >= ex[j]) & (xx < ex[j + 1])
            for i in range(ny) for j in range(nx)]


def render(O, f, slot, n, m, k):
    """按槽位类型把「曲线 + 滑块」落到画面上（唯一入口，避免各处参数顺序写岔）"""
    if slot in TONED:
        return predict(O, f, 1.0, 0.0, k)
    if slot in MONO:
        return predict(O, f)
    return predict(O, f, SAT_STEP ** n, HUE_STEP * m)


def explore(slot):
    """第一步：挑「在没见过的像素上也能复现」的结构。用 2×4 = 8 折交叉验证。

    为什么不是「上/下半幅」
    ----------------------
    第 2 版用的是单次 50/50 上下切分，这等于假设一张照片的上下两半亮度分布相同。
    真实照片不满足：上半幅是天、下半幅是地的时候，曲线在下半幅上根本没被约束过，
    打分自然没收益，于是被判「维持原样」。

    代价是实实在在的：槽 23 DEEPTONE 被这个切法判成「不动」，可它的 |ΔL*| 达 4.95
    （30 支平均 1.43），是全场影调差最大的两支之一；换成 8 折之后同一支从 12.23
    降到 8.76，而且这 2.68 是在「7/8 像素拟合、1/8 没见过的像素打分」上测出来的，
    不是把全幅拟合的过拟合结果拿来当收益。

    8 折切成 2×4 的块，每块横跨全宽、纵向半高，亮度与色相分布比单纯的上下两半均匀
    得多；每次留一块做测试，剩下的七块拟合，8 次循环取每块上的平均测试误差。
    候选结构按「8 折平均测试误差」排序，而不是某一次的切身结果。
    """
    O, R = load('d300ncp', slot), load('workshop', slot)
    cs = [(0, 0, 1.0)]
    if slot in TONED:
        for kb in range(0x80, 0x8A):
            cs.append((0, 0, (kb - 0x80) / 4.0))
    elif slot not in MONO:
        for n in range(-3, 4):
            for m in range(-3, 4):
                cs.append((n, m, 1.0))

    ms = cv_cells(O.shape)
    acc = np.zeros(len(cs))
    base = 0.0
    for msk in ms:
        tr, te = ~msk, msk
        f = _fit(slot, O[tr][:, None, :], R[tr][:, None, :])
        base += float(np.abs(predict(O, ID)[te] - R[te]).mean())
        for i, (n, m, k) in enumerate(cs):
            acc[i] += float(np.abs(render(O, f, slot, n, m, k)[te] - R[te]).mean())
    acc /= len(ms)
    base /= len(ms)

    i = int(np.argmin(acc))
    n, m, k = cs[i]
    if acc[i] > base - MIN_GAIN:                   # 留出块上收益不够，就别动
        return dict(kind='id', n=0, m=0, k=1.0, cv0=base, cv1=base)
    return dict(kind='tone', n=n, m=m, k=k, cv0=base, cv1=float(acc[i]))


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

    P = render(O, f, slot, pl['n'], pl['m'], pl['k'])
    e1 = float(np.abs(P - R).mean())

    T = compose(Tcur, f)
    return dict(slot=slot, e0=e0, e1=e1, f=f, n=pl['n'], m=pl['m'], k=pl['k'],
                how=how, T=T, cv=(pl['cv0'], pl['cv1']),
                dev=float(np.abs(T - Tcur).max()))


def main():
    dry = '--dry' in sys.argv
    print('%-4s %-24s %-6s %-9s %-6s %-6s %-5s %s'
          % ('槽', '滤镜', '现状', '8 折留出', '改后', '降幅', 'Δ曲线', '动作'))
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
    print('30 支平均（8 折留出）%.2f → %.2f（降 %.1f%%）   ← 每折都没见过的那块，才是真收益'
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
        P = render(load('d300ncp', slot), f_file, slot, r['n'], r['m'], r['k'])
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
