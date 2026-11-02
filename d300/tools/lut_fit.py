#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lut_fit.py —— 机内做不完的那一半，做成一张后期 3D LUT。

为什么要有这一步
----------------
真渲染口径下 26 支平均差 6.45 级 / ΔE00 5.36，残差几乎全在彩度上
（|ΔL*| 1.77，|ΔC*| 4.51），而且各支各偏一个方向。原因是 D300 的
优化校准引擎只提供「一条亮度 LUT + 一个全局饱和度倍率 + 一个全局色相角」，
而原版 NP3 的创意底子做的是「按色相分区、按彩度分区」的三维色彩重排。
一维/全局的工具表达不了三维映射 —— 这是引擎代际差异，不是参数没调好。

所以这条路不再往机内挤，而是把残差本身拟合成一个「输入 RGB → 目标 RGB」
的三维查找表（3D LUT）：机内 NCP 负责影调，后期 LUT 负责颜色。

做法
----
· 训练样本：同底片、同机、同 NX Studio 的一对成片（我们 / 官方）
· 拟合：三线性网格 + 「溅射残差 + 平滑 + 阻尼」迭代（无需 scipy）
· 留出：2×2 空间分块交叉验证，拟合用 3 块、打分用第 4 块
· 输出：33³ .cube（Resolve / PS / Affinity 通用）+ 逐支指标 csv + 预览图

    python tools/lut_fit.py                     # 全 26 支，42px? 不，420px 长边
    python tools/lut_fit.py --only DREAM,TOY    # 只跑几支
    python tools/lut_fit.py --size 0            # 原尺寸（慢）
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from diag_residual import to_lab, de2000                     # noqa: E402
from real_gap import NAMES, MONO, load, find                 # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
SAMP = os.path.join(ROOT, 'samples')
LUTD = os.path.join(ROOT, 'lut')
CLIP = 2.0


# ------------------------------------------------------------------ 网格插值
def interp(G, p):
    """三线性插值：G 形状 (N,N,N,3)，p 形状 (M,3) 取值 0..255"""
    N = G.shape[0]
    x = np.clip(p, 0, 255) * ((N - 1) / 255.0)
    i = np.clip(np.floor(x).astype(np.int64), 0, N - 2)
    f = x - i
    out = np.zeros((p.shape[0], 3))
    for dx in (0, 1):
        wx = (f[:, 0] if dx else 1.0 - f[:, 0])[:, None]
        for dy in (0, 1):
            wy = (f[:, 1] if dy else 1.0 - f[:, 1])[:, None]
            for dz in (0, 1):
                wz = (f[:, 2] if dz else 1.0 - f[:, 2])[:, None]
                out += wx * wy * wz * G[i[:, 0] + dx, i[:, 1] + dy, i[:, 2] + dz]
    return out


def _flat_idx(p, N):
    x = np.clip(p, 0, 255) * ((N - 1) / 255.0)
    i = np.clip(np.floor(x).astype(np.int64), 0, N - 2)
    f = x - i
    return i, f


def splat_avg(res, p, N):
    """把逐样本残差按三线性权重摊回网格，返回 (加权平均残差, 权重)

    归一化用 sum(w) 而不是 sum(w²)：三线性插值下一个样本同时改 8 个格子，
    用 sum(w²) 等于把步长放大 8–30 倍（边上格子更狠），迭代会直接崩。
    除以 sum(w) 得到「该格附近样本的平均残差」，λ≈1 时一步到位、且不发散。
    """
    i, f = _flat_idx(p, N)
    size = N ** 3
    acc = np.empty((3, size))
    wsum = np.zeros(size)
    for dx in (0, 1):
        wx = f[:, 0] if dx else 1.0 - f[:, 0]
        for dy in (0, 1):
            wy = f[:, 1] if dy else 1.0 - f[:, 1]
            for dz in (0, 1):
                wz = f[:, 2] if dz else 1.0 - f[:, 2]
                w = wx * wy * wz
                idx = (i[:, 0] + dx) * N * N + (i[:, 1] + dy) * N + (i[:, 2] + dz)
                wsum += np.bincount(idx, weights=w, minlength=size)
                for c in range(3):
                    acc[c] += np.bincount(idx, weights=w * res[:, c], minlength=size)
    valid = wsum > 0.02           # 支撑太少就判 0（该格保持原值）
    out = np.zeros((3, size))
    out[:, valid] = acc[:, valid] / wsum[valid]
    return out.reshape(3, N, N, N).transpose(1, 2, 3, 0), wsum.reshape(N, N, N)


