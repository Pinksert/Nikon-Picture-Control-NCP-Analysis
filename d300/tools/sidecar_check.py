#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sidecar_check.py —— 交付前体检：这批 .nksc 真的会被 NX Studio 认吗？

由来（2026-11-01）
------------------
底子探针两批共 14 份 sidecar，在 NX Studio 里全部退回「拍摄时设定 (SD 标准)」。
原因不是滤镜字节，而是写文件时用了 ``read_sidecar()`` 的**第二个**返回值（反转义过的
文本）：``<nine:NineEdits>`` 里本该是 ``&lt;userData&gt;`` 的转义 XML 变成了裸 ``<userData>``。
XML 本身仍然「合法」（裸标签照样能解析），所以任何按标签取值做往返校验的检查都查不出来——
只有 NX Studio 的解析器会整份丢弃。

这个脚本查的就是「XML 合法但语义坏了」这一类：
  1. 整份文件能被 XML 解析器读通
  2. NineEdits 的内容必须是**字符串**，且里面含 <userData>（而不是被解析成子元素）
  3. ExportData / CustomData 能 base64 解开，且滤镜字节自洽（魔数 + 名字可读）
  4. 同名 NEF 必须就在上一层（NX Studio 靠文件名配对，配不上就等于没有 sidecar）

用法::

    python d300/tools/sidecar_check.py _probe_base _probe_baseid d300/samples/probe_slider
    python d300/tools/sidecar_check.py --dir _probe_baseid --expect B1_STANDARD=0001
"""
import argparse
import base64
import html
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sidecar_batch as S                                       # noqa: E402


def check_one(path, nef_dir):
    """返回 (问题列表, 信息字典)。问题为空 = 这份 sidecar 形态正确。"""
    bad = []
    raw = open(path, encoding='utf-8', errors='replace').read()
    info = {}

    # 1. XML 能否整体解析
    #    ⚠️ 必须解析**原始**文本，不能先 html.unescape —— 那是解码后的形态，
    #       转义过的 `&lt;userData&gt;` 会被解成真标签，正确文件反而被误判。
    try:
        root = ET.fromstring(raw.encode('utf-8'))
        ok_parse = True
    except ET.ParseError as e:
        ok_parse = False
        bad.append('整体 XML 解析失败：%s' % e)
        root = None

    # 2. NineEdits 必须是纯文本，不能被解析成子元素
    if root is not None:
        node = None
        for el in root.iter():
            if el.tag.endswith('NineEdits'):
                node = el
                break
        if node is None:
            bad.append('找不到 NineEdits')
        else:
            if len(list(node)) > 0:
                bad.append('NineEdits 被解析成 %d 个子元素（写进去的是裸 XML）'
                           % len(list(node)))
            txt = (node.text or '')
            info['nine_len'] = len(txt)
            # 转义形态：解析后实体已解码，文本里能读到字面的 <userData>
            if '<userData>' not in txt:
                bad.append('NineEdits 文本里没有 <userData>')

    # 3. 两处内嵌滤镜
    for tag in ('ExportData', 'CustomData'):
        s = html.unescape(raw)
        m = re.search(r'<%s>(.*?)</%s>' % (tag, tag), s, re.S)
        if not m:
            if tag == 'CustomData':
                info['custom'] = None
            else:
                bad.append('找不到 <%s>' % tag)
            continue
        try:
            d = base64.b64decode(''.join(m.group(1).split()))
        except Exception as e:                                  # noqa: BLE001
            bad.append('%s base64 解不开：%s' % (tag, e))
            continue
        info[tag.lower()] = d
        if d[:4] != b'NCP\x00':
            bad.append('%s 魔数不是 NCP\\0（%r）' % (tag, d[:4]))
        nm = S.filt_name(d)
        info[tag.lower() + '_name'] = nm
        info[tag.lower() + '_len'] = len(d)

    # 4. NEF 配对
    base = os.path.basename(path)
    if not base.lower().endswith('.nef.nksc'):
        bad.append('文件名不是「<NEF 全名>.nksc」')
    nef = os.path.join(nef_dir, base[:-5])
    info['nef'] = os.path.exists(nef)
    if not info['nef']:
        bad.append('同名 NEF 不在上一层：%s' % base[:-5])
    return bad, info


def check_dir(d, expects=None, verbose=True):
    """检查一个目录（sidecar 可在目录内或 NKSC_PARAM 子目录）。返回失败数。"""
    d = os.path.abspath(d)
    scd = os.path.join(d, 'NKSC_PARAM')
    if not os.path.isdir(scd):
        scd = d
    files = sorted(f for f in os.listdir(scd) if f.lower().endswith('.nksc'))
    print('=' * 74)
    print('%s  →  %d 份 sidecar' % (d, len(files)))
    if not files:
        print('  没有 sidecar')
        return 0
    nbad = 0
    sizes = set()
    for f in files:
        p = os.path.join(scd, f)
        sizes.add(os.path.getsize(p))
        bad, info = check_one(p, d)
        stem = f[:-len('.NEF.nksc')] if f.lower().endswith('.nef.nksc') else f
        tag = ''
        if expects and stem in expects:
            want = expects[stem]
            got = info.get('custom') or info.get('exportdata') or b''
            got_code = (got[36] << 8 | got[37]) if len(got) > 37 else None
            ok = (got_code == want)
            tag = '  底子 %04X%s' % (got_code or 0, '' if ok else ' ✗ 期望 %04X' % want)
            if not ok:
                bad.append('底子编号不是 %04X' % want)
        print('  %-28s %5d B  名字 %-12s%s' %
              (stem, os.path.getsize(p), info.get('customdata_name') or '?', tag))
        if bad:
            nbad += 1
            for b in bad:
                print('      ✗ %s' % b)
        elif verbose:
            print('      ✓ XML 合法 / NineEdits 是文本 / 两处内嵌自洽 / NEF 配得上')
    if len(sizes) > 1:
        print('  ⚠ 文件大小不一致：%s' % sorted(sizes))
    print('  结果：%d / %d 合格' % (len(files) - nbad, len(files)))
    return nbad


def parse_expect(spec):
    """'B1_STANDARD=0001' → {'B1_STANDARD': 0x0001}"""
    if not spec:
        return None
    out = {}
    for item in spec:
        k, v = item.split('=')
        out[k] = int(v, 16)
    return out


def main():
    ap = argparse.ArgumentParser(description='sidecar 交付前体检')
    ap.add_argument('dirs', nargs='*', default=[],
                    help='一个或多个含 .nksc 的目录（可含 NKSC_PARAM 子目录）')
    ap.add_argument('--dir', action='append', default=[],
                    help='同位置参数，可重复')
    ap.add_argument('--expect', action='append', default=[],
                    help='期望底子编号，形如 B1_STANDARD=0001')
    ap.add_argument('-q', '--quiet', action='store_true')
    a = ap.parse_args()
    targets = a.dirs + a.dir
    if not targets:
        ap.error('至少给一个目录')
    exp = parse_expect(a.expect)
    total = sum(check_dir(t, exp, verbose=not a.quiet) for t in targets)
    print()
    print('合计不合格 %d 份' % total)
    raise SystemExit(0 if total == 0 else 1)


if __name__ == '__main__':
    main()
