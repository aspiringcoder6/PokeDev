"""Secret-safe HTTP client boundary for the OpenCode headless server."""

from __future__ import annotations

import asyncio
import ipaddress
import os
from contextlib import suppress
from dataclasses import dataclass, field, replace
from typing import Any, Protocol, runtime_checkable
from urllib.parse import quote, urlsplit

import httpx

_HTTP_NO_CONTENT = 204
_HTTP_ERROR_MIN = 400
_HTTP_SERVER_ERROR_MIN = 500
_NON_TERMINAL_FINISH_REASONS = frozenset({"tool-calls", "unknown"})


@dataclass(frozen=True, slots=True)
class OpenCodeServerSettings:
    """Connection settings for a separately managed OpenCode server.

    Provider credentials intentionally are not represented here. OpenCode owns
    provider authentication; ADLC only authenticates to the headless server.
    """

    base_url: str = "http://127.0.0.1:4096"
    username: str = "opencode"
    password: str | None = field(default=None, repr=False)
    model: str | None = None
    agent: str | None = None

    @classmethod
    def from_environment(cls) -> OpenCodeServerSettings:
        """Load non-provider connection settings without reading credential files."""
        return cls(
            base_url=os.getenv("ADLC_OPENCODE_SERVER_URL", "http://127.0.0.1:4096"),
            username=os.getenv("ADLC_OPENCODE_SERVER_USERNAME", os.getenv("OPENCODE_SERVER_USERNAME", "opencode")),
            password=os.getenv("ADLC_OPENCODE_SERVER_PASSWORD") or os.getenv("OPENCODE_SERVER_PASSWORD") or None,
            model=os.getenv("ADLC_OPENCODE_MODEL") or None,
            agent=os.getenv("ADLC_OPENCODE_AGENT") or None,
        )


@dataclass(frozen=True, slots=True)
class OpenCodeModelSelection:
    provider_id: str
    model_id: str

    @classmethod
    def parse(cls, value: str | None) -> OpenCodeModelSelection | None:
        if value is None:
            return None
        provider_id, separator, model_id = value.strip().partition("/")
        if not separator or not provider_id or not model_id:
            msg = "OpenCode models must use the provider/model form."
            raise ValueError(msg)
        return cls(provider_id=provider_id, model_id=model_id)


@dataclass(frozen=True, slots=True)
class OpenCodeSession:
    session_id: str
    directory: str


@dataclass(frozen=True, slots=True)
class OpenCodeTokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass(frozen=True, slots=True)
class OpenCodePromptResult:
    message_id: str
    text: str
    changed_files: tuple[str, ...] = ()
    provider_id: str | None = None
    model_id: str | None = None
    finish: str | None = None
    cost: float = 0.0
    token_usage: OpenCodeTokenUsage = field(default_factory=OpenCodeTokenUsage)


@dataclass(frozen=True, slots=True)
class OpenCodeFileDiff:
    file: str
    patch: str
    additions: int
    deletions: int
    status: str | None = None


