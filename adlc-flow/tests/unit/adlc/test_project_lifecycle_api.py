from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

from fastapi import HTTPException, Response
import pytest

from langflow.adlc.live_workflows import LiveService, LiveStore
from langflow.adlc.vai_services import ServiceCheckError
from langflow.api.v1 import adlc_project_lifecycle as api
from test_live_workflows import project


@pytest.mark.asyncio
async def test_every_run_mutation_requires_execute_permission_before_external_effect(tmp_path, monkeypatch):
    owner=str(uuid4()); live=LiveService(LiveStore(tmp_path/'live.db')); p=project(live.store,owner)
    row,_=live.store.create(owner,p,str(uuid4()),str(uuid4()),'Fix app','App','a'*40)
    actor=SimpleNamespace(id=UUID(owner)); session=AsyncMock()
    monkeypatch.setattr(api,'live_service',lambda:live)
    monkeypatch.setattr(api,'source',AsyncMock(return_value=(None,object())))
    monkeypatch.setattr(api,'permission',AsyncMock(return_value=False))
    live._handover=SimpleNamespace(create=AsyncMock(),merge=AsyncMock())
    live._recovery=SimpleNamespace(resume=AsyncMock(),stop=AsyncMock())
    cases=[(api.create_pull_request,api.PullCommand(command_id=uuid4(),head_commit='b'*40)),
           (api.merge_pull_request,api.MergeCommand(command_id=uuid4(),head_commit='b'*40,base_commit='a'*40)),
           (api.recover_run,api.RecoveryCommand(command_id=uuid4())),
           (api.stop_interrupted_run,api.RecoveryCommand(command_id=uuid4()))]
    for route,command in cases:
        with pytest.raises(HTTPException) as denied:
            await route(UUID(row['run_id']),command,session,actor)
        assert denied.value.status_code==403
    live._handover.create.assert_not_called();live._handover.merge.assert_not_called();live._recovery.resume.assert_not_called()
    live._recovery.stop.assert_not_called()
    # An unrelated actor is rejected even before reading the flow or contacting Gitea.
    with pytest.raises(HTTPException) as hidden:
        await api.read_handover(UUID(row['run_id']),session,SimpleNamespace(id=uuid4()),Response())
    assert hidden.value.status_code==404


@pytest.mark.asyncio
async def test_environment_permission_is_checked_before_read_save_or_check(monkeypatch):
    live=SimpleNamespace(environments=SimpleNamespace(read=Mock(),save=AsyncMock(),begin_check=AsyncMock()))
    monkeypatch.setattr(api,'live_service',lambda:live)
    monkeypatch.setattr(api,'authorize_project',AsyncMock(side_effect=ServiceCheckError('LIVE_PROJECT_NOT_FOUND',404)))
    project_id=uuid4(); actor=SimpleNamespace(id=uuid4()); session=AsyncMock()
    cases=[lambda:api.environment(project_id,session,actor,Response()),
           lambda:api.save_environment(project_id,api.EnvironmentCommand(expected_revision=0,profile={}),session,actor),
           lambda:api.check_environment(project_id,api.EnvironmentCheckCommand(check_id=uuid4(),environment_digest='a'*64),session,actor)]
    for call in cases:
        with pytest.raises(HTTPException) as denied:await call()
        assert denied.value.status_code==404
    live.environments.read.assert_not_called();live.environments.save.assert_not_called();live.environments.begin_check.assert_not_called()
