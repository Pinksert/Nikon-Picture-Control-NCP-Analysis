# -*- coding: utf-8 -*-
"""
sidecar_batch.py —— 用 NX Studio 的 .nksc 调整文件批量套用不同滤镜

背景
----
NX Studio 没有「批处理」菜单（语言文件里 BATCH 只出现在警告文案），
一次导出只能对选中的照片各用各的当前设置。
但它的调整文件（sidecar，*.NEF.nksc，XMP 文本）里
``nikon::PictureControl`` 过滤器的 ``<ExportData>`` **内嵌滤镜文件本体**（base64），
且 sidecar 与文件名无绑定（rdf:about 为空、无 OriginalFileName）。

于是可以这样批量：
    同一张 NEF 复制 N 份，每份配一个只改了 ExportData 的 sidecar，
    在 NX Studio 里全选 → 导出一次，得到 N 张分别套了不同滤镜的图。

实测结论（2026-10-31）
----------------------
* sidecar 内嵌的 392 字节与磁盘 NP3 文件**前 80 字节逐字节相同**（仅版本串 0300/0310 不同）
  → 里面就是磁盘滤镜文件本体，不是私有序列化格式。
* 两个样例的 ``<PictureControl>`` 编号：DREAM=14、PORTRAIT=10。
  NCP（自定义优化校准）的编号未知，需要从用户导出的模板里读。

两种用法
--------
1) probe —— 生成 3 张零风险验证包，用来判定「NX Studio 到底读不读 sidecar」：:

       python sidecar_batch.py probe

2) make —— 以用户导出的模板 sidecar 为骨架，批量替换滤镜，生成 N 份 NEF+ sidecar::

       python sidecar_batch.py make --template T.NEF.nksc --nef src.NEF \\
              --filters d300/ncp/release/NIKON/CUSTOMPC --out _render_v3

   模板必须是 NX Studio 自己生成的（这样 PictureControl 编号、卡结构都对）；
   本脚本不凭空构造滤镜字节，只做「替换 NX Studio 写过的东西」。

依赖：仅标准库。
"""
import argparse
import base64
import html
import os
import re
import shutil
import sys

# ---------------------------------------------------------------- 基础读写

def read_sidecar(path):
    """返回 (原始文本, 已 unescape 的文本)。XMP 里 NineEdits 是转义过的 XML。"""
    raw = open(path, encoding='utf-8', errors='replace').read()
    return raw, html.unescape(raw)


def embed_data(sidecar_text, filt_bytes):
    """把滤镜文件字节塞进 <ExportData>，同步 <ExportDataSize>。

    注意原文本里 NineEdits 是 HTML 转义过的（&lt;filter ...），
    所以替换必须发生在转义后的文本上，并且 base64 里不能有换行以外的东西。
    """
    b64 = base64.b64encode(filt_bytes).decode('ascii')
    # 原 sidecar 的 base64 是每 64 字符一行，照抄格式，减小 diff
    b64 = '\n'.join(b64[i:i + 64] for i in range(0, len(b64), 64))
    pat = re.compile(r'(<ExportData>).*?(</ExportData>)', re.S)
    if not pat.search(sidecar_text):
        raise SystemExit('模板里找不到 <ExportData>，不是有效的调整文件')
    out = pat.sub(lambda m: m.group(1) + b64 + m.group(2), sidecar_text, count=1)
    out = re.sub(r'(<ExportDataSize>)\d+(</ExportDataSize>)',
                 lambda m: m.group(1) + str(len(filt_bytes)) + m.group(2),
                 out, count=1)
    return out


def set_field(sidecar_text, tag, value):
    pat = re.compile(r'(<%s>)[^<]*(</%s>)' % (tag, tag))
    if not pat.search(sidecar_text):
        return sidecar_text
    return pat.sub(lambda m: m.group(1) + str(value) + m.group(2), sidecar_text, count=1)


def get_field(sidecar_text, tag):
    m = re.search(r'<%s>([^<]*)</%s>' % (tag, tag), sidecar_text)
    return m.group(1) if m else None


