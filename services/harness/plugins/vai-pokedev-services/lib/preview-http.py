"""A fixed, bounded HTTP relay to this sandbox's Taskboard; no arbitrary URL/headers."""
import base64
import json
import re
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

command = json.loads(base64.b64decode(sys.argv[1], validate=True))
method, path, body = command['method'], command['path'], command['body']
allowed = (method == 'GET' and (path == '/' or re.fullmatch(r'/api/tasks(?:\?status=(?:all|open|done))?', path))
           or method == 'POST' and path == '/api/tasks'
           or method in {'PATCH', 'DELETE'} and re.fullmatch(r'/api/tasks/[0-9]{1,12}', path))
if not allowed or len(body.encode()) > 4096 or method in {'GET', 'DELETE'} and body:
    raise ValueError('PREVIEW_HTTP_INVALID')
request = Request('http://127.0.0.1:8088' + path, method=method,
                  data=body.encode() if body else None, headers={'Content-Type': 'application/json'})
try:
    response = urlopen(request, timeout=10)
except HTTPError as error:
    response = error
with response:
    contents = response.read(131073)
    if len(contents) > 131072:
        raise ValueError('PREVIEW_HTTP_TOO_LARGE')
    print('POKEDEV_PREVIEW_HTTP:' + json.dumps({'status': response.status,
          'content_type': response.headers.get('Content-Type', ''),
          'body_base64': base64.b64encode(contents).decode()}))
