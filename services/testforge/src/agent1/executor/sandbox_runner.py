"""SandboxedPlaywrightExecutor — Bước 11 backend chạy Playwright trong sandbox-kit (M3.2).

Cùng contract execute_script() với PlaywrightExecutor — pipeline/benchmark có thể
đổi backend bằng cờ mà không đụng code downstream.

Luồng cho 1 session (reuse ttl=0):
  1. POST /api/v1/management/sessions {image: playwright official, ttl: 0}
  2. Poll GET /sessions/{id}/status đến runnerConnected
  3. Setup 1 lần: package.json + npm install + playwright.config.ts + demo_app/*
  4. Mỗi test case: write faults.json (fault thật) + specs/{tc}.spec.ts
     → runShellCommand "npx playwright test <spec> --reporter=json" (stdout = JSON report)
     → runReadFile evidence.json (text; CR-02 binary-safe đã có nếu cần)
  5. Teardown: DELETE /sessions/{id}

Điều kiện theo exitCode (KHÔNG theo status — CR-04: status chỉ là hiển thị).
"""

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from .runner import PlaywrightExecutor

DEFAULT_IMAGE = "mcr.microsoft.com/playwright:v1.63.0-jammy"
DEFAULT_BROKER = "http://127.0.0.1:8000"


class SandboxExecutor:
    """Backend thực thi Playwright bên trong sandbox-kit container."""

    def __init__(
        self,
        broker_url: str = DEFAULT_BROKER,
        image: str = DEFAULT_IMAGE,
        cpu: str = "2",
        memory: str = "4Gi",
        timeout_ms: int = PlaywrightExecutor.DEFAULT_TIMEOUT_MS,
        session_id: Optional[str] = None,
    ):
        self.broker_url = broker_url.rstrip("/")
        self.image = image
        self.cpu = cpu
        self.memory = memory
        self.timeout_ms = timeout_ms
        self.session_id = session_id or f"testforge-{int(time.time())}"
        self._session_ready = False
        self._setup_done = False

    # ------------------------------------------------------------------
    # HTTP helpers (stdlib-only, giống remote.py của sandbox-kit)
    # ------------------------------------------------------------------
    def _request(self, method: str, path: str, data: Optional[dict] = None, timeout: int = 120) -> dict:
        url = f"{self.broker_url}{path}"
        headers = {"Content-Type": "application/json"} if data else {}
        body = json.dumps(data).encode("utf-8") if data else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content = resp.read().decode("utf-8")
                return json.loads(content) if content else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"[sandbox] {method} {path} -> HTTP {e.code}: {detail[:300]}") from e

    def _execute(self, action_key: str, action_spec: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/api/v1/agent/execute", {
            "session_id": self.session_id,
            "action": {action_key: action_spec},
        })

    def shell(self, command: str, timeout: int = 120) -> Dict[str, Any]:
        return self._execute("runShellCommand", {"command": command, "timeout": timeout})

    def write_file(self, filepath: str, contents: str) -> None:
        self._execute("runWriteFile", {"filepath": filepath, "contents": contents})

    def read_file(self, filepath: str, encoding: Optional[str] = None) -> str:
        spec: Dict[str, Any] = {"filepath": filepath}
        if encoding:
            spec["encoding"] = encoding
        return self._execute("runReadFile", spec).get("stdout", "")

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------
    def start_session(self, setup_npm: bool = True) -> str:
        """Tạo session + chờ runner + setup môi trường 1 lần."""
        if self._session_ready:
            return self.session_id
        res = self._request("POST", "/api/v1/management/sessions", {
            "session_id": self.session_id,
            "image": self.image,
            "cpu": self.cpu,
            "memory": self.memory,
            "ttl": 0,
        })
        deadline = time.time() + 90
        while time.time() < deadline:
            status = self._request("GET", f"/api/v1/agent/sessions/{self.session_id}/status")
            if status.get("runnerConnected"):
                self._session_ready = True
                break
            time.sleep(1)
        if not self._session_ready:
            raise RuntimeError(f"[sandbox] runner không kết nối trong 90s: {self.session_id}")

        if setup_npm and not self._setup_done:
            pkg = {"name": "testforge-sandbox", "version": "1.0.0", "private": True,
                   "devDependencies": {"@playwright/test": "1.63.0"}}
            self.write_file("/workspace/package.json", json.dumps(pkg, indent=2))
            res = self.shell("cd /workspace && npm install --no-audit --no-fund", timeout=240)
            if res.get("exitCode") != 0:
                raise RuntimeError(f"[sandbox] npm install failed: {str(res.get('stderr'))[:300]}")
            self._setup_done = True
        return self.session_id

    def stop_session(self) -> None:
        try:
            self._request("DELETE", f"/api/v1/management/sessions/{self.session_id}")
        except Exception:
            pass
        self._session_ready = False

    def __enter__(self):
        self.start_session()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.stop_session()

    # ------------------------------------------------------------------
    # execute_script — CÙNG contract với PlaywrightExecutor
    # ------------------------------------------------------------------
    def discovery_check(self, spec_path: str) -> Dict[str, Any]:
        """Bước 9.5 trong sandbox: Playwright discovery check qua runShellCommand."""
        res = self.shell(
            f"cd /workspace && npx playwright test {spec_path} --list", timeout=90
        )
        ok = res.get("exitCode") == 0
        return {"ok": bool(ok), "stderr": str(res.get("stderr") or "")[-500:]}

    def execute_script(
        self,
        test_case_id: str,
        script_path_or_code: str,
        simulated_outcome: Optional[Dict[str, Any]] = None,
        script_path: Optional[str] = None,
        real_runtime: bool = True,
    ) -> Dict[str, Any]:
        """Thực thi spec trong sandbox. Spec PHẢI đã write_file vào /workspace trước
        (script_path = đường dẫn container, e.g. /workspace/specs/TC-X.spec.ts)."""
        if simulated_outcome:
            return PlaywrightExecutor._simulated_result(test_case_id, simulated_outcome)

        spec_container_path = script_path or f"/workspace/specs/{test_case_id}.spec.ts"
        cmd = (
            f"cd /workspace && npx playwright test {spec_container_path} "
            f"--reporter=json --timeout={self.timeout_ms}"
        )
        res = self.shell(cmd, timeout=max(self.timeout_ms // 1000 + 60, 120))

        report = PlaywrightExecutor._extract_json_report(res.get("stdout", ""))
        if report is None:
            return {
                "test_case_id": test_case_id,
                "status": "ERROR",
                "duration_ms": 0,
                "failed_step": None,
                "error": f"[sandbox] No JSON report. stderr: {str(res.get('stderr'))[:400]}",
                "artifacts": [],
                "network_events": [],
                "ui_evidence": {},
            }

        exec_res = PlaywrightExecutor.parse_playwright_report(report, test_case_id)
        # CR-02: fetch evidence.json (text) — quyết định phân loại ở Analyzer
        results = (report.get("suites") or [])
        for att in self._iter_attachments(report):
            if att.get("name") in ("evidence.json", "evidence") and att.get("path"):
                try:
                    raw = self.read_file(att["path"])
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        exec_res["network_events"] = parsed.get("network_events") or []
                        exec_res["ui_evidence"] = parsed.get("ui_evidence") or {}
                except (ValueError, RuntimeError):
                    pass
        return exec_res

    @staticmethod
    def _iter_attachments(report: Dict[str, Any]):
        def walk(suites):
            for s in suites or []:
                for spec in s.get("specs") or []:
                    for t in spec.get("tests") or []:
                        for r in t.get("results") or []:
                            yield from (r.get("attachments") or [])
                yield from walk(s.get("suites") or [])
        yield from walk(report.get("suites") or [])
