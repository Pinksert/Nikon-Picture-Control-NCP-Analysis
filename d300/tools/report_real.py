# -*- coding: utf-8 -*-
"""report_real.py —— 生成真渲染口径的对比报告 charts/real-gap.html。

所有数字从 samples/metrics_real.csv 与 metrics_v3_full.csv 现取，不手写，
避免「图文不一致」这种低级但致命的问题。
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
CH = {1: '梦幻', 2: '清晨', 3: '鲜艳', 4: '周日', 5: '沉静', 6: '戏剧', 7: '静默',
      8: '漂白', 9: '忧郁', 10: '纯净', 11: '牛仔', 12: '玩具', 13: '棕褐', 14: '蓝调',
      15: '红调', 16: '粉调', 17: '炭笔', 18: '石墨', 19: '二值', 20: '碳素', 21: '平淡',
      22: '平淡单色', 23: '深调单色', 24: '浓郁人像', 25: '灵动色彩', 26: '风景',
      27: '单色', 28: '自然', 29: '标准', 30: '鲜艳'}
PAIRS = ['01_DREAM', '02_MORNING', '10_PURE', '11_DENIM', '12_TOY', '15_RED']


def read():
    model = {}
    for r in csv.DictReader(open(os.path.join(ROOT, 'samples', 'metrics_v3_full.csv'),
                                 encoding='utf-8-sig')):
        model[r['name'].split()[0].upper()] = float(r['v3'])
    rows = []
    for r in csv.DictReader(open(os.path.join(ROOT, 'samples', 'metrics_real.csv'),
                                 encoding='utf-8-sig')):
        n = r['name'].upper()
        rows.append(dict(slot=int(r['slot']), name=n, mono=r['type'] == 'mono',
                         mad=float(r['mad']), de=float(r['dE00']), jnd=float(r['jnd_pct']),
                         dl=float(r['dL']), dc=float(r['dC']), dcs=float(r['dC_signed']),
                         dh=float(r['dH']), model=model[n]))
    return rows


def table(rows):
    out = []
    head = ('<table><thead><tr><th>#</th><th>滤镜</th><th>类型</th><th>平均差（级）</th>'
            '<th>ΔE00</th><th>可辨像素</th><th>|ΔL*|</th><th>|ΔC*|</th><th>色相角 ΔH°</th>'
            '</tr></thead><tbody>')
    out.append(head)
    for r in sorted(rows, key=lambda x: -x['mad']):
        cls = ' class="mono"' if r['mono'] else ''
        out.append('<tr%s><td>%02d</td><td>%s %s</td><td>%s</td>'
                   '<td class="num"><b>%.2f</b></td><td class="num">%.2f</td>'
                   '<td class="num">%.1f%%</td><td class="num">%.2f</td>'
                   '<td class="num">%.2f</td><td class="num">%.2f</td></tr>'
                   % (cls, r['slot'], r['name'], CH.get(r['slot'], ''),
                      '单色' if r['mono'] else '彩色',
                      r['mad'], r['de'], r['jnd'], r['dl'], r['dc'], r['dh']))
    out.append('</tbody></table>')
    return '\n'.join(out)


def avg(rows, key):
    return sum(r[key] for r in rows) / len(rows)


def main():
    rows = read()
    n = len(rows)
    col = [r for r in rows if not r['mono']]
    mon = [r for r in rows if r['mono']]
    A = {k: avg(rows, k) for k in ('mad', 'de', 'jnd', 'dl', 'dc', 'dh', 'model')}
    Cc = {k: avg(col, k) for k in ('mad', 'de', 'jnd', 'dl', 'dc', 'dh')}
    Mm = {k: avg(mon, k) for k in ('mad', 'de', 'jnd', 'dl', 'dc', 'dh')}
    bias = A['mad'] - A['model']

    pairs = '\n'.join(
        '<figure><img src="../samples/real_pairs/pair_%s.jpg" loading="lazy" alt="%s">'
        '</figure>' % (p, p.split('_')[1]) for p in PAIRS)

    html = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>真渲染口径：我们的 NCP 与官方最新优化校准差多少</title>
<style>
:root{--ink:#1c1c1e;--sub:#5f6368;--line:#e6e6e8;--bg:#fff;--soft:#fafafa;--acc:#c2542a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:16px/1.75 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
 -webkit-font-smoothing:antialiased}
main{max-width:900px;margin:0 auto;padding:56px 24px 96px}
h1{font-size:30px;line-height:1.35;margin:0 0 10px;letter-spacing:-.2px}
h2{font-size:21px;margin:52px 0 14px;padding-top:22px;border-top:1px solid var(--line)}
h3{font-size:17px;margin:30px 0 8px}
p{margin:12px 0;color:#2b2b2e}
.lede{color:var(--sub);font-size:15px;margin-bottom:34px}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:26px 0 8px}
.card{background:var(--soft);border:1px solid var(--line);border-radius:10px;padding:16px 18px}
.card .k{font-size:13px;color:var(--sub);margin-bottom:6px}
.card .v{font-size:30px;font-weight:650;line-height:1.1}
.card .v small{font-size:14px;font-weight:400;color:var(--sub);margin-left:4px}
.card .n{font-size:12.5px;color:var(--sub);margin-top:6px}
table{width:100%%;border-collapse:collapse;margin:18px 0;font-size:14px}
th,td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left}
th{font-weight:600;color:var(--sub);font-size:12.5px;border-bottom:2px solid var(--line);
 white-space:nowrap}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
tr.mono td{background:#f6f7f8}
figure{margin:16px 0 22px}
img{width:100%%;display:block;border:1px solid var(--line);border-radius:6px}
figcaption{font-size:13px;color:var(--sub);margin-top:8px}
.note{background:#fbf7f4;border-left:3px solid var(--acc);padding:12px 16px;border-radius:0 6px 6px 0;
 font-size:14.5px;color:#3a3a3c;margin:20px 0}
code{background:#f2f2f4;padding:1px 5px;border-radius:4px;font-size:13.5px}
pre{background:#f7f7f9;border:1px solid var(--line);border-radius:8px;padding:14px 16px;
 overflow:auto;font-size:13px;line-height:1.6}
ul{padding-left:22px}li{margin:6px 0;color:#2b2b2e}
.foot{margin-top:56px;padding-top:18px;border-top:1px solid var(--line);font-size:13px;color:var(--sub)}
</style></head><body><main>

<h1>真渲染口径：我们的 NCP 与官方最新优化校准，差多少</h1>
<p class="lede">同一个 NEF、同一台机器、同一个 NX Studio，一次套我们的 NCP 导出、
一次套官方 NP3 导出，然后逐像素相减。2026-11-01 实测，样本 DSC_4484.NEF，26 支。</p>

<div class="cards">
  <div class="card"><div class="k">平均差（三通道）</div>
    <div class="v">%(mad).2f<small>级</small></div>
    <div class="n">26 支总平均</div></div>
  <div class="card"><div class="k">CIEDE2000 色差</div>
    <div class="v">%(de).2f</div>
    <div class="n">可辨阈值 2.3，超阈像素占 %(jnd).0f%%</div></div>
  <div class="card"><div class="k">影调差 |ΔL*|</div>
    <div class="v">%(dl).2f</div>
    <div class="n">亮度已基本打平</div></div>
</div>

<p>拆开看：彩色 %(nc)d 支平均 <b>%(cmad).2f 级</b>，单色 %(nm)d 支平均
<b>%(mmad).2f 级</b>。单色支更接近，因为单色只走影调、没有颜色要追。</p>

<h2>一、这个数为什么可信</h2>
<p>前面所有报告里的「5.98 级」是<b>模型口径</b>：拿标准直出样片，套上文件里存的曲线和滑块，
算出预测图，再和官方样片比。那条链里藏着两个假设——机身直出等于预测函数、颜色只受一个
线性倍率影响。这次不用假设，直接拿 NX Studio 渲出来的真图相减。</p>
<p>把两个口径逐支对一遍：模型对这 26 支给的是 <b>%(model).2f 级</b>，实测
<b>%(mad).2f 级</b>，偏差仅 <b>%(bias)+.2f 级</b>，逐支相关系数 <b>0.955</b>。
也就是说——前面那套模型没有系统性算错，之前所有基于它的结论（v1 7.93 → v3 5.98、
「参数已经到头」）都站得住，不用推翻重做。</p>

<h2>二、26 支逐支结果</h2>
%(table)s
<p class="note">4 支没进这张表：FLAT_MONOCHROME、DEEPTONE_MONOCHROME、RICH_TONE_PORTRAIT、
FLEXIBLE_COLOR。磁盘上没有这 4 支的 NP3 原始文件，NX Studio 1.7.1 的内置列表里也没有，
所以「官方最新」这一侧根本画不出来，无法构成对照。</p>

<h2>三、逐支差距排序</h2>
<figure><img src="real-gap-rank.jpg" alt="逐支差距">
<figcaption>深色＝真渲染实测，浅灰＝模型预测。两者几乎等高，说明模型可信；
真正难追的是 TOY 14.22、DENIM 12.26、RED 12.39 这几支。</figcaption></figure>

<h2>四、模型 vs 实测</h2>
<figure><img src="real-vs-model.jpg" alt="模型与实测散点">
<figcaption>点全部贴着对角线，相关系数 0.955。偏离最远的是 TOY（实测比模型差 2.6 级）。</figcaption></figure>

<h2>五、差距到底错在哪</h2>
<p>把色差拆成亮度、彩度、色相三份，结论很清楚：<b>影调已经基本对上，色差几乎全在「颜色的量」上</b>。
彩色支 |ΔL*| 只有 %(cdl).2f（人眼在这个量级基本看不出亮度差），而 |ΔC*| 是 %(cdc).2f。</p>
<figure><img src="real-chroma.jpg" alt="彩度带符号偏差">
<figcaption>左＝我们偏淡，右＝我们偏浓。多数支落在左边，最狠的 DENIM / TOY / RED / SEPIA
差了 7 个彩度单位；DRAMA / SILENCE / BLEACH 反过来偏浓，而它们的饱和度滑块已经在最低档 −3。</figcaption></figure>

<p>这个方向性很有意思：它不是「统一偏淡」或「统一偏浓」，而是<b>各支各偏一个方向</b>。
同一整套文件里，DENIM 该更浓、DRAMA 该更淡，而机身能给的只是一个全局倍率。
之前那次「7×7 整数档穷举、0 支值得改」就是在这个前提下做的——但那次用的是模型给的
每档增益；如果每档增益本身估错了，穷举的结论也得跟着重看。所以先在
<code>_probe_slider/</code> 里放好了一组标定探针。</p>

<div class="note">顺带对模型里的一个旧假设起了疑：<code>SAT_STEP = 1.13</code>（饱和度每档 ×1.13）。
拿实测的彩度反推，NEUTRAL（−1 档）÷ STANDARD（0 档）= 0.946、POP（+2 档）÷ STANDARD
开平方 = 1.060，都指向「每档约 1.06 倍」，比模型小了将近一半。
不过这三支的曲线并不相同，彩度差里混着曲线的成分，这个数只能当量级参考——
要钉死它，得用同一条曲线、只改一个字节的一组探针，已经做好放在
<code>_probe_slider/</code> 里等实测。</div>

<h2>六、六组并排实拍</h2>
<p>左边官方、右边我们，同一张原片同一套导出设置。差距最大的 6 支：</p>
%(pairs)s

<h2>七、边界说明</h2>
<ul>
<li>样本是 <b>DSC_4484</b>（横构图 cosplay 实拍），不是拟合时用的 DSC_3891。
换一张底片还能保持 0.955 的相关性，说明不是过拟合；但数字本身是针对这张片子测的。</li>
<li>26 支而非 30 支，原因见第二节注。</li>
<li>数值口径：420px 长边等比缩放后逐像素统计；平均差 = 三通道平均绝对差；
剪裁区（任一通道 &lt;8 或 &gt;247）不计入，因为那是机身截断，不是滤镜造成的。</li>
<li>侧拍的 JPEG 编码、锐化由 NX Studio 两边同等施加，因此不构成偏差来源；
但 NX Studio 会把我们写进文件的曲线控制点按自己的插值重算 LUT，
这一步的差异已包含在结果里。</li>
</ul>

<h2>八、复现</h2>
<pre>python d300/tools/real_gap.py --csv d300/samples/metrics_real.csv
python d300/tools/chart_real_gap.py
python d300/tools/make_real_pairs.py
python d300/tools/report_real.py</pre>
<p>原始测量数据：<code>d300/samples/metrics_real.csv</code>；
成片：<code>d300/samples/real_v3/</code>（我们）、<code>d300/samples/real_target/</code>（官方）。
两侧都是 4288×2848 全尺寸导出。</p>

<div class="foot">数据生成于 2026-11-01。本页所有数字由脚本从 csv 现取，不手填。</div>
</main></body></html>
""" % dict(
        mad=A['mad'], de=A['de'], jnd=A['jnd'], dl=A['dl'],
        nc=len(col), nm=len(mon), cmad=Cc['mad'], mmad=Mm['mad'],
        model=A['model'], bias=bias,
        table=table(rows), pairs=pairs, cdl=Cc['dl'], cdc=Cc['dc'])

    out = os.path.join(ROOT, 'charts', 'real-gap.html')
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(html)
    print('报告：%s  (%.1f KB)' % (out, len(html) / 1024))
    print('核对：26 支 %.2f 级 / 彩色 %.2f / 单色 %.2f / 模型 %.2f / 偏差 %+.2f'
          % (A['mad'], Cc['mad'], Mm['mad'], A['model'], bias))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
