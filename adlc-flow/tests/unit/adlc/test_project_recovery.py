import ast
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from langflow.adlc.live_workflows import LiveService, LiveStore, digest
from langflow.adlc.project_recovery import ProjectRecovery, WorkerCheckpoint, checkpoint_binding
from langflow.adlc.vai_services import ServiceCheckError
from test_live_workflows import plan, project


def checkpoint_run(tmp_path, monkeypatch):
    import langflow.adlc.project_recovery as module
    import langflow.adlc.live_workflows as live_module
    monkeypatch.setattr(module, 'DATA', tmp_path)
    monkeypatch.setattr(live_module, 'DATA', tmp_path)
    store=LiveStore(tmp_path/'live.db'); p=project(store)
    row,_=store.create('alice',p,'delivery',str(uuid4()),'Fix the app','App','a'*40)
    row=store.update(row['run_id'],{'state':'UNCONFIRMED','phase':'execution','approved_plan_digest':'p'*64, 'model_route':{'provider':'test','model':'model'}})
    folder=tmp_path/'runs'/row['run_id']/'execution'; folder.mkdir(parents=True)
    checkpoint=WorkerCheckpoint(folder,row)
    checkpoint.write({'outputs':{'DEV':{'status':'DONE'}},'snapshot':{'state':'RUNNING','nodes':[]},'files':{'app.py':'code'}})
    return LiveService(store),row,checkpoint


def test_checkpoint_is_durable_atomic_and_bound_to_owner_phase_source_plan_and_environment(tmp_path,monkeypatch):
    live,row,checkpoint=checkpoint_run(tmp_path,monkeypatch)
    assert WorkerCheckpoint(checkpoint.path.parent,row).read()['state']['files']=={'app.py':'code'}
    for key,value in [('owner','bob'),('phase','planning'),('base_commit','b'*40),('approved_plan_digest','q'*64),('environment',{'digest':'z'*64})]:
        other={**row,key:value}
        with pytest.raises(ServiceCheckError,match='CHECKPOINT_INVALID'):
            WorkerCheckpoint(checkpoint.path.parent,other).read()
    document=json.loads(checkpoint.path.read_text()); document['state']['outputs']['DEV']['status']='FORGED'
    checkpoint.path.write_text(json.dumps(document))
    with pytest.raises(ServiceCheckError,match='CHECKPOINT_INVALID'):checkpoint.read()


def test_recovery_claim_is_one_command_one_generation_and_keeps_same_run(tmp_path,monkeypatch):
    live,row,checkpoint=checkpoint_run(tmp_path,monkeypatch)
    recovery=ProjectRecovery(live); command=str(uuid4())
    first,fresh=recovery.claim('alice',row['run_id'],command,0,'p'*64)
    second,fresh_again=recovery.claim('alice',row['run_id'],command,0,'p'*64)
    assert fresh and not fresh_again and first==second
    assert first['run_id']==row['run_id'] and first['recovery']['generation']==1
    assert checkpoint.read()['binding']==checkpoint_binding(first)
    with pytest.raises(ServiceCheckError,match='RECOVERY_CHANGED'):
        recovery.claim('alice',row['run_id'],str(uuid4()),0,'p'*64)
    with pytest.raises(ServiceCheckError,match='NOT_FOUND'):
        recovery.claim('bob',row['run_id'],str(uuid4()),0,'p'*64)
    assert len(live.store.runs('alice'))==1


@pytest.mark.asyncio
async def test_recovery_adopts_a_live_worker_without_spawning_another(tmp_path,monkeypatch):
    import langflow.adlc.project_recovery as module
    live,row,_=checkpoint_run(tmp_path,monkeypatch)
    live.observe=lambda row:row; live.spawn=Mock()
    recovery=ProjectRecovery(live); recovery.adopt=Mock()
    monkeypatch.setattr(module,'worker_alive',lambda row:True)
    with pytest.raises(ServiceCheckError,match='WORKER_ACTIVE'):
        await recovery.resume('alice',row['run_id'],str(uuid4()),0,'p'*64)
    recovery.adopt.assert_called_once(); live.spawn.assert_not_called()


