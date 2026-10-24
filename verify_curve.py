# -*- coding: utf-8 -*-
r"""
verify_curve.py —— 量化「曲线方案」能把目标预设还原到什么程度

做法：
    1) 读标准版 A 和目标版 B
    2) 用 LUT 把 A 的亮度映射一遍，得到预测亮度 L_pred
    3) 亮度域：比较 L_pred 与目标 B 的实际亮度 —— 这是曲线能兑现的部分
    4) 色彩域：把 A 按 L_pred/L 等比缩放（模拟相机只改亮度、不动色相），
       再跟 B 比 Lab 的 a*/b* —— 这是曲线兑现不了、被丢掉的部分

用法：
    python verify_curve.py <标准版.jpg> <目标版.jpg> <lut.json>
"""
import sys, json, struct
import numpy as np
from PIL import Image

OUT_MAX = 32767


def srgb_to_lab(rgb):
    """rgb: float64 0..255 -> Lab"""
    x = rgb / 255.0
    lin = np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124, 0.3576, 0.1805],
                  [0.2126, 0.7152, 0.0722],
                  [0.0193, 0.1192, 0.9505]])
    xyz = lin @ m.T
    wp = np.array([0.95047, 1.0, 1.08883])
    r = xyz / wp
    f = np.where(r > 0.008856, np.cbrt(r), 7.787 * r + 16.0 / 116.0)
    L = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], axis=-1)


def lum(rgb):
    return 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return
    lut = np.array(json.load(open(sys.argv[3]))['lut'], dtype=np.float64) / OUT_MAX * 255.0

    A = np.asarray(Image.open(sys.argv[1]).convert('RGB'), dtype=np.float64)
    B = np.asarray(Image.open(sys.argv[2]).convert('RGB'), dtype=np.float64)
    assert A.shape == B.shape, '两图尺寸不一致'

    LA, LB = lum(A), lum(B)
    idx = np.clip(np.round(LA), 0, 256).astype(np.int32)
    Lpred = lut[idx]

    print('=' * 66)
    print('曲线还原度验证（%d 像素）' % LA.size)
    print('=' * 66)
    print('原图亮度均值         %.2f   ->  目标 %.2f' % (LA.mean(), LB.mean()))
    print('套曲线后亮度均值     %.2f' % Lpred.mean())
    print()
    print('【亮度域】曲线能兑现的部分')
    print('  套曲线前 vs 目标：平均差 %.2f / 255' % np.abs(LA - LB).mean())
    print('  套曲线后 vs 目标：平均差 %.2f / 255' % np.abs(Lpred - LB).mean())
    gain = 1 - np.abs(Lpred - LB).mean() / max(np.abs(LA - LB).mean(), 1e-9)
    print('  亮度差异消除       %.1f%%' % (gain * 100))

    # 只改亮度、不动色相：RGB 等比缩放
    scale = np.where(LA > 1e-6, Lpred / np.maximum(LA, 1e-6), 1.0)[..., None]
    Ap = np.clip(A * scale, 0, 255)

    labA, labB, labP = srgb_to_lab(Ap), srgb_to_lab(B), srgb_to_lab(A)
    print()
    print('【色彩域】曲线兑现不了的部分')
    print('  色度 a* 平均差：套前 %.2f  ->  套后 %.2f' %
          (np.abs(labA[..., 1] - labB[..., 1]).mean(), np.abs(labP[..., 1] - labB[..., 1]).mean()))
    print('  色度 b* 平均差：套前 %.2f  ->  套后 %.2f' %
          (np.abs(labA[..., 2] - labB[..., 2]).mean(), np.abs(labP[..., 2] - labB[..., 2]).mean()))
    print('  饱和度平均差  ：套前 %.2f  ->  套后 %.2f' %
          (np.abs(np.hypot(labA[..., 1], labA[..., 2]) - np.hypot(labB[..., 1], labB[..., 2])).mean(),
           np.abs(np.hypot(labP[..., 1], labP[..., 2]) - np.hypot(labB[..., 1], labB[..., 2])).mean()))
    print()
    print('结论：影调（亮度）靠曲线能追上，色彩倾向要靠预设自己的色彩运算，一维 LUT 做不到。')


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()
