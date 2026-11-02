#!/usr/bin/env python3
"""sidecar 到底为什么不生效：把「名字太长」这个猜测排掉，直接做 4 格对照。

背景：2026-11-02 上午那批 `_probe_range/NKSC_PARAM/R1…R8` 在 NX Studio 里
8 张全渲染成同一个滤镜、面板写 SILENCE。后来手工逐个套用，NX Studio 自己
生成了 `manual/NKSC_PARAM/P1…P8.NEF.nksc`（17164 B，我们的是 17122 B）。

把两份 sidecar 的 base64 抹掉再做差异，**只剩两处不同**：

  1. `<rdf:Description rdf:about="">`  vs  `rdf:about="core-sidear-tags/1.0"`
  2. `ExposureSettings` 下 6 个 `Apply*` 标志：我们是 false，NX Studio 是 true
     （ToneCurve / ColorMode / HueAdjustment / Sharpening /
       SaturationAdjustment / DigitalColorEffectFilter）

所以「文件名太长」不是原因：路径 87 字符、文件名 24 字符，离 260 很远，
而且两次都在同一个父目录下、sidecar 与 NEF 名字严格配对。

本脚本就造 4 格，把这两个变量拆开：

  Q1  原样（对照，= 上午失败的那批）
  Q2  只改 rdf:about
  Q3  只改 Apply* 标志
  Q4  两个都改（= NX Studio 自己写出来的形态）

四格塞的是同一支滤镜 `P4 TOY+6`（彩度约 +78%，肉眼一眼能看出来）。
打开目录只看缩略图即可判定：谁跟 Q1 不一样，就说明谁被读进去了。

用法：
    python tools/sidecar_flag_test.py            # 生成 _probe_flag/
    python tools/sidecar_flag_test.py --out D:/x
"""
import argparse
import html
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sidecar_batch as S

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
TPL = os.path.join(ROOT, '..', 'lightroom', 'NKSC_PARAM', 'DSC_4484.NEF.nksc')
NEF = os.path.join(ROOT, '..', 'lightroom', 'DSC_4484.NEF')
NCP = os.path.join(ROOT, '..', '_probe_range', 'ncp', 'P4 TOY+6.NCP')

ABOUT = 'core-sidear-tags/1.0'
APPLY_ON = ('ToneCurve', 'ColorMode', 'HueAdjustment',
            'Sharpening', 'SaturationAdjustment', 'DigitalColorEffectFilter')


def set_about(txt):
    """rdf:about 改成 NX Studio 自己写的那个值（注意 Nikon 把它拼成了 sidear）。"""
    out, n = re.subn(r'(rdf:Description\s+rdf:about=")[^"]*(")',
                     lambda m: m.group(1) + ABOUT + m.group(2), txt, count=1)
    if n == 0:
        raise SystemExit('模板里找不到 rdf:Description rdf:about')
    return out


def set_apply(txt, names=APPLY_ON, value='true'):
    """把 ExposureSettings 里的 Apply* 逐个改成 true。

    两种形态都处理：转义（&lt;）与裸 XML。模板必须是转义形态，但为了稳妥都覆盖。
    """
    for form in (('&lt;', '&gt;'), ('<', '>')):
        lt, gt = form
        for n in names:
            pat = re.compile(r'(%s%s%s)[^%s]*(%s/%s%s)'
                             % (lt, 'Apply' + n, gt, gt[0], lt, 'Apply' + n, gt))
            txt = pat.sub(lambda m: m.group(1) + value + m.group(2), txt, count=1)
    return txt


VARIANTS = [
    ('Q1', False, False, '原样（= 上午失败那批）'),
    ('Q2', True, False, '只改 rdf:about'),
    ('Q3', False, True, '只改 Apply* 标志'),
    ('Q4', True, True, '两处都改（= NX Studio 自己的形态）'),
]

# 锚点：NX Studio 亲手写的、同一支 TOY +6 的 sidecar（P4 那份）。
# 它要是也渲染成 SILENCE，说明 sidecar 这条路过不了 —— 与我们的生成逻辑无关。
ANCHOR = ('Q5', os.path.join(ROOT, '..', '_probe_range', 'manual', 'NKSC_PARAM',
                             'P4.NEF.nksc'), 'NX 亲手写的同一支 TOY+6')

# 第二轮：只改文件名，内容与 Q1 逐字节相同。
# 2026-11-02 上午那批命名为 R1_SILENCE_sat-6 / R3_DENIM_sat+6 这类长名，
# 用户怀疑是名字太长。四格塞同一支 TOY+6：谁render 出来淡，就是名字把它挂掉了。
NAMES = [
    ('R4_TOY_sat+6', '原失败名（长、带 + 号）'),
    ('R4_TOY_sat6', '同长度，去掉 + 号'),
    ('N3', '短名'),
    ('N4_THIS_IS_A_VERY_LONG_PROBE_FILENAME_FOR_TESTING_NAME_LENGTH_LIMITS_TOY_PLUS6',
     '超长名（68 字符）'),
]