def export_data(sidecar_text):
    s = html.unescape(sidecar_text)
    m = re.search(r'<ExportData>(.*?)</ExportData>', s, re.S)
    if not m:
        return None
    return base64.b64decode(''.join(m.group(1).split()))


def filt_name(b):
    """滤镜字节里的名字。

    两种布局，名字偏移不同，逐个试，取那个像名字的：
      NP3（云创/新系统）：NCP\\0 + 4B(0x100) + 4B(4) + 版本4B + 4B(0x200) + 4B(20) + 名字20B
                          → 名字在魔数后第 20 字节
      NCP（自定义优化校准）：NCP\\0 + 4B(1) + 4B(36) + 版本4B + 名字20B
                          → 名字在魔数后第 12 字节
    """
    # 魔数后第 4 字节区分两种格式：
    #   NCP（自定义优化校准）b'\x00\x00\x00\x01' → 名字在魔数后第 12 字节
    #   NP3（云创滤镜）      b'\x00\x00\x01\x00' → 名字在魔数后第 20 字节
    # 不能靠「哪个像名字」去猜：长名字（如 MELANCHOLIC）会被短偏移截出尾巴 "LIC"
    off = 12 if b[4:8] == b'\x00\x00\x00\x01' else 20
    chunk = b[4 + off: 4 + off + 20].rstrip(b'\x00')
    t = chunk.decode('ascii', 'replace')
    return t if sum(1 for c in t if c.isalnum() or c in ' _-') >= 3 else '?'


def write_sidecar(path, text):
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)


def copy_nef(src, dst):
    if os.path.exists(dst):
        return False
    shutil.copy2(src, dst)
    return True


# ---------------------------------------------------------------- probe

def cmd_probe(args):
    """生成 3 张验证包，判定 NX Studio 是否读取 sidecar。"""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    tpl = os.path.join(root, 'lightroom', 'NKSC_PARAM', 'DSC_4484.NEF.nksc')
    nef = os.path.join(root, 'lightroom', 'DSC_4484.NEF')
    out = os.path.join(root, '_sidecar_probe')
    for p in (tpl, nef):
        if not os.path.exists(p):
            raise SystemExit('缺少素材：%s' % p)
    os.makedirs(out, exist_ok=True)

    _, tpl_txt = read_sidecar(tpl)
    base = export_data(tpl_txt)          # 模板内嵌的 DREAM（NX Studio 生成）

    plan = [
        # (文件名, 滤镜字节, PictureControl 编号, 期望在 NX Studio 里看到)
        ('T1', base, 14, 'DREAM（模板原样，内嵌 392 字节）'),
        ('T2', open(os.path.join(root, '滤镜', 'DREAM.NP3'), 'rb').read(),
         14, 'DREAM（换成磁盘 NP3，248 字节）'),
        ('T3', open(os.path.join(root, '滤镜', 'MONOCHROME.NP3'), 'rb').read(),
         13, 'MONOCHROME（黑白，13 是推测的编号）'),
    ]

    print('验证包目录：%s\n' % out)
    for name, fb, pid, want in plan:
        txt = embed_data(tpl_txt, fb)
        txt = set_field(txt, 'PictureControl', pid)
        copy_nef(nef, os.path.join(out, name + '.NEF'))
        write_sidecar(os.path.join(out, name + '.NEF.nksc'), txt)
        print('  %-4s 内嵌 %-10s %3d 字节  PictureControl=%-3d  期望显示：%s'
              % (name, filt_name(fb), len(fb), pid, want))

    print("""
怎么判定（在 NX Studio 里打开 %s 文件夹，看三张缩略图的「优化校准」名）：

  T1 显示 STANDARD 且 T2 也 STANDARD  →  sidecar 根本没被读取，方案作废
  T1 显示 DREAM、T2 显示 STANDARD     →  读了 sidecar，但磁盘滤镜文件不能直接塞
                                          （必须拿 NX Studio 自己生成的当模板）
  T1 显示 DREAM、T2 显示 DREAM        →  完全可行，磁盘滤镜文件可直接内嵌
  T3 的结果额外告诉我们编号和 ExportData 谁优先：
      显示 MONOCHROME → 以 ExportData 为准（批量时编号可以沿用模板，最省事）
      显示 DREAM      → 以 PictureControl 编号为准（批量时必须给对编号）

前提：编辑 → 首选项 → 「将调整、标签和评级内容保存到附属文件(照片编辑历史记录)」要勾上，
      否则 NX Studio 会把调整写回 NEF 里，sidecar 就不会被读。
""" % out)


