from .clarification import publish_once
from .impact import report_digests, validate_impact_pair
from .models import Assessment, HumanGatePolicy, OptionDecision, canonical_digest
from .review import review_gate


def effective_mode(policy, assessment, reports):
    if len(reports) != 2 or any(r.status != "complete" or r.blocking_findings for r in reports):
        raise ValueError("READINESS_IMPACT_BLOCKED")
    if policy.mode == "required":
        return "required"
    if (
        assessment.material_disagreement
        or assessment.questions
        or any(r.material_uncertainties or r.requires_authorization for r in reports)
    ):
        return "required"
    return "auto"


def bind_assessment(snapshot, reports, output):
    validate_impact_pair(snapshot, reports)
    assessment = Assessment.model_validate(output)
    if assessment.snapshot_digest != snapshot["digest"] or assessment.report_digests != report_digests(reports):
        raise ValueError("READINESS_ASSESSMENT_BINDING_INVALID")
    return assessment


def assessment_digest(assessment):
    return canonical_digest(assessment.model_dump(mode="json"))


class AssessmentEngine:
    def __init__(self, agents, store, human_bridge, policy_resolver, skill_catalog=None, authorize=None):
        self.agents, self.store, self.bridge, self.policy_resolver = agents, store, human_bridge, policy_resolver
        self.skills, self.authorize = skill_catalog, authorize

    def policy(self, run):
        row = self.policy_resolver(run.request.project_id)
        return HumanGatePolicy.model_validate(row) if row is not None else HumanGatePolicy()

    async def advance(self, run):
        run = self.store.load(run.id)
        if self.authorize:
            self.authorize(run)
        snapshot = run.snapshot.model_dump(mode="json") | {"run_id": run.id}
        if (
            run.readiness_kind not in {"ready_for_spec", "spec_ready"}
            or self.skills
            and review_gate(snapshot, run.reviews, self.skills) != run.readiness_kind
        ):
            raise ValueError("READINESS_REVIEW_BINDING_INVALID")
        validate_impact_pair(snapshot, run.impacts)
        if self.skills and not self.skills.check_role("assessor").ready:
            raise ValueError("READINESS_NATIVE_DEPENDENCY_MISSING")
        policy = self.policy(run)
        pair_digest = canonical_digest(report_digests(run.impacts))
        assessment = run.assessment
        if assessment is None:
            output = await self.agents.ask(
                "assessor",
                snapshot,
                {
                    "reviews": [r.model_dump(mode="json") for r in run.reviews],
                    "impacts": [r.model_dump(mode="json") for r in run.impacts],
                    "report_digests": report_digests(run.impacts),
                    "host_policy": policy.model_dump(mode="json"),
                },
                f"{run.id}:{snapshot['digest']}:{pair_digest}:assessor",
            )
            assessment = bind_assessment(snapshot, run.impacts, output)
        # Model latency must not preserve a revoked auto policy or source binding.
        policy = self.policy(run)
        if self.authorize:
            self.authorize(run)
        mode = effective_mode(policy, assessment, run.impacts)
        digest = assessment_digest(assessment)
        changes = {"assessment": assessment, "policy_revision": policy.revision, "error_code": None}
        if mode == "auto":
            decision = OptionDecision(
                mode="auto",
                snapshot_digest=run.snapshot.digest,
                assessment_digest=digest,
                policy_revision=policy.revision,
                selected_option_id=assessment.recommended_option_id,
                selected_by="agent",
                reason=assessment.recommendation_reason,
            )
            return self.store.update(
                run.id, run.revision, changes | {"status": "ready", "decision": decision, "pending_selection": None}
            )
        pending = {
            "assessment_digest": digest,
            "policy_revision": policy.revision,
            "mode": mode,
            "publication_id": f"{run.id}:{digest}:{policy.revision}:selection-publication",
            "options": [o.model_dump(mode="json") for o in assessment.options],
            "recommendation": assessment.recommended_option_id,
            "uncertainties": [u for r in run.impacts for u in r.material_uncertainties],
            "risks": [risk for r in run.impacts for risk in r.blocking_findings] + list(assessment.risks),
        }
        if self.bridge is None:
            changes["error_code"] = "READINESS_HUMAN_CHANNEL_UNAVAILABLE"
        run = self.store.update(
            run.id, run.revision, changes | {"status": "waiting_option", "pending_selection": pending}
        )
        return await self.publish_pending(run)

    async def publish_pending(self, run):
        if self.bridge is None:
            return run
        pending = run.pending_selection
        if not pending:
            return run
        key = pending["publication_id"]
        await publish_once(
            self.store,
            run,
            key,
            "selection-publication",
            lambda: self.bridge.publish_selection(
                run.id, pending["assessment_digest"], pending["options"], pending, run.request.project_id
            ),
            lambda: self.bridge.observe_selection(key),
        )
        return self.store.load(run.id)

    def select(self, run, principal_id, assessment_digest_value, option_id, command_id, expected_revision):
        payload = {"principal_id": principal_id, "assessment_digest": assessment_digest_value, "option_id": option_id}
        prior = self.store.command_result(run.id, command_id, payload)
        if prior:
            return prior
        run = self.store.load(run.id)
        if self.authorize:
            self.authorize(run)
        if run.status != "waiting_option" or run.assessment is None or run.snapshot is None:
            raise ValueError("READINESS_SELECTION_INVALID")
        snapshot = run.snapshot.model_dump(mode="json") | {"run_id": run.id}
        bind_assessment(snapshot, run.impacts, run.assessment.model_dump(mode="json"))
        if assessment_digest(run.assessment) != assessment_digest_value:
            raise ValueError("READINESS_SELECTION_STALE")
        if option_id not in {o.id for o in run.assessment.options}:
            raise ValueError("READINESS_SELECTION_INVALID")
        policy = self.policy(run)
        if policy.revision != run.policy_revision:
            self.store.update(run.id, run.revision, {"status": "assessing", "pending_selection": None})
            raise ValueError("READINESS_POLICY_CHANGED")
        effective_mode(policy, run.assessment, run.impacts)
        decision = OptionDecision(
            mode="required",
            snapshot_digest=run.snapshot.digest,
            assessment_digest=assessment_digest_value,
            policy_revision=policy.revision,
            selected_option_id=option_id,
            selected_by=principal_id,
            reason="Authenticated human option selection",
        )
        return self.store.command(
            run.id,
            command_id,
            payload,
            expected_revision,
            {"status": "ready", "decision": decision, "pending_selection": None, "error_code": None},
        )
