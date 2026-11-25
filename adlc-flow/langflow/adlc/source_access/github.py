import base64
import binascii
import json
import math
import re
import time
from collections.abc import Mapping
from http import HTTPStatus
from typing import Protocol
from urllib.parse import quote, unquote

import httpx

from .credentials import GITHUB_API_ORIGIN
from .models import Evidence, SourceError, SourceRef, is_git_sha, make_evidence

_ARGUMENTS_INVALID = "SOURCE_ARGUMENTS_INVALID"
_RESPONSE_INVALID = "SOURCE_RESPONSE_INVALID"
_AUTH_FAILED = "SOURCE_APP_AUTH_FAILED"
_CONTENT_LIMIT = "SOURCE_CONTENT_LIMIT"
_UNSUPPORTED_CONTENT = "SOURCE_UNSUPPORTED_CONTENT"
_ACCESS_DENIED = "SOURCE_ACCESS_DENIED"
_NOT_FOUND = "SOURCE_NOT_FOUND"
_RATE_LIMITED = "SOURCE_RATE_LIMITED"
_MAX_PATH_LENGTH = 4096
_MAX_REF_LENGTH = 1024
_MAX_KEYWORD_LENGTH = 200
_PER_PAGE = 100
_PR_FILES_LIMIT = 3000
_TIMEOUT = httpx.Timeout(10.0).as_dict()
_CONTROL = re.compile(r"[\x00-\x1f\x7f\ud800-\udfff]")
_POSITIVE_INT = re.compile(r"[1-9][0-9]{0,18}")


class InstallationTokens(Protocol):
    async def get(self, force: bool = False) -> str: ...  # noqa: FBT001, FBT002


def _repo_path(repository: str) -> str:
    owner, separator, repo = repository.partition("/")
    if (
        not separator
        or re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,37}[a-zA-Z0-9])?", owner) is None
        or re.fullmatch(r"[a-zA-Z0-9._-]{1,100}", repo) is None
        or repo in {".", ".."}
        or repo.lower().endswith(".git")
    ):
        raise SourceError(_ARGUMENTS_INVALID)
    return f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"


def _path_parts(path: str) -> list[str]:
    if len(path) > _MAX_PATH_LENGTH or "\\" in path or _CONTROL.search(path):
        raise SourceError(_ARGUMENTS_INVALID)
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise SourceError(_ARGUMENTS_INVALID)

    # Inspect encoded traversal without changing the components sent to GitHub.
    probe = path
    while "%" in probe:
        decoded = unquote(probe)
        if decoded == probe:
            break
        if any(part in {".", ".."} for part in decoded.replace("\\", "/").split("/")):
            raise SourceError(_ARGUMENTS_INVALID)
        probe = decoded
    return parts


def _quoted_ref(revision: str) -> str:
    parts = _path_parts(revision)
    if (
        len(revision) > _MAX_REF_LENGTH
        or revision == "@"
        or revision.startswith("-")
        or revision.endswith(".")
        or any(char in revision for char in " ~^:?*[")
        or ".." in revision
        or "@{" in revision
        or any(part.startswith(".") or part.endswith(".lock") for part in parts)
    ):
        raise SourceError(_ARGUMENTS_INVALID)
    return quote(revision, safe="")


def _file_path(ref: SourceRef) -> str | None:
    if not is_git_sha(ref.revision):
        raise SourceError(_ARGUMENTS_INVALID)
    if ref.locator == {"tree": "1"}:
        return None
    if ref.locator.keys() != {"path"}:
        raise SourceError(_ARGUMENTS_INVALID)
    return "/".join(quote(part, safe="") for part in _path_parts(ref.locator["path"]))


def _object(value: object) -> dict:
    if not isinstance(value, dict):
        raise SourceError(_RESPONSE_INVALID)
    return value


def _objects(value: object) -> list[dict]:
    if not isinstance(value, list):
        raise SourceError(_RESPONSE_INVALID)
    return [_object(item) for item in value]


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise SourceError(_RESPONSE_INVALID)
    return value


