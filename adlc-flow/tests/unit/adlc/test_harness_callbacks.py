# ruff: noqa: INP001, S101, S105, S106

from __future__ import annotations

from datetime import datetime, timezone
from http import HTTPStatus
from uuid import UUID, uuid4

import pytest

from langflow.adlc.harness_callbacks import (
    HARNESS_CALLBACK_MAX_BODY_BYTES,
    HarnessCallbackError,
    HarnessCallbackReceiver,
    HarnessCallbackSettings,
    sign_harness_delivery,
)
from langflow.adlc.harness_models import HarnessCorrelation, HarnessResultDelivery, HarnessSessionResult
from langflow.adlc.models import ExecutorTarget, TaskRequest, TaskResultStatus


def _request() -> TaskRequest:
    workflow_run_id = uuid4()
    task_run_id = uuid4()
    attempt_id = uuid4()
    return TaskRequest(
        request_id=uuid4(),
        workflow_run_id=workflow_run_id,
        task_run_id=task_run_id,
        attempt_id=attempt_id,
        task_definition_id=uuid4(),
        task_type="coding",
        name="Harness task",
        executor=ExecutorTarget(service="agent-provider:deepseek-harness", operation="coding-task"),
        input={"requirement": "Implement it."},
        context={},
        dependency_task_run_ids=[],
        constraints={"timeout_ms": 1000},
        idempotency_key=f"{workflow_run_id}:{task_run_id}:{attempt_id}",
        requested_at=datetime.now(timezone.utc),
    )


def _delivery(request: TaskRequest, *, delivery_id: UUID | None = None) -> HarnessResultDelivery:
    now = datetime.now(timezone.utc)
    return HarnessResultDelivery(
        delivery_id=delivery_id or uuid4(),
        callback_ref="adlc-primary",
        created_at=now,
        result=HarnessSessionResult(
            session_id="session-1",
            correlation=HarnessCorrelation(
                request_id=request.request_id,
                workflow_run_id=request.workflow_run_id,
                task_run_id=request.task_run_id,
                attempt_id=request.attempt_id,
            ),
            status=TaskResultStatus.SUCCEEDED,
            output={"summary": "done"},
            artifacts=[],
            error=None,
            started_at=now,
            completed_at=now,
        ),
    )


async def test_signed_callback_is_idempotent_and_accepts_result_before_session_binding() -> None:
    secret = "callback-secret"
    request = _request()
    receiver = HarnessCallbackReceiver(HarnessCallbackSettings(secret=secret), clock=lambda: 1_700_000_000)
    await receiver.register_attempt(request)
    delivery = _delivery(request)
    body = delivery.model_dump_json().encode()
    timestamp = "1700000000"
    signature = sign_harness_delivery(secret, timestamp, body)

    first = await receiver.receive(
        body,
        delivery_id=str(delivery.delivery_id),
        timestamp=timestamp,
        signature=signature,
    )
    replay = await receiver.receive(
        body,
        delivery_id=str(delivery.delivery_id),
        timestamp=timestamp,
        signature=signature,
    )
    bound = await receiver.bind_session(request.attempt_id, "session-1")

    assert first.duplicate is False
    assert replay.duplicate is True
    assert bound.result == delivery.result
    assert await receiver.wait_for_result(request.attempt_id, timeout_seconds=0.01) == delivery.result


async def test_callback_rejects_an_invalid_signature_without_accepting_result() -> None:
    request = _request()
    receiver = HarnessCallbackReceiver(HarnessCallbackSettings(secret="callback-secret"), clock=lambda: 10)
    await receiver.register_attempt(request)
    delivery = _delivery(request)
    body = delivery.model_dump_json().encode()

    with pytest.raises(HarnessCallbackError) as error:
        await receiver.receive(
            body,
            delivery_id=str(delivery.delivery_id),
            timestamp="10",
            signature="sha256:invalid",
        )

    assert error.value.code == "HARNESS_CALLBACK_SIGNATURE_INVALID"
    assert error.value.http_status == HTTPStatus.UNAUTHORIZED


async def test_callback_rejects_an_oversized_body_before_authentication() -> None:
    receiver = HarnessCallbackReceiver(HarnessCallbackSettings(secret="callback-secret"))

    with pytest.raises(HarnessCallbackError) as error:
        await receiver.receive(
            b"x" * (HARNESS_CALLBACK_MAX_BODY_BYTES + 1),
            delivery_id=None,
            timestamp=None,
            signature=None,
        )

    assert error.value.code == "HARNESS_CALLBACK_INVALID"
    assert error.value.http_status == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
