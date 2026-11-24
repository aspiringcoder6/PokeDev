"""Local engineering smoke only. Workflow acceptance still runs in the remote Sandbox."""
import importlib.util
from pathlib import Path
from http.server import ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location("tnqd_preview",ROOT/"integration-sources/pokedev-services-plugin/lib/tnqd-preview-server.py")
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
module.ROOT=(ROOT/"adlc-flow/data/tnqd-live/c-ce9de1ce08e8/dist/pokedev-tnqd/browser").resolve()
ThreadingHTTPServer(("127.0.0.1",8098),module.Handler).serve_forever()
