# ruff: noqa: PLR2004, S101
"""API tests for the intent intake endpoint (plan package G3)."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient

from langflow.adlc.orchestrator_intake import (
    DEFAULT_INTENT_TYPE,
    classify_intent,
    reset_intent_proposal_store,
)
from langflow.adlc.orchestrator_routing import ORCHESTRATOR_ROUTING_ENV
from langflow.adlc.orchestrator_plugin.interface import IntentType
from langflow.api.v1 import adlc as adlc_api
from langflow.services.auth.utils import get_current_active_user

ENDPOINT = "/api/v1/adlc/intents/plan-proposals"


def _app(user) -> FastAPI:
    app = FastAPI()
    app.include_router(adlc_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_active_user] = lambda: user
    return app


def _user():
    return SimpleNamespace(id=uuid4(), username="owner")


@pytest.fixture(autouse=True)
def _fresh_intake_state(monkeypatch: pytest.MonkeyPatch):
    reset_intent_proposal_store()
    yield
    reset_intent_proposal_store()


def _routing_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ORCHESTRATOR_ROUTING_ENV, "1")


def _routing_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ORCHESTRATOR_ROUTING_ENV, raising=False)


async def test_propose_returns_plan_proposal(monkeypatch) -> None:
    """Explicit intent_type → one plugin proposal; nothing runs or materializes."""
    _routing_on(monkeypatch)
    app = _app(_user())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            ENDPOINT,
            json={
                "description": "Implement a heart app",
                "intent_type": "code_generation",
                "required_capabilities": ["code_generation"],
                "context": {"source": "unit-test"},
            },
        )

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["intent_type"] == "code_generation"
    assert payload["classification"]["source"] == "explicit"
    assert payload["classification"]["heuristic"] == "keyword-rules-v1"
    assert payload["plugin_id"] == "monarch"
    assert payload["plan_id"]
    assert payload["intent_id"]
    assert len(payload["steps"]) == 1
    step = payload["steps"][0]
    assert step["name"]
    assert step["description"] == "Implement a heart app"
    assert "code_generation" in step["required_capabilities"]
    assert step["depends_on"] == []
    assert payload["metadata"]


async def test_proposal_is_idempotent_per_key(monkeypatch) -> None:
    """Same idempotency key replays the exact same proposal payload."""
    _routing_on(monkeypatch)
    app = _app(_user())
    body = {"description": "Implement a heart app", "idempotency_key": "proposal-key-1"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        first = await client.post(ENDPOINT, json=body)
        second = await client.post(ENDPOINT, json=body)

    assert first.status_code == status.HTTP_200_OK
    assert second.status_code == status.HTTP_200_OK
    assert first.json() == second.json()


async def test_idempotency_key_is_owner_scoped(monkeypatch) -> None:
    """Different owners with the same key get independent proposals."""
    _routing_on(monkeypatch)
    app_one = _app(_user())
    app_two = _app(SimpleNamespace(id=uuid4(), username="other"))
    body = {"description": "Review the module", "idempotency_key": "shared-key"}

    async with (
        AsyncClient(transport=ASGITransport(app=app_one), base_url="http://testserver") as client_one,
        AsyncClient(transport=ASGITransport(app=app_two), base_url="http://testserver") as client_two,
    ):
        first = await client_one.post(ENDPOINT, json=body)
        second = await client_two.post(ENDPOINT, json=body)

    assert first.status_code == status.HTTP_200_OK
    assert second.status_code == status.HTTP_200_OK
    assert first.json()["plan_id"] != second.json()["plan_id"]


async def test_unauthenticated_request_is_rejected() -> None:
    """The intake endpoint requires login like every other adlc endpoint."""
    app = FastAPI()
    app.include_router(adlc_api.router, prefix="/api/v1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(ENDPOINT, json={"description": "Implement a feature"})

    assert response.status_code in {
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    }


def test_intent_type_is_classified_by_keyword_rules() -> None:
    """Verbalize → classify: simple keyword rules, no LLM, audit trail."""
    intent_type, keywords = classify_intent("Hãy review module thanh toán giúp tôi")
    assert intent_type is IntentType.CODE_REVIEW
    assert keywords

    intent_type, keywords = classify_intent("Viết unit test cho service")
    assert intent_type is IntentType.TESTING
    assert keywords

    intent_type, keywords = classify_intent("Lập kế hoạch cho sprint tới")
    assert intent_type is IntentType.PLANNING
    assert keywords

    intent_type, keywords = classify_intent("Tạo trang web trái tim Hello World")
    assert intent_type is DEFAULT_INTENT_TYPE  # catch-all: code_generation
    assert keywords == []


async def test_heuristic_classification_is_audited(monkeypatch) -> None:
    """Missing intent_type → rule-based classification recorded in the response."""
    _routing_on(monkeypatch)
    app = _app(_user())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            ENDPOINT,
            json={"description": "Hãy review module thanh toán giúp tôi"},
        )

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["intent_type"] == "code_review"
    assert payload["classification"]["source"] == "heuristic"
    assert payload["classification"]["matched_keywords"]


async def test_invalid_intent_type_returns_422(monkeypatch) -> None:
    _routing_on(monkeypatch)
    app = _app(_user())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            ENDPOINT,
            json={"description": "Do something", "intent_type": "not-a-real-type"},
        )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_invalid_capability_returns_422(monkeypatch) -> None:
    _routing_on(monkeypatch)
    app = _app(_user())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            ENDPOINT,
            json={
                "description": "Do something",
                "required_capabilities": ["not-a-capability"],
            },
        )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_flag_off_returns_503_with_disabled_code(monkeypatch) -> None:
    """Flag off → 503 with code ORCHESTRATOR_ROUTING_DISABLED."""
    _routing_off(monkeypatch)
    app = _app(_user())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(ENDPOINT, json={"description": "Implement a feature"})

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json()["detail"]["code"] == "ORCHESTRATOR_ROUTING_DISABLED"
