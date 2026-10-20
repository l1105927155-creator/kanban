# -*- coding: utf-8 -*-
"""Isolated LAN access controls and remote proxy checks; no live data."""
import json, os, pathlib, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error
root = pathlib.Path(__file__).resolve().parent.parent
with tempfile.TemporaryDirectory() as temp:
    def port():
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            return s.getsockname()[1]
    backend_port = port()
    env = dict(os.environ, TASK_BOARD_DATA_DIR=temp, TASK_BOARD_HOST='127.0.0.1', TASK_BOARD_PORT=str(backend_port), TASK_BOARD_ALLOWED_CLIENTS='127.0.0.1/32')
    process = subprocess.Popen([sys.executable, str(root/'server.py')], env=env, stdout=subprocess.DEVNULL)
    base = 'http://127.0.0.1:%d' % backend_port
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base+'/api/health', timeout=.2).close()
                break
            except OSError:
                time.sleep(.05)
        def request(path, method='GET', payload=None, headers=None, expected=200):
            body = json.dumps(payload).encode() if payload is not None else None
            req=urllib.request.Request(base+path, data=body, method=method, headers=headers or {})
            try:
                response=urllib.request.urlopen(req)
            except urllib.error.HTTPError as exc:
                response=exc
            with response:
                assert response.status==expected, (response.status, expected)
                return response.read()
        request('/')
        request('/api/state', headers={'Host':'evil.example'}, expected=403)
        request('/api/tasks', 'POST', {'title':'blocked'}, expected=403)
        request('/api/tasks', 'POST', {'title':'blocked'}, {'X-Board-Request':'1','Origin':'http://evil.example'}, 403)
        with socket.socket() as s:
            s.bind(('127.0.0.2',0))
            s.connect(('127.0.0.1',backend_port))
            s.sendall(b'GET /api/state HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n')
            assert b'403' in s.recv(4096)
        body=request('/api/tasks','POST',{'title':'LAN test'},{'X-Board-Request':'1','Origin':base})
        task=json.loads(body)['task']
        request('/api/tasks/'+task['id'],'PATCH',{'note':'persisted'},{'X-Board-Request':'1'})
        assert json.loads((pathlib.Path(temp)/'data.json').read_text())['tasks'][0]['note']=='persisted'
        print('PASS: page, Host, Origin, mutation header, client whitelist, create/update persistence')
    finally:
        process.terminate()
        process.wait(timeout=5)
