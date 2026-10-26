# -*- coding: utf-8 -*-
r"""
ncp_d300.py —— 把尼康新版优化校准（.NP2 / .NP3）做成 D300 能吃的带曲线 .NCP

为什么需要它
------------
D300 只认 .NCP（52 字节 / 638 字节两种），且只认六个底子编号：
    0001 标准   03C2 中性   00C3 鲜艳
    0486 人像   04C7 风景   064D 单色
新机型的 20 个「创意优化校准」用的是 0801–0814 底子，曲线在固件里，导不出来。
唯一能搬的是**影调**：NCP 支持一条用户自定义曲线（UDC，257 点一维亮度 LUT），
作用在 sRGB 伽马之后。所以策略是「六个已知底子里挑一个 + 挂一条实测 LUT」。

与流传脚本的区别（重要）
------------------------
1. 控制点与 LUT 写成同一条曲线。
   尼康自己的导出文件就是这样（M.NCP 控制点 x=73→y=140 即 54.9%，LUT 实测 54.7%）。
   有的脚本只给控制点加一个"闭环修正 delta"，导致控制点与 LUT 差 6.7%——
   机身是按控制点重算的，这时显示的曲线和实际生效的曲线不是一回事。
2. 底子按 LUT 的测量基准选。
   LUT 是「标准 -> 目标」测出来的，所以彩色预设一律落在 0001；
   挂到 0486/03C2 上等于把底子特征算两遍。

用法
----
    # 主流程：NP2/NP3 目录 + 曲线目录 -> 卡上可直接用的 PICCONnn.NCP
    python ncp_d300.py build <NP目录> [--curve 曲线目录] [-o 输出目录]

    # 体检：检查一个目录里的 NCP 是否真能被 D300 接受
    python ncp_d300.py verify <目录>

    # 自己重测一条曲线（尼康工坊导出同一张 NEF 的两版 JPG，都用「与照相机兼容」）
    python ncp_d300.py measure <标准版.jpg> <目标版.jpg> <输出.json>
"""
import os
import struct
import sys

# ---------------------------------------------------------------- 常量

OUT_MAX = 32767          # LUT 满量程：15 位，由尼康原厂 S.NCP 实测确认
HDR_LEN = 64             # 曲线记录头部：578 = 64 + 257*2
REC2_LEN = HDR_LEN + 257 * 2
HDR_PREFIX = bytes.fromhex('493000FF00FF0100')   # 固定标识，不是校验和
MAX_PTS = 20

# D300 认得的六个底子
BASES = {
    0x0001: '标准', 0x03C2: '中性', 0x00C3: '鲜艳',
    0x0486: '人像', 0x04C7: '风景', 0x064D: '单色',
}

# 单色「调色」枚举（与 D300 菜单顺序一致，已对说明书核对）
TONE_BW, TONE_SEPIA, TONE_CYANO, TONE_RED, TONE_YELLOW = 0, 1, 2, 3, 4
TONE_GREEN, TONE_BLUEGREEN, TONE_BLUE, TONE_PURPLEBLUE, TONE_REDPURPLE = 5, 6, 7, 8, 9

# 滑块哨兵
SL_AUTO = 0x00           # 自动
SL_CURVE = 0x01          # 曲线接管（只用于对比度/亮度）
SL_NA = 0xFF             # 不适用
SL_ZERO = 0x80           # 数值 0

# 各滑块的合法整数范围（D300 说明书 p151）
RANGE = {
    'sharp': (0, 9), 'contrast': (-3, 3), 'brightness': (-1, 1),
    'saturation': (-3, 3), 'hue': (-3, 3),
}


# ---------------------------------------------------------------- NP2/NP3 解析

