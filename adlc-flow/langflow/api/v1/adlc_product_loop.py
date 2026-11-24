"""Pinned-source native TaskLoop acceptance runs for private delivery owners."""
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from langflow.adlc import cycle_planning as planning, delivery as d, delivery_cycles as cycles
from langflow.adlc.blueprints.models import WorkflowDefinition
from langflow.adlc.product_loop import ACTIVE, digest, product_loops, public_loop
from langflow.adlc.vai_services import ServiceCheckError
from langflow.api.utils import DbSession
from langflow.api.v1.adlc_delivery import permission, source
from langflow.api.v1.adlc_team_access import TeamUser
from langflow.services.authorization import FlowAction
from langflow.services.database.models.adlc_execution_plan import AdlcExecutionPlan

router = APIRouter(prefix='/adlc/deliveries/{identity}/native-loop', tags=['Native TaskLoop'])


class StartLoop(BaseModel):
    model_config = ConfigDict(extra='forbid')
    cycle_id: UUID
    loop_id: UUID
    context_digest: str


async def context_for(session, row, cycle, flow, actor):
    if cycle.number != 1:
        d.fail('LOOP_SUCCESSOR_EXECUTION_NOT_ENABLED')
    if not row.plan_id or not row.plan_approved_digest or not row.workflow_approved_digest:
        d.fail('LOOP_APPROVED_INPUT_REQUIRED')
    archive = await session.get(AdlcExecutionPlan, row.plan_id)
    if not archive or archive.owner_id != str(actor.id) or archive.workflow_definition_id != row.flow_id:
        d.fail('LOOP_APPROVED_INPUT_REQUIRED')
    workflow = WorkflowDefinition.model_validate(archive.workflow_payload)
    specs = [planning.loop_spec(stage) for stage in workflow.stages if stage.inputs.get('task_loop_spec')]
    if len(specs) != 1:
        d.fail('LOOP_SINGLE_TASK_REQUIRED')
    spec = specs[0]
    if any(c.verifier_ref != 'verifier:python-unittest/0.1.0' for c in spec.verification_commands):
        d.fail('LOOP_VERIFIER_UNSUPPORTED')
    snapshot = await planning.repository_context(workflow, spec.base_commit)
    context = {'base_commit': spec.base_commit, 'goal': spec.specification,
               'files': {p: item['content'] if item else '' for p, item in snapshot['files'].items()},
               'checks': [{'check_id': c.check_id, 'test_path': c.test_path, 'timeout_ms': c.timeout_ms}
                          for c in spec.verification_commands],
               'writable_paths': spec.writable_paths, 'max_iterations': min(spec.max_iterations, 3)}
    return context, digest({'context': context, 'plan': row.plan_approved_digest, 'cycle': str(cycle.id)})


@router.get('')
async def list_loops(identity: UUID, cycle_id: UUID, session: DbSession, actor: TeamUser, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    row, flow = await source(session, identity, actor)
    cycle = await cycles.owned_cycle(session, row, cycle_id)
    try:
        context, binding = await context_for(session, row, cycle, flow, actor)
        preview = {k: v for k, v in context.items() if k != 'files'}
        preview.update(context_digest=binding, file_sizes={p: len(text.encode()) for p, text in context['files'].items()})
        context_error = None
    except HTTPException as exc:
        preview = None
        context_error = exc.detail.get('code') if isinstance(exc.detail, dict) else 'LOOP_SOURCE_UNAVAILABLE'
    owner, delivery, selected = str(actor.id), str(row.id), str(cycle.id)
    await session.commit()
    service = product_loops()
    rows = service.store.list(owner, delivery, selected)
    for stored in rows:
        if stored['state'] in ACTIVE:
            service.spawn(stored)
    try:
        capabilities = await service.capabilities()
        error = context_error
    except ServiceCheckError as exc:
        capabilities, error = None, exc.code
    return {'context': preview, 'capabilities': capabilities, 'error_code': error,
            'loops': [public_loop(stored) for stored in rows]}


@router.post('', status_code=202)
async def start_loop(identity: UUID, command: StartLoop, session: DbSession, actor: TeamUser, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    row, flow = await source(session, identity, actor, write=True)
    cycle = await cycles.owned_cycle(session, row, command.cycle_id)
    if not await permission(actor, flow, FlowAction.EXECUTE):
        d.fail('DELIVERY_EXECUTION_DENIED', 403)
    context, binding = await context_for(session, row, cycle, flow, actor)
    if binding != command.context_digest:
        d.fail('LOOP_SOURCE_CHANGED')
    owner, delivery, selected = str(actor.id), str(row.id), str(cycle.id)
    await session.commit()
    service = product_loops()
    try:
        caps = await service.capabilities()
        if caps.get('ready') is not True:
            raise ServiceCheckError('LOOP_RUNTIME_UNAVAILABLE', 503)
        value, fresh = service.store.reserve(owner, delivery, selected, str(command.loop_id), context)
        service.spawn(value, create=fresh)
        return public_loop(value)
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {'code': exc.code}) from None
