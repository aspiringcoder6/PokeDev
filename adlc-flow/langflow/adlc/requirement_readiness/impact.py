import copy

from .models import ImpactReport, canonical_digest
from .review import independent_pair


def validate_impact_pair(snapshot, reports, *, allow_incomplete=False):
    if len(reports) != 2 or {r.analyst for r in reports} != {"code", "requirements"}:
        raise ValueError("READINESS_IMPACT_PAIR_INVALID")
    known = {e["id"] for e in snapshot.get("evidence", ())}
    for report in reports:
        if report.snapshot_digest != snapshot["digest"]:
            raise ValueError("READINESS_IMPACT_BINDING_INVALID")
        if not set(report.evidence_ids) <= known:
            raise ValueError("READINESS_IMPACT_CITATION_INVALID")
        if report.status != "complete" and not allow_incomplete:
            raise ValueError("READINESS_IMPACT_INCOMPLETE")
    return tuple(sorted(reports, key=lambda r: r.analyst))


def report_digests(reports):
    return {r.analyst: canonical_digest(r.model_dump(mode="json")) for r in reports}


class DualImpact:
    def __init__(self, agents, skill_catalog):
        self.agents, self.skills = agents, skill_catalog

    async def analyze(self, snapshot, reviews):
        for role in ("impact-code", "impact-requirements"):
            if not self.skills.check_role(role).ready:
                raise ValueError("READINESS_NATIVE_DEPENDENCY_MISSING")

        async def one(role, expected):
            output = await self.agents.ask(
                role,
                copy.deepcopy(snapshot),
                {"reviews": copy.deepcopy(reviews)},
                f"{snapshot['run_id']}:{snapshot['digest']}:{role}",
            )
            report = ImpactReport.model_validate(output)
            if report.analyst != expected:
                raise ValueError("READINESS_IMPACT_BINDING_INVALID")
            return report

        reports = await independent_pair(one("impact-code", "code"), one("impact-requirements", "requirements"))
        return validate_impact_pair(snapshot, reports, allow_incomplete=True)
