# -*- coding: utf-8 -*-
"""建 GitHub 仓库 Pinksert/Nikon-Picture-Control-NCP-Analysis 并上传 NCP 分析与转换相关代码"""
import os, sys, json, base64, subprocess

sys.stdout.reconfigure(encoding='utf-8')

ROOT = r'C:\Users\admin\WorkBuddy\D300固件'
TMP = os.path.join(ROOT, '.workbuddy', 'tmp')
REPO_NAME = 'Nikon-Picture-Control-NCP-Analysis'
OWNER = 'Pinksert'
API = 'https://api.github.com'


def get_token():
    p = subprocess.run(['git', 'credential', 'fill'],
                       input='protocol=https\nhost=github.com\n\n',
                       capture_output=True, text=True)
    for line in p.stdout.splitlines():
        if line.startswith('password='):
            return line.split('=', 1)[1]
    raise SystemExit('no token')


TOKEN = get_token()
PROXY = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')


def curl(method, url, data=None, raw=None):
    cmd = ['curl', '-sS', '--max-time', '60', '--retry', '3', '--retry-delay', '1',
           '--retry-all-errors', '-X', method, url,
           '-H', 'Authorization: token ' + TOKEN,
           '-H', 'Accept: application/vnd.github+json',
           '-H', 'User-Agent: ncp-repo']
    inp = None
    if data is not None:
        # 走 stdin，避免 Windows 命令行长度限制（WinError 206）
        cmd += ['-H', 'Content-Type: application/json', '--data-binary', '@-']
        inp = json.dumps(data).encode()
    attempts = [['--noproxy', '*']]
    if PROXY:
        attempts.append(['-x', PROXY])
    for extra in attempts:
        p = subprocess.run(cmd + extra, capture_output=True, input=inp)
        if p.returncode == 0:
            return p.stdout.decode('utf-8', 'replace')
    raise SystemExit('curl failed: ' + url)


# ---------- 1. 建库 ----------
print('== 创建仓库 ==')
r = curl('POST', API + '/user/repos', {
    'name': REPO_NAME,
    'description': ('Nikon Picture Control (.NCP/.NP2/.NP3) file format analysis and '
                    'NP2/NP3 -> NCP downgrade tools, including user-defined curve (UDC) '
                    'reverse engineering'),
    'private': False, 'has_issues': True, 'has_wiki': False,
    'has_projects': False, 'auto_init': False,
})
info = json.loads(r)
if 'full_name' in info:
    print('  已创建:', info['full_name'])
else:
    print('  (可能已存在):', str(info)[:200])

# ---------- 2. 文件清单 ----------
FILES = [
    ('README.md',                     os.path.join(TMP, 'pc_repo_README.md')),
    ('np2ncp.py',                     os.path.join(ROOT, 'np2ncp.py')),
    ('np2ncp_curve.py',               os.path.join(ROOT, 'np2ncp_curve.py')),
    ('make_curve_batch.py',           os.path.join(ROOT, 'make_curve_batch.py')),
    ('verify_curve.py',               os.path.join(ROOT, 'verify_curve.py')),
    ('tools/np2ncp_verify.py',        os.path.join(TMP, 'np2ncp_verify.py')),
    ('tools/np2ncp_selftest.py',      os.path.join(TMP, 'np2ncp_selftest.py')),
    ('tools/np2ncp_full.py',          os.path.join(TMP, 'np2ncp_full.py')),
    ('tools/np2ncp_approx.py',        os.path.join(TMP, 'np2ncp_approx.py')),
    ('tools/curve_analyze.py',        os.path.join(TMP, 'curve_analyze.py')),
    ('tools/curve_spline.py',         os.path.join(TMP, 'curve_spline.py')),
    ('tools/curve_dense.py',          os.path.join(TMP, 'curve_dense.py')),
    ('data/pc2.txt',                  os.path.join(TMP, 'pc2.txt')),
    ('data/pc3.txt',                  os.path.join(TMP, 'pc3.txt')),
    ('data/portrait_lut.json',        os.path.join(ROOT, 'portrait_lut.json')),
    ('data/S_dump.txt',               os.path.join(ROOT, 'S_dump.txt')),
    ('data/M_dump.txt',               os.path.join(ROOT, 'M_dump.txt')),
    ('report/np2ncp_full_report.txt', os.path.join(TMP, 'np2ncp_full_report.txt')),
    ('report/ncp_approx_report.txt',  os.path.join(TMP, 'ncp_approx_report.txt')),
    ('output/PORTRAIT_curve.NCP',     os.path.join(ROOT, 'curve_out', 'PORTRAIT_curve.NCP')),
]
# 36 个近似版 NCP
approx = os.path.join(ROOT, 'ncp_approx')
if os.path.isdir(approx):
    for fn in sorted(os.listdir(approx)):
        if fn.upper().endswith('.NCP'):
            FILES.append(('output/ncp_approx/' + fn, os.path.join(approx, fn)))

print('\n== 上传 %d 个文件 ==' % len(FILES))
ok = fail = 0
for path, local in FILES:
    if not os.path.exists(local):
        print('  跳过（不存在）:', local)
        continue
    raw = open(local, 'rb').read()
    b64 = base64.b64encode(raw).decode()
    # 文件已存在时要带 sha 才能更新
    sha = None
    meta = curl('GET', '%s/repos/%s/%s/contents/%s' % (API, OWNER, REPO_NAME, path))
    try:
        mj = json.loads(meta)
        if isinstance(mj, dict) and 'sha' in mj:
            sha = mj['sha']
    except Exception:
        pass
    payload = {'message': ('Update ' if sha else 'Add ') + path,
               'content': b64, 'branch': 'main'}
    if sha:
        payload['sha'] = sha
    r = curl('PUT', '%s/repos/%s/%s/contents/%s' % (API, OWNER, REPO_NAME, path), payload)
    js = json.loads(r)
    if 'content' in js:
        ok += 1
        print('  OK   %-46s %7d B' % (path, len(raw)))
    else:
        fail += 1
        print('  FAIL %-46s %s' % (path, str(js)[:160]))

print('\n完成：成功 %d，失败 %d' % (ok, fail))
print('https://github.com/%s/%s' % (OWNER, REPO_NAME))
