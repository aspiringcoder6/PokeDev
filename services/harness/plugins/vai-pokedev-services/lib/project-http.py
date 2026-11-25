"""Constant Sandbox preview transport. Request data is read from a private temporary file."""
import base64
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request

path = Path(sys.argv[1])
try:
    command = json.loads(path.read_text())
finally:
    path.unlink(missing_ok=True)
request = urllib.request.Request(
    "http://127.0.0.1:8088" + command["path"],
    data=base64.b64decode(command["body"], validate=True) if command["method"] != "GET" else None,
    method=command["method"], headers={"Content-Type": command["content_type"]},
)
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        return None

opener = urllib.request.build_opener(NoRedirect())
try:
    response = opener.open(request, timeout=20)
except urllib.error.HTTPError as error:
    response = error
content = response.read(16000001)
if len(content) > 16000000:
    raise ValueError("PROJECT_PREVIEW_BODY_LIMIT")
print("POKEDEV_PROJECT_HTTP:" + json.dumps({"status": response.status, "content_type": response.headers.get("Content-Type", "application/octet-stream"), "body_base64": base64.b64encode(content).decode()}))