def smooth3(G, rounds=1):
    """可分离 [1,2,1]/4 平滑，压掉网格里的孤立噪声

    边界必须用 edge 复制，不能用 np.roll —— 周期边界会把对立两面接起来，
    迭代中形成正反馈，几十轮后整张网格崩掉（踩过一次）。
    """
    out = G
    for _ in range(rounds):
        for ax in (0, 1, 2):
            pad = [(1, 1) if a == ax else (0, 0) for a in range(out.ndim)]
            p = np.pad(out, pad, mode='edge')
            lo = [slice(None)] * out.ndim
            mid = [slice(None)] * out.ndim
            hi = [slice(None)] * out.ndim
            lo[ax] = slice(0, -2)
            mid[ax] = slice(1, -1)
            hi[ax] = slice(2, None)
            out = (p[tuple(lo)] + 2.0 * p[tuple(mid)] + p[tuple(hi)]) / 4.0
    return out


def identity_grid(N):
    g = np.linspace(0.0, 255.0, N)
    G = np.stack(np.meshgrid(g, g, g, indexing='ij'), -1)
    return G.astype(np.float64)


def fit_lut(src, dst, N=17, iters=120, damp=0.5, sround=0, stages=(5, 9), trust=40.0):
    """拟合 src -> dst 的三维映射，返回网格 (N,N,N,3)

    三个阶段：
      1) 粗网格 5³/9³ 各跑 1/4 的迭代 —— 每格样本多、解稳定，给细网格当初值
      2) 细网格 N³ 跑满迭代
    每步都夹在「恒等 ± trust」的信任域内。信任域不是可选项：不加的话
    稀疏色域格子会冲到 0/255，留出误差反而从 2.3 涨到 4.0。
    """
    seq = [n for n in stages if n < N] + [N]
    G = None
    for k, n in enumerate(seq):
        it = iters if n == N else max(8, iters // 4)
        if G is None:
            G = identity_grid(n)
        else:
            g = np.linspace(0.0, 255.0, n)
            pts = np.stack(np.meshgrid(g, g, g, indexing='ij'), -1).reshape(-1, 3)
            G = interp(G, pts).reshape(n, n, n, 3)
        I = identity_grid(n)
        for _ in range(it):
            corr, ok = splat_avg(dst - interp(G, src), src, n)
            corr = np.nan_to_num(corr, nan=0.0, posinf=0.0, neginf=0.0)
            if sround:
                corr = smooth3(corr, sround)
            G = np.clip(np.clip(G + damp * corr, I - trust, I + trust), 0.0, 255.0)
    return G


# ------------------------------------------------------------------ 指标
def metrics(a, b, m):
    la, lb = to_lab(a[m]), to_lab(b[m])
    de = de2000(la, lb)
    ca = np.hypot(la[:, 1], la[:, 2])
    cb = np.hypot(lb[:, 1], lb[:, 2])
    return dict(mad=float(np.abs(a[m] - b[m]).mean()),
                de=float(de.mean()),
                jnd=float((de > 2.3).mean() * 100.0),
                dl=float(np.abs(la[:, 0] - lb[:, 0]).mean()),
                dc=float(np.abs(ca - cb).mean()),
                dcs=float((ca - cb).mean()))


def mask_of(a, b):
    m = ((a.min(2) > CLIP) & (a.max(2) < 255 - CLIP)
         & (b.min(2) > CLIP) & (b.max(2) < 255 - CLIP))
    if m.sum() < 5000:
        m = np.ones(a.shape[:2], bool)
    return m


# ------------------------------------------------------------------ 交叉验证
def folds(shape, ny=2, nx=2):
    h, w = shape[:2]
    out = []
    for j in range(ny):
        for i in range(nx):
            m = np.zeros(shape[:2], bool)
            m[j * h // ny:(j + 1) * h // ny, i * w // nx:(i + 1) * w // nx] = True
            out.append(m)
    return out


def cube_from_grid(G, N=33):
    """把 17³ 网格重采样成 33³ 的立方 LUT 数值（0..1）"""
    g = np.linspace(0.0, 255.0, N)
    pts = np.stack(np.meshgrid(g, g, g, indexing='ij'), -1).reshape(-1, 3)
    vals = interp(G, pts).reshape(N, N, N, 3)
    return np.clip(vals, 0.0, 255.0) / 255.0


def write_cube(path, cube, title='NCP residual'):
    N = cube.shape[0]
    with open(path, 'w', encoding='ascii', newline='\n') as f:
        f.write('TITLE "%s"\n' % title)
        f.write('LUT_3D_SIZE %d\n' % N)
        f.write('DOMAIN_MIN 0.0 0.0 0.0\nDOMAIN_MAX 1.0 1.0 1.0\n')
        for b in range(N):
            for g in range(N):
                for r in range(N):
                    v = cube[r, g, b]
                    f.write('%.6f %.6f %.6f\n' % (v[0], v[1], v[2]))


def apply_cube(img, cube, N=33, chunk=200000):
    """把 .cube 数值套到图上（三线性插值），返回新图 0..255"""
    g = np.linspace(0.0, 255.0, N)
    # 复用 interp：cube 是 (N,N,N,3)，取值按 0..255 索引
    flat = img.reshape(-1, 3)
    out = np.empty_like(flat)
    for s in range(0, flat.shape[0], chunk):
        e = min(s + chunk, flat.shape[0])
        out[s:e] = interp(cube * 255.0, flat[s:e])
    return np.clip(out.reshape(img.shape), 0, 255)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--v3', default=os.path.join(SAMP, 'real_v3'))
    ap.add_argument('--target', default=os.path.join(SAMP, 'real_target'))
    ap.add_argument('--size', type=int, default=420)
    ap.add_argument('--grid', type=int, default=17)
    ap.add_argument('--iters', type=int, default=120)
    ap.add_argument('--cv', action='store_true', help='做 2x2 分块交叉验证')
    ap.add_argument('--cv-iters', type=int, default=60)
    ap.add_argument('--only', default=None, help='逗号分隔的滤镜名')
    ap.add_argument('--preview', default=None, help='逗号分隔，生成三联预览')
    ap.add_argument('--out', default=os.path.join(SAMP, 'metrics_lut.csv'))
    a = ap.parse_args()

    os.makedirs(LUTD, exist_ok=True)
    os.makedirs(os.path.join(SAMP, 'lut_pairs'), exist_ok=True)
    want = set(x.strip().upper() for x in a.only.split(',')) if a.only else None
    prev = set(x.strip().upper() for x in a.preview.split(',')) if a.preview else set()
    cache = {}

    rows = []
    for slot, name in enumerate(NAMES, 1):
        if want and name not in want:
            continue
        pa, pb = find(a.v3, slot, name), find(a.target, slot, name)
        if not pa or not pb:
            continue
        A, B = load(pa, a.size), load(pb, a.size)
        if A.shape != B.shape:
            continue
        m = mask_of(A, B)
        src, dst = A[m], B[m]

        G = fit_lut(src, dst, N=a.grid, iters=a.iters)
        corr = np.clip(interp(G, src), 0, 255)
        before = _raw_metrics(src, dst)
        after = _raw_metrics(corr, dst)
        # 平均差按项目口径算全画面（real_gap.py 就是这么算的，剪掉的像素也算），
        # dE00 只算中间调（剪裁区色差无意义），两个指标口径不同要分开说明
        pred_all = np.clip(interp(G, A.reshape(-1, 3)), 0, 255).reshape(A.shape)
        mad_full0 = float(np.abs(A - B).mean())
        mad_full1 = float(np.abs(pred_all - B).mean())

        cv = ''
        if a.cv:
            des, mads = [], []
            for fm in folds(A.shape):
                tr = m & ~fm
                te = m & fm
                if tr.sum() < 20000 or te.sum() < 5000:
                    continue
                Gk = fit_lut(A[tr], B[tr], N=a.grid, iters=a.cv_iters)
                r = _raw_metrics(np.clip(interp(Gk, A[te]), 0, 255), B[te])
                des.append(r['de'])
                mads.append(r['mad'])
            cv = (np.mean(des), np.mean(mads)) if des else None

        # 兜底：拟合没带来收益（残差本来就低于信任域能分辨的量级，或像 BINARY
        # 那样只有两根色柱、格子几乎全空）时，宁可发一张恒等表，也不能让画质变差
        useful = after['de'] < before['de'] - 0.02
        if not useful:
            G = identity_grid(a.grid)
            pred_all = A
            after = before
            mad_full1 = mad_full0

        cube = cube_from_grid(G, 33)
        write_cube(os.path.join(LUTD, '%02d_%s.cube' % (slot, name)), cube,
                   'NCP residual %s' % name)
        if name in prev and useful:
            cache[name] = (A.copy(), B.copy(), cube)

        rows.append(dict(slot=slot, name=name, mono=slot in MONO, used=useful,
                         mad0=mad_full0, de0=before['de'], jnd0=before['jnd'],
                         mad1=mad_full1, de1=after['de'], jnd1=after['jnd'],
                         dl1=after['dl'], dc1=after['dc'],
                         cv_de=cv[0] if cv else float('nan'),
                         cv_mad=cv[1] if cv else float('nan')))
        print('%3d %-20s %6.2f -> %5.2f 级   dE00 %5.2f -> %4.2f   留出 %s%s'
              % (slot, name, mad_full0, mad_full1, before['de'], after['de'],
                 ('%.2f 级 / dE %.2f' % (cv[1], cv[0])) if cv else '—',
                 '' if useful else '   [不采用：无收益]'), flush=True)

    # 对照：所有支共用一张 LUT 会怎样（说明「每支一张」是必要的）
    if len(rows) >= 6 and not want:
        allsrc, alldst = [], []
        for r in rows:
            pa, pb = find(a.v3, r['slot'], r['name']), find(a.target, r['slot'], r['name'])
            A, B = load(pa, a.size), load(pb, a.size)
            mm = mask_of(A, B)
            allsrc.append(A[mm][::4])
            alldst.append(B[mm][::4])
        Gg = fit_lut(np.vstack(allsrc), np.vstack(alldst), N=a.grid, iters=a.iters)
        des, mads = [], []
        for r in rows:
            pa, pb = find(a.v3, r['slot'], r['name']), find(a.target, r['slot'], r['name'])
            A, B = load(pa, a.size), load(pb, a.size)
            mm = mask_of(A, B)
            rr = _raw_metrics(np.clip(interp(Gg, A[mm]), 0, 255), B[mm])
            des.append(rr['de'])
            mads.append(rr['mad'])
        print('-' * 72)
        print('共用一张 LUT（所有支汇总拟合）：%.2f 级 / dE00 %.2f'
              % (np.mean(mads), np.mean(des)))
        write_cube(os.path.join(LUTD, '00_共用_global.cube'),
                   cube_from_grid(Gg, 33), 'NCP residual pooled')

    for name, (A, B, cube) in cache.items():
        out = apply_cube(A, cube)
        strip = np.concatenate([B, A, out], axis=1)
        Image.fromarray(np.uint8(np.clip(strip, 0, 255))).save(
            os.path.join(SAMP, 'lut_pairs', 'lut_%s.jpg' % name), quality=92)

    with open(a.out, 'w', encoding='utf-8-sig') as f:
        f.write('slot,name,type,used,mad_before,dE00_before,jnd_before,'
                'mad_after,dE00_after,jnd_after,dL_after,dC_after,cv_dE00,cv_mad\n')
        for r in rows:
            f.write('%d,%s,%s,%d,%.4f,%.4f,%.2f,%.4f,%.4f,%.2f,%.4f,%.4f,%.3f,%.3f\n'
                    % (r['slot'], r['name'], 'mono' if r['mono'] else 'color',
                       1 if r['used'] else 0,
                       r['mad0'], r['de0'], r['jnd0'], r['mad1'], r['de1'],
                       r['jnd1'], r['dl1'], r['dc1'], r['cv_de'], r['cv_mad']))

    if rows:
        print('-' * 72)
        for k, lab in (('mad', '平均差（级）'), ('de', 'ΔE00'), ('jnd', '可辨像素%')):
            print('%-14s %6.2f -> %5.2f' % (lab, np.mean([r[k + '0'] for r in rows]),
                                            np.mean([r[k + '1'] for r in rows])))
        for tag, sel in (('彩色', [r for r in rows if not r['mono']]),
                         ('单色', [r for r in rows if r['mono']])):
            if sel:
                print('  %s %d 支       %6.2f -> %5.2f 级  dE00 %5.2f -> %4.2f'
                      % (tag, len(sel), np.mean([r['mad0'] for r in sel]),
                         np.mean([r['mad1'] for r in sel]),
                         np.mean([r['de0'] for r in sel]),
                         np.mean([r['de1'] for r in sel])))
        print('csv  -> %s' % a.out)
        print('cube -> %s' % LUTD)


def read_cube(path):
    """读 .cube：跳过 TITLE / LUT_3D_SIZE / DOMAIN_* 这些文本行"""
    rows, n = [], None
    for line in open(path, 'r', encoding='ascii', errors='ignore'):
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        if s.upper().startswith('LUT_3D_SIZE'):
            n = int(s.split()[1])
            continue
        if s[0].isalpha():
            continue
        rows.append([float(v) for v in s.split()[:3]])
    N = n or int(round(len(rows) ** (1.0 / 3.0)))
    arr = np.array(rows, dtype=np.float64).reshape(N, N, N, 3)
    # .cube 的行序是 R 变化最快、B 最慢，直接 reshape 得到的是 [b,g,r]；
    # 换回 [r,g,b] 才不会把红蓝对调（踩过一次：套到别的图上色偏到没边）
    return arr.transpose(2, 1, 0, 3)


def apply_main():
    """命令行套 LUT：

      python tools/lut_fit.py --apply a.cube in.jpg out.jpg
      python tools/lut_fit.py --apply-dir a.cube in/ out/
    """
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', nargs=3, metavar=('CUBE', 'IN', 'OUT'))
    ap.add_argument('--apply-dir', nargs=3, metavar=('CUBE', 'INDIR', 'OUTDIR'))
    a = ap.parse_args()
    if a.apply:
        cube_path, src, dst = a.apply
        cube = read_cube(cube_path)
        N = cube.shape[0]
        im = Image.open(src).convert('RGB')
        out = apply_cube(np.asarray(im, dtype=np.float64), cube, N=N)
        Image.fromarray(np.uint8(np.round(out))).save(dst, quality=95)
        print('%s -> %s  (%d^3 LUT)' % (src, dst, N))
        return

    cube_path, indir, outdir = a.apply_dir
    cube = read_cube(cube_path)
    N = cube.shape[0]
    os.makedirs(outdir, exist_ok=True)
    n = 0
    for f in sorted(os.listdir(indir)):
        stem, ext = os.path.splitext(f)
        if ext.lower() not in ('.jpg', '.jpeg', '.png', '.tif', '.tiff'):
            continue
        im = Image.open(os.path.join(indir, f)).convert('RGB')
        out = apply_cube(np.asarray(im, dtype=np.float64), cube, N=N)
        Image.fromarray(np.uint8(np.round(out))).save(
            os.path.join(outdir, stem + ext), quality=95)
        n += 1
    print('%d 张 -> %s  (%d^3 LUT)' % (n, outdir, N))


def _raw_metrics(pred, target):
    la, lb = to_lab(pred), to_lab(target)
    de = de2000(la, lb)
    ca = np.hypot(la[:, 1], la[:, 2])
    cb = np.hypot(lb[:, 1], lb[:, 2])
    return dict(mad=float(np.abs(pred - target).mean()), de=float(de.mean()),
                jnd=float((de > 2.3).mean() * 100.0),
                dl=float(np.abs(la[:, 0] - lb[:, 0]).mean()),
                dc=float(np.abs(ca - cb).mean()))


if __name__ == '__main__':
    if '--apply' in sys.argv or '--apply-dir' in sys.argv:
        apply_main()
    else:
        main()
