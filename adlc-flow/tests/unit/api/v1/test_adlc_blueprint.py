# ruff: noqa: PLR2004, S101

"""Blueprint generation coexists with flow ownership and the saved graph."""

from __future__ import annotations

import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from langflow.adlc.blueprint_generator import BlueprintGenerationError
from langflow.adlc.packages.defaults import create_default_package_access_policy, create_default_package_registry
from langflow.api.v1 import adlc as adlc_api


def _context(monkeypatch):
    user = SimpleNamespace(id=uuid4())
    flow = SimpleNamespace(
        id=uuid4(),
        locked=False,
        data={
            "nodes": [{"id": "note-1", "type": "noteNode", "data": {}}],
            "edges": [],
            "viewport": {"x": 10, "y": 20, "zoom": 1},
            "adlc": {
                "document_type": "WORKFLOW_DEFINITION",
                "schema_version": "0.1",
                "version": 3,
                "metadata": {"project": "keep-existing-context"},
            },
        },
    )
    session = SimpleNamespace(add=Mock(), commit=AsyncMock())
    generate = AsyncMock(
        return_value=(
            {
                "stages": [
                    {
                        "key": "implement",
                        "name": "Implement feature",
                        "package_id": "coding-agent",
                        "version": "0.1.0",
                        "inputs": {"requirement": "Build the feature."},
                    }
                ],
                "edges": [],
            },
            "dsh-session-1",
        )
    )
    monkeypatch.setattr(adlc_api, "get_authorized_flow_for_write", AsyncMock(return_value=flow))
    monkeypatch.setattr(adlc_api, "get_node_package_registry", create_default_package_registry)
    monkeypatch.setattr(adlc_api, "get_package_access_policy", create_default_package_access_policy)
    monkeypatch.setattr(adlc_api, "generate_blueprint_document", generate)
    return flow, user, session, generate


async def _generate(flow, user, session):
    return await adlc_api.generate_workflow_blueprint(
        flow.id,
        adlc_api.BlueprintGenerateRequest(requirement="Build the feature."),
        current_user=user,
        session=session,
    )


async def test_generated_blueprint_is_saved_with_existing_notes_and_context(monkeypatch) -> None:
    flow, user, session, generate = _context(monkeypatch)
    result = await _generate(flow, user, session)
    assert result.applied
    assert result.flow_id == str(flow.id)
    assert result.dsh_session_id == "dsh-session-1"
    assert result.stages[0].package == "coding-agent@0.1.0"
    assert flow.data["nodes"][0]["id"] == "note-1"
    assert flow.data["adlc"]["metadata"] == {"project": "keep-existing-context"}
    assert flow.data["adlc"]["version"] == 3
    assert flow.data["viewport"] == {"x": 10, "y": 20, "zoom": 1}
    assert result.data == flow.data
    session.add.assert_called_once_with(flow)
    session.commit.assert_awaited_once()
    generate.assert_awaited_once()
    adlc_api.get_authorized_flow_for_write.assert_awaited_once_with(
        flow_id=flow.id,
        current_user=user,
        session=session,
    )


@pytest.mark.parametrize("reason", ["locked", "components"])
async def test_generation_rejects_uneditable_flows_before_dispatch(monkeypatch, reason) -> None:
    flow, user, session, generate = _context(monkeypatch)
    if reason == "locked":
        flow.locked = True
    else:
        flow.data["nodes"].append({"id": "component", "type": "genericNode", "data": {}})
    original = copy.deepcopy(flow.data)
    with pytest.raises(HTTPException) as exc_info:
        await _generate(flow, user, session)
    assert exc_info.value.status_code == 409
    assert flow.data == original
    generate.assert_not_awaited()
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


async def test_generation_requires_write_permission_before_dispatch(monkeypatch) -> None:
    flow, user, session, generate = _context(monkeypatch)
    adlc_api.get_authorized_flow_for_write.side_effect = HTTPException(status_code=403)
    with pytest.raises(HTTPException) as exc_info:
        await _generate(flow, user, session)
    assert exc_info.value.status_code == 403
    generate.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.parametrize(
    "code",
    [
        "BLUEPRINT_GENERATION_SDK_UNAVAILABLE",
        "BLUEPRINT_GENERATION_NOT_CONFIGURED",
        "BLUEPRINT_GENERATION_CONFIGURATION_INVALID",
    ],
)
async def test_unavailable_generation_leaves_saved_flow_unchanged(monkeypatch, code) -> None:
    flow, user, session, generate = _context(monkeypatch)
    original = copy.deepcopy(flow.data)
    generate.side_effect = BlueprintGenerationError(
        code,
        "Blueprint generation is unavailable.",
        http_status=503,
    )
    with pytest.raises(HTTPException) as exc_info:
        await _generate(flow, user, session)
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == code
    assert exc_info.value.detail["category"] == "DEPENDENCY"
    assert flow.data == original
    session.add.assert_not_called()
    session.commit.assert_not_awaited()
