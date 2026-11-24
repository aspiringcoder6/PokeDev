# ruff: noqa: INP001, PLR2004, S101, S106

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from langflow.adlc.expressions import TemplateResolutionError, resolve_templates
from langflow.adlc.metrics import thresholds_from_environment
from langflow.adlc.models import (
    Actor,
    CreateWorkflowRunRequest,
    ExecutorTarget,
    MockArtifactSpec,
    TaskRunStatus,
    WorkflowRunStatus,
)
from langflow.adlc.notifications import (
    AdlcNotification,
    AdlcNotificationKind,
    CompositeAdlcNotificationSink,
    InMemoryAdlcNotificationSink,
    WebhookAdlcNotificationSink,
)
from langflow.adlc.run_service import AdlcRunService

SYSTEM_ACTOR = Actor(type="SYSTEM", id="test", display_name="Test")


def _roots() -> dict[str, Any]:
    return {
        "run": {"id": "run-1", "name": "Demo", "run_number": 3},
        "task": {
            "coding": {
                "status": "SUCCEEDED",
                "output": {"outputs": {"summary": "Result for coding.", "scores": [1, 2, 3]}},
            },
        },
    }


def test_full_match_preserves_value_type() -> None:
    resolved = resolve_templates("{{task.coding.output.outputs.scores}}", roots=_roots())
    assert resolved == [1, 2, 3]
    assert resolve_templates("{{run.run_number}}", roots=_roots()) == 3


def test_embedded_reference_substitutes_as_text() -> None:
    resolved = resolve_templates("prefix {{run.name}} suffix", roots=_roots())
    assert resolved == "prefix Demo suffix"


def test_nested_structures_resolve_deeply() -> None:
    payload = {
        "objective": "{{task.coding.output.outputs.summary}}",
        "labels": ["run-{{run.run_number}}", "{{run.id}}"],
        "nested": {"score": "{{task.coding.output.outputs.scores.2}}"},
        "untouched": 7,
    }
    resolved = resolve_templates(payload, roots=_roots())
    assert resolved["objective"] == "Result for coding."
    assert resolved["labels"] == ["run-3", "run-1"]
    assert resolved["nested"]["score"] == 3
    assert resolved["untouched"] == 7


def test_unknown_root_and_missing_paths_fail_strictly() -> None:
    with pytest.raises(TemplateResolutionError, match="unknown root"):
        resolve_templates("{{secrets.token}}", roots=_roots())
    with pytest.raises(TemplateResolutionError, match="missing key"):
        resolve_templates("{{task.coding.output.outputs.absent}}", roots=_roots())
    with pytest.raises(TemplateResolutionError, match="not a container"):
        resolve_templates("{{task.coding.status.deep}}", roots=_roots())
    with pytest.raises(TemplateResolutionError, match="out of range"):
        resolve_templates("{{task.coding.output.outputs.scores.9}}", roots=_roots())


def test_plain_values_pass_through() -> None:
    assert resolve_templates(None, roots=_roots()) is None
    assert resolve_templates(5, roots=_roots()) == 5
    assert resolve_templates("no templates", roots=_roots()) == "no templates"


def _artifact_spec(key: str) -> MockArtifactSpec:
    return MockArtifactSpec(kind="DOCUMENT", name=f"{key}.txt", media_type="text/plain", content=f"content {key}")


def _definition(key: str, *, dependencies: list[str] | None = None, **overrides: Any) -> Any:
    from langflow.adlc.models import AdlcTaskDefinition

    payload: dict[str, Any] = {
        "id": uuid4(),
        "key": key,
        "name": key.replace("_", " ").title(),
        "task_type": "IMPLEMENTATION",
        "dependencies": dependencies or [],
        "predetermined_output": {"summary": f"Result for {key}."},
        "artifact": _artifact_spec(key),
        "delay_ms": 0,
    }
    payload.update(overrides)
    return AdlcTaskDefinition(**payload)


async def test_dispatch_resolves_templates_from_upstream_output() -> None:
    service = AdlcRunService()
    definitions = [
        _definition("coding"),
        _definition(
            "finalize",
            dependencies=["coding"],
            direct_inputs={
                "spec": "{{task.coding.output.summary}}",
                "meta": {"run": "{{run.name}}", "labels": ["run-{{run.run_number}}"]},
            },
        ),
    ]
    run = await service.start_run(
        flow_id=uuid4(),
        flow_name="Template slice",
        definitions=definitions,
        request=CreateWorkflowRunRequest(flowId=uuid4(), executionMode="LEGACY_FLOW", delayMs=0),
        owner_id="owner-1",
    )
    assert run.status is WorkflowRunStatus.SUCCEEDED
    final_task = run.tasks[-1]
    assert final_task.status is TaskRunStatus.SUCCEEDED
    assert final_task.request is not None
    payload = final_task.request.input["namedInputs"]
    assert payload["spec"] == "Result for coding."
    assert payload["meta"] == {"run": "Template slice", "labels": ["run-1"]}


