# -*- coding: utf-8 -*-
"""上传 ncp_curve_all/ 的 30 个带曲线 NCP 到 output/curve_all/"""
import os, sys, json, base64, subprocess
sys.stdout.reconfigure(encoding='utf-8')
SRC = r'C:\Users\admin\WorkBuddy\D300固件\ncp_curve_all'
REPO = 'Pinksert/Nikon-Picture-Control-NCP-Analysis'
API = 'https://api.github.com'
p = subprocess.run(['git', 'credential', 'fill'],
                   input='protocol=https\nhost=github.com\n\n', capture_output=True, text=True)
TOKEN = [l.split('=', 1)[1] for l in p.stdout.splitlines() if l.startswith('password=')][0]


def curl(method, url, data=None):
    cmd = ['curl', '-sS', '--max-time', '60', '--retry', '3', '--retry-delay', '1',
           '--retry-all-errors', '-X', method, url,
           '-H', 'Authorization: token ' + TOKEN,
           '-H', 'Accept: application/vnd.github+json', '-H', 'User-Agent: ncp-repo']
    inp = None
    if data is not None:
        cmd += ['-H', 'Content-Type: application/json', '--data-binary', '@-']
        inp = json.dumps(data).encode()
    pp = subprocess.run(cmd + ['--noproxy', '*'], capture_output=True, input=inp)
    return pp.stdout.decode('utf-8', 'replace')


ok = fail = 0
for fn in sorted(os.listdir(SRC)):
    if not fn.endswith('.NCP'):
        continue
    path = 'output/curve_all/' + fn
    b64 = base64.b64encode(open(os.path.join(SRC, fn), 'rb').read()).decode()
    sha = None
    try:
        mj = json.loads(curl('GET', '%s/repos/%s/contents/%s' % (API, REPO, path)))
        if isinstance(mj, dict) and 'sha' in mj:
            sha = mj['sha']
    except Exception:
        pass
    payload = {'message': ('Update ' if sha else 'Add ') + path,
               'content': b64, 'branch': 'main'}
    if sha:
        payload['sha'] = sha
    r = json.loads(curl('PUT', '%s/repos/%s/contents/%s' % (API, REPO, path), payload))
    if 'content' in r:
        ok += 1
        print('  OK ', fn)
    else:
        fail += 1
        print('  FAIL', fn, str(r)[:120])
print('完成：成功 %d 失败 %d' % (ok, fail))
