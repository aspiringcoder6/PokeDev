"""DSH Task Loop SDK — high-level wrapper for submitting task_loop_spec to DSH.

This SDK provides a Pythonic interface for building, validating, and
submitting ``task_loop_spec`` (schema ``adlc://schemas/task-loop-spec/0.2``)
to a remote DSH server. It enforces all required fields, applies sensible
defaults, and delegates the loop to DSH (via the vai-taskloop plugin).

Design goals:
- **Required-first**: every required field is validated before submission;
  missing fields raise ``DSHTaskLoopSpecError`` with a precise message.
- **User-editable**: every field (required or optional) can be overridden
  by the caller; defaults are only applied when the caller leaves a field
  unset.
- **DSH-side loop**: the ``loop_until_pass`` flag (default ``True``) tells
  the DSH agent to keep iterating until all acceptance criteria pass.
  Our SDK does NOT loop on its own — it submits once and waits for DSH
  to finish. This matches the ADLC UI checkbox semantics: the user ticks
  "loop until pass" in the node info display, and DSH handles the loop.
- **DSH coding agent**: the SDK targets the DSH server's coding agent
  (``agent-provider:dsh``) by default, so the LLM agent in DSH uses the
  vai-sandbox / vai-testforce / vai_agentmemory plugins.
- **Re-request on missing info**: if the DSH session reports that the
  spec is incomplete, the SDK raises ``DSHTaskLoopIncompleteSpecError``
  with the list of fields the DSH agent asked the caller to fill in.

Example:
    >>> from langflow.adlc.sdk.dsh_task_loop_sdk import DSHTaskLoopSDK, DSHTaskLoopSpec
    >>> sdk = DSHTaskLoopSDK.from_env()
    >>> spec = DSHTaskLoopSpec(
    ...     specification="Implement add(a, b) and document it in README.md.",
    ...     base_commit="a1b2c3d4e5f6789012345678901234567890abcd",
    ...     writable_paths=["math_utils.py", "README.md"],
    ...     acceptance_criteria=[
    ...         DSHTaskLoopCriterion(
    ...             criterion_id="addition",
    ...             description="add(a, b) returns a + b",
    ...             check_refs=["acceptance"],
    ...         ),
    ...     ],
    ...     verification_commands=[
    ...         DSHTaskLoopCommand(
    ...             check_id="acceptance",
    ...             test_path="test_acceptance.py",
    ...         ),
    ...     ],
    ... )
    >>> result = await sdk.run(spec)
    >>> print(result.status, result.final_text)
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID

from langflow.adlc.harness_dsh_client import DshHarnessClient
from langflow.adlc.harness_client import HarnessServerSettings


SCHEMA_REF = "adlc://schemas/task-loop-spec/0.2"
SCHEMA_VERSION = "0.2"

# Default verifier — the only registered runner in v0.2.
DEFAULT_VERIFIER_REF = "verifier:python-unittest/0.1.0"

# Default loop budgets. These are passed to DSH as hints; DSH (via
# vai-taskloop) is responsible for enforcing them. Our SDK does NOT loop.
DEFAULT_MAX_ITERATIONS = 25
DEFAULT_MAX_STALLED_ITERATIONS = 3
DEFAULT_CONTEXT_BUDGET_CHARS = 131072  # 128 KiB
DEFAULT_MAX_DURATION_MS = 1_800_000  # 30 minutes
DEFAULT_MAX_TOTAL_TOKENS = 200_000
DEFAULT_MAX_TOTAL_COST = 10.0  # USD

# Validation bounds (mirror the JSON schema).
SPECIFICATION_MIN = 1
SPECIFICATION_MAX = 16_384
WRITABLE_PATHS_MIN = 1
WRITABLE_PATHS_MAX = 64
ACCEPTANCE_CRITERIA_MIN = 1
ACCEPTANCE_CRITERIA_MAX = 32
VERIFICATION_COMMANDS_MIN = 1
VERIFICATION_COMMANDS_MAX = 16
CHECK_REFS_MIN = 1
CHECK_REFS_MAX = 16
TIMEOUT_MS_MIN = 100
TIMEOUT_MS_MAX = 120_000
CONTEXT_BUDGET_CHARS_MIN = 1024
CONTEXT_BUDGET_CHARS_MAX = 262_144
MAX_DURATION_MS_MIN = 1000
MAX_DURATION_MS_MAX = 3_600_000
MAX_ITERATIONS_MIN = 1
MAX_ITERATIONS_MAX = 100
MAX_STALLED_ITERATIONS_MIN = 1
MAX_STALLED_ITERATIONS_MAX = 100

# Identifier pattern: lowercase letter, then lowercase letters / digits / underscores.
_IDENT_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_BASE_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


# ---- Error types ----------------------------------------------------------


class DSHTaskLoopSpecError(ValueError):
    """Raised when a ``DSHTaskLoopSpec`` is missing required fields or invalid."""

    def __init__(self, message: str, *, missing_fields: list[str] | None = None) -> None:
        super().__init__(message)
        self.missing_fields = missing_fields or []


class DSHTaskLoopIncompleteSpecError(DSHTaskLoopSpecError):
    """Raised when the DSH agent reports the spec is incomplete.

    The ``requested_fields`` attribute lists the field names the DSH agent
    asked the caller to fill in before resubmitting.
    """

    def __init__(self, message: str, requested_fields: list[str]) -> None:
        super().__init__(message, missing_fields=requested_fields)
        self.requested_fields = requested_fields


# ---- Enums ----------------------------------------------------------------


class LoopExitReason(str, Enum):
    """Why the DSH task loop stopped (reported by DSH, not by our SDK)."""

    ALL_CRITERIA_PASSED = "all_criteria_passed"
    MAX_ITERATIONS_REACHED = "max_iterations_reached"
    MAX_STALLED_REACHED = "max_stalled_reached"
    MAX_DURATION_REACHED = "max_duration_reached"
    MAX_TOKENS_REACHED = "max_tokens_reached"
    MAX_COST_REACHED = "max_cost_reached"
    SESSION_FAILED = "session_failed"
    CANCELLED = "cancelled"


# ---- Spec data classes ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class DSHTaskLoopCriterion:
    """One acceptance criterion mapped to one or more verification checks."""

    criterion_id: str
    description: str
    check_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.criterion_id, str) or not _IDENT_PATTERN.match(self.criterion_id):
            msg = (
                f"criterion_id must match {_IDENT_PATTERN.pattern!r}; "
                f"got {self.criterion_id!r}"
            )
            raise DSHTaskLoopSpecError(msg)
        if (
            not isinstance(self.description, str)
            or not SPECIFICATION_MIN <= len(self.description) <= 1024
        ):
            msg = f"description must be 1..1024 chars; got len={len(self.description)}"
            raise DSHTaskLoopSpecError(msg)
        if (
            not isinstance(self.check_refs, tuple)
            or not CHECK_REFS_MIN <= len(self.check_refs) <= CHECK_REFS_MAX
        ):
            msg = f"check_refs must have {CHECK_REFS_MIN}..{CHECK_REFS_MAX} items"
            raise DSHTaskLoopSpecError(msg)
        for ref in self.check_refs:
            if not isinstance(ref, str) or not _IDENT_PATTERN.match(ref):
                msg = f"check_ref entry must match {_IDENT_PATTERN.pattern!r}; got {ref!r}"
                raise DSHTaskLoopSpecError(msg)

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "description": self.description,
            "check_refs": list(self.check_refs),
        }


@dataclass(frozen=True, slots=True)
class DSHTaskLoopCommand:
    """One registered verification command (not a free-form shell command)."""

    check_id: str
    test_path: str
    verifier_ref: str = DEFAULT_VERIFIER_REF
    timeout_ms: int = 30_000

    def __post_init__(self) -> None:
        if not isinstance(self.check_id, str) or not _IDENT_PATTERN.match(self.check_id):
            msg = (
                f"check_id must match {_IDENT_PATTERN.pattern!r}; "
                f"got {self.check_id!r}"
            )
            raise DSHTaskLoopSpecError(msg)
        if not isinstance(self.test_path, str) or not self.test_path.strip():
            msg = "test_path must be a non-empty string"
            raise DSHTaskLoopSpecError(msg)
        if self.verifier_ref != DEFAULT_VERIFIER_REF:
            msg = (
                f"verifier_ref must be the const {DEFAULT_VERIFIER_REF!r}; "
                f"got {self.verifier_ref!r}"
            )
            raise DSHTaskLoopSpecError(msg)
        if not TIMEOUT_MS_MIN <= self.timeout_ms <= TIMEOUT_MS_MAX:
            msg = f"timeout_ms must be {TIMEOUT_MS_MIN}..{TIMEOUT_MS_MAX}; got {self.timeout_ms}"
            raise DSHTaskLoopSpecError(msg)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "verifier_ref": self.verifier_ref,
            "test_path": self.test_path,
            "timeout_ms": self.timeout_ms,
        }


@dataclass(frozen=True, slots=True)
class DSHTaskLoopSpec:
    """A complete ``task_loop_spec`` (schema v0.2) ready to submit to DSH.

    Required fields (no defaults — caller MUST supply):
        - ``specification``: full immutable objective
        - ``base_commit``: 40-char hex Git commit
        - ``writable_paths``: exact list of files the agent may write
        - ``acceptance_criteria``: 1..32 criteria, each mapped to checks
        - ``verification_commands``: 1..16 registered runner commands

    Optional fields (sensible defaults applied if omitted):
        - ``spec_id``: auto-generated UUID4
        - ``revision``: 1
        - ``loop_until_pass``: True (DSH loops until all criteria pass)
        - ``max_iterations``: 25 (DSH-side budget hint)
        - ``max_stalled_iterations``: 3
        - ``context_budget_chars``: 131072
        - ``max_duration_ms``: 1_800_000 (30 min)
        - ``max_total_tokens``: 200_000
        - ``max_total_cost``: 10.0 USD
    """

    specification: str
    base_commit: str
    writable_paths: tuple[str, ...]
    acceptance_criteria: tuple[DSHTaskLoopCriterion, ...]
    verification_commands: tuple[DSHTaskLoopCommand, ...]

    spec_id: UUID = field(default_factory=uuid.uuid4)
    revision: int = 1
    loop_until_pass: bool = True  # DSH-side loop flag (UI checkbox)
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    max_stalled_iterations: int = DEFAULT_MAX_STALLED_ITERATIONS
    context_budget_chars: int = DEFAULT_CONTEXT_BUDGET_CHARS
    max_duration_ms: int = DEFAULT_MAX_DURATION_MS
    max_total_tokens: int | None = DEFAULT_MAX_TOTAL_TOKENS
    max_total_cost: float | None = DEFAULT_MAX_TOTAL_COST

    def __post_init__(self) -> None:
        # ---- Required field validation ------------------------------------
        missing: list[str] = []
        if not isinstance(self.specification, str) or not (
            SPECIFICATION_MIN <= len(self.specification) <= SPECIFICATION_MAX
        ):
            missing.append(
                f"specification (must be {SPECIFICATION_MIN}..{SPECIFICATION_MAX} chars; "
                f"got len={len(self.specification) if isinstance(self.specification, str) else 'n/a'})"
            )
        if not isinstance(self.base_commit, str) or not _BASE_COMMIT_PATTERN.match(self.base_commit):
            missing.append(
                f"base_commit (must be 40 hex chars; got {self.base_commit!r})"
            )
        if (
            not isinstance(self.writable_paths, tuple)
            or not WRITABLE_PATHS_MIN <= len(self.writable_paths) <= WRITABLE_PATHS_MAX
        ):
            missing.append(
                f"writable_paths (must have {WRITABLE_PATHS_MIN}..{WRITABLE_PATHS_MAX} items)"
            )
        if (
            not isinstance(self.acceptance_criteria, tuple)
            or not ACCEPTANCE_CRITERIA_MIN
            <= len(self.acceptance_criteria)
            <= ACCEPTANCE_CRITERIA_MAX
        ):
            missing.append(
                f"acceptance_criteria (must have {ACCEPTANCE_CRITERIA_MIN}..{ACCEPTANCE_CRITERIA_MAX} items)"
            )
        if (
            not isinstance(self.verification_commands, tuple)
            or not VERIFICATION_COMMANDS_MIN
            <= len(self.verification_commands)
            <= VERIFICATION_COMMANDS_MAX
        ):
            missing.append(
                f"verification_commands (must have {VERIFICATION_COMMANDS_MIN}..{VERIFICATION_COMMANDS_MAX} items)"
            )

        if missing:
            msg = "DSHTaskLoopSpec is missing required fields: " + "; ".join(missing)
            raise DSHTaskLoopSpecError(msg, missing_fields=missing)

        # ---- Cross-field validation: every check_ref must exist -----------
        check_ids = {cmd.check_id for cmd in self.verification_commands}
        for criterion in self.acceptance_criteria:
            for ref in criterion.check_refs:
                if ref not in check_ids:
                    msg = (
                        f"criterion {criterion.criterion_id!r} references unknown "
                        f"check_id {ref!r}; known check_ids: {sorted(check_ids)}"
                    )
                    raise DSHTaskLoopSpecError(msg)

        # ---- Optional field bounds ----------------------------------------
        if not isinstance(self.revision, int) or self.revision < 1:
            raise DSHTaskLoopSpecError(f"revision must be >= 1; got {self.revision}")
        if not isinstance(self.loop_until_pass, bool):
            raise DSHTaskLoopSpecError(
                f"loop_until_pass must be a bool; got {type(self.loop_until_pass).__name__}"
            )
        if not MAX_ITERATIONS_MIN <= self.max_iterations <= MAX_ITERATIONS_MAX:
            raise DSHTaskLoopSpecError(
                f"max_iterations must be {MAX_ITERATIONS_MIN}..{MAX_ITERATIONS_MAX}; "
                f"got {self.max_iterations}"
            )
        if not (
            MAX_STALLED_ITERATIONS_MIN
            <= self.max_stalled_iterations
            <= MAX_STALLED_ITERATIONS_MAX
        ):
            raise DSHTaskLoopSpecError(
                f"max_stalled_iterations must be "
                f"{MAX_STALLED_ITERATIONS_MIN}..{MAX_STALLED_ITERATIONS_MAX}; "
                f"got {self.max_stalled_iterations}"
            )
        if not (
            CONTEXT_BUDGET_CHARS_MIN
            <= self.context_budget_chars
            <= CONTEXT_BUDGET_CHARS_MAX
        ):
            raise DSHTaskLoopSpecError(
                f"context_budget_chars must be "
                f"{CONTEXT_BUDGET_CHARS_MIN}..{CONTEXT_BUDGET_CHARS_MAX}; "
                f"got {self.context_budget_chars}"
            )
        if not MAX_DURATION_MS_MIN <= self.max_duration_ms <= MAX_DURATION_MS_MAX:
            raise DSHTaskLoopSpecError(
                f"max_duration_ms must be {MAX_DURATION_MS_MIN}..{MAX_DURATION_MS_MAX}; "
                f"got {self.max_duration_ms}"
            )
        if self.max_total_tokens is not None and self.max_total_tokens < 1:
            raise DSHTaskLoopSpecError(
                f"max_total_tokens must be >= 1 or None; got {self.max_total_tokens}"
            )
        if self.max_total_cost is not None and self.max_total_cost <= 0:
            raise DSHTaskLoopSpecError(
                f"max_total_cost must be > 0 or None; got {self.max_total_cost}"
            )

    # ---- Editing helpers (return new instances — dataclass is frozen) -----

    def with_overrides(self, **kwargs: Any) -> DSHTaskLoopSpec:
        """Return a copy of this spec with the given fields overridden.

        Use this to tweak defaults without rebuilding the spec from scratch.
        """
        return replace(self, **kwargs)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the JSON shape expected by the DSH task loop."""
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "spec_id": str(self.spec_id),
            "revision": self.revision,
            "specification": self.specification,
            "base_commit": self.base_commit,
            "writable_paths": list(self.writable_paths),
            "acceptance_criteria": [c.to_dict() for c in self.acceptance_criteria],
            "verification_commands": [c.to_dict() for c in self.verification_commands],
            "loop_until_pass": self.loop_until_pass,
            "max_iterations": self.max_iterations,
            "max_stalled_iterations": self.max_stalled_iterations,
            "context_budget_chars": self.context_budget_chars,
            "max_duration_ms": self.max_duration_ms,
        }
        if self.max_total_tokens is not None:
            payload["max_total_tokens"] = self.max_total_tokens
        if self.max_total_cost is not None:
            payload["max_total_cost"] = self.max_total_cost
        return payload

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DSHTaskLoopSpec:
        """Build a spec from a parsed JSON dict (e.g. loaded from disk)."""
        try:
            criteria = tuple(
                DSHTaskLoopCriterion(
                    criterion_id=item["criterion_id"],
                    description=item["description"],
                    check_refs=tuple(item["check_refs"]),
                )
                for item in payload["acceptance_criteria"]
            )
            commands = tuple(
                DSHTaskLoopCommand(
                    check_id=item["check_id"],
                    test_path=item["test_path"],
                    verifier_ref=item.get("verifier_ref", DEFAULT_VERIFIER_REF),
                    timeout_ms=item.get("timeout_ms", 30_000),
                )
                for item in payload["verification_commands"]
            )
            return cls(
                specification=payload["specification"],
                base_commit=payload["base_commit"],
                writable_paths=tuple(payload["writable_paths"]),
                acceptance_criteria=criteria,
                verification_commands=commands,
                spec_id=UUID(payload["spec_id"]) if "spec_id" in payload else uuid.uuid4(),
                revision=payload.get("revision", 1),
                loop_until_pass=payload.get("loop_until_pass", True),
                max_iterations=payload.get("max_iterations", DEFAULT_MAX_ITERATIONS),
                max_stalled_iterations=payload.get(
                    "max_stalled_iterations", DEFAULT_MAX_STALLED_ITERATIONS
                ),
                context_budget_chars=payload.get(
                    "context_budget_chars", DEFAULT_CONTEXT_BUDGET_CHARS
                ),
                max_duration_ms=payload.get("max_duration_ms", DEFAULT_MAX_DURATION_MS),
                max_total_tokens=payload.get("max_total_tokens", DEFAULT_MAX_TOTAL_TOKENS),
                max_total_cost=payload.get("max_total_cost", DEFAULT_MAX_TOTAL_COST),
            )
        except KeyError as exc:
            raise DSHTaskLoopSpecError(
                f"missing required field in payload: {exc.args[0]}"
            ) from exc


