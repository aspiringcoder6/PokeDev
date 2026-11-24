"""Typed HTTP client for the vAi ADLC Harness control API."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Protocol, runtime_checkable
from urllib.parse import quote, urlsplit

import httpx
from pydantic import ValidationError

from langflow.adlc.contract_authoring import contract_authoring_enabled
from langflow.adlc.contract_execution import execution_enabled, recovery_enabled
from langflow.adlc.contract_execution_models import EXECUTION_PROFILE
from langflow.adlc.harness_models import (
    HarnessArtifactRead,
    HarnessInteractionReceipt,
    HarnessInteractionResponse,
    HarnessPluginInventory,
    HarnessSessionAccepted,
    HarnessSessionRead,
    HarnessSessionRequest,
    HarnessSubmissionReceipt,
)

HARNESS_BASE_URL_ENV = "ADLC_HARNESS_BASE_URL"
HARNESS_API_TOKEN_ENV = "ADLC_HARNESS_API_TOKEN"  # noqa: S105 - environment variable name.
HARNESS_ALLOW_INSECURE_HTTP_ENV = "ADLC_HARNESS_ALLOW_INSECURE_HTTP"
AUTHORING_PROFILE_REF = "harness-profile:adlc-skilltree/0.1.0"
HARNESS_API_ROOT = "/api/v1/adlc-harness"
AUTHORING_API_ROOT = "/api/v1/adlc-harness-authoring"
CONTRACT_API_ROOT = "/api/v1/adlc-harness-contract"
CONTRACT_RECOVERY_API_ROOT = "/api/v1/adlc-harness-contract-recovery"

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
REQUEST_REJECTED = "HARNESS_REQUEST_REJECTED"
RESPONSE_INVALID = "HARNESS_RESPONSE_INVALID"
SERVER_AUTHENTICATION_FAILED = "HARNESS_SERVER_AUTHENTICATION_FAILED"
SERVER_CONFLICT = "HARNESS_SERVER_CONFLICT"
SERVER_ERROR = "HARNESS_SERVER_ERROR"
SERVER_UNAVAILABLE = "HARNESS_SERVER_UNAVAILABLE"


class HarnessClientError(RuntimeError):
    """Sanitized transport or contract failure from the Harness server."""

    def __init__(self, code: str, *, category: str = "DEPENDENCY", retryable: bool = True) -> None:
        super().__init__(code)
        self.code = code
        self.category = category
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class HarnessServerSettings:
    base_url: str = "http://127.0.0.1:3080"
    api_token: str | None = field(default=None, repr=False)
    allow_insecure_http: bool = False
    request_timeout_seconds: float = 30.0

    @classmethod
    def from_environment(cls) -> HarnessServerSettings:
        return cls(
            base_url=os.getenv(HARNESS_BASE_URL_ENV, "http://127.0.0.1:3080"),
            api_token=os.getenv(HARNESS_API_TOKEN_ENV) or None,
            allow_insecure_http=os.getenv(HARNESS_ALLOW_INSECURE_HTTP_ENV, "").strip().lower() in _TRUE_VALUES,
        )

    def validate(self) -> None:
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            msg = "Harness base URL must be an absolute HTTP(S) URL."
            raise ValueError(msg)
        if parsed.username is not None or parsed.password is not None:
            msg = "Harness credentials must not be embedded in the base URL."
            raise ValueError(msg)
        if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            msg = "Harness base URL must not contain a path, query, or fragment."
            raise ValueError(msg)
        if parsed.scheme == "http" and parsed.hostname not in _LOOPBACK_HOSTS and not self.allow_insecure_http:
            msg = "Plain HTTP is allowed only for loopback Harness endpoints unless explicitly enabled."
            raise ValueError(msg)
        if self.request_timeout_seconds <= 0:
            msg = "Harness request timeout must be positive."
            raise ValueError(msg)


@runtime_checkable
class HarnessClient(Protocol):
    async def get_artifact(self, session_id: str, artifact_id: str) -> HarnessArtifactRead:
        """Read bounded captured bytes by opaque identity, never an arbitrary URI."""
        ...

    async def health(self) -> dict[str, object]:
        """Read the secret-free Harness readiness projection."""
        ...

    async def create_session(self, request: HarnessSessionRequest) -> HarnessSessionAccepted:
        """Create or replay one idempotent Harness session."""
        ...

    async def get_plugin_inventory(self) -> HarnessPluginInventory:
        """Read and refresh the installed-plugin integrity projection."""
        ...

    async def get_session(self, session_id: str) -> HarnessSessionRead:
        """Read a Harness session projection."""
        ...

    async def submit_session(self, session_id: str) -> HarnessSubmissionReceipt:
        """Accept the prepared result and enqueue callback delivery."""
        ...

    async def respond_to_interaction(
        self,
        session_id: str,
        interaction_id: str,
        response: HarnessInteractionResponse,
    ) -> HarnessInteractionReceipt:
        """Resolve one pending Harness interaction and resume its agent session."""
        ...

    async def cancel_session(self, session_id: str) -> HarnessSessionRead:
        """Request cooperative cancellation of one Harness session."""
        ...


class HarnessHttpClient:
    """HTTP implementation that exposes only contract-shaped Harness values."""

    def __init__(
        self,
        settings: HarnessServerSettings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        authoring_enabled: bool | None = None,
        contract_execution_enabled: bool | None = None,
        contract_recovery_enabled: bool | None = None,
    ) -> None:
        self.settings = settings or HarnessServerSettings.from_environment()
        self.settings.validate()
        self._authoring_enabled = contract_authoring_enabled() if authoring_enabled is None else authoring_enabled
        self._contract_enabled = (
            execution_enabled() if contract_execution_enabled is None else contract_execution_enabled
        )
        self._recovery_enabled = recovery_enabled() if contract_recovery_enabled is None else contract_recovery_enabled
        self._session_roots: dict[str, str] = {}
        headers = {"accept": "application/json"}
        if self.settings.api_token:
            headers["authorization"] = f"Bearer {self.settings.api_token}"
        self._client = httpx.AsyncClient(
            base_url=self.settings.base_url.rstrip("/"),
            headers=headers,
            timeout=self.settings.request_timeout_seconds,
            transport=transport,
        )

    async def health(self) -> dict[str, object]:
        response = await self._request("GET", "/api/v1/adlc-harness/health")
        payload = self._json_object(response)
        return {str(key): value for key, value in payload.items()}

    async def create_session(self, request: HarnessSessionRequest) -> HarnessSessionAccepted:
        root = HARNESS_API_ROOT
        if request.execution.profile_ref == AUTHORING_PROFILE_REF:
            if not self._authoring_enabled:
                code = "HARNESS_AUTHORING_DISABLED"
                raise HarnessClientError(code, category="VALIDATION", retryable=False)
            root = AUTHORING_API_ROOT
        if request.execution.profile_ref == EXECUTION_PROFILE:
            if not self._contract_enabled:
                code = "HARNESS_CONTRACT_EXECUTION_DISABLED"
                raise HarnessClientError(code, category="VALIDATION", retryable=False)
            root = CONTRACT_API_ROOT
            if any(p.plugin_id == "vai-adlc-contract-recovery" for p in request.execution.plugin_lock):
                if not self._recovery_enabled:
                    code = "HARNESS_CONTRACT_RECOVERY_DISABLED"
                    raise HarnessClientError(code, category="VALIDATION", retryable=False)
                root = CONTRACT_RECOVERY_API_ROOT
        if request.context.get("adlc_local_project") is not None and request.execution.profile_ref in {
            EXECUTION_PROFILE,
            "harness-profile:adlc-coding-artifacts/0.1.0",
        }:
            if not any(
                p.plugin_id == "vai-adlc-local-projects" and p.version == "0.1.0" and p.required
                for p in request.execution.plugin_lock
            ):
                code = "HARNESS_LOCAL_PROJECT_RELEASE_REQUIRED"
                raise HarnessClientError(code, category="VALIDATION", retryable=False)
            if request.execution.profile_ref == EXECUTION_PROFILE:
                root = "/api/v1/adlc-local-contract"
            elif request.execution.profile_ref == "harness-profile:adlc-coding-artifacts/0.1.0":
                root = "/api/v1/adlc-local-harness"
            else:
                code = "HARNESS_LOCAL_PROJECT_PROFILE_UNSUPPORTED"
                raise HarnessClientError(code, category="VALIDATION", retryable=False)
        response = await self._request(
            "POST",
            f"{root}/sessions",
            json=request.model_dump(mode="json", exclude_none=True),
        )
        accepted = self._validate(response, HarnessSessionAccepted, "HARNESS_CREATE_RESPONSE_INVALID")
        self._session_roots[accepted.session.session_id] = root
        return accepted

    async def get_plugin_inventory(self) -> HarnessPluginInventory:
        response = await self._request("GET", "/api/v1/adlc-harness/plugins")
        return self._validate(response, HarnessPluginInventory, "HARNESS_PLUGIN_INVENTORY_RESPONSE_INVALID")

    async def get_session(self, session_id: str) -> HarnessSessionRead:
        roots = [self._session_roots[session_id]] if session_id in self._session_roots else [HARNESS_API_ROOT]
        if self._authoring_enabled and session_id not in self._session_roots:
            roots.append(AUTHORING_API_ROOT)
        if self._contract_enabled and session_id not in self._session_roots:
            roots.append(CONTRACT_API_ROOT)
        if self._contract_enabled and self._recovery_enabled and session_id not in self._session_roots:
            roots.append(CONTRACT_RECOVERY_API_ROOT)
        if session_id not in self._session_roots:
            roots.append("/api/v1/adlc-local-harness")
            if self._contract_enabled and self._recovery_enabled:
                roots.append("/api/v1/adlc-local-contract")
        for index, root in enumerate(roots):
            # Recovery probes are GET-only, fixed deployment endpoints, and only
            # fall through on 404. Never repeat a write on another endpoint.
            response = await self._request(
                "GET", f"{root}/sessions/{quote(session_id, safe='')}", allow_not_found=index < len(roots) - 1
            )
            if response.status_code == HTTPStatus.NOT_FOUND:
                continue
            session = self._validate(response, HarnessSessionRead, "HARNESS_SESSION_RESPONSE_INVALID")
            if session.session_id != session_id:
                code = "HARNESS_SESSION_RESPONSE_INVALID"
                raise HarnessClientError(code, retryable=False)
            self._session_roots[session_id] = root
            return session
        raise HarnessClientError(REQUEST_REJECTED, category="VALIDATION", retryable=False)

    async def _session_root(self, session_id: str) -> str:
        if session_id not in self._session_roots:
            await self.get_session(session_id)
        return self._session_roots[session_id]

    async def reconcile_contract_session(self, session_id: str) -> HarnessSessionRead:
        """Retry exact H5D evidence reconciliation, never create/resume an agent."""
        if not self._contract_enabled or not self._recovery_enabled:
            code = "HARNESS_CONTRACT_RECOVERY_DISABLED"
            raise HarnessClientError(code, category="VALIDATION", retryable=False)
        root = await self._session_root(session_id)
        if root not in {CONTRACT_RECOVERY_API_ROOT, "/api/v1/adlc-local-contract"}:
            code = "HARNESS_CONTRACT_RECOVERY_RELEASE_REQUIRED"
            raise HarnessClientError(code, category="VALIDATION", retryable=False)
        response = await self._request("POST", f"{root}/sessions/{quote(session_id, safe='')}/reconcile", json={})
        value = self._validate(response, HarnessSessionRead, "HARNESS_SESSION_RESPONSE_INVALID")
        if value.session_id != session_id:
            code = "HARNESS_SESSION_RESPONSE_INVALID"
            raise HarnessClientError(code, retryable=False)
        return value

    async def get_artifact(self, session_id: str, artifact_id: str) -> HarnessArtifactRead:
        root = await self._session_root(session_id)
        path = f"{root}/sessions/{quote(session_id, safe='')}/artifacts/{quote(artifact_id, safe='')}"
        # The byte endpoint is independently bounded before JSON/base64 parsing.
        try:
            async with self._client.stream("GET", path) as streamed:
                chunks = []
                size = 0
                async for chunk in streamed.aiter_bytes():
                    size += len(chunk)
                    if size > 768 * 1024:
                        code = "HARNESS_ARTIFACT_RESPONSE_TOO_LARGE"
                        raise HarnessClientError(code, retryable=False)
                    chunks.append(chunk)
                response = httpx.Response(streamed.status_code, content=b"".join(chunks))
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise HarnessClientError(SERVER_UNAVAILABLE) from exc
        if response.status_code == HTTPStatus.GONE:
            code = "HARNESS_ARTIFACT_EXPIRED"
            raise HarnessClientError(code, retryable=False)
        self._check_response_status(response)
        return self._validate(response, HarnessArtifactRead, "HARNESS_ARTIFACT_RESPONSE_INVALID")

    async def submit_session(self, session_id: str) -> HarnessSubmissionReceipt:
        root = await self._session_root(session_id)
        response = await self._request(
            "POST",
            f"{root}/sessions/{quote(session_id, safe='')}/submit",
            json={},
        )
        return self._validate(response, HarnessSubmissionReceipt, "HARNESS_SUBMIT_RESPONSE_INVALID")

    async def respond_to_interaction(
        self,
        session_id: str,
        interaction_id: str,
        response: HarnessInteractionResponse,
    ) -> HarnessInteractionReceipt:
        root = await self._session_root(session_id)
        http_response = await self._request(
            "POST",
            f"{root}/sessions/{quote(session_id, safe='')}/interactions/{quote(interaction_id, safe='')}/responses",
            json=response.model_dump(mode="json"),
        )
        return self._validate(http_response, HarnessInteractionReceipt, "HARNESS_INTERACTION_RESPONSE_INVALID")

    async def cancel_session(self, session_id: str) -> HarnessSessionRead:
        root = await self._session_root(session_id)
        response = await self._request(
            "POST",
            f"{root}/sessions/{quote(session_id, safe='')}/cancel",
            json={},
        )
        return self._validate(response, HarnessSessionRead, "HARNESS_CANCEL_RESPONSE_INVALID")

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, *, allow_not_found: bool = False, **kwargs) -> httpx.Response:
        try:
            response = await self._client.request(method, path, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise HarnessClientError(SERVER_UNAVAILABLE) from exc
        if not (allow_not_found and response.status_code == HTTPStatus.NOT_FOUND):
            self._check_response_status(response)
        return response

    @staticmethod
    def _check_response_status(response: httpx.Response) -> None:
        if response.status_code in {401, 403}:
            raise HarnessClientError(
                SERVER_AUTHENTICATION_FAILED,
                category="AUTHENTICATION",
                retryable=False,
            )
        if response.status_code == HTTPStatus.CONFLICT:
            raise HarnessClientError(SERVER_CONFLICT, category="CONFLICT", retryable=False)
        if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
            raise HarnessClientError(SERVER_ERROR)
        if response.status_code >= HTTPStatus.BAD_REQUEST:
            raise HarnessClientError(REQUEST_REJECTED, category="VALIDATION", retryable=False)

    @staticmethod
    def _json_object(response: httpx.Response) -> dict:
        try:
            payload = response.json()
        except ValueError as exc:
            raise HarnessClientError(RESPONSE_INVALID, retryable=False) from exc
        if not isinstance(payload, dict):
            raise HarnessClientError(RESPONSE_INVALID, retryable=False)
        return payload

    @classmethod
    def _validate(cls, response: httpx.Response, model_type, error_code: str):
        try:
            return model_type.model_validate(cls._json_object(response))
        except ValidationError as exc:
            raise HarnessClientError(error_code, retryable=False) from exc


__all__ = [
    "HARNESS_ALLOW_INSECURE_HTTP_ENV",
    "HARNESS_API_TOKEN_ENV",
    "HARNESS_BASE_URL_ENV",
    "HarnessClient",
    "HarnessClientError",
    "HarnessHttpClient",
    "HarnessServerSettings",
]
