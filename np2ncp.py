# -*- coding: utf-8 -*-
r"""
np2ncp.py —— 把尼康优化校准 .NP2 / .NP3 降级转换成 .NCP（52 字节，D300/D300S/D90 等老机型可用）

用法：
    python np2ncp.py <输入目录> [输出目录]
    例：python np2ncp.py "D300固件/滤镜" ./out_ncp

原理（实测 96/96 字节命中，见同目录 np2ncp_verify.py）：
    NP2/NP3 是 TLV 卡片链，NCP 是"抬头+名字+曲线号+8 个滑块+结束标记"。
    参数卡按下面的表一一搬进 NCP 的 8 个字节：
        卡 6  锐化      -> NCP[40]
        卡 8  对比度    -> NCP[41]
        卡 9  亮度      -> NCP[42]
        卡 10 饱和度    -> NCP[43]
        卡 11 色相      -> NCP[44]
        卡 12 滤镜效果  -> NCP[45]   （仅单色有效）
        卡 13 调色      -> NCP[46]   （仅单色有效）
        卡 14 调色强度  -> NCP[47]   （仅单色有效）
    数值：新格式 0.25 档（步进码 04），NCP 1 档 -> 四舍五入；FF=不适用。

丢什么（无法避免）：
    - 卡 7（清晰度，NP2 起新增）：NCP 没有这个位置，直接丢。
    - 卡 19~22（NP3 的快速锐化 / 中等锐化 / 效果级别等）：NCP 没有，直接丢。
    - 0.25 档的小数（如 +0.50）只能记成 0 或 1。
    - 亮度超过 ±1、锐化小于 0 的，会被钳到 NCP 的边界。
    - FLAT(028E) / AUTO(02CF) / 20 个创意底子(08 01–08 14) 在 NCP 里没有对应曲线，
      文件照样生成，但老机器没有这些曲线，用不了 —— 脚本会标 [!] 警示。
"""
import os, struct, sys

# NCP 已知的六个底子（D300 机内那套）
KNOWN_BASE = {0x0001: '标准', 0x03C2: '中性', 0x00C3: '鲜艳',
              0x0486: '人像', 0x04C7: '风景', 0x064D: '单色'}
# 单色「调色」的枚举值，尼康未公开，这里按 D300 单色菜单顺序推的，未实测：
# 0 黑白 / 1 棕褐 / 2 青 / 3 红 / 4 黄 / 5 绿 / 6 蓝绿 / 7 蓝 / 8 紫蓝 / 9 红紫
TONING_GUESS = {'SEPIA': 1, 'BLUE': 7, 'RED': 3, 'PINK': 9}
MAP = [(6, '锐化'), (8, '对比度'), (9, '亮度'), (10, '饱和度'),
       (11, '色相'), (12, '滤镜效果'), (13, '调色'), (14, '调色强度')]


def u32(b, o):
    return struct.unpack_from('>I', b, o)[0]


def parse_tlv(b):
    """返回 {卡号: 字节串或文本}"""
    out, off = {}, 4
    while off + 8 <= len(b):
        t = u32(b, off)
        if t == 0:
            break
        t >>= 8
        ln = u32(b, off + 4)
        d = b[off + 8: off + 8 + ln]
        if t == 1:                           # 版本卡
            out[t] = d.decode('latin1')
        elif t == 2:                         # 名字卡（UTF-16BE）
            out[t] = d.decode('utf-16-be', 'replace').rstrip('\x00')
        else:
            out[t] = d
        off += 8 + ln
    return out


def card_to_byte(d, name, warn):
    """新格式 2 字节卡 -> NCP 1 字节"""
    v, st = d[0], d[1]
    if v == 0xFF:
        return 0xFF
    if st == 0:                              # 滤镜/调色这类，值就是 0x80+n
        return 0x80 + (v - 0x80)
    raw = (v - 0x80) * st / 16.0             # 步进码 04 => 每格 0.25
    n = int(round(raw))
    if abs(raw - n) > 1e-9:
        warn.append('%s %+.2f 只能记成 %+d（NCP 是整档）' % (name, raw, n))
    if name == '锐化' and n < 0:
        warn.append('锐化 %+d 低于 0，NCP 最小是 0，已钳位' % n)
        n = 0
    if name == '亮度' and abs(n) > 1:
        warn.append('亮度 %+d 超出 NCP 的 -1~+1，已钳位' % n)
        n = max(-1, min(1, n))
    return 0x80 + max(-9, min(9, n))