def names_pack(out, nef, tpl):
    side = os.path.join(out, 'NKSC_PARAM')
    os.makedirs(side, exist_ok=True)
    for f in os.listdir(side):
        os.remove(os.path.join(side, f))
    for f in os.listdir(out):
        if f.lower().endswith('.nef'):
            os.remove(os.path.join(out, f))
    ncp = open(NCP, 'rb').read()
    txt = S.embed_data(tpl, ncp, slot02=True)
    print('%-70s %-6s %s' % ('文件名', '路径长', '说明'))
    print('-' * 96)
    for stem, why in NAMES:
        shutil.copy2(nef, os.path.join(out, stem + '.NEF'))
        S.write_sidecar(os.path.join(side, stem + '.NEF.nksc'), txt)
        full = os.path.join(side, stem + '.NEF.nksc')
        print('%-70s %-6d %s' % (stem + '.NEF', len(full), why))
    print()
    print('四份 sidecar 内容**完全相同**（同一支 TOY +6，彩度 +78%），只有文件名不同。')
    print('NX Studio 打开 %s，看 4 张缩略图：一样浓 → 名字无关；哪张淡 → 名字有问题。' % out)


def check(txt, about_fix, apply_fix):
    """回读校验：该改的改了、不该改的没动。"""
    esc = html.unescape(txt)
    ab = re.search(r'<rdf:Description rdf:about="([^"]*)"', esc)
    flags = dict(re.findall(r'<Apply(\w+)>(\w+)</Apply\1>', esc))
    got_about = (ab.group(1) == ABOUT) if ab else False
    got_apply = all(flags.get(n) == 'true' for n in APPLY_ON)
    assert got_about == about_fix, 'rdf:about 与预期不符'
    assert got_apply == apply_fix, 'Apply* 与预期不符'
    # 滤镜数据必须原封不动
    c = S.custom_data(txt)
    assert c is not None and len(c) == 638, 'CustomData 长度不对'
    return S.filt_name(c), flags


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=None)
    ap.add_argument('--nef', default=NEF)
    ap.add_argument('--mode', choices=('flags', 'names'), default='flags',
                    help='flags=拆 about/Apply*；names=只改文件名')
    a = ap.parse_args()

    if a.mode == 'names':
        out = os.path.abspath(a.out or os.path.join(ROOT, '..', '_probe_name'))
        names_pack(out, a.nef, S.template_text(TPL))
        return

    out = os.path.abspath(a.out or os.path.join(ROOT, '..', '_probe_flag'))
    side = os.path.join(out, 'NKSC_PARAM')
    os.makedirs(side, exist_ok=True)
    for f in os.listdir(side):
        os.remove(os.path.join(side, f))
    for f in os.listdir(out):
        if f.lower().endswith('.nef'):
            os.remove(os.path.join(out, f))

    tpl = S.template_text(TPL)
    ncp = open(NCP, 'rb').read()
    print('模板 %s' % os.path.basename(TPL))
    print('滤镜 %s  (%d B, 第 43 字节 = %+d)'
          % (os.path.basename(NCP), len(ncp), ncp[43] - 0x80))
    print()
    print('%-4s %-8s %-8s %-6s %-22s %s' % ('格', 'about', 'Apply*', '大小', '改动', '自检'))
    print('-' * 86)
    for stem, ab, ap_, why in VARIANTS:
        t = tpl
        if ab:
            t = set_about(t)
        if ap_:
            t = set_apply(t)
        t = S.embed_data(t, ncp, slot02=True)
        ncp_name, flags = check(t, ab, ap_)

        shutil.copy2(a.nef, os.path.join(out, stem + '.NEF'))
        path = os.path.join(side, stem + '.NEF.nksc')
        S.write_sidecar(path, t)

        # 落盘后再从文件读一遍，确认没有写坏
        back = S.custom_data(S.template_text(path))
        assert back == S.custom_data(t), '%s 往返被改坏' % stem
        print('%-4s %-8s %-8s %-6d %-22s %s'
              % (stem, '改' if ab else '原', '改' if ap_ else '原',
                 os.path.getsize(path), why, ncp_name))

    # 锚点：整份照抄 NX Studio 自己写的 sidecar，只换名字
    stem, src, why = ANCHOR
    shutil.copy2(a.nef, os.path.join(out, stem + '.NEF'))
    shutil.copy2(src, os.path.join(side, stem + '.NEF.nksc'))
    t = S.template_text(os.path.join(side, stem + '.NEF.nksc'))
    print('%-4s %-8s %-8s %-6d %-22s %s'
          % (stem, '=', '=', os.path.getsize(os.path.join(side, stem + '.NEF.nksc')),
             why, S.filt_name(S.custom_data(t))))

    print()
    print('目录：%s' % out)
    print('下一步：NX Studio 打开这个目录，**什么都别动**，只看 5 张缩略图。')
    print('        Q2/Q3/Q4 里谁明显比 Q1 浓（TOY +6 约 +78% 彩度），谁就被读进去了。')
    print('        Q5 是 NX 自己写的同一支：它也淡，说明整条路不通；它浓，说明差在我们生成的字节上。')


if __name__ == '__main__':
    main()