def _natural(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SourceError(_RESPONSE_INVALID)
    return value


def _sha(value: object) -> str:
    if not is_git_sha(value):
        raise SourceError(_RESPONSE_INVALID)
    return value.lower()


def _canonical_json(body: dict) -> str:
    return json.dumps(body, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_evidence(
    ref: SourceRef,
    body: dict,
    version: str,
    continuation: Mapping[str, int | str],
) -> Evidence:
    if continuation:
        body["continuation"] = dict(continuation)
    return make_evidence(ref, _canonical_json(body), version, complete=not continuation)


def _retry_after(headers: httpx.Headers) -> float | None:
    try:
        delay = float(headers.get("retry-after", "nan"))
        if math.isfinite(delay) and delay >= 0:
            return delay
        if headers.get("x-ratelimit-remaining") == "0":
            reset = float(headers.get("x-ratelimit-reset", "nan"))
            if math.isfinite(reset):
                return max(0.0, reset - time.time())
    except ValueError:
        pass
    return None


def _check_status(status: int, headers: httpx.Headers) -> None:
    if status == HTTPStatus.OK:
        return
    if status == HTTPStatus.UNAUTHORIZED:
        raise SourceError(_AUTH_FAILED)
    if status == HTTPStatus.TOO_MANY_REQUESTS or (
        status == HTTPStatus.FORBIDDEN and ("retry-after" in headers or headers.get("x-ratelimit-remaining") == "0")
    ):
        raise SourceError(_RATE_LIMITED, retry_after=_retry_after(headers))
    if status == HTTPStatus.FORBIDDEN:
        raise SourceError(_ACCESS_DENIED)
    if status == HTTPStatus.NOT_FOUND:
        raise SourceError(_NOT_FOUND)
    raise SourceError(_RESPONSE_INVALID)


class _GitHubRead:
    """Request state for one logical read, including its single credential refresh."""

    def __init__(
        self, client: httpx.AsyncClient, tokens: InstallationTokens, repo: str, max_bytes: int, max_pages: int
    ):
        self._client = client
        self._tokens = tokens
        self._repo = repo
        self._max_bytes = max_bytes
        self._max_pages = max_pages
        self._token: str | None = None
        self._refreshed = False
        self._repo_id: int | None = None

    async def _send(self, path: str, params: Mapping[str, str | int] | None) -> httpx.Response:
        if self._client.is_closed:
            raise SourceError(_AUTH_FAILED)
        request = httpx.Request(
            "GET",
            GITHUB_API_ORIGIN + self._repo + path,
            params=params,
            headers={
                "Accept": "application/vnd.github+json",
                "Accept-Encoding": "identity",
                "Authorization": f"Bearer {self._token}",
                "User-Agent": "PokeDev",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            extensions={"timeout": _TIMEOUT},
        )
        return await self._client.send(request, auth=None, follow_redirects=False, stream=True)

    async def get(self, path: str, params: Mapping[str, str | int] | None = None) -> tuple[object, httpx.Headers]:
        if self._token is None:
            self._token = await self._tokens.get()
        try:
            response = await self._send(path, params)
            if response.status_code == HTTPStatus.UNAUTHORIZED and not self._refreshed:
                await response.aclose()
                self._refreshed = True
                self._token = await self._tokens.get(force=True)
                response = await self._send(path, params)
            try:
                _check_status(response.status_code, response.headers)
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise SourceError(_RESPONSE_INVALID)
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > self._max_bytes:
                        raise SourceError(_CONTENT_LIMIT)
                    content.extend(chunk)
                return json.loads(content), response.headers
            finally:
                await response.aclose()
        except SourceError:
            raise
        except httpx.TimeoutException:
            error = "SOURCE_TIMEOUT"
        except httpx.HTTPError:
            error = "SOURCE_UNAVAILABLE"
        except (RecursionError, ValueError):
            error = _RESPONSE_INVALID
        # Raise outside the handler so provider data and request headers are not chained.
        raise SourceError(error)

    async def pages(self, path: str, filters: Mapping[str, str] | None = None) -> tuple[list[dict], int | None]:
        filters = filters or {}
        items = []
        for page_number in range(1, self._max_pages + 1):
            data, headers = await self.get(path, {**filters, "per_page": _PER_PAGE, "page": page_number})
            page = _objects(data)
            if len(page) > _PER_PAGE:
                raise SourceError(_RESPONSE_INVALID)
            items.extend(page)
            if not await self._has_next(headers, path, filters, page_number):
                return items, None
        return items, self._max_pages + 1

    async def _has_next(self, headers: httpx.Headers, path: str, filters: Mapping[str, str], current: int) -> bool:
        link = headers.get("link")
        if not link:
            return False
        relations = set()
        for item in link.split(","):
            parsed = re.fullmatch(r'<([^<>]+)>;\s*rel="(first|prev|next|last)"', item.strip())
            if parsed is None:
                raise SourceError(_RESPONSE_INVALID)
            target, relation = parsed.groups()
            if relation in relations:
                raise SourceError(_RESPONSE_INVALID)
            relations.add(relation)
            try:
                url = httpx.URL(target)
            except httpx.InvalidURL:
                url = None
            if url is None:
                raise SourceError(_RESPONSE_INVALID)
            await self._validate_link_scope(url, path)
            params = dict(url.params)
            number = params.pop("page", "")
            per_page = params.pop("per_page", str(_PER_PAGE))
            if (
                len(url.params.multi_items()) != len(url.params)
                or _POSITIVE_INT.fullmatch(number) is None
                or per_page != str(_PER_PAGE)
                or any(filters.get(key) != value for key, value in params.items())
                or (relation == "next" and int(number) != current + 1)
            ):
                raise SourceError(_RESPONSE_INVALID)
        return "next" in relations

    async def _validate_link_scope(self, url: httpx.URL, path: str) -> None:
        if (
            url.scheme != "https"
            or url.host != "api.github.com"
            or url.port not in {None, 443}
            or url.userinfo
            or url.fragment
        ):
            raise SourceError(_RESPONSE_INVALID)
        raw_path = url.raw_path.partition(b"?")[0].decode("ascii")
        if not raw_path.endswith(path):
            raise SourceError(_RESPONSE_INVALID)
        repository = raw_path.removesuffix(path)
        if repository.casefold() == self._repo.casefold():
            return
        # GitHub also uses /repositories/{id} links. Confirm the ID through
        # the named repository before accepting the page marker.
        if not repository.startswith("/repositories/"):
            raise SourceError(_RESPONSE_INVALID)
        linked_id = repository.removeprefix("/repositories/")
        if _POSITIVE_INT.fullmatch(linked_id) is None:
            raise SourceError(_RESPONSE_INVALID)
        if self._repo_id is None:
            data, _ = await self.get("")
            repo = _object(data)
            if _string(repo.get("full_name")).casefold() != self._repo.removeprefix("/repos/").casefold():
                raise SourceError(_RESPONSE_INVALID)
            self._repo_id = _natural(repo.get("id"))
        if self._repo_id != int(linked_id):
            raise SourceError(_RESPONSE_INVALID)


class GitHubReader:
    def __init__(
        self,
        client: httpx.AsyncClient,
        tokens: InstallationTokens,
        *,
        max_pages: int = 10,
        max_response_bytes: int = 2_000_000,
        max_file_bytes: int = 1_000_000,
    ):
        if (
            client.base_url not in {httpx.URL(GITHUB_API_ORIGIN), httpx.URL(GITHUB_API_ORIGIN + "/")}
            or client.trust_env
            or client.follow_redirects
        ):
            raise SourceError(_AUTH_FAILED)
        if min(max_pages, max_response_bytes, max_file_bytes) < 1:
            message = "GitHub read limits must be positive"
            raise ValueError(message)
        self._client = client
        self._tokens = tokens
        self._max_pages = max_pages
        self._max_response_bytes = max_response_bytes
        self._max_file_bytes = max_file_bytes

    def _start(self, repository: str) -> _GitHubRead:
        return _GitHubRead(
            self._client, self._tokens, _repo_path(repository), self._max_response_bytes, self._max_pages
        )

    async def resolve_revision(self, repository: str, ref: str) -> str:
        read = self._start(repository)
        payload, _ = await read.get(f"/commits/{_quoted_ref(ref)}")
        return _sha(_object(payload).get("sha"))

    async def read(self, ref: SourceRef) -> Evidence:
        read = self._start(ref.resource_id)
        if ref.kind == "github_file":
            return await self._read_file(read, ref)
        if ref.revision is not None:
            raise SourceError(_ARGUMENTS_INVALID)
        if ref.kind == "github_issue":
            return await self._read_issue(read, ref)
        if ref.kind == "github_related_work":
            return await self._read_related(read, ref)
        raise SourceError(_ARGUMENTS_INVALID)

    async def _read_file(self, read: _GitHubRead, ref: SourceRef) -> Evidence:
        path = _file_path(ref)
        if path is None:
            data, _ = await read.get(f"/git/trees/{ref.revision}", {"recursive": 1})
            tree = _object(data)
            version = _sha(tree.get("sha"))
            truncated = tree.get("truncated")
            if not isinstance(truncated, bool):
                raise SourceError(_RESPONSE_INVALID)
            entries = _objects(tree.get("tree"))
            body = {
                "tree": [
                    {
                        "path": _string(entry.get("path")),
                        "type": _string(entry.get("type")),
                        "sha": _sha(entry.get("sha")),
                    }
                    for entry in entries
                ]
            }
            return _json_evidence(ref, body, version, {"tree": "provider_truncated"} if truncated else {})
        payload, _ = await read.get(f"/contents/{path}", {"ref": ref.revision})
        if isinstance(payload, list):
            raise SourceError(_UNSUPPORTED_CONTENT)
        data = _object(payload)
        file_type = data.get("type")
        if file_type is not None and _string(file_type) != "file":
            raise SourceError(_UNSUPPORTED_CONTENT)
        version = _sha(data.get("sha"))
        size = data.get("size")
        if size is not None and _natural(size) > self._max_file_bytes:
            raise SourceError(_CONTENT_LIMIT)
        if _string(data.get("encoding")) != "base64":
            raise SourceError(_UNSUPPORTED_CONTENT)
        encoded = _string(data.get("content")).replace("\n", "").replace("\r", "")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            content = None
        if content is None:
            raise SourceError(_RESPONSE_INVALID)
        if len(content) > self._max_file_bytes:
            raise SourceError(_CONTENT_LIMIT)
        if size is not None and size != len(content):
            raise SourceError(_RESPONSE_INVALID)
        try:
            body = content.decode("utf-8")
        except UnicodeError:
            body = None
        if body is None or re.search(r"[\x00-\x08\x0b\x0e-\x1f\x7f]", body):
            raise SourceError(_UNSUPPORTED_CONTENT)
        return make_evidence(ref, body, version)

    async def _read_issue(self, read: _GitHubRead, ref: SourceRef) -> Evidence:
        number = ref.locator.get("number", "")
        if ref.locator.keys() != {"number"} or _POSITIVE_INT.fullmatch(number) is None:
            raise SourceError(_ARGUMENTS_INVALID)
        path = f"/issues/{number}"
        data, _ = await read.get(path)
        issue = _object(data)
        if _natural(issue.get("number")) != int(number):
            raise SourceError(_RESPONSE_INVALID)
        version = _string(issue.get("updated_at"))
        comments, next_page = await read.pages(f"{path}/comments")
        continuation: dict[str, int | str] = {"comments": next_page} if next_page is not None else {}
        body = {
            "number": int(number),
            "title": _string(issue.get("title")),
            "body": _string(issue.get("body") or ""),
            "state": _string(issue.get("state")),
            "labels": [_string(label.get("name")) for label in _objects(issue.get("labels"))],
            "comments": [_comment(item) for item in comments],
            "updated_at": version,
        }
        if issue.get("pull_request") is not None:
            body["pull_request"] = await self._read_pr(read, number, continuation)
        return _json_evidence(ref, body, version, continuation)

    async def _read_pr(self, read: _GitHubRead, number: str, continuation: dict[str, int | str]) -> dict:
        path = f"/pulls/{number}"
        data, _ = await read.get(path)
        pr = _object(data)
        head_sha = _sha(_object(pr.get("head")).get("sha"))
        base_sha = _sha(_object(pr.get("base")).get("sha"))
        changed_files = _natural(pr.get("changed_files"))
        files, next_files = await read.pages(f"{path}/files")
        if next_files is not None:
            continuation["files"] = next_files
        elif changed_files > _PR_FILES_LIMIT:
            continuation["files"] = "provider_limit"
        elif len(files) < changed_files:
            continuation["files"] = "provider_shortfall"
        review_comments, next_comments = await read.pages(f"{path}/comments")
        if next_comments is not None:
            continuation["review_comments"] = next_comments
        reviews, next_reviews = await read.pages(f"{path}/reviews")
        if next_reviews is not None:
            continuation["reviews"] = next_reviews
        return {
            "head_sha": head_sha,
            "base_sha": base_sha,
            "changed_files": changed_files,
            "updated_at": pr.get("updated_at"),
            "files": [
                {
                    "filename": _string(item.get("filename")),
                    **{key: item[key] for key in ("status", "sha", "previous_filename") if key in item},
                }
                for item in files
            ],
            "review_comments": [
                {
                    **_comment(item),
                    **{key: item[key] for key in ("path", "line", "side", "diff_hunk", "commit_id") if key in item},
                }
                for item in review_comments
            ],
            "reviews": [
                {
                    "id": _natural(item.get("id")),
                    "body": _string(item.get("body") or ""),
                    "author": _author(item),
                    "state": _string(item.get("state")),
                    "submitted_at": item.get("submitted_at"),
                    "commit_id": item.get("commit_id"),
                }
                for item in reviews
            ],
        }

    async def _read_related(self, read: _GitHubRead, ref: SourceRef) -> Evidence:
        keywords = ref.locator.get("keywords", "")
        state = ref.locator.get("state", "all")
        kind = ref.locator.get("type", "all")
        if (
            ref.locator.keys() - {"keywords", "state", "type"}
            or len(keywords) > _MAX_KEYWORD_LENGTH
            or not keywords.strip()
            or state not in {"all", "open", "closed"}
            or kind not in {"all", "issue", "pr"}
        ):
            raise SourceError(_ARGUMENTS_INVALID)
        terms = list(dict.fromkeys(keywords.casefold().split()))
        items, next_page = await read.pages("/issues", {"state": state})
        matches = []
        for item in items:
            entry_kind = "pr" if item.get("pull_request") is not None else "issue"
            if kind not in {"all", entry_kind}:
                continue
            entry_state = _string(item.get("state"))
            if state not in {"all", entry_state}:
                continue
            title = _string(item.get("title"))
            body = _string(item.get("body") or "")
            folded_title, folded_body = title.casefold(), body.casefold()
            title_terms = [term for term in terms if term in folded_title]
            body_terms = [term for term in terms if term in folded_body]
            if set(title_terms).union(body_terms) != set(terms):
                continue
            number = _natural(item.get("number"))
            if not number:
                raise SourceError(_RESPONSE_INVALID)
            target = "pull" if entry_kind == "pr" else "issues"
            matches.append(
                {
                    "number": number,
                    "title": title,
                    "type": entry_kind,
                    "state": entry_state,
                    "updated_at": _string(item.get("updated_at")),
                    "url": f"https://github.com/{ref.resource_id}/{target}/{number}",
                    "match_rationale": {"title": title_terms, "body": body_terms},
                }
            )
        version = max((item["updated_at"] for item in matches), default="no-match")
        return _json_evidence(
            ref, {"matches": matches}, version, {"issues": next_page} if next_page is not None else {}
        )


def _author(item: dict) -> str | None:
    user = item.get("user")
    return _string(_object(user).get("login")) if user is not None else None


def _comment(item: dict) -> dict:
    return {
        "id": _natural(item.get("id")),
        "body": _string(item.get("body")),
        "author": _author(item),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
    }
