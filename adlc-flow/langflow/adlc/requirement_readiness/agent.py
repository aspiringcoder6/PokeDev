from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from .models import CollectionResult, ContextVerdict, ReviewResult, ImpactReport, Assessment, HumanQuestion, canonical_digest

ROLES = ("collector", "context-verifier", "reviewer-a", "reviewer-b", "clarifier", "impact-code", "impact-requirements", "assessor")


class AgentRunner(Protocol):
    async def ask(self, role, snapshot, payload, operation_id) -> dict: ...


def session_id_for(operation_id):
    return str(uuid5(NAMESPACE_URL, "pokedev:requirement-readiness:"+operation_id))


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
        output = json.loads(result["final_text"], object_pairs_hook=no_duplicates,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(output, dict):
            raise ValueError()
        return output
    except (KeyError, TypeError, ValueError):
        raise ValueError("READINESS_AGENT_OUTPUT_INVALID") from None


class DshAgentRunner:
    def __init__(self, client, store, prompt_root, skill_catalog, preset_by_role, source_broker=None,
                 max_prompt_bytes=1_400_000, native_runner=None):
        self.client, self.store = client, store
        self.prompt_root, self.skills = Path(prompt_root), skill_catalog
        self.presets, self.source_broker = dict(preset_by_role), source_broker
        self.max_prompt_bytes, self.native_runner = min(max_prompt_bytes, 1_400_000), native_runner

    @property
    def manifest_digest(self):
        return canonical_digest({"presets": self.presets, "skills": self.skills.digest if self.skills else None,
                                 "prompts": {r: (self.prompt_root/f"{r}.md").read_text(encoding="utf-8") for r in ROLES}})

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
                instructions = self.skills.read("grill-me")+"\n"+self.skills.read("grilling")
            elif role in ("impact-code", "impact-requirements", "assessor"):
                prereq = self.skills.check_role(role)
                if not prereq.ready:
                    raise ValueError(prereq.code)
                instructions = prereq.instruction_text
        schema = {"collector": CollectionResult, "context-verifier": ContextVerdict,
                  "reviewer-a": ReviewResult, "reviewer-b": ReviewResult,
                  "impact-code": ImpactReport, "impact-requirements": ImpactReport, "assessor": Assessment}
        output_schema = schema[role].model_json_schema() if role in schema else {
            "type":"object", "properties":{"questions":{"type":"array","items":HumanQuestion.model_json_schema()}},
            "required":["questions"], "additionalProperties":False}
        prompt = (self.prompt_root/f"{role}.md").read_text(encoding="utf-8")
        envelope = {"instructions":prompt, "trusted_skills":instructions, "output_schema":output_schema,
                    "data":{"snapshot":snapshot,"payload":payload}}
        def render(value):
            encoded = json.dumps(value, ensure_ascii=True)
            if len(json.dumps({"text":encoded}, ensure_ascii=True).encode()) > self.max_prompt_bytes:
                raise ValueError("SOURCE_CONTEXT_LIMIT")
            return encoded
        initial = render(envelope)
        identity = session_id_for(operation_id)
        op = self.store.begin_operation(run.id, operation_id, role, identity)
        if op.state == "COMPLETED":
            return op.result
        session = await self.client.create_session(agent_preset=self.presets[role], session_id=identity)
        if not op.is_new:
            # An interrupted exchange cannot be associated with a terminal result by
            # merely taking the newest assistant message; inspect then stop conservatively.
            await session.history()
            self.store.operation_state(operation_id, "UNCONFIRMED")
            raise ValueError("READINESS_AGENT_UNCONFIRMED")
        async def exchange(text, index):
            key = operation_id+f":exchange:{index}"
            sub = self.store.begin_operation(run.id, key, role+":exchange", identity+f":{index}")
            if sub.state == "COMPLETED":
                return sub.result
            if not sub.is_new:
                raise ValueError("READINESS_AGENT_UNCONFIRMED")
            self.store.operation_state(operation_id,"ACKNOWLEDGED")
            try:
                output = parse_agent_output(await session.run(text))
            except BaseException:
                self.store.operation_state(key,"UNCONFIRMED")
                self.store.operation_state(operation_id,"UNCONFIRMED")
                raise
            self.store.finish_operation(key,output)
            return output
        output = await exchange(initial,0)
        if role.startswith("reviewer-") and self.skills:
            route = output.get("route")
            prereq = self.skills.check_route(route)
            if not prereq.ready:
                raise ValueError(prereq.code)
            output = await exchange(render({"trusted_native_instructions":prereq.instruction_text,
                "instruction":"Assess in this same session. Read only. Native receipts must come from backend.",
                "output_schema":output_schema}),1)
        if role.startswith("impact-"):
            for index in range(4):
                if output.get("type") != "read_requests":
                    break
                if self.source_broker is None:
                    raise ValueError("SOURCE_CONNECTION_UNAVAILABLE")
                evidence = await self.source_broker.read(run.id, operation_id+f":read:{index}", output["read_requests"])
                latest = self.store.load(run.id)
                if {e.id for e in latest.evidence} != {e["id"] for e in snapshot.get("evidence",())}:
                    raise ValueError("READINESS_SNAPSHOT_CHANGED")
                output = await exchange(render({"evidence":[e.model_dump(mode="json") for e in evidence]}),index+1)
            if output.get("type") == "read_requests":
                raise ValueError("READINESS_IMPACT_INCOMPLETE")
            if output.get("type") == "result":
                output = output["result"]
        self.store.finish_operation(operation_id,output)
        return output
