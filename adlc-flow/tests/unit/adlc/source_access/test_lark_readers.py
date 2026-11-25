import asyncio
import json

import httpx
import pytest

from langflow.adlc.source_access import SourceError, SourceGateway, SourceGrant, SourceRef
from langflow.adlc.source_access.http import lark_pages
from langflow.adlc.source_access.lark_base import LarkBaseReader
from langflow.adlc.source_access.lark_messages import LarkMessageReader


class Tokens:
    async def get(self, force=False):  # noqa: FBT002
        return "renewed" if force else "tenant"


def source(kind="lark_thread", resource="chat1", **locator):
    return SourceRef(kind=kind, connection_id="lark", resource_id=resource, locator=locator)


def grant(*resources):
    return SourceGrant(project_id="p", run_id="r", principal_id="reader", resources={"lark": set(resources)})


def run(respond, ref, *, reader_type=LarkMessageReader, resources=None, **limits):
    async def scenario():
        def guarded(request):
            assert request.url.host == "open.larksuite.com"
            assert request.headers["authorization"] in {"Bearer tenant", "Bearer renewed"}
            assert "cookie" not in request.headers
            return respond(request)

        async with httpx.AsyncClient(
            base_url="https://open.larksuite.com",
            trust_env=False,
            cookies={"session": "personal"},
            auth=("personal", "test"),
            transport=httpx.MockTransport(guarded),
        ) as client:
            reader = reader_type(client, Tokens(), **limits)
            gateway = SourceGateway({("lark", ref.kind): reader})
            return (await gateway.read(grant(*(resources if resources is not None else [ref.resource_id])), [ref]))[0]

    return asyncio.run(scenario())


def ok(**data):
    return httpx.Response(200, json={"code": 0, "data": data})


def messages(*items, cursor=""):
    return ok(items=list(items), has_more=bool(cursor), page_token=cursor)


def msg(mid, *, root="", stamp="100000", **overrides):
    return {
        "message_id": mid,
        "root_id": root,
        "parent_id": root,
        "chat_id": "chat1",
        "thread_id": "thread1",
        "sender": {"id": "author", "id_type": "open_id", "sender_type": "user"},
        "msg_type": "text",
        "create_time": stamp,
        "update_time": stamp,
        "deleted": False,
        "body": {"content": json.dumps({"text": mid})},
        **overrides,
    }


def test_thread_binds_in_chat_then_reads_pages_preserving_root_and_author():
    seen = []

    def respond(request):
        p = request.url.params
        assert request.url.path == "/open-apis/im/v1/messages"
        assert int(p["page_size"]) <= 50
        seen.append((p["container_id_type"], p["container_id"], p.get("page_token")))
        if p["container_id_type"] == "chat":
            return messages(msg("root"))
        assert "start_time" not in p
        assert "end_time" not in p
        if "page_token" not in p:
            return messages(msg("r1", root="root"), cursor="next")
        return messages(msg("r2", root="root", stamp="101000"), msg("older", root="root", stamp="99000"))

    evidence = run(respond, source(thread_id="thread1", start_time="100", end_time="102"))
    assert seen == [("chat", "chat1", None), ("thread", "thread1", None), ("thread", "thread1", "next")]
    assert evidence.complete
    items = json.loads(evidence.body)["messages"]
    assert [i["message_id"] for i in items] == ["root", "r1", "r2"]
    assert items[1]["root_id"] == items[1]["parent_id"] == "root"
    assert items[1]["sender"]["id"] == "author"
    assert items[1]["create_time"] == "100000"
    assert items[1]["content"]["text"] == "r1"


@pytest.mark.parametrize("bad_at", ["chat", "thread"])
def test_mismatched_chat_is_denied_before_its_content_is_returned(bad_at):
    def respond(request):
        mode = request.url.params["container_id_type"]
        if mode == bad_at:
            return messages(msg("x", chat_id="other"))
        assert mode == "chat"
        return messages(msg("root"))

    with pytest.raises(SourceError, match="SOURCE_SCOPE_DENIED"):
        run(respond, source(thread_id="thread1"))


def test_root_discovery_cap_never_reads_unbound_thread():
    def respond(request):
        assert request.url.params["container_id_type"] == "chat"
        return messages(msg("other-root", thread_id="other"), cursor="opaque")

    evidence = run(respond, source(thread_id="thread1"), max_pages=1)
    assert not evidence.complete
    assert "opaque" in evidence.body
    assert "other-root" not in evidence.body


def test_repeated_cursor_fails_closed():
    def respond(request):
        cursor = request.url.params.get("page_token")
        return messages(cursor="b" if cursor == "a" else "a")

    with pytest.raises(SourceError, match="SOURCE_PAGINATION_INVALID"):
        run(respond, source(start_time="100", end_time="101"))


