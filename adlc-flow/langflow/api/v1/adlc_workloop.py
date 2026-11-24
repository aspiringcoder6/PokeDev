"""PokeDev-owned Workloop runs; never exposes generic Workloop or Sandbox admin APIs."""
import hashlib
from uuid import UUID
from fastapi import APIRouter,HTTPException,Response
from pydantic import BaseModel,ConfigDict
from langflow.adlc import delivery as d,delivery_cycles as cycles
from langflow.adlc.product_loop import product_loops,digest
from langflow.adlc.workloop import workloops,catalog,LOCK,MODEL,public_run
from langflow.adlc.vai_services import ServiceCheckError
from langflow.adlc.preview_relay import preview_relays
from langflow.api.utils import DbSession
from langflow.api.v1.adlc_delivery import source,permission
from langflow.api.v1.adlc_team_access import TeamUser
from langflow.services.authorization import FlowAction

router=APIRouter(prefix='/adlc/deliveries/{identity}/workloop',tags=['Workloop'])
class StartWorkloop(BaseModel):
    model_config=ConfigDict(extra='forbid')
    cycle_id:UUID
    run_id:UUID
    factory:str
    workflow:str
    context_digest:str

def context(row,cycle,actor):
    candidates=product_loops().store.list(str(actor.id),str(row.id),str(cycle.id))
    candidate=next((x for x in candidates if x.get('state')=='SUCCEEDED' and x.get('files',{}).get('app.py')),None)
    selected=None if candidate is None else {'loop_id':candidate['loop_id'],'scope_id':candidate['scope_id'],
        'source_sha256':hashlib.sha256(candidate['files']['app.py'].encode()).hexdigest()}
    factories=catalog()
    revisions={k:v['revision'] for k,v in LOCK['repositories'].items()}
    binding=digest({'owner':str(actor.id),'delivery':str(row.id),'cycle':str(cycle.id),
                    'plan':row.plan_approved_digest,'workflow':row.workflow_approved_digest,
                    'candidate':selected,'revisions':revisions})
    return {'candidate':selected,'factories':factories,'revisions':revisions,'context_digest':binding}

@router.get('')
async def listing(identity:UUID,cycle_id:UUID,session:DbSession,actor:TeamUser,response:Response):
    response.headers['Cache-Control']='no-store'
    row,flow=await source(session,identity,actor)
    cycle=await cycles.owned_cycle(session,row,cycle_id)
    ctx=context(row,cycle,actor)
    await session.commit()
    service=workloops()
    import asyncio
    caps,plugins=await asyncio.gather(service.capabilities(),service.inventory())
    records=service.store.list(str(actor.id),str(row.id),str(cycle.id))
    return {'context':{**ctx,'candidate':None if ctx['candidate'] is None else {k:v for k,v in ctx['candidate'].items() if k!='scope_id'}},
            'capabilities':caps,'inventory':plugins,'runs':[public_run(service.observe(r), preview_relays) for r in records]}

@router.post('',status_code=202)
async def start(identity:UUID,command:StartWorkloop,session:DbSession,actor:TeamUser,response:Response):
    response.headers['Cache-Control']='no-store'
    row,flow=await source(session,identity,actor,write=True)
    cycle=await cycles.owned_cycle(session,row,command.cycle_id)
    if not await permission(actor,flow,FlowAction.EXECUTE): d.fail('DELIVERY_EXECUTION_DENIED',403)
    if not row.plan_approved_digest or not row.workflow_approved_digest: d.fail('WORKLOOP_APPROVED_INPUT_REQUIRED')
    ctx=context(row,cycle,actor)
    if ctx['context_digest']!=command.context_digest: d.fail('WORKLOOP_SOURCE_CHANGED')
    if command.factory=='pokedev':
        if command.workflow!='candidate-preview' or not ctx['candidate']: d.fail('WORKLOOP_CANDIDATE_REQUIRED')
    else:
        factory=next((f for f in ctx['factories'] if f['id']==command.factory),None)
        wf=next((w for w in (factory or {}).get('workflows',[]) if w['id']==command.workflow),None)
        if not wf or not wf['enabled']: d.fail('WORKLOOP_TEMPLATE_NOT_ENABLED')
    await session.commit()
    service=workloops()
    try:
        caps=await service.capabilities()
        if not caps['ready'] or (command.factory=='pokedev' and not caps['preview_ready']):
            raise ServiceCheckError('WORKLOOP_RUNTIME_UNAVAILABLE',503)
        execution={'factory':command.factory,'workflow':command.workflow,'model':MODEL,'revisions':ctx['revisions']}
        if command.factory=='pokedev':
            execution['candidate']=ctx['candidate']
            execution['node_ids']=['source','test','preview']
        else: execution['node_ids']=[n['id'] for n in wf['nodes']]
        value,fresh=service.store.reserve(str(actor.id),str(row.id),str(cycle.id),str(command.run_id),execution)
        if fresh: service.spawn(value)
        return public_run(value)
    except ServiceCheckError as exc: raise HTTPException(exc.status,{'code':exc.code}) from None