# ---- Result types ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DSHTaskLoopResult:
    """Final result of a DSH task loop run.

    Our SDK does NOT loop — it submits the spec to DSH once and waits for
    DSH (via vai-taskloop) to finish. The ``exit_reason`` and ``final_text``
    are reported by DSH.
    """

    spec: DSHTaskLoopSpec
    session_id: str
    final_text: str | None
    exit_reason: LoopExitReason
    started_at: datetime
    completed_at: datetime
    iterations: int = 1  # DSH may iterate internally; we report the count

    @property
    def passed(self) -> bool:
        return self.exit_reason is LoopExitReason.ALL_CRITERIA_PASSED

    @property
    def duration_seconds(self) -> float:
        return (self.completed_at - self.started_at).total_seconds()


# ---- SDK ------------------------------------------------------------------


@dataclass
class DSHTaskLoopSDK:
    """High-level SDK for submitting ``task_loop_spec`` to a DSH server.

    The SDK wraps a :class:`DshHarnessClient` and submits the spec to DSH.
    DSH (via the vai-taskloop plugin) is responsible for the loop — our
    SDK does NOT iterate on its own. The ``loop_until_pass`` flag in the
    spec tells DSH whether to keep iterating until all acceptance
    criteria pass.

    Every required field is validated up front; the SDK raises
    :class:`DSHTaskLoopSpecError` with a precise list of missing fields
    if the spec is incomplete.
    """

    client: DshHarnessClient
    coding_agent: str = "agent-provider:dsh"
    poll_interval_seconds: float = 2.0
    wait_timeout_seconds: float = 3600.0  # 1 hour

    @classmethod
    def from_env(
        cls,
        *,
        client: DshHarnessClient | None = None,
        coding_agent: str | None = None,
    ) -> DSHTaskLoopSDK:
        """Build the SDK from ``ADLC_HARNESS_*`` environment variables."""
        if client is None:
            settings = HarnessServerSettings.from_environment()
            client = DshHarnessClient(settings)
        agent = coding_agent or os.getenv("ADLC_CODING_AGENT", "agent-provider:dsh")
        return cls(client=client, coding_agent=agent)

    # ---- Validation helpers ----------------------------------------------

    @staticmethod
    def validate(spec: DSHTaskLoopSpec) -> None:
        """Re-validate a spec; raises :class:`DSHTaskLoopSpecError` on failure."""
        # The dataclass ``__post_init__`` already validates; calling it again
        # is a no-op for valid specs and surfaces a clear error for invalid ones.
        # We rebuild via ``from_dict`` to force re-validation.
        DSHTaskLoopSpec.from_dict(spec.to_dict())

    @staticmethod
    def missing_fields(spec: DSHTaskLoopSpec) -> list[str]:
        """Return the list of required fields that are missing or invalid.

        Returns an empty list when the spec is complete.
        """
        missing: list[str] = []
        if not (
            isinstance(spec.specification, str)
            and SPECIFICATION_MIN <= len(spec.specification) <= SPECIFICATION_MAX
        ):
            missing.append("specification")
        if not (
            isinstance(spec.base_commit, str)
            and _BASE_COMMIT_PATTERN.match(spec.base_commit)
        ):
            missing.append("base_commit")
        if not (
            isinstance(spec.writable_paths, tuple)
            and WRITABLE_PATHS_MIN <= len(spec.writable_paths) <= WRITABLE_PATHS_MAX
        ):
            missing.append("writable_paths")
        if not (
            isinstance(spec.acceptance_criteria, tuple)
            and ACCEPTANCE_CRITERIA_MIN <= len(spec.acceptance_criteria) <= ACCEPTANCE_CRITERIA_MAX
        ):
            missing.append("acceptance_criteria")
        if not (
            isinstance(spec.verification_commands, tuple)
            and VERIFICATION_COMMANDS_MIN <= len(spec.verification_commands) <= VERIFICATION_COMMANDS_MAX
        ):
            missing.append("verification_commands")
        return missing

    # ---- Submission -------------------------------------------------------

    async def submit(self, spec: DSHTaskLoopSpec) -> DSHTaskLoopResult:
        """Submit the spec to DSH and wait for it to finish.

        DSH (via vai-taskloop) handles the loop internally. Our SDK just
        sends the prompt and waits for the session to reach a terminal
        state. The ``loop_until_pass`` flag in the spec tells DSH whether
        to keep iterating until all acceptance criteria pass.
        """
        import asyncio

        self.validate(spec)
        started_at = datetime.now(timezone.utc)
        payload = spec.to_dict()

        # Create a session and send the prompt.
        session = await self.client._dsh.create_session()  # noqa: SLF001
        try:
            await session.prompt(self._compose_prompt(spec, payload))

            # Wait for the session to finish (DSH handles the loop).
            wait_result = await session.wait(
                timeout_s=self.wait_timeout_seconds,
                poll_s=self.poll_interval_seconds,
            )

            final_text = wait_result.get("final_text") or ""
            exit_reason = self._parse_exit_reason(final_text, wait_result)
            iterations = self._parse_iteration_count(final_text)

            return DSHTaskLoopResult(
                spec=spec,
                session_id=session.session_id,
                final_text=final_text,
                exit_reason=exit_reason,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                iterations=iterations,
            )
        finally:
            try:
                await session.cancel()
            except Exception:
                pass

    async def run(self, spec: DSHTaskLoopSpec) -> DSHTaskLoopResult:
        """Alias for :meth:`submit` — submits the spec and waits for DSH.

        Kept for backward compatibility with the previous SDK API.
        """
        return await self.submit(spec)

    # ---- Internals --------------------------------------------------------

    def _compose_prompt(
        self,
        spec: DSHTaskLoopSpec,
        payload: dict[str, Any],
    ) -> str:
        """Render the spec as a DSH prompt for the coding agent."""
        criteria_lines = "\n".join(
            f"- [{c.criterion_id}] {c.description} (checks: {', '.join(c.check_refs)})"
            for c in spec.acceptance_criteria
        )
        commands_lines = "\n".join(
            f"- {c.check_id}: {c.verifier_ref} {c.test_path} (timeout {c.timeout_ms}ms)"
            for c in spec.verification_commands
        )
        writable_lines = "\n".join(f"- {p}" for p in spec.writable_paths)

        # Loop instruction — only included when loop_until_pass is True.
        loop_instruction = ""
        if spec.loop_until_pass:
            loop_instruction = (
                f"\n## Loop until pass (UI checkbox: ON)\n"
                f"You MUST keep iterating until ALL acceptance criteria pass.\n"
                f"- Maximum iterations: {spec.max_iterations}\n"
                f"- Maximum stalled iterations: {spec.max_stalled_iterations}\n"
                f"- Maximum duration: {spec.max_duration_ms / 1000:.0f} seconds\n"
                f"- Maximum tokens: {spec.max_total_tokens or 'unlimited'}\n"
                f"- Maximum cost: ${spec.max_total_cost or 'unlimited'}\n"
                f"\n"
                f"After each iteration:\n"
                f"1. Run the verification commands.\n"
                f"2. If any criterion fails, fix the code and re-run.\n"
                f"3. If all criteria pass, report DONE.\n"
                f"4. If you hit a budget limit, report the reason.\n"
            )
        else:
            loop_instruction = (
                f"\n## Loop until pass (UI checkbox: OFF)\n"
                f"Run the verification commands ONCE. Report the result.\n"
            )

        return (
            f"You are the {self.coding_agent} coding agent. "
            f"Complete the following task loop specification.\n\n"
            f"## Specification (schema {SCHEMA_REF})\n"
            f"```json\n{json.dumps(payload, indent=2, ensure_ascii=False)}\n```\n\n"
            f"## Acceptance criteria\n{criteria_lines}\n\n"
            f"## Verification commands\n{commands_lines}\n\n"
            f"## Writable paths (you may ONLY modify these)\n{writable_lines}\n"
            f"{loop_instruction}\n"
            f"## Instructions\n"
            f"1. Use the vai-sandbox plugin to create an isolated execution environment.\n"
            f"2. Implement the specification by editing ONLY the writable paths above.\n"
            f"3. Use the vai-testforce plugin to run the verification commands.\n"
            f"4. Use the vai_agentmemory plugin to persist and recall relevant context.\n"
            f"5. When done, reply with a single final message in this format:\n"
            f"   - If all criteria pass: `ALL_CRITERIA_PASSED` followed by the list of passed criterion_ids.\n"
            f"   - If any criterion fails: `CRITERIA_FAILED` followed by the list of failed criterion_ids.\n"
            f"   - If a budget was hit: `EXIT_REASON: <reason>` (e.g. MAX_ITERATIONS_REACHED).\n"
        )

    @staticmethod
    def _parse_exit_reason(
        final_text: str,
        wait_result: dict[str, Any],
    ) -> LoopExitReason:
        """Parse the DSH agent's final message into an exit reason.

        The agent may put the status marker anywhere in the message
        (start, middle, or end), so we search for the marker as a
        whole-word match rather than requiring it at the start.
        """
        import re

        text = final_text.strip()
        # Check for explicit exit reason markers (whole-word match).
        if re.search(r"\bALL_CRITERIA_PASSED\b", text):
            return LoopExitReason.ALL_CRITERIA_PASSED
        if re.search(r"\bCRITERIA_FAILED\b", text):
            return LoopExitReason.MAX_ITERATIONS_REACHED
        if re.search(r"\bMAX_ITERATIONS_REACHED\b", text):
            return LoopExitReason.MAX_ITERATIONS_REACHED
        if re.search(r"\bMAX_STALLED_REACHED\b", text):
            return LoopExitReason.MAX_STALLED_REACHED
        if re.search(r"\bMAX_DURATION_REACHED\b", text):
            return LoopExitReason.MAX_DURATION_REACHED
        if re.search(r"\bMAX_TOKENS_REACHED\b", text):
            return LoopExitReason.MAX_TOKENS_REACHED
        if re.search(r"\bMAX_COST_REACHED\b", text):
            return LoopExitReason.MAX_COST_REACHED
        if wait_result.get("timeout"):
            return LoopExitReason.MAX_DURATION_REACHED
        return LoopExitReason.SESSION_FAILED

    @staticmethod
    def _parse_iteration_count(final_text: str) -> int:
        """Try to extract the iteration count from the DSH agent's final message."""
        import re

        # Match patterns like "5 iterations", "iteration: 5", "iterations=5"
        m = re.search(r"(\d+)\s+iterations?|iterations?\s*[:=]\s*(\d+)", final_text, re.IGNORECASE)
        if m:
            return int(m.group(1) or m.group(2))
        return 1


__all__ = [
    "DSHTaskLoopSDK",
    "DSHTaskLoopSpec",
    "DSHTaskLoopCriterion",
    "DSHTaskLoopCommand",
    "DSHTaskLoopResult",
    "DSHTaskLoopSpecError",
    "DSHTaskLoopIncompleteSpecError",
    "LoopExitReason",
    "SCHEMA_REF",
    "SCHEMA_VERSION",
    "DEFAULT_VERIFIER_REF",
    "DEFAULT_MAX_ITERATIONS",
    "DEFAULT_MAX_STALLED_ITERATIONS",
    "DEFAULT_CONTEXT_BUDGET_CHARS",
    "DEFAULT_MAX_DURATION_MS",
    "DEFAULT_MAX_TOTAL_TOKENS",
    "DEFAULT_MAX_TOTAL_COST",
]
