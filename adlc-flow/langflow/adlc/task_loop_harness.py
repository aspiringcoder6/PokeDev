"""Proposal-only Harness runtime adapter. No callback, Submit, approval or remote Verify."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from http import HTTPStatus
from typing import TYPE_CHECKING, Literal
from urllib.parse import quote
from uuid import uuid5

import httpx
from pydantic import Field, ValidationError

from langflow.adlc.harness_client import HarnessServerSettings
from langflow.adlc.task_loop_models import LoopModel
from langflow.adlc.task_loop_runtime import LoopRuntimeError
from langflow.adlc.task_loop_runtime_v2 import (
    LoopIterationOutcomeV2,
    LoopRuntimeBindingV2,
    LoopRuntimeSessionV2,
    LoopRuntimeUsageV2,
)

if TYPE_CHECKING:
    from pathlib import Path

    from langflow.adlc.task_loop_runtime_v2 import LoopIterationRequestV2

ROOT = "/api/v1/adlc-harness-iterations"
HARNESS_LOOP_SERVICE = "agent-provider:task-loop-harness"
HARNESS_CONTRACT_LOOP_SERVICE = "agent-provider:coding-agent-harness-contract-loop"
HARNESS_RUNTIME_REF = "runtime:deepseek-harness-iteration/0.1.0"
HARNESS_PLUGIN_REF = "plugin:vai-adlc-task-loop/0.1.0"
TOKEN_ENV = "ADLC_HARNESS_ITERATION_API_TOKEN"  # noqa: S105 - configuration key, not a secret.
MAX_RESPONSE_BYTES = 524_288
MAX_REQUEST_BYTES = 1_048_576
MIN_TOKEN_BYTES = 32


def _closed_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            message = "Duplicate JSON property"
            raise ValueError(message)
        result[key] = value
    return result


def _nonfinite(_value):
    message = "Non-finite JSON value"
    raise ValueError(message)


def _local_directory(directory):
    # This is a local cleanup handle, never a path sent to the remote runtime.
    if not directory.is_absolute():
        message = "HARNESS_ITERATION_WORKSPACE_INVALID"
        raise LoopRuntimeError(message)


def harness_loop_enabled() -> bool:
    return os.getenv("ADLC_TASK_LOOP_HARNESS_ENABLED", "").strip().lower() in {"true", "1", "yes", "on"}


def harness_binding() -> LoopRuntimeBindingV2:
    return LoopRuntimeBindingV2(
        runtime_ref=HARNESS_RUNTIME_REF,
        family="HARNESS",
        provider_id="my-codex",
        model_id="cx/gpt-5.6-luna",
        modes=("FILE_PROPOSAL",),
    )


class HarnessIterationRead(LoopModel):
    schema_version: Literal["0.1"] = "0.1"
    session: LoopRuntimeSessionV2
    state: Literal["OPENING", "READY", "RUNNING", "COMPLETED", "FAILED", "INTERRUPTED", "CANCELLED"]
    outcome: LoopIterationOutcomeV2 | None = None
    usage: LoopRuntimeUsageV2 | None = None
    error_code: str | None = Field(default=None, pattern=r"^HARNESS_ITERATION_[A-Z_]{1,100}$")
    released: bool = Field(strict=True)


class HarnessTaskLoopRuntime:
    def __init__(self, settings: HarnessServerSettings | None = None, *, transport=None, plugin_digest: str):
        settings = settings or HarnessServerSettings.from_environment()
        settings.validate()
        if settings.api_token is None or len(settings.api_token.encode("utf-8")) < MIN_TOKEN_BYTES:
            message = "Configure the independent Harness iteration token (at least 32 bytes)"
            raise ValueError(message)
        self.binding = harness_binding()
        self.plugin_digest = plugin_digest
        self._client = httpx.AsyncClient(
            base_url=settings.base_url.rstrip("/"),
            transport=transport,
            timeout=min(settings.request_timeout_seconds, 15),
            follow_redirects=False,
            headers={"accept": "application/json", "authorization": f"Bearer {settings.api_token or ''}"},
        )

    @classmethod
    def from_environment(cls):
        from langflow.adlc.task_loop_harness_release import PLUGIN_DIGEST

        base = HarnessServerSettings.from_environment()
        return cls(
            HarnessServerSettings(
                base_url=base.base_url, api_token=os.getenv(TOKEN_ENV), allow_insecure_http=base.allow_insecure_http
            ),
            plugin_digest=PLUGIN_DIGEST,
        )

    async def _json(self, method, path, **kwargs):
        try:
            async with self._client.stream(method, ROOT + path, **kwargs) as response:
                if response.status_code >= HTTPStatus.MULTIPLE_CHOICES:
                    code = (
                        "HARNESS_ITERATION_UNAUTHENTICATED"
                        if response.status_code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}
                        else (
                            "HARNESS_ITERATION_CONFLICT"
                            if response.status_code == HTTPStatus.CONFLICT
                            else "HARNESS_ITERATION_UNAVAILABLE"
                        )
                    )
                    # The native call may have started. Do not let coordinator retries hide an ambiguous dispatch.
                    raise LoopRuntimeError(code)
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        msg = "HARNESS_ITERATION_RESPONSE_TOO_LARGE"
                        raise LoopRuntimeError(msg)
                    chunks.append(chunk)
        except httpx.TransportError as exc:
            msg = "HARNESS_ITERATION_UNAVAILABLE"
            raise LoopRuntimeError(msg) from exc
        try:
            parsed = json.loads(b"".join(chunks), object_pairs_hook=_closed_object, parse_constant=_nonfinite)
        except (ValueError, UnicodeError, RecursionError) as exc:
            msg = "HARNESS_ITERATION_RESPONSE_INVALID"
            raise LoopRuntimeError(msg) from exc
        else:
            return parsed

    async def check_readiness(self):
        """Read-only release check. Never opens a session or sends a model prompt."""
        health = await self._json("GET", "/health")
        if (
            not isinstance(health, dict)
            or health.get("ready") is not True
            or health.get("runtime") != self.binding.model_dump(mode="json")
            or health.get("plugin_digest") != self.plugin_digest
        ):
            msg = "HARNESS_ITERATION_RELEASE_MISMATCH"
            raise LoopRuntimeError(msg)

    async def open_iteration(self, command: LoopIterationRequestV2, *, directory: Path):
        _local_directory(directory)
        if (
            command.runtime != self.binding
            or command.mode != "FILE_PROPOSAL"
            or command.specification.max_total_cost is not None
        ):
            msg = "HARNESS_ITERATION_PROFILE_UNSUPPORTED"
            raise LoopRuntimeError(msg)
        await self.check_readiness()
        identity = str(uuid5(command.attempt_id, "harness-iteration/0.1.0"))
        payload = {
            "session_id": identity,
            "request_digest": command.content_digest,
            "command": command.model_dump(mode="json"),
        }
        if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > MAX_REQUEST_BYTES:
            msg = "HARNESS_ITERATION_REQUEST_TOO_LARGE"
            raise LoopRuntimeError(msg)
        try:
            response = await self._json("POST", "/sessions", json=payload)
            session = LoopRuntimeSessionV2.model_validate(response)
            if (
                session.runtime != self.binding
                or session.request_digest != command.content_digest
                or session.session_id != identity
                or session.fresh_context is not True
                or session.tools_disabled is not True
            ):
                msg = "HARNESS_ITERATION_SESSION_MISMATCH"
                raise LoopRuntimeError(msg)
        except (LoopRuntimeError, ValidationError) as exc:
            # Open never prompts. The predicted identity allows cleanup even if its acknowledgement was lost.
            with contextlib.suppress(LoopRuntimeError):
                await self._json(
                    "POST", f"/sessions/{identity}/cancel", json={"request_digest": command.content_digest}
                )
            if isinstance(exc, ValidationError):
                msg = "HARNESS_ITERATION_SESSION_MISMATCH"
                raise LoopRuntimeError(msg) from exc
            raise
        else:
            return session

    async def _read(self, session):
        try:
            value = HarnessIterationRead.model_validate(
                await self._json(
                    "GET",
                    f"/sessions/{quote(session.session_id, safe='')}",
                    params={"request_digest": session.request_digest},
                )
            )
            if value.session != session:
                msg = "Session mismatch"
                raise ValueError(msg)
        except (ValidationError, ValueError) as exc:
            msg = "HARNESS_ITERATION_RESPONSE_INVALID"
            raise LoopRuntimeError(msg) from exc
        else:
            return value

    async def run_iteration(self, command, session, *, directory):
        _local_directory(directory)
        if session.runtime != self.binding or session.request_digest != command.content_digest:
            msg = "HARNESS_ITERATION_SESSION_MISMATCH"
            raise LoopRuntimeError(msg)
        # Only one dispatch. Ambiguous writes are observed/cancelled, never automatically reposted.
        await self._json(
            "POST",
            f"/sessions/{quote(session.session_id, safe='')}/execute",
            json={"request_digest": command.content_digest, "command": command.model_dump(mode="json")},
        )
        async with asyncio.timeout(command.timeout_ms / 1000):
            while True:
                value = await self._read(session)
                if value.state == "COMPLETED":
                    if (
                        value.outcome is None
                        or value.outcome.request_digest != command.content_digest
                        or not value.released
                    ):
                        msg = "HARNESS_ITERATION_OUTCOME_INVALID"
                        raise LoopRuntimeError(msg)
                    return value.outcome
                if value.state in {"FAILED", "INTERRUPTED", "CANCELLED"}:
                    raise LoopRuntimeError(value.error_code or "HARNESS_ITERATION_FAILED", usage=value.usage)
                await asyncio.sleep(0.25)

    async def close_iteration(self, session, *, directory, abort):
        _local_directory(directory)
        if session.runtime != self.binding:
            msg = "HARNESS_ITERATION_SESSION_MISMATCH"
            raise LoopRuntimeError(msg)
        if abort:
            await self._json(
                "POST",
                f"/sessions/{quote(session.session_id, safe='')}/cancel",
                json={"request_digest": session.request_digest},
            )
        else:
            await self._json(
                "POST",
                f"/sessions/{quote(session.session_id, safe='')}/release",
                json={"request_digest": session.request_digest},
            )
        read = await self._read(session)
        if not read.released:
            msg = "HARNESS_ITERATION_RELEASE_UNCONFIRMED"
            raise LoopRuntimeError(msg)

    async def aclose(self):
        await self._client.aclose()
