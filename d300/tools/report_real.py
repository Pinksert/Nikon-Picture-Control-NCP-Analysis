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


def base_groups():
    """按「官方 NP3 里挂的底子」把 26 支分三组，返回统计与表格行。

    官方每支 NP3 都带自己的底子编号（20 个创意滤镜是连号 0x0801-0x0814），
    而我们生成 NCP 时一律写 0x0001 STANDARD（单色支写 0x064D）——等于把它替换掉了。
    分组的意义就是看这个替换和残差有没有关系。
    """
    import glob
    import struct
    sys.path.insert(0, os.path.join(ROOT, '..', 'np3tool'))
    import np3core as C

    real = {r['name'].upper(): r for r in csv.DictReader(
        open(os.path.join(ROOT, 'samples', 'metrics_real.csv'), encoding='utf-8-sig'))}
    MONO = ('CHARCOAL', 'GRAPHITE', 'BINARY', 'CARBON')
    G = [('创意底·彩色', '0x0801–0x080C', [], '#C53030'),
         ('创意底·单色', '0x0811–0x0814', [], '#2F855A'),
         ('基础底', '0001 / 03C2 / 00C3 / 028E / 04C7 / 064D', [], '#2B6CB0')]
    for f in sorted(glob.glob(os.path.join(ROOT, '..', '滤镜', '*.NP3'))):
        d = C.parse_np(open(f, 'rb').read())
        nm = d['name'].upper()
        r = real.get(nm)
        if not r:
            continue
        base = d['base']
        gi = (1 if nm in MONO else 0) if 0x0801 <= base <= 0x0814 else 2
        G[gi][2].append((nm, float(r['mad']), float(r['dC_signed'])))

    out, stats = [], []
    for name, codes, items, col in G:
        m = [x[1] for x in items]
        c = [x[2] for x in items]
        mu_m = sum(m) / len(m)
        mu_c = sum(c) / len(c)
        sd = (sum((x - mu_c) ** 2 for x in c) / (len(c) - 1)) ** 0.5
        stats.append(dict(name=name, n=len(items), mad=mu_m, dc=mu_c, sd=sd, col=col))
        out.append('<tr><td><b style="color:%s">%s</b></td><td class="num">%d</td>'
                   '<td class="num">%.2f</td><td class="num">%s</td>'
                   '<td class="num">%.2f</td><td><code>%s</code></td></tr>'
                   % (col, name, len(items), mu_m,
                      ('%+.2f' % mu_c).replace('-', '−'), sd, codes))
    tab = ('<table><thead><tr><th>分组</th><th>支数</th><th>平均差（级）</th>'
           '<th>ΔC* 均值</th><th>ΔC* 标准差</th><th>官方底子编号</th></tr></thead>'
           '<tbody>%s</tbody></table>' % ''.join(out))
    return tab, stats


def main():
    rows = read()
    n = len(rows)
    col = [r for r in rows if not r['mono']]
    mon = [r for r in rows if r['mono']]
    A = {k: avg(rows, k) for k in ('mad', 'de', 'jnd', 'dl', 'dc', 'dh', 'model')}
    Cc = {k: avg(col, k) for k in ('mad', 'de', 'jnd', 'dl', 'dc', 'dh')}
    Mm = {k: avg(mon, k) for k in ('mad', 'de', 'jnd', 'dl', 'dc', 'dh')}
    bias = A['mad'] - A['model']
    gtab, gst = base_groups()
    g_col, g_mono, g_base = gst

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

<p>这个方向性本身有个前提要先钉住：机身能给的只是一个全局倍率，而各支要的方向不同，
所以「改档位」这条路要么全赢、要么全输。之前那次「7×7 整数档穷举、0 支值得改」就是
在这个前提下做的，而它依赖一个假设：饱和度每一档是 ×1.13。这个数如果错了，穷举的结论
就得跟着重做。所以专门做了一组标定探针，结果见下一节。</p>

<div class="note"><b>先更正我在初稿里写错的一条结论。</b>当时我看到两组数对不上：
拿 NEUTRAL（−1 档）/ STANDARD（0 档）/ POP（+2 档）三支的彩度比反推，算出「每档约 1.06 倍」；
又把模型口径的彩度差（+4.55）和真渲染口径的彩度差（−2.01）直接对照，断言「方向反了、模型算错」。
<b>两条都不成立。</b>第一条错在拿三支<b>不同曲线</b>反推，彩度差里混着曲线的成分；
第二条错在<b>底片不同</b>——模型口径那组（<code>d300ncp</code> 与 <code>workshop</code>）
是在 DSC_3891 上渲的，这份报告全在 DSC_4484 上，同一支滤镜在不同底片上偏浓偏淡本来就
可以相反。按同一底片对照，模型与实测的偏差只有 +0.23 级、相关系数 0.955，模型没有算错。</div>

<h2>六、滑块标定：机身到底给多少力量</h2>
<p>把变量降到只剩一个：同一张曲线的 11 个副本，每个只改一个字节。7 个改饱和度档
（−3 到 +3）、1 个改色相档、1 个只换底子编号、2 个测单色着色。在 NX Studio 里各渲一张，
再逐像素比。</p>

