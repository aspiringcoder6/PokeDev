"""Separate loopback origin for the hash-bound TNQD Sandbox preview."""
import asyncio
import base64
from datetime import datetime,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import re
import threading
from urllib.parse import unquote,urlsplit
from langflow.adlc.vai_services import PlatformClient

MIME={"text/html; charset=utf-8","text/plain","application/javascript","text/css","application/json","application/json; charset=utf-8","image/svg+xml","image/png","image/jpeg","image/webp","image/x-icon","font/woff","font/woff2","font/ttf","application/octet-stream"}

def valid_path(path):
    decoded=unquote(path)
    return len(path)<1800 and decoded.startswith("/") and not decoded.startswith("//") and ".." not in decoded and "\\" not in decoded and not any(ord(c)<32 for c in decoded)

class TnqdRelays:
    def __init__(self):self.lock=threading.Lock();self.servers={}
    def url(self,preview,scope):
        if preview.get("state")!="LIVE" or preview.get("access_mode")!="POKEDEV_TNQD_RELAY" or not preview.get("binding_verified"):return None
        try:expires=datetime.fromisoformat(preview["expires_at"].replace("Z","+00:00"))
        except (KeyError,ValueError,TypeError):return None
        if expires<=datetime.now(timezone.utc):return None
        key=(preview["preview_id"],scope)
        with self.lock:
            if key not in self.servers:self.servers[key]=self.start(preview["preview_id"],scope,expires)
            return self.servers[key][1]
    def start(self,identity,scope,expires):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def send_body(self,status,body,mime="text/plain"):
                self.send_response(status);self.send_header("Content-Type",mime);self.send_header("Content-Length",str(len(body)))
                self.send_header("Cache-Control","no-store");self.send_header("Referrer-Policy","no-referrer");self.send_header("X-Content-Type-Options","nosniff")
                self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'none'")
                self.end_headers();self.wfile.write(body)
            def do_GET(self):
                if self.headers.get("Host")!="localhost:"+str(self.server.server_port):return self.send_body(403,b"PREVIEW_HOST_DENIED")
                if datetime.now(timezone.utc)>=expires:return self.send_body(410,b"PREVIEW_EXPIRED")
                if not valid_path(self.path):return self.send_body(404,b"PREVIEW_PATH_DENIED")
                try:
                    async def fetch():
                        return await PlatformClient().request("POST","/api/v1/pokedev-services/tnqd/previews/"+identity+"/http",{"scope_id":scope,"path":self.path})
                    response=asyncio.run(fetch())
                    body=base64.b64decode(response["body_base64"],validate=True)
                    if len(body)>16000000 or response["content_type"] not in MIME:raise ValueError("response")
                    self.send_body(response["status"],body,response["content_type"])
                except Exception:self.send_body(502,b"TNQD_PREVIEW_UNCONFIRMED")
            def do_POST(self):self.send_body(405,b"READ_ONLY_DEMO")
            do_PATCH=do_DELETE=do_PUT=do_POST
        server=ThreadingHTTPServer(("127.0.0.1",0),Handler);server.daemon_threads=True
        threading.Thread(target=server.serve_forever,daemon=True,name="tnqd-preview-"+identity[:8]).start()
        def expire():server.shutdown();server.server_close()
        timer=threading.Timer(max(1,(expires-datetime.now(timezone.utc)).total_seconds()),expire);timer.daemon=True;timer.start()
        return server,"http://localhost:"+str(server.server_port)+"/"

tnqd_relays=TnqdRelays()
