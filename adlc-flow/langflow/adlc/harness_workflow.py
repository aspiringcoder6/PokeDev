"""Workflow-owned native Harness stages; only the coordinator can authorize gates."""

# ruff: noqa: EM101, PLR2004 - fixed public codes and the bounded native profile.
import asyncio
import os
from datetime import datetime, timezone
from uuid import UUID, uuid4, uuid5

from langflow.adlc.harness_demo import HarnessDemoService, get_demo_service, github_repository
from langflow.adlc.harness_demo_models import NATIVE_VERSION, DemoError, digest
from langflow.adlc.models import ServiceError, TaskMetrics, TaskResult, TaskResultStatus, TaskRunStatus, TokenUsage

SERVICE = "agent-provider:harness-workflow"
VERSION = "0.1.0"
PACKAGES = {
    "PLAN": "harness-workflow-plan",
    "EXECUTE": "harness-workflow-task",
    "PUBLISH": "harness-workflow-publish",
}
REFERENCES = frozenset(
    {
        SERVICE,
        "model:my-codex/cx/gpt-5.6-luna",
        "prompt:harness-workflow-scoped/0.1.0",
        "rules:harness-workflow-human-gates/0.1.0",
        "plugin:vai-adlc-demo-session/0.1.1",
        "memory:harness-project-advisory/0.1.0",
        "sandbox:harness-pagination-docker/0.1.0",
    }
)
REPOSITORY = "aspiringcoder6/vanguard"
CONFIGURATION = {
    "repository": REPOSITORY,
    "provider": "my-codex",
    "model": "cx/gpt-5.6-luna",
    "native_version": NATIVE_VERSION,
}


def workflow_enabled():
    return os.getenv("ADLC_HARNESS_DEMO_ENABLED", "").lower() == "true"


def session_id(run_id):
    return uuid5(UUID(str(run_id)), "harness-workflow-session/" + VERSION)