# ---------------------------------------------------------------- make

def cmd_make(args):
    tpl_path = os.path.abspath(args.template)
    nef = os.path.abspath(args.nef)
    fdir = os.path.abspath(args.filters)
    out = os.path.abspath(args.out)
    for p in (tpl_path, nef, fdir):
        if not os.path.exists(p):
            raise SystemExit('找不到：%s' % p)
    os.makedirs(out, exist_ok=True)

    _, tpl_txt = read_sidecar(tpl_path)
    pid = get_field(tpl_txt, 'PictureControl')
    print('模板：%s' % os.path.basename(tpl_path))
    print('  模板内嵌滤镜 = %s（%d 字节），PictureControl = %s'
          % (filt_name(export_data(tpl_txt) or b''),
             len(export_data(tpl_txt) or b''), pid))

    files = sorted(f for f in os.listdir(fdir)
                   if f.upper().endswith(('.NCP', '.NP2', '.NP3')))
    if not files:
        raise SystemExit('滤镜目录里没有文件：%s' % fdir)
    print('  滤镜 %d 个，源 NEF：%s\n' % (len(files), os.path.basename(nef)))

    for i, fn in enumerate(files, 1):
        stem = os.path.splitext(fn)[0]
        fb = open(os.path.join(fdir, fn), 'rb').read()
        # PictureControl 编号沿用模板，不猜：
        # 同一批滤镜（都是自定义优化校准）编号应当一致，猜错反而会出事
        txt = embed_data(tpl_txt, fb)
        if not args.dry_run:
            copy_nef(nef, os.path.join(out, stem + '.NEF'))
            write_sidecar(os.path.join(out, stem + '.NEF.nksc'), txt)
        ok = export_data(txt) == fb
        print('  %02d %-22s %-11s %3d 字节  往返%s'
              % (i, stem, filt_name(fb), len(fb), 'OK' if ok else '失败'))

    print("""
生成完毕：%s
  %d 份 NEF + %d 个同名 sidecar（命名规则：原文件全名 + .nksc）

在 NX Studio 里：
  1. 确认首选项勾了「保存到附属文件」
  2. 打开这个文件夹
  3. 如果缩略图没变，选「编辑 → 重新读取调整信息」（具体措辞以界面为准）
  4. Ctrl+A 全选 → 文件 → 导出(&E)... → sRGB、长边 600px、质量≥90
  5. 文件名选「与源文件同名」，导出的就是 01_DREAM.jpg … 30_VIVID.jpg
""" % (out, len(files), len(files)))


def main():
    ap = argparse.ArgumentParser(description='NX Studio sidecar 批量套用滤镜')
    sub = ap.add_subparsers(dest='cmd')

    sub.add_parser('probe', help='生成 3 张验证包，判定 sidecar 是否被读取')

    m = sub.add_parser('make', help='以模板 sidecar 批量生成 NEF + sidecar')
    m.add_argument('--template', required=True, help='NX Studio 导出的模板 .nksc')
    m.add_argument('--nef', required=True, help='源 RAW')
    m.add_argument('--filters', required=True, help='滤镜目录（.NCP/.NP2/.NP3）')
    m.add_argument('--out', required=True, help='输出目录')
    m.add_argument('--dry-run', action='store_true',
                   help='只检查能否正确嵌入并打印清单，不写文件')

    args = ap.parse_args()
    if args.cmd == 'probe':
        cmd_probe(args)
    elif args.cmd == 'make':
        cmd_make(args)
    else:
        ap.print_help()


if __name__ == '__main__':
    main()