def load_driver(tmp_path):
    root=Path(__file__).resolve().parents[4]
    tree=ast.parse((root/'integration-sources/workloop/project_worker.py').read_text(encoding='utf8'))
    selected=[n for n in tree.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name in {'Driver','update','sha'}]
    import asyncio,time
    snap={'nodes':[{'id':'DEV','session_id':'saved-session','state':'RUNNING'}],'events':[]}
    space={'asyncio':asyncio,'time':time,'json':json,'hashlib':hashlib,'snapshot':snap,'persist':Mock(),'directory':tmp_path,'manifest':{'run_id':str(uuid4()),'scope_id':'scope','phase':'execution'},'SimpleNamespace':SimpleNamespace,'Data':lambda **kw:kw,
           'wait_native_contract':AsyncMock(return_value={'status':'DONE'}),'human_inputs':SimpleNamespace(waiting=lambda *a:False)}
    exec(compile(ast.Module(body=selected,type_ignores=[]),'production-driver','exec'),space)
    driver=space['Driver'].__new__(space['Driver']); driver.outputs={}; driver.contracts={}; driver.client=AsyncMock(); driver.bridge_id='bridge'
    driver.native_intents={'DEV':{'workspace':'/owned/DEV','inputs':{'context.md':'digest'},'session_id':'saved-session','stage':'submitted'}}
    driver.bridge=AsyncMock(side_effect=[{'nodes':[{'id':'DEV','workspace':'/owned/DEV','inputs':{'context.md':'digest'}}]}, {'sha256':'artifact','artifact':{'files':{'app.py':'recovered'}}}])
    return driver,snap,space


@pytest.mark.asyncio
async def test_real_driver_adopts_submitted_contract_and_never_creates_session_or_resends_prompt(tmp_path):
    driver,snap,space=load_driver(tmp_path)
    result=await driver.native({'id':'DEV'},'instruction is not resent')
    assert result['files']=={'app.py':'recovered'}
    space['wait_native_contract'].assert_awaited_once()
    driver.client.create_session.assert_not_called(); driver.client.rpc.assert_not_called()
    assert snap['nodes'][0]['session_id']=='saved-session' and snap['nodes'][0]['recovered_session']


@pytest.mark.asyncio
async def test_unknown_session_acceptance_never_sends_a_second_request(tmp_path):
    driver,snap,space=load_driver(tmp_path)
    driver.native_intents['DEV'].update(stage='opening_session',session_id=None)
    with pytest.raises(RuntimeError,match='ACCEPTANCE_UNKNOWN'):
        await driver.native({'id':'DEV'},'do not send')
    space['wait_native_contract'].assert_not_called(); driver.client.create_session.assert_not_called()


@pytest.mark.asyncio
async def test_completed_task_checkpoint_is_reused_without_running_or_applying_again(tmp_path):
    driver,snap,space=load_driver(tmp_path)
    driver.outputs={'DEV':{'status':'DONE'}}; driver.implementation=AsyncMock()
    result=await driver.execute_task({'id':'DEV'})
    assert result['data']['recovered'] is True
    driver.implementation.assert_not_called(); driver.bridge.assert_not_called()


@pytest.mark.asyncio
async def test_stop_waits_for_owned_session_cancellation_and_then_allows_a_fresh_run(tmp_path,monkeypatch):
    import langflow.adlc.project_recovery as module
    live,row,_=checkpoint_run(tmp_path,monkeypatch)
    live.observe=lambda row:row
    monkeypatch.setattr(module,'worker_alive',lambda row:False)
    live.cancel_auto_sessions=AsyncMock(side_effect=[False,True])
    recovery=ProjectRecovery(live); command=str(uuid4())
    with pytest.raises(ServiceCheckError,match='STOP_UNCONFIRMED'):
        await recovery.stop('alice',row['run_id'],command,0)
    current=live.store.get('alice',row['run_id'])
    assert current['state']=='UNCONFIRMED' and recovery.inspect(current)['stopping']
    with pytest.raises(ServiceCheckError,match='STOP_UNCONFIRMED'):
        recovery.claim('alice',row['run_id'],str(uuid4()),0,'p'*64)
    stopped=await recovery.stop('alice',row['run_id'],command,0)
    assert stopped['state']=='FAILED' and stopped['error_code']=='LIVE_INTERRUPTED_RUN_CLOSED'
    assert await recovery.stop('alice',row['run_id'],command,0)==stopped
    assert live.cancel_auto_sessions.await_count==2


def test_recovery_cannot_reset_an_exhausted_automation_budget(tmp_path,monkeypatch):
    live,row,_=checkpoint_run(tmp_path,monkeypatch)
    live.store.update(row['run_id'],{'auto_timing':{'active_seconds':600,'limit_seconds':600}})
    with pytest.raises(ServiceCheckError,match='RECOVERY_CHANGED'):
        ProjectRecovery(live).claim('alice',row['run_id'],str(uuid4()),0,'p'*64)


@pytest.mark.parametrize('code',['dsh/transport','dsh/timeout','http/429','http/502','http/503','http/504'])
def test_actual_sdk_timeout_and_http_failure_codes_preserve_recovery(code):
    from dsh_web_sdk.errors import DshError
    from langflow.adlc.project_recovery import recoverable_error
    assert recoverable_error(DshError('transport interrupted',code=code))
    assert not recoverable_error(DshError('workspace missing',code='http/404'))


