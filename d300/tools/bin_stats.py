# -*- coding: utf-8 -*-
import csv
import io
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
rows = list(csv.DictReader(io.open(os.path.join(ROOT, 'samples', 'metrics_v3_full.csv'),
                                   encoding='utf-8')))
v = [(r['name'], float(r['v3']), float(r['v1']), float(r['dL']), r['kind']) for r in rows]
n3 = sum(x[2] for x in v) / 30
n3b = sum(x[1] for x in v) / 30
print('v1 %.2f → v3 %.2f 级（降 %.1f%%）' % (n3, n3b, (1 - n3b / n3) * 100))
print('|ΔL*| 均值 %.2f' % (sum(float(r['dL']) for r in rows) / 30))
mono = [x for x in v if x[4] == '单色']
col = [x for x in v if x[4] == '彩色']
print('单色 %d 支 %.2f 级 ｜ 彩色 %d 支 %.2f 级'
      % (len(mono), sum(x[1] for x in mono) / len(mono),
         len(col), sum(x[1] for x in col) / len(col)))
print()
bins = [(0, 3.5, '几乎看不出'), (3.5, 6, '接近'), (6, 9, '看得出'), (9, 99, '明显两样')]
for lo, hi, lab in bins:
    g = sorted([x for x in v if lo < x[1] <= hi], key=lambda x: -x[1])
    print('%-6s %2d 支：%s' % (lab, len(g),
                            '、'.join('%s %.2f' % (x[0], x[1]) for x in g)))
s = sorted(v, key=lambda x: -x[1])
print()
print('最像 3：', '、'.join('%s %.2f' % (x[0], x[1]) for x in s[-3:][::-1]))
print('最差 3：', '、'.join('%s %.2f' % (x[0], x[1]) for x in s[:3]))
print()
print('单色/彩色分组明细（v3 升序）：')
for lab, g in (('单色', mono), ('彩色', col)):
    print('  %s：%s' % (lab, '、'.join('%s %.2f' % (x[0], x[1])
                                    for x in sorted(g, key=lambda x: x[1]))))