def parse_cards(raw):
    """NP2/NP3 是 TLV 卡片链：type(4) + len(4) + data，type 需右移 8 位。

    ⚠️ 与 NCP 不同：NCP 的记录类型是裸大端 u32（00000001），
       NP2/NP3 的卡类型是「卡号 << 8」（卡 1 = 00000100）。两套编码别混用。
    """
    cards, off = {}, 4
    while off + 8 <= len(raw):
        t = struct.unpack_from('>I', raw, off)[0]
        if t == 0:
            break
        ln = struct.unpack_from('>I', raw, off + 4)[0]
        cards[t >> 8] = raw[off + 8: off + 8 + ln]
        off += 8 + ln
    return cards


def card_num(data):
    """把 2 字节参数卡解成整数值。

    编码：值 = (字节0 - 0x80) * 字节1 / 16；步进码 04 = 每格 0.25。
    字节1 == 0 的是枚举类（滤镜/调色），值本身就是 字节0 - 0x80。
    """
    if data is None or len(data) < 2:
        return None
    v, st = data[0], data[1]
    if v == 0xFF:
        return None                      # 不适用
    if st == 0:
        return v - 0x80                  # 枚举
    return (v - 0x80) * st / 16.0


def preset_from_np(raw):
    """读一个 NP2/NP3，返回 (名字, 底子编号, {参数名: 值})"""
    c = parse_cards(raw)
    # ⚠️ 名字卡是 ASCII 20 字节，不是 UTF-16BE（实测，见 README 分析）
    name = c.get(2, b'').rstrip(b'\x00').decode('ascii', 'replace')
    base = struct.unpack('>H', c[3][:2])[0] if len(c.get(3, b'')) >= 2 else 0
    vals = {k: card_num(c.get(i)) for k, i in (
        ('sharp', 6), ('clarity', 7), ('contrast', 8), ('brightness', 9),
        ('saturation', 10), ('hue', 11), ('filter', 12), ('tone', 13),
        ('tone_strength', 14))}
    return name, base, vals


# ---------------------------------------------------------------- NCP 构造

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def slider_byte(value, kind):
    """把整数值编码成 NCP 滑块的 1 个字节"""
    lo, hi = RANGE[kind]
    return SL_ZERO + _clamp(int(round(value)), lo, hi)


def sample_lut(lut, x):
    """在输入亮度 x（0..255）处对 LUT 求值 —— 生成端和体检端必须用同一个函数"""
    fi = x / 255.0 * 256.0
    i = min(int(fi), 255)
    return lut[i] + (lut[i + 1] - lut[i]) * (fi - i)


def repair_endpoints(lut, thresh=1028):
    """修掉端点假台阶。

    测曲线时脚本习惯性强制 lut[0]=0、lut[256]=满量程。若目标预设本身是
    抬黑（DREAM 输入 0 实测约输出 46/255），这个强制就在端点造出一道断崖：
    输入 0 -> 0，输入 1 -> 46。机身照这条曲线走，暗部会硬切一刀。

    做法：端点若与邻点跳变过大，就按邻段斜率外推，保持单调。
    阈值 1028/32767 ≈ 8/255，小跳变（正常曲线的端点收敛）不动。
    """
    lut = list(lut)
    fixed = []
    if lut[1] - lut[0] > thresh:
        before = lut[0]
        lut[0] = max(0, lut[1] - (lut[2] - lut[1]))
        fixed.append('起点 %d→%d' % (before, lut[0]))
    if lut[256] - lut[255] > thresh:
        before = lut[256]
        lut[256] = min(OUT_MAX, lut[255] + (lut[255] - lut[254]))
        fixed.append('终点 %d→%d' % (before, lut[256]))
    return lut, fixed


