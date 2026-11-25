import os
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from broker.state import (
    active_runners,
    active_metadata,
    LaunchRequest,
    RegisterStandbyRequest,
    AttachRunnerRequest,
    logger,
    DEFAULT_SANDBOX_IMAGE,
    DEFAULT_SANDBOX_ENTRYPOINT,
    DEFAULT_SANDBOX_EXTENSIONS,
)

from broker.services.runtime import get_provider

router = APIRouter()

@router.get("/debug/sessions")
def get_debug_sessions():
    return list(active_metadata.values())

@router.get("/debug/sessions/{session_id}")
def get_debug_session_detail(session_id: str):
    if session_id in active_metadata:
        return active_metadata[session_id]
    raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

@router.get("/debug/runners")
def get_debug_runners():
    runners = []
    for sid, ws in active_runners.items():
        meta = active_metadata.get(sid, {})
        runners.append({
            "sessionId": sid,
            "runnerId": meta.get("runnerId", "unknown"),
            "status": meta.get("status", "CONNECTED"),
            "workspace": meta.get("workspace", "/workspace")
        })
    return {"count": len(runners), "runners": runners}

@router.get("/debug/sandboxes")
def get_debug_sandboxes():
    sandboxes = []
    for sid, meta in active_metadata.items():
        sandboxes.append({
            "sandboxId": meta.get("sandboxId", "unknown"),
            "sessionId": sid,
            "runnerId": meta.get("runnerId", "unknown"),
            "status": meta.get("status", "READY"),
            "workspace": meta.get("workspace", "/workspace")
        })
    return {"count": len(sandboxes), "sandboxes": sandboxes}

@router.post("/api/launch")
async def launch_environment(payload: LaunchRequest = LaunchRequest()):
    session_id = payload.session_id or f"sess-{os.urandom(4).hex()}"
    project_path = payload.project_path or os.getcwd()
    image = payload.image or DEFAULT_SANDBOX_IMAGE
    # Same `is not None` semantics as management.create_session: explicit
    # empty values from the dashboard opt out of the env defaults.
    entrypoint = payload.entrypoint if payload.entrypoint is not None else DEFAULT_SANDBOX_ENTRYPOINT
    extensions = payload.extensions if payload.extensions is not None else DEFAULT_SANDBOX_EXTENSIONS
    ttl = payload.ttl or 3600

    try:
        # cpu/memory mirror the facade defaults previously supplied by
        # create_sandbox_container for this route.
        provider = get_provider()
        sandbox_id = provider.create_sandbox(
            session_id=session_id,
            project_path=project_path,
            image=image,
            ttl=ttl,
            cpu="2",
            memory="4Gi",
            entrypoint=entrypoint,
            extensions=extensions
        )
        if not payload.create_sandbox_only:
            # The sandbox's execd agent is the executor — no host-side runner
            # process is spawned; the sandbox is created and ready for direct
            # execd execution.
            return {
                "status": "launching",
                "message": f"OpenSandbox container '{sandbox_id}' launched (direct execd execution, no runner process)",
                "sessionId": session_id,
                "sandboxId": sandbox_id,
                "pid": 0
            }
        else:
            register_standby_sandbox_api(RegisterStandbyRequest(
                session_id=session_id,
                sandbox_id=sandbox_id,
                project_path=project_path,
                image=image,
                ttl=ttl
            ))
            return {
                "status": "standby",
                "message": f"OpenSandbox standby container '{sandbox_id}' created",
                "sessionId": session_id,
                "sandboxId": sandbox_id
            }
    except Exception as e:
        logger.error(f"Failed to launch environment: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/sandboxes/register-standby")
def register_standby_sandbox_api(payload: RegisterStandbyRequest):
    now_str = datetime.now(timezone.utc).isoformat()
    
    active_metadata[payload.session_id] = {
        "sessionId": payload.session_id,
        "runnerId": "none (standby)",
        "sandboxId": payload.sandbox_id,
        "workspace": payload.project_path,
        "image": payload.image,
        "ttl": payload.ttl,
        "status": "STANDBY",
        "runnerConnected": False,
        "createdAt": now_str,
        "lastActivity": now_str,
    }
    return {"status": "ok", "message": f"Registered standby sandbox {payload.sandbox_id}"}

@router.post("/api/sandboxes/attach-runner")
async def attach_runner_api(payload: AttachRunnerRequest):
    try:
        provider = get_provider()
        # The sandbox's execd agent is the executor — resume the paused/stopped
        # sandbox; no host-side runner process is spawned.
        started = provider.start_sandbox(payload.sandbox_id)
        return {
            "status": "attaching",
            "message": (
                f"Sandbox '{payload.sandbox_id}' {'resumed' if started else 'already running'} "
                f"— direct execd execution for session '{payload.session_id}'"
            ),
            "pid": 0
        }
    except Exception as e:
        logger.error(f"Failed to attach runner: {e}")
        raise HTTPException(status_code=500, detail=str(e))
