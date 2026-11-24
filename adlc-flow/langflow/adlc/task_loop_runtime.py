"""Replaceable runtime port. ADLC owns iteration scheduling, capture, proof and human gates."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path

    from langflow.adlc.task_loop_runtime_models import (
        LoopIterationOutcome,
        LoopIterationRequest,
        LoopRuntimeBinding,
        LoopRuntimeSession,
        LoopRuntimeUsage,
    )


class LoopRuntimeError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False, usage: LoopRuntimeUsage | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.usage = usage


class TaskLoopRuntime(Protocol):
    @property
    def binding(self) -> LoopRuntimeBinding:
        """Exact adapter/model/agent/capability identity; pinned for the whole loop."""
        ...

    async def open_iteration(self, command: LoopIterationRequest, *, directory: Path) -> LoopRuntimeSession:
        """Open a fresh session, without prompting; acknowledge scope and tool restrictions."""
        ...

    async def run_iteration(
        self, command: LoopIterationRequest, session: LoopRuntimeSession, *, directory: Path
    ) -> LoopIterationOutcome:
        """One bounded call; no hidden retry, conversation reuse, checks or approval."""
        ...

    async def close_iteration(self, session: LoopRuntimeSession, *, directory: Path, abort: bool) -> None:
        """Best-effort release of this exact session only; never dispatch new work."""
        ...
