import asyncio
from datetime import datetime, timezone
from hashlib import sha256

import pytest
from pydantic import ValidationError

from langflow.adlc.source_access import Evidence, SourceError, SourceGateway, SourceGrant, SourceRef


class RecordingReader:
    def __init__(self, body="evidence"):
        self.body = body
        self.calls = []

    async def read(self, ref):
        self.calls.append(ref)
        return Evidence(
            id="e1",
            source=ref,
            version="source-version",
            fetched_at=datetime(2026, 11, 25, tzinfo=timezone.utc),
            body=self.body,
            sha256=sha256(self.body.encode("utf-8")).hexdigest(),
        )


def github_ref(repo="org/allowed", **locator):
    return SourceRef(
        kind="github_file",
        connection_id="gh",
        resource_id=repo,
        locator={"path": "README.md", **locator},
        revision="a" * 40,
    )


def table_ref(table_id=None):
    return SourceRef(
        kind="lark_base_record",
        connection_id="lark",
        resource_id="shared-base",
        locator={"table_id": table_id} if table_id else {},
    )


def test_cross_project_resource_is_denied_before_any_reader_call():
    grant = SourceGrant(
        project_id="p1",
        run_id="r1",
        principal_id="normalizer",
        resources={"gh": {"org/allowed"}},
    )
    reader = RecordingReader()
    gateway = SourceGateway({("gh", "github_file"): reader})

    with pytest.raises(SourceError, match="SOURCE_SCOPE_DENIED"):
        asyncio.run(gateway.read(grant, [github_ref(), github_ref("org/private")]))

    assert reader.calls == []


def test_projects_sharing_a_base_get_only_their_own_tables():
    resources = {"lark": {"shared-base"}}
    project_one = SourceGrant(
        project_id="p1",
        run_id="r1",
        principal_id="normalizer",
        resources=resources,
        locator_allowlists={"lark:shared-base": {"table_id": ("table-1",)}},
    )
    project_two = SourceGrant(
        project_id="p2",
        run_id="r2",
        principal_id="normalizer",
        resources=resources,
        locator_allowlists={"lark:shared-base": {"table_id": ("table-2",)}},
    )
    reader = RecordingReader()
    gateway = SourceGateway({("lark", "lark_base_record"): reader})

    own_tables = asyncio.run(gateway.read(project_one, [table_ref("table-1")]))
    own_tables += asyncio.run(gateway.read(project_two, [table_ref("table-2")]))
    assert [evidence.source.locator["table_id"] for evidence in own_tables] == ["table-1", "table-2"]

    for grant, restricted_ref in (
        (project_one, table_ref("table-2")),
        (project_two, table_ref("table-1")),
        (project_one, table_ref()),
    ):
        with pytest.raises(SourceError, match="SOURCE_SCOPE_DENIED"):
            asyncio.run(gateway.read(grant, [restricted_ref]))

    assert reader.calls == [table_ref("table-1"), table_ref("table-2")]


def test_grant_is_isolated_from_mutation_of_its_inputs():
    resources = {"gh": {"org/allowed"}, "lark": {"shared-base"}}
    allowed_tables = ["table-1"]
    table_constraints = {"table_id": allowed_tables}
    locator_allowlists = {"lark:shared-base": table_constraints}
    grant = SourceGrant(
        project_id="p1",
        run_id="r1",
        principal_id="normalizer",
        resources=resources,
        locator_allowlists=locator_allowlists,
    )
    reader = RecordingReader()
    gateway = SourceGateway({("gh", "github_file"): reader, ("lark", "lark_base_record"): reader})

    resources["gh"].add("org/private")
    resources["gh"] = {"org/other-private"}
    allowed_tables.append("table-2")
    table_constraints["table_id"] = ["table-3"]
    locator_allowlists.clear()

    for restricted_ref in (
        github_ref("org/private"),
        github_ref("org/other-private"),
        table_ref("table-2"),
        table_ref("table-3"),
    ):
        with pytest.raises(SourceError, match="SOURCE_SCOPE_DENIED"):
            asyncio.run(gateway.read(grant, [restricted_ref]))
    assert reader.calls == []

    allowed = asyncio.run(gateway.read(grant, [github_ref(), table_ref("table-1")]))
    assert [evidence.source for evidence in allowed] == [github_ref(), table_ref("table-1")]


def test_grant_mappings_cannot_be_reassigned():
    grant = SourceGrant(
        project_id="p1",
        run_id="r1",
        principal_id="normalizer",
        resources={"lark": {"shared-base"}},
        locator_allowlists={"lark:shared-base": {"table_id": ("table-1",)}},
    )

    with pytest.raises(TypeError):
        grant.resources["lark"] = frozenset({"another-base"})
    with pytest.raises(TypeError):
        grant.locator_allowlists["lark:shared-base"] = {}
    with pytest.raises(TypeError):
        grant.locator_allowlists["lark:shared-base"]["table_id"] = ("table-2",)


def test_pending_locator_cannot_change_after_batch_authorization():
    pending = table_ref("table-1")

    class MutatingReader(RecordingReader):
        async def read(self, ref):
            with pytest.raises(TypeError):
                pending.locator["table_id"] = "private-table"
            return await super().read(ref)

    grant = SourceGrant(
        project_id="p1",
        run_id="r1",
        principal_id="normalizer",
        resources={"lark": {"shared-base"}},
        locator_allowlists={"lark:shared-base": {"table_id": ("table-1",)}},
    )
    reader = MutatingReader()
    gateway = SourceGateway({("lark", "lark_base_record"): reader})

    asyncio.run(gateway.read(grant, [table_ref("table-1"), pending]))

    assert reader.calls == [table_ref("table-1"), table_ref("table-1")]


