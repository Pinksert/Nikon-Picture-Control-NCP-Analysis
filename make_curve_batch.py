# -*- coding: utf-8 -*-
r"""
make_curve_batch.py —— 批量：一组导出 JPG → 一批带曲线的 NCP

前提（重要）：
    · 同一张 NEF，在尼康工坊里用「最新的优化校准系统」导出多份 JPG
    · 其中一份用 STANDARD，其余每份用你想模拟的预设
    · 所有滑块保持默认（不要留"自动"），导出设置完全一致

用法：
    python make_curve_batch.py <放JPG的目录> [输出目录]

脚本会自动从每张 JPG 的 EXIF 里认出它用的是哪个预设（靠 MakerNote 里的
`03100310` 版本号 + 20 字节名称 + 底子编号），拿 STANDARD 那张当基准，
其余每张反推一条曲线，生成一个 638 字节的带曲线 NCP。
"""
import os, sys, json, struct, glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from np2ncp_curve import build_ncp, measure_lut, N_POINTS, OUT_MAX

APPROX_DIR = r'C:\Users\admin\WorkBuddy\D300固件\ncp_approx'


def pc_info(path):
    """从 JPG 的 MakerNote 里认出预设名和底子编号"""
    b = open(path, 'rb').read(20000)
    i = b.find(b'03100310')
    if i < 0:
        return None, None
    name = b[i + 8:i + 28].rstrip(b'\x00').decode('latin1', 'replace')
    base = struct.unpack('<H', b[i + 48:i + 50])[0]
    return name, base


def sliders_for(name):
    """滑块：优先沿用 ncp_approx 里同名近似版的参数，对比度/亮度改成交给曲线"""
    p = os.path.join(APPROX_DIR, name + '_from_np3.NCP')
    if os.path.exists(p):
        d = open(p, 'rb').read()
        sl = list(d[40:48])
    else:
        sl = [0x83, 0x80, 0x80, 0x80, 0x80, 0xFF, 0xFF, 0xFF]
    sl[1] = sl[2] = 0x01          # 对比度 / 亮度交给曲线
    return sl


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else os.path.join(src, 'curve_out')
    os.makedirs(dst, exist_ok=True)

    imgs = sorted(set(glob.glob(os.path.join(src, '*.JPG')) + glob.glob(os.path.join(src, '*.jpg'))))
    info = {}
    for f in imgs:
        n, b = pc_info(f)
        if n:
            info[f] = (n, b)
            print('  %s -> 预设 %s  底子 %04X' % (os.path.basename(f), n, b))
    if not info:
        print('没认出任何预设，检查是不是尼康工坊导出的 JPG')
        return

    base_img = None
    for f, (n, b) in info.items():
        if n.upper() == 'STANDARD' or b == 0x0001:
            base_img = f
            break
    if not base_img:
        print('没找到 STANDARD 那张做基准，无法反推')
        return
    print('\n基准图：%s' % os.path.basename(base_img))

    made = 0
    for f, (n, b) in sorted(info.items(), key=lambda kv: kv[1][0]):
        if f == base_img:
            continue
        print('\n反推 %s ...' % n)
        lut = measure_lut(base_img, f)
        json.dump({'lut': lut}, open(os.path.join(dst, n + '_lut.json'), 'w'))
        out = build_ncp(n[:20], 0x0001, sliders_for(n), lut)
        open(os.path.join(dst, n + '_curve.NCP'), 'wb').write(out)
        made += 1
        print('  -> %s_curve.NCP（%d 字节）' % (n, len(out)))
    print('\n共生成 %d 个带曲线 NCP -> %s' % (made, dst))


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()
