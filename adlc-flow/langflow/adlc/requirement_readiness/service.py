from __future__ import annotations

import asyncio
from uuid import uuid4

from pydantic import ValidationError

from langflow.adlc.source_access import SourceError
from langflow.adlc.source_access.policy import authorize

from .assessment import AssessmentEngine, assessment_digest, bind_assessment
from .clarification import ClarificationEngine, publish_once
from .collection import CollectionEngine, SourceReadBroker, snapshot_for
from .impact import DualImpact, validate_impact_pair
from .models import ContextNeeded, HumanQuestion, HumanRound, PipelineConfig, ReadinessPackage, canonical_digest
from .review import DualReview, review_gate
from .skills import NativeAuthorizationRequired

ACTIVE = {
    "created",
    "collecting",
    "verifying_context",
    "context_ready",
    "reviewing",
    "needs_clarification",
    "requirements_ready",
    "impact_analyzing",
    "assessing",
}


class ReadinessService:
    def __init__(
        self,
        store,
        agents,
        gateway,
        skills,
        grant_resolver,
        policy_resolver,
        human_bridge=None,
        config=None,
        principal_resolver=None,
    ):
        self.store, self.agents, self.gateway, self.skills = store, agents, gateway, skills
        self.grants, self.principals = grant_resolver, principal_resolver
        self.config = config or PipelineConfig()
        self.broker = SourceReadBroker(gateway, store, grant_resolver)
        if hasattr(agents, "source_broker"):
            agents.source_broker = self.broker
        self.collection = CollectionEngine(agents, gateway, store, grant_resolver, self.broker)
        self.review, self.impact = DualReview(agents, skills), DualImpact(agents, skills)
        self.clarification = ClarificationEngine(agents, store, human_bridge)
        self.assessment = AssessmentEngine(agents, store, human_bridge, policy_resolver, skills, self.authorize_sources)
        self.queue = asyncio.Queue()
        self.queued = set()
        self.tasks = set()
        self.worker = None

    def authorize_sources(self, run, principal_id=None):
        scoped = run.model_copy(update={"principal_id": principal_id}) if principal_id else run
        grant = self.grants(scoped)
        for ref in (
            *run.request.source_refs,
            *(e.source for e in run.evidence),
            *(e.requested_source for e in run.evidence if e.requested_source),
        ):
            authorize(grant, ref)
        return grant

    def current_principal(self, principal):
        return self.principals(principal) if self.principals else principal

    def start(self, principal, request):
        principal = self.current_principal(principal)
        principal.require("submit", request.project_id)
        # Authorize before creating state, including requests that omit seed refs.
        from types import SimpleNamespace

        self.grants(SimpleNamespace(id="pending", principal_id=principal.id, request=request))
        digest = getattr(self.agents, "manifest_digest", getattr(self.skills, "digest", ""))
        run = self.store.create(principal.id, request, self.config, digest)
        self.authorize_sources(run, principal.id)
        self.schedule(run)
        return run

    def get(self, principal, run_id, purpose="read"):
        run = self.store.load(run_id)
        self.current_principal(principal).require(purpose, run.request.project_id)
        self.authorize_sources(run, principal.id)
        if run.status in {"ready", "waiting_option"} and run.policy_revision != self.assessment.policy(run).revision:
            run = self.store.update(
                run.id, run.revision, {"status": "assessing", "decision": None, "pending_selection": None}
            )
            self.schedule(run)
        return run

    def answer(self, principal, run_id, round_id, response, command_id, expected_revision):
        run = self.get(principal, run_id, "answer")
        if run.authorization_request and run.human_rounds and run.human_rounds[-1].kind == "authorization":
            payload = {"round_id": round_id, "response": response, "principal_id": principal.id}
            prior = self.store.command_result(run.id, command_id, payload)
            if prior:
                return prior
            row = run.human_rounds[-1]
            if (
                run.status != "awaiting_authorization"
                or row.id != round_id
                or row.snapshot_digest != run.snapshot.digest
                or set(response) != {"decision"}
                or response["decision"] not in {"allowed-once", "rejected"}
            ):
                raise ValueError("READINESS_ANSWER_BINDING_INVALID")
            row = row.model_copy(
                update={
                    "answered": True,
                    "confirmed": response["decision"] == "allowed-once",
                    "responder_id": principal.id,
                    "answers": {"decision": response["decision"]},
                }
            )
            status = "reviewing" if row.confirmed else "blocked"
            receipt = {
                "decision": response["decision"],
                "request": run.authorization_request,
                "responder_id": principal.id,
            }
            result = self.store.command(
                run.id,
                command_id,
                payload,
                expected_revision,
                {
                    "status": status,
                    "human_rounds": (*run.human_rounds[:-1], row),
                    "error_code": None if row.confirmed else "READINESS_AUTHORIZATION_REJECTED",
                },
                operation_result=(run.authorization_request["authorization_id"], receipt),
            )
            self.schedule(result)
            return result
        result = self.clarification.apply_answer(run, round_id, response, command_id, expected_revision, principal.id)
        self.schedule(result)
        return result

    def select(self, principal, run_id, digest, option_id, command_id, expected_revision):
        run = self.get(principal, run_id, "select")
        try:
            result = self.assessment.select(run, principal.id, digest, option_id, command_id, expected_revision)
        finally:
            self.schedule(self.store.load(run_id))
        return result

    def handoff(self, principal, run_id):
        run = self.get(principal, run_id)
        if run.status != "ready" or not run.decision or not run.snapshot or not run.assessment:
            raise ValueError("READINESS_HANDOFF_UNAVAILABLE")
        snapshot = run.snapshot.model_dump(mode="json") | {"run_id": run.id}
        if review_gate(snapshot, run.reviews, self.skills) != run.readiness_kind:
            raise ValueError("READINESS_HANDOFF_UNAVAILABLE")
        validate_impact_pair(snapshot, run.impacts)
        bind_assessment(snapshot, run.impacts, run.assessment.model_dump(mode="json"))
        decision = run.decision
        if (
            decision.snapshot_digest != run.snapshot.digest
            or decision.assessment_digest != assessment_digest(run.assessment)
            or decision.policy_revision != self.assessment.policy(run).revision
            or decision.selected_option_id not in {o.id for o in run.assessment.options}
        ):
            raise ValueError("READINESS_HANDOFF_UNAVAILABLE")
        identity = canonical_digest(
            {
                "run": run.id,
                "snapshot": run.snapshot.digest,
                "assessment": assessment_digest(run.assessment),
                "decision": decision.model_dump(mode="json"),
            }
        )
        return ReadinessPackage(
            handoff_id=identity,
            readiness_kind=run.readiness_kind,
            snapshot=run.snapshot,
            route=run.reviews[0].route,
            reviews=run.reviews,
            confirmed_answers=run.human_rounds,
            native_artifacts=tuple(sorted({a for r in run.reviews for a in r.artifacts})),
            impacts=run.impacts,
            assessment=run.assessment,
            decision=decision,
        )

    async def advance(self, run_id):
        owner = str(uuid4())
        if not self.store.lease(run_id, owner):
            return self.store.load(run_id)
        fence = self.store.fence.set((run_id, owner))
        current_task = asyncio.current_task()
        lease_lost = False

        async def renew():
            nonlocal lease_lost
            while True:
                await asyncio.sleep(30)
                try:
                    retained = self.store.lease(run_id, owner)
                except Exception:
                    retained = False
                if not retained:
                    lease_lost = True
                    current_task.cancel()
                    return

        renewal = asyncio.create_task(renew())
        self.tasks.add(renewal)
        try:
            run = self.store.load(run_id)
            if run.status not in ACTIVE:
                return run
            grant = self.authorize_sources(run)
            if run.status in {"created", "collecting", "verifying_context"}:
                return await self.collection.advance(run, grant)
            if run.status == "needs_clarification":
                return await self.clarification.advance(run)
            if run.status in {"context_ready", "reviewing"}:
                if run.status == "context_ready":
                    run = self.store.update(run.id, run.revision, {"status": "reviewing"})
                snapshot = run.snapshot.model_dump(mode="json") | {"run_id": run.id}
                reports = await self.review.assess(snapshot)
                gate = review_gate(snapshot, reports, self.skills)
                changes = {"reviews": reports, "status": gate}
                if gate in {"ready_for_spec", "spec_ready"}:
                    changes.update(status="requirements_ready", readiness_kind=gate)
                elif gate == "needs_context":
                    refs = tuple(ref for report in reports for ref in report.retrieve_refs)
                    changes.update(
                        missing_refs=refs,
                        status="created"
                        if refs and run.round_count < run.config.max_context_rounds
                        else "needs_context",
                    )
                return self.store.update(run.id, run.revision, changes)
            if run.status in {"requirements_ready", "impact_analyzing"}:
                if run.status == "requirements_ready":
                    run = self.store.update(run.id, run.revision, {"status": "impact_analyzing"})
                snapshot = run.snapshot.model_dump(mode="json") | {"run_id": run.id}
                if review_gate(snapshot, run.reviews, self.skills) != run.readiness_kind:
                    raise ValueError("READINESS_REVIEW_BINDING_INVALID")
                reports = await self.impact.analyze(snapshot, [r.model_dump(mode="json") for r in run.reviews])
                # Analysts may have persisted new evidence while reasoning.
                latest = self.store.load(run.id)
                if any(r.status != "complete" for r in reports):
                    refs = tuple(ref for r in reports for ref in r.retrieve_refs)
                    return self.store.update(
                        run.id,
                        latest.revision,
                        {
                            "impacts": reports,
                            "missing_refs": refs,
                            "status": "created"
                            if refs and latest.round_count < latest.config.max_context_rounds
                            else "needs_context",
                            "error_code": "READINESS_IMPACT_INCOMPLETE",
                        },
                    )
                return self.store.update(run.id, latest.revision, {"impacts": reports, "status": "assessing"})
            if run.status == "assessing":
                return await self.assessment.advance(run)
            return run
        except asyncio.CancelledError:
            if lease_lost:
                return self.store.load(run_id)
            raise
        except (ValueError, SourceError) as exc:
            run = self.store.load(run_id)
            code = exc.code if isinstance(exc, SourceError) else str(exc)
            if code in {"READINESS_REVISION_CONFLICT", "READINESS_LEASE_LOST"}:
                return run
            if isinstance(exc, ContextNeeded):
                return self.store.update(
                    run.id,
                    run.revision,
                    {
                        "missing_refs": exc.request.missing_refs,
                        "status": "created"
                        if exc.request.missing_refs and run.round_count < run.config.max_context_rounds
                        else "needs_context",
                        "error_code": "READINESS_CONTEXT_NEEDED",
                        "reviews": (),
                        "impacts": (),
                        "assessment": None,
                        "decision": None,
                        "pending_selection": None,
                        "readiness_kind": None,
                    },
                )
            if isinstance(exc, NativeAuthorizationRequired):
                request = exc.request
                identity = request["authorization_id"]
                self.store.begin_operation(run.id, identity, "native-authorization", identity)
                row = HumanRound(
                    id=identity,
                    snapshot_digest=run.snapshot.digest,
                    kind="authorization",
                    questions=(
                        HumanQuestion(
                            id=identity,
                            title="Authorize native prerequisite",
                            body=f"Authorize only {request['step_name']} on the named snapshot and artifacts: {request['artifact_bindings']}",
                            recommendation="Approve only if this native prerequisite is intended.",
                        ),
                    ),
                )
                rounds = (
                    run.human_rounds
                    if run.human_rounds and run.human_rounds[-1].id == identity
                    else (*run.human_rounds, row)
                )
                run = self.store.update(
                    run.id,
                    run.revision,
                    {
                        "status": "awaiting_authorization",
                        "authorization_request": request,
                        "human_rounds": rounds,
                        "error_code": code,
                    },
                )
                await self.publish_authorization(run)
                return self.store.load(run.id)
            if isinstance(exc, ValidationError):
                code = "READINESS_AGENT_OUTPUT_INVALID"
            if code == "READINESS_SNAPSHOT_CHANGED":
                return self.store.update(
                    run.id,
                    run.revision,
                    {
                        "snapshot": snapshot_for(run),
                        "reviews": (),
                        "impacts": (),
                        "assessment": None,
                        "decision": None,
                        "pending_selection": None,
                        "readiness_kind": None,
                        "status": "created" if run.round_count < run.config.max_context_rounds else "needs_context",
                        "error_code": None,
                    },
                )
            status = "awaiting_authorization" if code == "READINESS_NATIVE_AUTHORIZATION_REQUIRED" else "blocked"
            if code == "READINESS_AGENT_OUTPUT_INVALID":
                status = "failed"
            if code.startswith("SOURCE_") and code not in {"SOURCE_SCOPE_DENIED", "SOURCE_CONFIGURATION_INVALID"}:
                status = "needs_context"
            return self.store.update(
                run.id,
                run.revision,
                {
                    "status": status,
                    "error_code": code if code.startswith(("READINESS_", "SOURCE_")) else "READINESS_RUNTIME_FAILED",
                },
            )
        except Exception:
            run = self.store.load(run_id)
            return self.store.update(
                run.id, run.revision, {"status": "blocked", "error_code": "READINESS_RUNTIME_FAILED"}
            )
        finally:
            renewal.cancel()
            await asyncio.gather(renewal, return_exceptions=True)
            self.tasks.discard(renewal)
            self.store.release(run_id, owner)
            self.store.fence.reset(fence)

    def schedule(self, run):
        if self.worker is not None and run.status in ACTIVE and run.id not in self.queued:
            self.queued.add(run.id)
            self.queue.put_nowait(run.id)

    async def start_worker(self):
        if self.worker is not None:
            return

        async def work():
            while True:
                identity = await self.queue.get()
                self.queued.discard(identity)
                try:
                    before = self.store.load(identity)
                    result = await self.advance(identity)
                    if result.status in ACTIVE and result.revision == before.revision:
                        await asyncio.sleep(1)
                    self.schedule(result)
                finally:
                    self.queue.task_done()

        self.worker = asyncio.create_task(work())

        async def observe_outbox():
            while True:
                await asyncio.sleep(10)
                try:
                    await self.reconcile_waiting()
                except Exception:
                    # Transient store/channel loss must not stop later observation.
                    continue

        self.tasks.add(asyncio.create_task(observe_outbox()))
        for run in self.store.all_runs():
            self.schedule(run)
        await self.reconcile_waiting()

    async def reconcile_waiting(self):
        for run in self.store.all_runs():
            if run.status not in {"waiting_human", "waiting_option", "awaiting_authorization"}:
                continue
            try:
                self.authorize_sources(run)
                if run.status == "waiting_option" and run.policy_revision != self.assessment.policy(run).revision:
                    revised = self.store.update(
                        run.id, run.revision, {"status": "assessing", "pending_selection": None, "decision": None}
                    )
                    self.schedule(revised)
                elif run.status == "waiting_human" and self.clarification.bridge:
                    await self.clarification.advance(run)
                elif run.status == "waiting_option":
                    await self.assessment.publish_pending(run)
                elif run.status == "awaiting_authorization":
                    await self.publish_authorization(run)
            except (ValueError, SourceError) as exc:
                if str(exc) == "READINESS_REVISION_CONFLICT":
                    continue
                try:
                    self.store.update(
                        run.id,
                        run.revision,
                        {
                            "status": "blocked",
                            "error_code": exc.code
                            if isinstance(exc, SourceError)
                            else "READINESS_AUTHORIZATION_OR_POLICY_UNAVAILABLE",
                        },
                    )
                except ValueError:
                    # An authenticated decision may have won the checkpoint race.
                    continue

    async def publish_authorization(self, run):
        bridge = self.clarification.bridge
        request = run.authorization_request
        if bridge is None or request is None or not hasattr(bridge, "publish_authorization"):
            return
        identity = request["authorization_id"]
        await publish_once(
            self.store,
            run,
            identity + ":publication",
            "authorization-publication",
            lambda: bridge.publish_authorization(run.id, identity, request, run.request.project_id),
            lambda: bridge.observe_authorization(identity),
        )

    async def close(self):
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
            self.worker = None
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.gateway.aclose()
