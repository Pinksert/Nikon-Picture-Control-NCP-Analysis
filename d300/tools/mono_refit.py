#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mono_refit.py —— 单色 5 支的曲线重拟合（v4）。

为什么只做单色
--------------
单色没有颜色：像素全落在灰轴上，机身能给的「一条亮度曲线」正好是完整自由度。
彩色的差距有一大半在彩度上，曲线碰不到（见 docs/22）。

为什么之前那 5 支对不上
----------------------
它们的曲线是 `audit_release.py` 那一轮拟合的，用的是另一张底片（DSC_3891），
而检验成片是 DSC_4484。曲线本身与场景无关，但**拟合依赖的亮度分布**与场景有关：
DSC_3891 没覆盖到的亮度区间，曲线在那儿就是外推。

怎么拟合：直接在输出域做
------------------------
不反解回输入 x —— BINARY 的曲线是硬台阶，反解会把 70% 的像素塌进同一个 x，阈值信息全丢。
也不拿别的槽当探针 —— 各槽锐化档不同，探针在边缘有 1–2 级噪声，对硬阈值是致命的。

我们的成片 O 与官方成片 R 来自同一张底片、同一条渲染管线，差的只有曲线，于是令

    R = f(O)          f = 单调映射（分档中位数 + 平滑 + 单调化 + 端点外推）
    T_new(x) = f(T_cur(x))

这是精确可实现的：把 f 折进曲线 = 换一条曲线重渲一遍。

指标为什么不用老口径
--------------------
老口径（`real_gap.py` / `lut_fit.py`）是「两边都不剪裁的像素才参与统计」。两个毛病：

1. **可以刷分**：把更多像素推到纯黑/纯白，它们就被踢出统计集。实测把 BINARY 阈值
   下移 12 级能让这个口径的 ΔE00 从 7.69 掉到 2.26，而黑白占比从 63%/18% 涨到 76%
   —— 那 2.26 是假的。
2. **看不见灰雾**：反过来，目标黑、我们留灰的像素也被排除了，而那正是肉眼最先
   看出差别的地方。

所以主指标取 `dE_either`：只在**两边都剪裁**时才排除。多剪一个像素它照样留在分母里，
该黑没黑也照样留在分母里。另列三个数备查：
  dE_both  老口径（两边都未剪裁）—— 与前几轮的数字可比
  dE_all   全像素 —— 剪裁区占多数时会被稀释
  haze     我们剪裁、参考没剪的百分点 —— 正数 = 我们把画面压死得更多

用法
----
    python tools/mono_refit.py --dry          # 只评估
    python tools/mono_refit.py                # 评估 + 写 ncp/release_v4/
    python tools/mono_refit.py --pack-filter  # 另出「单色滤镜」探针包
