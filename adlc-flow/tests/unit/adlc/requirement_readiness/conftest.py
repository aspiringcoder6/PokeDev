from types import SimpleNamespace

import pytest

from langflow.adlc.requirement_readiness.models import HumanGatePolicy, PipelineConfig
from langflow.adlc.requirement_readiness.store import ReadinessStore
from langflow.adlc.source_access import SourceGateway, SourceGrant


class FakeCatalog:
    digest = "fixture"

    def check_route(self, route):
        return SimpleNamespace(ready=True)

    def check_role(self, role):
        return SimpleNamespace(ready=True)

    def validate_receipts(self, *args):
        return False


class FakeAgents:
    def __init__(self):
        self.calls = []
        self.clarify = False

    async def ask(self, role, snapshot, payload, operation_id):
        self.calls.append((role, snapshot, payload, operation_id))
        if role == "collector":
            return {"read_requests": [], "rationale": "no source required for new capability"}
        if role == "context-verifier":
            return {"sufficient": True}
        if role.startswith("reviewer-"):
            return {
                "reviewer_id": role[-1],
                "snapshot_digest": snapshot["digest"],
                "route": "openspec",
                "status": "needs_clarification"
                if self.clarify and "Confirmed human decisions" not in snapshot["request"]["requirement"]
                else "ready_for_spec",
                "route_reason": "known existing capability",
            }
        if role == "clarifier":
            return (
                {"questions": [{"id": "q1", "title": "Scope", "body": "Which scope?", "recommendation": "small"}]}
                if not payload["previous_rounds"]
                else {"questions": []}
            )
        if role.startswith("impact-"):
            return {
                "analyst": "code" if role == "impact-code" else "requirements",
                "snapshot_digest": snapshot["digest"],
                "status": "complete",
                "body": role + " native full report",
                "evidence_ids": [],
                "affected_items": [],
                "blocking_findings": [],
                "material_uncertainties": [],
                "requires_authorization": False,
            }
        assert role == "assessor"
        assert len(payload["impacts"]) == 2
        assert all(r["body"].endswith("native full report") for r in payload["impacts"])
        return {
            "snapshot_digest": snapshot["digest"],
            "report_digests": payload["report_digests"],
            "body": "Full assessment",
            "summary": "Two approaches",
            "affected_systems": [],
            "complexity": "small",
            "related_work": [],
            "concerns": [],
            "questions": [],
            "risks": [],
            "options": [
                {
                    "id": name,
                    "title": name,
                    "approach": approach,
                    "pros": [],
                    "cons": [],
                    "risks": [],
                    "prerequisites": [],
                }
                for name, approach in (("a", "Extend the adapter"), ("b", "Replace the adapter"))
            ],
            "recommended_option_id": "a",
            "recommendation_reason": "Less disruption",
            "material_disagreement": False,
        }


class Bridge:
    async def publish(self, *args):
        return "published"

    async def observe(self, *args):
        return None

    async def publish_selection(self, *args):
        return "published"

    async def observe_selection(self, *args):
        return None


@pytest.fixture
def runtime(tmp_path):
    from langflow.adlc.requirement_readiness.service import ReadinessService
    from langflow.adlc.requirement_readiness.service_auth import ServicePrincipal

    store = ReadinessStore(tmp_path / "runs.db")
    agents = FakeAgents()
    config = {"mode": "auto", "revision": "v1", "revoked": False}

    def grant(run):
        if config["revoked"]:
            raise ValueError("SOURCE_SCOPE_DENIED")
        return SourceGrant(
            project_id=run.request.project_id, run_id=run.id, principal_id=run.principal_id, resources={}
        )

    def policy(project):
        return HumanGatePolicy(mode=config["mode"], revision=config["revision"])

    principal = ServicePrincipal("svc", frozenset({"p"}), frozenset({"submit", "read", "answer", "select"}))
    service = ReadinessService(
        store, agents, SourceGateway({}), FakeCatalog(), grant, policy, Bridge(), PipelineConfig()
    )
    return SimpleNamespace(service=service, store=store, agents=agents, principal=principal, config=config)
