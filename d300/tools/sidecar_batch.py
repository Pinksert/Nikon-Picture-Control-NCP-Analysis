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

# ------------------------------------------------------- 磁盘文件 → sidecar 字节

# NX Studio 写进 sidecar 的不是磁盘滤镜文件原样，而是「规范化」后的形态：
#   磁盘文件只到卡 0x16（22 张），NX Studio 额外补了卡 0x17–0x20 共 144 字节。
# 这 144 字节在 DREAM / PORTRAIT 两个样例里**完全相同**，是固定补齐段。
# 实测（2026-10-31）：磁盘文件 + 这段 + 结束标记，并把版本串 0300 改成 0310，
#   与 NX Studio 生成的字节**逐字节完全一致**（0 差异）。
# 这正是直接塞磁盘文件会失败的原因 —— 少了这段补齐卡。
FIX_HEX = (
    '0000170000000002ff040000180000000002ff04000019000000000280010000'
    '1a0000000002800100001b0000000002800100001c0000000002800100001d00'
    '00000002800100001e0000000002800100001f000000001c8080808080808080'
    '8080808080808080808080808080808001010100000020000000001480008080'
    '800080808000808001010100b2018001'
)
FIXUP_TAIL = bytes.fromhex(FIX_HEX)          # 144 字节
FIXUP_END = b'\x00\x00\x00\x00'              # 结束标记
FIXUP_BODY = 244                             # 卡 0x01–0x16 的截止偏移


def fixup(disk_bytes):
    """磁盘滤镜文件 → NX Studio sidecar 能接受的字节（仅对 NP3 布局有效）。

    NP3 布局：b'NCP\\0' + 卡0x01(版本4B) + 卡0x02(名字20B) + 卡0x03..0x16(各2B)
              → 卡区截止在 244 字节
    """
    if disk_bytes[4:8] == b'\x00\x00\x00\x01':
        raise ValueError('这是 NCP 布局（卡编号体系不同），fixup 不适用，'
                         '请先用 inspect 看 NX Studio 实际存了什么')
    b = bytearray(disk_bytes[:FIXUP_BODY])
    b[14] = ord('1')                          # 版本串 0300 → 0310
    return bytes(b) + FIXUP_TAIL + FIXUP_END


# ---------------------------------------------------------------- 基础读写

SLOT_NAMES = ['DREAM', 'MORNING', 'POP', 'SUNDAY', 'SOMBER', 'DRAMA', 'SILENCE', 'BLEACH', 'MELANCHOLIC', 'PURE', 'DENIM', 'TOY', 'SEPIA', 'BLUE', 'RED', 'PINK', 'CHARCOAL', 'GRAPHITE', 'BINARY', 'CARBON', 'FLAT', 'FLAT_MONOCHROME', 'DEEPTONE_MONOCHROME', 'RICH_TONE_PORTRAIT', 'FLEXIBLE_COLOR', 'LANDSCAPE', 'MONOCHROME', 'NEUTRAL', 'STANDARD', 'VIVID']   # PICCON01..30 的正式名字（与 release/README.md 一致）


def slot_stem(fn):
    """PICCON01.NCP → 01_DREAM（real_render_check.py 期望的命名）。"""
    stem = os.path.splitext(fn)[0]
    m = re.match(r'^PICCON(\d{1,2})$', stem, re.I)
    if m:
        n = int(m.group(1))
        if 1 <= n <= len(SLOT_NAMES):
            return '%02d_%s' % (n, SLOT_NAMES[n - 1])
    return stem


def read_sidecar(path):
    """返回 (原始文本, 已 unescape 的文本)。XMP 里 NineEdits 是转义过的 XML。"""
    raw = open(path, encoding='utf-8', errors='replace').read()
    return raw, html.unescape(raw)


def embed_data(sidecar_text, filt_bytes, slot02=True):
    """把滤镜字节塞进 <ExportData> 与 <CustomData> —— 两处都要写。

    实测（2026-10-31）：套用「自定义优化校准」（导入的 NCP）时，NX Studio 会在
    sidecar 里写**两份**滤镜数据，而套用内置滤镜只有一份：

        <Export><ExportData>   ← 当前应用态：第 38 字节被写成 0x02
        <Custom><CustomData>   ← 滤镜原始定义：与磁盘文件一致（该字节 0x00）

    只替换其中一份 → NX Studio 直接回落成 STANDARD（V4 探针失败的真因）。
    """
    e = bytearray(filt_bytes)
    c = bytearray(filt_bytes)
    if slot02 and len(e) > 38:
        e[38] = 0x02                       # 复刻 NX Studio 应用态的那个字节
    out, ok1 = _embed_one(sidecar_text, 'ExportData', bytes(e))
    out, ok2 = _embed_one(out, 'CustomData', bytes(c))
    if not ok1:
        raise SystemExit('模板里找不到 <ExportData>，不是有效的调整文件')
    return out


