#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pack_kind_probe.py —— 试第 38 字节是不是「命名空间」。**已结案：不是，别再跑。**

结论（2026-11-02 11:31 实测）
--------------------------
`_probe_kind8`（三张，第 38 字节全写 0x08）打开即崩，事件日志：

    Rome2.dll 2.9.1.3000   0xc0000005   偏移 0x13d8f2

与 `_probe_batch` / `_probe_batch_fix` **第三次同一签名**。反汇编复核（本次重做）：

    lookup(edx=kind, ecx=base):
        if edx==0 or ecx==0: return 0
        if edx>=8: edx=8  elif edx>=2: edx=2  elif edx>=1: edx=1
        key = (edx<<16)|ecx                   ; 线性扫 38 项，步长 0x1a0 = 4×0x68
        ...未命中 → 返回 ecx（=条目数 38），没有 −1

调用点 `0x13A763` 前一行的 `mov edx,[profile+0x1b0]` 说明：**kind 不是直接从文件
某个字节读进来的**，而是 profile 结构里一个由加载器自己填的字段。我们把 0x08 写进
第 38 字节，进到 lookup 的 edx 仍然是 1 → key = 0x00010801 → 查不到 → 返回 38 →
越界 → 崩。

旁证：全仓库 593 份 NCP 的版本字段**清一色 "0100"**，第 38 字节只有 0x00 / 0x02。
也就是说，**「怎么在 NCP 里表达 kind=8」这件事，世界上没有人写成功过** ——
不是我们没找到写法，是 NCP 这个容器不承载它。创意底子只存在于 NP3 的原生指针里。

后果：`0x0801–0x0814` 十六支创意底子**永远拿不进机身**，见 `docs/20`。

---
（以下为历史记录，脚本已被闸门拦住，不会误跑。）

`_probe_batch_fix` 去掉 B8(0x0813) 之后**照样闪退**，事件日志里偏移还是
`Rome2.dll +0x13d8f2`。也就是说只要写 08xx，哪怕编号在 kind=8 组里存在，
也一样查不到 —— 我们写出来的东西被当成 kind=1。


同一天 `_probe_profile` 反而一次跑通，里面 0x0014 / 0x03D5 / 0x00D6
（D2X 模式 I/II/III）**只在 kind=1 组里存在**，kind=2 组没有它们。
这反证了：渲染走的是 `<CustomData>`（第 38 字节 = 0x00 → kind=1），
不是 `<ExportData>`（NX Studio 自己写 0x02）。

于是问题收敛成一句：**第 38 字节能不能写 0x08？**

证据链（stats 见 docs/19）：
  * 593 份现成 NCP 里，第 38 字节只有 0x00 与 0x02 两种；
  * 0x02 只出现在「kind=2 组也有的编号」上（0001/00C3/03C2/0486/04C7/064D），
    而 0014/03D5/00D6 这三份清一色 0x00 —— 与命名空间划分完全吻合；
  * 反汇编的钳位就是 `cmp edx,8 → 8 / cmp edx,2 → 2 / 否则 1`，
    正好是 0x08、0x02、0x00 这三个值。

所以本脚本做三张图，只改第 38 字节为 0x08：

    K0_STD_NS8     底子 0x0001  ← 对照：kind=8 里也有 STANDARD，应当正常
    K1_DREAM_NS8   底子 0x0801  ← 真问题：DREAM 只在 kind=8 里
    K2_SEPIA_NS8   底子 0x080D  ← 顺带验一支带色调的

判读：
    三张都开、K1/K2 明显不像 STANDARD  → 第 38 字节就是命名空间，创意底子解锁
    仍然闪退（还是 0x13d8f2）        → 这个字节不是命名空间，此路封死
    K1 开、K1 与平常的 STANDARD 无差别  → 打开时按 0x08 认了，但底子仍回落到 1

用法：
    python d300/tools/pack_kind_probe.py
    # 写完再开 _probe_kind8；崩了再单独开 _probe_kind8_b（只有对照那张）