"""
import argparse
import csv
import os
import struct
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from compensate import precompensate                      # noqa: E402
from diag_residual import to_lab, de2000                  # noqa: E402
from ncp_d300 import OUT_MAX, build_ncp, verify_one        # noqa: E402
from optimize_v2 import lut_to_curve, read_lut             # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
SAMP = os.path.join(ROOT, 'samples')
REL = os.path.join(ROOT, 'ncp', 'release', 'NIKON', 'CUSTOMPC')
OUT = os.path.join(ROOT, 'ncp', 'release_v4', 'NIKON', 'CUSTOMPC')
PACK = os.path.join(ROOT, '..', '_probe_monofilter')

MONO = [(17, 'CHARCOAL'), (18, 'GRAPHITE'), (19, 'BINARY'),
        (20, 'CARBON'), (27, 'MONOCHROME')]
CLIP = 2.0
X = np.arange(256, dtype=float)
MIN_GAIN = 0.10          # 留出集收益不到这个数就不改文件
SIZE = 420


# ------------------------------------------------------------------ 读图
def load(path, size=SIZE):
    im = Image.open(path).convert('RGB')
    r = size / max(im.size)
    if r < 1:
        im = im.resize((max(1, int(round(im.width * r))),
                        max(1, int(round(im.height * r)))), Image.LANCZOS)
    return np.asarray(im, dtype=np.float64)


def find(d, slot, name):
    stem = '%02d_%s' % (slot, name)
    for f in os.listdir(d):
        b, _ = os.path.splitext(f)
        if b.upper() == stem.upper():
            return os.path.join(d, f)
    return None


def pair(slot, name):
    return (load(find(os.path.join(SAMP, 'real_v3'), slot, name)),
            load(find(os.path.join(SAMP, 'real_target'), slot, name)))


def gray(a):
    """(H,W,3) 整幅与 (N,3) 像素表都能用"""
    a = np.asarray(a, dtype=np.float64)
    if a.ndim == 3:
        return a.mean(2)
    if a.ndim == 2 and a.shape[-1] == 3:
        return a.mean(1)
    return a


# ------------------------------------------------------------------ 指标
def clipmask(a):
    return (a.min(-1) <= CLIP) | (a.max(-1) >= 255 - CLIP)


def metrics(P, R, full=True):
    P = np.asarray(P, dtype=np.float64)
    R = np.asarray(R, dtype=np.float64)
    cp, cr = clipmask(P), clipmask(R)
    m = ~(cp & cr)
    if m.sum() < 3000:
        m = np.ones_like(cp)
    de_either = float(de2000(to_lab(P[m]), to_lab(R[m])).mean())
    out = dict(de_either=de_either, de_both=float('nan'), de_all=de_either,
               haze=float((cp & ~cr).mean() * 100))
    if full:
        b = (~cp) & (~cr)
        if b.sum() > 3000:
            out['de_both'] = float(de2000(to_lab(P[b]), to_lab(R[b])).mean())
        out['de_all'] = float(de2000(to_lab(P.reshape(-1, 3)),
                                     to_lab(R.reshape(-1, 3))).mean())
    return out


# ------------------------------------------------------------------ 拟合
def fit_f(o, r, step=2.0, minn=120):
    """f：我们的输出 → 官方输出。分档中位数 + 3 点平滑 + 单调化 + 端点按斜率外推。"""
    oo = np.clip(np.round(o), 0, 255).astype(int).ravel()
    rr = np.asarray(r, dtype=np.float64).ravel()
    xs, ys = [], []
    for a in np.arange(0, 256, step):
        m = (oo >= a) & (oo < a + step)
        if m.sum() < minn:
            continue
        xs.append(a + step / 2 - 0.5)
        ys.append(float(np.median(rr[m])))
    if len(xs) < 6:
        return None
    xs, ys = np.array(xs), np.array(ys)
    ys = np.convolve(np.pad(ys, 1, mode='edge'), [0.25, 0.5, 0.25], 'valid')
    ys = np.maximum.accumulate(ys)
    if xs[0] > 0:
        s = (ys[1] - ys[0]) / max(xs[1] - xs[0], 1e-6)
        xs = np.r_[0.0, xs]
        ys = np.r_[max(0.0, min(ys[0] - s * xs[1], ys[0])), ys]
    if xs[-1] < 255:
        s = (ys[-1] - ys[-2]) / max(xs[-1] - xs[-2], 1e-6)
        xs = np.r_[xs, 255.0]
        ys = np.r_[ys, min(255.0, max(ys[-1] + s * (255.0 - xs[-2]), ys[-1]))]
    return np.clip(np.maximum.accumulate(np.interp(X, xs, ys)), 0, 255)


def render_f(f, O):
    lo = gray(O)
    return np.clip(np.interp(lo, X, f)[..., None] + (O - lo[..., None]), 0, 255)


def cells(shape, ny=2, nx=2):
    h, w = shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    ey = np.linspace(0, h, ny + 1).astype(int)
    ex = np.linspace(0, w, nx + 1).astype(int)
    return [(yy >= ey[i]) & (yy < ey[i + 1]) & (xx >= ex[j]) & (xx < ex[j + 1])
            for i in range(ny) for j in range(nx)]


def cv_score(O, R):
    """2×2 空间分块留出：3 块拟合、1 块打分。判断重拟合是规律还是记图。"""
    acc = []
    for m in cells(O.shape):
        if m.sum() < 3000:
            continue
        f = fit_f(gray(O)[m], gray(R)[m])
        if f is None:
            continue
        acc.append(metrics(np.repeat(np.interp(gray(O)[m], X, f)[..., None], 3, -1),
                           R[m], full=False)['de_either'])
    return float(np.mean(acc)) if acc else float('nan')


def header_error(comp):
    """20 个自适应控制点折线与 257 点 LUT 的最大偏差（级）。

    机身按控制点重算曲线，两线不一致时显示的和生效的不是一回事；台阶型曲线尤其危险。
    """
    from ncp_d300 import header_from_lut
    h = header_from_lut(comp)
    n = h[8]
    pts = [(h[9 + 2 * i], h[10 + 2 * i]) for i in range(n)]
    xs = np.array([p[0] for p in pts], float)
    ys = np.array([p[1] for p in pts], float)
    ref = np.array(comp[:256], dtype=float) / OUT_MAX * 255.0
    return float(np.abs(np.interp(X, xs, ys) - ref).max())


# ------------------------------------------------------------------ 主流程
def evaluate():
    rows = []
    for slot, name in MONO:
        O, R = pair(slot, name)
        m0 = metrics(O, R)
        f = fit_f(gray(O), gray(R))
        m1 = metrics(render_f(f, O), R)
        cv = cv_score(O, R)
        rows.append(dict(slot=slot, name=name, m0=m0, m1=m1, cv=cv, f=f,
                         gain=m0['de_either'] - cv))
    return rows


def show(rows):
    print('%-11s %8s %8s %8s %8s %9s %7s %s'
          % ('滤镜', '现状', '重拟合', '留出', '老口径', '灰雾Δ', '收益', 'Δ曲线'))
    print('-' * 92)
    for r in rows:
        Tcur = lut_to_curve(read_lut(r['slot']))
        Tn = np.interp(Tcur, X, r['f'])
        print('%-11s %8.2f %8.2f %8.2f %8.2f %+9.1f %+7.2f %6.1f 级'
              % (r['name'], r['m0']['de_either'], r['m1']['de_either'], r['cv'],
                 r['m1']['de_both'], r['m1']['haze'] - r['m0']['haze'],
                 r['gain'], np.abs(Tn - Tcur).max()))
    print('-' * 92)
    print('5 支平均（主指标）：%.2f → %.2f，留出 %.2f'
          % (np.mean([r['m0']['de_either'] for r in rows]),
             np.mean([r['m1']['de_either'] for r in rows]),
             np.mean([r['cv'] for r in rows])))
    print('5 支平均（老口径）：%.2f → %.2f'
          % (np.mean([r['m0']['de_both'] for r in rows]),
             np.mean([r['m1']['de_both'] for r in rows])))


def write(rows, dry):
    changed = [r for r in rows if r['gain'] >= MIN_GAIN]
    print('\n达到改写门限（留出收益 ≥ %.2f）：%s'
          % (MIN_GAIN, '、'.join(r['name'] for r in changed) or '无'))
    if dry:
        return rows

    os.makedirs(OUT, exist_ok=True)
    for r in rows:
        slot, name = r['slot'], r['name']
        src = open(os.path.join(REL, 'PICCON%02d.NCP' % slot), 'rb').read()
        fn = os.path.join(OUT, 'PICCON%02d.NCP' % slot)

        # 没达到门限的一律原样复制：重写会引入 precompensate 往返的插值误差
        # （实测未改动的三支被重写后，曲线在陡段差出 18 级）。包要能整目录替换，
        # 但除了真改过的那几支，其余必须与 release 逐字节相同。
        if r['gain'] < MIN_GAIN:
            open(fn, 'wb').write(src)
            print('复制 %-18s 与 release 逐字节相同' % os.path.basename(fn))
            continue

        nm = src[16:36].decode('latin1').rstrip('\x00')
        base = struct.unpack_from('>H', src, 36)[0]
        sl = list(src[40:48])

        Tcur = lut_to_curve(read_lut(slot))
        T_new = np.interp(Tcur, X, r['f'])
        tgt = [int(round(y / 255.0 * OUT_MAX)) for y in T_new]
        tgt.append(tgt[-1])
        tgt = [int(t) for t in np.maximum.accumulate(tgt)]
        comp = precompensate(tgt, OUT_MAX)
        new = build_ncp(nm, base, sl, comp)
        open(fn, 'wb').write(new)
        prob = verify_one(fn)
        assert not prob, (slot, prob)

        # 回读：文件里的曲线 → 有效曲线 → 重新预测
        T_file = lut_to_curve(np.array(struct.unpack_from('>257H', new, 120), dtype=float)
                              / OUT_MAX * 255.0)
        O, R = pair(slot, name)
        lo = gray(O)
        keep = np.r_[True, np.diff(Tcur) > 1e-9]
        x = np.interp(np.clip(lo, Tcur[keep].min(), Tcur[keep].max()), Tcur[keep], X[keep])
        P = np.clip(np.interp(x, X, T_file)[..., None] + (O - lo[..., None]), 0, 255)
        mf = metrics(P, R)
        hdr = header_error(comp)
        print('写入 %-18s %d B  有效曲线最大偏差 %.1f 级  20 点折线偏差 %.1f 级  回读 dE %.2f'
              % (os.path.basename(fn), len(new),
                 np.abs(T_file - T_new).max(), hdr, mf['de_either']))

    with open(os.path.join(SAMP, 'mono_refit.csv'), 'w', encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['slot', 'name', 'de_either_before', 'de_either_after', 'cv_either',
                    'de_both_before', 'de_both_after', 'de_all_before', 'de_all_after',
                    'haze_before', 'haze_after', 'refit'])
        for r in rows:
            w.writerow([r['slot'], r['name'],
                        '%.4f' % r['m0']['de_either'], '%.4f' % r['m1']['de_either'],
                        '%.4f' % r['cv'], '%.4f' % r['m0']['de_both'],
                        '%.4f' % r['m1']['de_both'], '%.4f' % r['m0']['de_all'],
                        '%.4f' % r['m1']['de_all'], '%.2f' % r['m0']['haze'],
                        '%.2f' % r['m1']['haze'], int(r['gain'] >= MIN_GAIN)])
    print('\ncsv -> samples/mono_refit.csv')
    print('包   -> %s' % OUT)
    return rows


# ------------------------------------------------------------------ 滤镜探针
FILTERS = [(0, 'OFF'), (1, 'YELLOW'), (2, 'ORANGE'), (3, 'RED')]


def pack_filter():
    """单色滤镜探针：0/1/2/3 四档，各写一版 BINARY 与 MONOCHROME。

    BINARY 的残差是「黑白通道混色权重不同」——红主导的像素我们判白、官方判黑，
    蓝主导的反过来。曲线救不了，只有底子上的「滤镜」那一格能改混色权重。
    这一格我们从没动过（一直是 0x80 = 关闭）。
    """
    os.makedirs(PACK, exist_ok=True)
    print('%-24s %-8s %s' % ('文件', '滤镜', '滑块'))
    print('-' * 66)
    for slot, name in ((19, 'BINARY'), (27, 'MONOCHROME')):
        src = open(os.path.join(REL, 'PICCON%02d.NCP' % slot), 'rb').read()
        nm = src[16:36].decode('latin1').rstrip('\x00')
        base = struct.unpack_from('>H', src, 36)[0]
        lut = list(struct.unpack_from('>257H', src, 120)) if len(src) == 638 else None
        for val, lbl in FILTERS:
            sl = list(src[40:48])
            sl[5] = 0x80 + val          # 第 6 个滑块 = 单色滤镜
            short = '%s F%d' % (name[:8], val)
            new = build_ncp(short, base, sl, lut)
            fn = os.path.join(PACK, 'M%d_%s_F%d.NCP' % (slot, name[:4], val))
            open(fn, 'wb').write(new)
            print('%-24s %-8s %s' % (os.path.basename(fn), lbl,
                                     ' '.join('%02X' % v for v in sl)))
    readme = os.path.join(PACK, '说明-先看这里.txt')
    open(readme, 'w', encoding='utf-8-sig').write(
        '单色滤镜探针（8 个 NCP）\r\n'
        '======================\r\n\r\n'
        '要解决的问题：5 支单色里 BINARY 差 7 个 ΔE00，但曲线怎么改都没用。\r\n'
        '原因是「哪些像素算白」两边判得不一样，而且判法与颜色相关：\r\n'
        '  我们判白 / 官方判黑 的像素，73% 是红色主导\r\n'
        '  官方判白 / 我们判黑 的像素，69% 是蓝色主导\r\n'
        '这不是影调，是黑白通道的混合权重。NCP 里唯一能动这一格的是「单色滤镜」滑块，\r\n'
        '而我们一直写的是 0x80（关闭）。\r\n\r\n'
        '怎么用：\r\n'
        '  1. 同一个 NEF，逐个套这 8 个 NCP，各导出一张 JPEG；\r\n'
        '  2. 文件名保持原样（M19_BINA_F0.JPG …），放进 d300\\samples\\probe_monofilter\\；\r\n'
        '  3. 导出完告诉我，我来读数。\r\n\r\n'
        '判读：如果 F1/F2/F3 里有哪一档让「红白蓝黑」的分歧明显变小，就是它；\r\n'
        '      四档一样 = 这条也封死，BINARY 到此为止。\r\n'
        '注意：滤镜档会同时改变明暗分布，所以不看亮度，只看「分歧像素」的数量。\r\n')
    print('\n说明 -> %s' % readme)


# ------------------------------------------------------------------ 分歧诊断
def evidence(slot=19, name='BINARY'):
    """BINARY 的残差到底是不是影调？把「两派判得不一样」的像素按颜色拆开。

    做法：拿同一张底片上的彩色成片（DREAM，它不经过单色转换）当作每个像素的
    「本来颜色」，再看两组分歧像素里主导通道的占比。

    如果只是阈值高低不同，两组分歧像素的颜色成分应当一样（都是中间调灰）；
    实测一组 73% 红主导、另一组 69% 蓝主导 —— 那是黑白通道**混合权重**不同，
    属于底子，不属于曲线。曲线只能整体抬降，无法把红色挑出来变白。
    """
    C = load(find(os.path.join(SAMP, 'real_v3'), 1, 'DREAM'))
    O, R = pair(slot, name)
    wo, wr = O.min(2) > 253, R.min(2) > 253
    groups = [('两者都白', wo & wr), ('两者都黑', ~wo & ~wr),
              ('我们白 官方黑', wo & ~wr), ('官方白 我们黑', wr & ~wo)]
    rows = []
    for label, m in groups:
        px = C[m]
        mx, mn = px.max(1), px.min(1)
        sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
        ch = px.argmax(1)
        rows.append(dict(cls=label, n=int(m.sum()),
                         R=100 * float((ch == 0).mean()),
                         G=100 * float((ch == 1).mean()),
                         B=100 * float((ch == 2).mean()),
                         gray=float(gray(O)[m].mean()) if m.any() else 0.0,
                         sat=float(sat.mean())))
    with open(os.path.join(SAMP, 'mono_disagree.csv'), 'w', encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['class', 'n', 'R', 'G', 'B', 'gray', 'sat'])
        for r in rows:
            w.writerow([r['cls'], r['n'], '%.1f' % r['R'], '%.1f' % r['G'],
                        '%.1f' % r['B'], '%.1f' % r['gray'], '%.3f' % r['sat']])
    print('%-16s %8s %8s %8s %8s' % ('分组', '像素数', 'R主导', 'G主导', 'B主导'))
    for r in rows:
        print('%-16s %8d %7.0f%% %7.0f%% %7.0f%%' % (r['cls'], r['n'], r['R'], r['G'], r['B']))
    print('\ncsv -> samples/mono_disagree.csv')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--pack-filter', action='store_true')
    ap.add_argument('--evidence', action='store_true')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if a.evidence:
        evidence()
        return
    if a.pack_filter:
        pack_filter()
        return
    rows = evaluate()
    show(rows)
    write(rows, a.dry)


if __name__ == '__main__':
    main()
