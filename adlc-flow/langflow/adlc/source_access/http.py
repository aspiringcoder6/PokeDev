"""Bounded provider responses and Lark cursor traversal."""

import hashlib
import json
import math
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from http import HTTPStatus
from typing import Protocol

import httpx

from .credentials import LARK_API_ORIGIN
from .models import Evidence, SourceError, SourceRef, make_evidence

_AUTH_FAILED = "SOURCE_APP_AUTH_FAILED"
_RESPONSE_INVALID = "SOURCE_RESPONSE_INVALID"
_ACCESS_DENIED = "SOURCE_ACCESS_DENIED"
_NOT_FOUND = "SOURCE_NOT_FOUND"
_RATE_LIMITED = "SOURCE_RATE_LIMITED"
INVALID = "SOURCE_ARGUMENTS_INVALID"
TIMEOUT = httpx.Timeout(10.0).as_dict()
_CONTENT_LIMIT = "SOURCE_CONTENT_LIMIT"
_READ_FAILED = "SOURCE_LARK_READ_FAILED"
_PAGINATION_INVALID = "SOURCE_PAGINATION_INVALID"
_MAX_CURSOR = 4096
_PAGE_SIZE = 50
_BINARY_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_MAX_RETRY_DELAY = 3600.0
_THROTTLE_CODES = {99991400, 1254290}
_ACCESS_CODES = {
    131006,
    234004,
    234009,
    1254303,
    1254302,
    1770032,
    230002,
    230006,
    230013,
    230027,
    230073,
    99991672,
    99991676,
}
_TENANT_TOKEN_EXPIRED = 99991663


class AppTokens(Protocol):
    async def get(self, force: bool = False) -> str: ...  # noqa: FBT001, FBT002


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


def check_status(status: int, headers: httpx.Headers) -> None:
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


async def bounded_body(response: httpx.Response, limit: int) -> bytes:
    if response.headers.get("content-encoding", "identity").lower() != "identity":
        raise SourceError(_RESPONSE_INVALID)
    content = bytearray()
    async for chunk in response.aiter_bytes():
        if len(content) + len(chunk) > limit:
            raise SourceError(_CONTENT_LIMIT)
        content.extend(chunk)
    return bytes(content)


def decode_json(raw: bytes | str, *, error_code: str = _RESPONSE_INVALID) -> object:
    try:
        return json.loads(raw)
    except (ValueError, RecursionError):
        pass
    raise SourceError(error_code)


def obj(value: object) -> dict:
    if not isinstance(value, dict):
        raise SourceError(_RESPONSE_INVALID)
    return value


def identifier(value: object, *, error_code: str = INVALID) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value):
        raise SourceError(error_code)
    return value


def provider_id(value: object) -> str:
    return identifier(value, error_code=_RESPONSE_INVALID)


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def lark_evidence(
    ref: SourceRef,
    body: dict,
    findings: list[str],
    *,
    pending_refs: Sequence[SourceRef] = (),
    pending_reason: str | None = None,
) -> Evidence:
    labels = set(findings)
    if pending_refs and pending_reason:
        labels.add(pending_reason)
    if labels:
        body["findings"] = sorted(labels)
    serialized = canonical(body)
    # The serialized evidence includes all available provider timestamps and revisions.
    version = hashlib.sha256(serialized.encode()).hexdigest()
    return make_evidence(ref, serialized, version, pending_refs=pending_refs, incomplete_reasons=findings)


class LarkReader:
    def __init__(
        self,
        client: httpx.AsyncClient,
        tokens: AppTokens,
        *,
        max_pages: int = 20,
        max_response_bytes: int = 2_000_000,
        max_file_bytes: int = 1_000_000,
    ):
        if (
            client.base_url not in {httpx.URL(LARK_API_ORIGIN), httpx.URL(LARK_API_ORIGIN + "/")}
            or client.trust_env
            or client.follow_redirects
        ):
            raise SourceError(_AUTH_FAILED)
        if min(max_pages, max_response_bytes, max_file_bytes) < 1:
            msg = "Lark read limits must be positive"
            raise ValueError(msg)
        self._client = client
        self._tokens = tokens
        self._max_pages = max_pages
        self._max_bytes = max_response_bytes
        self._max_file_bytes = max_file_bytes

    def _start(self) -> "LarkRead":
        return LarkRead(self._client, self._tokens, self._max_bytes, self._max_file_bytes, self._max_pages)


