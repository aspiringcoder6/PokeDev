"""TestForge AI Broker — cầu nối HTTP giữa agent-harness-server (container Linux)
và TestForge AI pipeline (Windows host).

Mô hình Broker Pattern (docs/27_plugin_harness_design.md):

    LLM (trong harness container)
      -> tool testforge_* (plugin testforge-ai/lib/index.js)
      -> HTTP POST http://<host>:9099/api/v1/{explore|replay|staging|perf}
      -> broker spawn subprocess (scripts/run_explorer.py | replay_spec.py | ...)
      -> LLM poll GET /api/v1/result/{job_id} -> JSON

Vì sao broker: container harness là node:22-bookworm-slim, bwrap chặn internet,
200 pids, không có venv/Playwright/k6 — pipeline phải chạy trên Windows host.

Chạy:
    .venv\\Scripts\\python.exe testforge_broker.py --host 0.0.0.0 --port 9099

Cấu hình (env):
    TESTFORGE_BROKER_TOKEN      Bearer token bắt buộc cho mọi endpoint (trừ /health)
    TESTFORGE_ALLOWED_ORIGINS   CSV Origin được phép (CORS, chỉ áp dụng khi client gửi Origin)
    TESTFORGE_PROJECT_ROOT      Mặc định: thư mục cha của file này (cwd cho subprocess)
    TESTFORGE_PYTHON            Interpreter chạy scripts (mặc định: sys.executable)
    TESTFORGE_JOB_TIMEOUT       Timeout job mặc định, giây (mặc định 600)
    AGENT_MEMORY_API_URL        Base URL Agent Memory API (mặc định http://127.0.0.1:8000/v1)
    AGENT_MEMORY_API_KEY        (tuỳ chọn) Bearer token cho Agent Memory API

Endpoint /api/v1/fetch-testcase: lấy dữ liệu testcase từ Agent Memory (GraphRAG
recall) — trả raw chunks/entities, caller (LLM) tự compose 5-field Standard Test
Input; nếu Agent Memory không online, trả lỗi 502 tường minh.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")
BROKER_VERSION = "1.3"

TOKEN = os.getenv("TESTFORGE_BROKER_TOKEN", "")
ALLOWED_ORIGINS = {
    o.strip() for o in os.getenv("TESTFORGE_ALLOWED_ORIGINS", "").split(",") if o.strip()
}
DEFAULT_TIMEOUT = int(os.getenv("TESTFORGE_JOB_TIMEOUT", "600"))
MAX_TIMEOUT = 1200
MAX_BODY_BYTES = 10 * 1024
AGENT_MEMORY_URL = os.getenv("AGENT_MEMORY_API_URL", "http://127.0.0.1:8000/v1").rstrip("/")
AGENT_MEMORY_KEY = os.getenv("AGENT_MEMORY_API_KEY", "")

app = FastAPI(title="TestForge AI Broker", version=BROKER_VERSION)


# ---------------------------------------------------------------------------
# Job manager — sequential (1 worker): các job chạy tuần tự để tránh xung đột
# SUT/browser; job mới khi đang bận sẽ ở trạng thái "queued".
# ---------------------------------------------------------------------------

class JobManager:
    def __init__(self) -> None:
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="testforge-job")

    def submit(self, result_type: str, cmd: List[str], timeout: int) -> str:
        job_id = f"JOB-{uuid4_hex()}"
        job: Dict[str, Any] = {
            "job_id": job_id,
            "result_type": result_type,
            "status": "queued",
            "command": cmd,
            "timeout_seconds": timeout,
            "submitted_at": time.time(),
            "started_at": None,
            "finished_at": None,
            "exit_code": None,
            "error": None,
            "output": None,
        }
        with self._lock:
            self._jobs[job_id] = job
        self._pool.submit(self._run, job_id, cmd, timeout)
        return job_id

    def _run(self, job_id: str, cmd: List[str], timeout: int) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job["status"] = "running"
            job["started_at"] = time.time()
        log_path = os.path.join(PROJECT_ROOT, "artifacts", "broker", f"{job_id}.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        env = os.environ.copy()
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            proc = subprocess.Popen(  # noqa: S603 — cmd do broker tự dựng
                cmd,
                cwd=PROJECT_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                creationflags=creationflags,
            )
            try:
                raw, _ = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                raw, _ = proc.communicate()
                with self._lock:
                    job.update(
                        status="failed",
                        exit_code=proc.returncode,
                        finished_at=time.time(),
                        error=f"Job timeout after {timeout}s (log: {log_path})",
                    )
                _write_log(log_path, raw)
                return
        except Exception as exc:  # spawn failure
            with self._lock:
                job.update(status="failed", finished_at=time.time(), error=str(exc))
            return

        text = raw.decode("utf-8", errors="replace") if raw else ""
        _write_log(log_path, text)
        parsed = _parse_json_tail(text)
        with self._lock:
            job.update(
                status="completed" if proc.returncode == 0 else "failed",
                exit_code=proc.returncode,
                finished_at=time.time(),
                output={"parsed": parsed, "log_path": log_path, "tail": text[-4000:]},
            )
            if proc.returncode != 0 and not job["output"]["tail"].strip():
                job["error"] = f"exit={proc.returncode}, stdout rỗng (log: {log_path})"

    def get(self, job_id: str) -> Dict[str, Any] | None:
        with self._lock:
            return self._jobs.get(job_id)

    @property
    def active(self) -> int:
        with self._lock:
            return sum(1 for j in self._jobs.values() if j["status"] in ("queued", "running"))


def uuid4_hex() -> str:
    import uuid

    return uuid.uuid4().hex[:8]


def _write_log(path: str, text: str = "") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(text)


def _parse_json_tail(text: str) -> Any:
    """Scripts in ra JSON ở cuối stdout; thử nguyên khối, rồi từng đoạn từ cuối.

    Report thường in nhiều dòng (json.dumps indent) phía sau các dòng log —
    quét từ cuối: dòng đầu tiên bắt đầu '{' mở đầu khối JSON tới hết stdout.
    """
    if not text.strip():
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    lines = text.splitlines()
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip().startswith("{"):
            try:
                return json.loads("\n".join(lines[i:]))
            except json.JSONDecodeError:
                continue
    return None


jobs = JobManager()


# ---------------------------------------------------------------------------
# Security — token auth, body limit, optional Origin allowlist
# ---------------------------------------------------------------------------

def require_token(authorization: str = Header(default="")) -> None:
    if not TOKEN:
        return
    expected = f"Bearer {TOKEN}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Unauthorized: thiếu/sai Bearer token")


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    if ALLOWED_ORIGINS:
        origin = request.headers.get("origin")
        if origin and origin not in ALLOWED_ORIGINS:
            return JSONResponse(status_code=403, content={"detail": f"Origin bị từ chối: {origin}"})
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_BODY_BYTES:
        return JSONResponse(
            status_code=413, content={"detail": f"Body quá lớn (> {MAX_BODY_BYTES} bytes)"}
        )
    return await call_next(request)


# ---------------------------------------------------------------------------
# Request models — trường khớp CLI của scripts/ (docs/27 section 2)
# ---------------------------------------------------------------------------

class ExploreRequest(BaseModel):
    """scripts/run_explorer.py — explorer browser-first."""

    model_config = {"extra": "forbid"}

    input_json: str = Field("", description="Path 5-field JSON (ưu tiên khi khác rỗng)")
    input_inline: Optional[dict] = Field(
        None,
        description="Lối 1: 5-field Standard Test Input inline (function_id/feature/"
                    "precondition/steps/expected_result) — broker validate IN001-IN005, "
                    "ghi artifacts/inputs/<function_id>.json rồi chạy như input_json")
    feature: str = Field("", description="Path .feature Gherkin (khi không dùng input_json)")
    base_url: str
    api_url: str
    email: str
    actor: str = "admin"
    password_env: str = "STAGING_TTEAMFLOW_ADMIN_PASSWORD"
    cleanup_template: str = ""
    video: bool = False
    output: str = "artifacts/automation/exploration"
    headed: bool = Field(False, description="Mở browser có giao diện (xem agent thao tác)")
    slowmo: int = Field(0, ge=0, le=2000, description="Trễ mỗi action (ms) khi headed")
    job_timeout_seconds: int = Field(DEFAULT_TIMEOUT, ge=30, le=MAX_TIMEOUT)


class ReplayRequest(BaseModel):
    """scripts/replay_spec.py — replay fresh-state + Promotion Gate."""

    model_config = {"extra": "forbid"}

    session: str
    api_url: str
    email: str
    password_env: str = "STAGING_TTEAMFLOW_ADMIN_PASSWORD"
    cleanup_template: str = ""
    heal: bool = False
    fault_locator: List[str] = []
    headed: bool = Field(False, description="Mở browser có giao diện khi replay")
    slowmo: int = Field(0, ge=0, le=2000, description="Trễ mỗi action (ms) khi headed")
    job_timeout_seconds: int = Field(DEFAULT_TIMEOUT, ge=30, le=MAX_TIMEOUT)


class StagingRequest(BaseModel):
    """scripts/run_staging.py — regression suite + JUnit + proofs."""

    model_config = {"extra": "forbid"}

    profile: str
    suite: str
    output: str = "artifacts/automation/staging"
    keep_runs: int = 20
    job_timeout_seconds: int = Field(DEFAULT_TIMEOUT, ge=30, le=MAX_TIMEOUT)


class PerfRequest(BaseModel):
    """scripts/run_perf.py — Agent 2 performance test (k6)."""

    model_config = {"extra": "forbid"}

    requirement: str
    profile: str = "normal"
    tier: str | None = None
    base_url: str = "http://localhost"
    users_json: str = "opt/perf/users.json"
    timeout_seconds: int = 600
    capacity_report: bool = False
    staging_dir: str | None = None
    approved_by: str = ""
    justification: str = ""
    job_timeout_seconds: int = Field(DEFAULT_TIMEOUT, ge=30, le=MAX_TIMEOUT)


class FetchTestcaseRequest(BaseModel):
    """Lấy dữ liệu testcase từ Agent Memory (GraphRAG recall)."""

    model_config = {"extra": "forbid"}

    dataset: str = Field(description="Dataset id (UUID) hoặc tên dataset, VD 'testforge-P01'")
    query: str = Field(min_length=1, description="Câu truy vấn, VD 'FUNC-USER-ADD Add User'")
    function_id: str = Field("", description="function_id — được nối vào query nếu có")
    top_k: int = Field(5, ge=1, le=20)


# ---------------------------------------------------------------------------
# Command builders — request field -> CLI flag của script
# ---------------------------------------------------------------------------

def _py() -> str:
    return os.getenv("TESTFORGE_PYTHON", sys.executable)


def _validate_inline_input(std: dict) -> List[str]:
    """Validate 5-field inline theo schema chuẩn (quy tắc IN001-IN005).

    Ưu tiên validator chính thức của pipeline (schemas/standard_test_input.schema.json);
    nếu import lỗi thì fallback kiểm tra tối thiểu 5 trường.
    """
    try:
        from src.agent1.explorer.standard_input import validate_standard_input
        return [str(e) for e in validate_standard_input(std)]
    except Exception:
        errors: List[str] = []
        if not str(std.get("function_id") or "").strip():
            errors.append("function_id is required (IN001)")
        if not str(std.get("feature") or "").strip():
            errors.append("feature is required (IN002)")
        if not std.get("steps"):
            errors.append("steps must not be empty (IN003)")
        if not std.get("expected_result"):
            errors.append("expected_result is required (IN004)")
        return errors


def materialize_input_inline(req: ExploreRequest) -> str:
    """Lối 1: input_inline 5-field -> validate -> ghi file -> gán req.input_json.

    Ghi đè artifacts/inputs/<function_id>.json (cùng function_id = idempotent).
    Trả về đường dẫn file; raise HTTPException 422 khi input không hợp lệ hoặc
    input_json đã được cung cấp (hai lối loại trừ nhau).
    """
    std = req.input_inline
    if not isinstance(std, dict):
        raise HTTPException(status_code=422, detail="input_inline phải là object JSON 5 trường")
    if req.input_json:
        raise HTTPException(
            status_code=422,
            detail="Chỉ gửi MỘT trong input_json | input_inline (hai lối loại trừ nhau)")
    errors = _validate_inline_input(std)
    if errors:
        raise HTTPException(
            status_code=422,
            detail="input_inline không hợp lệ: " + "; ".join(errors[:5]))
    function_id = str(std.get("function_id") or "").strip() or "FUNC-UNKNOWN"
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", function_id).strip("._-") or "FUNC-UNKNOWN"
    out_dir = Path(PROJECT_ROOT) / "artifacts" / "inputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{safe_name}.json"
    out_path.write_text(json.dumps(std, ensure_ascii=False, indent=2), encoding="utf-8")
    req.input_json = str(out_path)
    return str(out_path)


def build_explore(req: ExploreRequest) -> List[str]:
    cmd = [_py(), "-u", os.path.join(SCRIPTS_DIR, "run_explorer.py")]
    if req.input_json:
        cmd += ["--input-json", req.input_json]
    elif req.feature:
        cmd += ["--feature", req.feature]
    cmd += ["--base-url", req.base_url, "--api-url", req.api_url, "--email", req.email,
            "--actor", req.actor, "--password-env", req.password_env, "--output", req.output]
    if req.cleanup_template:
        cmd += ["--cleanup-template", req.cleanup_template]
    if req.video:
        cmd.append("--video")
    if req.headed:
        cmd.append("--headed")
        if req.slowmo:
            cmd += ["--slowmo", str(req.slowmo)]
    return cmd


def build_replay(req: ReplayRequest) -> List[str]:
    cmd = [_py(), "-u", os.path.join(SCRIPTS_DIR, "replay_spec.py"),
           "--session", req.session, "--api-url", req.api_url, "--email", req.email,
           "--password-env", req.password_env]
    if req.cleanup_template:
        cmd += ["--cleanup-template", req.cleanup_template]
    if req.heal:
        cmd.append("--heal")
    for loc in req.fault_locator:
        cmd += ["--fault-locator", loc]
    if req.headed:
        cmd.append("--headed")
        if req.slowmo:
            cmd += ["--slowmo", str(req.slowmo)]
    return cmd


def build_staging(req: StagingRequest) -> List[str]:
    return [_py(), "-u", os.path.join(SCRIPTS_DIR, "run_staging.py"),
            "--profile", req.profile, "--suite", req.suite,
            "--output", req.output, "--keep-runs", str(req.keep_runs)]


def build_perf(req: PerfRequest) -> List[str]:
    cmd = [_py(), "-u", os.path.join(SCRIPTS_DIR, "run_perf.py"),
           "--requirement", req.requirement, "--profile", req.profile,
           "--base-url", req.base_url, "--users-json", req.users_json,
           "--timeout-seconds", str(req.timeout_seconds)]
    if req.tier:
        cmd += ["--tier", req.tier]
    if req.staging_dir:
        cmd += ["--staging-dir", req.staging_dir]
    if req.approved_by:
        cmd += ["--approved-by", req.approved_by]
    if req.justification:
        cmd += ["--justification", req.justification]
    if req.capacity_report:
        cmd.append("--capacity-report")
    return cmd


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/v1/health")
async def health() -> dict[str, Any]:
    agent_memory_reachable: bool | None = None
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            # Cognee mounts its health endpoint at the server root.
            memory_origin = AGENT_MEMORY_URL.removesuffix("/api/v1")
            res = await client.get(f"{memory_origin}/health")
            agent_memory_reachable = res.status_code == 200
    except Exception:
        agent_memory_reachable = False
    return {
        "status": "ok",
        "version": BROKER_VERSION,
        "project_root": PROJECT_ROOT,
        "k6_installed": shutil.which("k6") is not None,
        "python": _py(),
        "venv_path": sys.prefix,
        "jobs_active": jobs.active,
        "agent_memory": {"url": AGENT_MEMORY_URL, "reachable": agent_memory_reachable},
        "auth_required": bool(TOKEN),
    }


@app.post("/api/v1/explore", status_code=202, dependencies=[Depends(require_token)])
async def explore(req: ExploreRequest) -> dict[str, Any]:
    input_file = materialize_input_inline(req) if req.input_inline else ""
    job_id = jobs.submit("explore", build_explore(req), req.job_timeout_seconds)
    resp = _accepted(job_id)
    if input_file:
        resp["input_file"] = input_file
    return resp


@app.post("/api/v1/replay", status_code=202, dependencies=[Depends(require_token)])
async def replay(req: ReplayRequest) -> dict[str, Any]:
    job_id = jobs.submit("replay", build_replay(req), req.job_timeout_seconds)
    return _accepted(job_id)


@app.post("/api/v1/staging", status_code=202, dependencies=[Depends(require_token)])
async def staging(req: StagingRequest) -> dict[str, Any]:
    job_id = jobs.submit("staging", build_staging(req), req.job_timeout_seconds)
    return _accepted(job_id)


@app.post("/api/v1/perf", status_code=202, dependencies=[Depends(require_token)])
async def perf(req: PerfRequest) -> dict[str, Any]:
    job_id = jobs.submit("perf", build_perf(req), req.job_timeout_seconds)
    return _accepted(job_id)


class RecommendRequest(BaseModel):
    """Agent 3: PRUN FAIL -> recommendation REC (scripts/run_recommend.py)."""

    model_config = {"extra": "forbid"}

    perf_run: str = Field("", description="PRUN-<id>; rỗng = PRUN FAIL mới nhất")
    no_llm: bool = Field(False, description="Chỉ heuristic Zero-LLM")
    capacity: bool = Field(False, description="Nạp aggregated report cùng perf_req_id làm evidence")
    context: str = Field("", description="Context thêm cho LLM (source/config/SQL...)")


def build_recommend(req: RecommendRequest) -> List[str]:
    cmd = [_py(), "-u", os.path.join(SCRIPTS_DIR, "run_recommend.py")]
    cmd += ["--perf-run", req.perf_run] if req.perf_run else ["--latest-fail"]
    if req.no_llm:
        cmd.append("--no-llm")
    if req.capacity:
        cmd.append("--capacity")
    if req.context:
        cmd += ["--context", req.context]
    return cmd


@app.post("/api/v1/recommend", status_code=202, dependencies=[Depends(require_token)])
async def recommend(req: RecommendRequest) -> dict[str, Any]:
    job_id = jobs.submit("recommend", build_recommend(req), DEFAULT_TIMEOUT)
    return _accepted(job_id)


@app.get("/api/v1/result/{job_id}", dependencies=[Depends(require_token)])
async def result(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown job_id: {job_id}")
    payload = dict(job)
    if payload.get("started_at") and payload.get("finished_at"):
        payload["elapsed_seconds"] = round(payload["finished_at"] - payload["started_at"], 1)
    elif payload.get("started_at"):
        payload["elapsed_seconds"] = round(time.time() - payload["started_at"], 1)
    else:
        payload["elapsed_seconds"] = 0
    return payload


@app.post("/api/v1/fetch-testcase", dependencies=[Depends(require_token)])
async def fetch_testcase(req: FetchTestcaseRequest) -> dict[str, Any]:
    """GraphRAG recall từ Agent Memory: resolve dataset (id hoặc tên) -> /search.

    Trả raw context (chunks + entities + related_chunks). LLM/agent tự map về
    5-field Standard Test Input; TestForge validator (IN001-IN005) sẽ chặn nếu
    thiếu trường — Zero-LLM ở tầng pipeline.
    """
    query = f"{req.function_id} {req.query}".strip() if req.function_id else req.query
    headers = {"accept": "application/json"}
    if AGENT_MEMORY_KEY:
        headers["authorization"] = f"Bearer {AGENT_MEMORY_KEY}"
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            dataset_id = await _resolve_dataset(client, req.dataset)
            res = await client.get(
                f"{AGENT_MEMORY_URL}/search",
                params={"dataset_id": dataset_id, "q": query, "top_k": req.top_k},
            )
            res.raise_for_status()
            recall = res.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Agent Memory trả lỗi {exc.response.status_code}: {exc.response.text[:300]}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Không gọi được Agent Memory ({AGENT_MEMORY_URL}): {exc}",
        ) from exc

    return {
        "dataset": req.dataset,
        "dataset_id": dataset_id,
        "query": query,
        "chunks": recall.get("chunks", []),
        "entities": recall.get("entities", []),
        "related_chunks": recall.get("related_chunks", []),
        "note": (
            "Raw GraphRAG context — map về Standard Test Input 5 trường "
            "(function_id/feature/precondition/steps/expected_result) trước khi "
            "truyền cho testforge_explore; validator sẽ chặn input thiếu trường."
        ),
    }


async def _resolve_dataset(client: httpx.AsyncClient, dataset: str) -> str:
    """dataset là UUID id hoặc tên — trả về id."""
    if "-" in dataset and len(dataset) == 36:
        return dataset
    res = await client.get(f"{AGENT_MEMORY_URL}/datasets")
    res.raise_for_status()
    for row in res.json():
        if row.get("name", "").lower() == dataset.lower() or row.get("dataset_id") == dataset:
            return row["dataset_id"]
    raise HTTPException(status_code=404, detail=f"Không tìm thấy dataset '{dataset}'")


def _accepted(job_id: str) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "status": "queued",
        "poll_url": f"/api/v1/result/{job_id}",
        "note": "Job đã nhận. Poll GET /api/v1/result/{job_id} hoặc dùng tool testforge_result.",
    }


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def main() -> None:
    parser = argparse.ArgumentParser(description="TestForge AI Broker (FastAPI)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9099)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
