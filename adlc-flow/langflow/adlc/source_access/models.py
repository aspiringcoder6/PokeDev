import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Annotated, Literal, Protocol, TypeGuard, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    version: str
    fetched_at: datetime
    body: str
    sha256: str
    complete: bool = True


def is_git_sha(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{40}", value) is not None


def make_evidence(ref: SourceRef, body: str, version: str, *, complete: bool = True) -> Evidence:
    source = ref.model_copy(deep=True)
    canonical_ref = json.dumps(source.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    content_hash = hashlib.sha256(body.encode()).hexdigest()
    identity = hashlib.sha256(f"{canonical_ref}\n{version}\n{content_hash}".encode()).hexdigest()
    return Evidence(
        id=identity,
        source=source,
        version=version,
        fetched_at=datetime.now(timezone.utc),
        body=body,
        sha256=content_hash,
        complete=complete,
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
