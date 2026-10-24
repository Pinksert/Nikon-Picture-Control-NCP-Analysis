# -*- coding: utf-8 -*-
"""从 S_dump.txt 里还原 curve 记录字节，确认 LUT 起点，并尝试破解头部的校验值"""
import re, struct, sys
sys.stdout.reconfigure(encoding='utf-8')

txt = open(r'C:\Users\admin\WorkBuddy\D300固件\S_dump.txt', encoding='utf-8').read()
hexs = re.findall(r'^\s{5}[0-9A-F]{4}  ([0-9A-F ]+)$', txt, re.M)
data = bytes.fromhex(''.join(hexs).replace(' ', ''))
print('curve 记录数据长度:', len(data), '(应为 578)')

# LUT 起点候选：从搜索结果看起点 64 最像
for s in (60, 62, 64):
    v = struct.unpack('>257H', data[s:s + 514])
    print('起点 %3d: 首 %5d 末 %5d 峰值 %5d@%3d  单调率 %.0f%%'
          % (s, v[0], v[256], max(v), v.index(max(v)),
             100.0 * sum(1 for i in range(256) if v[i] <= v[i + 1]) / 256))

S = 64
lut = struct.unpack('>257H', data[S:S + 514])
print('\n确认：LUT 起点 = %d，257 点，首 %d 末 %d（量程 32767）' % (S, lut[0], lut[256]))
print('头部 64 字节:', data[:64].hex(' ').upper())
print('头部前 24 字节:', data[:24].hex(' ').upper())

# ---- 试着破解头两字节 0x4930 ----
def crc16_xmodem(d, crc=0):
    for b in d:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc

def crc16_ccitt(d, crc=0xFFFF):
    for b in d:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc

def crc16_modbus(d, crc=0xFFFF):
    for b in d:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc & 0xFFFF

def crc16_kermit(d, crc=0):
    for b in d:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc & 0xFFFF

TARGETS = {0x4930: '大端 4930', 0x3049: '小端 3049'}
CANDS = {
    'data[2:578] (跳过前2字节)': data[2:],
    'data[2:64] (头部剩余)': data[2:64],
    'data[64:578] (LUT)': data[64:],
    'data[0:578] 全部': data,
    'data[16:578]': data[16:],
    'data[18:578]': data[18:],
}
print('\n-- 尝试把头两字节 0x4930 解成 CRC16 --')
hit = False
for nm, buf in CANDS.items():
    for fn in (crc16_xmodem, crc16_ccitt, crc16_modbus, crc16_kermit):
        c = fn(buf)
        if c in TARGETS:
            print('  命中！%s + %s = %04X' % (nm, fn.__name__, c))
            hit = True
if not hit:
    print('  未命中。前 18 字节逐个看：', ' '.join('%02X' % b for b in data[:18]))
    print('  简单和校验：sum(data[2:])%%65536 = %04X' % (sum(data[2:]) % 65536))
    print('  sum(data[64:])%%65536 = %04X' % (sum(data[64:]) % 65536))
    print('  sum(data)%%65536 = %04X' % (sum(data) % 65536))
