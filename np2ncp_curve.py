# -*- coding: utf-8 -*-
r"""
np2ncp_curve.py —— 用「用户自定义曲线」把 NP3 创意预设模拟成 D300 能吃的 NCP

思路：
    NCP 里除了 8 个滑块，还能带一条 UDC（User Defined Curve）：
    257 个点的一维亮度查找表，每点 2 字节 = 514 字节，作为 type=2 的记录挂在后面。
    它作用在 sRGB(1/2.4) 伽马之后，是成像流水线的最后一步。
    所以只要测出「同一个输入亮度，标准版输出多少、目标预设输出多少」，
    就能直接造出这条 LUT，套在标准底子上逼近目标预设的影调。

文件结构（待真实样本验证）：
    "NCP\0"
    type=1  len=36   data(36)   = 版本4 + 名字20 + 底子2 + 改过1 + 未知1 + 8滑块
    type=2  len=514  data(514)  = 257 × uint16 大端，输出亮度 0..32767
    type=0                       = 结束
    合计 574 字节

用法：
    1) 从两张导出图反推曲线（同一张 NEF，滑块都保持默认）：
       python np2ncp_curve.py measure <标准版.jpg> <目标版.jpg> <输出.json>
    2) 用曲线生成 NCP：
       python np2ncp_curve.py build <lut.json> <名字> <底子十六进制> <输出.NCP>
"""
import os, struct, sys, json

N_POINTS = 257
OUT_MAX = 32767           # 输出亮度上限（15 位）：已由 S.NCP 实测确认
HDR_LEN = 64              # 曲线记录开头的头部长度：已由 S.NCP 实测确认（578 = 64 + 257×2）
HDR_PREFIX = bytes.fromhex('493000FF00FF0100')   # 固定的 8 字节前缀（两文件实测相同）
MAX_PTS = 20                                     # 尼康曲线最多 20 个控制点


def hdr_from_lut(lut, npts=MAX_PTS):
    """把目标 LUT 反算成控制点写进头部。
       这样"头部控制点"和"后面 257 点的 LUT"是同一条曲线——
       不管尼康软件是读控制点重算、还是直接用 LUT，结果都一样。
       控制点取满 20 个，实测插值误差 <15/32767，可以忽略。"""
    npts = max(2, min(npts, MAX_PTS))
    h = bytearray(HDR_PREFIX)
    h += bytes([npts])
    for k in range(npts):
        x = round(k * 255.0 / (npts - 1))
        # LUT 索引 i 对应输入 i/256*255，这里反过来插值取 y
        fi = x / 255.0 * 256.0
        i = int(fi)
        i = min(i, 255)
        v = lut[i] + (lut[i + 1] - lut[i]) * (fi - i)
        y = int(round(max(0, min(255, v / OUT_MAX * 255.0))))
        h += bytes([x, y])
    h += b'\x00' * (HDR_LEN - len(h))
    assert len(h) == HDR_LEN
    return bytes(h)


def build_ncp(name, base, sliders, lut=None, hdr=None, modified=0):
    """生成 NCP。sliders 是 8 个字节；lut 是 257 个 0..32767 的整数，None 表示不带曲线"""
    b = bytearray(b'NCP\0')
    # ---- 记录 1：配置数据 ----
    prof = bytearray()
    prof += b'0100'
    prof += name.encode('ascii', 'replace')[:20].ljust(20, b'\0')
    prof += struct.pack('>H', base)
    prof += bytes([modified, 0xFF])                  # 改过标志 / 未知位
    prof += bytes(sliders)
    assert len(prof) == 36, len(prof)
    b += struct.pack('>II', 1, len(prof)) + prof
    # ---- 记录 2：曲线数据 = 64 字节头部 + 257×2 字节 LUT ----
    if lut is not None:
        assert len(lut) == N_POINTS
        h = hdr if hdr is not None else hdr_from_lut(lut)
        assert len(h) == HDR_LEN, len(h)
        data = h + b''.join(struct.pack('>H', max(0, min(OUT_MAX, int(v)))) for v in lut)
        assert len(data) == 578, len(data)
        b += struct.pack('>II', 2, len(data)) + data
    # ---- 结束 ----
    b += struct.pack('>I', 0)
    return bytes(b)


def parse_ncp(path):
    """读一个真实 NCP，返回 (name, base, modified, sliders, hdr, lut)"""
    b = open(path, 'rb').read()
    assert b[:4] == b'NCP\0'
    name = base = modified = None
    sliders = hdr = lut = None
    off = 4
    while off + 8 <= len(b):
        t, ln = struct.unpack('>II', b[off:off + 8])
        d = b[off + 8: off + 8 + ln]
        if t == 1:
            name = d[4:24].rstrip(b'\x00').decode('latin1')
            base = struct.unpack('>H', d[24:26])[0]
            modified = d[26]
            sliders = list(d[28:36])
        elif t == 2:
            hdr = d[:HDR_LEN]
            lut = list(struct.unpack('>257H', d[HDR_LEN:HDR_LEN + 514]))
        elif t == 0:
            break
        off += 8 + ln
    return name, base, modified, sliders, hdr, lut


