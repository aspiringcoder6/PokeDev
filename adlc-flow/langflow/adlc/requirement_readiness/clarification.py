from __future__ import annotations

from typing import Protocol

from .collection import snapshot_for
from .models import HumanQuestion, HumanRound, canonical_digest


class HumanBridge(Protocol):
    async def publish(self, run_id, round_id, questions, project_id): ...
    async def observe(self, round_id): ...
    async def publish_selection(self, run_id, assessment_digest, options, recommendation, project_id): ...
    async def observe_selection(self, assessment_digest): ...


def validate_round_response(row,response):
    if not isinstance(response,dict) or set(response)!={"answers","confirmed"}:
        raise ValueError("READINESS_ANSWER_INVALID")
    answers=response["answers"]
    expected={q["id"] for q in row["questions"]}
    if (not isinstance(answers,dict) or set(answers)!=expected
            or any(not isinstance(v,str) or not v.strip() for v in answers.values())
            or type(response["confirmed"]) is not bool
            or response["confirmed"] and (row.get("kind")!="confirmation" or expected)):
        raise ValueError("READINESS_ANSWER_INVALID")
    return {"answers":dict(answers),"confirmed":response["confirmed"]}


async def publish_once(store,run,key,role,publish,observe):
    op=store.begin_operation(run.id,key,role,key)
    if op.state=="COMPLETED":
        return op.result
    if not op.is_new:
        receipt=await observe()
        if receipt is None:
            return None
    else:
        try:
            receipt=await publish()
        except Exception:
            store.operation_state(key,"UNCONFIRMED")
            return None
    store.finish_operation(key,{"receipt":receipt})
    return receipt


class ClarificationEngine:
    def __init__(self,agents,store,human_bridge):
        self.agents,self.store,self.bridge=agents,store,human_bridge

    async def advance(self,run):
        run=self.store.load(run.id)
        if self.bridge is None:
            return self.store.update(run.id,run.revision,{"status":"blocked","error_code":"READINESS_HUMAN_CHANNEL_UNAVAILABLE"})
        if run.status=="waiting_human":
            row=run.human_rounds[-1]
        else:
            snapshot=run.snapshot.model_dump(mode="json") | {"run_id":run.id}
            key=f"{run.id}:{snapshot['digest']}:clarifier:{len(run.human_rounds)}"
            output=await self.agents.ask("clarifier",snapshot,{
                "reviews":[r.model_dump(mode="json") for r in run.reviews],
                "previous_rounds":[r.model_dump(mode="json") for r in run.human_rounds]},key)
            if set(output)!={"questions"}:
                raise ValueError("READINESS_AGENT_OUTPUT_INVALID")
            questions=tuple(HumanQuestion.model_validate(q) for q in output["questions"])
            if len(questions)>20 or len({q.id for q in questions})!=len(questions):
                raise ValueError("READINESS_AGENT_OUTPUT_INVALID")
            row=HumanRound(id=canonical_digest([key,"human"]),snapshot_digest=snapshot["digest"],
                           kind="frontier" if questions else "confirmation",questions=questions)
            run=self.store.update(run.id,run.revision,{"status":"waiting_human","human_rounds":(*run.human_rounds,row)})
        await publish_once(self.store,run,row.id+":publish","human-publication",
            lambda:self.bridge.publish(run.id,row.id,[q.model_dump(mode="json") for q in row.questions],run.request.project_id),
            lambda:self.bridge.observe(row.id))
        return self.store.load(run.id)

    def apply_answer(self,run,round_id,response,command_id,expected_revision=None,principal_id=None):
        payload={"round_id":round_id,"response":response,"principal_id":principal_id}
        prior=self.store.command_result(run.id,command_id,payload)
        if prior:
            return prior
        run=self.store.load(run.id)
        if run.status!="waiting_human" or not run.human_rounds or run.human_rounds[-1].id!=round_id:
            raise ValueError("READINESS_ANSWER_BINDING_INVALID")
        row=run.human_rounds[-1]
        if row.snapshot_digest!=run.snapshot.digest or row.kind=="authorization":
            raise ValueError("READINESS_ANSWER_BINDING_INVALID")
        validated=validate_round_response(row.model_dump(mode="json"),response)
        row=row.model_copy(update=validated | {"answered":True})
        rounds=(*run.human_rounds[:-1],row)
        changes={"human_rounds":rounds,"status":"needs_clarification"}
        if row.kind=="confirmation":
            if not row.confirmed:
                changes["status"]="waiting_human"
            else:
                actual=[f"{q.id}: {r.answers[q.id]}" for r in rounds for q in r.questions if q.id in r.answers]
                requirement=run.request.requirement+"\n\nConfirmed human decisions:\n"+"\n".join(actual)
                revised=run.model_copy(update={"confirmed_requirement":requirement})
                changes.update(confirmed_requirement=requirement,snapshot=snapshot_for(revised),status="context_ready",
                               reviews=(),impacts=(),assessment=None,decision=None,pending_selection=None,readiness_kind=None)
        return self.store.command(run.id,command_id,payload,
            run.revision if expected_revision is None else expected_revision,changes)