def header_from_lut(lut, npts=MAX_PTS):
    """把 LUT 采样成 npts 个控制点写进 64 字节头部。

    ⚠️ 两个坑：
    1. 控制点与 LUT 必须是同一条曲线。机身按控制点重算，两条曲线不一致时
       显示的和实际生效的不是一回事，重则画面色块化。
    2. **不能均匀撒点**。双色/木炭这类预设的曲线在局部极陡（相邻两格跳 27/255），
       20 个等距点根本压不住，实测整体误差能到 51/255。这里改成自适应：
       每轮在「当前折线与目标偏差最大」的位置补一个点，陡的地方自然点密。
    """
    npts = _clamp(npts, 2, MAX_PTS)

    def y8(x):
        return _clamp(int(round(sample_lut(lut, x) / OUT_MAX * 255.0)), 0, 255)

    xs = [0, 255]
    ys = [y8(0), y8(255)]
    while len(xs) < npts:
        best_x, best_e = None, 0.0
        for x in range(1, 255):
            if x in xs:
                continue
            j = 0
            while j + 2 < len(xs) and xs[j + 1] < x:
                j += 1
            x0, x1, y0, y1 = xs[j], xs[j + 1], ys[j], ys[j + 1]
            e = abs((y0 + (y1 - y0) * (x - x0) / (x1 - x0)) - y8(x))
            if e > best_e:
                best_x, best_e = x, e
        if best_x is None:
            break
        k = 0
        while xs[k] < best_x:
            k += 1
        xs.insert(k, best_x)
        ys.insert(k, y8(best_x))
    # y 必须非递减，否则机身重算出的曲线会抖（LUT 本身单调，这里只是兜底）
    for i in range(1, len(ys)):
        if ys[i] < ys[i - 1]:
            ys[i] = ys[i - 1]
    h = bytearray(HDR_PREFIX)
    h.append(len(xs))
    for x, y in zip(xs, ys):
        h += bytes([x, y])
    h += b'\x00' * (HDR_LEN - len(h))
    return bytes(h[:HDR_LEN])


def build_ncp(name, base, sliders, lut=None):
    """生成 .NCP。lut 为 None -> 52 字节；否则 638 字节。"""
    assert base in BASES, '底子 %04X 不在 D300 认得的六个里' % base
    nb = name.upper().encode('ascii', 'replace')[:20]
    assert len(nb) <= 20

    prof = bytearray(b'0100')                       # 版本
    prof += nb.ljust(20, b'\x00')                   # 名字 20 字节 ASCII
    prof += struct.pack('>H', base)                 # 底子编号
    prof += bytes([0, 0xFF])                        # 未修改 / 未知位
    prof += bytes(sliders)                          # 八个滑块
    assert len(prof) == 36

    out = bytearray(b'NCP\0')
    out += struct.pack('>II', 1, 36) + prof         # 记录 1：配置数据

    if lut is not None:
        assert len(lut) == 257
        data = header_from_lut(lut) + b''.join(
            struct.pack('>H', int(_clamp(v, 0, OUT_MAX))) for v in lut)
        assert len(data) == REC2_LEN
        out += struct.pack('>II', 2, REC2_LEN) + data   # 记录 2：曲线
    out += struct.pack('>I', 0)                     # 结束
    return bytes(out)


def read_curve(path):
    """从一个带曲线的 NCP 里取出 LUT；没有曲线返回 None"""
    raw = open(path, 'rb').read()
    if raw[:4] != b'NCP\0':
        return None
    off = 4
    while off + 8 <= len(raw):
        t, ln = struct.unpack_from('>II', raw, off)
        if t == 0:
            break
        if t == 2 and ln == REC2_LEN:
            return list(struct.unpack_from('>257H', raw, off + 8 + HDR_LEN))
        off += 8 + ln
    return None


# ---------------------------------------------------------------- 预设 -> NCP

# 尼康创意优化校准编号 01–20 与中文名（NAME_MAP.md）
CREATIVE = [
    ('DREAM', '梦幻'), ('MORNING', '清晨'), ('POP', '流行'), ('SUNDAY', '星期天'),
    ('SOMBER', '低沉'), ('DRAMA', '戏剧'), ('SILENCE', '静寂'), ('BLEACH', '漂白'),
    ('MELANCHOLIC', '忧郁'), ('PURE', '纯净'), ('DENIM', '牛仔布'), ('TOY', '玩具'),
    ('SEPIA', '棕褐色'), ('BLUE', '蓝色'), ('RED', '红色'), ('PINK', '粉色'),
    ('CHARCOAL', '木炭'), ('GRAPHITE', '石墨'), ('BINARY', '双色'), ('CARBON', '黑碳'),
]

