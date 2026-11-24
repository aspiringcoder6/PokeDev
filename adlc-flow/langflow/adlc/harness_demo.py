"""Owner-scoped, real demo workflow. No recorded assistant output becomes proof.

Runs only inside newly-created demo repositories. Existing source repositories,
default GitHub branches, old plugin releases and normal ADLC runs are untouched.
"""

# ruff: noqa: EM101, PLR2004, ARG002 - stable public error codes; bounded demo limits; runtime port signatures.

import asyncio
import hashlib
import json
import os
import re
import sqlite3
from contextlib import suppress
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from uuid import UUID, uuid4, uuid5

import httpx
from pydantic import ValidationError

from langflow.adlc.harness_demo_models import (
    BINDING,
    DEMO_DIR,
    MEMORY,
    NATIVE_VERSION,
    REQUIREMENT,
    SKILL,
    SOURCE,
    SOURCE_PATH,
    TEST_PATH,
    TESTS,
    WORKFLOW,
    AgentReport,
    DemoError,
    NativeActivity,
    TaskBrief,
    TaskPlan,
    digest,
)
from langflow.adlc.harness_demo_sandbox import DockerDemoSandbox, DockerDemoVerifier, process
from langflow.adlc.models import ExecutorTarget, TaskRequest, TaskResultStatus
from langflow.adlc.task_loop_live import TaskLoopExecutor
from langflow.adlc.task_loop_live_models import LiveLoopCandidate, LiveLoopSpec
from langflow.adlc.task_loop_runtime import LoopRuntimeError
from langflow.adlc.task_loop_runtime_v2 import LoopIterationOutcomeV2, LoopRuntimeSessionV2
from langflow.adlc.task_loop_store import TaskLoopStore
from langflow.adlc.task_loop_workspace import TaskLoopWorkspace

DOMAIN = b"adlc-harness-demo-tools-v1\n"
GITHUB_REPO = "vanguard-lint/vanguard"
GITHUB_LABEL = "adlc-harness"


def github_repository():
    value = os.getenv("ADLC_HARNESS_GITHUB_REPOSITORY", GITHUB_REPO)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", value):
        raise DemoError("DEMO_GITHUB_REPOSITORY_INVALID", 503)
    return value


TOOLS = {
    "PLAN": {"demo_context", "demo_write_task_plan"},
    "ITERATE": {
        "demo_context",
        "demo_load_skill",
        "demo_memory_recall",
        "demo_write_task_brief",
        "demo_sandbox_read",
        "demo_sandbox_write",
        "demo_sandbox_checks",
        "demo_report_iteration",
    },
    "HANDOFF": {"demo_context", "demo_report_task", "demo_commit_candidate"},
}


def now():
    return datetime.now(timezone.utc).isoformat()


