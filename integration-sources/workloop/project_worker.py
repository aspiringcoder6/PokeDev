"""Requirement-driven Workloop DAG using real native TaskLoop agents and Sandbox verification."""
from __future__ import annotations

import asyncio
import base64
import difflib
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
from datetime import datetime
import sys
import time
import threading
from types import SimpleNamespace
from uuid import UUID, uuid4, uuid5
import zipfile
from copy import deepcopy

ROOT = Path(__file__).resolve().parents[2]
directory = Path(sys.argv[1]).resolve().parent
manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf8"))
runtime = ROOT / "adlc-flow/data/workloop/runtime/workloop/src"
sys.path[:0] = [str(ROOT / "sdk"), str(ROOT / "adlc-flow"), str(runtime), str(runtime / "workloop/engine")]
os.environ.update(WORKLOOP_SRC=str(runtime), WORKLOOP_TRACING="0", LANGFLOW_DATABASE_URL="sqlite:///" + str(directory / "engine.sqlite3").replace("\\", "/"))

from dsh_web_sdk import DshClient, RetryConfig
from workloop.backend.processing import process
from workloop.backend.services.db import Store
from workloop.gateway.deepseek_harness.gateway import DshHarnessGateway
from workloop.engine.workloop_task import WorkloopTask
from lfx.schema.data import Data
from langflow.adlc.live_workflows import validate_plan, safe_path, digest, LiveStore, execution_definitions, completed_native_nodes
from langflow.adlc.project_workflows import planning_plan
from langflow.adlc.gitea_projects import git, prepare_candidate, source_files, OMIT, DATA
from langflow.adlc.tnqd_memory import ProjectDocumentMemory
from langflow.adlc.human_inputs import HumanInputStore, wait_native_contract
from langflow.adlc.workflow_controls import active_inputs, condition_result
from langflow.adlc.project_environment import apply_environment, archive_sources, workspace_path
from langflow.adlc.project_recovery import WorkerCheckpoint, recoverable_error
from langflow.adlc.native_source_context import context_parts, pack_sources
from langflow.adlc.atomic_data import write_json_atomic

MODEL = manifest.get("model_route") or {"provider": "netmind", "model": "zai-org/GLM-5.3-Flash"}
human_inputs = HumanInputStore(DATA / "live.sqlite3")
BRIDGE = "/api/v1/pokedev-services/tnqd"
JOBS = "/api/v1/pokedev-services/projects/jobs"
snapshot = {k: manifest[k] for k in ("run_id", "scope_id", "phase")}
snapshot.update(state="PLANNING" if manifest["phase"] == "planning" else "RUNNING", nodes=[], events=[], documents=manifest.get("documents", []), checks=[], memory=[], error_code=None)
checkpoint = WorkerCheckpoint(directory, manifest)
recovered = checkpoint.read()["state"] if (manifest.get("recovery") or {}).get("generation") else None
if recovered:
    snapshot = deepcopy(recovered["snapshot"])
    snapshot.update(state="PLANNING" if manifest["phase"] == "planning" else "RUNNING", error_code=None)
    snapshot.pop("completed_at", None)
    snapshot.pop("recovery_required", None)
snapshot["recovery_generation"] = (manifest.get("recovery") or {}).get("generation", 0)
snapshot["worker_pid"] = os.getpid()
active_driver = None
persist_lock = threading.RLock()


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def persist():
    with persist_lock:
        snapshot["heartbeat_at"] = time.time()
        write_json_atomic(directory / "result.json", snapshot)
        if active_driver is not None:
            checkpoint.write(active_driver.checkpoint_state())


def update(identity, state=None, **values):
    row = next((n for n in snapshot["nodes"] if n["id"] == identity), None)
    if row is None:
        row = {"id": identity}; snapshot["nodes"].append(row)
    row.update(values)
    if state:
        row["state"] = state
        snapshot["events"].append({"node": identity, "state": state, "at": time.time()})
    persist()
    return row


class NativeGateway(DshHarnessGateway):
    def __init__(self, *args, node_id, **kwargs):
        super().__init__(*args, **kwargs); self.node_id = node_id

    async def _kill(self, ref):
        if snapshot.get("recovery_required"):
            return  # An uncertain transport acknowledgment must not cancel the session being recovered.
        return await super()._kill(ref)

    async def close_all(self):
        if snapshot.get("recovery_required"):
            return
        return await super().close_all()

    async def _open_session(self, spec):
        active_driver.native_intents[self.node_id]["stage"] = "opening_session"
        persist()
        try:
            ref = await super()._open_session(spec)
        except Exception as exc:
            if recoverable_error(exc):
                snapshot["recovery_required"] = True
                persist()
            raise
        active_driver.native_intents[self.node_id].update(stage="session_opened", session_id=ref.id)
        update(self.node_id, session_id=ref.id, native_start_at=time.time())
        return ref

    async def _submit(self, spec, ref):
        try:
            route = await self.client.rpc("session/selectModel", {"request": {"sessionId": ref.id, **MODEL}})
            selected = route.get("selected") or {}
            if selected.get("provider") != MODEL["provider"] or selected.get("model") != MODEL["model"]:
                raise RuntimeError("LIVE_MODEL_ROUTE_UNCONFIRMED")
            active_driver.native_intents[self.node_id]["stage"] = "prompt_pending"
            persist()
            accepted = await ref.raw.prompt(self._prompt_of[spec.n])
            if accepted is not True:
                raise RuntimeError("LIVE_MODEL_PROMPT_REJECTED")
            active_driver.native_intents[self.node_id]["stage"] = "submitted"
            persist()
        except Exception as exc:
            if recoverable_error(exc):
                snapshot["recovery_required"] = True
                persist()
            raise

    async def _poll(self, spec, ref, on_status, poll_s):
        def waiting():
            paused = human_inputs.waiting(manifest["run_id"], ref.id)
            current = next((n for n in snapshot["nodes"] if n["id"] == self.node_id), {})
            desired = "WAITING_INPUT" if paused else "RUNNING"
            if current.get("state") != desired:
                update(self.node_id, desired)
            else:
                persist()
            return paused

        try:
            final = await wait_native_contract(self.client, spec.workspace, spec.n, waiting=waiting,
                timeout_s=spec.timeout_s, stall_s=spec.stall_s, poll_s=poll_s, on_status=on_status)
        except Exception as exc:
            if recoverable_error(exc):
                snapshot["recovery_required"] = True
                persist()
            raise
        if final.get("stalled") or final.get("timeout"):
            return final
        return {"status": final.get("status", "BLOCKED"), "report_summary": self._summarize_task(final), "comments": final.get("comments", [])}