# 调色类：源文件里「调色」字段是不适用，按预设名指定 D300 的调色枚举
TONING = {'SEPIA': TONE_SEPIA, 'BLUE': TONE_BLUE, 'RED': TONE_RED, 'PINK': TONE_REDPURPLE}

# 纯黑白类：单色底子 + 滤镜关 + B&W
PURE_MONO = {'CHARCOAL', 'GRAPHITE', 'BINARY', 'CARBON',
             'MONOCHROME', 'FLAT_MONOCHROME', 'DEEPTONE_MONOCHROME'}

# D300 机身自带的六个，不必再导
BUILTIN = {'STANDARD', 'NEUTRAL', 'VIVID', 'PORTRAIT', 'LANDSCAPE', 'MONOCHROME'}

# 转了没意义的
SKIP_REASON = {
    'AUTO': '参数全是「不适用」，转出来就是标准底子，而 D300 已有标准',
    'SILENCE_SAT-2': '同一预设的备选测法（饱和度 -2 版），与 SILENCE 重复',
}

# 底子选择：LUT 是「标准 -> 目标」测的，所以彩色一律 0001；单色必须 064D
def pick_base(name):
    if name in TONING or name in PURE_MONO:
        return 0x064D
    return 0x0001


def sliders_for(name, vals, has_curve):
    """按预设类型组八个滑块"""
    sharp = vals.get('sharp')
    sharp_b = SL_AUTO if sharp is None else slider_byte(sharp, 'sharp')

    if has_curve:
        contrast_b = SL_CURVE                 # 对比度交给曲线
        bright_b = SL_CURVE                   # 亮度交给曲线
    else:
        contrast_b = slider_byte(vals.get('contrast') or 0, 'contrast')
        bright_b = slider_byte(vals.get('brightness') or 0, 'brightness')

    sat = vals.get('saturation')
    hue = vals.get('hue')
    sat_b = SL_ZERO if sat is None else slider_byte(sat, 'saturation')
    hue_b = SL_ZERO if hue is None else slider_byte(hue, 'hue')

    # 单色三项
    if name in TONING:
        filt_b, tone_b, str_b = SL_ZERO, SL_ZERO + TONING[name], SL_ZERO + 4
    elif name in PURE_MONO:
        filt_b, tone_b, str_b = SL_ZERO, SL_ZERO + TONE_BW, SL_NA
    else:
        filt_b = tone_b = str_b = SL_NA       # 彩色底子：不适用

    return [sharp_b, contrast_b, bright_b, sat_b, hue_b, filt_b, tone_b, str_b]


# ---------------------------------------------------------------- 体检