class HarnessWorkflowExecutor:
    service_name = SERVICE
    capabilities = ("native-harness", "human-gates", "sandbox", "memory", "verified-github-publication")

    def __init__(self, service: HarnessDemoService, *, authorize=None):
        self.service, self.authorize = service, authorize
        with service.ledger.db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS harness_workflow_stages
                (workflow_id TEXT NOT NULL,stage TEXT NOT NULL,request_digest TEXT NOT NULL,
                 result TEXT,PRIMARY KEY(workflow_id,stage))""")

    def bind_workflow_authority(self, authorize):
        self.authorize = authorize

    def parse(self, request):
        phase = request.executor.operation
        trace = request.metadata.get("plan_traceability", {})
        if (
            phase not in PACKAGES
            or request.executor.service != SERVICE
            or trace.get("package_id") != PACKAGES[phase]
            or trace.get("package_version") != VERSION
            or request.metadata.get("resolved_configuration") != CONFIGURATION
            or request.constraints.get("max_attempts") != 1
        ):
            raise DemoError("HARNESS_WORKFLOW_BINDING_INVALID")
        if not self.authorize:
            raise DemoError("HARNESS_WORKFLOW_AUTHORITY_UNAVAILABLE")
        authority = self.authorize(request)
        owner = authority["owner_id"]
        if (
            not workflow_enabled()
            or os.getenv("ADLC_DEMO_GITHUB_ENABLED", "").lower() != "true"
            or owner != os.getenv("ADLC_DEMO_GITHUB_OWNER_ID")
            or github_repository() != REPOSITORY
        ):
            raise DemoError("HARNESS_WORKFLOW_OWNER_REPOSITORY_DENIED")
        return phase, authority

    def saved(self, request, phase, *, reserve=False):
        fingerprint = digest(request.model_dump(mode="json"))
        with self.service.ledger.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT request_digest,result FROM harness_workflow_stages WHERE workflow_id=? AND stage=?",
                (str(request.workflow_run_id), phase),
            ).fetchone()
            if row:
                if row[0] != fingerprint:
                    raise DemoError("HARNESS_WORKFLOW_STAGE_CONFLICT")
                if row[1]:
                    return TaskResult.model_validate_json(row[1])
                raise DemoError("HARNESS_WORKFLOW_STAGE_INTERRUPTED")
            if reserve:
                # Durable intent before creating a checkout, invoking a model or publishing.
                db.execute(
                    "INSERT INTO harness_workflow_stages VALUES (?,?,?,NULL)",
                    (str(request.workflow_run_id), phase, fingerprint),
                )
            return None

    def retain(self, request, phase, result):
        with self.service.ledger.db() as db:
            changed = db.execute(
                "UPDATE harness_workflow_stages SET result=? WHERE workflow_id=? AND stage=? AND result IS NULL",
                (result.model_dump_json(), str(request.workflow_run_id), phase),
            ).rowcount
            if changed != 1:
                raise DemoError("HARNESS_WORKFLOW_CHECKPOINT_CONFLICT")

    def snapshot(self, record):
        memory = [e["output"]["result"] for e in record["events"] if e["stage"] == "demo_memory_recall"]
        briefs = [e["output"]["result"] for e in record["events"] if e["stage"] == "demo_write_task_brief"]
        return {
            key: record.get(key)
            for key in (
                "plan",
                "plan_digest",
                "candidate",
                "verification",
                "task_report",
                "commit",
                "handoff",
                "handoff_digest",
                "publish_receipt",
                "native_diagnostics",
            )
        } | {"memory": memory, "briefs": briefs}

    def review(self, record, phase):
        if phase == "PUBLISH":
            return None
        return {
            "kind": "PLAN" if phase == "PLAN" else "COMMIT",
            "session_id": record["id"],
            "workflow_run_id": record["workflow_run_id"],
            "repository": record["github_repository"],
            "native_version": NATIVE_VERSION,
            "digest": record["plan_digest"] if phase == "PLAN" else record["handoff_digest"],
            "evidence": record["plan"] if phase == "PLAN" else record["handoff"],
            "result": self.snapshot(record),
        }

    def result(self, request, phase, started, *, record=None, error=None):
        completed = datetime.now(timezone.utc)
        stages = {"PLAN"} if phase == "PLAN" else {"ITERATE", "HANDOFF"} if phase == "EXECUTE" else set()
        usages = [
            e["output"]["usage"]
            for e in (record or {}).get("events", [])
            if e["stage"] == "native_session" and e["output"]["stage"] in stages
        ]
        output = (
            None
            if error
            else {
                "outputs": {
                    "session": {
                        "id": record["id"],
                        "workflow_run_id": record["workflow_run_id"],
                        "phase": phase,
                        "status": record["status"],
                        "url": "/harness/?run=" + record["id"],
                    },
                    "review": self.review(record, phase),
                    "result": self.snapshot(record),
                }
            }
        )
        return TaskResult(
            request_id=request.request_id,
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
            status=TaskResultStatus.FAILED if error else TaskResultStatus.SUCCEEDED,
            output=output,
            artifacts=[],
            error=ServiceError(
                error_id=uuid4(),
                code=error,
                category="EXECUTION",
                retryable=False,
                service=SERVICE,
                message="The workflow-owned Harness stage did not produce an accepted result.",
                occurred_at=completed,
            )
            if error
            else None,
            metrics=TaskMetrics(
                duration_ms=max(0, int((completed - started).total_seconds() * 1000)),
                token_usage=TokenUsage(
                    **{k: sum(u[k] for u in usages) for k in ("input_tokens", "output_tokens", "total_tokens")}
                ),
                custom={"model": "cx/gpt-5.6-luna", "cost": None},
            ),
            started_at=started,
            completed_at=completed,
            metadata={
                "harness_workflow": {
                    "session_id": str(session_id(request.workflow_run_id)),
                    "phase": phase,
                    "native_version": NATIVE_VERSION,
                }
            },
        )

    async def operation(self, request, phase, authority):
        run_id, owner = session_id(request.workflow_run_id), authority["owner_id"]
        if not (await self.service.capabilities())["ready"]:
            raise DemoError("HARNESS_WORKFLOW_NOT_READY")
        if phase == "PLAN":
            requirement = request.input.get("namedInputs", {}).get("requirement")
            if not isinstance(requirement, str) or not 1 <= len(requirement) <= 8192:
                raise DemoError("HARNESS_WORKFLOW_REQUIREMENT_INVALID")
            await self.service.create(
                owner,
                requirement,
                github=True,
                issue={
                    "source": "WORKFLOW",
                    "title": request.context.get("workflow_name", request.name),
                    "workflow_run_id": str(request.workflow_run_id),
                    "repository": REPOSITORY,
                },
                run_id=run_id,
                workflow_run_id=request.workflow_run_id,
                source_flow_id=UUID(request.metadata["flow_id"]),
            )
            self.service.ledger.transition(run_id, owner, "DRAFT", "PLANNING")
            operation, expected = self.service.plan, "AWAITING_PLAN_APPROVAL"
        else:
            record = self.service.ledger.get(run_id, owner)
            review = authority.get("review")
            kind, key = ("PLAN", "plan_digest") if phase == "EXECUTE" else ("COMMIT", "handoff_digest")
            if (
                record.get("workflow_run_id") != str(request.workflow_run_id)
                or record["github_repository"] != REPOSITORY
                or not review
                or review.get("kind") != kind
                or review.get("session_id") != str(run_id)
                or review.get("workflow_run_id") != str(request.workflow_run_id)
                or review.get("repository") != REPOSITORY
                or review.get("native_version") != NATIVE_VERSION
                or review.get("digest") != record.get(key)
            ):
                raise DemoError("HARNESS_WORKFLOW_EXACT_REVIEW_REQUIRED")
            previous, target = (
                ("AWAITING_PLAN_APPROVAL", "RUNNING")
                if phase == "EXECUTE"
                else ("AWAITING_MERGE_APPROVAL", "PUBLISHING")
            )
            self.service.ledger.transition(run_id, owner, previous, target)
            await self.service.event(
                run_id,
                "approve-plan" if phase == "EXECUTE" else "approve-merge",
                {
                    "approved_by": owner,
                    "digest": review["digest"],
                    "workflow_approval_request_id": authority["approval_request_id"],
                },
            )
            operation, expected = (
                (self.service.execute, "AWAITING_MERGE_APPROVAL")
                if phase == "EXECUTE"
                else (self.service.publish, "SUCCEEDED")
            )
        self.service.launch(run_id, lambda: operation(run_id))
        await self.service.jobs[str(run_id)]
        record = self.service.ledger.get(run_id, owner)
        if record["status"] != expected:
            code = record.get("error_code", "HARNESS_WORKFLOW_STAGE_FAILED")
            raise DemoError(code.replace("DEMO_", "HARNESS_", 1))
        if phase == "PUBLISH" and not record["publish_receipt"].get("github_pushed"):
            raise DemoError("HARNESS_WORKFLOW_REMOTE_PUBLICATION_MISSING")
        return record

    async def execute(self, request, on_state_change):
        started, phase, reserved, record = datetime.now(timezone.utc), request.executor.operation, False, None
        await on_state_change(TaskRunStatus.RUNNING, None)
        try:
            phase, authority = self.parse(request)
            saved = self.saved(request, phase, reserve=True)
            if saved:
                await on_state_change(TaskRunStatus(saved.status.value), saved)
                return saved
            reserved = True
            record = await self.operation(request, phase, authority)
            result = self.result(request, phase, started, record=record)
        except asyncio.CancelledError:
            job = self.service.jobs.get(str(session_id(request.workflow_run_id)))
            if job:
                job.cancel()
                await asyncio.gather(job, return_exceptions=True)
            raise
        except DemoError as exc:
            result = self.result(request, phase, started, error=exc.code)
        except Exception:  # noqa: BLE001 - do not publish secrets in transport or filesystem exceptions.
            result = self.result(request, phase, started, error="HARNESS_WORKFLOW_STAGE_FAILED")
        if reserved:
            self.retain(request, phase, result)
        await on_state_change(TaskRunStatus(result.status.value), result)
        return result

    async def get_saved_result(self, request):
        phase, _ = self.parse(request)
        return self.saved(request, phase)

    async def resume(self, request, on_state_change):
        started = datetime.now(timezone.utc)
        try:
            result = await self.get_saved_result(request)
            if result is None:
                raise DemoError("HARNESS_WORKFLOW_STAGE_INTERRUPTED")
        except DemoError as exc:
            result = self.result(request, request.executor.operation, started, error=exc.code)
        # Observation only. Never replay a model call, commit or push after restart.
        await on_state_change(TaskRunStatus(result.status.value), result)
        return result


def create_workflow_executor():
    return HarnessWorkflowExecutor(get_demo_service()) if workflow_enabled() else None