def approx_base(name, c, base, sliders):
    """近似模式：把 NCP 不认的底子换成六个已知底子里最接近的一个。
       返回 (新底子, 说明, 是否被改动过滑块)"""
    if base in KNOWN_BASE:
        return base, None, False
    if base == 0x028E:                                   # 平面
        return 0x03C2, '平面 → 中性底子（平面本身就是低对比，中性最接近）', False
    if base == 0x02CF:                                   # 自动
        # 原文件八张卡全是"不适用"，没有数值可搬；按 AUTO 的语义（以标准为基础、
        # 由相机自动调色相和色调）补一份能被认识的默认值：锐化交给相机自动，其余取默认
        sliders[:] = [0x00, 0x80, 0x80, 0x80, 0x80, 0xFF, 0xFF, 0xFF]
        return 0x0001, ('自动 → 标准底子 + 锐化自动、其余默认'
                        '（原参数全是"不适用"，无数值可搬，这五项是按语义补的）'), True

    is_mono = (10 in c and c[10][0] == 0xFF and 11 in c and c[11][0] == 0xFF)
    if name in TONING_GUESS:                             # 蓝 / 棕褐 / 红 / 粉 这四种调色
        t = TONING_GUESS[name]
        sliders[5] = 0x80                                # 滤镜效果关掉
        sliders[6] = 0x80 + t                            # 调色 = 猜测的枚举值
        sliders[7] = 0x80 + 4                            # 调色强度 +4（原文件 ID14 就是 +4.00）
        return 0x064D, '%s → 单色底子 + 调色[%s] + 强度+4（色值枚举未实测）' % (name, name), True
    if is_mono:                                          # 黑白类创意预设
        return 0x064D, '%s → 单色底子（滤镜/调色/强度照搬，还原度较高）' % name, False
    return 0x0001, '%s → 标准底子做载体（参数照搬，但色彩曲线丢失，只是近似）' % name, False


def convert(src_bytes, approx=False):
    """-> (NCP 52 字节, 报告行列表)"""
    c = parse_tlv(src_bytes)
    warn = []
    name = c.get(2, 'PC').upper()
    base = struct.unpack('>H', c[3][:2])[0] if 3 in c and len(c[3]) >= 2 else 0
    sliders = [card_to_byte(c[i], nm, warn) for i, nm in MAP]

    # 新格式多出来、NCP 装不下的参数
    LOSTNAME = {7: '清晰度', 19: 'NP3 新增(快速锐化?)', 20: 'NP3 新增',
                21: '效果级别', 22: 'NP3 新增(中等锐化?)'}
    lost = []
    for i in sorted(LOSTNAME):
        if i in c and isinstance(c[i], (bytes, bytearray)) and c[i][0] != 0xFF:
            v, st = c[i][0], c[i][1]
            if st == 4:                      # 步进码 04 = 每格 0.25，换算可靠
                s = '%+.2f' % ((v - 0x80) * st / 16.0)
            else:                            # 步进码不是 04 的，只报原始字节，不乱猜
                s = '[%02X %02X]' % (v, st)
            lost.append('卡%d %s = %s' % (i, LOSTNAME[i], s))

    note = None
    if approx:
        base, note, _ = approx_base(name, c, base, sliders)

    b = bytearray(52)
    b[0:4] = b'NCP\0'
    struct.pack_into('>I', b, 4, 1)          # 记录类型 = 1（配置数据）
    struct.pack_into('>I', b, 8, 36)         # 记录长度 = 36
    b[12:16] = b'0100'                       # 版本
    nb = name.encode('ascii', 'replace')[:20]
    b[16:16 + len(nb)] = nb                  # 名字，不足补零
    struct.pack_into('>H', b, 36, base)      # 基准曲线编号
    b[38] = 0                                # 未被用户修改
    b[39] = 0xFF
    for i, s in enumerate(sliders):
        b[40 + i] = s
    b[48:52] = b'\0\0\0\0'                   # 结束标记

    rep = []
    if note:
        rep.append('[近似] ' + note)
    if base in KNOWN_BASE:
        rep.append('底子 %04X = %s（NCP 认得）' % (base, KNOWN_BASE[base]))
    else:
        rep.append('[!] 底子 %04X 不在 NCP 的六个底子里 —— 文件能生成，但老机身没有这条曲线' % base)
    if lost:
        rep.append('[丢] NCP 无对应位置：' + '、'.join(lost))
    rep += ['[丢] ' + w for w in warn]
    return bytes(b), rep


