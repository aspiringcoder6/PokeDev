from fastapi import APIRouter
from broker.routes.management import create_session, delete_session, get_session_detail
from broker.routes.agent import execute_action, get_session_workspace
from broker.state import active_runners, active_metadata

router = APIRouter()

# Legacy alias endpoints for backward compatibility
@router.post("/session/create")
@router.post("/api/sessions/create")
async def legacy_create_session(payload: dict = {}):
    from broker.state import CreateSessionPayload
    p = CreateSessionPayload(**payload) if payload else CreateSessionPayload()
    return await create_session(p)

@router.delete("/session/{session_id}")
@router.delete("/api/sessions/{session_id}")
async def legacy_delete_session(session_id: str):
    return await delete_session(session_id)

@router.get("/session/{session_id}/metadata")
def legacy_get_session_metadata(session_id: str):
    return get_session_detail(session_id)

@router.get("/session/{session_id}/workspace")
def legacy_get_session_workspace(session_id: str):
    return get_session_workspace(session_id)

@router.post("/execute")
async def legacy_execute_action(payload: dict):
    from broker.state import ExecutePayload
    p = ExecutePayload(**payload)
    return await execute_action(p)

@router.get("/")
def read_root():
    return {
        "status": "ok",
        "active_runners_count": len(active_runners),
        "active_sessions": list(active_runners.keys())
    }
