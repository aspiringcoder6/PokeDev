"""Start only the pinned taskboard candidate, then probe its actual HTTP API."""
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

binding = json.loads(Path('pokedev-preview-binding.json').read_text(encoding='utf8'))
source_hash = hashlib.sha256(Path('app.py').read_bytes()).hexdigest()
if source_hash != binding['source_sha256']:
    raise RuntimeError('PREVIEW_SOURCE_CHANGED')

receipt_path = Path('pokedev-preview-start.json')
if receipt_path.is_file():
    old = json.loads(receipt_path.read_text(encoding='utf8'))
    if old['preview_id'] != binding['preview_id'] or old['source_sha256'] != source_hash:
        raise RuntimeError('PREVIEW_BINDING_CHANGED')
    print('POKEDEV_PREVIEW_START:' + json.dumps(old, ensure_ascii=False))
    raise SystemExit(0)

launcher = "from app import TaskStore, create_server\ncreate_server(TaskStore(), host='0.0.0.0', port=8088).serve_forever()\n"
Path('pokedev-preview-app.py').write_text(launcher, encoding='utf8')
with Path('pokedev-preview-app.log').open('ab') as log:
    proc = subprocess.Popen([sys.executable, 'pokedev-preview-app.py'], stdin=subprocess.DEVNULL,
                            stdout=log, stderr=log, start_new_session=True)

def call(path, method='GET', data=None):
    request = Request('http://127.0.0.1:8088' + path, method=method,
                      data=None if data is None else json.dumps(data).encode(),
                      headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=5) as response:
        raw = response.read(300000)
        return response.status, raw

for attempt in range(30):
    try:
        status, html = call('/')
        if status == 200 and b'<html' in html.lower():
            break
    except Exception:
        pass
    if proc.poll() is not None:
        raise RuntimeError('PREVIEW_SERVER_EXITED')
    time.sleep(0.3)
else:
    raise RuntimeError('PREVIEW_HTTP_UNAVAILABLE')

checks = [{'id': 'page', 'label': 'Trang ứng dụng trả HTTP 200', 'passed': status == 200}]
task_id = None
try:
    status, raw = call('/api/tasks', 'POST', {'title': 'PokeDev kiểm tra bản triển khai'})
    task = json.loads(raw)['task']
    task_id = task['id']
    checks.append({'id': 'create', 'label': 'Thêm công việc qua HTTP', 'passed': status == 201 and task['done'] is False})
    status, raw = call('/api/tasks/' + str(task_id), 'PATCH', {'done': True})
    checks.append({'id': 'toggle', 'label': 'Đánh dấu hoàn tất', 'passed': status == 200 and json.loads(raw)['task']['done'] is True})
    status, raw = call('/api/tasks?status=done')
    checks.append({'id': 'filter', 'label': 'Lọc công việc hoàn thành', 'passed': status == 200 and any(t['id'] == task_id for t in json.loads(raw)['tasks'])})
finally:
    if task_id is not None:
        status, raw = call('/api/tasks/' + str(task_id), 'DELETE')
        checks.append({'id': 'delete', 'label': 'Xóa dữ liệu kiểm tra', 'passed': status == 200 and json.loads(raw)['deleted'] is True})

report = {'preview_id': binding['preview_id'], 'source_sha256': source_hash,
          'pid': proc.pid, 'port': 8088, 'checks': checks,
          'passed': len(checks) == 5 and all(row['passed'] for row in checks),
          'verification_kind': 'LIVE_HTTP_SMOKE', 'attested': False}
receipt_path.write_text(json.dumps(report, ensure_ascii=False), encoding='utf8')
print('POKEDEV_PREVIEW_START:' + json.dumps(report, ensure_ascii=False))
