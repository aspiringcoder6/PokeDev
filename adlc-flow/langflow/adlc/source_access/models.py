import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Annotated, Literal, Protocol, TypeGuard, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, field_validator, model_serializer

# The first colon in a locator allowlist key separates the connection from the resource.
ConnectionId = Annotated[str, Field(min_length=1, pattern=r"^[^:]+$")]

Kind = Literal[
    "github_file",
    "github_issue",
    "github_related_work",
    "lark_thread",
    "lark_base_record",
    "lark_document",
]


class SourceError(ValueError):
    def __init__(self, code: str, *, retry_after: float | None = None):
        super().__init__(code)
        self.code = code
        self.retry_after = retry_after


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceRef(Closed):
    kind: Kind
    connection_id: ConnectionId
    resource_id: str = Field(min_length=1)
    locator: dict[str, str] = Field(default_factory=dict)
    revision: str | None = None


class Evidence(Closed):
    id: str
    source: SourceRef
    requested_source: SourceRef | None = None
    pending_refs: tuple[SourceRef, ...] = ()
    incomplete_reasons: tuple[str, ...] = ()
    version: str
    fetched_at: datetime
    body: str
    sha256: str
    complete: bool = True

    @model_serializer(mode="wrap")
    def serialize(self, handler: SerializerFunctionWrapHandler) -> dict:
        result = handler(self)
        if self.requested_source is None:
            result.pop("requested_source", None)
        if not self.pending_refs:
            result.pop("pending_refs", None)
        if not self.incomplete_reasons:
            result.pop("incomplete_reasons", None)
        return result


def is_git_sha(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{40}", value) is not None


def _ref_key(ref: SourceRef) -> str:
    return json.dumps(ref.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def completed_evidence_ids(evidence: Iterable[Evidence]) -> frozenset[str]:
    """Resolve exact source dependencies without modifying the frozen evidence."""
    pending = list(evidence)
    completed: set[str] = set()
    covered: set[str] = set()
    while pending:
        remaining = []
        for item in pending:
            if item.incomplete_reasons:
                continue
            if item.pending_refs:
                if any(_ref_key(ref) not in covered for ref in item.pending_refs):
                    remaining.append(item)
                    continue
            elif not item.complete:
                continue
            completed.add(item.id)
            covered.add(_ref_key(item.source))
            if item.requested_source is not None:
                covered.add(_ref_key(item.requested_source))
        if len(remaining) == len(pending):
            break
        pending = remaining
    return frozenset(completed)


def make_evidence(
    ref: SourceRef,
    body: str,
    version: str,
    *,
    complete: bool = True,
    requested_source: SourceRef | None = None,
    pending_refs: Iterable[SourceRef] = (),
    incomplete_reasons: Iterable[str] = (),
) -> Evidence:
    source = ref.model_copy(deep=True)
    canonical_ref = _ref_key(source)
    requested = requested_source.model_copy(deep=True) if requested_source is not None else None
    if requested is not None:
        canonical_ref += "\n" + _ref_key(requested)
    unique_refs = {_ref_key(ref): ref for ref in pending_refs}
    pending = tuple(unique_refs[key].model_copy(deep=True) for key in sorted(unique_refs))
    reasons = tuple(sorted(set(incomplete_reasons)))
    if pending or reasons:
        coverage = {"pending_refs": sorted(unique_refs), "incomplete_reasons": reasons}
        canonical_ref += "\n" + json.dumps(coverage, sort_keys=True, separators=(",", ":"))
    content_hash = hashlib.sha256(body.encode()).hexdigest()
    identity = hashlib.sha256(f"{canonical_ref}\n{version}\n{content_hash}".encode()).hexdigest()
    return Evidence(
        id=identity,
        source=source,
        requested_source=requested,
        version=version,
        fetched_at=datetime.now(timezone.utc),
        body=body,
        sha256=content_hash,
        complete=complete and not (pending or reasons),
        pending_refs=pending,
        incomplete_reasons=reasons,
    )


class SourceGrant(Closed):
    """Access for a run, constructed from the current server-owned project binding."""

    project_id: str
    run_id: str
    principal_id: str
    resources: Mapping[ConnectionId, frozenset[str]]
    locator_allowlists: Mapping[str, Mapping[str, tuple[str, ...]]] = Field(default_factory=dict, validate_default=True)
    max_reads: int = Field(default=24, ge=1, le=200)
    max_bytes: int = Field(default=500_000, ge=1, le=2_000_000)

    @field_validator("resources")
    @classmethod
    def freeze_resources(
        cls, resources: Mapping[ConnectionId, frozenset[str]]
    ) -> Mapping[ConnectionId, frozenset[str]]:
        return MappingProxyType(dict(resources))

    @field_validator("locator_allowlists")
    @classmethod
    def freeze_locator_allowlists(
        cls, allowlists: Mapping[str, Mapping[str, tuple[str, ...]]]
    ) -> Mapping[str, Mapping[str, tuple[str, ...]]]:
        return MappingProxyType({key: MappingProxyType(dict(limits)) for key, limits in allowlists.items()})


class Reader(Protocol):
    async def read(self, ref: SourceRef) -> Evidence: ...


@runtime_checkable
class RevisionReader(Reader, Protocol):
    async def resolve_revision(self, repository: str, ref: str) -> str: ...


@runtime_checkable
class ReferenceResolver(Reader, Protocol):
    async def resolve_ref(self, ref: SourceRef) -> SourceRef: ...


@runtime_checkable
class ScopedReader(Protocol):
    def start_read(self) -> Reader: ...
