"""Separate loopback origin for an artifact-bound project Sandbox."""
import asyncio
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
import re

from langflow.adlc.tnqd_relay import valid_path
from langflow.adlc.vai_services import PlatformClient


class LiveRelays:
    def __init__(self):
        self.lock, self.servers = threading.Lock(), {}

    def url(self, preview, scope):
        if preview.get("state") != "LIVE" or preview.get("expires_at", 0) <= time.time() or not preview.get("binding_verified"):
            return None
        key = (preview["job_id"], scope)
        with self.lock:
            if key not in self.servers:
                self.servers[key] = self.start(preview, scope)
            return self.servers[key][1]

    def start(self, preview, scope):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send_body(self, status, body, mime="text/plain"):
                self.send_response(status)
                for key, value in {"Content-Type": mime, "Content-Length": str(len(body)), "Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'"}.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def forward(self):
                origin = "http://localhost:" + str(self.server.server_port)
                if self.headers.get("Host") != "localhost:" + str(self.server.server_port):
                    return self.send_body(403, b"PREVIEW_HOST_DENIED")
                if time.time() >= preview["expires_at"]:
                    return self.send_body(410, b"PREVIEW_EXPIRED")
                if not valid_path(self.path):
                    return self.send_body(404, b"PREVIEW_PATH_DENIED")
                if self.command != "GET" and self.headers.get("Origin") != origin:
                    return self.send_body(403, b"PREVIEW_ORIGIN_DENIED")
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 <= length <= 1000000:
                        return self.send_body(413, b"PREVIEW_BODY_LIMIT")
                    body = self.rfile.read(length) if length else b""
                    async def fetch():
                        return await PlatformClient().request("POST", "/api/v1/pokedev-services/projects/jobs/" + preview["job_id"] + "/http", {"scope_id": scope, "method": self.command, "path": self.path, "body_base64": base64.b64encode(body).decode(), "content_type": self.headers.get("Content-Type", "application/json")})
                    result = asyncio.run(fetch())
                    content = base64.b64decode(result["body_base64"], validate=True)
                    if len(content) > 16000000:
                        raise ValueError("body")
                    if not isinstance(result["status"], int) or not 200 <= result["status"] <= 599 or not re.fullmatch(r"[A-Za-z0-9!#$&^_.+/-]+(?:;[A-Za-z0-9 =_.-]+)*", result["content_type"]):
                        raise ValueError("response")
                    self.send_body(result["status"], content, result["content_type"])
                except Exception:
                    self.send_body(502, b"PREVIEW_UNAVAILABLE")

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = forward

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True, name="live-preview-" + preview["job_id"][:8]).start()
        def expire():
            server.shutdown(); server.server_close()
        timer = threading.Timer(max(1, preview["expires_at"] - time.time()), expire)
        timer.daemon = True; timer.start()
        return server, "http://localhost:" + str(server.server_port) + "/"


live_relays = LiveRelays()
