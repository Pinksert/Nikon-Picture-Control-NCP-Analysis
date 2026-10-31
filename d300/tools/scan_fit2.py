import numpy as np, itertools, sys
import optimize_v2 as A

MONO = set(A.MONO); TONED = set(A.TONED)
ID = np.arange(256, dtype=float)

def run(nb, clamp):
    """用给定 nb/clamp 复算 explore 的 CV 口径，统计 30 支"""
    tot0 = tot1 = 0.0
    rows = []
    for slot in range(1, 31):
        O, R = A.load('d300ncp', slot), A.load('workshop', slot)
        h = O.shape[0] // 2
        Of, Rf, ev = O[:h], R[:h], slice(h, None)
        def score(f, s=1.0, deg=0.0):
            return float(np.abs(A.predict(O, f, s, deg)[ev] - R[ev]).mean())
        e0 = score(ID)
        if slot in MONO:
            f = A.fit_map(Of, Rf, False, clamp=clamp, nb=nb)
        else:
            f = A.fit_map(Of, Rf, True, clamp=(6.0 if clamp is None else clamp), nb=nb)
        cands = [(score(f), 'tone')]
        if slot in TONED:
            for kb in range(0x80, 0x8A):
                k = (kb - 0x80) / 4.0
                cands.append((float(np.abs(A.predict(O, f, 1.0, 0.0, k)[ev] - R[ev]).mean()), 'k'))
        elif slot not in MONO:
            for n in range(-3, 4):
                for m in range(-3, 4):
                    cands.append((score(f, A.SAT_STEP**n, A.HUE_STEP*m), 'tone'))
        b = min(cands)
        e1 = b[0] if b[0] < e0 - A.MIN_GAIN else e0
        tot0 += e0; tot1 += e1
        rows.append((slot, e0, e1))
    return tot0/30, tot1/30, rows

print('%5s %6s %8s %8s %8s' % ('nb', 'clamp', 'CV基准', 'CV改后', '降幅%'))
best = None
for nb in (44, 64, 128, 200):
    for clamp in (2.0, 3.0, 4.0, 6.0):
        a, b, _ = run(nb, clamp)
        d = (1-b/a)*100
        tag = ''
        if best is None or b < best[0]:
            best = (b, nb, clamp); tag = '  ←'
        print('%5d %6s %8.3f %8.3f %7.2f%%%s' % (nb, clamp, a, b, d, tag))
print('\n最佳:', best)
