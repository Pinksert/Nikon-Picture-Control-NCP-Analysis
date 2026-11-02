#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_pack.py —— 给一张**没用过的新底片**同时套「我们的 NCP」与「官方 NP3」，
一次导出后就能量出拟合到底能不能泛化（不是只在 DSC_4484 上凑出来）。

为什么需要这个
--------------
此前所有数字（26 支 ΔE00、LUT 的 2.10）都是在 DSC_4484 这一张上拟合、又在这同一张上
量的。换一张构图、色调、影调分布都不同的底片，才看得出曲线/LUT 是学到了规律还是记住了图。

产出（一个目录，一次 Ctrl+A 即可导出）
--------------------------------------
    <out>/<tag>/00_PLAIN.NEF            无 sidecar，什么都不套（对照：证明批次确实生效）
    <out>/<tag>/01_DREAM__O.NEF         我们的 NCP（release 打底，release_v5 覆盖）
    <out>/<tag>/01_DREAM__T.NEF         官方 NP3（_filters_np3，按槽位对应）
    <out>/<tag>/NKSC_PARAM/*.NEF.nksc   每份 NEF 的配对 sidecar

导出后文件名就是 `01_DREAM__O.jpg` / `01_DREAM__T.jpg`，`validate_read.py` 直接认。

用法：
    python tools/validate_pack.py --nef "C:/.../DSC_8981.NEF" --tag 8981
"""
import argparse
import csv
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..', 'np3tool')))

import sidecar_batch as S                                     # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
BASE = os.path.normpath(os.path.join(ROOT, '..'))
TPL = os.path.join(BASE, 'lightroom', 'NKSC_PARAM', 'DSC_4484.NEF.nksc')
# ⚠️ 两侧必须用**各自的**模板，不能混用（2026-11-02 第一次就栽在这上面）：
#   O 侧（NCP 自定义优化校准）→ DSC_4484 那份：<PictureControl>=1，
#       SelectedPictureControl/SavedPicConProcess=1，六个 Apply* 全 false。
#   T 侧（NP3 官方最新优化校准）→ _render_target 那份：<PictureControl>=10，
#       Selected*/SavedPicConProcess=0，六个 Apply*（色相/饱和/曲线/锐化…）全 true，
#       且**没有** <CustomData>（内置滤镜只存一份 ExportData）。
# 拿 O 的模板去套 NP3：NX Studio 会把滤镜当成「不应用任何分项的自定义校准」，
# 26 张里有 22 张渲出来和「不套滤镜」一模一样（平均差 2.2 级，纯 JPEG 噪声），
# 只有 LANDSCAPE/MONOCHROME/NEUTRAL/VIVID 这四个内置名被它按名字认出来才生效。
TPL_T = os.path.join(BASE, '_render_target', 'NKSC_PARAM', '01_DREAM.NEF.nksc')
REL = os.path.join(ROOT, 'ncp', 'release', 'NIKON', 'CUSTOMPC')
REL5 = os.path.join(ROOT, 'ncp', 'release_v5', 'NIKON', 'CUSTOMPC')
NP3D = os.path.join(BASE, '_filters_np3')
META = os.path.join(ROOT, 'samples', 'metrics_real.csv')


def ncp_name(b):
    """NCP 布局里的名字：偏移 16，长 20；紧接的 36–37 是底子 ID。"""
    return b[16:36].rstrip(b'\0').decode('ascii', 'replace')


def np3_name(b):
    return b[24:44].rstrip(b'\0').decode('ascii', 'replace')


def load_ours():
    out = {}
    for f in sorted(os.listdir(REL)):
        if f.upper().endswith('.NCP'):
            b = open(os.path.join(REL, f), 'rb').read()
            if len(b) == 638:
                out[ncp_name(b)] = b
    # v5 覆盖 v3：只换掉改动过的那几支，其余保持不变
    n5 = 0
    for f in sorted(os.listdir(REL5)):
        if f.upper().endswith('.NCP'):
            b = open(os.path.join(REL5, f), 'rb').read()
            if len(b) == 638:
                out[ncp_name(b)] = b
                n5 += 1
    return out, n5