def verify_one(path):
    """返回问题列表；空列表 = 通过"""
    bad = []
    raw = open(path, 'rb').read()
    if raw[:4] != b'NCP\0':
        return ['魔数不对']
    if len(raw) not in (52, 638):
        bad.append('长度 %d，只能是 52 或 638' % len(raw))

    off, rec = 4, {}
    while off + 8 <= len(raw):
        t, ln = struct.unpack_from('>II', raw, off)
        rec[t] = (ln, raw[off + 8: off + 8 + ln])
        if t == 0:
            break
        off += 8 + ln
    if 1 not in rec:
        return bad + ['缺记录 1']
    ln1, d1 = rec[1]
    if ln1 != 36:
        bad.append('记录 1 长度 %d，应为 36' % ln1)
    if d1[0:4] != b'0100':
        bad.append('版本串不是 0100')

    name_raw = d1[4:24]
    if any(b and not (0x20 <= b <= 0x7E) for b in name_raw.rstrip(b'\x00')):
        bad.append('名字含不可打印字符（机内会显示乱码）')
    if name_raw.rstrip(b'\x00') != name_raw.rstrip(b'\x00').upper():
        bad.append('名字不是大写（尼康自己的文件都是大写）')

    base = struct.unpack('>H', d1[24:26])[0]
    if base not in BASES:
        bad.append('底子 %04X 不在 D300 认得的六个里' % base)
    if d1[27] != 0xFF:
        bad.append('未知位不是 FF')

    sl = list(d1[28:36])
    ok_vals = set(range(0x80 - 3, 0x80 + 4)) | {SL_AUTO, SL_CURVE, SL_NA}
    if sl[0] not in set(range(0x80, 0x8A)) | {SL_AUTO, SL_NA}:
        bad.append('锐化 %02X 越界（0..9 或 A/—）' % sl[0])
    for idx, label, lo, hi in ((1, '对比度', -3, 3), (2, '亮度', -1, 1),
                               (3, '饱和度', -3, 3), (4, '色相', -3, 3)):
        if sl[idx] not in set(range(0x80 + lo, 0x80 + hi + 1)) | {SL_AUTO, SL_CURVE, SL_NA}:
            bad.append('%s %02X 越界（%d..%d 或 A/*/—）' % (label, sl[idx], lo, hi))
    if sl[5] not in set(range(0x80, 0x85)) | {SL_NA}:
        bad.append('滤镜 %02X 越界（0..4 或 —）' % sl[5])
    if sl[6] not in set(range(0x80, 0x8A)) | {SL_NA}:
        bad.append('调色 %02X 越界（0..9 或 —）' % sl[6])
    if sl[7] not in set(range(0x80, 0x8A)) | {SL_NA}:
        bad.append('调色强度 %02X 越界' % sl[7])
    _ = ok_vals

    # 曲线
    if len(raw) == 638:
        if 2 not in rec:
            bad.append('文件 638 字节但没有记录 2')
        else:
            ln2, d2 = rec[2]
            if ln2 != REC2_LEN:
                bad.append('记录 2 长度 %d，应为 %d' % (ln2, REC2_LEN))
            if d2[0:8] != HDR_PREFIX:
                bad.append('曲线头部前缀不是 493000FF00FF0100')
            n = d2[8]
            if not (2 <= n <= MAX_PTS):
                bad.append('控制点个数 %d 越界' % n)
            xs = [d2[9 + 2 * i] for i in range(n)]
            ys = [d2[10 + 2 * i] for i in range(n)]
            if any(xs[i] >= xs[i + 1] for i in range(n - 1)):
                bad.append('控制点 x 不是严格递增')
            if xs and (xs[0] != 0 or xs[-1] != 255):
                bad.append('控制点没覆盖 0..255')
            if any(ys[i] > ys[i + 1] for i in range(n - 1)):
                bad.append('控制点 y 非单调（机身重算会抖）')
            lut = struct.unpack_from('>257H', d2, HDR_LEN)
            # 端点不强制 0 / 满量程：抬黑、压高光的预设本来就该有偏移
            for i, lab in ((0, '起点'), (255, '终点')):
                jump = abs(lut[i + 1] - lut[i]) / OUT_MAX * 255.0
                if jump > 8.0:
                    bad.append('%s有 %.0f/255 的断崖（暗部/高光会硬切）' % (lab, jump))
            nonmono = sum(1 for i in range(256) if lut[i] > lut[i + 1])
            if nonmono:
                bad.append('LUT 有 %d 处下降' % nonmono)
            # 控制点 vs LUT 一致性（这是最容易被搞坏的一条）
            worst = 0.0
            for i in range(n):
                dev = abs(ys[i] - sample_lut(lut, xs[i]) / OUT_MAX * 255.0)
                worst = max(worst, dev)
            if worst > 1.5:
                bad.append('控制点与 LUT 最大偏差 %.1f/255 —— 两条曲线不是同一条' % worst)
            # 控制点能不能代表整条 LUT：按 20 点线性重建，看全表最大误差
            recon, j = [], 0
            for x in range(256):
                while j + 2 < n and xs[j + 1] < x:
                    j += 1
                x0, x1 = xs[j], xs[min(j + 1, n - 1)]
                y0, y1 = ys[j], ys[min(j + 1, n - 1)]
                recon.append(y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0))
            err = max(abs(recon[x] - sample_lut(lut, x) / OUT_MAX * 255.0)
                      for x in range(256))
            if err > 6.0:
                bad.append('20 个控制点压不住这条曲线，整体误差 %.1f/255' % err)
    elif 2 in rec:
        bad.append('有曲线记录但总长不是 638')
    return bad