async def test_dispatch_fails_run_on_unresolvable_template() -> None:
    service = AdlcRunService()
    definitions = [
        _definition(
            "orphan",
            direct_inputs={"spec": "{{task.missing.output}}"},
        ),
    ]
    run = await service.start_run(
        flow_id=uuid4(),
        flow_name="Broken template slice",
        definitions=definitions,
        request=CreateWorkflowRunRequest(flowId=uuid4(), executionMode="LEGACY_FLOW", delayMs=0),
        owner_id="owner-1",
    )
    assert run.status is WorkflowRunStatus.PAUSED
    task = run.tasks[0]
    assert task.status is TaskRunStatus.FAILED
    assert task.result is not None
    assert task.result.error is not None
    assert task.result.error.details.get("exception_type") == "AdlcRunStateError"


def _notification() -> AdlcNotification:
    return AdlcNotification(
        kind=AdlcNotificationKind.APPROVAL_REQUIRED,
        workflow_run_id=uuid4(),
        message="Approval required.",
    )


def test_composite_notification_sink_fans_out() -> None:
    first = InMemoryAdlcNotificationSink()
    second = InMemoryAdlcNotificationSink()
    composite = CompositeAdlcNotificationSink((first, second))
    composite.notify(_notification())
    assert len(first.notifications) == 1
    assert len(second.notifications) == 1


def test_webhook_sink_posts_payload_and_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    class _Response:
        status_code = 200

    def _post(url: str, *, json: dict[str, Any], headers: dict[str, str], timeout: float) -> _Response:
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return _Response()

    monkeypatch.setattr("langflow.adlc.notifications.httpx.post", _post)
    sink = WebhookAdlcNotificationSink("http://hooks.internal/adlc", token="secret-token")
    notification = _notification()
    sink.notify(notification)

    assert len(calls) == 1
    assert calls[0]["url"] == "http://hooks.internal/adlc"
    assert calls[0]["headers"]["authorization"] == "Bearer secret-token"
    assert calls[0]["json"]["kind"] == "APPROVAL_REQUIRED"


def test_webhook_sink_swallows_network_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    failure = ConnectionError("down")

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise failure

    monkeypatch.setattr("langflow.adlc.notifications.httpx.post", _boom)
    sink = WebhookAdlcNotificationSink("http://hooks.internal/adlc")
    sink.notify(_notification())


def test_thresholds_from_environment_overrides_and_ignores_garbage() -> None:
    thresholds = thresholds_from_environment(
        {
            "ADLC_METRICS_FAILURE_RATE": "0.25",
            "ADLC_METRICS_FAILURE_MIN_SAMPLES": "5",
            "ADLC_METRICS_DEADLINE_BREACHES": "2",
            "ADLC_METRICS_DENIED_DISPATCHES": "4",
        }
    )
    assert thresholds.failure_rate == 0.25
    assert thresholds.failure_min_samples == 5
    assert thresholds.deadline_breaches == 2
    assert thresholds.denied_dispatches == 4

    fallback = thresholds_from_environment({"ADLC_METRICS_FAILURE_RATE": "not-a-number"})
    assert fallback == thresholds_from_environment({})
    assert fallback.failure_rate == 0.5


async def test_run_service_uses_composed_notification_sink() -> None:
    notifications = InMemoryAdlcNotificationSink()
    service = AdlcRunService(notification_sink=notifications)
    definitions = [
        _definition("coding"),
        _definition(
            "approval",
            dependencies=["coding"],
            task_type="APPROVAL",
            executor_target=ExecutorTarget(service="control:approval", operation="after-task"),
            approval_gate="ACTION",
        ),
    ]
    run = await service.start_run(
        flow_id=uuid4(),
        flow_name="Notify slice",
        definitions=definitions,
        request=CreateWorkflowRunRequest(flowId=uuid4(), executionMode="LEGACY_FLOW", delayMs=0),
        owner_id="owner-1",
    )
    assert run.status is WorkflowRunStatus.WAITING_APPROVAL
    kinds = [notification.kind for notification in notifications.notifications]
    assert AdlcNotificationKind.APPROVAL_REQUIRED in kinds
