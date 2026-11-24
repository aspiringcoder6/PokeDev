"""Run the actual pinned Workloop DAG in its own process; no PokeDev ORM/global lfx state."""
import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
manifest_path = Path(sys.argv[1]).resolve()
manifest = json.loads(manifest_path.read_text(encoding='utf8'))
directory = manifest_path.parent
runtime = ROOT/'adlc-flow/data/workloop/runtime'
source = runtime/'workloop/src'
sys.path.insert(0,str(ROOT/'sdk'))
sys.path.insert(0,str(source))
sys.path.insert(0,str(source/'workloop/engine'))
os.environ['WORKLOOP_SRC'] = str(source)
os.environ['LANGFLOW_DATABASE_URL'] = 'sqlite:///' + str(directory/'engine.sqlite3').replace('\\','/')
os.environ['WORKLOOP_TRACING'] = '0'
from workloop.backend.processing import process
from workloop.backend.services.db import Store
from workloop.backend.services.loader import load_workflow
from workloop.gateway.base import Contract
from workloop.gateway.deepseek_harness.gateway import DshHarnessGateway
from workloop.engine.workloop_task import WorkloopTask
from lfx.schema.data import Data
from dsh_web_sdk import DshClient, RetryConfig

snapshot = {key:manifest[key] for key in ['run_id','scope_id','factory','workflow','revisions']}
snapshot.update(state='RUNNING',nodes=[],events=[],started_at=time.time())
def persist():
    snapshot['updated_at'] = time.time()
    temp = directory/'result.tmp'
    temp.write_text(json.dumps(snapshot,ensure_ascii=False),encoding='utf8')
    temp.replace(directory/'result.json')

def node_state(name,state,**details):
    row=next((x for x in snapshot['nodes'] if x['id']==name),None)
    if row is None:
        row={'id':name};snapshot['nodes'].append(row)
    row.update(state=state,**details)
    snapshot['events'].append({'node':name,'state':state,'at':time.time()})
    persist()

class ScopedTask(WorkloopTask):
    """Forward DAG input to native agents; block descendants of a failed contract."""
    async def report_output(self):
        from workloop.gateway import get_gateway
        name = self._id
        gateway = get_gateway()
        context = self.context
        if hasattr(context,'data'): context=context.data
        upstream = json.dumps(context,ensure_ascii=False,default=str) if context else ''
        if upstream and '"status": "BLOCKED"' in upstream:
            raise RuntimeError('WORKLOOP_UPSTREAM_BLOCKED')
        node_state(name,'RUNNING')
        brief = self.brief or ''
        if upstream: brief += '\n\n[Đầu vào từ bước trước]\n' + upstream[:16000]
        try:
            contract=await gateway.run_contract_task(name=name,role=self.role or 'coder',brief=brief,
                 system_prompt=(self.system_prompt or '').strip() or None,
                 model=(self.model or '').strip() or manifest['model']['model'])
            node_state(name,contract.status,summary=contract.report_summary,session_id=contract.session_ref,
                       attempts=contract.attempts)
            if contract.status not in {'DONE','DONE_WITH_CONCERNS'}:
                raise RuntimeError('WORKLOOP_NODE_NOT_DONE')
            return Data(data={'task':name,'status':contract.status,'report':contract.report_summary})
        except Exception:
            node_state(name,'BLOCKED',error_code='WORKLOOP_NODE_FAILED')
            raise

class StrictNativeGateway(DshHarnessGateway):
    async def _open_session(self,spec):
        ref=await super()._open_session(spec)
        node_state(spec.name,'RUNNING',session_id=ref.id)
        return ref
    async def _submit(self,spec,ref):
        # Upstream catches selection failures; PokeDev requires the reviewed model.
        await self.client.rpc('session/selectModel',{'request':{'sessionId':ref.id,
            'provider':manifest['model']['provider'],'model':manifest['model']['model']}})
        accepted=await ref.raw.prompt(self._prompt_of[spec.n])
        if accepted is not True: raise RuntimeError('WORKLOOP_PROMPT_NOT_ACCEPTED')

