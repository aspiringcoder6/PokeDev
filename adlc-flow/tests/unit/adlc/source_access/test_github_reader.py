import asyncio
import base64
import json
import subprocess
from hashlib import sha256

import httpx
import pytest

from langflow.adlc.source_access import SourceError, SourceGateway, SourceGrant, SourceRef, make_evidence
from langflow.adlc.source_access.github import GitHubReader

COMMIT = "a" * 40
BLOB = "b" * 40
STAMP = "2026-11-24T12:30:00Z"
REPO_PATH = "/repos/org/repo"


class Tokens:
    async def get(self, force=False):  # noqa: FBT002
        return "test-refreshed-token" if force else "test-installation-token"


def source(kind="github_file", *, resource_id="org/repo", locator=None, revision=None):
    return SourceRef(
        kind=kind,
        connection_id="gh",
        resource_id=resource_id,
        locator=locator if locator is not None else {"path": "README.md"},
        revision=revision,
    )


def grant():
    return SourceGrant(project_id="p1", run_id="r1", principal_id="collector", resources={"gh": {"org/repo"}})


def run_reader(respond, operation, **limits):
    async def scenario():
        async with httpx.AsyncClient(
            base_url="https://api.github.com",
            transport=httpx.MockTransport(respond),
            trust_env=False,
            auth=("personal", "password"),
            cookies={"session": "personal-session"},
        ) as client:
            return await operation(GitHubReader(client, Tokens(), **limits))

    return asyncio.run(scenario())


def file_response(content=b"hello", **overrides):
    return httpx.Response(
        200,
        json={
            "type": "file",
            "sha": BLOB,
            "size": len(content),
            "encoding": "base64",
            "content": base64.b64encode(content).decode("ascii"),
            **overrides,
        },
    )


def issue(number, title="Feature change", body="Details", state="open", *, pr=False):
    return {
        "id": number * 100,
        "number": number,
        "title": title,
        "body": body,
        "state": state,
        "updated_at": STAMP,
        "labels": [{"name": "enhancement"}],
        **({"pull_request": {"url": f"https://api.github.com{REPO_PATH}/pulls/{number}"}} if pr else {}),
    }


def page(items, path=None, *, page_number=2):
    headers = {"Link": f'<https://api.github.com{path}?per_page=100&page={page_number}>; rel="next"'} if path else {}
    return httpx.Response(200, json=items, headers=headers)


def comment(comment_id, body):
    return {"id": comment_id, "body": body, "user": {"login": "reviewer"}, "updated_at": STAMP}


def test_file_read_uses_pinned_commit_without_checkout(monkeypatch):
    def no_subprocess(*_args, **_kwargs):
        pytest.fail("remote source reads must not spawn Git or other subprocesses")

    monkeypatch.setattr(subprocess, "Popen", no_subprocess)

    def respond(request):
        assert request.method == "GET"
        assert request.url.raw_path == f"{REPO_PATH}/contents/docs/Read%20me.md?ref={COMMIT}".encode()
        assert request.headers["Authorization"] == "Bearer test-installation-token"
        assert "Cookie" not in request.headers
        return file_response()

    ref = source(locator={"path": "docs/Read me.md"}, revision=COMMIT)
    evidence = run_reader(respond, lambda reader: reader.read(ref))

    assert evidence.source == ref
    assert evidence.version == BLOB
    assert evidence.body == "hello"
    assert evidence.sha256 == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    assert evidence.complete


@pytest.mark.parametrize(("requested", "encoded"), [("feature/readiness", "feature%2Freadiness"), (None, "HEAD")])
def test_gateway_resolves_requested_ref_to_commit(requested, encoded):
    def respond(request):
        assert request.url.raw_path == f"{REPO_PATH}/commits/{encoded}".encode()
        return httpx.Response(200, json={"sha": COMMIT})

    async def resolve(reader):
        gateway = SourceGateway({("gh", "github_file"): reader})
        original = source(revision=requested)
        pinned = await gateway.resolve_revision(grant(), original)
        assert original.revision == requested
        assert pinned.locator is not original.locator
        return pinned

    assert run_reader(respond, resolve) == source(revision=COMMIT)