"""
import argparse
import os
import shutil
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..', 'np3tool')))

import np3core as C                                            # noqa: E402
import sidecar_batch as S                                      # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
NEF = os.path.normpath(os.path.join(ROOT, '..', 'lightroom', 'DSC_4484.NEF'))
TPL = os.path.normpath(os.path.join(ROOT, '..', 'lightroom', 'NKSC_PARAM',
                                    'DSC_4484.NEF.nksc'))

SL_COLOR = [0x83, 0x01, 0x01, 0x80, 0x80, 0x80, 0xFF, 0xFF]
NS_OFF = 38                      # NCP 里 <CustomData> 的第 38 字节 = 记录1 的第 26 字节

PLAN = [
    (0x0001, 'K0_STD_NS8',   'STANDARD',  '对照：kind=8 组里也有它'),
    (0x0801, 'K1_DREAM_NS8', 'DREAM',     '真问题：只在 kind=8 组里'),
    (0x080D, 'K2_SEPIA_NS8', 'SEPIA',     '顺带：kind=8 组的上界'),
]


def make(name, base, ns):
    """恒等曲线 + 指定底子 + 第 38 字节写成 ns。"""
    ncp = C.make_ncp(name, base, SL_COLOR, np.arange(256, dtype=np.float64))
    b = bytearray(ncp)
    assert len(b) == 638, len(b)
    b[NS_OFF] = ns
    b = bytes(b)
    d = C.read_ncp(b)
    assert d['base'] == base, '底子写坏 %04X' % d['base']
    assert b[NS_OFF] == ns, '第 38 字节没写进去'
    err = float(np.abs(C.H(d['lut']) - np.arange(257)).max())
    assert err < 1.5, '恒等曲线偏差 %.2f' % err
    return b


def build(out, tpl, nef, files, prefix_note):
    """files: [(stem, ncp_bytes)]；整包写完再交给 NX Studio。"""
    if os.path.isdir(out):
        shutil.rmtree(out)
    side = os.path.join(out, 'NKSC_PARAM')
    os.makedirs(side)
    tpl_txt = S.template_text(tpl)
    for stem, ncp in files:
        txt = S.embed_data(tpl_txt, ncp, slot02=False)   # 两处都保留 0x08
        back_c = S.custom_data(txt)
        back_e = S.export_data(txt)
        assert back_c[NS_OFF] == ncp[NS_OFF], 'CustomData 第38字节被改'
        assert back_e[NS_OFF] == ncp[NS_OFF], 'ExportData 第38字节被改'
        assert back_c == ncp and back_e == ncp, '字节被改动'
        dst = os.path.join(out, stem + '.NEF')
        shutil.copy2(nef, dst)
        os.utime(dst, None)
        S.write_sidecar(os.path.join(side, stem + '.NEF.nksc'), txt)
        print('  %-14s 底子 0x%04X  第38字节 0x%02X  sidecar %d B'
              % (stem, C.read_ncp(ncp)['base'], ncp[NS_OFF],
                 os.path.getsize(os.path.join(side, stem + '.NEF.nksc'))))
    with open(os.path.join(out, prefix_note), 'w', encoding='utf-8') as f:
        f.write('整包已写完，可以打开。\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(ROOT, '..', '_probe_kind8'))
    ap.add_argument('--out-b', default=os.path.join(ROOT, '..', '_probe_kind8_b'))
    ap.add_argument('--nef', default=NEF)
    ap.add_argument('--template', default=TPL)
    ap.add_argument('--i-know-it-crashes', action='store_true',
                    help='2026-11-02 已证伪；无此开关一律拒绝执行')
    a = ap.parse_args()

    if not a.i_know_it_crashes:
        raise SystemExit(
            '拒绝执行：第 38 字节 = 0x08 已经实测三次，每次都让 NX Studio 在\n'
            'Rome2.dll +0x13d8f2 崩溃。kind 不是从这一格读的，写多少都一样。\n'
            '创意底子（0x0801–0x0814）在 NCP 里无法表达，别再试了。\n'
            '见 docs/19-namespace-byte.md 第八节、docs/20-in-camera-ceiling-locked.md。\n'
            '（确实要重跑请加 --i-know-it-crashes）')

    print('=== A 包：三张，第 38 字节全 = 0x08 ===')
    files = [(stem, make(stem, base, 0x08)) for base, stem, _, _ in PLAN]
    build(os.path.abspath(a.out), a.template, a.nef, files, '_可打开.txt')

    print()
    print('=== B 包：只有对照那张（A 崩了再看 B）===')
    build(os.path.abspath(a.out_b), a.template, a.nef,
          [files[0]], '_可打开.txt')

    print()
    print("""判读（先开 A）：
  三张都开、K1/K2 明显不像 STANDARD  → 第 38 字节就是命名空间，创意底子解锁，
                                       接着把 0x080E–0x0814 那几支也补进来
  仍然闪退（日志还是 +0x13d8f2）      → 这个字节不是命名空间，创意底子此路封死
  只开不崩但 K1 和 STANDARD 一模一样   → 认了 0x08 但底子仍回落，同样是封死
  A 崩了，B（只有对照）能开            → 同上，kind=8 本身合法、0801 却查不到""")

    print()
    print('对照：_probe_profile 里 0x0014/0x03D5/0x00D6 能正常渲染，'
          '而它们只在 kind=1 组 —— 说明渲染读的是 CustomData。')


if __name__ == '__main__':
    main()
