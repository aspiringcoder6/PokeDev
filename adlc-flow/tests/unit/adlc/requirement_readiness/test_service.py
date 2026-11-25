import asyncio

import pytest

from langflow.adlc.requirement_readiness.models import NormalizedInput


async def drive(service, run):
    for _ in range(12):
        if run.status in {"ready", "waiting_option", "waiting_human", "blocked", "failed", "needs_context"}:
            return run
        run = await service.advance(run.id)
    raise AssertionError("workflow did not stop")


def test_whole_three_stage_auto_and_stable_handoff(runtime):
    async def scenario():
        s, p = runtime.service, runtime.principal
        run = s.start(p, NormalizedInput(request_id="req", project_id="p", requirement="Assess inputs"))
        with pytest.raises(ValueError, match="READINESS_HANDOFF_UNAVAILABLE"):
            s.handoff(p, run.id)
        run = await drive(s, run)
        assert run.status == "ready"
        package = s.handoff(p, run.id)
        assert package.handoff_id == s.handoff(p, run.id).handoff_id
        assert package.decision.selected_option_id == "a"
        roles = [c[0] for c in runtime.agents.calls]
        assert roles.index("assessor") > roles.index("impact-requirements")
        assert len(package.reviews) == len(package.impacts) == 2
        runtime.config["revoked"] = True
        with pytest.raises(ValueError, match="SOURCE_SCOPE_DENIED"):
            s.handoff(p, run.id)

    asyncio.run(scenario())


def test_required_selection_is_durable_and_idempotent(runtime):
    async def scenario():
        runtime.config["mode"] = "required"
        s, p = runtime.service, runtime.principal
        run = await drive(s, s.start(p, NormalizedInput(request_id="req", project_id="p", requirement="Assess")))
        assert run.status == "waiting_option"
        with pytest.raises(ValueError):
            s.handoff(p, run.id)
        digest = run.pending_selection["assessment_digest"]
        chosen = s.select(p, run.id, digest, "b", "cmd", run.revision)
        assert chosen.decision.selected_option_id == "b"
        assert s.select(p, run.id, digest, "b", "cmd", run.revision).decision == chosen.decision
        with pytest.raises(ValueError, match="READINESS_IDEMPOTENCY_CONFLICT"):
            s.select(p, run.id, digest, "a", "cmd", run.revision)

    asyncio.run(scenario())


def test_interview_waits_for_actual_answers_and_final_confirmation(runtime):
    async def scenario():
        runtime.agents.clarify = True
        s, p = runtime.service, runtime.principal
        run = await drive(s, s.start(p, NormalizedInput(request_id="req", project_id="p", requirement="Assess")))
        assert run.status == "waiting_human"
        first_digest = run.snapshot.digest
        run = s.answer(
            p, run.id, run.human_rounds[-1].id, {"answers": {"q1": "small"}, "confirmed": False}, "answer", run.revision
        )
        run = await drive(s, run)
        assert run.human_rounds[-1].kind == "confirmation"
        assert run.snapshot.digest == first_digest
        run = s.answer(p, run.id, run.human_rounds[-1].id, {"answers": {}, "confirmed": True}, "confirm", run.revision)
        run = await drive(s, run)
        assert run.status == "ready"
        assert run.snapshot.digest != first_digest
        assert "Which scope?" in run.snapshot.request.requirement
        assert run.human_rounds[0].responder_id == "svc"
        assert [c[0] for c in runtime.agents.calls].count("reviewer-a") == 2

    asyncio.run(scenario())


def test_policy_change_during_assessor_cannot_auto_select(runtime):
    async def scenario():
        original = runtime.agents.ask

        async def ask(role, *args):
            result = await original(role, *args)
            if role == "assessor":
                runtime.config.update(mode="required", revision="v2")
            return result

        runtime.agents.ask = ask
        run = await drive(
            runtime.service,
            runtime.service.start(
                runtime.principal, NormalizedInput(request_id="r", project_id="p", requirement="Assess")
            ),
        )
        assert run.status == "waiting_option"
        assert run.policy_revision == "v2"

    asyncio.run(scenario())


def test_policy_revision_after_ready_reopens_bound_selection(runtime):
    async def scenario():
        s, p = runtime.service, runtime.principal
        run = await drive(s, s.start(p, NormalizedInput(request_id="r", project_id="p", requirement="Assess")))
        runtime.config.update(mode="required", revision="v2")
        with pytest.raises(ValueError):
            s.handoff(p, run.id)
        latest = runtime.store.load(run.id)
        assert latest.status == "assessing"
        latest = await drive(s, latest)
        assert latest.status == "waiting_option"
        assert len([c for c in runtime.agents.calls if c[0] == "assessor"]) == 1

    asyncio.run(scenario())


