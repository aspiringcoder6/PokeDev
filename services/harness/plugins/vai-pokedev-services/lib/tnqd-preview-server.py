"""Fixed TNQD Sandbox profile. Static Angular artifact + explicitly synthetic read API."""
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import mimetypes
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit, parse_qs
import zipfile

ROOT = Path("tnqd-site").resolve()

def prepare():
    chunks=sorted(Path(".").glob("tnqd-upload-*.txt"))
    encoded="".join(p.read_text() for p in chunks)
    archive=base64.b64decode(encoded,validate=True)
    binding=json.loads(Path("tnqd-binding.json").read_text())
    if hashlib.sha256(archive).hexdigest()!=binding["artifact_sha256"]: raise ValueError("artifact hash mismatch")
    Path("tnqd-artifact.zip").write_bytes(archive)
    ROOT.mkdir(exist_ok=True)
    with zipfile.ZipFile("tnqd-artifact.zip") as z:
        infos=z.infolist()
        if len(infos)>12000 or sum(i.file_size for i in infos)>120000000: raise ValueError("archive limit")
        for i in infos:
            target=(ROOT/i.filename).resolve()
            if not target.is_relative_to(ROOT) or i.file_size>16000000 or i.filename.startswith("/") or "\\" in i.filename: raise ValueError("archive path")
        z.extractall(ROOT)
    print("TNQD_PREPARED:"+json.dumps(binding),flush=True)

ROWS=[{"id":index+1,"name":("DEMO-AN "+str(index+1) if index<3 else "DEMO-BINH "+str(index-2) if index<7 else "Nhân sự mẫu "+str(index+1)),"idNumber":"DEMO-"+str(10000+index),"memberType":"UNION_MEMBER","memberTypeDisplay":"Đoàn viên","status":"ACTIVE","youthUnionName":"Chi đoàn Demo","unitName":"Đơn vị Demo","gender":"MALE","dateOfBirth":"2000-01-01","joinDate":"2020-03-26","positions":[],"governmentPositions":[]} for index in range(45)]

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def send(self,status,data,content_type="application/json; charset=utf-8"):
        body=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status);self.send_header("Content-Type",content_type);self.send_header("Content-Length",str(len(body)));self.send_header("Cache-Control","no-store");self.end_headers();self.wfile.write(body)
    def do_GET(self):
        u=urlsplit(self.path);q=parse_qs(u.query)
        if u.path=="/__pokedev/binding": return self.send(200,json.loads(Path("tnqd-binding.json").read_text()))
        if u.path.startswith("/api/"):
            if u.path.endswith("/youths/filter"):
                keyword=(q.get("keyword",q.get("name",[""]))[0] or "").strip().upper()
                if keyword=="DEMO-ERROR": return self.send(503,{"detail":{"name":"Lỗi đọc dữ liệu demo. Vui lòng thử lại."}})
                time.sleep(0.8 if keyword=="DEMO-AN" else 0.12)
                rows=[r for r in ROWS if not keyword or keyword in r["name"].upper() or keyword in r["idNumber"].upper()]
                page=max(0,int(q.get("page",[0])[0]));size=max(1,min(100,int(q.get("size",[20])[0])))
                return self.send(200,{"detail":{"content":rows[page*size:(page+1)*size],"totalElements":len(rows),"page":page,"size":size}})
            if "/youths/" in u.path or "current" in u.path or "me"==u.path.rsplit("/",1)[-1]:
                return self.send(200,{"detail":{"id":999,"name":"Demo chỉ đọc","memberType":"UNION_MEMBER"}})
            return self.send(200,{"detail":[]})
        target=(ROOT/u.path.lstrip("/")).resolve()
        if not target.is_relative_to(ROOT):return self.send(403,{"error":"path"})
        if not target.is_file():target=ROOT/"index.html"
        mime=mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix==".js":mime="application/javascript"
        self.send(200,target.read_bytes(),mime)

def proxy(encoded):
    from urllib.request import urlopen
    from urllib.error import HTTPError
    command=json.loads(base64.b64decode(encoded))
    try: response=urlopen("http://127.0.0.1:8088"+command["path"],timeout=12)
    except HTTPError as error: response=error
    body=response.read(300000)
    if len(body)>260000: raise ValueError("response limit")
    print("TNQD_HTTP:"+json.dumps({"status":response.status,"content_type":response.headers.get("Content-Type"),"body_base64":base64.b64encode(body).decode()}),flush=True)

if __name__=="__main__":
    if sys.argv[1:2]==["prepare"]:prepare()
    elif sys.argv[1:2]==["proxy"]:proxy(sys.argv[2])
    elif sys.argv[1:2]==["start"]:
        import subprocess
        subprocess.Popen([sys.executable,str(Path(__file__).resolve()),"serve"],stdout=open("tnqd-http.log","ab"),stderr=subprocess.STDOUT,start_new_session=True)
        time.sleep(1); print("TNQD_STARTED",flush=True)
    else:ThreadingHTTPServer(("0.0.0.0",8088),Handler).serve_forever()