@pytest.mark.parametrize(
    ("ref", "has_reader", "expected"),
    [
        (source(resource_id="other/private", revision="main"), True, "SOURCE_SCOPE_DENIED"),
        (source("github_issue", locator={"number": "1"}), True, "SOURCE_ARGUMENTS_INVALID"),
        (source(revision="main"), False, "SOURCE_CONNECTION_UNAVAILABLE"),
    ],
)
def test_gateway_denies_revision_before_network(ref, has_reader, expected):
    def respond(_request):
        pytest.fail("rejected revisions must not access GitHub")

    async def resolve(reader):
        gateway = SourceGateway({("gh", "github_file"): reader} if has_reader else {})
        return await gateway.resolve_revision(grant(), ref)

    with pytest.raises(SourceError, match=expected):
        run_reader(respond, resolve)


def test_make_evidence_has_canonical_identity_and_body_hash():
    one = source("github_related_work", locator={"keywords": "foo", "state": "open"})
    two = source("github_related_work", locator={"state": "open", "keywords": "foo"})
    evidence = make_evidence(one, "body", STAMP)

    assert make_evidence(two, "body", STAMP).id == evidence.id
    assert make_evidence(two, "different", STAMP).id != evidence.id
    assert make_evidence(two, "body", "different").id != evidence.id
    assert evidence.sha256 == sha256(b"body").hexdigest()
    assert evidence.fetched_at.utcoffset().total_seconds() == 0


@pytest.mark.parametrize(
    "ref",
    [
        source(resource_id="org/repo/extra", revision=COMMIT),
        source(resource_id="org/..", revision=COMMIT),
        source(resource_id="https://github.com/org/repo", revision=COMMIT),
        source(resource_id="org/repo.git", revision=COMMIT),
        source(revision="main"),
        source(locator={"path": "../secret"}, revision=COMMIT),
        source(locator={"path": "docs//README"}, revision=COMMIT),
        source(locator={"path": "docs/%2e%2e/secret"}, revision=COMMIT),
        source(locator={"path": "docs\\README"}, revision=COMMIT),
        source(locator={"path": "docs", "tree": "1"}, revision=COMMIT),
        source(locator={"tree": "true"}, revision=COMMIT),
        source("github_issue", locator={"number": "0"}),
        source("github_issue", locator={"number": "1/other"}),
        source("github_issue", locator={"number": "1", "repo": "other"}),
        source("github_related_work", locator={"keywords": "x" * 201}),
        source("github_related_work", locator={"keywords": "work", "state": "invalid"}),
        source("github_related_work", locator={"keywords": "work", "type": "invalid"}),
        source("github_related_work", locator={"keywords": "work", "extra": "invalid"}),
    ],
)
def test_invalid_locators_do_not_reach_transport(ref):
    def respond(_request):
        pytest.fail("invalid locators must not access GitHub")

    with pytest.raises(SourceError, match="SOURCE_ARGUMENTS_INVALID"):
        run_reader(respond, lambda reader: reader.read(ref))


@pytest.mark.parametrize("revision", ["feature/../private", "feature/%2e%2e", "feature//private", "a?foo=bar", ""])
def test_invalid_requested_revision_does_not_reach_transport(revision):
    def respond(_request):
        pytest.fail("invalid refs must not access GitHub")

    with pytest.raises(SourceError, match="SOURCE_ARGUMENTS_INVALID"):
        run_reader(respond, lambda reader: reader.resolve_revision("org/repo", revision))


def test_invalid_resolved_sha_is_rejected():
    with pytest.raises(SourceError, match="SOURCE_RESPONSE_INVALID"):
        run_reader(
            lambda _request: httpx.Response(200, json={"sha": "main"}),
            lambda reader: reader.resolve_revision("org/repo", "HEAD"),
        )


@pytest.mark.parametrize(
    ("response", "limits", "error"),
    [
        (file_response(b"\x00\x01"), {}, "SOURCE_UNSUPPORTED_CONTENT"),
        (file_response(b"\xff\xfe"), {}, "SOURCE_UNSUPPORTED_CONTENT"),
        (file_response(content=b"x", encoding="none"), {}, "SOURCE_UNSUPPORTED_CONTENT"),
        (file_response(content=b"long"), {"max_file_bytes": 3}, "SOURCE_CONTENT_LIMIT"),
        (file_response(content=b"long", size=1), {"max_file_bytes": 3}, "SOURCE_CONTENT_LIMIT"),
        (file_response(sha="blob"), {}, "SOURCE_RESPONSE_INVALID"),
        (file_response(content=b"x", encoding=False), {}, "SOURCE_RESPONSE_INVALID"),
        (httpx.Response(200, json={"type": "dir"}), {}, "SOURCE_UNSUPPORTED_CONTENT"),
    ],
)
def test_file_rejects_unsupported_or_oversized_content(response, limits, error):
    with pytest.raises(SourceError, match=error):
        run_reader(lambda _request: response, lambda reader: reader.read(source(revision=COMMIT)), **limits)