@pytest.fixture
def github_grant():
    return SourceGrant(
        project_id="p1",
        run_id="r1",
        principal_id="normalizer",
        resources={"gh": {"org/allowed"}},
        max_reads=2,
        max_bytes=4,
    )


@pytest.mark.parametrize(
    ("reader_key", "code"),
    [
        (("other", "github_file"), "SOURCE_CONNECTION_UNAVAILABLE"),
        (("gh", "github_issue"), "SOURCE_CONNECTION_UNAVAILABLE"),
    ],
)
def test_missing_reader_for_connection_and_kind(github_grant, reader_key, code):
    reader = RecordingReader()
    gateway = SourceGateway({reader_key: reader})

    with pytest.raises(SourceError, match=code):
        asyncio.run(gateway.read(github_grant, [github_ref()]))

    assert reader.calls == []


@pytest.mark.parametrize("argument", ["token", "base_url", "authorization"])
def test_credential_or_endpoint_argument_is_denied_before_reader(github_grant, argument):
    reader = RecordingReader()
    gateway = SourceGateway({("gh", "github_file"): reader})

    with pytest.raises(SourceError, match="SOURCE_ARGUMENTS_INVALID"):
        asyncio.run(gateway.read(github_grant, [github_ref(**{argument: "unexpected"})]))

    assert reader.calls == []


@pytest.mark.parametrize(
    ("ref_count", "body", "code", "call_count"),
    [
        (3, "x", "SOURCE_READ_LIMIT", 0),
        (2, "a\u00e9", "SOURCE_CONTEXT_LIMIT", 2),
        (2, "aaa\u00e9", "SOURCE_CONTEXT_LIMIT", 1),
    ],
)
def test_read_and_utf8_byte_limits(github_grant, ref_count, body, code, call_count):
    reader = RecordingReader(body)
    gateway = SourceGateway({("gh", "github_file"): reader})

    with pytest.raises(SourceError, match=code):
        asyncio.run(gateway.read(github_grant, [github_ref()] * ref_count))

    assert len(reader.calls) == call_count


@pytest.mark.parametrize(("count", "body"), [(1, "ab\u00e9"), (2, "\u00e9")])
def test_authorized_reads_return_evidence_at_exact_limits(github_grant, count, body):
    reader = RecordingReader(body)
    gateway = SourceGateway({("gh", "github_file"): reader})
    refs = [github_ref(path=f"file-{index}.md") for index in range(count)]

    evidence = asyncio.run(gateway.read(github_grant, refs))

    assert reader.calls == refs
    assert [item.model_dump() for item in evidence] == [
        {
            "id": "e1",
            "source": ref.model_dump(),
            "version": "source-version",
            "fetched_at": datetime(2026, 11, 25, tzinfo=timezone.utc),
            "body": body,
            "sha256": sha256(body.encode("utf-8")).hexdigest(),
            "complete": True,
        }
        for ref in refs
    ]


def test_related_work_kind_routes_to_its_own_reader(github_grant):
    ref = SourceRef(
        kind="github_related_work",
        connection_id="gh",
        resource_id="org/allowed",
        locator={"keywords": "source access"},
    )
    reader = RecordingReader("work")
    gateway = SourceGateway({("gh", "github_related_work"): reader})

    evidence = asyncio.run(gateway.read(github_grant, [ref]))

    assert [item.source for item in evidence] == [ref]
    assert reader.calls == [ref]


def test_source_ref_cannot_embed_a_grant():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        SourceRef(kind="github_file", connection_id="gh", resource_id="org/private", grant={})


def test_source_ref_cannot_reuse_another_connection_locator_key():
    grant = SourceGrant(
        project_id="p1",
        run_id="r1",
        principal_id="normalizer",
        resources={"lark": {"shared:base"}},
        locator_allowlists={"lark:shared:base": {"table_id": ("table-1",)}},
    )
    reader = RecordingReader()
    gateway = SourceGateway({("lark", "lark_base_record"): reader})
    valid_ref = SourceRef(
        kind="lark_base_record",
        connection_id="lark",
        resource_id="shared:base",
        locator={"table_id": "table-1"},
    )

    evidence = asyncio.run(gateway.read(grant, [valid_ref]))
    assert [item.source for item in evidence] == [valid_ref]

    with pytest.raises(SourceError, match="SOURCE_SCOPE_DENIED"):
        asyncio.run(
            gateway.read(
                grant,
                [valid_ref.model_copy(update={"locator": {"table_id": "table-2"}})],
            )
        )
    assert reader.calls == [valid_ref]

    with pytest.raises(ValidationError, match="connection_id"):
        SourceRef(
            kind="lark_base_record",
            connection_id="lark:shared",
            resource_id="base",
            locator={"table_id": "table-1"},
        )


def test_server_grant_rejects_a_connection_id_that_collides_with_a_locator_key():
    with pytest.raises(ValidationError, match="resources"):
        SourceGrant(
            project_id="p1",
            run_id="r1",
            principal_id="normalizer",
            resources={"lark": {"shared:base"}, "lark:shared": {"base"}},
            locator_allowlists={"lark:shared:base": {"table_id": ("table-1",)}},
        )


# A snapshot must retain its provenance when passed between workflow stages.
def test_source_locator_cannot_be_mutated_after_validation():
    from langflow.adlc.source_access.models import SourceRef

    ref = SourceRef(kind="github_file", connection_id="gh", resource_id="org/repo", locator={"path": "a"})
    with pytest.raises(TypeError):
        ref.locator["path"] = "b"