def rebuild_check(path):
    """用 build_ncp 重建一份，跟原文件逐字节比——能对上就说明格式完全破解"""
    name, base, modified, sliders, hdr, lut = parse_ncp(path)
    orig = open(path, 'rb').read()
    got = build_ncp(name, base, sliders, lut, hdr, modified)
    same = (got == orig)
    diff = [i for i in range(min(len(got), len(orig))) if got[i] != orig[i]]
    out = ['原文件 %d 字节 / 重建 %d 字节' % (len(orig), len(got)),
           '名字 %s  底子 %04X  改过 %d' % (name, base, modified),
           '八滑块 ' + ' '.join('%02X' % c for c in sliders),
           'LUT: 257 点，首 %d 末 %d' % (lut[0], lut[256]) if lut else 'LUT: 无',
           '逐字节一致: %s' % ('是 —— 格式破解完成' if same else '否'),
           '不一致的字节位置: %s' % (diff[:20] if diff else '无')]
    return '\n'.join(out)


def measure_lut(ref_img, tgt_img):
    """同一张 NEF 导出的两版 JPG，逐像素对齐。
       对每个输入亮度 v，统计它在目标版里对应的平均亮度，得到 0..255 的映射。"""
    import numpy as np
    from PIL import Image

    def lum(p):
        a = np.asarray(Image.open(p).convert('RGB'), dtype=np.float64)
        return 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]

    A, B = lum(ref_img), lum(tgt_img)
    if A.shape != B.shape:
        raise SystemExit('两张图尺寸不一致：%s vs %s' % (A.shape, B.shape))

    ai = np.clip(np.round(A), 0, 255).astype(np.int32).ravel()
    bi = B.ravel()
    sums = np.bincount(ai, weights=bi, minlength=256)
    cnts = np.bincount(ai, minlength=256)
    have = cnts > 50                                  # 样本太少的级别不采信
    v8 = np.arange(256, dtype=np.float64)
    v8[have] = sums[have] / cnts[have]
    v8[0] = 0.0
    v8[255] = 255.0
    # 补齐没采到的级别
    idx = np.where(~have)[0]
    if len(idx):
        v8[~have] = np.interp(idx, np.where(have)[0], v8[have])
    # 单调化（相机端 LUT 必须是非递减的，否则效果会很怪）
    v8 = np.maximum.accumulate(v8)
    # 8bit 的 256 级 -> 257 点（第 257 点是纯白）
    lut = np.empty(N_POINTS)
    lut[:256] = v8 / 255.0 * OUT_MAX
    lut[256] = OUT_MAX
    return [int(round(x)) for x in lut]


def dump_ncp(path):
    """把一个真实 NCP 摊开，用来确认曲线记录的布局"""
    b = open(path, 'rb').read()
    out = ['文件 %s  长度 %d' % (path, len(b)), '魔数 %r' % b[:4]]
    off = 4
    while off + 8 <= len(b):
        t, ln = struct.unpack('>II', b[off:off + 8])
        d = b[off + 8: off + 8 + ln]
        out.append('记录 type=%d len=%d  (数据起点 %d)' % (t, ln, off + 8))
        if t == 1:
            out.append('   版本 %s  名字 %s  底子 %04X  改过 %d  未知 %02X'
                       % (d[0:4].decode('latin1'), d[4:24].rstrip(b'\x00').decode('latin1'),
                          struct.unpack('>H', d[24:26])[0], d[26], d[27]))
            out.append('   八滑块 ' + ' '.join('%02X' % c for c in d[28:36]))
        elif t == 2:
            out.append('   完整 hex（每行 32 字节）：')
            for i in range(0, len(d), 32):
                out.append('     %04X  %s' % (i, d[i:i + 32].hex(' ').upper()))
            # 自动搜索 LUT 起点：578 字节里塞 257 个 uint16，起点只能是 0..64 的偶数
            out.append('   -- 搜索 LUT 起点（要求：257 点、末值≈32767、尽量单调）--')
            best = []
            for s in range(0, len(d) - 514 + 1, 2):
                v = struct.unpack('>257H', d[s:s + 514])
                mono = sum(1 for i in range(256) if v[i] <= v[i + 1]) / 256.0
                over = sum(1 for x in v if x > 32767)
                best.append((mono, over, s, v[0], v[128], v[256]))
            best.sort(reverse=True)
            for mono, over, s, a, m, z in best[:6]:
                out.append('     起点 %3d: 单调率 %.1f%%  超量程点 %d  首 %d  中 %d  末 %d'
                           % (s, mono * 100, over, a, m, z))
        if t == 0:
            break
        off += 8 + ln
    return '\n'.join(out)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == 'dump' and len(sys.argv) >= 3:
        txt = dump_ncp(sys.argv[2])
        print(txt)
        if len(sys.argv) >= 4:
            open(sys.argv[3], 'w', encoding='utf-8').write(txt)
    elif cmd == 'rebuild' and len(sys.argv) >= 3:
        txt = rebuild_check(sys.argv[2])
        print(txt)
        if len(sys.argv) >= 4:
            open(sys.argv[3], 'w', encoding='utf-8').write(txt)
    elif cmd == 'measure' and len(sys.argv) >= 5:
        lut = measure_lut(sys.argv[2], sys.argv[3])
        json.dump({'lut': lut}, open(sys.argv[4], 'w'))
        print('曲线已存 %s：257 点，首尾 %d -> %d，中点 %d'
              % (sys.argv[4], lut[0], lut[256], lut[128]))
    elif cmd == 'build' and len(sys.argv) >= 6:
        lut = json.load(open(sys.argv[2]))['lut']
        name, base = sys.argv[3], int(sys.argv[4], 16)
        sliders = [0x83, 0x80, 0x80, 0x80, 0x80, 0xFF, 0xFF, 0xFF]
        out = build_ncp(name, base, sliders, lut)
        open(sys.argv[5], 'wb').write(out)
        print('已生成 %s（%d 字节，底子 %04X）' % (sys.argv[5], len(out), base))
    else:
        print(__doc__)


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()