@pytest.mark.parametrize(("code", "status"), [(230002, 400), (99991672, 403)])
def test_revoked_access_errors_are_sanitized(code, status):
    def respond(_request):
        return httpx.Response(status, json={"code": code, "msg": "private provider detail"})

    with pytest.raises(SourceError, match=r"^SOURCE_ACCESS_DENIED$") as error:
        run(respond, source(start_time="1", end_time="2"))
    assert error.value.__context__ is None


@pytest.mark.parametrize(("code", "status"), [(99991663, 400), (99991663, 200), (1, 401)])
def test_token_expiry_refreshes_only_once_per_read(code, status):
    auth = []

    def respond(request):
        auth.append(request.headers["authorization"])
        return httpx.Response(status, json={"code": code})

    with pytest.raises(SourceError, match="SOURCE_APP_AUTH_FAILED"):
        run(respond, source(start_time="1", end_time="2"))
    assert auth == ["Bearer tenant", "Bearer renewed"]


def test_attachment_is_fetched_only_from_bound_message_resource():
    def respond(request):
        if request.url.path == "/open-apis/im/v1/messages":
            return messages(
                msg(
                    "m",
                    thread_id="",
                    msg_type="file",
                    body={
                        "content": json.dumps(
                            {"file_key": "key", "file_name": "notes.txt", "url": "https://other.invalid/path"}
                        )
                    },
                )
            )
        assert request.url.path == "/open-apis/im/v1/messages/m/resources/key"
        assert request.url.params["type"] == "file"
        return httpx.Response(200, content=b"project notes", headers={"content-type": "application/octet-stream"})

    evidence = run(respond, source(start_time="100", end_time="102"))
    assert evidence.complete
    assert "project notes" in evidence.body


@pytest.mark.parametrize(
    "bad",
    [
        {"body": {}},
        {"msg_type": "image", "body": {"content": '{"image_key":"image"}'}},
        {"deleted": True},
        {"body": {"content": "{}"}},
    ],
)
def test_unavailable_message_content_has_an_explicit_finding(bad):
    evidence = run(lambda _: messages(msg("m", thread_id="", **bad)), source(start_time="100", end_time="102"))
    assert not evidence.complete
    assert json.loads(evidence.body)["findings"]


def test_bounded_transport_rejects_over_limit_responses():
    with pytest.raises(SourceError, match="SOURCE_CONTENT_LIMIT"):
        run(lambda _: messages(msg("m")), source(start_time="1", end_time="2"), max_response_bytes=10)


def base(**locator):
    return source("lark_base_record", "app", table_id="tbl", **locator)


TABLE = "/open-apis/bitable/v1/apps/app/tables/tbl"
TITLE = {"field_id": "fldTitle", "field_name": "Title", "type": 1}
FILE = {"field_id": "fldFile", "field_name": "Files", "type": 17}
FILTER = {"conjunction": "and", "conditions": [{"field_name": "Title", "operator": "contains", "value": ["plan"]}]}


