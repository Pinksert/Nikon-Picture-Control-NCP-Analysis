# -*- coding: utf-8 -*-
"""上传「滤镜」目录里全部预设文件到仓库 presets/"""
import os, sys, json, base64, subprocess

sys.stdout.reconfigure(encoding='utf-8')
SRC = r'C:\Users\admin\WorkBuddy\D300固件\滤镜'
REPO = 'Pinksert/Nikon-Picture-Control-NCP-Analysis'
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


def curl(method, url, data=None):
    cmd = ['curl', '-sS', '--max-time', '60', '--retry', '3', '--retry-delay', '1',
           '--retry-all-errors', '-X', method, url,
           '-H', 'Authorization: token ' + TOKEN,
           '-H', 'Accept: application/vnd.github+json',
           '-H', 'User-Agent: ncp-repo']
    inp = None
    if data is not None:
        cmd += ['-H', 'Content-Type: application/json', '--data-binary', '@-']
        inp = json.dumps(data).encode()
    p = subprocess.run(cmd + ['--noproxy', '*'], capture_output=True, input=inp)
    return p.stdout.decode('utf-8', 'replace')


files = sorted(os.listdir(SRC))
print('待上传 %d 个' % len(files))
ok = fail = 0
for fn in files:
    local = os.path.join(SRC, fn)
    if not os.path.isfile(local):
        continue
    path = 'presets/' + fn
    b64 = base64.b64encode(open(local, 'rb').read()).decode()
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
        print('  OK  %s' % fn)
    else:
        fail += 1
        print('  FAIL %s -> %s' % (fn, str(r)[:150]))

print('\n完成：成功 %d，失败 %d' % (ok, fail))