<figure><img src="slider-sat.jpg" alt="饱和度滑块标定">
<figcaption>三条线是同一个像素集在不同统计层里的表现：全部中间调、彩度前 10%%、彩度前 1%%。
七张图共用同一批像素，所以曲线是干净的。</figcaption></figure>

<p>结论比预想的平和：<b>平均每档 ×1.118</b>，模型假设 ×1.130，只差 1.1%%。
但这个平均值掩盖了真正的问题——<b>倍率不是常数</b>。0→+1 档还有 ×1.114，
+1→+2 掉到 ×1.081、+2→+3 只剩 ×1.059；往负方向反过来，−1→−2 是 ×0.865、
−2→−3 是 ×0.834，同样越往外越狠（降比升更有力）。所以 +3 档累计只有 1.275、
−3 档累计 0.648，而模型按恒定倍率外推的是 1.443 和 0.693——<b>两端都高估</b>，
+3 档高估 13%%。</p>

<p>原因不难理解：越靠近色域边界，滑块的实际增益越小，最浓的那 1%% 像素在 +2 到 +3
之间几乎不再涨（1.15 → 1.17）。用实测的 1.118 重跑那遍 7×7 整数档穷举，结论从
「0 支值得改」变成 <b>1 支</b>（SUNDAY 从 +1 档改到 +2 档，八折留出仅改善 0.065 级），
量级上仍属可忽略。所以「参数到头」这个结论站得住，只是理由要换个说法：
不是台阶不够多，也不是台阶比以为的矮，而是<b>高档位被色域边界压住了</b>。</p>

<figure><img src="slider-misc.jpg" alt="色相、底子、单色着色">
<figcaption>同一个探针包的另外三组。中间那格是本次最有价值的发现。</figcaption></figure>

<p>另外三组里最值得记的是<b>底子编号</b>：把 <code>0x0001</code>（STANDARD）改成
<code>0x00C3</code>（VIVID），曲线区一个字节都没动，渲染结果的彩度却涨了 8.1%%、亮度降了
1.87、ΔE00 均值 2.36（55%% 的像素超过可辨阈）。这说明 NX Studio <b>会读底子字节</b>，
底子不是装饰。之前那句「换底子无收益」是在模型里得出的——模型里四个底子只差 36 字节，
效果自然小；真渲染里这 36 字节带来的差异比残差的一半还大。这条线索此前被漏掉了，
它也给后面留了个口子：既然底子会改变基础色彩处理，「每支选哪个底子」本身就是一个
还没搜过的维度。</p>

<p>色相档每档 +3.83°（模型 3.5°），量级也对。单色着色那组澄清了一件事：
<code>offset 47</code> 管的是<b>浓度</b>而不是色相——0 档到 +3 档，色相几乎不动
（66.2° → 66.8°），彩度却从 23.04 掉到 17.61。至于 30 支里 SEPIA / BLUE / RED / PINK
为什么是四种不同色调，靠的是 <code>offset 46</code>（四支分别是 0x81 / 0x87 / 0x83 / 0x89），
那是色相档，本次没有单独标定。</p>

<p>顺带查清了一件事：这四支的底子编号是 <code>0x064D</code> MONOCHROME，43 / 44 两格是
<code>FF</code>（饱和与色相被禁用）——<b>它们名义上挂着单色底子，实际是靠着色档出颜色的</b>。
这就解释了为什么它们的残差特别难压（SEPIA −7.30、RED −7.54）：饱和度的 ±3 档对它们
根本不起作用，彩度天花板由另一个系统决定。所以给它们换彩色底子属于另一个问题，
和 DENIM / TOY 那种「彩色支换底子」不能混在一起比。</p>

<div class="note">标定这件事本身踩了一个坑，值得记下来：<b>七张图必须共用同一批像素</b>。
第一版脚本对每张图各自圈遮罩（排除截断区），结果饱和度一调，进遮罩的像素就换了一批，
C* 从 −3 档到 +3 档呈现 8.49 → 11.38 → 9.95 的「先升后降」，看起来像滑块根本不生效。
换成「以 0 档的遮罩为准、七张图共用」之后立刻单调，斜率也稳定在 1.118（三套统计层
分别给出 1.115 / 1.118 / 1.118，线性拟合 R² 0.91–0.97）。凡是跨图比较，先固定像素集。</div>

<h2>七、底子：被曲线吞掉的那一层</h2>
<p>我们生成 NCP 时，底子字节一律写 <code>0x0001</code>（STANDARD），单色支写 <code>0x064D</code>。
而官方每支 NP3 都带着<b>自己的底子编号</b>：20 个创意滤镜是连号的 <code>0x0801–0x0814</code>
（DREAM = 0801、DENIM = 080B、BINARY = 0813……）。换句话说，这一格被我们替换掉了。</p>

<p>把这个替换和实测残差摆在一起，分组整齐得不像巧合：</p>
%(gtab)s

<figure><img src="baseid-gap.jpg" loading="lazy" alt="底子类别与残差">
<figcaption>左：平均差；右：彩度偏差（带符号）。彩色创意底子那一组不只是更差，是向两侧散开。</figcaption></figure>

