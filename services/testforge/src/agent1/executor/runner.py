"""Playwright Sandboxed Executor (Bước 11).

Nhiệm vụ:
- Khởi tạo môi trường runtime (Chromium/Firefox/WebKit) qua Node subprocess.
- Thực thi script Playwright đã sinh ra (real mode) hoặc simulated mode cho unit test.
- Thu thập bằng chứng (evidence): screenshots, traces, logs.
- Trả về ExecutionResult có cấu trúc chuẩn (schemas/execution_result.schema.json).

Chế độ:
- real_runtime=False (mặc định): không đụng browser — dùng cho unit test/mock pipeline.
- real_runtime=True: gọi `npx playwright test <spec>` với JSON reporter, parse kết quả thật.
"""

import json
import re
import shutil
import subprocess
import os
import signal
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional


class PlaywrightExecutor:
    """Bộ thực thi kịch bản Playwright và thu thập evidence."""

    DEFAULT_TIMEOUT_MS = 30000
    PROCESS_TIMEOUT_SECONDS = 180

    def __init__(
        self,
        browser_type: str = "chromium",
        headless: bool = True,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        project_root: Optional[str] = None,
        npx_command: Optional[str] = None,
        config_path: Optional[str] = None,
    ):
        """
        Args:
            browser_type: Trình duyệt thực thi (chromium/firefox/webkit)
            headless: Chạy ẩn browser hay không
            timeout_ms: Timeout mỗi test case (đồng bộ playwright.config.ts)
            project_root: Thư mục chứa playwright.config.ts (mặc định: root của repo)
            npx_command: Đường dẫn npx (tự dò nếu bỏ trống; Windows ưu tiên npx.cmd)
        """
        self.browser_type = browser_type
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self.npx_command = npx_command or shutil.which("npx.cmd") or shutil.which("npx") or "npx"
        self.config_path = config_path

    def execute_script(
        self,
        test_case_id: str,
        script_path_or_code: str,
        simulated_outcome: Optional[Dict[str, Any]] = None,
        script_path: Optional[str] = None,
        real_runtime: bool = False,
    ) -> Dict[str, Any]:
        """Thực thi script kiểm thử và trả về kết quả cấu trúc ExecutionResult.

        Args:
            test_case_id: Mã test case
            script_path_or_code: Đường dẫn file spec hoặc nội dung script
            simulated_outcome: Giả lập kết quả (dùng cho unit test/pipeline mock)
            script_path: Đường dẫn file .spec.ts đã lưu bởi ArtifactStore (real mode)
            real_runtime: True -> chạy Playwright thật qua subprocess; False -> mock kết quả

        Returns:
            Dict cấu trúc ExecutionResult
        """
        if simulated_outcome:
            return self._simulated_result(test_case_id, simulated_outcome)

        if not real_runtime:
            # Chế độ mặc định (không runtime): kết quả hợp lệ giữ pipeline thông
            return {
                "test_case_id": test_case_id,
                "status": "SIMULATED",
                "execution_mode": "simulated",
                "duration_ms": 0,
                "failed_step": None,
                "error": None,
                "artifacts": [],
            }

        result = self.execute_script_file(script_path or script_path_or_code, test_case_id)
        result["execution_mode"] = "local"
        return result

    # ------------------------------------------------------------------
    # Real runtime (Bước 11 — subprocess Node)
    # ------------------------------------------------------------------
    def discovery_check(self, spec_path: str) -> Dict[str, Any]:
        """Bước 9.5 — TypeScript compile / Playwright discovery check (không cần browser).

        `npx playwright test <spec> --list` buộc Playwright loader transpile và
        đăng ký file spec -> bắt mọi lỗi cú pháp/import mà Static Validator
        (heuristic) không thấy. Chạy TRƯỚC browser execution.

        Returns: {"ok": bool, "stderr": str}
        """
        if not Path(spec_path).exists():
            return {"ok": False, "stderr": f"Spec file not found: {spec_path}"}
        # Native separators: Playwright so khop filter voi path tuyet doi goc
        # (as_posix() khong khop tren Windows -> "No tests found").
        spec_arg = re.escape(str(Path(spec_path).resolve()))
        cmd = [self.npx_command, "playwright", "test", spec_arg, "--list"]
        if self.config_path:
            cmd.extend(["--config", self.config_path])
        try:
            proc = self._run_subprocess(cmd, timeout=90)
            return {"ok": proc.returncode == 0, "stderr": (proc.stderr or "")[-500:]}
        except FileNotFoundError:
            return {"ok": False, "stderr": f"Playwright runtime not found: {self.npx_command}"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "stderr": "discovery check timed out"}

    def execute_script_file(self, spec_path: str, test_case_id: str) -> Dict[str, Any]:
        """Chạy một file .spec.ts bằng Playwright CLI và parse kết quả.

        Args:
            spec_path: Đường dẫn tuyệt đối/tương đối tới file .spec.ts
            test_case_id: Mã test case (để trace)

        Returns:
            ExecutionResult
        """
        if not Path(spec_path).exists():
            return {
                "test_case_id": test_case_id,
                "status": "ERROR",
                "duration_ms": 0,
                "failed_step": None,
                "error": f"Spec file not found: {spec_path}",
                "artifacts": [],
            }

        # Playwright CLI coi đối số file là regex:
        # - dùng absolute path gốc OS (as_posix() không khớp trên Windows)
        # - re.escape để path chứa '.'/'-' khớp literal
        spec_arg = re.escape(str(Path(spec_path).resolve()))
        cmd = [
            self.npx_command, "playwright", "test",
            spec_arg,
            "--reporter=json",
            f"--timeout={self.timeout_ms}",
        ]
        if not self.headless:
            cmd.append("--headed")
        if self.config_path:
            cmd.extend(["--config", self.config_path])

        try:
            proc = self._run_subprocess(cmd)
        except FileNotFoundError:
            return {
                "test_case_id": test_case_id,
                "status": "ERROR",
                "duration_ms": 0,
                "failed_step": None,
                "error": f"Playwright runtime not found: '{self.npx_command}' is not available",
                "artifacts": [],
            }

        report = self._extract_json_report(proc_stdout=proc.stdout)
        if report is None:
            return {
                "test_case_id": test_case_id,
                "status": "ERROR",
                "duration_ms": 0,
                "failed_step": None,
                "error": f"Failed to parse Playwright JSON report. stderr: {proc.stderr[-500:]}",
                "artifacts": [],
            }

        result = self.parse_playwright_report(report, test_case_id)
        if proc.returncode != 0 and result["status"] == "PASS":
            result.update(status="ERROR", error="Playwright process failed despite passing test entry")
        return result

    def _run_subprocess(self, cmd, timeout=None) -> Any:
        """Chạy subprocess với timeout; chuyển FileNotFoundError cho caller."""
        cli = self.project_root / "node_modules/@playwright/test/cli.js"
        if cli.is_file() and shutil.which("node"):
            cmd = [shutil.which("node"), str(cli.resolve()), *cmd[2:]]
        # File capture avoids inherited-pipe deadlocks from a webServer descendant.
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            process = subprocess.Popen(cmd, cwd=str(self.project_root), stdout=stdout,
                stderr=stderr, start_new_session=os.name != "nt")
            try:
                process.wait(timeout=timeout or self.PROCESS_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                return subprocess.CompletedProcess(cmd, 2, "", "Playwright process timed out")
            stdout.seek(0)
            stderr.seek(0)
            return subprocess.CompletedProcess(cmd, process.returncode,
                stdout.read().decode("utf-8", errors="replace"), stderr.read().decode("utf-8", errors="replace"))

    @staticmethod
    def _extract_json_report(proc_stdout: str) -> Optional[Dict[str, Any]]:
        """Trích JSON report từ stdout (bỏ qua các dòng nhiễu trước '{' đầu tiên).

        Args:
            proc_stdout: stdout của subprocess playwright test

        Returns:
            Dict JSON report hoặc None nếu không parse được
        """
        if not proc_stdout:
            return None
        start = proc_stdout.find("{")
        if start == -1:
            return None
        try:
            # raw_decode: parse object JSON đầu tiên, bỏ qua nhiễu đuôi stdout
            obj, _ = json.JSONDecoder().raw_decode(proc_stdout[start:])
            return obj
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Parse JSON report -> ExecutionResult
    # ------------------------------------------------------------------
    @classmethod
    def parse_playwright_report(cls, report: Dict[str, Any], test_case_id: str) -> Dict[str, Any]:
        """Chuyển Playwright JSON report thành ExecutionResult.

        Args:
            report: Dict JSON report từ @playwright/test
            test_case_id: Mã test case

        Returns:
            ExecutionResult: {test_case_id, status, duration_ms, failed_step, error, artifacts}
        """
        entry = cls._locate_test_result(report, test_case_id)

        duration_ms = 0
        error_msg: Optional[str] = None
        artifacts: list = []
        network_events: list = []
        ui_evidence: Dict[str, Any] = {}

        results = (entry or {}).get("results") or []
        if results:
            r0 = results[0]
            duration_ms = int(r0.get("duration", 0))
            errors = r0.get("errors") or []
            if errors:
                error_msg = str(errors[0].get("message", "")).strip() or None
            for att in r0.get("attachments") or []:
                if att.get("path"):
                    artifacts.append(att["path"])
                elif att.get("name"):
                    artifacts.append(att["name"])
                if att.get("name") in ("evidence.json", "evidence"):
                    evidence = cls._read_evidence_attachment(att)
                    network_events = evidence.get("network_events") or []
                    ui_evidence = evidence.get("ui_evidence") or {}

        status = cls._map_status(entry, results)
        failed_step = cls._infer_failed_step(error_msg or "")

        return {
            "test_case_id": test_case_id,
            "status": status,
            "duration_ms": duration_ms,
            "failed_step": failed_step,
            "error": error_msg,
            "artifacts": artifacts,
            "network_events": network_events,
            "ui_evidence": ui_evidence,
        }

    @staticmethod
    def _read_evidence_attachment(att: Dict[str, Any]) -> Dict[str, Any]:
        """Đọc attachment evidence.json (từ file đính kèm hoặc body base64)."""
        import base64
        try:
            if att.get("path"):
                raw = Path(att["path"]).read_text(encoding="utf-8")
            elif att.get("body"):
                raw = base64.b64decode(att["body"]).decode("utf-8")
            else:
                return {}
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except (OSError, ValueError):
            return {}

    @classmethod
    def _locate_test_result(cls, report: Dict[str, Any], test_case_id: str) -> Optional[Dict[str, Any]]:
        """Duyệt cây suites->specs->tests tìm entry khớp test_case_id."""
        def walk(suites: list) -> Optional[Dict[str, Any]]:
            for suite in suites or []:
                for spec in suite.get("specs") or []:
                    title = str(spec.get("title", ""))
                    for t in spec.get("tests") or []:
                        if test_case_id in title or test_case_id in str(t.get("title", "")):
                            return t
                found = walk(suite.get("suites") or [])
                if found:
                    return found
            return None

        return walk(report.get("suites") or [])

    @classmethod
    def _map_status(cls, entry: Dict[str, Any], results: list) -> str:
        """Ánh xạ outcome Playwright -> PASS/FAIL."""
        outcome = (entry or {}).get("status") or (results[0].get("status") if results else "unknown")
        return {
            "expected": "PASS",      # pass
            "unexpected": "FAIL",    # fail
            "flaky": "PASS",
            "skipped": "SKIPPED",
        }.get(str(outcome), "ERROR")

    @classmethod
    def _infer_failed_step(cls, error_message: str) -> Optional[int]:
        """Suy ra step bị lỗi từ comment '// Step N:' trong error stack (heuristic)."""
        import re
        match = re.search(r"Step (\d+)", error_message)
        return int(match.group(1)) if match else None

    # ------------------------------------------------------------------
    # Simulated mode (backward compatible)
    # ------------------------------------------------------------------
    @staticmethod
    def _simulated_result(test_case_id: str, simulated_outcome: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "test_case_id": test_case_id,
            "status": simulated_outcome.get("status", "PASS"),
            "execution_mode": "simulated",
            "duration_ms": simulated_outcome.get("duration_ms", 1200),
            "failed_step": simulated_outcome.get("failed_step"),
            "error": simulated_outcome.get("error"),
            "artifacts": simulated_outcome.get("artifacts", ["screenshot.png", "trace.zip"]),
        }
