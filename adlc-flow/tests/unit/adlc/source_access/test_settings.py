import asyncio

import httpx
import pytest

from langflow.adlc.source_access.models import SourceError, SourceRef
from langflow.adlc.source_access.settings import build_source_gateway, resolve_project_grant


def settings():
    return {
        "projects": {"p": {"principals": ["svc"], "resources": {"lk": ["doc"]}}},
        "connections": [
            {
                "connection_id": "lk",
                "provider": "lark",
                "app_id": "app",
                "tenant_id": "tenant",
                "app_secret_ref": "SECRET",
            }
        ],
    }


def test_current_project_binding_and_revocation():
    config = settings()
    assert resolve_project_grant("svc", "p", "r", config).resources["lk"] == {"doc"}
    config["projects"]["p"]["principals"] = []
    for principal, project in [("svc", "p"), ("other", "p"), ("svc", "unknown")]:
        with pytest.raises(SourceError, match="SOURCE_SCOPE_DENIED"):
            resolve_project_grant(principal, project, "r", config)


def test_field_restrictions_fail_closed():
    config = settings()
    config["projects"]["p"]["locator_allowlists"] = {"lk:doc": {"field_id": ["secret"]}}
    with pytest.raises(SourceError, match="SOURCE_FIELD_SCOPE_UNSUPPORTED"):
        resolve_project_grant("svc", "p", "r", config)


def test_wiring_uses_app_identity_and_owned_client_lifecycle():
    async def scenario():
        seen = []

        def respond(request):
            seen.append(request)
            if "auth/v3" in request.url.path:
                return httpx.Response(200, json={"code": 0, "tenant_access_token": "fake", "expire": 7200})
            assert request.headers["authorization"] == "Bearer fake"
            return httpx.Response(200, json={"code": 0, "data": {"content": "document"}})

        def factory(**kwargs):
            assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
            return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

        gateway = build_source_gateway(settings(), lambda name: "test-secret", factory)
        try:
            result = await gateway.read(
                resolve_project_grant("svc", "p", "r", settings()),
                [SourceRef(kind="lark_document", connection_id="lk", resource_id="doc")],
            )
            assert result[0].body and result[0].complete
            assert len(seen) == 2
        finally:
            await gateway.aclose()

    asyncio.run(scenario())


def test_missing_secret_is_sanitized():
    def unavailable(name):
        raise RuntimeError("sensitive backend detail")

    with pytest.raises(SourceError, match="^SOURCE_CONNECTION_UNAVAILABLE$"):
        build_source_gateway(settings(), unavailable)


@pytest.mark.parametrize(
    "change",
    [
        {"principals": "svc-other"},
        {"resources": {"lk": "doc"}},
        {"locator_allowlists": {"lk:typo": {"table_id": ["tbl"]}}},
    ],
)
def test_malformed_binding_cannot_widen_access(change):
    config = settings()
    config["projects"]["p"].update(change)
    with pytest.raises(SourceError, match="SOURCE_CONFIGURATION_INVALID"):
        resolve_project_grant("svc", "p", "r", config)