def test_base_direct_record_and_attachments_are_bound_to_schema_and_record():
    paths = []

    def respond(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/fields"):
            return messages(TITLE, FILE)
        if request.url.path.endswith("/records/rec"):
            return ok(
                record={
                    "record_id": "rec",
                    "last_modified_time": 123,
                    "fields": {
                        "Title": "plan",
                        "Files": [
                            {
                                "file_token": "one",
                                "name": "file.txt",
                                "type": "text/plain",
                                "url": "https://other.invalid",
                            },
                            {"file_token": "two", "name": "scan.pdf", "type": "application/pdf", "size": 9},
                        ],
                    },
                }
            )
        assert request.url.path == "/open-apis/drive/v1/medias/one/download"
        assert json.loads(request.url.params["extra"]) == {
            "bitablePerm": {"tableId": "tbl", "attachments": {"fldFile": {"rec": ["one"]}}}
        }
        return httpx.Response(200, content=b"attached text")

    evidence = run(respond, base(record_id="rec"), reader_type=LarkBaseReader)
    assert paths == [TABLE + "/fields", TABLE + "/records/rec", "/open-apis/drive/v1/medias/one/download"]
    body = json.loads(evidence.body)
    assert body["schema"] == [TITLE, FILE]
    assert body["records"][0]["last_modified_time"] == 123
    cells = body["records"][0]["fields"]
    assert cells["Title"] == "plan"
    assert cells["Files"][0]["text"] == "attached text"
    assert cells["Files"][1]["kind"] == "base_attachment"
    assert cells["Files"][1]["file_token"] == "two"  # noqa: S105 - fixture media ID
    assert "other.invalid" not in evidence.body
    assert "text" not in cells["Files"][1]
    assert not evidence.complete
    assert "unsupported_attachment_format" in body["findings"]


def test_base_search_paginates_schema_then_search_post():
    seen = []

    def respond(request):
        path, cursor = request.url.path, request.url.params.get("page_token")
        seen.append((path, cursor))
        if path.endswith("/fields"):
            return messages(FILE, cursor="s2") if cursor is None else messages(TITLE)
        assert request.method == "POST"
        assert json.loads(request.content)["filter"] == FILTER
        return messages(
            {"record_id": "r1" if cursor is None else "r2", "fields": {"Title": "plan"}},
            cursor="p2" if cursor is None else "",
        )

    evidence = run(respond, base(filter=json.dumps(FILTER)), reader_type=LarkBaseReader)
    assert seen == [
        (TABLE + "/fields", None),
        (TABLE + "/fields", "s2"),
        (TABLE + "/records/search", None),
        (TABLE + "/records/search", "p2"),
    ]
    assert evidence.complete
    assert [r["record_id"] for r in json.loads(evidence.body)["records"]] == ["r1", "r2"]


def test_base_search_rejects_non_schema_field_before_reading_records():
    def respond(request):
        assert request.url.path == TABLE + "/fields"
        return messages(FILE)

    with pytest.raises(SourceError, match="SOURCE_ARGUMENTS_INVALID"):
        run(respond, base(filter=json.dumps(FILTER)), reader_type=LarkBaseReader)


def test_schema_page_cap_does_not_read_records_without_schema():
    def respond(request):
        assert request.url.path == TABLE + "/fields"
        return messages(TITLE, cursor="more")

    evidence = run(respond, base(record_id="rec"), reader_type=LarkBaseReader, max_pages=1)
    assert not evidence.complete
    assert json.loads(evidence.body)["continuation"]["schema"] == "more"


def test_direct_record_response_must_match_before_media_io():
    def respond(request):
        if request.url.path.endswith("/fields"):
            return messages(FILE)
        assert request.url.path == TABLE + "/records/rec"
        return ok(record={"record_id": "wrong", "fields": {"Files": [{"file_token": "t", "name": "pw.txt"}]}})

    with pytest.raises(SourceError, match="SOURCE_SCOPE_DENIED"):
        run(respond, base(record_id="rec"), reader_type=LarkBaseReader)


def test_wiki_requires_grants_for_alias_and_actual_document_before_content_read():
    ref = source("lark_document", "alias", wiki="1")
    seen = []

    def respond(request):
        seen.append(request.url.path)
        assert request.url.path == "/open-apis/wiki/v2/spaces/get_node"
        assert request.url.params["token"] == "alias"  # noqa: S105 - fixture Wiki node ID
        return ok(node={"node_token": "alias", "obj_type": "docx", "obj_token": "actual"})

    for resources in (["actual"], ["alias"]):
        with pytest.raises(SourceError, match="SOURCE_SCOPE_DENIED"):
            run(respond, ref, reader_type=LarkBaseReader, resources=resources)
    assert seen == ["/open-apis/wiki/v2/spaces/get_node"]


def test_wiki_evidence_round_trips_requested_actual_binding_and_distinct_identity():
    ref = source("lark_document", "alias", wiki="1")
    actual = source("lark_document", "actual")

    def respond(request):
        if request.url.path.endswith("/get_node"):
            return ok(node={"node_token": "alias", "obj_token": "actual", "obj_type": "docx"})
        assert request.url.path == "/open-apis/docx/v1/documents/actual/raw_content"
        return ok(content="decision text")

    indirect = run(respond, ref, reader_type=LarkBaseReader, resources=["alias", "actual"])
    direct = run(respond, actual, reader_type=LarkBaseReader)
    assert indirect.source == actual
    assert indirect.requested_source == ref
    assert direct.requested_source is None
    assert direct.id != indirect.id
    assert direct.body == indirect.body
    assert direct.sha256 == indirect.sha256
    assert direct.complete
    assert type(indirect).model_validate_json(indirect.model_dump_json()) == indirect


def test_structured_document_reads_block_pages_and_reports_unparsed_media():
    def respond(request):
        assert request.url.path == "/open-apis/docx/v1/documents/doc/blocks"
        if "page_token" not in request.url.params:
            return messages(
                {"block_id": "doc", "block_type": 1, "page": {"elements": []}, "children": ["image"]}, cursor="next"
            )
        return messages({"block_id": "image", "block_type": 27, "image": {"token": "f"}})

    evidence = run(respond, source("lark_document", "doc", blocks="1"), reader_type=LarkBaseReader)
    assert not evidence.complete
    assert [b["block_id"] for b in json.loads(evidence.body)["blocks"]] == ["doc", "image"]


@pytest.mark.parametrize(
    ("ref", "reader"),
    [
        (source(start_time="7", end_time="2"), LarkMessageReader),
        (base(record_id="../other"), LarkBaseReader),
        (base(record_id="r", view_id="view"), LarkBaseReader),
        (source("lark_document", "doc", url="https://example.invalid"), LarkBaseReader),
    ],
)
def test_closed_locators_before_any_io(ref, reader):
    with pytest.raises(SourceError, match="SOURCE_ARGUMENTS_INVALID"):
        run(lambda _: pytest.fail("unexpected HTTP request"), ref, reader_type=reader)


@pytest.mark.parametrize(("ref", "code"), [(base(record_id="r"), 1254302), (source("lark_document", "d"), 1770032)])
def test_provider_denied_base_and_document_never_fall_back_to_user(ref, code):
    with pytest.raises(SourceError, match=r"^SOURCE_ACCESS_DENIED$"):
        run(lambda _: httpx.Response(200, json={"code": code, "msg": "private"}), ref, reader_type=LarkBaseReader)


@pytest.mark.parametrize(
    ("more", "expected"), [(True, ([{"message_id": "m"}], False, "next")), (False, ([{"message_id": "m"}], True, None))]
)
def test_shared_page_walker_returns_items_completeness_and_continuation(more, expected):
    async def fetch(_cursor):
        return {"code": 0, "data": {"items": [{"message_id": "m"}], "has_more": more, "page_token": "next"}}

    assert asyncio.run(lark_pages(fetch, max_pages=1)) == expected


def test_shared_page_walker_rejects_logical_provider_error():
    async def fetch(_cursor):
        return {"code": 1, "msg": "private provider detail"}

    with pytest.raises(SourceError, match=r"^SOURCE_LARK_READ_FAILED$"):
        asyncio.run(lark_pages(fetch))


@pytest.mark.parametrize("changes", [{"thread_id": "other"}, {"root_id": "elsewhere"}])
def test_bound_thread_rejects_reply_with_other_thread_or_root(changes):
    def respond(request):
        if request.url.params["container_id_type"] == "chat":
            return messages(msg("root"))
        return messages(msg("reply", root="root", **changes))

    with pytest.raises(SourceError, match="SOURCE_SCOPE_DENIED"):
        run(respond, source(thread_id="thread1"))


def test_page_cap_on_thread_replies_keeps_partial_messages_and_cursor():
    def respond(request):
        if request.url.params["container_id_type"] == "chat":
            return messages(msg("root"))
        return messages(msg("reply", root="root"), cursor="pending")

    evidence = run(respond, source(thread_id="thread1"), max_pages=1)
    assert not evidence.complete
    assert json.loads(evidence.body)["continuation"]["messages"] == "pending"
    assert "reply" in evidence.body


def test_no_transport_request_for_unsafe_clients():
    for settings in [{"base_url": "https://example.invalid"}, {"trust_env": True}, {"follow_redirects": True}]:

        async def scenario(options):
            async with httpx.AsyncClient(**options) as client:
                LarkBaseReader(client, Tokens())

        with pytest.raises(SourceError, match="SOURCE_APP_AUTH_FAILED"):
            asyncio.run(scenario({"base_url": "https://open.larksuite.com", "trust_env": False, **settings}))


def test_linked_document_cell_is_inert_and_requires_its_own_read():
    def respond(request):
        if request.url.path.endswith("/fields"):
            return messages({"field_name": "Decision", "field_id": "link", "type": 15})
        assert request.url.path == TABLE + "/records/rec"
        return ok(
            record={
                "record_id": "rec",
                "fields": {"Decision": {"text": "Doc", "link": "https://a.larksuite.com/docx/actual"}},
            }
        )

    evidence = run(respond, base(record_id="rec"), reader_type=LarkBaseReader)
    assert not evidence.complete
    assert "linked_content_not_collected" in evidence.body
    assert "https://a.larksuite.com/docx/actual" in evidence.body


@pytest.mark.parametrize("payload", [b"\x01\x02binary", b"%PDF-1.4\nobject", b"bad utf8: \xff"])
def test_mislabeled_binary_attachment_is_not_extracted_as_text(payload):
    def respond(request):
        if request.url.path == "/open-apis/im/v1/messages":
            return messages(
                msg("m", thread_id="", msg_type="file", body={"content": '{"file_key":"k","file_name":"note.txt"}'})
            )
        return httpx.Response(200, content=payload)

    evidence = run(respond, source(start_time="100", end_time="102"))
    body = json.loads(evidence.body)
    assert not evidence.complete
    assert "unsupported_attachment_format" in body["findings"]
    assert "text" not in body["messages"][0]["attachment"]


def test_malformed_message_type_is_sanitized():
    with pytest.raises(SourceError, match="SOURCE_RESPONSE_INVALID"):
        run(lambda _: messages(msg("m", thread_id="", msg_type={})), source(start_time="100", end_time="101"))
