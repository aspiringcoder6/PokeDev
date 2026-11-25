from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from langflow.adlc.source_access import SourceRef

from .models import (
    Assessment,
    CollectionResult,
    ContextNeeded,
    ContextRequest,
    ContextVerdict,
    HumanQuestion,
    ImpactReport,
    ReviewResult,
    canonical_digest,
)
from .skills import NativeAuthorizationRequired

ROLES = (
    "collector",
    "context-verifier",
    "reviewer-a",
    "reviewer-b",
    "clarifier",
    "impact-code",
    "impact-requirements",
    "assessor",
)


class AgentRunner(Protocol):
    async def ask(self, role, snapshot, payload, operation_id) -> dict: ...


def session_id_for(operation_id):
    return str(uuid5(NAMESPACE_URL, "pokedev:requirement-readiness:" + operation_id))


def parse_agent_output(result):
    if result.get("timeout"):
        raise ValueError("READINESS_AGENT_UNCONFIRMED")
    try:

        def no_duplicates(pairs):
            out = {}
            for key, value in pairs:
                if key in out:
                    raise ValueError("duplicate key")
                out[key] = value
            return out

        output = json.loads(
            result["final_text"],
            object_pairs_hook=no_duplicates,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
        if not isinstance(output, dict):
            raise ValueError()
        return output
    except (KeyError, TypeError, ValueError):
        raise ValueError("READINESS_AGENT_OUTPUT_INVALID") from None


class DshAgentRunner:
    def __init__(
        self,
        client,
        store,
        prompt_root,
        skill_catalog,
        preset_by_role,
        source_broker=None,
        max_prompt_bytes=1_400_000,
        native_runner=None,
    ):
        self.client, self.store = client, store
        self.prompt_root, self.skills = Path(prompt_root), skill_catalog
        self.presets, self.source_broker = dict(preset_by_role), source_broker
        self.max_prompt_bytes, self.native_runner = min(max_prompt_bytes, 1_400_000), native_runner
        self._auth_lock = asyncio.Lock()
        self._authenticated = False
        if getattr(getattr(client, "retry", None), "max_attempts", 1) != 1:
            raise ValueError("READINESS_TRANSPORT_RETRIES_UNSAFE")

    async def authenticate(self):
        async with self._auth_lock:
            if not self._authenticated and hasattr(self.client, "__aenter__"):
                await self.client.__aenter__()
            self._authenticated = True

    @staticmethod
    def event_text(event):
        data = event.get("data") or {}
        message = data.get("message") or data
        return "\n".join(block.get("text", "") for block in message.get("content", ()) if block.get("type") == "text")

    async def submit(self, session, text, key, prior):
        if not hasattr(session, "prompt"):
            # The test transport port is run-only. Production SDK always takes the
            # acknowledged prompt/cursor path below.
            if not prior.is_new:
                raise ValueError("READINESS_AGENT_UNCONFIRMED")
            return parse_agent_output(await session.run(text))
        marker = f"[readiness exchange {key}]"
        text = text + "\n" + marker
        if len(json.dumps({"text": text}, ensure_ascii=True).encode()) > self.max_prompt_bytes:
            raise ValueError("SOURCE_CONTEXT_LIMIT")
        if prior.is_new:
            cursor = await session.cursor()
            metadata = {"cursor": cursor, "accepted": False, "marker": marker}
            self.store.operation_state(key, "INTENT", metadata)
            accepted = await session.prompt(text, mode="queue")
            if accepted is not True:
                raise ValueError("READINESS_AGENT_UNCONFIRMED")
            metadata["accepted"] = True
            self.store.operation_state(key, "ACKNOWLEDGED", metadata)
        else:
            metadata = prior.result or {}
            if "cursor" not in metadata:
                raise ValueError("READINESS_AGENT_UNCONFIRMED")
            cursor = metadata["cursor"]
            events = await session.history()
            if not metadata.get("accepted") and not any(
                e.get("seq", -1) > cursor and e.get("type") == "user/message" and marker in self.event_text(e)
                for e in events
            ):
                raise ValueError("READINESS_AGENT_UNCONFIRMED")
        result = await session.wait()
        if result.get("timeout"):
            raise ValueError("READINESS_AGENT_UNCONFIRMED")
        events = await session.history()
        fresh = [e for e in events if e.get("type") == "assistant/message" and e.get("seq", -1) > cursor]
        if not fresh:
            raise ValueError("READINESS_AGENT_UNCONFIRMED")
        newest = max(fresh, key=lambda e: e["seq"])
        return parse_agent_output({"final_text": self.event_text(newest)})

    @property
    def manifest_digest(self):
        return canonical_digest(
            {
                "presets": self.presets,
                "skills": self.skills.digest if self.skills else None,
                "prompts": {r: (self.prompt_root / f"{r}.md").read_text(encoding="utf-8") for r in ROLES},
            }
        )

    async def ask(self, role, snapshot, payload, operation_id):
        if role not in ROLES or role not in self.presets:
            raise ValueError("READINESS_ROLE_INVALID")
        run = self.store.load(snapshot["run_id"])
        if run.runtime_manifest_digest and run.runtime_manifest_digest != self.manifest_digest:
            raise ValueError("READINESS_RUNTIME_CHANGED")
        instructions = ""
        if self.skills:
            self.skills.verify()
            if role.startswith("reviewer-"):
                instructions = self.skills.read("specification-router")
            elif role == "clarifier":
                instructions = self.skills.read("grill-me") + "\n" + self.skills.read("grilling")
            elif role in ("impact-code", "impact-requirements", "assessor"):
                prereq = self.skills.check_role(role)
                if not prereq.ready:
                    raise ValueError(prereq.code)
                instructions = prereq.instruction_text
        schema = {
            "collector": CollectionResult,
            "context-verifier": ContextVerdict,
            "reviewer-a": ReviewResult,
            "reviewer-b": ReviewResult,
            "impact-code": ImpactReport,
            "impact-requirements": ImpactReport,
            "assessor": Assessment,
        }
        output_schema = (
            schema[role].model_json_schema()
            if role in schema
            else {
                "type": "object",
                "properties": {"questions": {"type": "array", "items": HumanQuestion.model_json_schema()}},
                "required": ["questions"],
                "additionalProperties": False,
            }
        )
        read_schema = {
            "type": "object",
            "properties": {
                "type": {"const": "read_requests"},
                "read_requests": {"type": "array", "items": SourceRef.model_json_schema()},
            },
            "required": ["type", "read_requests"],
            "additionalProperties": False,
        }
        if role in {"impact-code", "impact-requirements", "assessor", "clarifier"}:
            output_schema = {"anyOf": [output_schema, read_schema, ContextRequest.model_json_schema()]}
        prompt = (self.prompt_root / f"{role}.md").read_text(encoding="utf-8")
        envelope = {
            "instructions": prompt,
            "trusted_skills": instructions,
            "output_schema": output_schema,
            "data": {"snapshot": snapshot, "payload": payload},
        }
        if role.startswith("reviewer-") and self.skills:
            envelope["output_schema"] = {
                "type": "object",
                "properties": {
                    "route": {"enum": ["spec-kit", "openspec", "unresolved"]},
                    "route_reason": {"type": "string"},
                    "status": {
                        "enum": [
                            "ready_for_spec",
                            "needs_context",
                            "needs_clarification",
                            "blocked",
                            "awaiting_authorization",
                        ]
                    },
                    "findings": {"type": "array"},
                    "retrieve_refs": {"type": "array", "items": SourceRef.model_json_schema()},
                },
                "required": ["route", "route_reason", "status"],
            }
            envelope["routing_stage"] = (
                "Select a route with the supplied router first. Native assessment follows in this same session."
            )

        def render(value):
            encoded = json.dumps(value, ensure_ascii=True)
            if len(json.dumps({"text": encoded}, ensure_ascii=True).encode()) > self.max_prompt_bytes:
                raise ValueError("SOURCE_CONTEXT_LIMIT")
            return encoded

        initial = render(envelope)
        identity = session_id_for(operation_id)
        op = self.store.begin_operation(run.id, operation_id, role, identity)
        if op.state == "COMPLETED":
            if op.result.get("type") == "needs_context":
                raise ContextNeeded(op.result)
            return op.result
        await self.authenticate()
        session = await self.client.create_session(agent_preset=self.presets[role], session_id=identity)
        if session.session_id != identity or session.agent_preset != self.presets[role]:
            raise ValueError("READINESS_SESSION_BINDING_INVALID")
        if not op.is_new and self.store.observe_operation(operation_id + ":exchange:0") is None:
            await session.history()
            self.store.operation_state(operation_id, "UNCONFIRMED")
            raise ValueError("READINESS_AGENT_UNCONFIRMED")

        async def exchange(text, index):
            key = operation_id + f":exchange:{index}"
            sub = self.store.begin_operation(run.id, key, role + ":exchange", identity + f":{index}")
            if sub.state == "COMPLETED":
                return sub.result
            self.store.operation_state(operation_id, "ACKNOWLEDGED")
            try:
                output = await self.submit(session, text, key, sub)
            except BaseException:
                observed = self.store.observe_operation(key)
                self.store.operation_state(key, "UNCONFIRMED", observed.result)
                self.store.operation_state(operation_id, "UNCONFIRMED")
                raise
            self.store.finish_operation(key, output)
            return output

        output = await exchange(initial, 0)
        next_exchange = 1
        if role.startswith("reviewer-") and self.skills:
            route = output.get("route")
            if route == "unresolved" and output.get("status") in {
                "needs_context",
                "needs_clarification",
                "blocked",
                "awaiting_authorization",
            }:
                report = ReviewResult.model_validate(
                    output | {"reviewer_id": role[-1], "snapshot_digest": snapshot["digest"]}
                )
                self.store.finish_operation(operation_id, report.model_dump(mode="json"))
                return report.model_dump(mode="json")
            prereq = self.skills.check_route(route)
            if not prereq.ready:
                raise ValueError(prereq.code)
            native_schema = {
                "type": "object",
                "properties": {
                    "type": {"const": "native_steps"},
                    "steps": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 10,
                        "items": {
                            "type": "object",
                            "properties": {
                                "step_name": {"enum": list(prereq.required_receipt_kinds)},
                                "artifact_bindings": {"type": "object", "additionalProperties": {"type": "string"}},
                            },
                            "required": ["step_name", "artifact_bindings"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["type", "steps"],
                "additionalProperties": False,
            }
            output = await exchange(
                render(
                    {
                        "trusted_native_instructions": prereq.instruction_text,
                        "instruction": "Assess the selected route in this session. Request pinned native checks with type=native_steps, steps=[{step_name,artifact_bindings}]. The backend returns receipts. No shell commands or writes.",
                        "selected_route": route,
                        "output_schema": {"anyOf": [output_schema, native_schema]},
                    }
                ),
                next_exchange,
            )
            next_exchange += 1
            trusted_receipts = []
            for _ in range(4):
                if output.get("type") != "native_steps":
                    break
                if not self.native_runner:
                    raise ValueError("READINESS_NATIVE_DEPENDENCY_MISSING")
                steps = output.get("steps")
                if not isinstance(steps, list) or not 1 <= len(steps) <= 10:
                    raise ValueError("READINESS_AGENT_OUTPUT_INVALID")
                for step in steps:
                    if (
                        set(step) != {"step_name", "artifact_bindings"}
                        or step["step_name"] not in prereq.required_receipt_kinds
                    ):
                        raise ValueError("READINESS_NATIVE_STEP_INVALID")
                    try:
                        receipt = await asyncio.to_thread(
                            self.native_runner.execute,
                            step["step_name"],
                            snapshot["digest"],
                            step["artifact_bindings"],
                            operation_id=operation_id,
                        )
                    except NativeAuthorizationRequired:
                        self.store.operation_state(operation_id, "AWAITING_AUTHORIZATION")
                        raise
                    trusted_receipts.append(receipt.id)
                output = await exchange(
                    render(
                        {
                            "trusted_receipt_ids": trusted_receipts,
                            "selected_route": route,
                            "instruction": "Return the final ReviewResult bound to this selected route and snapshot.",
                        }
                    ),
                    next_exchange,
                )
                next_exchange += 1
            if output.get("route") != route:
                raise ValueError("READINESS_REVIEW_BINDING_INVALID")
        if role in {"impact-code", "impact-requirements", "assessor", "clarifier"}:
            for index in range(4):
                if output.get("type") != "read_requests":
                    break
                if self.source_broker is None:
                    raise ValueError("SOURCE_CONNECTION_UNAVAILABLE")
                if set(output) != {"type", "read_requests"}:
                    raise ValueError("READINESS_AGENT_OUTPUT_INVALID")
                evidence = await self.source_broker.read(
                    run.id, operation_id + f":read:{index}", output["read_requests"]
                )
                latest = self.store.load(run.id)
                if {e.id for e in latest.evidence} != {e["id"] for e in snapshot.get("evidence", ())}:
                    raise ValueError("READINESS_SNAPSHOT_CHANGED")
                output = await exchange(
                    render({"evidence": [e.model_dump(mode="json") for e in evidence]}), next_exchange
                )
                next_exchange += 1
            if output.get("type") == "read_requests":
                raise ValueError("READINESS_IMPACT_INCOMPLETE")
            if output.get("type") == "result":
                output = output["result"]
        if output.get("type") == "needs_context":
            self.store.finish_operation(operation_id, output)
            raise ContextNeeded(output)
        if role in schema:
            output = schema[role].model_validate(output).model_dump(mode="json")
        self.store.finish_operation(operation_id, output)
        return output
