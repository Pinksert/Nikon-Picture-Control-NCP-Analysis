# -*- coding: utf-8 -*-
"""解析 ncp jpg 目录：每张图的预设身份，找出基准图，跑批量曲线生成"""
import os, sys, json, struct, glob
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r'C:\Users\admin\WorkBuddy\D300固件\.workbuddy\tmp')

SRC = r'C:\Users\admin\WorkBuddy\D300固件\ncp jpg'

def pc_info(path):
    b = open(path, 'rb').read(20000)
    i = b.find(b'03100310')
    if i < 0:
        return None, None            # 兼容系统导出：无此标记
    name = b[i + 8:i + 28].rstrip(b'\x00').decode('latin1', 'replace')
    base = struct.unpack('<H', b[i + 48:i + 50])[0]
    return name, base

files = sorted(glob.glob(os.path.join(SRC, '*.JPG')) + glob.glob(os.path.join(SRC, '*.jpg')))
files = sorted(set(files))
print('目录里 %d 个文件：' % len(files))
info = {}
compat_sd = None
for f in files:
    n, b = pc_info(f)
    tag = os.path.basename(f)
    if n is None:
        print('  %-28s [兼容系统导出，无标记]' % tag)
        if compat_sd is None:
            compat_sd = f
        continue
    info[f] = (n, b)
    print('  %-28s %-12s 底子 %04X' % (tag, n, b))

print('\n基准图（兼容系统导出）:', os.path.basename(compat_sd) if compat_sd else '没找到！')
json.dump({'compat_sd': compat_sd,
           'targets': {f: n for f, (n, b) in info.items()}},
          open(r'C:\Users\admin\WorkBuddy\D300固件\curve_out\batch_map.json', 'w'),
          ensure_ascii=False, indent=1)
print('映射已存 curve_out/batch_map.json')