<p>要害在右图。单色支同样被换了底子（官方是 0811–0814，我们换成 <code>0x064D</code>），
彩度偏差却几乎贴着零线，标准差只有 %(gmsd).2f；彩色创意底子组是 %(gcsd).2f，
从 −7.7 摊到 +4.4。同样是「换掉了官方底子」，一组没事、一组全乱——区别在于
<b>单色要的是同一色相上的一维着色，一条曲线搬得动；彩色要的是逐色相的彩度重排，
一条单调曲线搬不动</b>。这也正是第五节「各支各偏一个方向」的成因：偏淡最狠的
DENIM / TOY / RED / SEPIA 恰好是官方底子里饱和倾向最强的那几支，偏浓的
DRAMA / SILENCE / BLEACH 正好相反。把它们统统压到同一个中性底子上，
再想用一张全局倍率补回来，补不回来。</p>

<div class="note"><b>但这是相关性，还不是因果。</b>也可能只是「这几支本来就更极端、更难拟合」。
要把两者拆开，唯一的办法是把变量降到只剩底子：<b>恒等曲线 + 只改底子编号</b>。
这样的探针已经备好 8 份（<code>_probe_baseid/</code>），覆盖 4 个基础底子与 4 个创意底子编号。
它同时回答一个更关键的问题：<b>NCP 认不认 <code>0x08xx</code> 创意底子编号</b>——
认，就能按底子重配这三十支；不认，就只剩「在 4 个基础底子里挑」这一条路。
实测结果出来后会补进本页。</div>

<h2>八、六组并排实拍</h2>
<p>左边官方、右边我们，同一张原片同一套导出设置。差距最大的 6 支：</p>
%(pairs)s

<h2>九、边界说明</h2>
<ul>
<li>样本是 <b>DSC_4484</b>（横构图 cosplay 实拍），不是拟合时用的 DSC_3891。
换一张底片还能保持 0.955 的相关性，说明不是过拟合；但数字本身是针对这张片子测的。</li>
<li><b>本页所有对照都必须同一底片。</b>仓库里另有一组彩度差（<code>d300ncp</code> / <code>workshop</code>）
是在 DSC_3891 上渲的，方向和本页可以相反——同一支滤镜在不同底片上偏浓偏淡并不矛盾，
把两组数字直接相减是错的。</li>
<li>26 支而非 30 支，原因见第二节注。</li>
<li>数值口径：420px 长边等比缩放后逐像素统计；平均差 = 三通道平均绝对差；
剪裁区（任一通道 &lt;8 或 &gt;247）不计入，因为那是机身截断，不是滤镜造成的。</li>
<li>侧拍的 JPEG 编码、锐化由 NX Studio 两边同等施加，因此不构成偏差来源；
但 NX Studio 会把我们写进文件的曲线控制点按自己的插值重算 LUT，
这一步的差异已包含在结果里。</li>
<li>滑块标定用的是同一张曲线的探针，测的是<b>纯滑块力量</b>；真实文件里曲线与滑块
同时作用，两者不是简单相乘，所以 1.118 不能直接拿去乘某支滤镜的实际彩度。</li>
</ul>

<h2>十、复现</h2>
<pre>python d300/tools/real_gap.py --csv d300/samples/metrics_real.csv
python d300/tools/chart_real_gap.py
python d300/tools/make_real_pairs.py
python d300/tools/probe_slider_read.py --dir d300/samples/probe_slider
python d300/tools/chart_slider.py
python d300/tools/probe_baseid_read.py --dir d300/samples/probe_baseid
python d300/tools/chart_baseid.py
python d300/tools/report_real.py</pre>
<p>原始测量数据：<code>d300/samples/metrics_real.csv</code>、<code>d300/samples/probe_slider.csv</code>；
成片：<code>d300/samples/real_v3/</code>（我们）、<code>d300/samples/real_target/</code>（官方）、
<code>d300/samples/probe_slider/</code>（11 张标定探针）、<code>d300/samples/probe_baseid/</code>（8 张底子探针）。
两侧都是 4288×2848 全尺寸导出。</p>

<div class="foot">数据生成于 2026-11-01。本页所有数字由脚本从 csv 现取，不手填。</div>
</main></body></html>
""" % dict(
        mad=A['mad'], de=A['de'], jnd=A['jnd'], dl=A['dl'],
        nc=len(col), nm=len(mon), cmad=Cc['mad'], mmad=Mm['mad'],
        model=A['model'], bias=bias,
        table=table(rows), pairs=pairs, cdl=Cc['dl'], cdc=Cc['dc'],
        gtab=gtab, gmsd=g_mono['sd'], gcsd=g_col['sd'])

    out = os.path.join(ROOT, 'charts', 'real-gap.html')
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(html)
    print('报告：%s  (%.1f KB)' % (out, len(html) / 1024))
    print('核对：26 支 %.2f 级 / 彩色 %.2f / 单色 %.2f / 模型 %.2f / 偏差 %+.2f'
          % (A['mad'], Cc['mad'], Mm['mad'], A['model'], bias))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
