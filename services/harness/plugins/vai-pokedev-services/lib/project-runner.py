"""Run approved project commands only inside a fresh Sandbox; preserve protected source/tests."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile

HOME = Path.cwd()
COMMAND = json.loads((HOME / "project-job.json").read_text())
ROOT = HOME / "project-source"
RESULT = {k: COMMAND[k] for k in ("job_id", "scope_id", "source_sha256", "plan_digest")}
RESULT.update(state="RUNNING", checks=[], browser_checks=[], protected_intact=False, preview_ready=False, passed=False)


def persist():
    path = HOME / "project-result.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(RESULT, ensure_ascii=False), encoding="utf8")
    temporary.replace(path)


def valid_path(name):
    return name and not name.startswith("/") and "\\" not in name and ":" not in name and all(p not in {"", ".", "..", ".git"} and not p.startswith(".env") for p in name.split("/"))


def hashes(paths):
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}


def run_browser():
    sys.path.insert(0, "/app")
    from playwright.sync_api import sync_playwright, expect
    from src.agent1.explorer.playwright_driver import PlaywrightDriver
    from src.agent1.explorer.recorder import TraceRecorder
    from src.agent1.explorer.session import ExplorationSession
    session = ExplorationSession(output_root="project-evidence", base_url="http://127.0.0.1:8088/", actor="project-sandbox", total_deadline_ms=180000, run_id="POKEDEV-" + COMMAND["job_id"])
    class PrivateDriver(PlaywrightDriver):
        def storage_entries(self):
            return []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 960})
        context.route("**/*", lambda route: route.continue_() if route.request.url.startswith("http://127.0.0.1:8088/") else route.abort())
        page = context.new_page()
        recorder = TraceRecorder(session, PrivateDriver(page, actor="project-sandbox"), step_deadline_ms=20000)
        checks = COMMAND.get("browser_checks") or [{"label": "Ứng dụng mở được trong Sandbox", "steps": [{"action": "goto", "path": "/"}, {"action": "visible", "selector": "body"}]}]
        for index, check in enumerate(checks, 1):
            def action(_, check=check):
                page.goto("http://127.0.0.1:8088/", wait_until="domcontentloaded")
                for step in check.get("steps", []):
                    kind = step["action"]
                    if kind == "goto":
                        path = step.get("path", "/")
                        if not path.startswith("/") or path.startswith("//"):
                            raise ValueError("PROJECT_BROWSER_PATH_INVALID")
                        page.goto("http://127.0.0.1:8088" + path, wait_until="domcontentloaded")
                    elif kind == "text":
                        expect(page.get_by_text(step["text"], exact=False).first).to_be_visible()
                    elif kind == "visible":
                        expect(page.locator(step["selector"]).first).to_be_visible()
                    elif kind == "fill":
                        page.locator(step["selector"]).first.fill(step["value"])
                    elif kind == "click":
                        page.locator(step["selector"]).first.click()
                    else:
                        raise ValueError("PROJECT_BROWSER_ACTION_INVALID")
            recorder.record("STEP-1-" + str(index), check["label"], "ASSERT", action, target=check["label"])
        required = ["STEP-1-" + str(i) for i in range(1, len(checks) + 1)]
        if [r.get("step_id") for r in session.records] != required:
            raise ValueError("PROJECT_BROWSER_TRACE_INCOMPLETE")
        import inspect
        if "required_steps" in inspect.signature(session.finalize).parameters:
            session.finalize(required_steps=required)
        else:
            session.finalize("PASSED" if all(r.get("status") == "GROUNDED" for r in session.records) else "FAILED")
        RESULT["browser_checks"] = [{"id": "B" + str(i + 1), "label": record["user_intent"], "passed": record["status"] == "GROUNDED", "error": str(record.get("observed_ui", {}).get("error", ""))[:1500]} for i, record in enumerate(session.records)]
        RESULT["browser_backend"] = "TestForge TraceRecorder"
        RESULT["browser_run_id"] = session.run_id
        context.close(); browser.close()


def main():
    persist()
    encoded = "".join((HOME / ("project-upload-" + str(i) + ".txt")).read_text() for i in range(COMMAND["chunks"]))
    archive = base64.b64decode(encoded, validate=True)
    if hashlib.sha256(archive).hexdigest() != COMMAND["source_sha256"]:
        raise ValueError("PROJECT_SOURCE_HASH_MISMATCH")
    ROOT.mkdir(exist_ok=True)
    paths, expanded = [], 0
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        for item in source.infolist():
            if item.is_dir():
                continue
            if not valid_path(item.filename) or item.filename in paths or stat.S_ISLNK(item.external_attr >> 16) or item.file_size > 16000000:
                raise ValueError("PROJECT_ARCHIVE_PATH_INVALID")
            expanded += item.file_size
            if expanded > 160000000 or len(paths) > 20000:
                raise ValueError("PROJECT_ARCHIVE_LIMIT")
            target = ROOT / item.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read(item)); paths.append(item.filename)
    initial = hashes(paths)
    protected = hashes(COMMAND["protected_paths"])
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR"}}
    env.update(PORT="8088", HOST="0.0.0.0", PYTHONDONTWRITEBYTECODE="1", CI="true")
    for index, command in enumerate(COMMAND["commands"], 1):
        start = time.time()
        try:
            completed = subprocess.run(command["argv"], cwd=ROOT, env=env, capture_output=True, timeout=min(600, max(5, command.get("timeout", 180))))
            check = {"id": "V" + str(index), "label": command.get("label", "Kiểm tra dự án"), "argv": command["argv"], "exit_code": completed.returncode, "passed": completed.returncode == 0, "stdout": completed.stdout.decode(errors="replace")[-12000:], "stderr": completed.stderr.decode(errors="replace")[-6000:], "duration": time.time() - start}
        except subprocess.TimeoutExpired:
            check = {"id": "V" + str(index), "label": command.get("label", "Kiểm tra dự án"), "passed": False, "exit_code": -1, "stderr": "Quá thời gian chạy lệnh", "duration": time.time() - start}
        RESULT["checks"].append(check); persist()
        if not check["passed"]:
            RESULT.update(state="FAILED", error_code="PROJECT_CHECKS_FAILED"); return
    RESULT["protected_intact"] = hashes(COMMAND["protected_paths"]) == protected
    if not RESULT["protected_intact"] or hashes(paths) != initial:
        raise ValueError("PROJECT_SOURCE_OR_TEST_CHANGED_DURING_VERIFY")
    preview = COMMAND.get("preview")
    if preview:
        argv = preview.get("argv")
        if not argv:
            relative = preview.get("path", ".")
            if relative != "." and not valid_path(relative):
                raise ValueError("PROJECT_PREVIEW_PATH_INVALID")
            argv = ["python", "-m", "http.server", "8088", "--bind", "0.0.0.0", "--directory", relative]
        log = (HOME / "project-app.log").open("wb")
        subprocess.Popen(argv, cwd=ROOT, env=env, stdout=log, stderr=log)
        for i in range(40):
            try:
                with urllib.request.urlopen("http://127.0.0.1:8088/", timeout=2) as response:
                    if response.status < 400:
                        RESULT["preview_ready"] = True; break
            except Exception:
                time.sleep(0.5)
        if not RESULT["preview_ready"]:
            raise ValueError("PROJECT_PREVIEW_START_FAILED")
        run_browser()
    if hashes(COMMAND["protected_paths"]) != protected or hashes(paths) != initial:
        raise ValueError("PROJECT_SOURCE_OR_TEST_CHANGED_DURING_VERIFY")
    RESULT.update(passed=all(c["passed"] for c in RESULT["checks"] + RESULT["browser_checks"]), binding_verified=True)
    RESULT["state"] = "SUCCEEDED" if RESULT["passed"] else "FAILED"
    if not RESULT["passed"]:
        RESULT["error_code"] = "PROJECT_BROWSER_CHECKS_FAILED"


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        RESULT.update(state="FAILED", error_code=str(error) if str(error).startswith("PROJECT_") else "PROJECT_RUNNER_FAILED", error_type=type(error).__name__)
    finally:
        RESULT["completed_at"] = time.time(); persist()