class DemoLedger:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS demo_runs
                    (id TEXT PRIMARY KEY, owner TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS demo_calls
                    (id TEXT PRIMARY KEY, session TEXT NOT NULL, digest TEXT NOT NULL, result TEXT);
                CREATE TABLE IF NOT EXISTS demo_deliveries (id TEXT PRIMARY KEY, digest TEXT NOT NULL, run_id TEXT);
            """)

    def db(self):
        return sqlite3.connect(self.path, timeout=10)

    def create(self, record, owner):
        with self.db() as db:
            db.execute(
                "INSERT INTO demo_runs VALUES (?,?,?,?)", (record["id"], owner, record["status"], json.dumps(record))
            )

    def get(self, run_id, owner=None):
        with self.db() as db:
            row = db.execute("SELECT owner,payload FROM demo_runs WHERE id=?", (str(run_id),)).fetchone()
        if not row or (owner is not None and row[0] != owner):
            raise DemoError("DEMO_NOT_FOUND", 404)
        return json.loads(row[1])

    def list(self, owner):
        with self.db() as db:
            return [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT payload FROM demo_runs WHERE owner=? ORDER BY rowid DESC LIMIT 25", (owner,)
                )
            ]

    def save(self, record):
        encoded = json.dumps(record)
        if len(encoded.encode()) > 2_097_152:
            raise DemoError("DEMO_HISTORY_LIMIT")
        with self.db() as db:
            db.execute("UPDATE demo_runs SET payload=?,status=? WHERE id=?", (encoded, record["status"], record["id"]))

    def transition(self, run_id, owner, expected, target):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT owner,status,payload FROM demo_runs WHERE id=?", (str(run_id),)).fetchone()
            if not row or row[0] != owner:
                raise DemoError("DEMO_NOT_FOUND", 404)
            if row[1] != expected:
                raise DemoError("DEMO_STATE_CONFLICT")
            record = json.loads(row[2])
            record["status"] = target
            db.execute("UPDATE demo_runs SET payload=?,status=? WHERE id=?", (json.dumps(record), target, str(run_id)))
        return record


class DemoHarnessClient:
    def __init__(self, url, token, *, transport=None):
        parsed = httpx.URL(url)
        if (
            parsed.scheme != "http"
            or parsed.host not in {"127.0.0.1", "localhost"}
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.userinfo
            or len(token.encode()) < 32
        ):
            raise DemoError("DEMO_HARNESS_CONFIGURATION_INVALID", 503)
        self.url, self.token = str(parsed).rstrip("/"), token
        self.transport = transport

    async def request(self, method, path, body=None):
        async with (
            httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=15, transport=self.transport) as client,
            client.stream(
                method,
                self.url + "/api/v1/adlc-demo" + path,
                headers={"Authorization": "Bearer " + self.token},
                json=body,
            ) as response,
        ):
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > 131072:
                    raise DemoError("DEMO_HARNESS_RESPONSE_INVALID", 502)
            try:
                result = json.loads(data)
            except ValueError:
                raise DemoError("DEMO_HARNESS_RESPONSE_INVALID", 502) from None
            if not isinstance(result, dict):
                raise DemoError("DEMO_HARNESS_RESPONSE_INVALID", 502)
            if response.status_code not in {200, 202}:
                code = result.get("error_code")
                if code == "EEXIST":
                    raise DemoError("DEMO_HARNESS_WRITER_LEASE_BLOCKED", 503)
                if code in {
                    "DEMO_NOT_READY",
                    "DEMO_DISABLED",
                    "DEMO_UNAUTHENTICATED",
                    "DEMO_JOURNAL_LIMIT",
                    "DEMO_JOB_CONFLICT",
                }:
                    raise DemoError(code, 503)
                raise DemoError("DEMO_HARNESS_UNAVAILABLE", 503)
            return result

    async def run(self, command):
        await self.request("POST", "/jobs", command)  # No POST/model retry on unknown acknowledgement.
        async with asyncio.timeout(command["timeout_ms"] / 1000 + 10):
            while True:
                result = await self.request("GET", "/jobs/" + command["session_id"])
                if (
                    result.get("request_digest") != digest(command)
                    or result.get("runtime_version") != NATIVE_VERSION
                    or result.get("session_id") != command["session_id"]
                    or result.get("run_id") != command["run_id"]
                    or result.get("stage") != command["stage"]
                ):
                    raise DemoError("DEMO_NATIVE_BINDING_MISMATCH", 502)
                diagnostics = None
                if result.get("native_activity") is not None:
                    try:
                        activity = NativeActivity.model_validate(result["native_activity"])
                    except ValidationError:
                        raise DemoError("DEMO_NATIVE_DIAGNOSTICS_INVALID", 502) from None
                    diagnostics = {
                        "session_id": command["session_id"],
                        "stage": command["stage"],
                        "runtime_version": NATIVE_VERSION,
                        "request_digest": result["request_digest"],
                        "native_activity": activity.model_dump(mode="json"),
                    }
                if result.get("status") == "FAILED":
                    code = result.get("error_code")
                    code = (
                        code
                        if isinstance(code, str) and re.fullmatch(r"DEMO_[A-Z0-9_]{1,80}", code)
                        else "DEMO_NATIVE_JOB_FAILED"
                    )
                    raise DemoError(code, 502, native_diagnostics=diagnostics)
                if result.get("status") == "COMPLETED":
                    if result.get("request_digest") != digest(command):
                        raise DemoError("DEMO_NATIVE_BINDING_MISMATCH", 502)
                    return result
                await asyncio.sleep(0.5)

    async def cancel(self, session_id):
        await self.request("POST", "/jobs/" + str(session_id) + "/cancel", {})


class DemoTaskLoopRuntime:
    binding = BINDING

    def __init__(self, service, run_id):
        self.service, self.run_id = service, run_id

    async def open_iteration(self, command, *, directory):
        session_id = uuid5(command.attempt_id, "harness-demo/" + NATIVE_VERSION)
        self.service.bind(
            session_id,
            self.run_id,
            "ITERATE",
            directory=directory,
            iteration=command.iteration,
            command_digest=command.content_digest,
        )
        return LoopRuntimeSessionV2(
            runtime=self.binding,
            request_digest=command.content_digest,
            session_id=str(session_id),
            fresh_context=True,
            tools_disabled=False,
        )

    async def run_iteration(self, command, session, *, directory):
        try:
            result = await self.service.native(session.session_id)
            return LoopIterationOutcomeV2(
                runtime=self.binding,
                request_digest=command.content_digest,
                session_id=session.session_id,
                mode="WORKSPACE_EDIT",
                usage=result["usage"],
                context_compacted=False,
                tool_activity=True,
                files=None,
            )
        except (DemoError, TimeoutError) as exc:
            raise LoopRuntimeError(exc.code if isinstance(exc, DemoError) else "DEMO_NATIVE_TIMEOUT") from None

    async def close_iteration(self, session, *, directory, abort):
        await self.service.unbind(session.session_id, abort=abort)


class HarnessDemoService:
    def __init__(self, root, *, client=None, sandbox=None):
        self.root = Path(root).resolve()
        self.ledger = DemoLedger(self.root / "demo.sqlite3")
        self.client = client
        self.sandbox = sandbox or DockerDemoSandbox(os.getenv("ADLC_DEMO_SANDBOX_IMAGE", "python:3.12-alpine"))
        self.scopes, self.jobs, self.locks = {}, {}, {}

    def lock(self, run_id):
        return self.locks.setdefault(str(run_id), asyncio.Lock())

    def repository(self, run_id):
        target = self.root / UUID(str(run_id)).hex / "source"
        if target.is_symlink() or target.is_junction():
            raise DemoError("DEMO_WORKSPACE_INVALID")
        return target

    async def git(self, directory, *args):
        code, out, _ = await process(
            [
                "git",
                "-c",
                "core.hooksPath=",
                "-c",
                "commit.gpgsign=false",
                "-c",
                "core.autocrlf=false",
                "-c",
                "core.eol=lf",
                "-C",
                str(directory),
                *args,
            ],
            timeout=60,
            credential_context=True,
        )
        if code:
            raise DemoError("DEMO_GIT_FAILED")
        return out.strip()

    async def event(self, run_id, stage, output):
        async with self.lock(run_id):
            record = self.ledger.get(run_id)
            if len(record["events"]) >= 256:
                raise DemoError("DEMO_EVENT_LIMIT")
            record["events"].append({"seq": len(record["events"]) + 1, "stage": stage, "at": now(), "output": output})
            self.ledger.save(record)

    async def update(self, run_id, **changes):
        async with self.lock(run_id):
            record = self.ledger.get(run_id)
            record.update(changes)
            self.ledger.save(record)
        return record

    async def capabilities(self):
        blockers = []
        try:
            docker = await self.sandbox.health()
        except (OSError, DemoError, TimeoutError):
            docker = None
            blockers.append("DEMO_DOCKER_IMAGE_UNAVAILABLE")
        if not self.client:
            blockers.append("DEMO_HARNESS_NOT_CONFIGURED")
        else:
            try:
                health = await self.client.request("GET", "/health")
                if (
                    health.get("model") != "cx/gpt-5.6-luna"
                    or health.get("provider") != "my-codex"
                    or health.get("runtime_version") != NATIVE_VERSION
                    or not health.get("ready")
                ):
                    blockers.append("DEMO_HARNESS_NOT_READY")
            except (httpx.HTTPError, DemoError):
                blockers.append("DEMO_HARNESS_NOT_READY")
        return {
            "workflow": WORKFLOW,
            "requirement": REQUIREMENT,
            "ready": not blockers,
            "blockers": blockers,
            "sandbox": docker,
            "memory_mode": "REVIEWED_GATEWAY" if os.getenv("ADLC_DEMO_MEMORY_PROJECT_ID") else "CURATED_LOCAL",
            "github_repository": github_repository(),
            "github_writes_enabled": os.getenv("ADLC_DEMO_GITHUB_ENABLED", "").lower() == "true",
        }

    async def create(
        self, owner, requirement, *, issue=None, github=False, run_id=None, workflow_run_id=None, source_flow_id=None
    ):
        if github and os.getenv("ADLC_DEMO_GITHUB_ENABLED", "").lower() != "true":
            raise DemoError("DEMO_GITHUB_DISABLED")
        run_id = run_id or uuid4()
        record = {
            "id": str(run_id),
            "owner": owner,
            "status": "DRAFT",
            "created_at": now(),
            "workflow": WORKFLOW,
            "requirement": requirement,
            "requirement_digest": digest(requirement),
            "events": [],
            "issue": issue,
            "github": github,
            "github_repository": github_repository(),
            "provider_simulated": getattr(self.client, "simulated", False),
            **(
                {"workflow_run_id": str(workflow_run_id), "source_flow_id": str(source_flow_id)}
                if workflow_run_id is not None
                else {}
            ),
        }
        self.ledger.create(record, owner)
        await self.event(run_id, "requirement", {"text": requirement, "digest": record["requirement_digest"]})
        return self.ledger.get(run_id, owner)

    async def restart(self, run_id, owner):
        async with self.lock(run_id):
            previous = self.ledger.get(run_id, owner)
            if previous["status"] != "FAILED" or str(run_id) in self.jobs:
                raise DemoError("DEMO_STATE_CONFLICT")
            if previous.get("restart_run_id"):
                return self.ledger.get(previous["restart_run_id"], owner)
            if previous.get("restart_pending"):
                raise DemoError("DEMO_RESTART_UNCONFIRMED")
            if previous["github"] and previous.get("github_repository", GITHUB_REPO) != github_repository():
                raise DemoError("DEMO_RESTART_REPOSITORY_CHANGED")
            if previous["github"] and os.getenv("ADLC_DEMO_GITHUB_ENABLED", "").lower() != "true":
                raise DemoError("DEMO_GITHUB_DISABLED")
            # Durable intent before allocating a new logical run. No model/GitHub POST here.
            previous["restart_pending"] = True
            self.ledger.save(previous)
            issue = previous.get("issue")
            if issue:
                issue = {k: v for k, v in issue.items() if k not in {"assigned_agent", "task_id", "plan_digest"}}
                issue = {
                    **issue,
                    "source": "EXPLICIT_SESSION_RESTART",
                    "original_source": issue.get("original_source", issue.get("source")),
                }
            child = await self.create(owner, previous["requirement"], issue=issue, github=previous["github"])
            child = await self.update(child["id"], restart_of=previous["id"])
            await self.event(
                child["id"],
                "restart",
                {
                    "previous_run_id": previous["id"],
                    "requested_by": owner,
                    "approvals_carried_forward": False,
                    "model_started": False,
                },
            )
            previous.update(restart_pending=False, restart_run_id=child["id"])
            self.ledger.save(previous)
            return self.ledger.get(child["id"], owner)

    async def prepare(self, run_id):
        record = self.ledger.get(run_id)
        directory = self.repository(run_id)
        directory.parent.mkdir(parents=True, exist_ok=True)
        if directory.exists():
            raise DemoError("DEMO_REPOSITORY_ALREADY_EXISTS")
        if record["github"]:
            # The operator opted in; clone only, never execute upstream scripts/hooks.
            await self.git(
                directory.parent,
                "clone",
                "--no-checkout",
                "--single-branch",
                "--branch",
                "main",
                "https://github.com/" + record.get("github_repository", GITHUB_REPO) + ".git",
                str(directory),
            )
            await self.git(directory, "checkout", "-b", "demo-main", "origin/main")
            # Use the explicitly signed-in GitHub CLI account only in this owned checkout.
            # No provider key, token-bearing Git URL or global credential configuration.
            await self.git(directory, "config", "--add", "credential.https://github.com.helper", "")
            await self.git(
                directory, "config", "--add", "credential.https://github.com.helper", "!gh auth git-credential"
            )
            upstream = await self.git(directory, "rev-parse", "HEAD")
        else:
            directory.mkdir()
            await self.git(directory, "init", "-q", "-b", "demo-main")
            upstream = None
        await self.git(directory, "config", "user.name", "ADLC Harness Agent")
        await self.git(directory, "config", "user.email", "adlc-harness@example.invalid")
        target = directory / DEMO_DIR
        if target.exists():
            raise DemoError("DEMO_UPSTREAM_PATH_OCCUPIED")
        target.mkdir(parents=True)
        (target / "app.py").write_bytes(SOURCE.encode())
        (target / "test_acceptance.py").write_bytes(TESTS.encode())
        await self.git(directory, "add", "--", SOURCE_PATH, TEST_PATH)
        await self.git(directory, "commit", "-qm", "chore: add frozen pagination task and protected checks")
        base = await self.git(directory, "rev-parse", "HEAD")
        mirror = directory.parent / "orchestrator-mirror.git"
        mirror.mkdir()
        await self.git(mirror, "init", "--bare", "-q")
        await self.git(directory, "remote", "add", "demo-mirror", str(mirror))
        await self.git(directory, "push", "demo-mirror", "demo-main:refs/heads/demo-main")
        return await self.update(
            run_id,
            base_commit=base,
            upstream_commit=upstream,
            remote_branch="codex/harness-session-" + UUID(str(run_id)).hex[:12],
        )

    def bind(self, session_id, run_id, stage, **context):
        if str(session_id) in self.scopes or len(self.scopes) >= 2:
            raise DemoError("DEMO_SESSION_CONFLICT")
        self.scopes[str(session_id)] = {
            "run_id": str(run_id),
            "stage": stage,
            "live": True,
            "calls": [],
            "session_id": str(session_id),
            **context,
        }

    async def unbind(self, session_id, *, abort=False):
        scope = self.scopes.pop(str(session_id), None)
        if scope:
            scope["live"] = False
            if abort and not scope.get("completed") and self.client:
                with suppress(httpx.HTTPError, DemoError, TimeoutError):
                    await self.client.cancel(session_id)
                # No new model invocation or guessed release on timeout.

    async def native(self, session_id):
        scope = self.scopes[str(session_id)]
        record = self.ledger.get(scope["run_id"])
        if record.get("workflow", {}).get("runtime") != BINDING.model_dump(mode="json"):
            # A reload never silently substitutes the runtime frozen in an old run.
            raise DemoError("DEMO_NATIVE_BINDING_MISMATCH", 409)
        if not self.client:
            raise DemoError("DEMO_HARNESS_NOT_CONFIGURED", 503)
        command = {
            "schema_version": "0.1",
            "session_id": str(session_id),
            "run_id": scope["run_id"],
            "stage": scope["stage"],
            "timeout_ms": 180000,
            "model": "cx/gpt-5.6-luna",
            "provider": "my-codex",
        }
        try:
            result = await self.client.run(command)
        except DemoError as exc:
            if exc.native_diagnostics:
                await self.event(scope["run_id"], "native_diagnostics", exc.native_diagnostics)
                await self.update(scope["run_id"], native_diagnostics=exc.native_diagnostics)
            raise
        except httpx.HTTPError:
            raise DemoError("DEMO_HARNESS_TRANSPORT_UNKNOWN", 502) from None
        required = TOOLS[scope["stage"]]
        if scope["stage"] == "ITERATE":
            required = required - {"demo_sandbox_write"}  # A valid unchanged iteration remains possible.
        if not required.issubset(set(scope["calls"])):
            raise DemoError("DEMO_REQUIRED_TOOLS_MISSING")
        scope["completed"] = True
        await self.event(
            scope["run_id"],
            "native_session",
            {
                "session_id": str(session_id),
                "stage": scope["stage"],
                "provider": "my-codex",
                "model": "cx/gpt-5.6-luna",
                "usage": result["usage"],
                "tools": scope["calls"],
                "runtime_version": result.get("runtime_version"),
                "native_activity": result.get("native_activity"),
            },
        )
        return result

    def launch(self, run_id, operation):
        if str(run_id) in self.jobs:
            raise DemoError("DEMO_JOB_ACTIVE")

        async def guarded():
            try:
                await operation()
            except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 - durable terminal boundary; no exception text exposed.
                await self.update(
                    run_id,
                    status="FAILED",
                    error_code=exc.code if hasattr(exc, "code") else "DEMO_EXECUTION_INTERRUPTED",
                )
            finally:
                self.jobs.pop(str(run_id), None)

        self.jobs[str(run_id)] = asyncio.create_task(guarded())

    async def plan(self, run_id):
        await self.prepare(run_id)
        session_id = uuid4()
        self.bind(session_id, run_id, "PLAN")
        try:
            await self.native(session_id)
            await self.update(run_id, status="AWAITING_PLAN_APPROVAL")
        finally:
            await self.unbind(session_id, abort=True)

    async def execute(self, run_id):
        record = self.ledger.get(run_id)
        issue = record["issue"] or {
            "source": "LOCAL_DEMO",
            "number": 1,
            "title": "Pagination task",
            "body": record["requirement"],
        }
        issue = {
            **issue,
            "assigned_agent": "harness-coding-agent",
            "task_id": "pagination",
            "plan_digest": record["plan_digest"],
        }
        await self.update(run_id, issue=issue)
        await self.event(run_id, "assignment", issue)
        source = self.repository(run_id)
        workspace = TaskLoopWorkspace(source, source.parent / "worktrees")
        store = TaskLoopStore(source.parent / "loop.sqlite3")
        spec = LiveLoopSpec(
            spec_id=UUID(str(run_id)),
            specification=record["requirement"],
            base_commit=record["base_commit"],
            writable_paths=(SOURCE_PATH,),
            max_iterations=3,
            max_duration_ms=600000,
            verification_commands=({"check_id": "acceptance", "test_path": TEST_PATH},),
            acceptance_criteria=(
                {
                    "criterion_id": "pagination",
                    "description": "Fixed four pagination checks",
                    "check_refs": ["acceptance"],
                },
            ),
        )

        async def verified(stage, output):
            await self.event(run_id, stage, output)

        kernel = TaskLoopExecutor(
            workspace=workspace,
            store=store,
            runtime=DemoTaskLoopRuntime(self, run_id),
            verifier=DockerDemoVerifier(workspace, _ScopedSandbox(self.sandbox), verified),
        )
        task_id, definition_id = uuid4(), uuid4()

        async def changed(*_):
            return None

        for iteration in range(1, 4):
            request = TaskRequest(
                request_id=uuid4(),
                workflow_run_id=UUID(str(run_id)),
                task_run_id=task_id,
                attempt_id=uuid4(),
                task_definition_id=definition_id,
                task_type="IMPLEMENTATION",
                name="Harness demo pagination",
                executor=ExecutorTarget(service="agent-provider:task-loop", operation="demo-task-loop"),
                input={
                    "namedInputs": {
                        "task_loop_spec": spec.model_dump(mode="json"),
                        "requirement": record["requirement"],
                    }
                },
                context={"task_loop_iteration": iteration},
                dependency_task_run_ids=[],
                constraints={"max_attempts": 3, "timeout_ms": 210000},
                idempotency_key=str(uuid4()),
                requested_at=datetime.now(timezone.utc),
            )
            result = await kernel.execute(request, changed)
            await self.event(run_id, "task_loop", result.model_dump(mode="json"))
            if result.status is TaskResultStatus.SUCCEEDED:
                outputs = result.output["outputs"]
                await self.update(
                    run_id,
                    candidate=outputs["candidate"],
                    verification=outputs["verification_report"],
                    loop_result=result.model_dump(mode="json"),
                )
                break
            if not result.error or result.error.code != "TASK_LOOP_CHECKS_FAILED":
                raise DemoError(result.error.code if result.error else "DEMO_TASK_LOOP_FAILED")
        else:
            raise DemoError("DEMO_ITERATIONS_EXHAUSTED")
        session_id = uuid4()
        self.bind(session_id, run_id, "HANDOFF")
        try:
            await self.native(session_id)
            record = self.ledger.get(run_id)
            approval = {
                "commit": record["commit"],
                "candidate_digest": record["candidate"]["content_digest"],
                "verification_digest": digest(record["verification"]),
                "base_commit": record["base_commit"],
                "target": record["remote_branch"] if record["github"] else "local-bare:demo-main",
            }
            await self.update(
                run_id, status="AWAITING_MERGE_APPROVAL", handoff=approval, handoff_digest=digest(approval)
            )
        finally:
            await self.unbind(session_id, abort=True)

    async def memory(self, record):
        project = os.getenv("ADLC_DEMO_MEMORY_PROJECT_ID", "")
        if not project:
            return {**MEMORY, "content_digest": digest(MEMORY["text"])}
        from langflow.adlc.project_memory_client import get_memory_clients, load_binding

        binding = load_binding(record["owner"], UUID(project))
        result = (
            await get_memory_clients()
            .get(binding)
            .operation("context", query="pagination one-based Python bool", top_k=3)
        )
        return {
            "source": "REVIEWED_GATEWAY",
            "backend_revision": binding.backend_revision,
            "authority": "ADVISORY_UNTRUSTED",
            "verification_evidence": False,
            "chunks": [c.model_dump(mode="json") for c in result.chunks],
        }

    async def tool(self, command):
        scope = self.scopes.get(str(command.session_id))
        if not scope or not scope["live"] or command.name not in TOOLS[scope["stage"]]:
            raise DemoError("DEMO_TOOL_SCOPE_DENIED", 403)
        key, fingerprint = str(command.call_id), digest(command.model_dump(mode="json"))
        with self.ledger.db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT digest,result FROM demo_calls WHERE id=?", (key,)).fetchone()
            if old:
                if old[0] != fingerprint or old[1] is None:
                    raise DemoError("DEMO_TOOL_REPLAY_CONFLICT")
                return json.loads(old[1])
            db.execute("INSERT INTO demo_calls VALUES (?,?,?,NULL)", (key, str(command.session_id), fingerprint))
        async with self.lock(scope["run_id"] + ":tools"):
            record = self.ledger.get(scope["run_id"])
            args, name = command.arguments, command.name
            if not isinstance(args, dict):
                raise DemoError("DEMO_ARGUMENTS_INVALID", 422)
            no_args = {
                "demo_context",
                "demo_load_skill",
                "demo_memory_recall",
                "demo_sandbox_read",
                "demo_sandbox_checks",
                "demo_commit_candidate",
            }
            if name in no_args and args:
                raise DemoError("DEMO_ARGUMENTS_INVALID", 422)
            if name == "demo_context":
                result = {k: record[k] for k in ("id", "requirement", "requirement_digest", "base_commit")}
                result.update(
                    {
                        "plan": record.get("plan"),
                        "issue": record.get("issue"),
                        "iteration": scope.get("iteration"),
                        "candidate": record.get("candidate"),
                        "verification": record.get("verification"),
                        "previous_findings": [
                            e["output"]["verification"]["checks"] for e in record["events"] if e["stage"] == "verify"
                        ][-1:],
                        "allowed_file": "app.py",
                        "protected_checks": 4,
                        "skill_id": SKILL["skill_id"],
                    }
                )
            elif name == "demo_write_task_plan":
                if record.get("plan"):
                    raise DemoError("DEMO_PLAN_IMMUTABLE")
                plan = TaskPlan.model_validate(args).model_dump(mode="json")
                plan = {
                    **plan,
                    "requirement_digest": record["requirement_digest"],
                    "base_commit": record["base_commit"],
                }
                await self.update(scope["run_id"], plan=plan, plan_digest=digest(plan))
                result = {"plan": plan, "digest": digest(plan)}
            elif name == "demo_load_skill":
                result = {**SKILL, "content_digest": digest(SKILL)}
            elif name == "demo_memory_recall":
                result = await self.memory(record)
            elif name == "demo_write_task_brief":
                if "demo_write_task_brief" in scope["calls"]:
                    raise DemoError("DEMO_BRIEF_ALREADY_WRITTEN")
                brief = TaskBrief.model_validate(args).model_dump(mode="json")
                result = {
                    "brief": brief,
                    "iteration": scope["iteration"],
                    "plan_digest": record["plan_digest"],
                    "digest": digest(brief),
                }
            elif name.startswith("demo_sandbox_"):
                if not {"demo_write_task_brief", "demo_load_skill", "demo_memory_recall"}.issubset(scope["calls"]):
                    raise DemoError("DEMO_BRIEF_SKILL_MEMORY_REQUIRED")
                directory = scope["directory"] / DEMO_DIR
                op = name.removeprefix("demo_sandbox_")
                if op == "write":
                    if set(args) != {"content", "expected_digest"} or "demo_sandbox_read" not in scope["calls"]:
                        raise DemoError("DEMO_ARGUMENTS_INVALID", 422)
                    actual = "sha256:" + hashlib.sha256((directory / "app.py").read_bytes()).hexdigest()
                    if args["expected_digest"] != actual:
                        raise DemoError("DEMO_WRITE_DIGEST_CONFLICT")
                    if not isinstance(args["content"], str) or len(args["content"].encode()) > 16384:
                        raise DemoError("DEMO_FILE_INVALID", 422)
                result = await self.sandbox.run(directory, op, content=args.get("content"))
                result["verification_evidence"] = False  # Agent self-check is not independent Verify.
            elif name in {"demo_report_iteration", "demo_report_task"}:
                report = AgentReport.model_validate(args).model_dump(mode="json")
                if name == "demo_report_iteration" and "demo_sandbox_checks" not in scope["calls"]:
                    raise DemoError("DEMO_SELF_CHECK_REQUIRED")
                result = {
                    "report": report,
                    "advisory": True,
                    "candidate_digest": record.get("candidate", {}).get("content_digest"),
                }
                if name == "demo_report_task":
                    await self.update(scope["run_id"], task_report=result)
            elif name == "demo_commit_candidate":
                if "demo_report_task" not in scope["calls"] or not record.get("verification"):
                    raise DemoError("DEMO_REPORT_VERIFY_REQUIRED")
                result = await self.commit(record)
            else:
                raise DemoError("DEMO_TOOL_DENIED", 403)
            scope["calls"].append(name)
            await self.event(
                scope["run_id"], name, {"session_id": str(command.session_id), "arguments": args, "result": result}
            )
            with self.ledger.db() as db:
                db.execute("UPDATE demo_calls SET result=? WHERE id=?", (json.dumps(result), key))
            return result

    async def commit(self, record):
        if record.get("commit"):
            return {"commit": record["commit"], "branch": record["agent_branch"]}
        candidate = LiveLoopCandidate.model_validate(record["candidate"])
        if set(candidate.changes) != {SOURCE_PATH} or candidate.changes[SOURCE_PATH] is None:
            raise DemoError("DEMO_COMMIT_SCOPE_INVALID")
        source = self.repository(record["id"])
        if await self.git(source, "rev-parse", "HEAD") != record["base_commit"] or await self.git(
            source, "status", "--porcelain"
        ):
            raise DemoError("DEMO_SOURCE_CHANGED")
        branch = "agent/demo-" + UUID(record["id"]).hex[:12]
        await self.git(source, "checkout", "-b", branch, record["base_commit"])
        (source / SOURCE_PATH).write_bytes(candidate.changes[SOURCE_PATH].content.encode())
        await self.git(source, "add", "--", SOURCE_PATH)
        await self.git(source, "commit", "-qm", "fix: correct pagination verified by protected Docker checks")
        commit = await self.git(source, "rev-parse", "HEAD")
        await self.git(source, "checkout", "demo-main")
        await self.update(record["id"], commit=commit, agent_branch=branch)
        return {"commit": commit, "branch": branch, "candidate_digest": candidate.content_digest, "remote_push": False}

    async def publish(self, run_id):
        record = self.ledger.get(run_id)
        source = self.repository(run_id)
        if await self.git(source, "rev-parse", "demo-main") != record["base_commit"]:
            raise DemoError("DEMO_MERGE_BASE_CHANGED")
        if await self.git(source, "rev-parse", record["agent_branch"]) != record["commit"]:
            raise DemoError("DEMO_AGENT_HEAD_CHANGED")
        if await self.git(source, "status", "--porcelain"):
            raise DemoError("DEMO_SOURCE_CHANGED")
        await self.git(source, "checkout", "demo-main")
        await self.git(source, "merge", "--ff-only", record["commit"])
        await self.git(source, "push", "demo-mirror", "demo-main:refs/heads/demo-main")
        receipt = {
            "actor": "ADLC_ORCHESTRATOR",
            "merge": "FAST_FORWARD",
            "commit": record["commit"],
            "local_bare_pushed": True,
            "github_pushed": False,
        }
        if record["github"]:
            if os.getenv("ADLC_DEMO_GITHUB_ENABLED", "").lower() != "true":
                raise DemoError("DEMO_GITHUB_DISABLED")
            remote = await self.git(source, "ls-remote", "origin", "refs/heads/" + record["remote_branch"])
            if remote:
                raise DemoError("DEMO_REMOTE_BRANCH_EXISTS")
            # No force; creates only this demo branch. Never writes refs/heads/main.
            await self.git(source, "push", "origin", "demo-main:refs/heads/" + record["remote_branch"])
            receipt.update(
                github_pushed=True,
                repository=record.get("github_repository", GITHUB_REPO),
                branch=record["remote_branch"],
            )
        await self.event(run_id, "publish", receipt)
        return await self.update(run_id, status="SUCCEEDED", publish_receipt=receipt)


class _ScopedSandbox:
    def __init__(self, sandbox):
        self.sandbox = sandbox

    async def run(self, directory, operation):
        return await self.sandbox.run(directory / DEMO_DIR, operation)


@lru_cache(maxsize=1)
def get_demo_service():
    token = os.getenv("ADLC_DEMO_API_TOKEN", "")
    try:
        client = DemoHarnessClient(os.getenv("ADLC_DEMO_HARNESS_URL", "http://127.0.0.1:3080"), token)
    except DemoError:
        client = None
    root = Path(os.getenv("ADLC_DEMO_STATE_ROOT", str(Path(__file__).resolve().parents[2] / "data/harness-demo")))
    return HarnessDemoService(root, client=client)
