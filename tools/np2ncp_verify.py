# -*- coding: utf-8 -*-
"""用之前实测 dump（pc2.txt）验证：NP2/NP3 的卡片值能否无损填回 NCP 的 8 个滑块。
   不重新读原文件（沙箱拦截），数据源是 10-21 那次对 42 个文件的完整 TLV dump。"""
import re, sys
sys.stdout.reconfigure(encoding='utf-8')

TXT = open(r'C:\Users\admin\WorkBuddy\D300固件\.workbuddy\tmp\pc2.txt', encoding='utf-8').read()

# ---- 1. 解析 NCP（curve + 8 滑块）----
ncp = {}
for m in re.finditer(r'^(\w+)\.NCP\s+ver=\S+ curve=(\w+) (\w+) flag=\S+ unk39=\S+ sliders=([0-9A-F ]+)',
                     TXT, re.M):
    name, c0, c1, sl = m.group(1), m.group(2), m.group(3), m.group(4).split()
    ncp[name] = dict(curve=c0 + c1, sliders=[int(x, 16) for x in sl])

# ---- 2. 解析 NP2/NP3 的 TLV 卡片 ----
tlv = {}
cur = None
for line in TXT.splitlines():
    m = re.match(r'^--- (\w+)\.(NP2|NP3) \((\d+) bytes\)', line)
    if m:
        cur = (m.group(1), m.group(2)); tlv[cur] = {}; continue
    m = re.match(r'\s+type=([0-9A-F]{8}) len=(\d+)\s+(?:\[([0-9A-F ]+)\]|TEXT=|\'(.*)\')', line)
    if m and cur:
        t = int(m.group(1), 16) >> 8
        if m.group(3):
            h = m.group(3).split()
            tlv[cur][t] = (int(h[0], 16), int(h[1], 16))
        elif m.group(4):
            tlv[cur][t] = m.group(4)

# ---- 3. 映射表：NCP 滑块位 -> (卡片 ID, 名称) ----
MAP = [(6, '锐化'), (8, '对比度'), (9, '亮度'), (10, '饱和度'),
       (11, '色相'), (12, '滤镜效果'), (13, '调色'), (14, '调色强度')]

def card2ncp(c):
    """NP2/NP3 卡片 (v, step) -> NCP 字节。0xFF=不适用；0x80+n=整数档"""
    v, st = c
    if v == 0xFF: return 0xFF, None
    if st == 0:   return 0x80 + (v - 0x80), (v - 0x80)          # 步进 0：原样
    raw = (v - 0x80) * st / 16.0
    n = int(round(raw))
    return 0x80 + max(-9, min(9, n)), (raw, n)

print("=" * 92)
print("A. 六个有 NCP 原版的预设：NP2/NP3 卡片 → NCP 字节，逐字节对照")
print("=" * 92)
print("  %-11s %-4s %-9s %-9s %s" % ('预设', '位', 'NCP真值', 'NP2推出', 'NP3推出'))
total = hit = 0
for n in ['STANDARD', 'NEUTRAL', 'VIVID', 'PORTRAIT', 'LANDSCAPE', 'MONOCHROME']:
    for i, (cid, nm) in enumerate(MAP):
        truth = ncp[n][ 'sliders'][i]
        row = ['%s[%d]%s' % (n[:9], i, nm)]
        outs = []
        for ext in ('NP2', 'NP3'):
            k = (n, ext)
            if k not in tlv or cid not in tlv[k]:
                outs.append('--'); continue
            byte, info = card2ncp(tlv[k][cid])
            outs.append('%02X%s' % (byte, '' if byte == truth else '≠%02X' % truth))
            total += 1
            hit += (byte == truth)
        print("  %-11s %-4s    %02X        %-9s %s" % (n, '%s(%d)' % (nm[:3], cid), truth, outs[0], outs[1]))
print()
print("  → 8 个滑块位 × 6 个预设 × 2 个新格式 = %d 个字节，命中 %d 个，%.1f%%"
      % (total, hit, 100.0 * hit / total))

print()
print("=" * 92)
print("B. 基准曲线编号（NCP offset 36-37  ←  NP2/NP3 的 3 号卡）")
print("=" * 92)
for n in ['STANDARD', 'NEUTRAL', 'VIVID', 'PORTRAIT', 'LANDSCAPE', 'MONOCHROME', 'FLAT', 'AUTO']:
    c = ncp.get(n, {}).get('curve', '（无 NCP 版）')
    r = []
    for ext in ('NP2', 'NP3'):
        k = (n, ext)
        r.append('%02X%02X' % tlv[k][3] if k in tlv and 3 in tlv[k] else '--')
    print("  %-11s NCP=%-6s NP2=%-5s NP3=%-5s %s" % (n, c, r[0], r[1],
          '' if c in ('（无 NCP 版）',) or r[0].upper() == c.upper() else '★新格式有、NCP 没有这个底子'))

print()
print("=" * 92)
print("C. 新格式里 NCP 装不下的卡片")
print("=" * 92)
used = set(c for c, _ in MAP) | {3}
for ext in ('NP2', 'NP3'):
    ids = sorted(set(c for (n, e), d in tlv.items() if e == ext for c in d if c < 0x100))
    extra = [i for i in ids if i not in used and i != 2]
    print("  %s 全部卡 ID：%s" % (ext, ids))
    print("     → NCP 无对应位置的：%s" % extra)
    for i in extra:
        vals = sorted(set(('%02X%02X' % d[i]) if isinstance(d[i], tuple) else ('文本:' + str(d[i])[:6])
                          for (n, e), d in tlv.items() if e == ext and i in d))
        print("        ID%-3d 取值样本 %s" % (i, vals[:6]))

print()
print("=" * 92)
print("D. 数值精度 / 量程差异")
print("=" * 92)
print("  %-6s %-24s %-24s" % ('', 'NCP (0100)', 'NP2/NP3 (0210/0300)'))
print("  %-6s %-24s %-24s" % ('步进', '1 档（整数字节）', '0.25 档（步进码 04）'))
print("  %-6s %-24s %-24s" % ('锐化', '0~9 / 00=自动', 'NP3: -3~9'))
print("  %-6s %-24s %-24s" % ('亮度', '-1~+1', 'NP2/NP3: -1.5~+1.5'))
print()
print("  实例：NEUTRAL 的 ID7 在 NP2 是 [80 04]=0.00，NP3 是 [82 04]=+0.50")
print("        → 0.50 这种四分之一档，NCP 一个字节里没有落脚点（只能记 0 或 1）")
