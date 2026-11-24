import copy
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from langflow.adlc.live_workflows import LiveService, LiveStore
from langflow.adlc.project_handover import ProjectHandover, merge_readiness
from langflow.adlc.vai_services import ServiceCheckError
from test_live_workflows import project


HEAD='b'*40; BASE='a'*40


def evidence():
    row={'base_commit':BASE,'published':{'branch':'codex/result','commit':HEAD},'handover':{'base_branch':'main'}}
    pull={'number':1,'title':'Fix app','html_url':'http://gitea/admin/notes/pulls/1','head':{'sha':HEAD,'ref':'codex/result'},'base':{'sha':BASE,'ref':'main'},'state':'open','mergeable':True,'merged':False,'user':{'id':1}}
    branch={'commit':{'id':BASE},'enable_status_check':True,'status_check_contexts':['ci/*'],'required_approvals':1,'user_can_merge':True}
    statuses=[{'context':'ci/test','status':'success','id':2,'updated_at':'2026-10-27T01:00:00Z'}]
    reviews=[{'id':1,'user':{'id':2},'commit_id':HEAD,'state':'APPROVED','official':True,'submitted_at':'2026-10-27T01:00:00Z'}]
    return row,pull,branch,statuses,reviews


def test_merge_requires_current_tested_head_base_checks_and_independent_current_reviews():
    args=evidence(); assert merge_readiness(*args)['can_merge']
    mutations=[(0,lambda v:v['published'].update(commit='c'*40),'HEAD_CHANGED'),
               (2,lambda v:v['commit'].update(id='c'*40),'BASE_CHANGED'),
               (3,lambda v:v[0].update(status='failure'),'CHECKS_NOT_PASSED'),
               (3,lambda v:v.clear(),'REQUIRED_CHECK_MISSING'),
               (4,lambda v:v[0].update(commit_id='c'*40),'REVIEW_REQUIRED'),
               (4,lambda v:v[0]['user'].update(id=1),'REVIEW_REQUIRED'),
               (4,lambda v:v[0].update(dismissed=True),'REVIEW_REQUIRED'),
               (1,lambda v:v.update(mergeable=False),'NOT_MERGEABLE')]
    for index,change,code in mutations:
        changed=copy.deepcopy(args); change(changed[index])
        result=merge_readiness(*changed)
        assert not result['can_merge'] and any(code in c for c in result['reasons'])


def test_latest_status_and_review_override_history_and_no_ci_is_explicit():
    args=evidence(); args[3].append({'context':'ci/test','status':'failure','id':1,'updated_at':'2026-10-26T01:00:00Z'})
    assert merge_readiness(*args)['can_merge']
    args[4].append({'id':2,'user':{'id':2},'commit_id':HEAD,'state':'REQUEST_CHANGES','submitted_at':'2026-10-27T02:00:00Z'})
    assert not merge_readiness(*args)['can_merge']
    row,pull,branch,statuses,reviews=evidence(); branch.update(enable_status_check=False,required_approvals=0)
    result=merge_readiness(row,pull,branch,[],[])
    assert result['can_merge'] and result['no_ci']


def setup(tmp_path):
    store=LiveStore(tmp_path/'live.db'); p=project(store)
    row,_=store.create('alice',p,str(uuid4()),str(uuid4()),'Fix app','Fix app',BASE)
    row=store.update(row['run_id'],{'state':'SUCCEEDED','phase':'execution','approved_plan_digest':'p'*64,'published':{'branch':'codex/result','commit':HEAD},'checks':[]})
    live=LiveService(store); live.observe=lambda row:row
    gitea=AsyncMock(); handover=ProjectHandover(live,gitea)
    return handover,row,gitea


@pytest.mark.asyncio
async def test_pr_creation_is_idempotent_and_does_not_override_server_merge_rules(tmp_path):
    service,row,gitea=setup(tmp_path); _,pull,branch,statuses,reviews=evidence()
    remote=[]
    async def request(method,path,body=None):
        if method=='POST' and path.endswith('/pulls'):
            pull['body']=body['body']; remote.append(copy.deepcopy(pull)); return copy.deepcopy(pull)
        if '/branches/codex%2Fresult' in path:return {'commit':{'id':HEAD}}
        if '/branches/main' in path:return copy.deepcopy(branch)
        if '/pulls?state=all' in path:return copy.deepcopy(remote)
        if '/pulls/1/reviews?' in path:return copy.deepcopy(reviews)
        if '/status?' in path:return {'statuses':copy.deepcopy(statuses)}
        if path.endswith('/pulls/1'):return copy.deepcopy(pull)
        raise AssertionError((method,path,body))
    gitea.request.side_effect=request
    first=await service.create('alice',row['run_id'],HEAD,str(uuid4()))
    second=await service.create('alice',row['run_id'],HEAD,str(uuid4()))
    assert first['pull']==second['pull'] and len(remote)==1
    assert sum(c.args[0]=='POST' for c in gitea.request.await_args_list)==1
    with pytest.raises(ServiceCheckError,match='NOT_FOUND'):
        await service.create('bob',row['run_id'],HEAD,str(uuid4()))


@pytest.mark.asyncio
async def test_merge_sends_exact_head_and_never_force_merges_or_blindly_repeats_uncertain_requests(tmp_path):
    service,row,gitea=setup(tmp_path); _,pull,_,_,_=evidence()
    value={'state':'OPEN','base_branch':'main','pull':{'number':1,'head':HEAD,'base_commit':BASE},'readiness':{'can_merge':True,'no_ci':False,'reasons':[]}}
    service.save(row,value)
    async def refresh(owner,identity,locked=False):return service.live.store.get(owner,identity)['handover']
    service.refresh=refresh
    gitea.request.side_effect=ServiceCheckError('GITEA_UNAVAILABLE',503)
    with pytest.raises(ServiceCheckError,match='MERGE_UNCONFIRMED'):
        await service.merge('alice',row['run_id'],str(uuid4()),HEAD,BASE)
    body=gitea.request.await_args.args[2]
    assert body['head_commit_id']==HEAD and body['force_merge'] is False and body['merge_when_checks_succeed'] is False
    with pytest.raises(ServiceCheckError,match='MERGE_UNCONFIRMED'):
        await service.merge('alice',row['run_id'],str(uuid4()),HEAD,BASE)
    assert gitea.request.await_count==1


@pytest.mark.asyncio
async def test_merge_without_ci_requires_explicit_ack_and_closed_issue_waits_for_confirmed_merge(tmp_path):
    service,row,gitea=setup(tmp_path)
    value={'state':'OPEN','base_branch':'main','pull':{'number':1,'head':HEAD,'base_commit':BASE},'readiness':{'can_merge':True,'no_ci':True,'reasons':[]}}
    service.refresh=AsyncMock(return_value=value)
    with pytest.raises(ServiceCheckError,match='NO_CI_CONFIRMATION'):
        await service.merge('alice',row['run_id'],str(uuid4()),HEAD,BASE)
    gitea.request.assert_not_called()
    row['issue']={'number':4}
    assert await service.close_issue(row,value)==value
    gitea.request.assert_not_called()
