#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pack_sidecar_batch.py —— 一次性生成「NEF 副本 + 配对 sidecar」的批量包。

2026-11-02 实测：NX Studio **是**读 sidecar 里内嵌的自定义优化校准的。
上午那批之所以 8 张全渲染成 SILENCE，是**扫描时序**：它边生成边扫，
扫到 NEF 时 sidecar 还没落盘，就缓存了「无调整」；NEF 又是 copy2 复制的、
mtime 停在旧时间，之后没有变化能触发重读。

    _probe_range/ 目录注册 09:47:26，sidecar 落盘 09:47:25.7–26.1（每份间隔 50 ms）
    _probe_flag/  10:45 一次写完、10:47 才打开  → 5 格全部正确生效
    _probe_name/  4 格只改文件名（含 68 字符长名、带 + 号的原失败名）→ 全部正确生效

所以规则只有一条：**整包写完，再让 NX Studio 打开这个目录。** 本脚本就是干这个的。

用法（以底子指纹探针为例）：
    python tools/pack_sidecar_batch.py --ncp-dir ../_probe_baseid/ncp \\
                                       --out ../_probe_baseid/batch

生成结构：
    <out>/B1_STANDARD.NEF        ← 底片副本，mtime 刷成现在
    <out>/NKSC_PARAM/B1_STANDARD.NEF.nksc
    ...

导出后文件名就是 `B1_STANDARD.JPG`，`probe_baseid_read.py` 直接认。
"""
import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..', 'np3tool')))

import numpy as np                                            # noqa: E402
import np3core as C                                           # noqa: E402
import sidecar_batch as S                                     # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
TPL = os.path.normpath(os.path.join(ROOT, '..', 'lightroom', 'NKSC_PARAM',
                                    'DSC_4484.NEF.nksc'))
NEF = os.path.normpath(os.path.join(ROOT, '..', 'lightroom', 'DSC_4484.NEF'))


def build(ncp_dir, out, nef, tpl_path, keep_old=False):
    os.makedirs(os.path.join(out, 'NKSC_PARAM'), exist_ok=True)
    side = os.path.join(out, 'NKSC_PARAM')
    if not keep_old:
        for f in os.listdir(side):
            os.remove(os.path.join(side, f))
        for f in os.listdir(out):
            if f.lower().endswith('.nef'):
                os.remove(os.path.join(out, f))

    tpl = S.template_text(tpl_path)          # 校验过「转义形态」的模板
    items = sorted(f for f in os.listdir(ncp_dir) if f.upper().endswith('.NCP'))
    if not items:
        raise SystemExit('目录里没有 NCP：%s' % ncp_dir)

    print('%-16s %-4s %-11s %-6s %-8s %s'
          % ('输出名', '槽', '底子', '恒等', '大小', '自检'))
    print('-' * 78)
    n_ok = 0
    for fn in items:
        stem = os.path.splitext(fn)[0]
        path = os.path.join(ncp_dir, fn)
        ncp = open(path, 'rb').read()
        if len(ncp) != 638:
            print('%-16s  跳过：%d 字节，不是 638 B 的 NCP' % (stem, len(ncp)))
            continue

        txt = S.embed_data(tpl, ncp, slot02=True)
        dst_nef = os.path.join(out, stem + '.NEF')
        shutil.copy2(nef, dst_nef)
        os.utime(dst_nef, None)              # 刷 mtime：别让旧缓存认死这张图
        sidecar = os.path.join(side, stem + '.NEF.nksc')
        S.write_sidecar(sidecar, txt)

        # 三重校验：往返比特一致 / 名字对得上 / 曲线读出与原文件一致
        back = S.template_text(sidecar)
        assert S.custom_data(back) == ncp, '%s CustomData 往返被改坏' % stem
        assert S.export_data(back)[:38] + S.export_data(back)[39:] == \
            ncp[:38] + ncp[39:], '%s ExportData 除第 38 字节外被改动' % stem
        assert S.export_data(back)[38] == 0x02, '%s 第 38 字节没写成 0x02' % stem
        r = C.read_ncp(ncp)
        ident = float(np.abs(C.H(r['lut']) - np.arange(257)).max())
        print('%-16s %-4s 0x%04X    %-6.1f %-8d %s'
              % (stem, '-', r['base'], ident, os.path.getsize(sidecar),
                 S.filt_name(ncp)))
        n_ok += 1

    print('-' * 78)
    print('%d 份 → %s' % (n_ok, out))
    print('下一步：先别打开这个目录，等这里全部写完；再让 NX Studio 打开，一次 Ctrl+A 导出。')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ncp-dir', required=True, help='放 <名字>.NCP 的目录')
    ap.add_argument('--out', required=True)
    ap.add_argument('--nef', default=NEF)
    ap.add_argument('--template', default=TPL)
    ap.add_argument('--keep-old', action='store_true', help='保留目录里已有的 NEF/sidecar')
    a = ap.parse_args()
    build(os.path.abspath(a.ncp_dir), os.path.abspath(a.out),
          a.nef, a.template, a.keep_old)


if __name__ == '__main__':
    main()
