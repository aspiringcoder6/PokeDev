# ruff: noqa: INP001, S101

"""Unit tests for the run_service → Evidence Plane mirror.

Terminal task results must land in the Evidence Plane as best-effort
observability: metric evidence per task outcome plus patch evidence per
SOURCE_PATCH artifact whose diff payload is still cached. Failures in the
mirror must never break orchestration.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

from langflow.adlc.artifact_payload_store import (
    BoundedArtifactPayloadStore,
    SourcePatchFile,
    SourcePatchSnapshot,
)
from langflow.adlc.evidence_plane import (
    EvidencePlaneService,
    EvidenceType,
    InMemoryEvidenceStore,
    ValidationStatus,
)
from langflow.adlc.legacy_flow_normalizer import normalize_legacy_flow_graph
from langflow.adlc.models import (
    Artifact,
    Checksum,
    CreateWorkflowRunRequest,
    ExecutorTarget,
    TaskResult,
    TaskResultStatus,
    TaskRun,
    TaskRunStatus,
    WorkflowExecutionMode,
    WorkflowRun,
    WorkflowRunStatus,
)
from langflow.adlc.run_service import AdlcRunService


def _graph() -> dict:
    names = ["Plan", "Implement"]
    nodes = [
        {
            "id": name.lower().replace(" ", "_"),
            "type": "genericNode",
            "data": {"type": name.replace(" ", ""), "node": {"display_name": name}},
        }
        for name in names
    ]
    return {
        "nodes": nodes,
        "edges": [{"source": "plan", "target": "implement"}],
    }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _patch_artifact(payload: bytes) -> Artifact:
    workflow_run_id = uuid4()
    task_run_id = uuid4()
    attempt_id = uuid4()
    return Artifact(
        artifact_id=uuid4(),
        workflow_run_id=workflow_run_id,
        task_run_id=task_run_id,
        attempt_id=attempt_id,
        kind="SOURCE_PATCH",
        name="patch.diff",
        media_type="text/x-diff",
        uri="store://artifact-payloads/patch",
        size_bytes=len(payload),
        checksum=Checksum(algorithm="SHA256", value=hashlib.sha256(payload).hexdigest()),
        producer="agent-provider:opencode",
        created_at=_now(),
    )


def _patch_payload_bytes() -> bytes:
    snapshot = SourcePatchSnapshot(
        format="harness-git-diff-v1",
        files=[SourcePatchFile(file="src/app.py", patch="@@ -1 +1 @@\n", additions=1, deletions=1)],
        reported_files=["src/app.py"],
    )
    return snapshot.model_dump_json().encode("utf-8")


async def test_terminal_task_results_are_mirrored_as_metric_evidence() -> None:
    flow_id = uuid4()
    plane = EvidencePlaneService(store=InMemoryEvidenceStore())
    service = AdlcRunService(evidence_plane=plane)
    run = await service.start_run(
        flow_id=flow_id,
        flow_name="Evidence slice",
        definitions=normalize_legacy_flow_graph(flow_id, _graph()),
        request=CreateWorkflowRunRequest(flowId=flow_id, executionMode="LEGACY_FLOW", delayMs=0),
        owner_id="owner-1",
    )

    assert run.status is WorkflowRunStatus.SUCCEEDED
    metrics = plane.query_evidence_by_type(EvidenceType.METRIC, workflow_run_id=run.id)
    assert len(metrics) == 2  # one per task
    statuses = {evidence.payload["status"] for evidence in metrics}
    assert statuses == {"SUCCEEDED"}
    producers = {evidence.producer for evidence in metrics}
    assert producers == {"mock-agent-adapter"}


async def test_evidence_plane_failure_does_not_break_the_run() -> None:
    flow_id = uuid4()

    class ExplodingPlane:
        def submit_evidence(self, evidence: object) -> None:  # noqa: ARG002
            raise RuntimeError("evidence plane is down")

    service = AdlcRunService(evidence_plane=ExplodingPlane())  # type: ignore[arg-type]
    run = await service.start_run(
        flow_id=flow_id,
        flow_name="Resilient slice",
        definitions=normalize_legacy_flow_graph(flow_id, _graph()),
        request=CreateWorkflowRunRequest(flowId=flow_id, executionMode="LEGACY_FLOW", delayMs=0),
        owner_id="owner-1",
    )

    assert run.status is WorkflowRunStatus.SUCCEEDED


def test_source_patch_evidence_payload_is_built_from_payload_store() -> None:
    payload = _patch_payload_bytes()
    artifact = _patch_artifact(payload)
    store = BoundedArtifactPayloadStore()
    store.retain(artifact, payload)

    service = AdlcRunService(artifact_payloads=store)

    evidence_payload = service._source_patch_evidence_payload(artifact)  # noqa: SLF001

    assert evidence_payload is not None
    assert evidence_payload["artifact_id"] == str(artifact.artifact_id)
    assert evidence_payload["files"] == [
        {"file": "src/app.py", "patch": "@@ -1 +1 @@\n", "additions": 1, "deletions": 1}
    ]


def test_source_patch_evidence_payload_returns_none_when_payload_missing() -> None:
    payload = _patch_payload_bytes()
    artifact = _patch_artifact(payload)
    service = AdlcRunService(artifact_payloads=BoundedArtifactPayloadStore())

    evidence_payload = service._source_patch_evidence_payload(artifact)  # noqa: SLF001

    assert evidence_payload is None


def test_mirror_task_evidence_emits_metric_and_patch_evidence() -> None:
    payload = _patch_payload_bytes()
    artifact = _patch_artifact(payload)
    store = BoundedArtifactPayloadStore()
    store.retain(artifact, payload)

    plane = EvidencePlaneService(store=InMemoryEvidenceStore())
    service = AdlcRunService(artifact_payloads=store, evidence_plane=plane)

    task = TaskRun(
        id=artifact.task_run_id,
        workflow_run_id=artifact.workflow_run_id,
        task_definition_id=uuid4(),
        key="implement",
        name="Implement",
        task_type="IMPLEMENTATION",
        status=TaskRunStatus.RUNNING,
        dependency_task_run_ids=[],
        executor=ExecutorTarget(service=artifact.producer, operation="coding-task"),
        current_attempt_id=artifact.attempt_id,
        artifacts=[artifact],
    )
    run = WorkflowRun(
        id=artifact.workflow_run_id,
        workflow_key="mirror-slice",
        execution_mode=WorkflowExecutionMode.LEGACY_FLOW,
        flow_id=uuid4(),
        name="Mirror",
        status=WorkflowRunStatus.RUNNING,
        tasks=[task],
        created_at=_now(),
    )
    result = TaskResult(
        request_id=uuid4(),
        workflow_run_id=run.id,
        task_run_id=task.id,
        attempt_id=artifact.attempt_id,
        status=TaskResultStatus.SUCCEEDED,
        output={},
        artifacts=[artifact],
        error=None,
        started_at=_now(),
        completed_at=_now(),
    )

    service._mirror_task_evidence(run, task, result)  # noqa: SLF001

    metrics = plane.query_evidence_by_type(EvidenceType.METRIC, workflow_run_id=run.id)
    patches = plane.query_evidence_by_type(EvidenceType.PATCH, workflow_run_id=run.id)
    assert len(metrics) == 1
    assert metrics[0].payload["event"] == "task_completed"
    assert metrics[0].payload["status"] == "SUCCEEDED"
    assert metrics[0].task_run_id == task.id
    assert metrics[0].attempt_id == artifact.attempt_id
    assert len(patches) == 1
    assert patches[0].validation_status is ValidationStatus.VALID
    assert patches[0].payload["files"][0]["file"] == "src/app.py"