def _embed_one(txt, tag, data):
    """替换单个 <tag>：base64 每 60 字符一行，与 NX Studio 的排版一致。

    模板里的 XMP 是 HTML 转义过的（&lt;ExportData&gt;、换行 &#xA;），
    两种形态都支持：按输入文本自动判断，并保持原来的形态输出。
    """
    esc = '&lt;' in txt
    lt, gt = ('&lt;', '&gt;') if esc else ('<', '>')
    nl = '&#xA;' if esc else '\n'
    s = base64.b64encode(data).decode('ascii')
    chunk = [s[k:k + 60] for k in range(0, len(s), 60)]
    blk = nl.join(chunk) + nl               # 末尾也带一个换行，与亲生模板一致
    pat = re.compile(r'(%s%s%s).*?(%s/%s%s)' % (lt, tag, gt, lt, tag, gt), re.S)
    if not pat.search(txt):
        return txt, False
    out = pat.sub(lambda m: m.group(1) + blk + m.group(2), txt, count=1)
    # <ExportDataSize> 记的是 base64 文本长度（含全部换行），不是滤镜字节数
    size = len(s) + len(chunk)
    sp = re.compile(r'(%s%sSize%s)\d+(%s/%sSize%s)' % (lt, tag, gt, lt, tag, gt))
    out = sp.sub(lambda m: m.group(1) + str(size) + m.group(2), out, count=1)
    return out, True



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


def custom_data(sidecar_text):
    """<CustomData> 里的滤镜字节（自定义优化校准才有这一处）。"""
    s = html.unescape(sidecar_text)
    m = re.search(r'<CustomData>(.*?)</CustomData>', s, re.S)
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
        ('V1', base, 14, 'DREAM（模板原样，NX Studio 亲生的 392 字节）'),
        ('V2', fixup(open(os.path.join(root, '滤镜', 'DREAM.NP3'), 'rb').read()),
         14, 'DREAM（磁盘 NP3 经 fixup 补齐，应还原成与 V1 相同）'),
        ('V3', fixup(open(os.path.join(root, '滤镜', 'MONOCHROME.NP3'), 'rb').read()),
         13, 'MONOCHROME（黑白，一眼可辨；13 是推测编号）'),
        # NCP 是另一套布局（2 张大卡），fixup 不适用。先按「直接塞本体」试一次：
        # 若 V4 显示 DREAM，整条路就通了，连模板都不用做。
        ('V4', open(os.path.join(root, 'd300', 'ncp', 'release', 'NIKON',
                                 'CUSTOMPC', 'PICCON01.NCP'), 'rb').read(),
         14, 'DREAM（我们的 v3 NCP，638 字节，直接塞本体）'),
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

  V1 显示 STANDARD                    →  sidecar 根本没被读取，方案作废
  V1 显示 DREAM、V2/V3 也各自正确      →  fixup 补齐公式实机有效，可以批量
  V1 显示 DREAM、V2 显示 STANDARD      →  读了 sidecar，但补齐公式不对

V3 顺带告诉我们 <PictureControl> 编号和 <ExportData> 谁优先：
      显示 MONOCHROME → 以 ExportData 为准（批量时编号沿用模板即可，最省事）
      显示 DREAM      → 以编号为准（13 是推测值，猜错就会显示错滤镜）

V4 是关键：我们的产物是 NCP（另一套布局，2 张大卡，638 字节），fixup 对它不适用。
      显示 DREAM      → NCP 可以直接塞本体，整条路通了，不用做模板
      显示 STANDARD   → 需要你套用一个 NCP 后导出 sidecar 当模板，我用 inspect 分析

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

    raw_txt, tpl_txt = read_sidecar(tpl_path)
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
        stem = slot_stem(fn)
        fb = open(os.path.join(fdir, fn), 'rb').read()
        # PictureControl 编号沿用模板，不猜：
        # 同一批滤镜（都是自定义优化校准）编号应当一致，猜错反而会出事
        used = fb
        if args.fixup:
            try:
                used = fixup(fb)
            except ValueError as e:
                print('  %02d %-22s 跳过：%s' % (i, stem, e))
                continue
        txt = embed_data(raw_txt, used, slot02=not args.no_slot_byte)
        if not args.dry_run:
            copy_nef(nef, os.path.join(out, stem + '.NEF'))
            write_sidecar(os.path.join(out, stem + '.NEF.nksc'), txt)
        got = export_data(txt)
        # ExportData 的第 38 字节会被写成 0x02（应用态），比对时跳过这一位
        ok = (got == used) or (
            len(got) == len(used) and got[:38] == used[:38] and got[39:] == used[39:])
        cb = custom_data(txt)
        ok2 = (cb is None) or (cb == used)
        print('  %02d %-22s %-20s %3d→%-3d 字节  往返%s'
              % (i, stem, filt_name(fb), len(fb), len(used),
                 'OK' if (ok and ok2) else '失败(Export%s/Custom%s)'
                 % ('OK' if ok else 'X', 'OK' if ok2 else 'X')))

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


