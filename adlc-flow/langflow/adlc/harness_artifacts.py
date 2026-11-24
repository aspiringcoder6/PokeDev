"""Import publisher-owned source patches before immutable Harness acceptance."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import re
from datetime import timedelta
from typing import TYPE_CHECKING

from pydantic import ValidationError

from langflow.adlc.artifact_payload_store import (
    ArtifactPayloadStoreError,
    ArtifactPayloadUnavailableError,
    BoundedArtifactPayloadStore,
    SourcePatchRead,
    SourcePatchSnapshot,
)
from langflow.adlc.harness_client import HarnessClientError

if TYPE_CHECKING:
    from langflow.adlc.harness_client import HarnessClient
    from langflow.adlc.harness_models import HarnessCorrelation, HarnessSessionResult
    from langflow.adlc.models import Artifact

CAPTURE_KIND = "harness-git-diff"
CAPTURE_PRODUCER_PREFIX = "plugin:vai-adlc-artifacts-git/"
CAPTURE_PRODUCERS = frozenset(f"{CAPTURE_PRODUCER_PREFIX}{version}" for version in ("0.1.0", "0.1.1", "0.2.0"))
MAX_HARNESS_PATCH_BYTES = 512 * 1024
MAX_HARNESS_PATCH_FILES = 128


def is_captured_harness_patch(artifact: Artifact) -> bool:
    return artifact.metadata.get("capture") == CAPTURE_KIND or artifact.producer.startswith(CAPTURE_PRODUCER_PREFIX)


class HarnessArtifactImporter:
    """Only a configured authenticated Harness client can supply artifact bytes."""

    def __init__(self, payloads: BoundedArtifactPayloadStore, client: HarnessClient | None) -> None:
        self.payloads = payloads
        self.client = client

    async def import_result(self, result: HarnessSessionResult) -> None:
        for artifact in result.artifacts:
            if is_captured_harness_patch(artifact):
                if not any(
                    entry.plugin_id == "vai-adlc-artifacts-git"
                    and entry.required
                    and artifact.producer == f"{CAPTURE_PRODUCER_PREFIX}{entry.version}"
                    for entry in result.plugin_lock
                ):
                    code = "HARNESS_ARTIFACT_PRODUCER_MISMATCH"
                    raise HarnessClientError(code, retryable=False)
                await self.read(result.session_id, result.correlation, artifact)

    async def read(self, session_id: str, correlation: HarnessCorrelation, artifact: Artifact) -> SourcePatchRead:
        self._validate_descriptor(correlation, artifact)
        try:
            payload = self.payloads.read(artifact)
        except ArtifactPayloadUnavailableError:
            if self.client is None:
                code = "HARNESS_ARTIFACT_CLIENT_UNAVAILABLE"
                raise HarnessClientError(code) from None
            response = await self.client.get_artifact(session_id, str(artifact.artifact_id))
            if (
                response.session_id != session_id
                or response.correlation != correlation
                or response.artifact != artifact
            ):
                code = "HARNESS_ARTIFACT_CORRELATION_MISMATCH"
                raise HarnessClientError(code, retryable=False) from None
            try:
                payload = base64.b64decode(response.payload_base64, validate=True)
            except (binascii.Error, ValueError):
                code = "HARNESS_ARTIFACT_PAYLOAD_INVALID"
                raise HarnessClientError(code, retryable=False) from None
            if (
                len(payload) != artifact.size_bytes
                or len(payload) > MAX_HARNESS_PATCH_BYTES
                or hashlib.sha256(payload).hexdigest() != artifact.checksum.value
            ):
                code = "HARNESS_ARTIFACT_CHECKSUM_MISMATCH"
                raise HarnessClientError(code, retryable=False) from None
            snapshot = self._validate_snapshot(payload, artifact)
            try:
                await asyncio.to_thread(self.payloads.retain, artifact, payload)
            except ArtifactPayloadStoreError as exc:
                raise HarnessClientError(exc.code, retryable=False) from None
            return SourcePatchRead(artifact=artifact.model_copy(deep=True), **snapshot.model_dump())
        snapshot = self._validate_snapshot(payload, artifact)
        return SourcePatchRead(artifact=artifact.model_copy(deep=True), **snapshot.model_dump())

    @staticmethod
    def _validate_descriptor(correlation: HarnessCorrelation, artifact: Artifact) -> None:
        if (
            artifact.workflow_run_id != correlation.workflow_run_id
            or artifact.task_run_id != correlation.task_run_id
            or artifact.attempt_id != correlation.attempt_id
            or artifact.kind != "SOURCE_PATCH"
            or artifact.media_type != "application/json"
            or artifact.producer not in CAPTURE_PRODUCERS
            or artifact.metadata.get("capture") != CAPTURE_KIND
            or artifact.metadata.get("format") != "harness-git-diff-v1"
            or artifact.uri != f"adlc://runs/{correlation.workflow_run_id}/artifacts/{artifact.artifact_id}"
            or artifact.size_bytes <= 0
            or artifact.size_bytes > MAX_HARNESS_PATCH_BYTES
            or artifact.expires_at is None
            or artifact.created_at.tzinfo is None
            or artifact.expires_at.tzinfo is None
            or artifact.expires_at <= artifact.created_at
            or artifact.expires_at > artifact.created_at + timedelta(hours=24)
            or re.fullmatch(r"[0-9a-f]{64}", artifact.checksum.value) is None
        ):
            code = "HARNESS_ARTIFACT_DESCRIPTOR_INVALID"
            raise HarnessClientError(code, retryable=False)

    @staticmethod
    def _validate_snapshot(payload: bytes, artifact: Artifact) -> SourcePatchSnapshot:
        try:
            snapshot = SourcePatchSnapshot.model_validate_json(payload)
        except ValidationError:
            code = "HARNESS_ARTIFACT_PAYLOAD_INVALID"
            raise HarnessClientError(code, retryable=False) from None
        if (
            snapshot.format != "harness-git-diff-v1"
            or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", snapshot.base_commit or "")
            or snapshot.base_commit != artifact.metadata.get("base_commit")
            or len(snapshot.files) > MAX_HARNESS_PATCH_FILES
            or len(snapshot.files) != artifact.metadata.get("file_count")
            or len({item.file for item in snapshot.files}) != len(snapshot.files)
        ):
            code = "HARNESS_ARTIFACT_PAYLOAD_INVALID"
            raise HarnessClientError(code, retryable=False)
        for item in snapshot.files:
            if (
                item.file.startswith("/")
                or re.search(r"[:\\\x00-\x1f\x7f]", item.file)
                or any(part in {"", ".", ".."} for part in item.file.split("/"))
                or item.additions < 0
                or item.deletions < 0
            ):
                code = "HARNESS_ARTIFACT_PATH_REJECTED"
                raise HarnessClientError(code, retryable=False)
        return snapshot
