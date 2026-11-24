"""Runtime-neutral iteration protocol. These records grant no verification/approval authority."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID  # noqa: TC003 - Pydantic runtime fields.

from pydantic import Field, model_validator

from langflow.adlc.blueprints.canonicalization import sha256_digest
from langflow.adlc.task_loop_live_models import LiveLoopCandidate, LiveLoopSpec, validate_live_path
from langflow.adlc.task_loop_models import Digest, FileContent, LoopModel, validate_files

PROTOCOL = "task-loop-runtime:iteration/0.1.0"
RuntimeName = Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_./:-]+$")]
IterationMode = Literal["WORKSPACE_EDIT", "FILE_PROPOSAL"]


class LoopRuntimeBinding(LoopModel):
    protocol_ref: Literal["task-loop-runtime:iteration/0.1.0"] = PROTOCOL
    runtime_ref: RuntimeName
    family: Literal["OPENCODE", "HARNESS", "CUSTOM"]
    provider_id: RuntimeName
    model_id: RuntimeName
    agent: RuntimeName | None = None
    modes: tuple[IterationMode, ...] = Field(min_length=1, max_length=2)
    fresh_sessions: Literal[True] = True
    reported_usage: Literal[True] = True
    cancellation: Literal[True] = True

    @model_validator(mode="after")
    def unique_modes(self) -> LoopRuntimeBinding:
        if len(set(self.modes)) != len(self.modes):
            msg = "Runtime modes must be unique"
            raise ValueError(msg)
        return self


class LoopCandidateReference(LoopModel):
    candidate_id: UUID
    content_digest: Digest
    iteration: int = Field(ge=0, le=100, strict=True)

    @classmethod
    def of(cls, candidate: LiveLoopCandidate) -> LoopCandidateReference:
        return cls(
            candidate_id=candidate.candidate_id,
            content_digest=candidate.content_digest,
            iteration=candidate.iteration,
        )


class LoopIterationRequest(LoopModel):
    """Private, bounded command: no credentials, host paths or prior conversations."""

    schema_version: Literal["0.1"] = "0.1"
    runtime: LoopRuntimeBinding
    workflow_run_id: UUID
    task_run_id: UUID
    attempt_id: UUID
    request_id: UUID
    iteration: int = Field(ge=1, le=100, strict=True)
    policy_digest: Digest
    specification: LiveLoopSpec
    parent_candidate: LiveLoopCandidate
    mode: IterationMode
    prompt: str = Field(max_length=262_144, strict=True)
    system: str = Field(min_length=1, max_length=4096, strict=True)
    timeout_ms: int = Field(ge=1, le=3_600_000, strict=True)

    @model_validator(mode="after")
    def bound_command(self) -> LoopIterationRequest:
        if (
            self.mode not in self.runtime.modes
            or self.parent_candidate.base_commit != self.specification.base_commit
            or self.parent_candidate.iteration >= self.iteration
            or set(self.parent_candidate.changes) - set(self.specification.writable_paths)
            or len(self.prompt) + len(self.system) > self.specification.context_budget_chars
        ):
            msg = "Iteration scope, mode or context budget is invalid"
            raise ValueError(msg)
        return self

    @property
    def content_digest(self) -> str:
        return sha256_digest(self.model_dump(mode="json"))


class LoopRuntimeSession(LoopModel):
    """Acknowledgement, not a provider transcript. Kernel checks it before prompting."""

    schema_version: Literal["0.1"] = "0.1"
    runtime: LoopRuntimeBinding
    request_digest: Digest
    session_id: str = Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_.:-]+$", strict=True)
    fresh_context: bool = Field(strict=True)
    tools_disabled: bool = Field(strict=True)


class LoopRuntimeUsage(LoopModel):
    input_tokens: int = Field(ge=0, strict=True)
    output_tokens: int = Field(ge=0, strict=True)
    total_tokens: int = Field(ge=0, strict=True)
    cost: float = Field(ge=0, allow_inf_nan=False, strict=True)

    @model_validator(mode="after")
    def consistent_tokens(self) -> LoopRuntimeUsage:
        if self.total_tokens < self.input_tokens + self.output_tokens:
            msg = "Total tokens cannot be smaller than measured input/output"
            raise ValueError(msg)
        return self


class LoopIterationOutcome(LoopModel):
    """Untrusted candidate proposal only; no PASS, checks, artifacts or approval fields."""

    schema_version: Literal["0.1"] = "0.1"
    runtime: LoopRuntimeBinding
    request_digest: Digest
    session_id: str = Field(min_length=1, max_length=512, strict=True)
    mode: IterationMode
    usage: LoopRuntimeUsage
    context_compacted: Literal[False] = False
    tool_activity: bool = Field(strict=True)
    files: dict[str, FileContent] | None = None

    @model_validator(mode="after")
    def proposal_shape(self) -> LoopIterationOutcome:
        if self.mode not in self.runtime.modes:
            msg = "Unsupported outcome mode"
            raise ValueError(msg)
        if self.mode == "FILE_PROPOSAL":
            if self.files is None or self.tool_activity:
                msg = "File proposals require tool-free replacement files"
                raise ValueError(msg)
            validate_files(self.files)
            for path in self.files:
                validate_live_path(path)
        elif self.files is not None:
            msg = "Workspace capture belongs to the kernel, not the runtime response"
            raise ValueError(msg)
        return self


class LoopRuntimeCheckpoint(LoopModel):
    """Portable checkpoint header; source/proof bytes stay in the kernel's sealed ledger."""

    schema_version: Literal["0.1"] = "0.1"
    runtime: LoopRuntimeBinding
    workflow_run_id: UUID
    task_run_id: UUID
    request_id: UUID
    attempt_id: UUID
    iteration: int = Field(ge=1, le=100, strict=True)
    request_digest: Digest
    spec_digest: Digest
    policy_digest: Digest
    parent_candidate: LoopCandidateReference
    mode: IterationMode
    phase: Literal["RESERVED", "AGENT_RUNNING", "CANDIDATE_CAPTURED", "VERIFIED", "FINISHED"]
    session: LoopRuntimeSession | None = None
    usage: LoopRuntimeUsage | None = None
    outcome_digest: Digest | None = None
    candidate: LoopCandidateReference | None = None
    verification_digest: Digest | None = None

    @model_validator(mode="after")
    def sealed_scope(self) -> LoopRuntimeCheckpoint:
        if self.mode not in self.runtime.modes or self.parent_candidate.iteration >= self.iteration:
            msg = "Invalid checkpoint mode/lineage"
            raise ValueError(msg)
        if self.session and (
            self.session.runtime != self.runtime or self.session.request_digest != self.request_digest
        ):
            msg = "Checkpoint session is not bound to this command"
            raise ValueError(msg)
        if self.candidate and self.candidate.iteration != self.iteration:
            msg = "Checkpoint candidate belongs to another iteration"
            raise ValueError(msg)
        if (self.phase in {"CANDIDATE_CAPTURED", "VERIFIED"} or self.candidate is not None) and (
            self.candidate is None or self.outcome_digest is None or self.session is None or self.usage is None
        ):
            msg = "Captured checkpoints need a bound session, outcome, usage and candidate"
            raise ValueError(msg)
        if self.phase == "VERIFIED" and self.verification_digest is None:
            msg = "Verified checkpoints need kernel-owned evidence"
            raise ValueError(msg)
        return self


class LoopRuntimeView(LoopModel):
    """Owner-scoped, content-free read projection; not an execution capability."""

    schema_version: Literal["0.1"] = "0.1"
    workflow_run_id: UUID
    task_run_id: UUID
    binding_source: Literal["CHECKPOINT", "LEGACY", "NOT_STARTED", "UNAVAILABLE"]
    runtime: LoopRuntimeBinding | None = None
    protocol_ref: Literal["task-loop-runtime:iteration/0.1.0"] | None = None
    execution_unified_with_harness: Literal[False] = False
