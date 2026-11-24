"""OpenCode transport details isolated from the runtime-neutral task-loop kernel."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from langflow.adlc.coding_agent_loop_models import ContractFileProposal
from langflow.adlc.opencode_client import OpenCodeClientError, OpenCodeModelSelection
from langflow.adlc.task_loop_runtime import LoopRuntimeError
from langflow.adlc.task_loop_runtime_models import (
    LoopIterationOutcome,
    LoopRuntimeBinding,
    LoopRuntimeSession,
    LoopRuntimeUsage,
)

if TYPE_CHECKING:
    from langflow.adlc.opencode_client import OpenCodeClient
    from langflow.adlc.task_loop_runtime_models import LoopIterationRequest

OPENCODE_RUNTIME_REF = "runtime:opencode-task-loop/0.1.0"
TASK_LOOP_MODEL = "aigateway/MiniMax/MiniMax-M3"


def opencode_loop_binding(agent: str | None = None) -> LoopRuntimeBinding:
    provider, _, model = TASK_LOOP_MODEL.partition("/")
    return LoopRuntimeBinding(
        runtime_ref=OPENCODE_RUNTIME_REF,
        family="OPENCODE",
        provider_id=provider,
        model_id=model,
        agent=agent,
        modes=("WORKSPACE_EDIT", "FILE_PROPOSAL"),
    )


class OpenCodeTaskLoopRuntime:
    def __init__(self, client: OpenCodeClient, *, agent: str | None = None) -> None:
        self.client = client
        self.model = OpenCodeModelSelection.parse(TASK_LOOP_MODEL)
        self.binding = opencode_loop_binding(agent)

    def _check(self, command: LoopIterationRequest) -> None:
        if command.runtime != self.binding:
            msg = "TASK_LOOP_RUNTIME_MISMATCH"
            raise LoopRuntimeError(msg)

    async def open_iteration(self, command: LoopIterationRequest, *, directory: Path) -> LoopRuntimeSession:
        self._check(command)
        restricted = command.mode == "FILE_PROPOSAL"
        creator = getattr(self.client, "create_restricted_session" if restricted else "create_session", None)
        if creator is None:
            msg = "OPENCODE_CONTRACT_PERMISSIONS_UNAVAILABLE"
            raise LoopRuntimeError(msg)
        try:
            session = await creator(
                directory=str(directory), title=f"task-loop-{command.attempt_id}", timeout_ms=command.timeout_ms
            )
        except OpenCodeClientError as exc:
            raise LoopRuntimeError(exc.code, retryable=exc.retryable) from exc
        # Persist this handle before observing freshness, so any failed observation can be aborted on recovery.
        return LoopRuntimeSession(
            runtime=self.binding,
            request_digest=command.content_digest,
            session_id=session.session_id,
            fresh_context=Path(session.directory).resolve() == directory.resolve(),
            tools_disabled=restricted,
        )

    async def run_iteration(
        self, command: LoopIterationRequest, session: LoopRuntimeSession, *, directory: Path
    ) -> LoopIterationOutcome:
        self._check(command)
        try:
            if await self.client.get_messages(
                session.session_id, directory=str(directory), timeout_ms=command.timeout_ms
            ):
                msg = "TASK_LOOP_SESSION_NOT_FRESH"
                raise LoopRuntimeError(msg)
            reply = await self.client.prompt(
                session.session_id,
                directory=str(directory),
                prompt=command.prompt,
                system=command.system,
                model=self.model,
                agent=self.binding.agent if command.mode == "WORKSPACE_EDIT" else None,
                timeout_ms=command.timeout_ms,
            )
            if reply.provider_id != self.binding.provider_id or reply.model_id != self.binding.model_id:
                msg = "TASK_LOOP_MODEL_MISMATCH"
                raise LoopRuntimeError(msg)
            messages = await self.client.get_messages(
                session.session_id, directory=str(directory), timeout_ms=command.timeout_ms
            )
        except OpenCodeClientError as exc:
            raise LoopRuntimeError(exc.code, retryable=exc.retryable) from exc
        usage = self.usage(messages)
        tools = any(part.get("type") in {"tool", "subtask"} for item in messages for part in item.get("parts", []))
        if command.mode == "FILE_PROPOSAL" and tools:
            msg = "CODING_AGENT_CONTRACT_TOOL_ACTIVITY"
            raise LoopRuntimeError(msg, usage=usage)
        try:
            files = (
                ContractFileProposal.model_validate_json(reply.text).files if command.mode == "FILE_PROPOSAL" else None
            )
        except (ValueError, ValidationError) as exc:
            code = "TASK_LOOP_EXECUTION_INVALID"
            raise LoopRuntimeError(code, usage=usage) from exc
        return LoopIterationOutcome(
            runtime=self.binding,
            request_digest=command.content_digest,
            session_id=session.session_id,
            mode=command.mode,
            usage=usage,
            tool_activity=tools,
            files=files,
        )

    @staticmethod
    def usage(messages: list[dict]) -> LoopRuntimeUsage:
        assistants = {}
        for message in messages:
            if any(part.get("type") == "compaction" for part in message.get("parts", [])):
                msg = "TASK_LOOP_CONTEXT_COMPACTED"
                raise LoopRuntimeError(msg)
            info = message.get("info", {})
            if info.get("summary") is True:
                msg = "TASK_LOOP_CONTEXT_COMPACTED"
                raise LoopRuntimeError(msg)
            if info.get("role") == "assistant" and info.get("id"):
                assistants[info["id"]] = info
        if not assistants:
            msg = "TASK_LOOP_USAGE_UNAVAILABLE"
            raise LoopRuntimeError(msg)
        inputs = outputs = total = 0
        cost = 0.0
        try:
            for info in assistants.values():
                tokens = info.get("tokens", {})
                if (
                    not isinstance(tokens, dict)
                    or "input" not in tokens
                    or "output" not in tokens
                    or "cost" not in info
                ):
                    msg = "TASK_LOOP_USAGE_UNAVAILABLE"
                    raise LoopRuntimeError(msg)
                cache = tokens.get("cache", {})
                counts = [tokens.get(key, 0) for key in ("input", "output", "reasoning")]
                counts += [cache.get(key, 0) for key in ("read", "write")]
                if any(type(value) is not int or value < 0 for value in counts):
                    msg = "Invalid token counts"
                    raise ValueError(msg)
                inputs += counts[0]
                outputs += counts[1]
                total += sum(counts)
                item_cost = info["cost"]
                if type(item_cost) not in (float, int) or item_cost < 0:
                    msg = "Invalid cost"
                    raise ValueError(msg)
                cost += item_cost
            return LoopRuntimeUsage(input_tokens=inputs, output_tokens=outputs, total_tokens=total, cost=cost)
        except (ValueError, TypeError, AttributeError, ValidationError) as exc:
            msg = "TASK_LOOP_USAGE_INVALID"
            raise LoopRuntimeError(msg) from exc

    async def close_iteration(self, session: LoopRuntimeSession, *, directory: Path, abort: bool) -> None:
        if session.runtime != self.binding:
            msg = "TASK_LOOP_RUNTIME_MISMATCH"
            raise LoopRuntimeError(msg)
        try:
            if abort:
                await self.client.abort(session.session_id, directory=str(directory))
            await self.client.dispose_instance(directory=str(directory))
        except OpenCodeClientError as exc:
            raise LoopRuntimeError(exc.code, retryable=exc.retryable) from exc
