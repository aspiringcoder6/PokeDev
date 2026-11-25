from __future__ import annotations

import asyncio
import json

from pydantic import ValidationError

from langflow.adlc.source_access import SourceError, SourceRef, completed_evidence_ids
from langflow.adlc.source_access.models import Evidence, is_git_sha
from .models import CollectionResult, ContextSnapshot, ContextVerdict, canonical_digest


def remaining_rounds(limit, completed):
    return max(0, limit-completed)


def context_passes(verdict, evidence):
    known = {item.id for item in evidence}
    return (verdict.sufficient and not verdict.missing_refs and set(verdict.evidence_ids) <= known
            and completed_evidence_ids(evidence) == known and bool(verdict.evidence_ids or not evidence))


def ref_key(ref):
    return json.dumps(ref.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def snapshot_for(run):
    request = run.request
    if run.confirmed_requirement:
        request = request.model_copy(update={"requirement": run.confirmed_requirement})
    return ContextSnapshot.from_input(request, run.evidence)


class SourceReadBroker:
    def __init__(self, gateway, store, grant_resolver):
        self.gateway, self.store, self.grant_resolver = gateway, store, grant_resolver
        self._locks = {}

    async def read(self, run_id, operation_id, refs):
        # Shared broker serializes the analysts' read reservations, not their reasoning.
        async with self._locks.setdefault(run_id, asyncio.Lock()):
            run = self.store.load(run_id)
            scope = self.grant_resolver(run)
            refs = tuple(SourceRef.model_validate(ref) for ref in refs)
            requested_digest = canonical_digest([r.model_dump(mode="json") for r in refs])
            prior = run.read_operations.get(operation_id)
            if prior and prior["request_digest"] != requested_digest:
                raise ValueError("READINESS_OPERATION_BINDING_INVALID")
            if prior and prior.get("state") == "completed":
                # Recheck permissions even when returning a cached read.
                from langflow.adlc.source_access.policy import authorize
                for ref in refs:
                    authorize(scope, ref)
                return tuple(Evidence.model_validate(e) for e in prior["evidence"])
            if prior and prior.get("error"):
                raise SourceError(prior["error"])
            if prior is None:
                if run.tool_calls + len(refs) > min(run.config.max_tool_calls, scope.max_reads):
                    raise ValueError("SOURCE_READ_LIMIT")
                operations = dict(run.read_operations)
                operations[operation_id] = {"request_digest": requested_digest, "state":"reserved"}
                run = self.store.update(run.id, run.revision, {"tool_calls":run.tool_calls+len(refs), "read_operations":operations})
            pinned = []
            try:
                for ref in refs:
                    if ref.kind == "github_file" and not is_git_sha(ref.revision):
                        key = canonical_digest([ref.connection_id,ref.resource_id,ref.revision or "HEAD"])
                        sha = run.pinned_revisions.get(key)
                        if sha:
                            ref = ref.model_copy(update={"revision":sha})
                        else:
                            resolved = await self.gateway.resolve_revision(self.grant_resolver(run),ref)
                            versions = dict(run.pinned_revisions) | {key:resolved.revision}
                            run = self.store.update(run.id,run.revision,{"pinned_revisions":versions})
                            ref = resolved
                    pinned.append(ref)
                evidence = tuple(await self.gateway.read(self.grant_resolver(run),pinned))
                size = sum(len(e.body.encode()) for e in evidence)
                if run.context_bytes+size > min(run.config.max_context_bytes, scope.max_bytes):
                    raise SourceError("SOURCE_CONTEXT_LIMIT")
            except (SourceError, ValueError) as exc:
                code = exc.code if isinstance(exc, SourceError) else "SOURCE_READ_FAILED"
                operations = dict(run.read_operations)
                operations[operation_id] = operations[operation_id] | {"error":code,"state":"failed"}
                self.store.update(run.id,run.revision,{"read_operations":operations,"error_code":code})
                raise
            merged = {e.id:e for e in run.evidence}
            merged.update({e.id:e for e in evidence})
            operations = dict(run.read_operations)
            operations[operation_id] = operations[operation_id] | {
                "state":"completed", "evidence":[e.model_dump(mode="json") for e in evidence],
                "requested_refs":[r.model_dump(mode="json") for r in refs]}
            self.store.update(run.id,run.revision,{"evidence":tuple(merged.values()),
                "context_bytes":run.context_bytes+size,"read_operations":operations})
            return evidence


class CollectionEngine:
    def __init__(self, agents, gateway, store, grant_resolver=None, broker=None):
        self.agents, self.gateway, self.store = agents,gateway,store
        self.grant_resolver = grant_resolver
        self.broker = broker

    async def advance(self, run, grant):
        resolver = self.grant_resolver or (lambda _: grant)
        broker = self.broker or SourceReadBroker(self.gateway,self.store,resolver)
        while True:
            run = self.store.load(run.id)
            try:
                if run.status not in {"collecting","verifying_context"}:
                    if not remaining_rounds(run.config.max_context_rounds,run.round_count):
                        return self.store.update(run.id,run.revision,{"status":"needs_context"})
                    run = self.store.update(run.id,run.revision,{"round_count":run.round_count+1,
                        "status":"collecting","round_snapshot":snapshot_for(run),"error_code":None})
                if run.status == "collecting":
                    scope = resolver(run)
                    snapshot = run.round_snapshot.model_dump(mode="json") | {"run_id":run.id}
                    payload = {"allowed_sources":{key:sorted(values) for key,values in scope.resources.items()},
                        "seed_refs":[r.model_dump(mode="json") for r in run.request.source_refs],
                        "missing_refs":[r.model_dump(mode="json") for r in run.missing_refs]}
                    output = await self.agents.ask("collector",snapshot,payload,f"{run.id}:collect:{run.round_count}:{snapshot['digest']}")
                    result = CollectionResult.model_validate(output)
                    refs = {ref_key(r):r for r in (*run.request.source_refs,*run.missing_refs,*result.read_requests)}
                    covered = {ref_key(e.source) for e in run.evidence if e.id in completed_evidence_ids(run.evidence)}
                    covered.update(ref_key(e.requested_source) for e in run.evidence if e.requested_source and e.id in completed_evidence_ids(run.evidence))
                    # Original branch references are covered by a successful pinned read operation.
                    for op in run.read_operations.values():
                        if op.get("state")=="completed" and all(e["id"] in completed_evidence_ids(run.evidence) for e in op["evidence"]):
                            covered.update(ref_key(SourceRef.model_validate(r)) for r in op.get("requested_refs",()))
                    refs = [r for key,r in refs.items() if key not in covered]
                    if refs:
                        try:
                            await broker.read(run.id,f"{run.id}:round:{run.round_count}:reads",refs)
                        except (SourceError, ValueError) as exc:
                            latest = self.store.load(run.id)
                            return self.store.update(run.id,latest.revision,{"status":"needs_context", "missing_refs":refs,
                                "error_code":exc.code if isinstance(exc,SourceError) else str(exc)})
                    run = self.store.load(run.id)
                    run = self.store.update(run.id,run.revision,{"status":"verifying_context","snapshot":snapshot_for(run)})
                snapshot = run.snapshot.model_dump(mode="json") | {"run_id":run.id}
                verdict = ContextVerdict.model_validate(await self.agents.ask("context-verifier",snapshot,{},
                    f"{run.id}:verify:{run.round_count}:{snapshot['digest']}"))
                if context_passes(verdict,run.evidence) and not run.error_code:
                    return self.store.update(run.id,run.revision,{"status":"context_ready","missing_refs":(),"verdict":verdict})
                run = self.store.update(run.id,run.revision,{"status":"needs_context","missing_refs":verdict.missing_refs,"verdict":verdict})
            except ValidationError:
                latest = self.store.load(run.id)
                return self.store.update(run.id,latest.revision,{"status":"failed","error_code":"READINESS_AGENT_OUTPUT_INVALID"})