class OpenCodeClientError(RuntimeError):
    """Sanitized OpenCode dependency error suitable for contract mapping."""

    def __init__(
        self,
        *,
        code: str,
        category: str,
        retryable: bool,
        http_status: int | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.category = category
        self.retryable = retryable
        self.http_status = http_status


@runtime_checkable
class OpenCodeClient(Protocol):
    """Small subset of the OpenCode server API required by AgentAdapter."""

    async def health(self, *, timeout_ms: int = 5000) -> str:
        """Return the healthy server version or raise a sanitized client error."""
        ...

    async def create_session(self, *, directory: str, title: str, timeout_ms: int) -> OpenCodeSession:
        """Create one session scoped to the sandbox directory."""
        ...

    async def create_restricted_session(self, *, directory: str, title: str, timeout_ms: int) -> OpenCodeSession:
        """Create a session that acknowledges a deny-all tool permission rule."""
        ...

    async def prompt(
        self,
        session_id: str,
        *,
        directory: str,
        prompt: str,
        system: str,
        model: OpenCodeModelSelection | None,
        agent: str | None,
        timeout_ms: int,
    ) -> OpenCodePromptResult:
        """Send a prompt and wait for the completed assistant message."""
        ...

    async def list_sessions(self, *, directory: str, timeout_ms: int = 5000) -> tuple[dict[str, Any], ...]:
        """Return raw session summaries scoped to one workspace directory."""
        ...

    async def get_messages(self, session_id: str, *, directory: str, timeout_ms: int) -> list[dict[str, Any]]:
        """Return the raw ordered message list for one session."""
        ...

    async def get_workspace_diff(self, *, directory: str, timeout_ms: int) -> tuple[OpenCodeFileDiff, ...]:
        """Return the current VCS diff for the isolated workspace."""
        ...

    async def abort(self, session_id: str, *, directory: str, timeout_ms: int = 5000) -> None:
        """Abort in-flight work for a session."""
        ...

    async def dispose_instance(self, *, directory: str, timeout_ms: int = 5000) -> None:
        """Release directory-scoped watchers, subprocesses, and runtime resources."""
        ...


class OpenCodeHttpClient:
    """Minimal async client for the documented OpenCode server endpoints."""

    def __init__(
        self,
        settings: OpenCodeServerSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        poll_interval_seconds: float = 0.25,
    ) -> None:
        if poll_interval_seconds < 0:
            msg = "OpenCode poll interval cannot be negative."
            raise ValueError(msg)
        self.settings = settings
        self.base_url = _validate_base_url(settings.base_url)
        self._transport = transport
        self._poll_interval_seconds = poll_interval_seconds

    async def health(self, *, timeout_ms: int = 5000) -> str:
        payload = await self._request("GET", "/global/health", timeout_ms=timeout_ms)
        data = _mapping(payload, code="OPENCODE_RESPONSE_INVALID")
        if data.get("healthy") is not True or not isinstance(data.get("version"), str):
            raise _invalid_response()
        return data["version"]

    async def create_session(self, *, directory: str, title: str, timeout_ms: int) -> OpenCodeSession:
        payload = await self._request(
            "POST",
            "/session",
            directory=directory,
            json_body={"title": title},
            timeout_ms=timeout_ms,
        )
        data = _mapping(payload, code="OPENCODE_RESPONSE_INVALID")
        session_id = data.get("id")
        response_directory = data.get("directory")
        if not isinstance(session_id, str) or not session_id or not isinstance(response_directory, str):
            raise _invalid_response()
        return OpenCodeSession(session_id=session_id, directory=response_directory)

    async def create_restricted_session(self, *, directory: str, title: str, timeout_ms: int) -> OpenCodeSession:
        permissions = [{"permission": "*", "pattern": "*", "action": "deny"}]
        payload = await self._request(
            "POST",
            "/session",
            directory=directory,
            json_body={"title": title, "permission": permissions},
            timeout_ms=timeout_ms,
        )
        data = _mapping(payload, code="OPENCODE_RESPONSE_INVALID")
        session_id, response_directory = data.get("id"), data.get("directory")
        if not isinstance(session_id, str) or not session_id or not isinstance(response_directory, str):
            raise _invalid_response()
        if data.get("permission") != permissions:
            with suppress(OpenCodeClientError):
                await self.abort(session_id, directory=directory)
            code = "OPENCODE_CONTRACT_PERMISSIONS_UNAVAILABLE"
            raise OpenCodeClientError(code=code, category="VALIDATION", retryable=False)
        return OpenCodeSession(session_id=session_id, directory=response_directory)

    async def prompt(
        self,
        session_id: str,
        *,
        directory: str,
        prompt: str,
        system: str,
        model: OpenCodeModelSelection | None,
        agent: str | None,
        timeout_ms: int,
    ) -> OpenCodePromptResult:
        body: dict[str, Any] = {
            "parts": [{"type": "text", "text": prompt}],
            "system": system,
        }
        if model is not None:
            body["model"] = {"providerID": model.provider_id, "modelID": model.model_id}
        if agent is not None:
            body["agent"] = agent

        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(timeout_ms, 1) / 1000
        encoded_session_id = quote(session_id, safe="")
        messages_path = f"/session/{encoded_session_id}/message"
        baseline = _messages(
            await self._request(
                "GET",
                messages_path,
                directory=directory,
                timeout_ms=self._remaining_timeout_ms(deadline),
            )
        )
        baseline_ids = {_message_id(message) for message in baseline}

        await self._request(
            "POST",
            f"/session/{encoded_session_id}/prompt_async",
            directory=directory,
            json_body=body,
            timeout_ms=self._remaining_timeout_ms(deadline),
        )

        while True:
            messages = _messages(
                await self._request(
                    "GET",
                    messages_path,
                    directory=directory,
                    timeout_ms=self._remaining_timeout_ms(deadline),
                )
            )
            completed = self._new_completed_assistant(messages, baseline_ids)
            if completed is not None:
                result = self._parse_prompt_result(completed)
                return replace(
                    result,
                    changed_files=self._new_changed_files(messages, baseline_ids),
                )

            remaining_seconds = deadline - loop.time()
            if remaining_seconds <= 0:
                raise _timeout_error()
            await asyncio.sleep(min(self._poll_interval_seconds, remaining_seconds))

    @staticmethod
    def _new_completed_assistant(
        messages: list[dict[str, Any]],
        baseline_ids: set[str],
    ) -> dict[str, Any] | None:
        for message in reversed(messages):
            info = _mapping(message.get("info"), code="OPENCODE_RESPONSE_INVALID")
            if _message_id(message) in baseline_ids or info.get("role") != "assistant":
                continue
            OpenCodeHttpClient._raise_message_error(info.get("error"))
            finish = info.get("finish")
            if isinstance(finish, str) and finish and finish not in _NON_TERMINAL_FINISH_REASONS:
                return message
        return None

    @staticmethod
    def _new_changed_files(
        messages: list[dict[str, Any]],
        baseline_ids: set[str],
    ) -> tuple[str, ...]:
        changed_files: list[str] = []
        for message in messages:
            info = _mapping(message.get("info"), code="OPENCODE_RESPONSE_INVALID")
            if _message_id(message) in baseline_ids or info.get("role") != "assistant":
                continue
            parts = message.get("parts")
            if not isinstance(parts, list):
                raise _invalid_response()
            for part in parts:
                if not isinstance(part, dict) or part.get("type") != "patch":
                    continue
                files = part.get("files")
                if isinstance(files, list):
                    changed_files.extend(value for value in files if isinstance(value, str))
        return tuple(dict.fromkeys(changed_files))

    @staticmethod
    def _parse_prompt_result(payload: Any) -> OpenCodePromptResult:
        data = _mapping(payload, code="OPENCODE_RESPONSE_INVALID")
        info = _mapping(data.get("info"), code="OPENCODE_RESPONSE_INVALID")
        OpenCodeHttpClient._raise_message_error(info.get("error"))
        message_id = info.get("id")
        parts = data.get("parts")
        if not isinstance(message_id, str) or not message_id or not isinstance(parts, list):
            raise _invalid_response()

        text_parts: list[str] = []
        changed_files: list[str] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text" and isinstance(part.get("text"), str) and part.get("ignored") is not True:
                text_parts.append(part["text"])
            if part.get("type") == "patch" and isinstance(part.get("files"), list):
                changed_files.extend(value for value in part["files"] if isinstance(value, str))

        tokens = info.get("tokens") if isinstance(info.get("tokens"), dict) else {}
        cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
        return OpenCodePromptResult(
            message_id=message_id,
            text="\n".join(text_parts),
            changed_files=tuple(dict.fromkeys(changed_files)),
            provider_id=_optional_string(info.get("providerID")),
            model_id=_optional_string(info.get("modelID")),
            finish=_optional_string(info.get("finish")),
            cost=_number(info.get("cost")),
            token_usage=OpenCodeTokenUsage(
                input_tokens=_integer(tokens.get("input")),
                output_tokens=_integer(tokens.get("output")),
                reasoning_tokens=_integer(tokens.get("reasoning")),
                cache_read_tokens=_integer(cache.get("read")),
                cache_write_tokens=_integer(cache.get("write")),
            ),
        )

    @staticmethod
    def _remaining_timeout_ms(deadline: float) -> int:
        remaining_seconds = deadline - asyncio.get_running_loop().time()
        if remaining_seconds <= 0:
            raise _timeout_error()
        return max(1, int(remaining_seconds * 1000))

    async def list_sessions(self, *, directory: str, timeout_ms: int = 5000) -> tuple[dict[str, Any], ...]:
        payload = await self._request(
            "GET",
            "/session",
            directory=directory,
            timeout_ms=timeout_ms,
        )
        if not isinstance(payload, list):
            raise _invalid_response()
        return [item for item in payload if isinstance(item, dict)]

    async def get_messages(self, session_id: str, *, directory: str, timeout_ms: int) -> list[dict[str, Any]]:
        payload = await self._request(
            "GET",
            f"/session/{quote(session_id, safe='')}/message",
            directory=directory,
            timeout_ms=timeout_ms,
        )
        return _messages(payload)

    async def get_workspace_diff(
        self,
        *,
        directory: str,
        timeout_ms: int,
    ) -> tuple[OpenCodeFileDiff, ...]:
        payload = await self._request(
            "GET",
            "/vcs/diff",
            directory=directory,
            query={"mode": "git"},
            timeout_ms=timeout_ms,
        )
        if not isinstance(payload, list):
            raise _invalid_response()
        diffs: list[OpenCodeFileDiff] = []
        for value in payload:
            item = _mapping(value, code="OPENCODE_RESPONSE_INVALID")
            file = item.get("file")
            patch = item.get("patch", "")
            status = item.get("status")
            if not isinstance(file, str) or not isinstance(patch, str):
                raise _invalid_response()
            if status is not None and not isinstance(status, str):
                raise _invalid_response()
            diffs.append(
                OpenCodeFileDiff(
                    file=file,
                    patch=patch,
                    additions=_integer(item.get("additions")),
                    deletions=_integer(item.get("deletions")),
                    status=status,
                )
            )
        return tuple(diffs)

    async def abort(self, session_id: str, *, directory: str, timeout_ms: int = 5000) -> None:
        payload = await self._request(
            "POST",
            f"/session/{quote(session_id, safe='')}/abort",
            directory=directory,
            timeout_ms=timeout_ms,
        )
        if payload is not True:
            raise _invalid_response()

    async def dispose_instance(self, *, directory: str, timeout_ms: int = 5000) -> None:
        payload = await self._request(
            "POST",
            "/instance/dispose",
            directory=directory,
            timeout_ms=timeout_ms,
        )
        if payload is not True:
            raise _invalid_response()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        directory: str | None = None,
        query: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout_ms: int,
    ) -> Any:
        params = dict(query or {})
        if directory is not None:
            params["directory"] = directory
        auth = None
        if self.settings.password is not None:
            auth = httpx.BasicAuth(self.settings.username, self.settings.password)
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                auth=auth,
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                response = await client.request(
                    method,
                    path,
                    params=params or None,
                    json=json_body,
                    headers={"Accept": "application/json"},
                    timeout=max(timeout_ms, 1) / 1000,
                )
        except httpx.TimeoutException as exc:
            raise OpenCodeClientError(
                code="OPENCODE_REQUEST_TIMEOUT",
                category="TIMEOUT",
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise OpenCodeClientError(
                code="OPENCODE_SERVER_UNAVAILABLE",
                category="DEPENDENCY",
                retryable=True,
            ) from exc

        if response.status_code >= _HTTP_ERROR_MIN:
            raise _http_error(response.status_code)
        if response.status_code == _HTTP_NO_CONTENT:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise _invalid_response() from exc

    @staticmethod
    def _raise_message_error(value: Any) -> None:
        if value is None:
            return
        error = _mapping(value, code="OPENCODE_RESPONSE_INVALID")
        name = error.get("name")
        data = error.get("data") if isinstance(error.get("data"), dict) else {}
        if name == "ProviderAuthError":
            raise OpenCodeClientError(
                code="OPENCODE_PROVIDER_AUTHENTICATION_FAILED",
                category="AUTHENTICATION",
                retryable=False,
            )
        if name == "MessageAbortedError":
            raise OpenCodeClientError(code="OPENCODE_ABORTED", category="CANCELLED", retryable=False)
        if name == "MessageOutputLengthError":
            raise OpenCodeClientError(code="OPENCODE_OUTPUT_LIMIT", category="EXECUTION", retryable=False)
        if name == "APIError":
            status = data.get("statusCode") if isinstance(data.get("statusCode"), int) else None
            retryable = data.get("isRetryable") is True
            raise OpenCodeClientError(
                code="OPENCODE_PROVIDER_ERROR",
                category="DEPENDENCY",
                retryable=retryable,
                http_status=status,
            )
        raise OpenCodeClientError(code="OPENCODE_EXECUTION_FAILED", category="EXECUTION", retryable=False)


def _validate_base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.query or parsed.fragment:
        msg = "OpenCode server URL must be an HTTP(S) origin without query or fragment."
        raise ValueError(msg)
    if parsed.username is not None or parsed.password is not None:
        msg = "OpenCode server credentials must not be embedded in the URL."
        raise ValueError(msg)
    if parsed.scheme == "http" and not _is_loopback(parsed.hostname):
        msg = "Remote OpenCode servers require HTTPS; plain HTTP is allowed only for loopback hosts."
        raise ValueError(msg)
    return value.strip().rstrip("/")


def _is_loopback(hostname: str) -> bool:
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _http_error(status: int) -> OpenCodeClientError:
    mapping = {
        400: ("OPENCODE_REQUEST_INVALID", "VALIDATION", False),
        401: ("OPENCODE_SERVER_AUTHENTICATION_FAILED", "AUTHENTICATION", False),
        403: ("OPENCODE_SERVER_AUTHORIZATION_FAILED", "AUTHORIZATION", False),
        404: ("OPENCODE_RESOURCE_NOT_FOUND", "NOT_FOUND", False),
        408: ("OPENCODE_REQUEST_TIMEOUT", "TIMEOUT", True),
        409: ("OPENCODE_CONFLICT", "CONFLICT", False),
        429: ("OPENCODE_RATE_LIMITED", "RATE_LIMIT", True),
    }
    code, category, retryable = mapping.get(
        status,
        ("OPENCODE_SERVER_ERROR", "DEPENDENCY", status >= _HTTP_SERVER_ERROR_MIN),
    )
    return OpenCodeClientError(code=code, category=category, retryable=retryable, http_status=status)


def _timeout_error() -> OpenCodeClientError:
    return OpenCodeClientError(
        code="OPENCODE_REQUEST_TIMEOUT",
        category="TIMEOUT",
        retryable=True,
    )


def _invalid_response() -> OpenCodeClientError:
    return OpenCodeClientError(code="OPENCODE_RESPONSE_INVALID", category="DEPENDENCY", retryable=True)


def _messages(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise _invalid_response()
    return [_mapping(item, code="OPENCODE_RESPONSE_INVALID") for item in value]


def _message_id(message: dict[str, Any]) -> str:
    info = _mapping(message.get("info"), code="OPENCODE_RESPONSE_INVALID")
    message_id = info.get("id")
    if not isinstance(message_id, str) or not message_id:
        raise _invalid_response()
    return message_id


def _mapping(value: Any, *, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OpenCodeClientError(code=code, category="DEPENDENCY", retryable=True)
    return value


def _integer(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = [
    "OpenCodeClient",
    "OpenCodeClientError",
    "OpenCodeFileDiff",
    "OpenCodeHttpClient",
    "OpenCodeModelSelection",
    "OpenCodePromptResult",
    "OpenCodeServerSettings",
    "OpenCodeSession",
    "OpenCodeTokenUsage",
]