def test_file_rejects_malformed_base64():
    response = httpx.Response(
        200, json={"type": "file", "sha": BLOB, "size": 3, "encoding": "base64", "content": "a!a="}
    )

    with pytest.raises(SourceError, match="SOURCE_RESPONSE_INVALID"):
        run_reader(lambda _request: response, lambda reader: reader.read(source(revision=COMMIT)))


def test_recursive_tree_marks_provider_truncation():
    def respond(request):
        assert request.url.raw_path == f"{REPO_PATH}/git/trees/{COMMIT}?recursive=1".encode()
        return httpx.Response(
            200,
            json={"sha": BLOB, "truncated": True, "tree": [{"type": "blob", "path": "README.md", "sha": COMMIT}]},
        )

    evidence = run_reader(respond, lambda reader: reader.read(source(locator={"tree": "1"}, revision=COMMIT)))

    assert evidence.version == BLOB
    assert json.loads(evidence.body)["tree"] == [{"type": "blob", "path": "README.md", "sha": COMMIT}]
    assert not evidence.complete


def test_issue_collects_two_comment_pages():
    actions = []

    def respond(request):
        actions.append(request.url.raw_path.decode())
        if request.url.path.endswith("/issues/7"):
            return httpx.Response(200, json=issue(7))
        if request.url.params["page"] == "1":
            return page([comment(71, "First")], f"{REPO_PATH}/issues/7/comments")
        return page([comment(72, "Second")])

    evidence = run_reader(respond, lambda reader: reader.read(source("github_issue", locator={"number": "7"})))

    assert evidence.complete
    assert evidence.version == STAMP
    assert [item["body"] for item in json.loads(evidence.body)["comments"]] == ["First", "Second"]
    assert actions == [
        f"{REPO_PATH}/issues/7",
        f"{REPO_PATH}/issues/7/comments?per_page=100&page=1",
        f"{REPO_PATH}/issues/7/comments?per_page=100&page=2",
    ]


def test_pr_collects_independent_file_and_review_comment_pages():
    def respond(request):
        path = request.url.path.removeprefix(REPO_PATH)
        number = request.url.params.get("page")
        if path == "/issues/7":
            return httpx.Response(200, json=issue(7, pr=True))
        if path == "/issues/7/comments":
            return page([comment(71, "Issue comment")])
        if path == "/pulls/7":
            return httpx.Response(
                200,
                json={
                    "number": 7,
                    "head": {"sha": COMMIT},
                    "base": {"sha": BLOB},
                    "changed_files": 2,
                    "updated_at": STAMP,
                },
            )
        if path == "/pulls/7/reviews":
            return page([])
        if path == "/pulls/7/files":
            filename = "first.py" if number == "1" else "second.py"
            items = [{"filename": filename, "status": "modified", "sha": BLOB}]
        else:
            assert path == "/pulls/7/comments"
            items = [{**comment(int(number), f"Review {number}"), "path": "first.py", "line": 10}]
        return page(items, request.url.path if number == "1" else None)

    evidence = run_reader(respond, lambda reader: reader.read(source("github_issue", locator={"number": "7"})))
    body = json.loads(evidence.body)

    assert evidence.complete
    assert body["title"] == "Feature change"
    assert body["body"] == "Details"
    assert body["state"] == "open"
    assert body["labels"] == ["enhancement"]
    assert body["comments"][0]["body"] == "Issue comment"
    assert body["pull_request"]["head_sha"] == COMMIT
    assert body["pull_request"]["base_sha"] == BLOB
    assert [item["filename"] for item in body["pull_request"]["files"]] == ["first.py", "second.py"]
    assert [item["body"] for item in body["pull_request"]["review_comments"]] == ["Review 1", "Review 2"]


