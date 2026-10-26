#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""曲线预补偿：抵消工坊「与照相机兼容」引擎在曲线前插入的那层变换。

怎么发现的
----------
T01_IDENT（恒等曲线）套用后不等于机身：中间调暗 18 级，两端归零。
T02_INVERT 的输出恰好是 T01 的 `255 - y`，这只有在「引擎先算 H(x)、再把结果交给我的曲线」
时才成立（若 H 加在曲线之后，需要 H 反对称，实测不是）。

模型
----
    输出 = C( H(x) )        x = 输入值（机内标准渲染的亮度）
                            H = 引擎在曲线前套的固定变换（实测）
                            C = 我写进 NCP 的曲线

  用 T01（C=恒等）直接量出 H；用 P29/P17/P01 三个形状迥异的曲线验证模型，
  分档残差从 12.6/10.5/8.9 降到 1.0/3.7/0.7。

补偿
----
想让输出 = T(x)，就写 C = T ∘ H⁻¹：

    C(y) = T( H⁻¹(y) )

H 的实测值（921600 像素、184262 个中性像素、4 级分档、中位数为统计量）
"""
import numpy as np

# 实测 H：输入亮度 -> 引擎实际喂给曲线的值
H_PTS = [
    (0, 0), (10, 9.0), (14, 12.0), (18, 14.9), (22, 18.5), (26, 21.9),
    (30, 24.6), (34, 27.9), (38, 31.1), (42, 34.1), (46, 37.2), (50, 40.6),
    (54, 43.8), (58, 46.9), (62, 50.2), (66, 53.6), (70, 56.9), (74, 60.1),
    (78, 63.4), (82, 67.0), (86, 70.3), (90, 73.9), (94, 77.4), (98, 80.9),
    (102, 84.4), (106, 88.3), (110, 92.1), (114, 95.9), (118, 99.9),
    (122, 103.9), (126, 108.3), (130, 112.3), (134, 116.2), (138, 120.1),
    (142, 124.2), (146, 127.4), (150, 132.0), (154, 136.1), (158, 140.6),
    (162, 144.9), (166, 149.5), (170, 154.4), (174, 158.9), (178, 164.0),
    (182, 169.2), (186, 174.1), (190, 179.1), (194, 183.9), (198, 188.3),
    (202, 193.7), (206, 197.6), (210, 202.9), (214, 207.0), (218, 211.9),
    (222, 216.5), (226, 220.9), (230, 225.7), (234, 230.5), (238, 235.0),
    (242, 239.7), (246, 243.9), (250, 248.6), (255, 255.0),
]


def _build():
    x = np.array([p[0] for p in H_PTS], dtype=float)
    y = np.array([p[1] for p in H_PTS], dtype=float)
    # 轻微平滑（3 点），再强制单调，避免量化噪声造成 H⁻¹ 抖动
    ys = y.copy()
    ys[1:-1] = (y[:-2] + y[1:-1] + y[2:]) / 3.0
    ys[0], ys[-1] = 0.0, 255.0
    ys = np.maximum.accumulate(ys)
    ys = np.clip(ys, 0, 255)
    return x, ys


HX, HY = _build()


def H(x):
    """引擎的曲线前变换（0..255 连续）"""
    return np.interp(np.clip(x, 0, 255), HX, HY)


def H_inv(v):
    """H 的反函数。H 单调不减，先去掉重复值再反转插值。"""
    v = np.clip(v, 0, 255)
    keep = np.r_[True, np.diff(HY) > 1e-9]
    return np.interp(v, HY[keep], HX[keep])


def precompensate(target_lut, out_max=32767):
    """把「想要的曲线」换成「写进文件的曲线」，抵消 H。

    target_lut: 257 项、0..out_max 的目标映射
    返回 new_lut: 引擎执行 C(H(x)) 之后等于 target 的曲线
    """
    t = np.asarray(target_lut, dtype=float) / out_max * 255.0
    t = np.clip(t, 0, 255)
    y = np.arange(257, dtype=float)          # 引擎交给曲线的值
    c = np.interp(H_inv(y), np.arange(257, dtype=float),
                  np.interp(np.arange(257), np.arange(257), t))
    c = np.clip(c, 0, 255)
    # 必须单调不减，否则机身重算曲线会抖
    c = np.maximum.accumulate(c)
    return [int(round(v / 255.0 * out_max)) for v in c]


def simulate(target_lut, out_max=32767, n=256):
    """用实测 H 模拟引擎执行补偿后文件的结果，与目标对比（自检用）"""
    comp = np.array(precompensate(target_lut, out_max), dtype=float) / out_max * 255.0
    x = np.arange(n, dtype=float) * 255.0 / (n - 1)
    out = np.interp(H(x), np.arange(257, dtype=float), comp)
    tgt = np.interp(x, np.arange(257, dtype=float),
                    np.asarray(target_lut, dtype=float) / out_max * 255.0)
    return x, out, tgt


if __name__ == '__main__':
    print('实测 H 的偏差（引擎 vs 直给）：')
    for v in (0, 16, 32, 64, 96, 128, 160, 192, 224, 255):
        print('  输入 %3d → H=%6.1f  偏差 %+5.1f' % (v, H(v), H(v) - v))
    print()
    print('H⁻¹ 关键点：')
    for v in (0, 20, 47, 64, 110, 128, 200, 255):
        print('  输出 %3d → 需要输入 %6.1f' % (v, H_inv(v)))
    print()
    tgt = [i * 32767 // 256 for i in range(257)]
    _, out, t = simulate(tgt)
    print('自检：恒等曲线补偿后，模拟输出与目标最大偏差 %.2f/255' % np.abs(out - t).max())
    print('     （补偿前同样是恒等曲线，偏差达 %.2f/255）'
          % np.abs(np.interp(np.arange(256) * 255 / 255, HX, HY) - np.arange(256)).max())