def test_concurrent_checkpoint_winner_is_not_overwritten(runtime):
    async def scenario():
        s = runtime.service
        run = s.start(runtime.principal, NormalizedInput(request_id="r", project_id="p", requirement="Assess"))
        run = await s.advance(run.id)
        assert run.status == "context_ready"
        original = s.review.assess

        async def assess(snapshot):
            reports = await original(snapshot)
            latest = runtime.store.load(run.id)
            runtime.store.update(run.id, latest.revision, {"status": "cancelled"})
            return reports

        s.review.assess = assess
        result = await s.advance(run.id)
        assert result.status == "cancelled"

    asyncio.run(scenario())


def test_native_authorization_is_a_named_separate_transaction(runtime):
    from langflow.adlc.requirement_readiness.skills import NativeAuthorizationRequired

    async def scenario():
        s, p = runtime.service, runtime.principal
        run = await s.advance(s.start(p, NormalizedInput(request_id="r", project_id="p", requirement="Assess")).id)
        request = {
            "step_name": "native-check",
            "operation_id": "review-op",
            "snapshot_digest": run.snapshot.digest,
            "artifact_bindings": {"spec": "spec.md"},
            "command_digest": "command-v1",
            "authorization_id": "auth-id",
        }

        async def blocked(snapshot):
            raise NativeAuthorizationRequired(request)

        s.review.assess = blocked
        run = await s.advance(run.id)
        assert run.status == "awaiting_authorization"
        assert run.authorization_request == request
        assert run.human_rounds[-1].kind == "authorization"
        run = s.answer(p, run.id, run.human_rounds[-1].id, {"decision": "allowed-once"}, "approve", run.revision)
        assert run.status == "reviewing"
        assert runtime.store.observe_operation("auth-id").result["request"] == request

    asyncio.run(scenario())


def test_waiting_outbox_reconciles_without_model_calls(runtime):
    async def scenario():
        runtime.config["mode"] = "required"
        s, p = runtime.service, runtime.principal
        s.assessment.bridge = None
        run = await drive(s, s.start(p, NormalizedInput(request_id="r", project_id="p", requirement="Assess")))
        assert run.status == "waiting_option"
        count = len(runtime.agents.calls)
        published = []

        class RecoveredBridge:
            async def publish_selection(self, *args):
                published.append(args)
                return "delivered"

            async def observe_selection(self, *args):
                return None

        s.assessment.bridge = RecoveredBridge()
        await s.reconcile_waiting()
        await s.reconcile_waiting()
        assert len(published) == 1
        assert len(runtime.agents.calls) == count

    asyncio.run(scenario())


def test_incomplete_impact_preserves_both_full_reports(runtime):
    async def scenario():
        original = runtime.agents.ask

        async def ask(role, *args):
            output = await original(role, *args)
            if role == "impact-requirements":
                output["status"] = "incomplete"
                output["blocking_findings"] = ["Missing essential traceability"]
            return output

        runtime.agents.ask = ask
        run = await drive(
            runtime.service,
            runtime.service.start(
                runtime.principal, NormalizedInput(request_id="r", project_id="p", requirement="Assess")
            ),
        )
        assert run.status == "needs_context"
        assert len(run.impacts) == 2
        assert run.impacts[1].body.endswith("native full report")

    asyncio.run(scenario())


def test_recovered_outbox_does_not_publish_after_scope_revocation(runtime):
    async def scenario():
        runtime.config["mode"] = "required"
        s, p = runtime.service, runtime.principal
        s.assessment.bridge = None
        run = await drive(s, s.start(p, NormalizedInput(request_id="r", project_id="p", requirement="Assess")))
        runtime.config["revoked"] = True

        class Bridge:
            async def publish_selection(self, *args):
                raise AssertionError("revoked scope must not publish")

            async def observe_selection(self, *args):
                return None

        s.assessment.bridge = Bridge()
        await s.reconcile_waiting()
        assert runtime.store.load(run.id).status == "blocked"

    asyncio.run(scenario())


def test_uncertain_publication_observation_never_resends_or_kills_recovery(runtime):
    async def scenario():
        runtime.config["mode"] = "required"
        s, p = runtime.service, runtime.principal
        attempts = []

        class Bridge:
            async def publish_selection(self, *args):
                attempts.append("send")
                raise TimeoutError()

            async def observe_selection(self, *args):
                raise ConnectionError()

        s.assessment.bridge = Bridge()
        run = await drive(s, s.start(p, NormalizedInput(request_id="r", project_id="p", requirement="Assess")))
        await s.reconcile_waiting()
        assert attempts == ["send"]
        assert runtime.store.load(run.id).status == "waiting_option"

    asyncio.run(scenario())