@pytest.mark.parametrize("max_pages", [1, 2])
def test_pr_collects_review_summaries_separately_from_inline_comments(max_pages):
    def respond(request):
        path = request.url.path.removeprefix(REPO_PATH)
        match path:
            case "/issues/7":
                return httpx.Response(200, json=issue(7, pr=True))
            case "/pulls/7":
                return httpx.Response(200, json={"head": {"sha": COMMIT}, "base": {"sha": BLOB}, "changed_files": 0})
            case "/pulls/7/reviews":
                current = request.url.params["page"]
                review = {
                    "id": int(current),
                    "body": f"Review summary {current}",
                    "state": "COMMENTED",
                    "user": {"login": "maintainer"},
                    "commit_id": COMMIT,
                    "submitted_at": STAMP,
                }
                return page([review], request.url.path if current == "1" else None)
            case _:
                return page([])

    ref = source("github_issue", locator={"number": "7"})
    evidence = run_reader(respond, lambda reader: reader.read(ref), max_pages=max_pages)
    body = json.loads(evidence.body)

    assert evidence.complete == (max_pages == 2)
    assert [item["body"] for item in body["pull_request"]["reviews"]] == [
        f"Review summary {page_number}" for page_number in range(1, max_pages + 1)
    ]
    assert body["pull_request"]["reviews"][0]["submitted_at"] == STAMP
    assert body["pull_request"]["review_comments"] == []
    assert body.get("continuation") == ({"reviews": 2} if max_pages == 1 else None)


def test_pr_reports_provider_files_cap():
    def respond(request):
        match request.url.path.removeprefix(REPO_PATH):
            case "/issues/7":
                return httpx.Response(200, json=issue(7, pr=True))
            case "/pulls/7":
                return httpx.Response(200, json={"head": {"sha": COMMIT}, "base": {"sha": BLOB}, "changed_files": 3001})
            case _:
                return page([])

    evidence = run_reader(respond, lambda reader: reader.read(source("github_issue", locator={"number": "7"})))

    assert not evidence.complete
    assert json.loads(evidence.body)["continuation"]["files"] == "provider_limit"


def test_related_work_preserves_scope_and_matches_a_later_page():
    def respond(request):
        assert request.url.host == "api.github.com"
        assert request.url.path == f"{REPO_PATH}/issues"
        assert request.url.params["state"] == "open"
        assert request.url.params["per_page"] == "100"
        if request.url.params["page"] == "1":
            return page([issue(7, title="UI change", pr=True)], f"{REPO_PATH}/issues")
        assert request.url.params["page"] == "2"
        return page(
            [
                issue(8, title="Readiness copy", body="The gate is green.", pr=True),
                issue(9, title="Readiness gate"),
                issue(10, title="Readiness", body="No matching keyword", pr=True),
            ],
        )

    ref = source("github_related_work", locator={"keywords": "  Readiness   GATE ", "type": "pr", "state": "open"})
    evidence = run_reader(respond, lambda reader: reader.read(ref))
    matches = json.loads(evidence.body)["matches"]

    assert evidence.complete
    assert [item["number"] for item in matches] == [8]
    assert matches[0]["type"] == "pr"
    assert matches[0]["title"] == "Readiness copy"
    assert matches[0]["state"] == "open"
    assert matches[0]["updated_at"] == STAMP
    assert matches[0]["url"] == "https://github.com/org/repo/pull/8"
    assert matches[0]["match_rationale"] == {"title": ["readiness"], "body": ["gate"]}


def test_bounded_empty_related_work_is_incomplete():
    def respond(request):
        assert request.url.params["page"] == "1"
        return page([issue(1, "Other work")], f"{REPO_PATH}/issues")

    ref = source("github_related_work", locator={"keywords": "readiness"})
    evidence = run_reader(respond, lambda reader: reader.read(ref), max_pages=1)

    assert not evidence.complete
    assert json.loads(evidence.body) == {"matches": [], "continuation": {"issues": 2}}


@pytest.mark.parametrize(
    "next_link",
    [
        '<https://other.example/repos/org/repo/issues?page=2>; rel="next"',
        '<https://api.github.com/repos/other/private/issues?page=2>; rel="next"',
        '<https://api.github.com/repos/org/repo/pulls?page=2>; rel="next"',
        '<https://api.github.com/repos/org/repo/issues?page=1>; rel="next"',
        '<https://api.github.com/repos/org/repo/issues?page=2&state=closed>; rel="next"',
    ],
)
def test_invalid_pagination_cannot_change_repo_endpoint_filters_or_order(next_link):
    def respond(request):
        assert request.url.path == f"{REPO_PATH}/issues"
        assert request.url.params["page"] == "1"
        return httpx.Response(200, json=[], headers={"Link": next_link})

    ref = source("github_related_work", locator={"keywords": "query", "state": "open"})
    with pytest.raises(SourceError, match="SOURCE_RESPONSE_INVALID"):
        run_reader(respond, lambda reader: reader.read(ref))