def main():
    args = [a for a in sys.argv[1:] if a not in ('--no-pause', '--approx')]
    approx = '--approx' in sys.argv
    if args and args[0] in ('-h', '--help'):
        print(__doc__)
        return

    here = os.path.dirname(os.path.abspath(__file__))
    if len(args) >= 1:
        src = args[0]
    else:
        # 双击运行、没给参数：先找脚本旁边的「滤镜」目录，找不到就用脚本所在目录
        src = os.path.join(here, '滤镜')
        if not os.path.isdir(src):
            src = here
    dst = args[1] if len(args) >= 2 else os.path.join(here, 'ncp_out')

    print('=' * 60)
    print('尼康优化校准 NP2 / NP3 → NCP 转换器')
    print('输入目录：%s' % src)
    print('输出目录：%s' % dst)
    print('模式：%s' % ('近似 —— 底子换成老机身认得的，参数照搬'
                        if approx else '原样转换 —— 底子照抄，认不出的会标 [!]'))
    print('=' * 60, flush=True)

    if not os.path.isdir(src):
        print('\n[错误] 输入目录不存在：%s' % src)
        print('把本脚本放到那个目录旁边再双击，或者在命令行里指定路径：')
        print('    python np2ncp.py <输入目录> [输出目录]')
        pause()
        return

    os.makedirs(dst, exist_ok=True)
    log = []
    n = usable = 0
    for f in sorted(os.listdir(src)):
        if not f.upper().endswith(('.NP2', '.NP3')):
            continue
        try:
            raw = open(os.path.join(src, f), 'rb').read()
            out, rep = convert(raw, approx)
        except Exception as e:
            n += 1
            msg = '%s -> [跳过] 这个文件读不动：%s' % (f, e)
            print(msg, flush=True)
            log.append(msg)
            continue
        o = os.path.join(dst, os.path.splitext(f)[0] + '_from_' + f[-3:].lower() + '.NCP')
        open(o, 'wb').write(out)
        n += 1
        line = '%s -> %s (%d 字节)' % (f, os.path.basename(o), len(out))
        print(line, flush=True)
        log.append(line)
        for r in rep:
            print('      ' + r, flush=True)
            log.append('      ' + r)
            if r.startswith('底子') and 'NCP 认得' in r:
                usable += 1

    tail = ['', '=' * 60,
            '共转换 %d 个，NCP 文件在：%s' % (n, dst),
            '其中底子老机身认得、真能用的：%d 个' % usable,
            '其余是 NCP 里没有对应曲线的，文件能生成但相机调不出来']
    for t in tail:
        print(t, flush=True)
        log.append(t)

    try:
        open(os.path.join(dst, '_转换日志.txt'), 'w', encoding='utf-8').write('\n'.join(log))
    except Exception:
        pass
    pause()


def pause():
    """双击运行时停一下，让人看得见结果；命令行加 --no-pause 就不停"""
    if '--no-pause' in sys.argv:
        return
    try:
        if sys.stdin and sys.stdin.isatty():
            input('\n按回车键关闭窗口...')
    except Exception:
        pass


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        print('\n[出错] 上面是错误信息，把它发给 AI 就能定位。')
        try:
            if sys.stdin and sys.stdin.isatty():
                input('\n按回车键关闭窗口...')
        except Exception:
            pass