# ---------------------------------------------------------------- 子命令

def cmd_build(argv):
    if not argv:
        print(__doc__)
        return 1
    src = argv[0]
    curve_dir = None
    dst = None
    i = 1
    while i < len(argv):
        if argv[i] == '--curve':
            curve_dir = argv[i + 1]; i += 2
        elif argv[i] in ('-o', '--out'):
            dst = argv[i + 1]; i += 2
        else:
            i += 1
    dst = dst or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out')
    os.makedirs(dst, exist_ok=True)

    # 曲线库：从带曲线的 NCP 里取 LUT，按文件名前缀匹配预设名
    curves = {}
    if curve_dir and os.path.isdir(curve_dir):
        for f in sorted(os.listdir(curve_dir)):
            if not f.upper().endswith('.NCP'):
                continue
            lut = read_curve(os.path.join(curve_dir, f))
            if lut:
                curves[os.path.splitext(f)[0].replace('_curve', '').upper()] = lut

    # 收集源文件，同名的优先 NP3（信息更全）
    srcs = {}
    for f in sorted(os.listdir(src)):
        stem, ext = os.path.splitext(f)
        if ext.upper() not in ('.NP2', '.NP3'):
            continue
        if stem.upper() not in srcs or ext.upper() == '.NP3':
            srcs[stem.upper()] = os.path.join(src, f)

    order = [n for n, _ in CREATIVE] + [
        'FLAT', 'FLAT_MONOCHROME', 'DEEPTONE_MONOCHROME',
        'RICH_TONE_PORTRAIT', 'FLEXIBLE_COLOR', 'AUTO']
    order += [n for n in sorted(srcs) if n not in order]
    # 只有曲线、没有 NP2/NP3 源文件的（这几个的曲线是直接从照片测出来的）
    order += [n for n in sorted(curves) if n not in order]

    rows, slot, nfail, skipped = [], 0, 0, []
    repairs = []
    for name in order:
        p = srcs.get(name)
        lut = curves.get(name)
        if p is None and lut is None:
            continue
        vals = preset_from_np(open(p, 'rb').read())[2] if p else {}
        # D300 机身自带这六个，再导一份没曲线的进去毫无意义
        if name in BUILTIN and lut is None:
            skipped.append('%s（机身自带）' % name)
            continue
        if name in SKIP_REASON:
            skipped.append('%s（%s）' % (name, SKIP_REASON[name]))
            continue
        fixes = []
        if lut is not None:
            lut, fixes = repair_endpoints(lut)
        base = pick_base(name)
        sl = sliders_for(name, vals, lut is not None)
        out = build_ncp(name, base, sl, lut)

        rec = 'PICCON%02d.NCP' % (slot + 1)
        open(os.path.join(dst, rec), 'wb').write(out)
        problems = verify_one(os.path.join(dst, rec))
        nfail += bool(problems)
        if fixes:
            repairs.append((name, fixes))
        rows.append((slot + 1, name, base, sl, lut is not None, None, problems))
        slot += 1

    # ---- 报告 ----
    print('输入 %s' % src)
    print('曲线库 %s（命中 %d 条）' % (curve_dir or '未提供', len(curves)))
    print('输出 %s' % dst)
    print('=' * 96)
    print('%-10s %-22s %-10s %-24s %-5s %s' %
          ('卡上文件', '预设名', '底子', '八滑块', '曲线', '体检'))
    print('-' * 96)
    for n, name, base, sl, has, srcb, prob in rows:
        print('%-10s %-22s %04X %-4s %-24s %-5s %s' % (
            'PICCON%02d' % n, name, base, BASES[base],
            ' '.join('%02X' % c for c in sl),
            '638B' if has else '52B',
            '通过' if not prob else '** ' + '；'.join(prob)))
    print('-' * 96)
    print('共 %d 个，体检不通过 %d 个' % (len(rows), nfail))
    no_curve = [r[1] for r in rows if not r[4]]
    if no_curve:
        print('没有实测曲线的（只有滑块近似，影调不像）：%s' % '、'.join(no_curve))
    if skipped:
        print('跳过（D300 机身自带且无曲线）：%s' % '、'.join(skipped))
    if repairs:
        print()
        print('端点假台阶已修复（测量脚本强制 lut[0]=0 / lut[256]=满量程 造成）：')
        for name, f in repairs:
            print('  %-22s %s' % (name, '，'.join(f)))

    # 清单
    man = os.path.join(dst, '_清单.txt')
    with open(man, 'w', encoding='utf-8') as f:
        cn = dict(CREATIVE)
        cn.update({'FLAT': '平面', 'FLAT_MONOCHROME': '平面单色',
                   'DEEPTONE_MONOCHROME': '深色调单色',
                   'RICH_TONE_PORTRAIT': '丰富色调人像',
                   'FLEXIBLE_COLOR': '灵活颜色', 'AUTO': '自动',
                   'STANDARD': '标准（新系统版）', 'NEUTRAL': '自然（新系统版）',
                   'VIVID': '鲜艳（新系统版）', 'LANDSCAPE': '风景（新系统版）',
                   'MONOCHROME': '单色（新系统版）'})
        for n, name, base, sl, has, srcb, prob in rows:
            f.write('PICCON%02d.NCP  %-22s %-14s 底子=%s%s\n' % (
                n, name, cn.get(name, ''), BASES[base],
                '' if not prob else '  [体检不通过]'))
    print('清单 -> %s' % man)
    return 0 if nfail == 0 else 2