def load_np3():
    out = {}
    for f in sorted(os.listdir(NP3D)):
        if f.upper().endswith('.NP3'):
            b = open(os.path.join(NP3D, f), 'rb').read()
            out[np3_name(b)] = b
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--nef', required=True)
    ap.add_argument('--tag', required=True, help='批次短名，用在目录与文件名上')
    ap.add_argument('--out', default=os.path.join(BASE, '_validate_nef'))
    ap.add_argument('--template', default=TPL, help='O 侧模板（NCP，PC=1）')
    ap.add_argument('--template-t', default=TPL_T, help='T 侧模板（NP3，PC=10，Apply*=true）')
    a = ap.parse_args()

    ours, n5 = load_ours()
    tgt = load_np3()
    order = [(int(r['slot']), r['name'])
             for r in csv.DictReader(open(META, encoding='utf-8-sig'))]

    miss_o = [n for _, n in order if n not in ours]
    miss_t = [n for _, n in order if n not in tgt]
    if miss_o or miss_t:
        raise SystemExit('缺滤镜：我们 %s / 官方 %s' % (miss_o, miss_t))

    dst = os.path.abspath(os.path.join(a.out, a.tag))
    side = os.path.join(dst, 'NKSC_PARAM')
    os.makedirs(side, exist_ok=True)
    for f in os.listdir(dst):
        if f.lower().endswith('.nef'):
            os.remove(os.path.join(dst, f))
    for f in os.listdir(side):
        os.remove(os.path.join(side, f))

    tpl_o = S.template_text(a.template)
    tpl_t = S.template_text(a.template_t)

    # 两侧模板的形态闸门：六个 Apply* 与 PictureControl 编号必须与「历史上跑通的那批」一致
    def shape(tpl):
        import html
        u = html.unescape(tpl)
        return (S.get_field(u, 'PictureControl'),
                S.get_field(u, 'ApplyToneCurve'),
                S.get_field(u, 'ApplySaturationAdjustment'),
                S.get_field(u, 'ApplyHueAdjustment'),
                S.get_field(u, 'ApplyColorMode'),
                S.get_field(u, 'ApplySharpening'),
                S.get_field(u, 'ApplyDigitalColorEffectFilter'),
                S.get_field(u, 'SavedPicConProcess'))
    so, st_ = shape(tpl_o), shape(tpl_t)
    print('O 侧模板形态：PC=%s Apply曲线=%s 饱和=%s 色相=%s 色彩模式=%s 锐化=%s 数码滤镜=%s 处理=%s' % so)
    print('T 侧模板形态：PC=%s Apply曲线=%s 饱和=%s 色相=%s 色彩模式=%s 锐化=%s 数码滤镜=%s 处理=%s' % st_)
    if so[0] != '1':
        raise SystemExit('O 侧模板的 <PictureControl> 不是 1，套 NCP 会失效：%s' % (so[0],))
    if st_[0] != '10' or st_[1] != 'true':
        raise SystemExit('T 侧模板不是 NP3 形态（PC=%s，ApplyToneCurve=%s），'
                         '套官方滤镜会渲成「拍摄时设定」' % (st_[0], st_[1]))

    def emit(stem, body, tpl=None):
        nef = os.path.join(dst, stem + '.NEF')
        shutil.copy2(a.nef, nef)
        os.utime(nef, None)                       # 刷 mtime，别让 NX 认旧缓存
        if body is None:
            return
        txt = S.embed_data(tpl, body, slot02=True)
        S.write_sidecar(os.path.join(side, stem + '.NEF.nksc'), txt)
        back = S.template_text(os.path.join(side, stem + '.NEF.nksc'))
        got = S.export_data(back)
        ref = body
        assert got == ref or (len(got) == len(ref) and
                              ref[4:8] == b'\x00\x00\x00\x01' and
                              got[:38] == ref[:38] and got[39:] == ref[39:]), \
            '%s 往返被改坏' % stem

    emit('00_PLAIN', None)
    print('%-14s %-6s %-10s %s' % ('文件', '槽', '底子', '说明'))
    print('-' * 62)
    print('%-14s %-6s %-10s %s' % ('00_PLAIN', '-', '-', '不套任何滤镜（对照）'))
    n = 0
    for slot, name in order:
        emit('%02d_%s__O' % (slot, name), ours[name], tpl_o)
        try:
            body_t = S.fixup(tgt[name])
        except ValueError as e:
            print('  %-12s 官方 NP3 补齐失败：%s' % (name, e))
            continue
        emit('%02d_%s__T' % (slot, name), body_t, tpl_t)
        n += 1
        base = int.from_bytes(ours[name][36:38], 'big')
        print('%-14s %-6d 0x%04X     O 与 T 成对' % (name, slot, base))
    print('-' * 62)
    print('%d 组 × 2 + 1 张对照 = %d 份 NEF，目录：%s' % (n, n * 2 + 1, dst))
    print('我们的 NCP：release 打底，其中 %d 支用 release_v5 覆盖' % n5)
    print('\n下一步：整包已写完，现在可以让 NX Studio 打开这个目录，Ctrl+A → 导出。')
    print('     文件名选「与源文件同名」，sRGB，长边 ≥1600，品质 ≥90。')


if __name__ == '__main__':
    main()