def cmd_inspect(args):
    """解析 NX Studio 导出的模板，报告它到底存了什么、能不能批量构造。"""
    import struct
    path = os.path.abspath(args.template)
    _, txt = read_sidecar(path)
    d = export_data(txt)
    print('模板：%s' % os.path.basename(path))
    print('  <PictureControl>      = %s' % get_field(txt, 'PictureControl'))
    print('  <ExportDataSize>      = %s（实际 %d 字节）'
          % (get_field(txt, 'ExportDataSize'), len(d)))
    print('  滤镜名字              = %s' % filt_name(d))
    print('  魔数                  = %r' % d[:4])
    print('  第 5–8 字节           = %s  → %s'
          % (d[4:8].hex(), 'NCP 布局' if d[4:8] == b'\x00\x00\x00\x01' else 'NP3 布局'))
    print('  版本串                = %r' % d[12:16])

    off, n = 4, 0
    print('  卡结构：')
    while off + 8 <= len(d) and n < 40:
        t, ln = struct.unpack_from('>II', d, off)
        if t == 0:
            print('    @%-4d 结束标记' % off)
            break
        print('    @%-4d 类型%08X  长%-4d %s'
              % (off, t, ln, d[off + 8:off + 8 + min(ln, 16)].hex()))
        off += 8 + ln
        n += 1
    print('  卡数 %d，卡区结束 @%d，文件长 %d' % (n, off, len(d)))

    # 与磁盘文件比对
    if args.filter:
        fb = open(os.path.abspath(args.filter), 'rb').read()
        print('\n  与磁盘滤镜 %s（%d 字节）比对：' % (os.path.basename(args.filter), len(fb)))
        if fb == d:
            print('    完全相同 → 磁盘文件可直接内嵌，无需 fixup')
            return
        # 规范长度 = 卡区 244 + 补齐段 144 + 结束 4 = 392，与磁盘文件本身多长无关
        if (fb[4:8] != b'\x00\x00\x00\x01'
                and len(d) == FIXUP_BODY + len(FIXUP_TAIL) + len(FIXUP_END)):
            cand = fixup(fb)
            print('    fixup 构造 %d 字节，差异 %d 字节 %s'
                  % (len(cand), sum(1 for i in range(len(d)) if cand[i] != d[i]),
                     '→ 完全一致' if cand == d else ''))
            return
        common = 0
        while common < min(len(fb), len(d)) and fb[common] == d[common]:
            common += 1
        print('    既不相同也不能用 fixup。最长公共前缀 %d 字节。' % common)
        print('    → 需要按上面打印的卡结构另找规律（把这份输出发出来分析）')


def main():
    ap = argparse.ArgumentParser(description='NX Studio sidecar 批量套用滤镜')
    sub = ap.add_subparsers(dest='cmd')

    sub.add_parser('probe', help='生成 3 张验证包，判定 sidecar 是否被读取')

    n = sub.add_parser('inspect', help='解析模板 sidecar，报告卡结构与能否构造')
    n.add_argument('--template', required=True, help='NX Studio 导出的 .nksc')
    n.add_argument('--filter', help='对应的磁盘滤镜文件，用来比对')

    m = sub.add_parser('make', help='以模板 sidecar 批量生成 NEF + sidecar')
    m.add_argument('--template', required=True, help='NX Studio 导出的模板 .nksc')
    m.add_argument('--nef', required=True, help='源 RAW')
    m.add_argument('--filters', required=True, help='滤镜目录（.NCP/.NP2/.NP3）')
    m.add_argument('--out', required=True, help='输出目录')
    m.add_argument('--dry-run', action='store_true',
                   help='只检查能否正确嵌入并打印清单，不写文件')
    m.add_argument('--fixup', action='store_true',
                   help='对磁盘文件先做补齐（NP3 布局需要；NCP 会自动跳过）')
    m.add_argument('--no-slot-byte', action='store_true',
                   help='ExportData 第 38 字节不写 0x02（默认写，与 NX Studio 应用态一致）')

    args = ap.parse_args()
    if args.cmd == 'probe':
        cmd_probe(args)
    elif args.cmd == 'inspect':
        cmd_inspect(args)
    elif args.cmd == 'make':
        cmd_make(args)
    else:
        ap.print_help()


if __name__ == '__main__':
    main()
