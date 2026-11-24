"""Loopback-only preview origin. Every response comes from the remote Sandbox.

The broker advertises host-local Docker ports. This bounded relay keeps platform
credentials on the server and app scripts on an origin distinct from PokeDev.
"""
from __future__ import annotations

import asyncio
import base64
import re
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from langflow.adlc.vai_services import PlatformClient


def valid_request(method, path, body):
    return (len(body) <= 4096 and (
        method == 'GET' and not body and (path == '/' or re.fullmatch(r'/api/tasks(?:\?status=(?:all|open|done))?', path))
        or method == 'POST' and path == '/api/tasks'
        or method == 'PATCH' and re.fullmatch(r'/api/tasks/[0-9]{1,12}', path)
        or method == 'DELETE' and not body and re.fullmatch(r'/api/tasks/[0-9]{1,12}', path)))


class PreviewRelays:
    def __init__(self):
        self.lock = threading.Lock()
        self.servers = {}

    def url(self, row):
        preview = row.get('preview', {})
        if row.get('state') != 'SUCCEEDED' or preview.get('state') != 'LIVE' or preview.get('access_mode') != 'POKEDEV_RELAY':
            return None
        try:
            expires = datetime.fromisoformat(preview['expires_at'].replace('Z', '+00:00'))
        except (KeyError, TypeError, ValueError):
            return None
        if expires <= datetime.now(timezone.utc):
            return None
        identity = row['run_id']
        with self.lock:
            if identity not in self.servers:
                self.servers[identity] = self.start(identity, preview['scope_id'], expires)
            return self.servers[identity][1]

    def start(self, identity, scope, expires):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def respond(self, status, body, content_type='text/plain; charset=utf-8'):
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Connection', 'close')
                self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'")
                self.end_headers()
                self.wfile.write(body)
                self.wfile.flush()

            def handle_app(self):
                # Reject DNS rebinding and cross-origin writes. No PokeDev cookies
                # or request headers are forwarded to the remote application.
                origin = 'http://localhost:' + str(self.server.server_port)
                if self.headers.get('Host') != origin.removeprefix('http://'):
                    return self.respond(403, b'PREVIEW_HOST_DENIED')
                if datetime.now(timezone.utc) >= expires:
                    return self.respond(410, b'PREVIEW_EXPIRED')
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                    self.connection.settimeout(5)
                    if size > 4096:
                        # Consume only a bounded amount before rejecting, so a
                        # small oversized POST still receives its HTTP response
                        # instead of a TCP reset on Windows.
                        self.rfile.read(min(size, 8192))
                        return self.respond(413, b'PREVIEW_BODY_TOO_LARGE')
                    if size < 0 or self.headers.get('Transfer-Encoding'):
                        return self.respond(413, b'PREVIEW_BODY_TOO_LARGE')
                    body = self.rfile.read(size)
                    if self.command != 'GET' and self.headers.get('Origin') != origin:
                        return self.respond(403, b'PREVIEW_ORIGIN_DENIED')
                    if not valid_request(self.command, self.path, body):
                        return self.respond(404, b'PREVIEW_PATH_DENIED')

                    async def request():
                        return await PlatformClient().request('POST', '/api/v1/pokedev-services/previews/' + identity + '/http',
                            {'scope_id': scope, 'method': self.command, 'path': self.path, 'body': body.decode('utf8')})

                    result = asyncio.run(request())
                    contents = base64.b64decode(result['body_base64'], validate=True)
                    if len(contents) > 131072 or result['content_type'] not in {'text/html; charset=utf-8', 'application/json; charset=utf-8'}:
                        raise ValueError('response')
                    return self.respond(result['status'], contents, result['content_type'])
                except Exception:
                    # Mutations are dispatched once; an ambiguous response never retries.
                    return self.respond(502, b'PREVIEW_RESPONSE_UNCONFIRMED')

            do_GET = do_POST = do_PATCH = do_DELETE = handle_app

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True, name='pokedev-preview-' + identity[:8]).start()
        def expire():
            server.shutdown()
            server.server_close()
        timer = threading.Timer(max(1, (expires - datetime.now(timezone.utc)).total_seconds()), expire)
        timer.daemon = True
        timer.start()
        return server, 'http://localhost:' + str(server.server_port) + '/'


preview_relays = PreviewRelays()
