# -*- coding: utf-8 -*-
"""更新仓库里的 README.md 并新增 README_EN.md（带 sha 覆盖）"""
import os, sys, json, base64, subprocess

sys.stdout.reconfigure(encoding='utf-8')
TMP = os.path.dirname(os.path.abspath(__file__))
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


FILES = [
    ('README.md', os.path.join(TMP, 'pc_repo_README.md')),
    ('README_EN.md', os.path.join(TMP, 'pc_repo_README_EN.md')),
]
for path, local in FILES:
    b64 = base64.b64encode(open(local, 'rb').read()).decode()
    sha = None
    meta = curl('GET', '%s/repos/%s/contents/%s' % (API, REPO, path))
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
    r = json.loads(curl('PUT', '%s/repos/%s/contents/%s' % (API, REPO, path), payload))
    print('%s -> %s' % (path, 'OK' if 'content' in r else str(r)[:200]))