class LarkRead:
    """One logical read shares a token refresh and bounded content budget across requests."""

    def __init__(self, client: httpx.AsyncClient, tokens: AppTokens, max_bytes: int, file_bytes: int, max_pages: int):
        self.client = client
        self.tokens = tokens
        self.remaining = max_bytes
        self.file_bytes = file_bytes
        self.pages_left = max_pages
        self.attachments_left = max_pages
        self.token: str | None = None
        self.refreshed = False

    async def _request(self, path: str, params: Mapping | None, body: dict | None, *, binary: bool) -> bytes | dict:
        if self.client.is_closed:
            raise SourceError(_AUTH_FAILED)
        if self.token is None:
            self.token = await self.tokens.get()
        while True:
            request = httpx.Request(
                "GET" if body is None else "POST",
                LARK_API_ORIGIN + "/open-apis/" + path,
                params=params,
                json=body,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Accept-Encoding": "identity",
                    "User-Agent": "PokeDev",
                },
                extensions={"timeout": TIMEOUT},
            )
            try:
                response = await self.client.send(request, auth=None, follow_redirects=False, stream=True)
                try:
                    status = response.status_code
                    if status not in (HTTPStatus.OK, HTTPStatus.BAD_REQUEST, HTTPStatus.UNAUTHORIZED):
                        check_status(status, response.headers)
                    if status != HTTPStatus.UNAUTHORIZED:
                        limit = min(self.remaining, self.file_bytes) if binary else self.remaining
                        raw = await bounded_body(response, limit)
                        self.remaining -= len(raw)
                        if (
                            binary
                            and status == HTTPStatus.OK
                            and "json" not in response.headers.get("content-type", "")
                        ):
                            return raw
                        payload = obj(decode_json(raw))
                        code = payload.get("code")
                        if type(code) is not int:
                            raise SourceError(_RESPONSE_INVALID)
                        if code == 0 and status == HTTPStatus.OK and not binary:
                            return payload
                        if code in _THROTTLE_CODES:
                            delay = _retry_after(response.headers)
                            raise SourceError(
                                _RATE_LIMITED, retry_after=min(delay, _MAX_RETRY_DELAY) if delay is not None else None
                            )
                        if code in _ACCESS_CODES:
                            raise SourceError(_ACCESS_DENIED)
                        if code != _TENANT_TOKEN_EXPIRED:
                            raise SourceError(_READ_FAILED)
                finally:
                    await response.aclose()
            except httpx.TimeoutException:
                failure = "SOURCE_TIMEOUT"
            except httpx.HTTPError:
                failure = "SOURCE_UNAVAILABLE"
            else:
                if self.refreshed:
                    raise SourceError(_AUTH_FAILED)
                self.refreshed = True
                self.token = await self.tokens.get(force=True)
                continue
            raise SourceError(failure)

    async def data(self, path: str, params: Mapping | None = None, body: dict | None = None) -> dict:
        payload = await self._request(path, params, body, binary=False)
        return obj(obj(payload).get("data"))

    async def pages(
        self,
        path: str,
        params: Mapping | None = None,
        *,
        body: dict | None = None,
        stop_when: Callable[[dict], bool] | None = None,
    ) -> tuple[list[dict], str | None]:
        async def fetch(cursor: str | None) -> dict:
            self.pages_left -= 1
            query = {**(params or {}), "page_size": _PAGE_SIZE}
            if cursor:
                query["page_token"] = cursor
            return obj(await self._request(path, query, body, binary=False))

        items, _, cursor = await lark_pages(fetch, max_pages=self.pages_left, stop_when=stop_when)
        return items, cursor

    async def attachment(
        self, path: str, params: Mapping, *, is_text: bool, metadata: dict, findings: list[str]
    ) -> dict:
        if not is_text:
            findings.append("unsupported_attachment_format")
        elif self.attachments_left == 0:
            findings.append("attachment_read_limit")
        else:
            self.attachments_left -= 1
            raw = await self._request(path, params, None, binary=True)
            if isinstance(raw, bytes):
                try:
                    text = raw.decode("utf-8")
                except UnicodeError:
                    text = None
                if text is not None and not text.startswith("%PDF-") and not _BINARY_CONTROL.search(text):
                    return {**metadata, "text": text}
            findings.append("unsupported_attachment_format")
        return metadata


async def lark_pages(
    fetch_page: Callable[[str | None], Awaitable[dict]],
    *,
    max_pages: int = 20,
    stop_when: Callable[[dict], bool] | None = None,
) -> tuple[list[dict], bool, str | None]:
    items = []
    seen = set()
    cursor = None
    for _ in range(max_pages):
        payload = obj(await fetch_page(cursor))
        if type(payload.get("code")) is not int or payload["code"] != 0:
            raise SourceError(_READ_FAILED)
        data = obj(payload.get("data"))
        page = data.get("items")
        if not isinstance(page, list) or len(page) > _PAGE_SIZE or type(data.get("has_more", False)) is not bool:
            raise SourceError(_RESPONSE_INVALID)
        next_cursor = data.get("page_token")
        if next_cursor is not None and (not isinstance(next_cursor, str) or len(next_cursor) > _MAX_CURSOR):
            raise SourceError(_PAGINATION_INVALID)
        if "has_more" not in data and next_cursor:
            raise SourceError(_PAGINATION_INVALID)
        if data.get("has_more"):
            if not next_cursor or next_cursor in seen:
                raise SourceError(_PAGINATION_INVALID)
            cursor = next_cursor
            seen.add(cursor)
        entries = [obj(item) for item in page]
        if stop_when is not None:
            matches = [item for item in entries if stop_when(item)]
            if matches:
                return matches, True, None
        else:
            items.extend(entries)
        if not data.get("has_more", False):
            return items, True, None
    return items, False, cursor