def cmd_verify(argv):
    if not argv:
        print(__doc__)
        return 1
    d = argv[0]
    files = sorted(f for f in os.listdir(d) if f.upper().endswith('.NCP'))
    if not files:
        print('目录里没有 .NCP：%s' % d)
        return 1
    bad = 0
    for f in files:
        prob = verify_one(os.path.join(d, f))
        bad += bool(prob)
        print('%-24s %s' % (f, '通过' if not prob else '** ' + '；'.join(prob)))
    print('-' * 60)
    print('%d 个文件，不通过 %d 个' % (len(files), bad))
    return 0 if bad == 0 else 2


def cmd_measure(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1
    import json
    import numpy as np
    from PIL import Image

    def lum(p):
        a = np.asarray(Image.open(p).convert('RGB'), dtype=np.float64)
        return 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]

    A, B = lum(argv[0]), lum(argv[1])
    if A.shape != B.shape:
        print('两张图尺寸不一致：%s vs %s' % (A.shape, B.shape))
        return 1
    ai = np.clip(np.round(A), 0, 255).astype(np.int32).ravel()
    bi = B.ravel()
    sums = np.bincount(ai, weights=bi, minlength=256)
    cnts = np.bincount(ai, minlength=256)
    have = cnts > 50
    v8 = np.zeros(256)
    v8[have] = sums[have] / cnts[have]
    v8[0], v8[255] = 0.0, 255.0
    idx = np.where(~have)[0]
    if len(idx):
        v8[~have] = np.interp(idx, np.where(have)[0], v8[have])
    v8 = np.maximum.accumulate(v8)
    lut = [int(round(x)) for x in np.append(v8 / 255.0 * OUT_MAX, OUT_MAX)]
    json.dump({'lut': lut}, open(argv[2], 'w'))
    print('曲线已存 %s：257 点，首 %d 末 %d 中点 %d'
          % (argv[2], lut[0], lut[256], lut[128]))
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd, rest = sys.argv[1], sys.argv[2:]
    return {'build': cmd_build, 'verify': cmd_verify,
            'measure': cmd_measure}.get(cmd, lambda a: (print(__doc__), 1)[1])(rest)


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    sys.exit(main())
