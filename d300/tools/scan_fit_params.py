# -*- coding: utf-8 -*-
"""拟合参数扫描：证明 nb=44 / clamp=6 已经是这一族拟合的局部最优

背景：曲线拟合有两个手选参数 —— 分箱数 nb 与相对恒等的最大偏移 clamp。
本脚本在「留出半幅」口径下把它们扫一遍，回答「加大自由度还有没有收益」。

结论（30 支，留出半幅 = 拟合时没碰过的那一半）：

    nb=44  clamp=6    7.059      ← 现行设置
    nb=128 clamp=4    6.959      看似更好
    nb=128 clamp=6    6.968
    nb=200 clamp=4    7.013

前两行说明 CV 口径确实认为「更细的分箱 + 更紧的偏移」更好，但把它落到文件上、
用 audit_release.py 从文件本身反算整幅误差，结果是 **6.37 / 6.48，都比现行的 6.17 差**，
而且 nb=128 时还出现了 1 支变差。

原因：bin 变细后每档内的像素数变少，中位数噪声变大；clamp 收紧后落地重拟合被限制得太死。
所以这个「改善」只在 CV 口径里成立，是过拟合的另一副面孔。

用法：
    python scan_fit_params.py
"""
import numpy as np
import optimize_v2 as A

MONO, TONED = set(A.MONO), set(A.TONED)
ID = np.arange(256, dtype=float)


def run(nb, clamp):
    """按给定 nb/clamp 复算两阶段拟合的 CV 口径，返回 30 支的平均误差"""
    tot0 = tot1 = 0.0
    for slot in range(1, 31):
        O, R = A.load('d300ncp', slot), A.load('workshop', slot)
        h = O.shape[0] // 2
        Of, Rf, ev = O[:h], R[:h], slice(h, None)

        def score(f, s=1.0, deg=0.0, k=1.0):
            return float(np.abs(A.predict(O, f, s, deg, k)[ev] - R[ev]).mean())

        e0 = score(ID)
        if slot in MONO:
            f = A.fit_map(Of, Rf, False, clamp=clamp, nb=nb)
        else:
            f = A.fit_map(Of, Rf, True, clamp=(6.0 if clamp is None else clamp), nb=nb)

        cands = [score(f)]
        if slot in TONED:
            for kb in range(0x80, 0x8A):
                cands.append(score(f, 1.0, 0.0, (kb - 0x80) / 4.0))
        elif slot not in MONO:
            for n in range(-3, 4):
                for m in range(-3, 4):
                    cands.append(score(f, A.SAT_STEP ** n, A.HUE_STEP * m))

        b = min(cands)
        e1 = b if b < e0 - A.MIN_GAIN else e0
        tot0 += e0
        tot1 += e1
    return tot0 / 30, tot1 / 30


def main():
    print('%5s %6s %9s %9s %8s' % ('nb', 'clamp', 'CV 基准', 'CV 改后', '降幅'))
    best = None
    for nb in (44, 64, 128, 200):
        for clamp in (2.0, 3.0, 4.0, 6.0):
            a, b = run(nb, clamp)
            tag = ''
            if best is None or b < best[0]:
                best = (b, nb, clamp)
                tag = '  ←'
            print('%5d %6.1f %9.3f %9.3f %7.2f%%%s' % (nb, clamp, a, b, (1 - b / a) * 100, tag))
    print('\nCV 口径最佳 nb=%d clamp=%.1f（%.3f）' % (best[1], best[2], best[0]))
    print('但落地后整幅实测更差，见文件头说明 —— 现行 nb=44 / clamp=6 保留。')


if __name__ == '__main__':
    main()
