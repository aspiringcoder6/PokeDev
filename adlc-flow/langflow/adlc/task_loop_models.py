"""Separately versioned contracts for the deterministic task-loop slice."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from langflow.adlc.blueprints.canonicalization import sha256_digest

Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
FileContent = Annotated[str, Field(strict=True, max_length=16_384)]
MAX_FILE_PATH_LENGTH = 255
MAX_FILES = 64
MAX_FILE_BYTES = 65_536


def validate_file_path(path: str) -> str:
    """Use the same relative, platform-independent file names in every snapshot."""
    parts = path.split("/")
    if (
        not path
        or len(path) > MAX_FILE_PATH_LENGTH
        or any(part in {"", ".", "..", ".git"} for part in parts)
        or any(character in path for character in "\\:\x00\r\n")
    ):
        message = "Task-loop file paths must be safe repository-relative POSIX paths"
        raise ValueError(message)
    return path


def validate_files(files: dict[str, str | None]) -> dict[str, str | None]:
    if (
        len(files) > MAX_FILES
        or sum(len((content or "").encode("utf-8")) for content in files.values()) > MAX_FILE_BYTES
    ):
        message = "Task-loop mock files exceed the 64-file/64-KiB bound"
        raise ValueError(message)
    for path in files:
        validate_file_path(path)
    return files


class LoopModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TaskLoopCriterion(LoopModel):
    criterion_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    description: str = Field(min_length=1, max_length=1024)
    verifier_ref: Literal["verifier:task-loop-mock-file/0.1.0"] = "verifier:task-loop-mock-file/0.1.0"
    path: str
    expected_content: FileContent

    _path = field_validator("path")(validate_file_path)


class TaskLoopSpec(LoopModel):
    """Full immutable objective and machine criteria, repeated in every prompt."""

    schema_version: Literal["0.1"] = "0.1"
    spec_id: UUID
    revision: int = Field(default=1, ge=1, strict=True)
    specification: str = Field(min_length=1, max_length=16_384)
    acceptance_criteria: tuple[TaskLoopCriterion, ...] = Field(min_length=1, max_length=32)
    initial_files: dict[str, FileContent] = Field(default_factory=dict)
    max_iterations: int = Field(default=3, ge=1, le=100, strict=True)
    max_stalled_iterations: int = Field(default=2, ge=1, le=100, strict=True)
    context_budget_chars: int = Field(default=131_072, ge=1024, le=262_144, strict=True)

    _files = field_validator("initial_files")(validate_files)

    @model_validator(mode="after")
    def unique_criteria(self) -> TaskLoopSpec:
        identities = [criterion.criterion_id for criterion in self.acceptance_criteria]
        if len(identities) != len(set(identities)):
            message = "Acceptance criterion IDs must be unique"
            raise ValueError(message)
        return self

    @property
    def content_digest(self) -> str:
        return sha256_digest(self.model_dump(mode="json"))


class MockTaskLoopStep(LoopModel):
    """One scripted edit; null deletes a file. Notes are trace data, never context."""

    changes: dict[str, FileContent | None] = Field(default_factory=dict)
    note: str = Field(default="", max_length=1024)

    _changes = field_validator("changes")(validate_files)


class MockTaskLoopConfiguration(LoopModel):
    mock_steps: tuple[MockTaskLoopStep, ...] = Field(min_length=1, max_length=100)


class TaskLoopCandidate(LoopModel):
    schema_version: Literal["0.1"] = "0.1"
    candidate_id: UUID
    parent_candidate_id: UUID | None
    iteration: int = Field(ge=0, strict=True)
    content_digest: Digest
    files: dict[str, FileContent]

    _files = field_validator("files")(validate_files)

    @model_validator(mode="after")
    def verify_digest(self) -> TaskLoopCandidate:
        if self.content_digest != sha256_digest(self.files):
            message = "Candidate contents do not match their digest"
            raise ValueError(message)
        return self


class TaskLoopCheck(LoopModel):
    criterion_id: str
    passed: bool = Field(strict=True)
    message: str


class TaskLoopVerification(LoopModel):
    schema_version: Literal["0.1"] = "0.1"
    mode: Literal["MOCK"] = "MOCK"
    candidate_id: UUID
    candidate_digest: Digest
    checks: tuple[TaskLoopCheck, ...] = Field(min_length=1, max_length=32)

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


class TaskLoopPrompt(LoopModel):
    spec_digest: Digest
    specification: TaskLoopSpec
    candidate: TaskLoopCandidate
    previous_findings: tuple[TaskLoopCheck, ...]


class TaskLoopIteration(LoopModel):
    iteration: int = Field(ge=1)
    request_id: UUID
    attempt_id: UUID
    session_id: UUID
    prompt: TaskLoopPrompt
    candidate: TaskLoopCandidate
    verification: TaskLoopVerification
    agent_note: str

    def summary(self) -> dict:
        """Bounded evidence for TaskResult metadata, excluding prompts/file bytes."""
        return {
            "iteration": self.iteration,
            "request_id": str(self.request_id),
            "attempt_id": str(self.attempt_id),
            "session_id": str(self.session_id),
            "spec_digest": self.prompt.spec_digest,
            "input_candidate_id": str(self.prompt.candidate.candidate_id),
            "candidate_id": str(self.candidate.candidate_id),
            "candidate_digest": self.candidate.content_digest,
            "verification": self.verification.model_dump(mode="json"),
        }
