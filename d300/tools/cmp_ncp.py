#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""比对 NX Studio 导出的 NCP 与我生成的原始文件。

用途：验证「导入工坊 → 套用 → 再导出」这个过程有没有把曲线丢掉、有没有改写参数。

用法：
    python cmp_ncp.py 导出目录              # 自动按内嵌名称配对 out/ 里的原件
    python cmp_ncp.py 导出的.PICCON01.NCP   # 单个文件
    python cmp_ncp.py 导出目录 --out out    # 指定原件目录（默认 out）

判读规则：
    638 字节 且 控制点个数>0  → 曲线完整保留
    52 字节                   → 曲线被丢弃（只剩滑块配置）
    其它                     → 被改写，看逐项差异
"""

import os
import struct
import sys
import glob

OUT_MAX = 32767
HDR_LEN = 64


def read_ncp(path):
    """解析 NCP，返回 dict。结构坏了就返回 None。"""
    b = open(path, 'rb').read()
    info = {'size': len(b), 'path': path}

    if len(b) < 48 or b[:4] != b'NCP\x00':
        return None
    try:
        r1t, r1l = struct.unpack_from('>II', b, 4)
        d = b[12:12 + r1l]
        info['rec1_type'] = r1t
        info['name'] = d[4:24].rstrip(b'\x00').decode('latin1')
        info['ver'] = d[0:4].decode('latin1', 'replace')
        info['base'] = struct.unpack_from('>H', d, 24)[0]
        info['dirty'] = d[26]
        info['unk'] = d[27]
        info['sliders'] = list(d[28:36])
        info['tail'] = list(d[36:])
    except Exception:
        return None

    info['curve'] = None
    off = 12 + r1l
    if off + 8 <= len(b):
        r2t, r2l = struct.unpack_from('>II', b, off)
        if r2t == 2 and off + 8 + r2l <= len(b):
            c = b[off + 8:off + 8 + r2l]
            n = c[8]
            if n >= 2 and HDR_LEN + 257 * 2 <= len(c):
                pts = [(c[9 + 2 * i], c[10 + 2 * i]) for i in range(n)]
                lut = struct.unpack_from('>257H', c, HDR_LEN)
                info['curve'] = {'n': n, 'pts': pts, 'lut': lut, 'blob': c}
    return info


def lut_sample(lut, x):
    fi = x / 255.0 * 256.0
    i = min(int(fi), 255)
    return lut[i] + (lut[i + 1] - lut[i]) * (fi - i)


def to255(v):
    return v / OUT_MAX * 255.0


def report(exported, original):
    e = read_ncp(exported)
    print('=' * 66)
    print('导出文件：%s' % os.path.basename(exported))

    if e is None:
        print('  解析失败 —— 不是合法 NCP，或结构被改写')
        return False

    print('  尺寸 %d 字节   名称 "%s"   底子 0x%04X   滑块 %s'
          % (e['size'], e['name'], e['base'],
             ' '.join('%02X' % v for v in e['sliders'])))

    if e['curve'] is None:
        print('  曲线：**没有**（这个文件只剩下 52 字节的滑块配置）')
        print('  结论：工坊导出时把自定义曲线丢了 —— 要么导入时就没读进去，')
        print('        要么导出格式退化。需要改用「从存储卡导入」或直接装机验证。')
        return False

    c = e['curve']
    print('  曲线：%d 个控制点，LUT %d–%d'
          % (c['n'], c['lut'][0], c['lut'][256]))
    print('  控制点：%s' % ' '.join('(%d,%d)' % p for p in c['pts']))

    if original is None:
        print('  （没有原件可对比，仅列出导出结果）')
        return True

    o = read_ncp(original)
    print('  --- 与原件对比 ---')
    ok = True

    if e['name'] != o['name']:
        print('  名称：原件 "%s" → 导出 "%s"' % (o['name'], e['name']))
    if e['base'] != o['base']:
        print('  **底子被改**：0x%04X → 0x%04X' % (o['base'], e['base']))
        ok = False
    if e['sliders'] != o['sliders']:
        print('  **滑块被改**：%s → %s'
              % (' '.join('%02X' % v for v in o['sliders']),
                 ' '.join('%02X' % v for v in e['sliders'])))

    oc = o['curve']
    if oc is None:
        print('  原件本来就没曲线，略过曲线对比')
        return ok

    dev = []
    for x in range(256):
        a = to255(lut_sample(oc['lut'], x))
        b2 = to255(lut_sample(c['lut'], x))
        dev.append(b2 - a)
    worst = max(dev, key=abs)
    print('  曲线差异：最大 %.2f/255（在输入 %d 处），平均 %.2f/255'
          % (worst, dev.index(worst), sum(abs(v) for v in dev) / 256))
    if abs(worst) <= 1.0:
        print('  结论：曲线**完整保留**，工坊读懂了这批文件')
    elif abs(worst) <= 4.0:
        print('  结论：曲线基本保留，有轻微重采样差异（可接受）')
    else:
        print('  结论：**曲线被改动**，差异过大')

    if o['curve']['n'] != c['n']:
        print('  控制点个数：%d → %d（工坊重采样了）'
              % (o['curve']['n'], c['n']))
    return ok and abs(worst) <= 4.0


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    outdir = 'out'
    if '--out' in sys.argv:
        outdir = sys.argv[sys.argv.index('--out') + 1]

    if not args:
        print(__doc__)
        return 1

    target = args[0]
    if os.path.isdir(target):
        files = sorted(glob.glob(os.path.join(target, '*.NCP'))
                       + glob.glob(os.path.join(target, '*.ncp')))
    else:
        files = [target]

    if not files:
        print('目录里没有 NCP 文件：%s' % target)
        return 1

    # 按内嵌名称建索引，配不上再退回按文件名
    by_name, by_file = {}, {}
    for p in glob.glob(os.path.join(outdir, '*.NCP')):
        i = read_ncp(p)
        if i:
            by_name[i['name']] = p
            by_file[os.path.basename(p)] = p

    allok = True
    for f in files:
        i = read_ncp(f)
        orig = None
        if i:
            orig = by_name.get(i['name'])
        if orig is None:
            orig = by_file.get(os.path.basename(f))
        allok &= report(f, orig)

    print('=' * 66)
    print('总体：%s' % ('通过' if allok else '有项目需要处理，见上面标 ** 的行'))
    return 0 if allok else 2


if __name__ == '__main__':
    sys.exit(main())