class Driver:
    def __init__(self, client):
        self.client = client
        self.capacity = asyncio.Semaphore(2)
        self.outputs, self.contracts, self.definitions = {}, {}, {}
        self.gateways = []
        self.parallel_pairs = {}
        self.verification_count = 0
        self.frozen_tests = None
        self.verified_candidate_digest = None
        self.control_flow = manifest.get("plan", {}).get("control_flow")
        self.reuse_nodes = {}
        if manifest.get("parent_run_id"):
            parent = LiveStore().get(manifest["owner"], manifest["parent_run_id"])
            if any(parent.get(key) != manifest.get(key) for key in ("project_id", "base_commit", "approved_plan_digest")):
                raise RuntimeError("LIVE_PARENT_PLAN_MISMATCH")
            self.reuse_nodes = completed_native_nodes(parent.get("nodes", []))
        self.document_memory = ProjectDocumentMemory(DATA / "memory.sqlite3")
        self.remote_memory = None
        self.bridge_id = str(uuid5(UUID(manifest["run_id"]), manifest["phase"]))
        planned = manifest.get("plan") or (manifest.get("workflow") or {}).get("plan") or {}
        required_paths = {path for task in planned.get("tasks", []) for path in task.get("write_paths", [])}
        self.baseline, self.tree = source_files(manifest["source_path"], manifest["base_commit"], required_paths=required_paths)
        self.files = dict(self.baseline)
        self.protected = {p for p in self.tree if self.test_path(p)}
        self.baseline_protected = {}
        self.candidate = directory.parent / "candidate"
        self.native_intents, self.gate_progress, self.pending_verify = {}, {}, None
        if recovered:
            self.files = deepcopy(recovered["files"])
            self.outputs = deepcopy(recovered["outputs"])
            self.native_intents = deepcopy(recovered.get("native_intents", {}))
            self.gate_progress = deepcopy(recovered.get("gate_progress", {}))
            self.pending_verify = deepcopy(recovered.get("pending_verify"))
            self.frozen_tests = recovered.get("frozen_tests")
            self.verified_candidate_digest = recovered.get("verified_candidate_digest")
            self.verification_count = recovered.get("verification_count", 0)
            self.candidate = directory.parent / ("candidate-recovered-" + str(manifest["recovery"]["generation"]))
        snapshot["candidate_directory"] = self.candidate.name

    def checkpoint_state(self):
        return {"snapshot": snapshot, "files": self.files, "outputs": self.outputs, "native_intents": self.native_intents,
                "gate_progress": self.gate_progress, "pending_verify": self.pending_verify, "frozen_tests": self.frozen_tests,
                "verified_candidate_digest": self.verified_candidate_digest, "verification_count": self.verification_count}

    async def restore_candidate(self):
        await asyncio.to_thread(prepare_candidate, manifest["source_path"], manifest["base_commit"], self.candidate)
        self.baseline_protected = {p: sha((self.candidate / p).read_bytes()) for p in self.protected}
        if not recovered:
            return
        allowed = {p for t in manifest["plan"]["tasks"] for p in t.get("write_paths", [])}
        for path in set(self.baseline) | set(self.files):
            if self.baseline.get(path) == self.files.get(path):
                continue
            if path not in allowed or not safe_path(path) or path in self.protected:
                raise RuntimeError("LIVE_RECOVERY_SOURCE_INVALID")
            target = self.candidate / path
            if any(p.is_symlink() for p in [target, *target.parents] if p != self.candidate.parent):
                raise RuntimeError("LIVE_RECOVERY_SOURCE_INVALID")
            if path in self.files:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(self.files[path], encoding="utf8", newline="\n")
            elif target.exists():
                target.unlink()
        if self.frozen_tests and {p: sha((self.candidate / p).read_bytes()) for p in self.frozen_tests} != self.frozen_tests:
            raise RuntimeError("LIVE_FROZEN_TESTS_CHANGED")

    async def pending_approvals(self):
        # The app's run-scoped human-input monitor owns native questions and
        # permissions; the engine must never answer them on the user's behalf.
        return []

    async def close_all(self):
        for gateway in self.gateways:
            await gateway.close_all()

    @staticmethod
    def test_path(path):
        name = Path(path).name.lower()
        return any(part in {"test", "tests", "spec", "specs", "__tests__"} for part in Path(path).parts) or name.startswith("test_") or ".test." in name or ".spec." in name or name.endswith("_test.py")

    async def bridge(self, path, body=None):
        target = path if path.startswith("/api/") else BRIDGE + path
        return await (self.client.http_get(target, timeout=45) if body is None else self.client.http_post(target, body, timeout=90))

    async def memory(self, operation, identity, revision, body=None, source=""):
        scope = manifest["scope_id"]
        context = manifest["run_id"] + ":" + manifest["phase"]
        local = self.document_memory.publish(scope, identity, revision, body, source) if operation == "publish" else self.document_memory.read(scope, identity, revision, context)
        result = local
        if self.remote_memory is not False:
            try:
                result = await self.bridge("/memory", {"scope_id": scope, "operation": operation, "document_id": identity, "revision": revision, "body": body, "source_ref": source, "caller_context_id": context})
                self.remote_memory = True
            except Exception:
                self.remote_memory = False
        result = {**result, "harness_state": "AVAILABLE" if self.remote_memory else "UNAVAILABLE"}
        snapshot["memory"].append({k: v for k, v in result.items() if k != "body"})
        persist()
        return result

    def context_inputs(self, task, *, baseline=False):
        files = self.baseline if baseline else self.files
        context = "# Yêu cầu\n" + manifest["requirement"] + "\n# Source\n" + manifest["repository"] + "@" + manifest["base_commit"]
        context += "\n# Spec đóng băng\n" + "\n\n".join(d["body"] for d in snapshot["documents"])
        context += "\n# Task\n" + json.dumps(task, ensure_ascii=False)
        if manifest.get("workflow"):
            context += "\n# Workflow do người dùng thiết kế trên canvas, giữ nguyên phạm vi và tiêu chí\n" + json.dumps(manifest["workflow"]["plan"], ensure_ascii=False)
        if manifest.get("plan"):
            context += "\n# Kế hoạch đã duyệt: file, giao diện phối hợp và lệnh kiểm chứng\n" + json.dumps(manifest["plan"], ensure_ascii=False)
        if manifest.get("environment"):
            from langflow.adlc.project_environment import public_environment
            context += "\n# Môi trường đã đóng băng; file được sửa vẫn dùng đường dẫn repo chính\n" + json.dumps(public_environment(manifest["environment"]), ensure_ascii=False)
        result = {**context_parts(context), "source-tree.json": json.dumps(self.tree[:4000], ensure_ascii=False)}
        file_sets = [("source", files)]
        if task.get("kind") == "review":
            receipt = snapshot.get("verification") or {}
            changed = sorted(p for p in set(self.baseline) | set(self.files) if self.baseline.get(p) != self.files.get(p))
            file_sets.append(("baseline-source", {p: self.baseline[p] for p in changed if p in self.baseline}))
            evidence = {"base_commit": manifest["base_commit"], "changed_paths": changed[:400], "changed_count": len(changed),
                        "unchanged_original_count": sum(self.files.get(p) == body for p, body in self.baseline.items()),
                        "verification": {k: receipt.get(k) for k in ["state", "passed", "protected_intact", "binding_verified", "source_sha256", "plan_digest", "browser_backend"]},
                        "checks": [{"id": check.get("id"), "label": str(check.get("label", ""))[:300], "passed": check.get("passed"),
                                    "exit_code": check.get("exit_code"), "stdout": str(check.get("stdout", ""))[:1000], "stderr": str(check.get("stderr", ""))[:2000]}
                                   for check in receipt.get("checks", [])],
                        "browser_checks": [{"id": check.get("id"), "label": str(check.get("label", ""))[:300], "passed": check.get("passed"),
                                            "error": str(check.get("error", ""))[:1000]} for check in receipt.get("browser_checks", [])]}
            result["review-evidence.json"] = json.dumps(evidence, ensure_ascii=False)
        planned = manifest.get("plan") or (manifest.get("workflow") or {}).get("plan") or {}
        required = {path for item in planned.get("tasks", []) for path in item.get("write_paths", [])}
        required.update(path for path in self.files if self.baseline.get(path) != self.files[path])
        return pack_sources(result, file_sets, required_paths=required)

    async def native(self, task, instruction, inputs=None):
        identity = task["id"]
        if identity in self.native_intents:
            return await self.resume_native(task, self.native_intents[identity])
        update(identity, "WAITING_SLOT", title=task["title"], role=task.get("role", "coder"), depends_on=task.get("depends_on", []),
               original_id=task.get("original_id", identity), iteration=task.get("iteration", 0), repair=identity.startswith("FIX") or (task.get("kind") == "implement" and task.get("iteration", 0) > 0))
        async with self.capacity:
            update(identity, "RUNNING", started_at=time.time())
            prepared = await self.bridge("/runs", {"run_id": self.bridge_id, "scope_id": manifest["scope_id"], "nodes": [{"id": identity, "inputs": inputs or self.context_inputs(task)}]})
            binding = next(n for n in prepared["nodes"] if n["id"] == identity)
            old = None if "iteration" in task else self.reuse_nodes.get(identity)
            if old:
                old_bridge = str(uuid5(UUID(manifest["parent_run_id"]), manifest["phase"]))
                old_workspace = str(PurePosixPath(binding["workspace"]).parent.parent / old_bridge / identity)
                contract = await self.client.get_task(old_workspace, "1")
                if contract.get("status") in {"DONE", "DONE_WITH_CONCERNS"}:
                    artifact = await self.bridge("/runs/" + old_bridge + "?scope_id=" + manifest["scope_id"] + "&node_id=" + identity)
                    if old.get("artifact_digest") and artifact["sha256"] != old["artifact_digest"]:
                        raise RuntimeError("LIVE_PARENT_ARTIFACT_CHANGED")
                    ended = old.get("native_end_at") or datetime.fromisoformat(contract["updatedAt"].replace("Z", "+00:00")).timestamp()
                    update(identity, session_id=old["session_id"], native_start_at=old.get("native_start_at"), native_end_at=ended, native_status=contract["status"], artifact_digest=artifact["sha256"], reused_from=manifest["parent_run_id"])
                    self.contracts[identity] = SimpleNamespace(status=contract["status"])
                    return artifact["artifact"]
            self.native_intents[identity] = {"stage": "prepared", "workspace": binding["workspace"], "inputs": binding["inputs"]}
            persist()
            gateway = NativeGateway(os.environ["DSH_URL"], os.environ["DSH_TOKEN"], root_workspace=binding["workspace"], node_id=identity, provider=MODEL["provider"], model=MODEL["model"], timeout_s=1200, stall_s=1200, max_rearms=0, workflow_name="pokedev-project", run_tag=manifest["run_id"][-8:])
            gateway.client.retry = RetryConfig(max_attempts=1)
            self.gateways.append(gateway)
            common = "\nĐọc inputs/context.md, mọi context-extra-*.md nếu có, rồi tra inputs/source-index.json để đọc đúng file source-*-file-*.txt cần thiết; không cần đọc toàn bộ repo. Index ghi đường dẫn repo, tên input và SHA của toàn bộ nội dung file. Đọc bản gốc và giữ nguyên phần ngoài yêu cầu; có thể sao chép source sang scratch trong outputs rồi dùng script tạo JSON từ file để không phải viết lại cả file dài bằng một lần sinh. Chỉ làm trong workspace task đã cấp. Không đọc secret, không sửa inputs, không subagent, không commit/push. Viết JSON thuần đúng schema vào outputs/result.json bằng tool filesystem rồi hoàn tất contract TaskLoop. Không tự nhận kết quả test là PASS; runner độc lập sẽ chạy."
            common += " Nếu cần quyết định hoặc thông tin từ người dùng, gọi ask_user_question và chờ phản hồi qua UI; không tự đoán, không chỉ hỏi trong tin nhắn kết thúc. Phản hồi không thay đổi phạm vi file hay kế hoạch đã duyệt."
            try:
                contract = await gateway.run_contract_task(name=identity, n="1", role=task.get("role", "coder"), brief=instruction + common, model=MODEL["model"])
                self.contracts[identity] = contract
                if contract.status not in {"DONE", "DONE_WITH_CONCERNS"}:
                    if snapshot.get("recovery_required"):
                        raise RuntimeError("LIVE_RECOVERY_NATIVE_NOT_FINISHED")
                    detail = " ".join(str(e.get("text", "")) for e in getattr(contract, "errors", []))
                    code = re.search(r"\bLIVE_[A-Z_]+\b", detail)
                    raise RuntimeError(code.group() if code else "LIVE_NATIVE_TASK_INCOMPLETE")
                artifact = await self.bridge("/runs/" + self.bridge_id + "?scope_id=" + manifest["scope_id"] + "&node_id=" + identity)
                update(identity, native_end_at=time.time(), native_status=contract.status, artifact_digest=artifact["sha256"])
                return artifact["artifact"]
            finally:
                await gateway.close_all()

    async def resume_native(self, task, intent):
        """Adopt the recorded contract/session; recovery never resends an accepted prompt."""
        identity = task["id"]
        receipt = await self.bridge("/runs/" + self.bridge_id + "?scope_id=" + manifest["scope_id"])
        binding = next((node for node in receipt["nodes"] if node["id"] == identity), None)
        if not binding or binding["workspace"] != intent["workspace"] or binding["inputs"] != intent["inputs"]:
            raise RuntimeError("LIVE_RECOVERY_NATIVE_BINDING_CHANGED")
        if not intent.get("session_id") or intent.get("stage") not in {"prompt_pending", "submitted"}:
            raise RuntimeError("LIVE_RECOVERY_NATIVE_ACCEPTANCE_UNKNOWN")
        node = next(n for n in snapshot["nodes"] if n["id"] == identity)
        if node.get("session_id") != intent["session_id"]:
            raise RuntimeError("LIVE_RECOVERY_NATIVE_BINDING_CHANGED")
        update(identity, "RUNNING", recovered_session=True, error_code=None)
        def waiting():
            paused = human_inputs.waiting(manifest["run_id"], intent["session_id"])
            update(identity, "WAITING_INPUT" if paused else "RUNNING")
            return paused
        contract = await wait_native_contract(self.client, intent["workspace"], "1", waiting=waiting, timeout_s=1200, stall_s=1200, poll_s=2)
        if contract.get("status") not in {"DONE", "DONE_WITH_CONCERNS"} or contract.get("timeout") or contract.get("stalled"):
            raise RuntimeError("LIVE_RECOVERY_NATIVE_NOT_FINISHED")
        artifact = await self.bridge("/runs/" + self.bridge_id + "?scope_id=" + manifest["scope_id"] + "&node_id=" + identity)
        if node.get("artifact_digest") and node["artifact_digest"] != artifact["sha256"]:
            raise RuntimeError("LIVE_RECOVERY_NATIVE_BINDING_CHANGED")
        self.contracts[identity] = SimpleNamespace(status=contract["status"])
        update(identity, native_end_at=node.get("native_end_at") or time.time(), native_status=contract["status"], artifact_digest=artifact["sha256"])
        return artifact["artifact"]

    async def planning(self, task):
        if task["id"] == "P01":
            revision = "req-" + manifest["run_id"][:16]
            await self.memory("publish", "BUSINESS", revision, manifest["requirement"], manifest["repository"] + "@" + manifest["base_commit"])
            context = await self.memory("read", "BUSINESS", revision)
            inputs = self.context_inputs(task, baseline=True)
            inputs["context.md"] += "\n# Memory nghiệp vụ\n" + context["body"]
            for identity in ("SPEC", "DESIGN", "TESTS"):
                previous = self.document_memory.latest(manifest["scope_id"], identity, manifest["run_id"] + ":prior", verified_only=True)
                if previous:
                    inputs["context.md"] += "\n# Context vòng trước, candidate chưa merge\n" + previous["body"][:12000]
            result = await self.native(task, 'Bạn là BA. Dựa trên yêu cầu và source thực, tạo 3 tài liệu SPEC (phân tích yêu cầu, AC cụ thể), DESIGN (thiết kế và phạm vi file), TESTS (kịch bản test theo AC). Trả {"documents":[{"id":"SPEC","title":"Phân tích yêu cầu","body":"Markdown đã điền"}, {"id":"DESIGN","title":"Thiết kế chi tiết","body":"..."},{"id":"TESTS","title":"Kế hoạch kiểm thử","body":"..."}]}. Mỗi body 600–12000 ký tự, có nguồn repo/commit và phần chưa rõ. Không bịa tên API, bảng CSDL hoặc kết quả chạy. Bám yêu cầu mới, nội dung Memory cũ chỉ là context. Không dùng fixture TNQD nếu không thuộc repo/yêu cầu. Với repo mới, ưu tiên web HTML/CSS/JS thuần, chạy offline và test Python unittest nếu yêu cầu không chỉ định framework.', inputs)
            documents = result.get("documents", [])
            if {d.get("id") for d in documents} != {"SPEC", "DESIGN", "TESTS"} or len(documents) != 3 or any(not 600 <= len(d.get("body", "")) <= 12000 for d in documents):
                raise RuntimeError("LIVE_SPEC_DOCUMENT_INVALID")
            for document in documents:
                document.update(revision="spec-" + manifest["run_id"][:16], sha256=sha(document["body"]))
                await self.memory("publish", document["id"], document["revision"], document["body"], "BA:" + manifest["run_id"])
            snapshot["documents"] = documents
            return {"summary": "BA đã tạo ba tài liệu từ yêu cầu, Memory và source thực."}
        prompt = '''Bạn là Planner. Phân rã spec thành DAG công việc cụ thể trên repo hiện tại. Không cố định 17 task, không dùng mục tiêu hoặc file TNQD nếu yêu cầu không có.
Trả JSON {"title":"...","summary":"...","tasks":[{"id":"T01","title":"mô tả cụ thể ít nhất 12 ký tự","kind":"implement|test|review","role":"coder|tester|reviewer","depends_on":[],"write_paths":["đường dẫn file chính xác"],"steps":["các bước cụ thể"],"acceptance":["tiêu chí kiểm chứng"]}],"commands":[{"label":"cài dependencies / test / build","argv":["python","-m","unittest","discover","-s","tests","-v"],"timeout":180}],"preview":{"path":"."},"browser_checks":[{"label":"kiểm tra cụ thể theo AC","steps":[{"action":"goto","path":"/"},{"action":"text","text":"nội dung cần thấy"}]}]}.
2–20 task, thường 4–8 cho yêu cầu nhỏ; tách Developer/Tester thành nhánh độc lập nếu có thể. Mỗi task ghi đủ file, bước và tiêu chí. Task sửa cùng file phải có dependency. Tester chỉ viết file tests mới, không sửa source ứng dụng hay tests đã có. Developer không sửa tests. Review chỉ đọc. Dùng đúng đường dẫn repo, không wildcard; không task ID bắt đầu SYS_.
Commands là argv chạy trong Sandbox Linux, không shell interpolation. Cần lệnh chạy test thật, không chỉ py_compile/echo. Nếu phải cài dependencies hoặc build, thêm argv tương ứng. Không giả định dependency đã có. Repo web mới không chỉ định stack: ưu tiên HTML/CSS/JS thuần + Python unittest builtin, không npm nếu không cần. Preview static dùng {"path":"thư mục chứa index.html"}; backend dùng {"argv":["python","app.py"]} và PORT=8088/HOST=0.0.0.0; CLI dùng null.
Browser actions chỉ goto(path tương đối), text(text), visible(selector), fill(selector,value), click(selector); mỗi check bắt đầu từ trang /. Không phụ thuộc mạng ngoài Sandbox, không dùng CDN. Repo thiếu workspace, dependency hay thông tin phải ghi vào tài liệu; không thay repo bằng app minh họa khác.'''
        prompt += "\nCommand limits: at most 8 commands, 40 argv entries each, 500 characters per entry, and 5-600 seconds per timeout. Use null preview and no browser checks for API-only verification without a configured preview."
        # A selected canvas is executable input, not advisory text for another planner.
        # Freeze and run its exact tasks, edges, file grants and checks.
        result = await planning_plan(manifest.get("workflow"), lambda: self.native(task, prompt))
        snapshot["plan"] = apply_environment(result, manifest.get("environment"))
        return {"summary": "Đã dùng đúng phiên bản workflow trên canvas; giữ nguyên DAG, phạm vi file và lệnh kiểm chứng." if manifest.get("workflow") else "Planner đã tạo DAG, phạm vi sửa và lệnh kiểm chứng theo yêu cầu.", "task_count": len(result["tasks"])}

    def apply(self, task, result):
        proposed = result.get("files", {})
        if not isinstance(proposed, dict) or len(proposed) > 40:
            raise RuntimeError("LIVE_CODE_PROPOSAL_INVALID")
        if task["kind"] != "review" and not proposed:
            raise RuntimeError("LIVE_CODE_CHANGE_REQUIRED")
        for path, body in proposed.items():
            if not safe_path(path) or path not in task.get("write_paths", []) or path in self.protected:
                raise RuntimeError("LIVE_WRITE_SCOPE_DENIED")
            if task["kind"] == "implement" and self.test_path(path):
                raise RuntimeError("LIVE_PROTECTED_TEST_WRITE_DENIED")
            if task["kind"] == "test" and not self.test_path(path):
                raise RuntimeError("LIVE_TESTER_APPLICATION_WRITE_DENIED")
            if body is not None and (not isinstance(body, str) or len(body.encode()) > 160000):
                raise RuntimeError("LIVE_FILE_LIMIT")
            original = self.candidate / path
            if any(p.is_symlink() for p in (original, *original.parents) if p != self.candidate.parent):
                raise RuntimeError("LIVE_PATH_ESCAPE")
            target = original.resolve()
            if not target.is_relative_to(self.candidate.resolve()):
                raise RuntimeError("LIVE_PATH_ESCAPE")
            if path in self.tree and path not in self.baseline:
                raise RuntimeError("LIVE_SOURCE_CONTEXT_MISSING")
            if body is None:
                if target.exists(): target.unlink()
                self.files.pop(path, None)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(body, encoding="utf8", newline="\n"); self.files[path] = body
        self.verified_candidate_digest = None
        return {"summary": result.get("summary", task["title"]), "changed_files": list(proposed)}

    def candidate_digest(self):
        return digest({p: sha((self.candidate / p).read_bytes()) for p in sorted(set(self.tree) | set(self.files)) if safe_path(p) and (self.candidate / p).is_file() and not (self.candidate / p).is_symlink()})

    def review_evidence(self):
        changed = sorted(p for p in set(self.baseline) | set(self.files) if self.baseline.get(p) != self.files.get(p))
        snapshot["changed_files"] = changed
        snapshot["file_hashes"] = {p: sha((self.candidate / p).read_bytes()) if (self.candidate / p).exists() else None for p in changed}
        snapshot["diff"] = "\n".join("".join(difflib.unified_diff(self.baseline.get(p, "").splitlines(keepends=True), self.files.get(p, "").splitlines(keepends=True), fromfile="a/" + p, tofile="b/" + p)) for p in changed)
        persist()
        return changed

    async def human_gate(self, task, round_number, *, exhausted=False):
        self.review_evidence()
        current = self.candidate_digest()
        verified = self.verified_candidate_digest == current and snapshot.get("verification", {}).get("passed") is True
        update(task["id"], "WAITING_INPUT", title=task["title"], role="human", depends_on=task.get("depends_on", []), candidate_digest=current,
               control="gate", original_id=task.get("original_id", task["id"]), iteration=round_number, started_at=time.time())
        question = human_inputs.open_gate(manifest, task, current, round_number, exhausted=exhausted, can_approve=verified)
        while question["status"] != "ANSWERED":
            await asyncio.sleep(2); persist()
            question = human_inputs.get(manifest["owner"], manifest["run_id"], question["request_id"])
        decision = question["gate_decision"]
        if decision == "stopped":
            raise RuntimeError("LIVE_REVIEW_STOPPED")
        if decision == "approved" and (not verified or self.candidate_digest() != current):
            raise RuntimeError("LIVE_REVIEW_SOURCE_CHANGED")
        if decision == "approved":
            snapshot.setdefault("control_receipts", []).append({"gate": task.get("original_id", task["id"]), "reviewer": "human", "request_id": question["request_id"], "approved": True, "source_digest": current, "plan_digest": manifest["approved_plan_digest"]})
        result = {"approved": decision == "approved", "port": decision, "source_digest": current, "feedback": question.get("feedback", ""), "summary": question.get("feedback") or "Người dùng đã duyệt kết quả", "status": "APPROVED" if decision == "approved" else "CHANGES_REQUESTED"}
        update(task["id"], "DONE", completed_at=time.time(), outcome=result["status"], summary=result["summary"])
        return result

    def visit_task(self, task, round_number):
        identity = task.get("original_id", task["id"])
        return {**task, "id": identity[:18]+"__R"+str(round_number)+"_"+sha(identity)[:6], "original_id": identity, "iteration": round_number}

    async def review_gate(self, task):
        loop = next((item for item in self.control_flow["loops"] if item["gate"] == task["id"]), None)
        rounds = loop["max_rounds"] if loop else 0
        if not hasattr(self, "gate_progress"):
            self.gate_progress = {}
        progress = self.gate_progress.setdefault(task["id"], {"number": 0, "stage": "review", "repair_index": 0})
        while progress["number"] <= rounds:
            number = progress["number"]
            if progress["stage"] == "approved":
                if progress["result"]["source_digest"] != self.candidate_digest():
                    raise RuntimeError("LIVE_REVIEW_SOURCE_CHANGED")
                return progress["result"]
            if progress["stage"] == "repair":
                for index in range(progress["repair_index"], len(loop["nodes"])):
                    original = self.definitions[loop["nodes"][index]]
                    if original["kind"] != "test":
                        visit = self.visit_task(original, number+1)
                        visit["feedback"] = progress["feedback"]
                        self.definitions[visit["id"]] = visit
                        await self.execute_task(visit)
                        self.outputs[original["id"]] = self.outputs[visit["id"]]
                        latest = next(n for n in snapshot["nodes"] if n["id"] == visit["id"])
                        update(original["id"], latest["state"], outcome=self.outputs[original["id"]].get("status", "DONE"), port=self.outputs[original["id"]].get("port"), latest_visit=visit["id"])
                    progress["repair_index"] = index + 1
                    persist()
                progress.update(number=number+1, stage="review", repair_index=0)
                persist()
                continue
            if progress["stage"] == "escalation":
                escalation = self.visit_task(task, number+1)
                self.definitions[escalation["id"]] = escalation
                result = await self.human_gate(escalation, number+1, exhausted=True)
                progress.update(stage="approved", result=result)
                persist()
                return result
            visit = self.visit_task(task, number)
            self.definitions[visit["id"]] = visit
            verified = self.verified_candidate_digest == self.candidate_digest() and snapshot.get("verification", {}).get("passed") is True
            if task["control"]["reviewer"] == "human":
                result = await self.human_gate(visit, number, exhausted=not loop)
            else:
                result = await self.native(visit, 'Review độc lập source và bằng chứng kiểm thử thực theo tiêu chí. Chỉ đọc. Trả {"approved":true|false,"summary":"lý do và thay đổi cần thiết"}. Chỉ approved khi bằng chứng kiểm thử đạt cho đúng source hiện tại.')
                if type(result.get("approved")) is not bool or not isinstance(result.get("summary"), str):
                    raise RuntimeError("LIVE_REVIEW_VERDICT_INVALID")
                result["approved"] = result["approved"] and verified
                result["source_digest"] = self.candidate_digest()
                result.update(port="approved" if result["approved"] else "changes_requested", status="APPROVED" if result["approved"] else "CHANGES_REQUESTED")
                result["feedback"] = result["summary"] if verified else "Cần xử lý các lỗi kiểm thử thực trước khi được duyệt. " + result["summary"]
                update(visit["id"], "DONE", completed_at=time.time(), outcome=result["status"], control="gate", original_id=task["id"], iteration=number, summary=result["summary"])
                if result["approved"]:
                    native_node = next(n for n in snapshot["nodes"] if n["id"] == visit["id"])
                    snapshot.setdefault("control_receipts", []).append({"gate": task["id"], "reviewer": "agent", "session_id": native_node["session_id"], "approved": True, "source_digest": self.candidate_digest(), "plan_digest": manifest["approved_plan_digest"]})
            snapshot["events"].append({"node": task["id"], "state": result["status"], "iteration": number, "at": time.time()}); persist()
            if result["approved"]:
                progress.update(stage="approved", result=result)
                persist()
                return result
            if number == rounds:
                progress["stage"] = "escalation"
            else:
                progress.update(stage="repair", repair_index=0, feedback=result.get("feedback") or result.get("summary", ""))
            persist()

    async def control(self, task):
        kind = task["control"]["type"]
        if kind == "verify":
            return await self.verification(task, report_only=True, max_repairs=0)
        if kind == "condition":
            original = task.get("original_id", task["id"])
            source = next(edge["source"] for edge in self.control_flow["edges"] if edge["target"] == original and not edge["feedback"])
            return condition_result(task["control"]["predicate"], self.outputs[source])
        return await self.review_gate(task)

    async def implementation(self, task):
        if task["kind"] == "review":
            if task.get("verification_required") and not all(snapshot.get("verification", {}).get(k) is True for k in ["passed", "protected_intact", "binding_verified"]):
                raise RuntimeError("LIVE_REVIEW_VERIFICATION_REQUIRED")
            result = await self.native(task, 'Review source hiện tại theo spec. Chỉ đọc. Tra inputs/source-index.json để đọc đúng các file source và baseline-source được chỉ ra; đối chiếu bản gốc của file thay đổi với bản mới và review-evidence.json. Dùng receipt kiểm thử/browser thực của runner độc lập nếu đã có; không yêu cầu tự chạy lại trong workspace chỉ chứa snapshot, và không nhận mình là người đã chạy các test đó. Trả {"approved":true|false,"summary":"kết luận kèm phạm vi và điểm chưa xác nhận"}. Không tự tuyên bố test đã đạt khi chưa có receipt.')
            if not result.get("approved"):
                raise RuntimeError("LIVE_REVIEW_CHANGES_REQUIRED")
            return result
        inputs = self.context_inputs(task, baseline=task["kind"] == "test")
        if task.get("feedback"):
            inputs["review-feedback.md"] = task["feedback"]
        instruction = 'Thực hiện đúng task theo spec. Trả {"files":{"đường/dẫn/file":"toàn bộ nội dung UTF-8 thay thế"},"summary":"đã sửa gì"}. Chỉ file trong write_paths; không sửa test có sẵn. Có thể thêm file mới hoặc null để xóa file trong phạm vi. Không tự chạy hay báo đạt verification.'
        if task["kind"] == "test":
            instruction += " Bạn là Tester độc lập, chỉ nhận source baseline và spec. Viết tests thực chạy được theo commands đã duyệt, dùng expected result từ nghiệp vụ; không bỏ qua test, không tự sửa app để test xanh."
        return self.apply(task, await self.native(task, instruction, inputs))

    def package(self):
        paths = set(git(self.candidate, "ls-files", "-z", raw=True).strip("\0").split("\0")) | set(self.files)
        return archive_sources(self.candidate, paths, manifest.get("environment"), directory / "candidate.zip")

    async def verification(self, task, *, report_only=False, max_repairs=None):
        if self.control_flow and not report_only and self.verified_candidate_digest == self.candidate_digest() and snapshot.get("verification", {}).get("passed") is True:
            return {"passed": True, "status": "DONE", "summary": "Dùng lại bằng chứng đã kiểm chứng cho đúng source hiện tại."}
        if {p: sha((self.candidate / p).read_bytes()) for p in self.protected} != self.baseline_protected:
            raise RuntimeError("LIVE_BASELINE_TESTS_CHANGED")
        protected = sorted(self.protected | {p for t in manifest["plan"]["tasks"] if t["kind"] == "test" for p in t.get("write_paths", [])})
        frozen = {p: sha((self.candidate / p).read_bytes()) for p in protected}
        if self.frozen_tests is None:
            self.frozen_tests = frozen
        elif frozen != self.frozen_tests:
            raise RuntimeError("LIVE_FROZEN_TESTS_CHANGED")
        snapshot["test_suite_sha256"] = digest(frozen)
        repairs = (0 if self.control_flow else 2) if max_repairs is None else max_repairs
        for retry in range(repairs + 1):
            raw = await asyncio.to_thread(self.package)
            source_sha = sha(raw)
            pending = getattr(self, "pending_verify", None)
            if pending:
                if pending["source_sha256"] != source_sha or pending["task"] != task["id"]:
                    raise RuntimeError("LIVE_RECOVERY_VERIFICATION_CHANGED")
                attempt, job_id = pending["attempt"], pending["job_id"]
            else:
                attempt = self.verification_count; self.verification_count += 1
                job_id = str(uuid5(UUID(manifest["run_id"]), "verify-" + str(attempt)))
                self.pending_verify = {"task": task["id"], "attempt": attempt, "job_id": job_id, "source_sha256": source_sha}
                persist()
            command = {"job_id": job_id, "scope_id": manifest["scope_id"], "source_sha256": source_sha, "plan_digest": manifest["approved_plan_digest"], "archive_base64": base64.b64encode(raw).decode(), "commands": manifest["plan"]["commands"], "protected_paths": [workspace_path(p, manifest.get("environment")) for p in protected], "preview": manifest["plan"].get("preview"), "browser_checks": manifest["plan"].get("browser_checks", [])}
            receipt = await self.bridge(JOBS, command)
            for _ in range(900):
                if receipt["state"] in {"SUCCEEDED", "FAILED", "UNCONFIRMED"}: break
                await asyncio.sleep(2)
                receipt = await self.bridge(JOBS + "/" + job_id + "?scope_id=" + manifest["scope_id"])
                snapshot["checks"] = [g for g in snapshot["checks"] if g["id"] != "verify-" + str(attempt)] + [{"id": "verify-" + str(attempt), "title": "Sandbox · lần " + str(attempt + 1), "tests": receipt.get("checks", []) + receipt.get("browser_checks", [])}]
                persist()
            if receipt.get("source_sha256") != source_sha or receipt.get("plan_digest") != manifest["approved_plan_digest"]:
                raise RuntimeError("LIVE_SANDBOX_RECEIPT_MISMATCH")
            snapshot["checks"] = [g for g in snapshot["checks"] if g["id"] != "verify-" + str(attempt)] + [{"id": "verify-" + str(attempt), "title": "Sandbox · lần " + str(attempt + 1), "tests": receipt.get("checks", []) + receipt.get("browser_checks", [])}]
            snapshot["verification"] = receipt
            snapshot["source_sha256"] = source_sha
            if receipt.get("state") == "UNCONFIRMED":
                snapshot["recovery_required"] = True
                persist()
                raise RuntimeError("LIVE_RECOVERY_VERIFICATION_UNCONFIRMED")
            self.pending_verify = None
            if receipt.get("preview_ready") and receipt.get("binding_verified"):
                snapshot["preview"] = {"state": "LIVE", "job_id": job_id, "expires_at": receipt["expires_at"], "binding_verified": True, "source_sha256": source_sha}
            persist()
            if {p: sha((self.candidate / p).read_bytes()) for p in protected} != frozen:
                raise RuntimeError("LIVE_FROZEN_TESTS_CHANGED")
            if receipt.get("state") == "SUCCEEDED" and receipt.get("passed") is True and receipt.get("protected_intact") and receipt.get("binding_verified"):
                self.verified_candidate_digest = self.candidate_digest()
                persist()
                return {"passed": True, "status": "DONE", "summary": "Kiểm thử và build đã chạy thật trong Sandbox; bộ test được giữ nguyên."}
            if report_only and receipt.get("state") == "FAILED" and receipt.get("error_code") in {"PROJECT_CHECKS_FAILED", "PROJECT_BROWSER_CHECKS_FAILED"}:
                self.verified_candidate_digest = None
                return {"passed": False, "status": "FAILED", "summary": "Kiểm thử chưa đạt; chuyển theo điều kiện và cổng review đã duyệt."}
            if retry == repairs or receipt.get("state") == "UNCONFIRMED" or receipt.get("error_code") not in {"PROJECT_CHECKS_FAILED", "PROJECT_BROWSER_CHECKS_FAILED"}:
                raise RuntimeError(receipt.get("error_code") or "LIVE_VERIFICATION_FAILED")
            repair = {"id": "FIX" + str(attempt + 1), "title": "Sửa source theo lỗi Sandbox, giữ nguyên toàn bộ test", "kind": "implement", "role": "coder", "depends_on": [task["id"]], "write_paths": sorted({p for t in manifest["plan"]["tasks"] if t["kind"] == "implement" for p in t.get("write_paths", [])}), "acceptance": ["Bộ test đã khóa phải giữ nguyên"], "steps": ["Đọc log thực", "Sửa nguyên nhân trong source", "Để runner kiểm tra lại"]}
            inputs = self.context_inputs(repair); inputs["findings.json"] = json.dumps({k: v for k, v in receipt.items() if k in {"checks", "browser_checks", "error_code"}}, ensure_ascii=False)[:150000]
            result = await self.native(repair, 'Sửa các lỗi trong inputs/findings.json bằng code ứng dụng. Không sửa hoặc nới test/expected result, commands hay quyền. Trả {"files":{"path":"nội dung đầy đủ"},"summary":"nguyên nhân và thay đổi"}.', inputs)
            self.apply(repair, result)
            update(repair["id"], "DONE", completed_at=time.time(), summary=result.get("summary", "Đã sửa theo phản hồi kiểm thử"))

    async def handover(self):
        changed = self.review_evidence()
        if not changed:
            raise RuntimeError("LIVE_NO_PRODUCT_CHANGES")
        for document in snapshot["documents"]:
            if document.get("revision") == "verified-" + manifest["run_id"][:16]:
                continue
            document["previous_body"] = document["body"]
            document["body"] += "\n\n## Kết quả phát triển đã kiểm chứng\nRun " + manifest["run_id"] + "\nSource SHA " + snapshot["source_sha256"] + "\nFile thay đổi:\n" + "\n".join("- " + p for p in sorted(changed)) + "\nKiểm thử thực: " + json.dumps(snapshot["checks"], ensure_ascii=False)[:10000]
            document.update(revision="verified-" + manifest["run_id"][:16], sha256=sha(document["body"]))
            await self.memory("publish", document["id"], document["revision"], document["body"], "verified-workloop:" + manifest["run_id"])
            receipt = self.document_memory.read(manifest["scope_id"], document["id"], document["revision"], "new-agent-context:" + str(uuid4()))
            snapshot["memory"].append({k: v for k, v in receipt.items() if k != "body"})
        return {"summary": "Đã bàn giao diff, kết quả Sandbox và tài liệu có phiên bản; chờ người dùng chọn xuất nhánh Gitea."}

    async def execute_task(self, task):
        identity = task["id"]
        if identity in self.outputs:
            self.contracts[identity] = SimpleNamespace(status="DONE")
            return Data(data={"task": identity, "status": "DONE", "recovered": True})
        try:
            if any(p not in self.outputs for p in task.get("depends_on", [])):
                raise RuntimeError("LIVE_UPSTREAM_ARTIFACT_MISSING")
            if self.control_flow and not identity.startswith("SYS_") and not active_inputs(task, self.control_flow["edges"], self.outputs):
                self.outputs[identity] = {"skipped": True, "status": "SKIPPED", "summary": "Nhánh không được chọn"}
                self.contracts[identity] = SimpleNamespace(status="DONE")
                update(identity, "SKIPPED", title=task["title"], completed_at=time.time(), original_id=task.get("original_id", identity))
                return Data(data={"task": identity, "status": "DONE", "skipped": True})
            if identity.startswith("SYS_"):
                update(identity, "RUNNING", title=task["title"], role="runner", started_at=time.time(), depends_on=task["depends_on"])
                result = await (self.verification(task) if identity == "SYS_VERIFY" else self.handover())
            elif manifest["phase"] == "planning":
                result = await self.planning(task)
            elif task.get("control"):
                update(identity, "RUNNING", title=task["title"], role="runner", started_at=time.time(), control=task["control"]["type"], original_id=task.get("original_id", identity))
                result = await self.control(task)
            else:
                result = await self.implementation(task)
            result.setdefault("status", "DONE")
            self.outputs[identity] = result
            self.contracts.setdefault(identity, SimpleNamespace(status="DONE"))
            (directory / (identity + ".artifact.json")).write_text(json.dumps(result, ensure_ascii=False), encoding="utf8")
            update(identity, "DONE", completed_at=time.time(), summary=result.get("summary", task["title"]), outcome=result.get("status", "DONE"), port=result.get("port"), approved=result.get("approved"), source_digest=result.get("source_digest"))
            return Data(data={"task": identity, "status": "DONE"})
        except Exception as error:
            from langflow.adlc.project_recovery import recoverable_error
            if recoverable_error(error) or str(error).startswith(("LIVE_RECOVERY_NATIVE_NOT_FINISHED", "LIVE_RECOVERY_NATIVE_ACCEPTANCE_UNKNOWN", "LIVE_RECOVERY_VERIFICATION_UNCONFIRMED")):
                snapshot["recovery_required"] = True
            code = str(error) if str(error).startswith(("LIVE_", "PROJECT_")) else "LIVE_TASK_FAILED_" + type(error).__name__
            update(identity, "FAILED", completed_at=time.time(), error_code=code)
            for child in self.definitions.values():
                if identity in child.get("depends_on", []): update(child["id"], "BLOCKED", depends_on=child["depends_on"])
            raise

    async def capture_usage(self):
        from langflow.adlc.project_metrics import measured_usage
        identities = {n["session_id"] for n in snapshot["nodes"] if n.get("session_id") and not n.get("reused_from")}
        if not identities:
            return
        try:
            response = await self.client.rpc("session/list", {"_request": {"sessionIds": sorted(identities)}})
            for item in response.get("items", []):
                if item.get("sessionId") not in identities:
                    continue
                usage = measured_usage(item)
                if usage is not None:
                    for node in snapshot["nodes"]:
                        if node.get("session_id") == item["sessionId"]:
                            node["usage"] = {"tokens": usage, "source": "harness_session_projection", "collected_at": datetime.now().astimezone().isoformat()}
            persist()
        except Exception:
            pass  # Missing telemetry must never become a fake zero or fail the work.

    async def monitor(self):
        clock = time.monotonic()
        snapshot.setdefault("active_seconds", float((manifest.get("auto_timing") or {}).get("active_seconds", 0)))
        while True:
            stamp = time.monotonic()
            if not human_inputs.waiting(manifest["run_id"]):
                snapshot["active_seconds"] += stamp - clock
            clock = stamp
            persist()
            running = [n for n in snapshot["nodes"] if n.get("session_id") and n["state"] == "RUNNING"]
            if len(running) >= 2:
                try:
                    async def activity(node):
                        events = await self.client.session(node["session_id"]).history(max_messages=1)
                        if not events:
                            return False
                        last = events[-1]; stamp = last.get("time", 0)
                        stamp = stamp / 1000 if stamp > 100000000000 else stamp
                        end = max((i for i, e in enumerate(events) if e.get("type") in {"turn/end", "turn/error"}), default=-1)
                        return 0 <= time.time() - stamp <= 45 and any(e.get("type") in {"turn/start", "step/start", "tool/call", "tool/result"} for e in events[end + 1:])
                    flags = await asyncio.wait_for(asyncio.gather(*(activity(n) for n in running)), timeout=25)
                    active = [n for n, observed in zip(running, flags) if observed]
                    if len(active) >= 2:
                        a, b = active[:2]
                        key = tuple(sorted([a["id"], b["id"]])); stamp = time.time()
                        proof = self.parallel_pairs.setdefault(key, {"tasks": list(key), "first_observed_at": stamp, "samples": 0, "source": "scoped-session-events"})
                        proof.update(last_observed_at=stamp, samples=proof["samples"] + 1, overlap_seconds=stamp - proof["first_observed_at"], verified=proof["samples"] >= 2)
                        if proof["overlap_seconds"] >= snapshot.get("parallel", {}).get("overlap_seconds", 0):
                            snapshot["parallel"] = dict(proof)
                except Exception:
                    pass
            await asyncio.sleep(5)


