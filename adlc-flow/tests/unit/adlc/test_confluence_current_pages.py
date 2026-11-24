"""A readable Cloud page body is not proof the page is still published."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import mcp
import mcp.client.streamable_http
import pytest

from langflow.adlc.document_intake import ConfluencePages
from langflow.adlc.vai_services import ServiceCheckError
from test_document_intake import intake, approved


@pytest.mark.asyncio
@pytest.mark.parametrize("current_ids", [[], ["456"], ["123"]])
async def test_cloud_body_from_trash_cannot_be_used_without_current_publication(monkeypatch, current_ids):
    calls = []

    @asynccontextmanager
    async def transport(*args, **kwargs):
        yield None, None, None

    class Session:
        def __init__(self, *args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def initialize(self):
            pass

        async def call_tool(self, name, arguments):
            calls.append((name, arguments))
            value = (
                {"id": "123", "title": "Deleted page still readable by ID", "version": 9, "body": "<p>Requirements</p>"}
                if name == "confluence_get_page"
                else {"results": [{"id": identity} for identity in current_ids]}
            )
            return SimpleNamespace(isError=False, structuredContent=value, content=[])

    monkeypatch.setattr(mcp, "ClientSession", Session)
    monkeypatch.setattr(mcp.client.streamable_http, "streamablehttp_client", transport)
    if "123" in current_ids:
        page = await ConfluencePages().read("123")
        assert page["version"] == 9 and page["body"] == "Requirements"
    else:
        with pytest.raises(ServiceCheckError, match="INTAKE_PAGE_NOT_CURRENT"):
            await ConfluencePages().read("123")
    assert calls == [
        ("confluence_get_page", {"page_id": "123"}),
        ("confluence_search", {"cql": "id = 123 AND type = page", "limit": 1}),
    ]


@pytest.mark.asyncio
async def test_deleted_source_revokes_approval_keeps_cache_and_requires_review_after_restore(intake):
    service, _, pages = intake
    row = await approved(intake)
    original = row["page_body"]

    def deleted():
        raise ServiceCheckError("INTAKE_PAGE_NOT_CURRENT", 409)

    pages.before_return = deleted
    with pytest.raises(ServiceCheckError, match="INTAKE_PAGE_NOT_CURRENT"):
        await service.decide("owner", 1, service.contract_digest(row), "approve")
    deleted_row = service.get("owner", 1)
    assert deleted_row["approval"] is None
    assert deleted_row["state"] == "SOURCE_UNAVAILABLE"
    assert deleted_row["page_body"] == original
    assert not deleted_row.get("run_id")
    pages.before_return = None
    restored = await service.refresh("owner", 1, fresh=True)
    assert restored["state"] == "NEEDS_REVIEW" and restored["approval"] is None
