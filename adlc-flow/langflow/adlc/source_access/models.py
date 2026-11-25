from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    connection_id: str = Field(min_length=1)
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


class SourceGrant(Closed):
    """Access for a run, constructed from the current server-owned project binding."""

    project_id: str
    run_id: str
    principal_id: str
    resources: Mapping[str, frozenset[str]]
    locator_allowlists: Mapping[str, Mapping[str, tuple[str, ...]]] = Field(
        default_factory=dict, validate_default=True
    )
    max_reads: int = Field(default=24, ge=1, le=200)
    max_bytes: int = Field(default=500_000, ge=1, le=2_000_000)

    @field_validator("resources")
    @classmethod
    def freeze_resources(cls, resources: Mapping[str, frozenset[str]]) -> Mapping[str, frozenset[str]]:
        return MappingProxyType(dict(resources))

    @field_validator("locator_allowlists")
    @classmethod
    def freeze_locator_allowlists(
        cls, allowlists: Mapping[str, Mapping[str, tuple[str, ...]]]
    ) -> Mapping[str, Mapping[str, tuple[str, ...]]]:
        return MappingProxyType({key: MappingProxyType(dict(limits)) for key, limits in allowlists.items()})


class Reader(Protocol):
    async def read(self, ref: SourceRef) -> Evidence: ...