@pytest.mark.asyncio
async def test_real_native_gateway_preserves_uncertain_prompt_session_for_adoption(tmp_path):
    from langflow.adlc.project_recovery import recoverable_error
    from dsh_web_sdk.errors import DshTimeoutError
    class GatewayBase:
        async def _kill(self,ref):self.killed=True
        async def close_all(self):self.closed=True
    root=Path(__file__).resolve().parents[4]
    tree=ast.parse((root/'integration-sources/workloop/project_worker.py').read_text(encoding='utf8'))
    selected=[node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='NativeGateway']
    snapshot={}; intent={'DEV':{'stage':'session_opened','session_id':'owned'}}
    space={'DshHarnessGateway':GatewayBase,'snapshot':snapshot,'active_driver':SimpleNamespace(native_intents=intent),'persist':Mock(),'MODEL':{'provider':'test','model':'test'},'recoverable_error':recoverable_error}
    exec(compile(ast.Module(body=selected,type_ignores=[]),'production-native-gateway','exec'),space)
    gateway=space['NativeGateway'].__new__(space['NativeGateway']);gateway.node_id='DEV';gateway.client=AsyncMock();gateway._prompt_of={'1':'only one prompt'}
    gateway.client.rpc.return_value={'selected':space['MODEL']}
    ref=SimpleNamespace(id='owned',raw=SimpleNamespace(prompt=AsyncMock(side_effect=DshTimeoutError('lost acknowledgment'))))
    with pytest.raises(DshTimeoutError):await gateway._submit(SimpleNamespace(n='1'),ref)
    assert snapshot['recovery_required'] and intent['DEV']['stage']=='prompt_pending'
    await gateway._kill(ref);await gateway.close_all()
    assert not getattr(gateway,'killed',False) and not getattr(gateway,'closed',False)
    assert ref.raw.prompt.await_count==1


@pytest.mark.asyncio
async def test_verified_worker_termination_stops_real_descendants_on_windows(tmp_path,monkeypatch):
    import asyncio,os,subprocess,sys,psutil
    import langflow.adlc.project_recovery as module
    marker=tmp_path/'child.pid'
    script="import pathlib,subprocess,sys,time;p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);pathlib.Path(sys.argv[1]).write_text(str(p.pid));time.sleep(60)"
    parent=subprocess.Popen([sys.executable,'-c',script,str(marker)],creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    try:
        for _ in range(100):
            if marker.exists():break
            await asyncio.sleep(.02)
        assert marker.exists()
        child=int(marker.read_text())
        monkeypatch.setattr(module,'worker_alive',lambda row:psutil.pid_exists(row['worker_pid']))
        assert await module.terminate_worker({'worker_pid':parent.pid})
        assert not psutil.pid_exists(child) or psutil.Process(child).status()==psutil.STATUS_ZOMBIE
    finally:
        for identity in [int(marker.read_text()) if marker.exists() else None,parent.pid]:
            try:
                if identity:psutil.Process(identity).kill()
            except psutil.NoSuchProcess:pass
        parent.wait(timeout=5)


@pytest.mark.asyncio
async def test_termination_never_touches_a_pid_outside_the_verified_run(monkeypatch):
    import psutil
    import langflow.adlc.project_recovery as module
    monkeypatch.setattr(module,'worker_alive',lambda row:False)
    process=Mock(side_effect=AssertionError('unrelated PID must not be opened'))
    monkeypatch.setattr(psutil,'Process',process)
    assert await module.terminate_worker({'worker_pid':999})
    process.assert_not_called()


@pytest.mark.asyncio
async def test_gate_recovery_continues_after_completed_repair_without_repeating_developer_or_tester(tmp_path):
    from test_workflow_controls import worker_class
    driver,snapshot,space=worker_class(tmp_path)
    driver.gate_progress={'GATE':{'number':0,'stage':'repair','repair_index':1,'feedback':'Fix the failed assertion'}}
    async def native(task,instruction):
        space['update'](task['id'],'RUNNING',session_id='review-session')
        return {'approved':True,'summary':'Exact recovered source accepted'}
    driver.native=native
    result=await driver.review_gate(driver.definitions['GATE'])
    assert result['approved'] and driver.gate_progress['GATE']['stage']=='approved'
    driver.implementation.assert_not_called()
    driver.verification.assert_awaited_once()
    assert not any(node['id'].startswith('DEV__') or node['id'].startswith('TEST__') for node in snapshot['nodes'])
