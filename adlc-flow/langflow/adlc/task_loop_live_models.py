"""Version 0.2 task-loop contracts for pinned source and behavioral verification."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Pydantic resolves this at runtime.
from typing import Annotated, Literal
from uuid import UUID  # noqa: TC003 - Pydantic resolves this at runtime.

from pydantic import Field, field_validator, model_validator

from langflow.adlc.blueprints.canonicalization import sha256_digest
from langflow.adlc.task_loop_models import Digest, FileContent, LoopModel, validate_file_path, validate_files

Commit = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
Identity = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)]
_ASCII_CONTROL_LIMIT = 32


def validate_live_path(path: str) -> str:
    validate_file_path(path)
    reserved = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
    if any(ord(character) < _ASCII_CONTROL_LIMIT or character in '<>"|?*' for character in path) or any(
        part != part.rstrip(" .") or part.split(".")[0].casefold() in reserved for part in path.split("/")
    ):
        message = "Loop paths must be portable regular-file paths"
        raise ValueError(message)
    return path


class LiveLoopCommand(LoopModel):
    """A registered runner, not an agent-generated shell command."""

    check_id: Identity
    verifier_ref: Literal["verifier:python-unittest/0.1.0"] = "verifier:python-unittest/0.1.0"
    test_path: str
    timeout_ms: int = Field(default=30_000, ge=100, le=120_000, strict=True)

    _path = field_validator("test_path")(validate_live_path)

    @model_validator(mode="after")
    def python_test(self) -> LiveLoopCommand:
        if not self.test_path.endswith(".py"):
            message = "The unittest runner requires a tracked Python test file"
            raise ValueError(message)
        return self


class LiveLoopCriterion(LoopModel):
    criterion_id: Identity
    description: str = Field(min_length=1, max_length=1024)
    check_refs: tuple[Identity, ...] = Field(min_length=1, max_length=16)


class LiveLoopSpec(LoopModel):
    schema_version: Literal["0.2"] = "0.2"
    spec_id: UUID
    revision: int = Field(default=1, ge=1, strict=True)
    specification: str = Field(min_length=1, max_length=16_384)
    base_commit: Commit
    writable_paths: tuple[str, ...] = Field(min_length=1, max_length=64)
    acceptance_criteria: tuple[LiveLoopCriterion, ...] = Field(min_length=1, max_length=32)
    verification_commands: tuple[LiveLoopCommand, ...] = Field(min_length=1, max_length=16)
    max_iterations: int = Field(default=3, ge=1, le=100, strict=True)
    max_stalled_iterations: int = Field(default=2, ge=1, le=100, strict=True)
    context_budget_chars: int = Field(default=131_072, ge=1024, le=262_144, strict=True)
    max_duration_ms: int = Field(default=600_000, ge=1000, le=3_600_000, strict=True)
    max_total_tokens: int | None = Field(default=None, ge=1, strict=True)
    max_total_cost: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_policy(self) -> LiveLoopSpec:
        for path in self.writable_paths:
            validate_live_path(path)
        check_ids = [item.check_id for item in self.verification_commands]
        criterion_ids = [item.criterion_id for item in self.acceptance_criteria]
        used = {ref for item in self.acceptance_criteria for ref in item.check_refs}
        if (
            len({path.casefold() for path in self.writable_paths}) != len(self.writable_paths)
            or len(set(check_ids)) != len(check_ids)
            or len(set(criterion_ids)) != len(criterion_ids)
            or used != set(check_ids)
            or any(
                item.test_path.casefold() in {path.casefold() for path in self.writable_paths}
                for item in self.verification_commands
            )
        ):
            message = "Loop paths/IDs must be unique, every check must be mapped, and tests must be protected"
            raise ValueError(message)
        return self

    @property
    def content_digest(self) -> str:
        return sha256_digest(self.model_dump(mode="json"))


class LiveLoopFile(LoopModel):
    content: FileContent
    mode: Literal["100644", "100755"] = "100644"


class LiveLoopCandidate(LoopModel):
    """Complete cumulative text overlay relative to the pinned base; null deletes."""

    schema_version: Literal["0.2"] = "0.2"
    candidate_id: UUID
    parent_candidate_id: UUID | None
    iteration: int = Field(ge=0, strict=True)
    base_commit: Commit
    changes: dict[str, LiveLoopFile | None]
    content_digest: Digest

    @model_validator(mode="after")
    def verify_digest(self) -> LiveLoopCandidate:
        for path in self.changes:
            validate_live_path(path)
        validate_files({path: item.content if item else None for path, item in self.changes.items()})
        if self.content_digest != self.digest(self.base_commit, self.changes):
            message = "Candidate overlay does not match its digest"
            raise ValueError(message)
        return self

    @staticmethod
    def digest(base_commit: str, changes: dict[str, LiveLoopFile | None]) -> str:
        return sha256_digest(
            {
                "base_commit": base_commit,
                "changes": {path: item.model_dump() if item else None for path, item in changes.items()},
            }
        )


class LiveLoopEvidence(LoopModel):
    check_id: Identity
    argv: tuple[str, ...]
    test_digest: Digest
    exit_code: int
    executed_tests: int = Field(ge=0)
    timed_out: bool
    passed: bool
    stdout: str = Field(max_length=8192)
    stderr: str = Field(max_length=8192)

    @model_validator(mode="after")
    def valid_pass(self) -> LiveLoopEvidence:
        if self.passed and (self.exit_code != 0 or self.timed_out or self.executed_tests == 0):
            message = "Passing evidence requires successful execution of at least one test"
            raise ValueError(message)
        return self


class LiveLoopVerification(LoopModel):
    schema_version: Literal["0.2"] = "0.2"
    mode: Literal["COMMAND"] = "COMMAND"
    spec_digest: Digest
    candidate_id: UUID
    candidate_digest: Digest
    checks: tuple[LiveLoopEvidence, ...] = Field(min_length=1, max_length=16)

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


class LiveLoopState(LoopModel):
    """Internal durable aggregate, separate from the public wire contracts."""

    spec_digest: Digest
    policy_digest: Digest
    task_definition_id: UUID
    max_iterations: int
    current: LiveLoopCandidate
    next_iteration: int = 1
    stalled_iterations: int = 0
    stopped: bool = False
    started_at: datetime
    total_tokens: int = 0
    total_cost: float | None = 0.0
    previous_findings: tuple[LiveLoopEvidence, ...] = ()
    history: tuple[dict, ...] = ()
    # Internal sidecar only; public v0.2 candidates/specifications/proof remain unchanged.
    runtime_binding: dict | None = None
