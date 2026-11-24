"""Typed models for the combined ADLC command-execution contract v0.1."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal, NoReturn
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from langflow.adlc.models import CONTRACT_VERSION, ServiceError

NonEmptyString = Annotated[str, Field(min_length=1)]


def _invalid(message: str) -> NoReturn:
    raise ValueError(message)


def _is_none(value: object) -> bool:
    return value is None


class CommandExecutionStatus(str, Enum):
    """Lifecycle of one sandbox command, independent of TaskRun state."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"


class ExecutionLogStream(str, Enum):
    SYSTEM = "SYSTEM"
    STDOUT = "STDOUT"
    STDERR = "STDERR"


class ExecutionLogLevel(str, Enum):
    TRACE = "TRACE"
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ArtifactReference(BaseModel):
    """Reference artifact bytes stored outside a command response."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: UUID
    name: NonEmptyString | None = Field(default=None, exclude_if=_is_none)
    media_type: NonEmptyString | None = Field(default=None, exclude_if=_is_none)
    uri: NonEmptyString | None = Field(default=None, exclude_if=_is_none)


class ExecutionLogEntry(BaseModel):
    """One ordered, redacted command log entry."""

    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    occurred_at: datetime
    stream: ExecutionLogStream
    level: ExecutionLogLevel
    message: str = Field(max_length=16384)
    redacted: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class CommandExecutionRequest(BaseModel):
    """Idempotent request to execute one argv-style command in a sandbox."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["0.1"] = CONTRACT_VERSION
    command_id: UUID
    workflow_run_id: UUID
    task_run_id: UUID
    attempt_id: UUID
    sandbox_session_id: NonEmptyString
    executable: NonEmptyString
    arguments: list[str] = Field(default_factory=list)
    working_directory: NonEmptyString | None = None
    environment: dict[str, str] = Field(default_factory=dict)
    secret_refs: dict[str, NonEmptyString] = Field(default_factory=dict)
    timeout_ms: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=256)
    requested_at: datetime
    trace_context: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CommandExecutionResponse(BaseModel):
    """Current or terminal snapshot for one command execution."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["0.1"] = CONTRACT_VERSION
    command_id: UUID
    workflow_run_id: UUID
    task_run_id: UUID
    attempt_id: UUID
    status: CommandExecutionStatus
    exit_code: int | None = None
    logs: list[ExecutionLogEntry] = Field(default_factory=list)
    logs_truncated: bool = False
    artifact_refs: list[ArtifactReference] = Field(default_factory=list)
    error: ServiceError | None = None
    queued_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_status_shape(self) -> CommandExecutionResponse:
        """Keep partial and terminal response fields unambiguous."""
        if self.status is CommandExecutionStatus.QUEUED:
            self._require_absent("QUEUED", started_at=self.started_at, completed_at=self.completed_at)
            self._require_absent("QUEUED", exit_code=self.exit_code, error=self.error, duration_ms=self.duration_ms)
        elif self.status is CommandExecutionStatus.RUNNING:
            if self.started_at is None:
                _invalid("RUNNING requires started_at")
            self._require_absent("RUNNING", completed_at=self.completed_at, exit_code=self.exit_code, error=self.error)
        elif self.status is CommandExecutionStatus.SUCCESS:
            self._require_terminal_timestamps("SUCCESS")
            if self.exit_code != 0:
                _invalid("SUCCESS requires exit_code=0")
            if self.error is not None:
                _invalid("SUCCESS requires error=null")
        elif self.status is CommandExecutionStatus.FAILED:
            if self.completed_at is None:
                _invalid("FAILED requires completed_at")
            if self.error is None:
                _invalid("FAILED requires a ServiceError")
        elif self.status is CommandExecutionStatus.TIMEOUT:
            if self.completed_at is None:
                _invalid("TIMEOUT requires completed_at")
            if self.error is None or self.error.category != "TIMEOUT":
                _invalid("TIMEOUT requires a TIMEOUT ServiceError")
        elif self.status is CommandExecutionStatus.CANCELLED:
            if self.completed_at is None:
                _invalid("CANCELLED requires completed_at")
            if self.error is None or self.error.category != "CANCELLED":
                _invalid("CANCELLED requires a CANCELLED ServiceError")

        sequences = [entry.sequence for entry in self.logs]
        if sequences != sorted(set(sequences)):
            _invalid("log sequence values must be unique and increasing")
        if self.started_at is not None and self.started_at < self.queued_at:
            _invalid("started_at cannot precede queued_at")
        completion_floor = self.started_at or self.queued_at
        if self.completed_at is not None and self.completed_at < completion_floor:
            _invalid("completed_at cannot precede command start or queue time")
        return self

    def _require_terminal_timestamps(self, status: str) -> None:
        if self.started_at is None or self.completed_at is None:
            _invalid(f"{status} requires started_at and completed_at")

    @staticmethod
    def _require_absent(status: str, **values: object) -> None:
        present = [name for name, value in values.items() if value is not None]
        if present:
            _invalid(f"{status} requires {', '.join(present)} to be null")
