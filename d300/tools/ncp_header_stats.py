#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ncp_header_stats.py —— 统计现成 NCP 的头部长什么样（第 38 字节的证据表）。

为什么做：`_probe_batch_fix` 之后，剩下的怀疑对象只有「第 38 字节」——
它到底是 NX Studio 的「应用态标记」，还是底子的**命名空间**？

手里的 593 份 NCP（我们生成的 + nikonpc 上第三方做的 + 原厂工具出的）够判了：
  第 38 字节只出现 0x00 与 0x02；
  0x02 只出现在「kind=2 组里也有的编号」上；
  0014 / 03D5 / 00D6（只属于 kind=1）清一色 0x00；
  0x0801 / 0x0808 / 0x080B / 0x0813（只属于 kind=8）清一色 0x00。

用法：
    python d300/tools/ncp_header_stats.py
    python d300/tools/ncp_header_stats.py --csv samples/ncp_header.csv
"""
import argparse
import collections
import glob
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
BASE = os.path.normpath(os.path.join(ROOT, '..'))   # D300固件/

# kind 归属（dump_rome2_table.py 的产物，见 docs/18）
KIND1 = {0x0001, 0x03C2, 0x00C3, 0x064D, 0x0486, 0x04C7, 0x0014, 0x03D5, 0x00D6}
KIND2 = {0x0001, 0x03C2, 0x00C3, 0x064D, 0x0486, 0x04C7, 0x028E, 0x02CF}
KIND8 = KIND2 | {0x0801, 0x0802, 0x0803, 0x0804, 0x0805, 0x0806, 0x0807,
                 0x0808, 0x0809, 0x080A, 0x080B, 0x080C, 0x080D}


def rec1(raw):
    if raw[:4] != b'NCP\0':
        return None
    off = 4
    while off + 8 <= len(raw):
        t, ln = struct.unpack_from('>II', raw, off)
        if t == 0:
            break
        if t == 1:
            return raw[off + 8: off + 8 + ln]
        off += 8 + ln
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=BASE)
    ap.add_argument('--csv', default=None)
    a = ap.parse_args()

    combo = collections.Counter()
    files = set()
    for pat in ('**/*.NCP', '**/*.ncp'):
        files |= set(glob.glob(os.path.join(a.root, pat), recursive=True))
    for p in files:
        try:
            prof = rec1(open(p, 'rb').read())
        except Exception:
            continue
        if not prof or len(prof) < 36:
            continue
        combo[(struct.unpack_from('>H', prof, 24)[0], prof[26], prof[27])] += 1

    tot = sum(combo.values())
    print('扫描 %s：%d 个 NCP 文件，%d 种 (底子, 第26字节, 第27字节)'
          % (a.root, len(files), len(combo)))
    print()
    print('%9s %6s %6s %6s  %-10s %s'
          % ('底子', 'byte26', 'byte27', '数量', 'kind 归属', '说明'))
    print('-' * 76)
    for (base, p26, p27), c in sorted(combo.items()):
        kinds = [n for n, s in (('1', KIND1), ('2', KIND2), ('8', KIND8)) if base in s]
        note = ''
        if p26 == 0x08:
            note = '（本仓库没有一份这么写 —— 待验证）'
        elif p26 == 0x02 and kinds and '2' not in kinds:
            note = '⚠ 0x02 却不在 kind=2 组'
        elif p26 == 0x00 and kinds == ['1']:
            note = '只在 kind=1 → 必须 0x00'
        print('0x%04X %7s %6s %6d  %-10s %s'
              % (base, '0x%02X' % p26, '0x%02X' % p27, c,
                 ('kind ' + ','.join(kinds)) if kinds else '不在任何组', note))

    print()
    print('第 26 字节的取值分布：%s' % dict(collections.Counter(
        {('%02X' % p26): n for (_, p26, _), n in
         ((k, v) for k, v in combo.items())})))
    # 上面的字典推导在重复 key 上只保留最后一个，重算一遍更稳
    dist = collections.Counter()
    for (_, p26, _), n in combo.items():
        dist['0x%02X' % p26] += n
    print('  按份数：%s  （共 %d 份）' % (dict(dist), tot))

    if a.csv:
        os.makedirs(os.path.dirname(os.path.abspath(a.csv)), exist_ok=True)
        with open(a.csv, 'w', encoding='utf-8-sig') as f:
            f.write('base,byte26,byte27,count\n')
            for (base, p26, p27), c in sorted(combo.items()):
                f.write('0x%04X,0x%02X,0x%02X,%d\n' % (base, p26, p27, c))
        print('csv -> %s' % a.csv)


if __name__ == '__main__':
    main()
