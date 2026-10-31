# -*- coding: utf-8 -*-
"""从 v3-gap.html 的表格解析出 30 支明细，输出 Markdown 表 + CSV。

口径：
  v1 / v3 / 变化  = 全图 RGB 级差（与 audit_release.py、metrics.csv 同一口径）
  ΔE00 / 可辨 / |ΔL*| / |ΔC*| = 去剪裁口径（diag_residual.py，剪裁区不计）
"""
import csv
import io
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
HTML = os.path.join(ROOT, 'charts', 'v3-gap.html')

s = io.open(HTML, encoding='utf-8').read()
body = s[s.index('<h2>30 支明细</h2>'):]
body = body[:body.index('</table>')]
rows = []
for tr in re.findall(r'<tr>(.*?)</tr>', body, re.S):
    tds = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, re.S)
    if len(tds) < 11 or tds[0].strip() == '槽':
        continue
    def txt(x):
        return re.sub(r'<[^>]+>', '', x).replace('&nbsp;', ' ').strip()
    rows.append(dict(slot=int(txt(tds[0])),
                     name=re.sub(r'\s+', ' ', txt(tds[1])).strip(),
                     kind=txt(tds[2]),
                     v1=float(txt(tds[3])), v3=float(txt(tds[4])),
                     delta=float(txt(tds[5])), de=float(txt(tds[6])),
                     pct=float(txt(tds[7]).rstrip('%')),
                     dL=float(txt(tds[8])), dC=float(txt(tds[9]))))
assert len(rows) == 30, len(rows)

# 与 metrics.csv 交叉核对（两条独立路径，数字必须一致）
mc = {int(r['slot']): float(r['e_v3'])
      for r in csv.DictReader(io.open(os.path.join(ROOT, 'samples', 'metrics.csv'),
                                      encoding='utf-8-sig'))}
bad = [(r['slot'], r['v3'], mc[r['slot']]) for r in rows
       if abs(r['v3'] - mc[r['slot']]) > 0.011]
print('与 metrics.csv 核对：', '一致' if not bad else '不一致 ' + str(bad))

out = io.StringIO()
out.write('| 槽 | 滤镜 | 底子 | v1 实测 | v3 预测 | 变化 | ΔE00 | 可辨像素 | |ΔL\\*| | |ΔC\\*| |\n')
out.write('|---:|---|---|---:|---:|---:|---:|---:|---:|---:|\n')
for r in rows:
    out.write('| %d | %s | %s | %.2f | **%.2f** | %+.2f | %.2f | %.0f%% | %.2f | %.2f |\n'
              % (r['slot'], r['name'], r['kind'], r['v1'], r['v3'], r['delta'],
                 r['de'], r['pct'], r['dL'], r['dC']))
tbl = out.getvalue()

p = os.path.join(ROOT, 'samples', 'metrics_v3_full.csv')
with open(p, 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=['slot', 'name', 'kind', 'v1', 'v3', 'delta',
                                      'de00', 'pct', 'dL', 'dC'])
    w.writeheader()
    for r in rows:
        w.writerow(dict(slot=r['slot'], name=r['name'], kind=r['kind'], v1=r['v1'],
                        v3=r['v3'], delta=r['delta'], de00=r['de'], pct=r['pct'],
                        dL=r['dL'], dC=r['dC']))
print('CSV：', p)

q = os.path.join(ROOT, 'charts', 'v3-gap-table.md')
io.open(q, 'w', encoding='utf-8').write(tbl)
print('Markdown 表：', q)
print()
print(tbl[:600])
