import asyncio
import copy

from .models import ReviewResult


async def independent_pair(first, second):
    tasks = [asyncio.create_task(first), asyncio.create_task(second)]
    try:
        return tuple(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


class DualReview:
    def __init__(self, agents, skill_catalog):
        self.agents,self.skill_catalog=agents,skill_catalog

    async def assess(self,snapshot):
        async def one(role,expected):
            report=ReviewResult.model_validate(await self.agents.ask(role,copy.deepcopy(snapshot),{},
                f"{snapshot['run_id']}:{snapshot['digest']}:{role}"))
            if report.reviewer_id!=expected or report.snapshot_digest!=snapshot["digest"]:
                raise ValueError("READINESS_REVIEW_BINDING_INVALID")
            return report
        return await independent_pair(one("reviewer-a","a"),one("reviewer-b","b"))


def review_gate(snapshot,reports,skill_catalog):
    if len(reports)!=2 or {r.reviewer_id for r in reports}!={"a","b"}:
        return "blocked"
    known={e["id"] for e in snapshot.get("evidence",())}
    for report in reports:
        citations=set(report.evidence) | {e for f in report.findings for e in f.evidence}
        if report.snapshot_digest!=snapshot["digest"] or not citations<=known:
            return "blocked"
    for state in ("blocked","awaiting_authorization","needs_context"):
        if any(r.status==state for r in reports):
            return state
    if len({r.route for r in reports})!=1 or reports[0].route=="unresolved":
        return "needs_clarification"
    if not skill_catalog.check_route(reports[0].route).ready:
        return "blocked"
    if any(r.status=="needs_clarification" or any(f.blocking for f in r.findings) for r in reports):
        return "needs_clarification"
    if len({r.status for r in reports})!=1:
        return "blocked"
    if reports[0].status=="spec_ready":
        if (not all(skill_catalog.validate_receipts(r.receipt_ids,snapshot["digest"],r.artifacts) for r in reports)
                or set(reports[0].artifacts)!=set(reports[1].artifacts)):
            return "blocked"
    return reports[0].status
