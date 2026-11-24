import json
from uuid import uuid4
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException,Response
from langflow.adlc.workloop import WorkloopService,WorkloopStore,public_run
from langflow.adlc.vai_services import ServiceCheckError

def context():
    return {'factory':'pokedev','workflow':'candidate-preview','model':{'provider':'netmind','model':'GLM'},
            'revisions':{'workloop':'a'*40},'candidate':{'loop_id':'candidate','scope_id':'b'*64,'source_sha256':'c'*64}}

def test_owned_intent_restart_and_exact_replay(tmp_path):
    path=tmp_path/'runs.sqlite3';store=WorkloopStore(path)
    row,fresh=store.reserve('owner','delivery','cycle','id',context())
    assert fresh and WorkloopStore(path).reserve('owner','delivery','cycle','id',context())==(row,False)
    assert store.list('other','delivery','cycle')==[]
    with pytest.raises(ServiceCheckError,match='CONFLICT'): store.reserve('other','delivery','cycle','id',context())
    with pytest.raises(ServiceCheckError,match='ACTIVE'): store.reserve('owner','delivery','cycle','new',context())

def test_completed_engine_does_not_override_failed_or_missing_node_proof(tmp_path):
    store=WorkloopStore(tmp_path/'runs.sqlite3');row,_=store.reserve('owner','delivery','cycle','id',context())
    service=WorkloopService(store,data=tmp_path/'results')
    directory=service.data/'id';directory.mkdir(parents=True)
    result={k:row[k] for k in ['run_id','scope_id','factory','workflow','revisions']}
    result.update(state='SUCCEEDED',engine_status='completed',nodes=[{'id':'test','state':'BLOCKED'}])
    (directory/'result.json').write_text(json.dumps(result))
    assert service.observe(row)['state']=='UNCONFIRMED'
    result['nodes']=[{'id':'source','state':'DONE'}]
    (directory/'result.json').write_text(json.dumps(result))
    assert service.observe(row)['state']=='UNCONFIRMED'

def test_preview_result_binds_source_scope_and_real_test_and_http_results(tmp_path):
    store=WorkloopStore(tmp_path/'runs.sqlite3');row,_=store.reserve('owner','delivery','cycle','id',context())
    service=WorkloopService(store,data=tmp_path/'results');directory=service.data/'id';directory.mkdir(parents=True)
    result={k:row[k] for k in ['run_id','scope_id','factory','workflow','revisions']}
    result.update(state='SUCCEEDED',nodes=[{'id':n,'state':'DONE'} for n in ['source','test','preview']],preview={
      'preview_id':'id','state':'LIVE','source_sha256':'c'*64,'scope_id':'b'*64,
      'tests':{'passed':True,'protected_intact':True,'checks':[{'exit_code':0}]},
      'http':{'passed':True,'checks':[{'passed':True} for _ in range(5)]}})
    (directory/'result.json').write_text(json.dumps(result))
    assert service.observe(row)['state']=='SUCCEEDED'
    for key,value in [('scope_id','wrong'),('source_sha256','d'*64)]:
        bad=json.loads(json.dumps(result));bad['preview'][key]=value
        (directory/'result.json').write_text(json.dumps(bad))
        assert service.observe(row)['state']=='UNCONFIRMED'

def test_expired_preview_keeps_evidence_and_removes_link():
    result=public_run({'scope_id':'private','candidate':{'scope_id':'private'},'state':'SUCCEEDED',
       'preview':{'scope_id':'private','url':'http://app.example/','expires_at':'2000-01-01T00:00:00Z','state':'LIVE','tests':{'passed':True}}})
    assert result['preview']['state']=='EXPIRED' and result['preview']['url'] is None
    assert result['preview']['tests']['passed'] is True
    assert 'scope_id' not in result and 'scope_id' not in result['preview'] and 'candidate' not in result

@pytest.mark.asyncio
async def test_api_checks_delivery_owner_before_catalog_or_platform(monkeypatch):
    from langflow.api.v1 import adlc_workloop as api
    monkeypatch.setattr(api,'source',AsyncMock(side_effect=HTTPException(404)))
    monkeypatch.setattr(api,'workloops',lambda:pytest.fail('Unauthorized platform access'))
    with pytest.raises(HTTPException): await api.listing(uuid4(),uuid4(),AsyncMock(),object(),Response())

def test_api_rejects_injected_path_or_harness_parameters():
    from pydantic import ValidationError
    from langflow.api.v1.adlc_workloop import StartWorkloop
    with pytest.raises(ValidationError):
        StartWorkloop(cycle_id=uuid4(),run_id=uuid4(),factory='factory-wilson',workflow='pingpong',context_digest='x',workspace='/app/workspace/shared')


def test_preview_relay_is_local_scoped_and_rejects_cross_origin_or_arbitrary_paths():
    import base64
    import httpx
    from datetime import datetime,timedelta,timezone
    from unittest.mock import patch
    from langflow.adlc.preview_relay import PreviewRelays
    relay=PreviewRelays()
    row={'run_id':'owned','state':'SUCCEEDED','preview':{'state':'LIVE','access_mode':'POKEDEV_RELAY',
         'scope_id':'private-scope','expires_at':(datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat()}}
    async def remote(_client,method,path,command):
        assert method=='POST' and path.endswith('/owned/http') and command['scope_id']=='private-scope'
        return {'status':200,'content_type':'text/html; charset=utf-8','body_base64':base64.b64encode(b'<html>remote sandbox</html>').decode()}
    with patch('langflow.adlc.preview_relay.PlatformClient.request',remote):
        url=relay.url(row)
        assert url.startswith('http://localhost:') and relay.url(row)==url
        with httpx.Client(trust_env=False) as client:
            assert client.get(url).text=='<html>remote sandbox</html>'
            assert client.get(url+'.env').status_code==404
            assert client.get(url,headers={'Host':'evil.example'}).status_code==403
            assert client.post(url+'api/tasks',json={'title':'test'},headers={'Origin':'http://evil.example'}).status_code==403
            assert client.post(url+'api/tasks',content='x'*4097,headers={'Origin':url.rstrip('/')}).status_code==413
    relay.servers['owned'][0].shutdown()