def test_named_pagination_can_return_canonical_repo_casing():
    def respond(request):
        assert request.url.path == f"{REPO_PATH}/issues"
        if request.url.params["page"] == "1":
            return page([], "/repos/Org/Repo/issues")
        return page([issue(8, title="Query")])

    ref = source("github_related_work", locator={"keywords": "query"})
    evidence = run_reader(respond, lambda reader: reader.read(ref))

    assert [item["number"] for item in json.loads(evidence.body)["matches"]] == [8]


@pytest.mark.parametrize("linked_id", [422, 999])
def test_numeric_pagination_path_is_verified_against_authorized_repo(linked_id):
    paths = []

    def respond(request):
        paths.append(request.url.path)
        if request.url.path == REPO_PATH:
            return httpx.Response(200, json={"id": 422, "full_name": "org/repo"})
        assert request.url.path == f"{REPO_PATH}/issues"
        if request.url.params["page"] == "1":
            return page([], f"/repositories/{linked_id}/issues")
        return page([issue(8, title="Query")])

    ref = source("github_related_work", locator={"keywords": "query"})
    if linked_id == 422:
        evidence = run_reader(respond, lambda reader: reader.read(ref))
        assert json.loads(evidence.body)["matches"][0]["number"] == 8
        assert paths == [f"{REPO_PATH}/issues", REPO_PATH, f"{REPO_PATH}/issues"]
    else:
        with pytest.raises(SourceError, match="SOURCE_RESPONSE_INVALID"):
            run_reader(respond, lambda reader: reader.read(ref))
        assert paths == [f"{REPO_PATH}/issues", REPO_PATH]


@pytest.mark.parametrize("final_status", [200, 401])
def test_401_refreshes_installation_token_once(final_status):
    seen = []

    def respond(request):
        sent = request.headers["Authorization"]
        seen.append(sent)
        if sent == "Bearer test-refreshed-token" and final_status == 200:
            return file_response()
        return httpx.Response(401, json={"message": f"Secret token: {sent}"})

    operation = lambda reader: reader.read(source(revision=COMMIT))  # noqa: E731
    if final_status == 200:
        assert run_reader(respond, operation).body == "hello"
    else:
        with pytest.raises(SourceError, match=r"^SOURCE_APP_AUTH_FAILED$") as result:
            run_reader(respond, operation)
        assert result.value.__context__ is None

    assert seen == ["Bearer test-installation-token", "Bearer test-refreshed-token"]


@pytest.mark.parametrize(
    ("status", "headers", "error", "retry_after"),
    [
        (403, {}, "SOURCE_ACCESS_DENIED", None),
        (403, {"Retry-After": "17"}, "SOURCE_RATE_LIMITED", 17),
        (403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1"}, "SOURCE_RATE_LIMITED", 0),
        (404, {}, "SOURCE_NOT_FOUND", None),
        (429, {"Retry-After": "20"}, "SOURCE_RATE_LIMITED", 20),
        (429, {"Retry-After": "NaN"}, "SOURCE_RATE_LIMITED", None),
        (302, {"Location": "https://other.example/token"}, "SOURCE_RESPONSE_INVALID", None),
    ],
)
def test_http_errors_are_typed_and_sanitized(status, headers, error, retry_after):
    def respond(request):
        assert request.url.host == "api.github.com"
        return httpx.Response(status, headers=headers, json={"secret": request.headers["Authorization"]})

    with pytest.raises(SourceError, match=f"^{error}$") as result:
        run_reader(respond, lambda reader: reader.read(source(revision=COMMIT)))

    assert result.value.retry_after == retry_after
    assert result.value.__context__ is None


def test_response_is_bounded_while_streaming():
    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"x" * 120
            pytest.fail("reader must stop streaming once the byte limit is crossed")

    with pytest.raises(SourceError, match="SOURCE_CONTENT_LIMIT"):
        run_reader(
            lambda _request: httpx.Response(200, stream=SlowBody()),
            lambda reader: reader.read(source(revision=COMMIT)),
            max_response_bytes=100,
        )
