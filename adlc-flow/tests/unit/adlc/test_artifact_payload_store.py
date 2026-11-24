# ruff: noqa: INP001, PLR2004, S101

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from langflow.adlc.artifact_payload_store import (
    ArtifactPayloadStoreError,
    ArtifactPayloadUnavailableError,
    BoundedArtifactPayloadStore,
)
from langflow.adlc.models import Artifact, Checksum


def _artifact(payload: bytes, *, expires_at: datetime | None = None) -> Artifact:
    return Artifact(
        artifact_id=uuid4(),
        workflow_run_id=uuid4(),
        task_run_id=uuid4(),
        attempt_id=uuid4(),
        kind="SOURCE_PATCH",
        name="source-patch.json",
        media_type="application/vnd.opencode.vcs-diff+json",
        uri="adlc://test/artifact",
        size_bytes=len(payload),
        checksum=Checksum(value=hashlib.sha256(payload).hexdigest()),
        producer="agent-provider:opencode",
        created_at=datetime.now(timezone.utc),
        expires_at=expires_at,
    )


def test_store_retains_exact_checksums_and_run_identity() -> None:
    store = BoundedArtifactPayloadStore()
    payload = b'{"files":[]}'
    artifact = _artifact(payload)

    store.retain(artifact, payload)
    store.retain(artifact, payload)

    assert store.read(artifact) == payload
    assert store.total_bytes == len(payload)
    with pytest.raises(ArtifactPayloadUnavailableError):
        store.read(artifact.model_copy(update={"workflow_run_id": uuid4()}))
    with pytest.raises(ArtifactPayloadStoreError, match="ARTIFACT_PAYLOAD_CHECKSUM_MISMATCH"):
        store.retain(_artifact(payload), b"tampered")


def test_store_rejects_oversized_or_over_capacity_payloads_without_eviction() -> None:
    store = BoundedArtifactPayloadStore(max_artifact_bytes=8, max_total_bytes=10)
    first = _artifact(b"12345678")
    second = _artifact(b"abc")

    store.retain(first, b"12345678")

    with pytest.raises(ArtifactPayloadStoreError, match="ARTIFACT_PAYLOAD_TOO_LARGE"):
        store.retain(_artifact(b"123456789"), b"123456789")
    with pytest.raises(ArtifactPayloadStoreError, match="ARTIFACT_PAYLOAD_STORE_FULL"):
        store.retain(second, b"abc")
    assert store.read(first) == b"12345678"
    assert store.total_bytes == 8


def test_expired_payloads_are_removed_and_capacity_is_reused() -> None:
    clock = [datetime(2026, 9, 17, 0, 0, tzinfo=timezone.utc)]
    store = BoundedArtifactPayloadStore(
        max_artifact_bytes=8,
        max_total_bytes=8,
        retention=timedelta(minutes=5),
        now=lambda: clock[0],
    )
    first = _artifact(b"12345678", expires_at=clock[0] + timedelta(minutes=5))
    store.retain(first, b"12345678")

    clock[0] += timedelta(minutes=6)

    with pytest.raises(ArtifactPayloadUnavailableError):
        store.read(first)
    assert store.total_bytes == 0
    second = _artifact(b"abcdef", expires_at=clock[0] + timedelta(minutes=5))
    store.retain(second, b"abcdef")
    assert store.read(second) == b"abcdef"


def test_durable_payloads_survive_restart_without_extending_expiry(tmp_path) -> None:
    clock = [datetime(2026, 9, 17, 7, 0, tzinfo=timezone(timedelta(hours=7)))]
    path = tmp_path / "runs.sqlite3"
    store = BoundedArtifactPayloadStore(database_path=path, now=lambda: clock[0], retention=timedelta(minutes=5))
    payload = b'{"files":[]}'
    artifact = _artifact(payload, expires_at=clock[0] + timedelta(minutes=5))
    store.retain(artifact, payload)
    clock[0] += timedelta(minutes=3)
    reopened = BoundedArtifactPayloadStore(database_path=path, now=lambda: clock[0])
    assert reopened.read(artifact) == payload
    assert reopened.total_bytes == len(payload)
    with pytest.raises(ArtifactPayloadUnavailableError):
        reopened.read(artifact.model_copy(update={"attempt_id": uuid4()}))
    clock[0] += timedelta(minutes=3)
    with pytest.raises(ArtifactPayloadUnavailableError):
        reopened.read(artifact)
    assert BoundedArtifactPayloadStore(database_path=path, now=lambda: clock[0]).total_bytes == 0


def test_restored_payloads_keep_capacity_and_checksum_guards(tmp_path) -> None:
    path = tmp_path / "runs.sqlite3"
    original = BoundedArtifactPayloadStore(database_path=path, max_artifact_bytes=8, max_total_bytes=10)
    artifact = _artifact(b"12345678")
    original.retain(artifact, b"12345678")
    restored = BoundedArtifactPayloadStore(database_path=path, max_artifact_bytes=8, max_total_bytes=10)
    with pytest.raises(ArtifactPayloadStoreError, match="ARTIFACT_PAYLOAD_STORE_FULL"):
        restored.retain(_artifact(b"abc"), b"abc")
    assert restored.read(artifact) == b"12345678"


def test_separate_live_stores_deduplicate_and_share_capacity(tmp_path) -> None:
    path = tmp_path / "shared.sqlite3"
    first = BoundedArtifactPayloadStore(database_path=path, max_artifact_bytes=8, max_total_bytes=10)
    second = BoundedArtifactPayloadStore(database_path=path, max_artifact_bytes=8, max_total_bytes=10)
    artifact = _artifact(b"12345678")
    first.retain(artifact, b"12345678")
    second.retain(artifact, b"12345678")
    assert second.read(artifact) == b"12345678"
    third = BoundedArtifactPayloadStore(database_path=path, max_artifact_bytes=8, max_total_bytes=10)
    with pytest.raises(ArtifactPayloadStoreError, match="ARTIFACT_PAYLOAD_STORE_FULL"):
        third.retain(_artifact(b"abc"), b"abc")
    # An independently initialized store must also reject a changed ownership claim.
    fourth = BoundedArtifactPayloadStore(database_path=path, max_artifact_bytes=8, max_total_bytes=10)
    with pytest.raises(ArtifactPayloadStoreError, match="ARTIFACT_PAYLOAD_ID_CONFLICT"):
        fourth.retain(artifact.model_copy(update={"attempt_id": uuid4()}), b"12345678")
