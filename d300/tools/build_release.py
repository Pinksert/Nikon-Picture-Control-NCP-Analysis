#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成正式发布包：`发布包/` = NIKON\\CUSTOMPC\\PICCON01..30（补偿版，可直接拷卡）+ 说明。

发布依据（2026-10-30 第七批照片，DSC_5299–5306）：
  · 01 STD / 02 STEP(硬阶跃128) / 03 GAM(gamma0.45) / 04 U-POP / 05 C-POP
    / 06 U-BIN / 07 C-BIN / 08 U-SEP
  · 02 STEP 的阶跃 50% 交点 = 输入 144.6，模型预测 H⁻¹(128)=146.1
    → 机身在套曲线之前也做了和工坊一样的 H 压缩
  · 03 GAM 实测传递曲线与「LUT(H(x))」预测逐点吻合（残差 ~1 级），
    与「LUT(x)」相差 8–15 级 → 确认 H 存在
  · 从 GAM 反推的机身 H 与 compensate.py 的工坊 H 对比：平均差 +0.95 级、标准差 1.04 级
    → 机身 H ≡ 工坊 H
  · 04 vs 05（POP 未补偿/补偿）实测对模型残差均为 ~1 级，两条链路都成立
→ 所以发布 **out_comp/**（补偿版）：机身出图 = 目标曲线 T(x)，工坊里也是 T(x)，两边一致。
"""
import os
import shutil
import struct

HERE = os.path.dirname(os.path.abspath(__file__))


def _pick(*rel):
    for r in rel:
        p = os.path.normpath(os.path.join(HERE, r))
        if os.path.isdir(p):
            return p
    raise SystemExit('找不到目录：' + ' / '.join(rel))


# 兼容两种布局（同 build_pack7.py）
NCPROOT = _pick('../ncp', '.')
IN_REPO = os.path.normpath(NCPROOT) != os.path.normpath(HERE)

SRC = NCPROOT
SRC_DIR = os.path.join(NCPROOT, 'out_comp')
# v2 之后 `release/` 由 optimize_v2.py 生成，这里只重建 v1 存档
DST = os.path.join(NCPROOT, 'release_v1') if IN_REPO else os.path.join(HERE, '发布包')

SL_OFF, BASE_OFF, NAME_OFF = 40, 36, 16


def read_plan():
    cands = [os.path.join(SRC, 'out', '_清单.txt'), os.path.join(SRC, '_清单.txt')]
    path = next((p for p in cands if os.path.exists(p)), None)
    if path is None:
        raise SystemExit('找不到 _清单.txt：' + ' / '.join(cands))
    rows = []
    for line in open(path, encoding='utf-8'):
        line = line.strip()
        if not line:
            continue
        f, rest = line.split(None, 1)
        parts = rest.split()
        en = parts[0]
        cn = parts[-2] if len(parts) >= 3 else ''
        rows.append((f, en, cn))
    return rows


def main():
    if os.path.isdir(DST):
        shutil.rmtree(DST)
    d = os.path.join(DST, 'NIKON', 'CUSTOMPC')
    os.makedirs(d)

    rows = read_plan()
    assert len(rows) == 30, len(rows)

    print('%-12s %-22s %-14s %-6s %-4s' % ('槽位', '名称', '底子', '字节', '点'))
    print('-' * 70)
    for f, en, cn in rows:
        raw = open(os.path.join(SRC_DIR, f), 'rb').read()
        b = bytearray(raw)
        # 机内显示的就是这个名字，保持原滤镜名（英文，20 字节 ASCII 上限）
        b[NAME_OFF:NAME_OFF + 20] = ('%s' % en).encode('ascii')[:20].ljust(20, b'\x00')
        b = bytes(b)
        assert len(b) == 638, (f, len(b))
        assert b[SL_OFF + 1] == 0x01 and b[SL_OFF + 2] == 0x01, f
        base = struct.unpack_from('>H', b, BASE_OFF)[0]
        mono = (b[43] == 0xFF and b[44] == 0xFF)
        assert (base == 0x064D) if mono else (base == 0x0001), (f, hex(base))
        assert b[56] == 0x49 and b[64] > 0
        open(os.path.join(d, f), 'wb').write(b)
        print('%-12s %-22s 0x%04X %-6d %-4d' % (f, en + ' / ' + cn, base, len(b), b[64]))

    print('\n发布包：', d)
    print('共 %d 个文件' % len(os.listdir(d)))


if __name__ == '__main__':
    main()