class CandidateGateway:
    """Workloop gateway for deterministic source/test/deployment tasks; never fabricates an agent session."""
    def __init__(self,client): self.client=client;self.contracts={};self.events=[]
    async def pending_approvals(self): return []
    async def close_all(self): pass
    async def read_preview(self):
        return await self.client.http_get('/api/v1/pokedev-services/previews/'+manifest['run_id']+'?scope_id='+manifest['candidate']['scope_id'])
    async def wait_preview(self,terminal):
        for _ in range(110):
            receipt=await self.read_preview();snapshot['preview']=receipt;persist()
            if receipt['state'] in terminal: return receipt
            if receipt['state'] in {'FAILED','UNCONFIRMED'}: raise RuntimeError('WORKLOOP_PREVIEW_UNCONFIRMED')
            await asyncio.sleep(2)
        raise RuntimeError('WORKLOOP_PREVIEW_TIMEOUT')
    async def run_contract_task(self,name,role,brief,**kw):
        candidate=manifest['candidate'];scope=candidate['scope_id']
        if name=='source':
            result=await self.client.http_get('/api/v1/pokedev-services/product-loops/'+candidate['loop_id']+'?scope_id='+scope)
            actual=hashlib.sha256(result.get('files',{}).get('app.py','').encode()).hexdigest()
            if result.get('state')!='SUCCEEDED' or actual!=candidate['source_sha256']:
                raise RuntimeError('WORKLOOP_CANDIDATE_CHANGED')
            text='Đã đối chiếu đúng bản sửa app.py và source SHA-256.'
        elif name=='test':
            if self.contracts.get('source',Contract('','')).status!='DONE': raise RuntimeError('WORKLOOP_UPSTREAM_BLOCKED')
            await self.client.http_post('/api/v1/pokedev-services/previews',
                {'preview_id':manifest['run_id'],'loop_id':candidate['loop_id'],'scope_id':scope})
            result=await self.wait_preview({'VERIFIED'})
            if result.get('source_sha256')!=candidate['source_sha256'] or result.get('tests',{}).get('protected_intact') is not True:
                raise RuntimeError('WORKLOOP_TEST_PROOF_INVALID')
            text='Bộ test bảo vệ đạt trong Sandbox mới, giữ nguyên source và test.'
        elif name=='preview':
            if self.contracts.get('test',Contract('','')).status!='DONE': raise RuntimeError('WORKLOOP_UPSTREAM_BLOCKED')
            await self.client.http_post('/api/v1/pokedev-services/previews/'+manifest['run_id']+'/deploy',{'scope_id':scope})
            result=await self.wait_preview({'LIVE'})
            text='Ứng dụng đã chạy trong Sandbox; 5/5 kiểm tra HTTP đạt.'
        else: raise RuntimeError('WORKLOOP_NODE_DENIED')
        contract=Contract(n=name,name=name,role=role,status='DONE',report_summary=text)
        self.contracts[name]=contract
        return contract

async def main():
    persist()
    store=Store(str(directory/'workloop.sqlite3'))
    runner=process.WorkflowRunner(store)
    process.WorkloopTask=ScopedTask
    factory=manifest['factory']
    cfg={'harness':{'kind':'pokedev-services'},'model':manifest['model']}
    async with DshClient(os.environ['DSH_URL'],os.environ['DSH_TOKEN'],timeout=25,retry=RetryConfig(max_attempts=1)) as client:
        if factory=='pokedev':
            wf={'name':'candidate-preview','nodes':{'source':'WorkloopTask','test':'WorkloopTask','preview':'WorkloopTask'},
                'config':{'source':{'role':'reviewer','brief':'Đối chiếu bản sửa đã hoàn tất.'},
                          'test':{'role':'reviewer','brief':'Chạy lại bộ test bảo vệ trong Sandbox mới.'},
                          'preview':{'role':'release','brief':'Khởi động bản thử và kiểm chứng HTTP.'}},
                'edges':[{'source_id':'source','source_output':'report','target_id':'test','target_input':'context'},
                         {'source_id':'test','source_output':'report','target_id':'preview','target_input':'context'}]}
            gateway=CandidateGateway(client)
        else:
            checkout=runtime/factory
            wf=load_workflow(str(checkout),str(checkout/'workflows'/(manifest['workflow']+'.spec.yaml')))
            if len(wf['nodes'])>6: raise RuntimeError('WORKLOOP_NODE_LIMIT')
            workspace='/app/workspace/pokedev-workloop/'+manifest['scope_id'][:16]+'/'+manifest['run_id']
            gateway=StrictNativeGateway(os.environ['DSH_URL'],os.environ['DSH_TOKEN'],root_workspace=workspace,
                provider=manifest['model']['provider'],model=manifest['model']['model'],timeout_s=360,stall_s=360,max_rearms=0,
                workflow_name=manifest['workflow'],run_tag=manifest['run_id'].replace('-','')[-8:])
            # Contract status can stay IN_PROGRESS while the agent reads/writes.
            # A short contract-only stall timer used to cancel a healthy native turn.
            gateway.client.retry=type(gateway.client.retry)(max_attempts=1)
            for node in wf['config'].values():
                node['brief']=(node.get('brief') or '')+'\n\n[Phạm vi PokeDev] Chỉ thao tác trong workspace riêng này. Không commit/push, không sửa repo hoặc dịch vụ ngoài workspace, không dùng subagent. Thiếu quyền thì báo BLOCKED.'
            snapshot['workspace']=workspace
            cfg['harness']['kind']='dsh'
        process.make_gateway=lambda *a,**k:gateway
        job_id=store.create_job(wf['name'],1,{'source':'pokedev','run_id':manifest['run_id'],'factory':factory})
        snapshot['job_id']=job_id;persist()
        try:
            await asyncio.wait_for(runner.run(job_id,wf,cfg),timeout=850)
            summary=list(gateway.contracts.values())
            success=len(summary)==len(wf['nodes']) and all(c.status in {'DONE','DONE_WITH_CONCERNS'} for c in summary)
            snapshot['state']='SUCCEEDED' if success else 'FAILED'
            if not success: snapshot['error_code']='WORKLOOP_NODE_NOT_DONE'
            snapshot['engine_status']=store.get_job(job_id)['status']
        except Exception as exc:
            snapshot['state']='UNCONFIRMED' if isinstance(exc,asyncio.TimeoutError) else 'FAILED'
            snapshot['error_code']='WORKLOOP_RUNTIME_FAILED'
        finally:
            await gateway.close_all()
            snapshot['completed_at']=time.time();persist()

if __name__=='__main__':
    try: asyncio.run(main())
    except BaseException as exc:
        snapshot['state']='UNCONFIRMED';snapshot['error_code']='WORKLOOP_WORKER_STOPPED';persist()
        raise SystemExit(1)