async def main():
    global active_driver
    driver = None; monitor = None
    persist()
    try:
        async with DshClient(os.environ["DSH_URL"], os.environ["DSH_TOKEN"], timeout=45, retry=RetryConfig(max_attempts=1)) as client:
            driver = Driver(client)
            active_driver = driver
            if manifest["phase"] == "planning":
                definitions = [{"id": "P01", "title": "Lấy ngữ cảnh Memory và soạn spec theo yêu cầu", "role": "researcher", "depends_on": []}, {"id": "P02", "title": "Phân rã spec thành task cụ thể và DAG phụ thuộc", "role": "researcher", "depends_on": ["P01"]}]
            else:
                if validate_plan(manifest["plan"])["digest"] != manifest["approved_plan_digest"]:
                    raise RuntimeError("LIVE_APPROVED_PLAN_CHANGED")
                await driver.restore_candidate()
                definitions = execution_definitions(manifest["plan"])
            driver.definitions = {t["id"]: t for t in definitions}
            for task in definitions:
                if task["id"] not in driver.outputs:
                    old = next((n for n in snapshot["nodes"] if n["id"] == task["id"]), {})
                    update(task["id"], "WAITING_INPUT" if old.get("state") == "WAITING_INPUT" else "PENDING", title=task["title"], role=task["role"], depends_on=task["depends_on"], error_code=None)
            monitor = asyncio.create_task(driver.monitor())
            class Task(WorkloopTask):
                async def report_output(self):
                    return await driver.execute_task(driver.definitions[self._id])
            process.WorkloopTask = Task
            process.make_gateway = lambda *args, **kwargs: driver
            workflow = {"name": "project-" + manifest["phase"], "nodes": {t["id"]: "WorkloopTask" for t in definitions}, "config": {t["id"]: {"role": t["role"], "brief": t["title"]} for t in definitions}, "edges": [{"source_id": p, "source_output": "report", "target_id": t["id"], "target_input": "context"} for t in definitions for p in t["depends_on"]]}
            store = Store(str(directory / "workloop.sqlite3")); runner = process.WorkflowRunner(store)
            job = store.create_job(workflow["name"], 1, {"run_id": manifest["run_id"], "project_id": manifest["project_id"]})
            snapshot["job_id"] = job
            from langflow.adlc.human_inputs import wait_active
            spent = float(snapshot.get("active_seconds", 0))
            limit = float((manifest.get("auto_timing") or {}).get("limit_seconds", 3500))
            await wait_active(runner.run(job, workflow, {"harness": {"kind": "project-owned"}, "defaults": {"max_parallel": 2}, "model": MODEL}), lambda: human_inputs.waiting(manifest["run_id"]), max(1, limit-spent))
            await driver.capture_usage()
            snapshot["engine_status"] = store.get_job(job)["status"]
            if any(t["id"] not in driver.outputs for t in definitions) or any(n["state"] not in ({"DONE", "SKIPPED"} if driver.control_flow else {"DONE"}) for n in snapshot["nodes"]):
                raise RuntimeError("LIVE_DAG_INCOMPLETE")
            snapshot["state"] = "PLAN_READY" if manifest["phase"] == "planning" else "SUCCEEDED"
    except Exception as error:
        recoverable = recoverable_error(error) or snapshot.get("recovery_required") or str(error).startswith(("LIVE_RECOVERY_NATIVE_NOT_FINISHED", "LIVE_RECOVERY_NATIVE_ACCEPTANCE_UNKNOWN"))
        snapshot.update(state="UNCONFIRMED" if recoverable else "FAILED", error_code=str(error) if str(error).startswith(("LIVE_", "PROJECT_")) else "LIVE_WORKFLOW_FAILED_" + type(error).__name__)
        import traceback
        traceback.print_exc()
    finally:
        if monitor: monitor.cancel()
        snapshot["completed_at"] = time.time(); persist()


if __name__ == "__main__":
    asyncio.run(main())
