import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from broker.state import (
    push_event,
    event_log,
    active_runners,
    active_workspaces,
    active_metadata,
    CreateSessionPayload,
    AttachRunnerRequest,
    logger,
    DEFAULT_SANDBOX_IMAGE,
    DEFAULT_SANDBOX_ENTRYPOINT,
    DEFAULT_SANDBOX_EXTENSIONS,
)
from broker.services.runtime import get_provider
from broker.services.vfs_client import vfs_client

router = APIRouter(prefix="/api/v1/management", tags=["Orchestrator Management"])


class RenewPayload(BaseModel):
    ttl: int = Field(gt=0, description="Seconds to extend the sandbox expiry from now")


class AttachProjectPayload(BaseModel):
    project: str = Field(min_length=1, description="VFS workspace (project) name to bind and sync")

@router.post("/sessions")
async def create_session(payload: CreateSessionPayload = CreateSessionPayload()):
    """
    [Orchestrator] Provision an OpenSandbox container and optional Standalone Runner process.
    """
    session_id = payload.session_id or f"sess-{uuid.uuid4().hex[:8]}"
    project_path = payload.project_path
    image = payload.image or DEFAULT_SANDBOX_IMAGE
    cpu = payload.cpu or "2"
    memory = payload.memory or "4Gi"
    # `is not None` (not truthiness): the dashboard sends explicit empty
    # values ([] / {}) for non-dind images to opt OUT of the env defaults.
    # Safety: only apply DinD defaults when image IS the DinD-capable default.
    # Non-DinD images (python:3.11-slim, ubuntu, etc.) crash exit 127 with
    # start-dind.sh as entrypoint (file doesn't exist in those images).
    _is_dind = image == DEFAULT_SANDBOX_IMAGE and DEFAULT_SANDBOX_ENTRYPOINT is not None
    entrypoint = payload.entrypoint if payload.entrypoint is not None else (DEFAULT_SANDBOX_ENTRYPOINT if _is_dind else None)
    extensions = payload.extensions if payload.extensions is not None else (DEFAULT_SANDBOX_EXTENSIONS if _is_dind else None)
    # ttl <= 0 (or None) => no auto-expiration; only manual termination removes it
    ttl = payload.ttl if payload.ttl and payload.ttl > 0 else 0
    ttl = ttl or 0

    provider = get_provider()
    try:
        sandbox_id = provider.create_sandbox(
            session_id=session_id,
            project_path=project_path,
            image=image,
            ttl=ttl,
            cpu=cpu,
            memory=memory,
            entrypoint=entrypoint,
            extensions=extensions
        )

        # Always write metadata immediately after container creation so the session
        # is visible in the dashboard regardless of whether a runner connects.
        now_str = datetime.now(timezone.utc).isoformat()
        if payload.create_sandbox_only:
            # Standby mode: no runner will be started
            active_metadata[session_id] = {
                "sessionId": session_id,
                "runnerId": "none (standby)",
                "sandboxId": sandbox_id,
                "workspace": project_path or "/workspace",
                "image": image,
                "cpu": cpu,
                "memory": memory,
                "ttl": ttl,
                "entrypoint": entrypoint,
                "extensions": extensions,
                "status": "STANDBY",
                "runnerConnected": False,
                "createdAt": now_str,
                "lastActivity": now_str,
            }
        else:
            # Full session mode: write a STARTING placeholder; WebSocket handler
            # will overwrite this with full runner info once the runner connects.
            # The sandbox's execd agent is the executor itself — no host-side
            # runner process is spawned and no WS registration will ever arrive.
            # Poll the sandbox health (best-effort ~15s); never fail the request
            # on timeout.
            active_metadata[session_id] = {
                "sessionId": session_id,
                "runnerId": "unknown",
                "sandboxId": sandbox_id,
                "workspace": project_path or "/workspace",
                "image": image,
                "cpu": cpu,
                "memory": memory,
                "ttl": ttl,
                "entrypoint": entrypoint,
                "extensions": extensions,
                "status": "STARTING",
                "runnerConnected": False,
                "createdAt": now_str,
                "lastActivity": now_str,
            }
            runner_id = "runner-" + uuid.uuid4().hex[:8]
            active_metadata[session_id]["runnerId"] = runner_id
            from broker.services.opensandbox_executor import get_executor

            sandbox_ready = False
            start_time = time.time()
            while time.time() - start_time < 15.0:
                try:
                    handle = await get_executor().get_handle(sandbox_id)
                    if await handle.is_healthy():
                        sandbox_ready = True
                        break
                except Exception as poll_err:
                    logger.warning(
                        f"[Management] Sandbox health poll failed for '{sandbox_id}': {poll_err}"
                    )
                await asyncio.sleep(0.5)
            if sandbox_ready:
                now_ready = datetime.now(timezone.utc).isoformat()
                active_metadata[session_id].update({
                    "status": "RUNNING",
                    "lastActivity": now_ready,
                })
            else:
                logger.warning(
                    f"[Management] Sandbox '{sandbox_id}' not healthy after 15s "
                    f"(session '{session_id}' keeps status STARTING)."
                )

        meta = active_metadata.get(session_id, {})
        push_event(
            f"[provision] session '{session_id}' sandbox '{sandbox_id}' project '{project_path}' ttl={ttl}"
        )

        return {
            "status": "success",
            "sessionId": session_id,
            "sandboxId": sandbox_id,
            "runnerId": meta.get("runnerId", "unknown"),
            "workspace": meta.get("workspace", "/workspace"),
            "image": image,
            "cpu": cpu,
            "memory": memory,
            "ttl": ttl,
            "entrypoint": entrypoint,
            "extensions": extensions,
        }
    except Exception as e:
        logger.error(f"[Management] Failed to create session: {e}")
        # Clean up any partial metadata entry
        active_metadata.pop(session_id, None)
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """
    [Orchestrator] Terminate a session and kill the underlying OpenSandbox container.
    """
    provider = get_provider()
    meta = active_metadata.pop(session_id, None)
    ws = active_runners.pop(session_id, None)
    active_workspaces.pop(session_id, None)

    sandbox_id = meta.get("sandboxId") if meta else None
    if ws:
        try:
            await ws.close()
        except Exception:
            pass

    if sandbox_id:
        provider.terminate_sandbox(sandbox_id)
        # Release the direct executor's cached SDK handle (opensandbox
        # provider); a no-op for providers that never cached one.
        try:
            from broker.services.opensandbox_executor import get_executor

            await get_executor().evict(sandbox_id)
        except Exception as evict_err:
            logger.warning(f"[Management] Failed to evict executor handle for '{sandbox_id}': {evict_err}")

    push_event(f"[terminate] session '{session_id}' sandbox '{sandbox_id}' destroyed")

    return {
        "status": "success",
        "sessionId": session_id,
        "message": f"Session '{session_id}' terminated and sandbox container destroyed."
    }

@router.get("/logs")
def get_event_logs():
    """Recent broker events for the dashboard Command Console."""
    return {"logs": list(event_log)}


@router.get("/sessions")
def list_sessions():
    """
    [Orchestrator] List all active sessions and topology mappings.
    """
    return list(active_metadata.values())

@router.get("/sessions/{session_id}")
def get_session_detail(session_id: str):
    """
    [Orchestrator] Get detailed metadata for a specific session.
    """
    if session_id in active_metadata:
        return active_metadata[session_id]
    raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

@router.get("/sandboxes")
def list_sandboxes():
    """
    [Orchestrator] List active OpenSandbox containers and container-level metrics.
    """
    sandboxes = []
    for sid, meta in active_metadata.items():
        sandboxes.append({
            "sandboxId": meta.get("sandboxId", "unknown"),
            "sessionId": sid,
            "runnerId": meta.get("runnerId", "unknown"),
            "status": meta.get("status", "READY"),
            "workspace": meta.get("workspace", "/workspace"),
            "image": meta.get("image", "ubuntu:latest"),
            "cpu": meta.get("cpu", "2"),
            "memory": meta.get("memory", "4Gi"),
            "ttl": meta.get("ttl", 3600),
        })
    return {"count": len(sandboxes), "sandboxes": sandboxes}

@router.get("/runners")
def list_runners():
    """
    [Orchestrator] List connected Standalone Runners.
    """
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

@router.post("/sessions/{session_id}/attach-runner")
async def attach_runner(session_id: str, payload: AttachRunnerRequest):
    """
    [Orchestrator] Attach a runner to a standby sandbox.
    The sandbox's execd agent is the executor itself — this resumes the
    paused/stopped sandbox (no runner process is spawned).
    """
    provider = get_provider()
    try:
        started = provider.start_sandbox(payload.sandbox_id)
        return {
            "status": "attaching",
            "message": (
                f"Sandbox '{payload.sandbox_id}' {'resumed' if started else 'already running'} "
                f"— direct execd execution for session '{session_id}'"
            ),
            "pid": 0
        }
    except Exception as e:
        logger.error(f"[Management] Failed to attach runner: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _resolve_sandbox_id(session_id: str) -> str:
    meta = active_metadata.get(session_id)
    if not meta or not meta.get("sandboxId"):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return meta["sandboxId"]


@router.post("/sessions/{session_id}/pause")
async def pause_session(session_id: str):
    """[Orchestrator] Pause the sandbox backing a session (docker pause)."""
    sandbox_id = _resolve_sandbox_id(session_id)
    try:
        get_provider().pause_sandbox(sandbox_id)
    except Exception as e:
        logger.error(f"[Management] Pause failed for '{session_id}' (sandbox '{sandbox_id}'): {e}")
        raise HTTPException(status_code=502, detail=f"Pause failed for sandbox '{sandbox_id}': {e}")
    active_metadata[session_id].update({
        "status": "PAUSED",
        "lastActivity": datetime.now(timezone.utc).isoformat(),
    })
    push_event(f"[lifecycle] session '{session_id}' paused (sandbox '{sandbox_id}')")
    return {"status": "success", "sessionId": session_id, "sandboxId": sandbox_id, "sessionStatus": "PAUSED"}


@router.post("/sessions/{session_id}/resume")
async def resume_session(session_id: str):
    """[Orchestrator] Resume a paused sandbox backing a session."""
    sandbox_id = _resolve_sandbox_id(session_id)
    try:
        get_provider().resume_sandbox(sandbox_id)
    except Exception as e:
        logger.error(f"[Management] Resume failed for '{session_id}' (sandbox '{sandbox_id}'): {e}")
        raise HTTPException(status_code=502, detail=f"Resume failed for sandbox '{sandbox_id}': {e}")
    now_dt = datetime.now(timezone.utc)
    active_metadata[session_id].update({
        "status": "RUNNING",
        "lastActivity": now_dt.isoformat(),
    })
    # Mirrors the server-side pause semantics: resuming restarts the expiry
    # clock. ttl <= 0 means "no expiry" — clear any stale stamped expiry.
    ttl_val = active_metadata[session_id].get("ttl")
    try:
        ttl_num = float(ttl_val)
    except (TypeError, ValueError):
        ttl_num = 0
    if ttl_num > 0:
        active_metadata[session_id]["expiresAt"] = (now_dt + timedelta(seconds=ttl_num)).isoformat()
    else:
        active_metadata[session_id].pop("expiresAt", None)
    push_event(f"[lifecycle] session '{session_id}' resumed (sandbox '{sandbox_id}')")
    return {"status": "success", "sessionId": session_id, "sandboxId": sandbox_id, "sessionStatus": "RUNNING"}


@router.post("/sessions/{session_id}/renew")
async def renew_session(session_id: str, payload: RenewPayload):
    """[Orchestrator] Extend the sandbox expiry by ttl seconds from now."""
    sandbox_id = _resolve_sandbox_id(session_id)
    try:
        result = get_provider().renew_sandbox(sandbox_id, payload.ttl)
    except Exception as e:
        logger.error(f"[Management] Renew failed for '{session_id}' (sandbox '{sandbox_id}'): {e}")
        raise HTTPException(status_code=502, detail=f"Renew failed for sandbox '{sandbox_id}': {e}")
    now_str = datetime.now(timezone.utc).isoformat()
    meta = active_metadata[session_id]
    meta.update({"ttl": payload.ttl, "lastActivity": now_str})
    if result.get("expiresAt"):
        meta["expiresAt"] = result["expiresAt"]
    else:
        # SDK did not report a new expiry — derive it client-side so the
        # reaper's createdAt+ttl fallback cannot reap a just-renewed session.
        meta["expiresAt"] = (datetime.now(timezone.utc) + timedelta(seconds=payload.ttl)).isoformat()
    push_event(f"[lifecycle] session '{session_id}' renewed (+{payload.ttl}s)")
    return {"status": "success", "sessionId": session_id, "sandboxId": sandbox_id, **result}


@router.get("/sessions/{session_id}/metrics")
def session_metrics(session_id: str):
    """[Orchestrator] Sandbox resource metrics (CPU/memory) passthrough."""
    sandbox_id = _resolve_sandbox_id(session_id)
    try:
        metrics = get_provider().get_sandbox_metrics(sandbox_id)
    except Exception as e:
        logger.error(f"[Management] Metrics failed for '{session_id}' (sandbox '{sandbox_id}'): {e}")
        raise HTTPException(status_code=502, detail=f"Metrics failed for sandbox '{sandbox_id}': {e}")
    return {"sessionId": session_id, "sandboxId": sandbox_id, "metrics": metrics}


@router.get("/sessions/{session_id}/ports/{port}")
def session_endpoint(session_id: str, port: int):
    """[Orchestrator] Public URL of a service listening on `port` inside the session's sandbox."""
    sandbox_id = _resolve_sandbox_id(session_id)
    try:
        endpoint = get_provider().get_sandbox_endpoint(sandbox_id, port)
    except Exception as e:
        logger.error(f"[Management] Endpoint lookup failed for '{session_id}' (sandbox '{sandbox_id}', port {port}): {e}")
        raise HTTPException(status_code=502, detail=f"Endpoint lookup failed for sandbox '{sandbox_id}' port {port}: {e}")
    return {"sessionId": session_id, "sandboxId": sandbox_id, "port": port, "url": endpoint.get("url")}


@router.get("/sessions/{session_id}/diagnostics")
def session_diagnostics(session_id: str):
    """[Orchestrator] Sandbox diagnostics (events + logs) passthrough."""
    sandbox_id = _resolve_sandbox_id(session_id)
    try:
        data = get_provider().get_sandbox_diagnostics(sandbox_id, scope="all")
    except Exception as e:
        logger.error(f"[Management] Diagnostics failed for '{session_id}' (sandbox '{sandbox_id}'): {e}")
        raise HTTPException(status_code=502, detail=f"Diagnostics failed for sandbox '{sandbox_id}': {e}")
    return {"sessionId": session_id, "sandboxId": sandbox_id, **data}


@router.post("/sessions/{session_id}/attach-project")
async def attach_project(session_id: str, payload: AttachProjectPayload):
    """[Orchestrator] Bind a sandbox to a project's VFS workspace and sync its
    files into /workspace — enables 'create sandbox first, sync project later'.

    Resets the session sync manifest so the FULL project tree is pushed (normal
    delta sync only ships changes). Paused sandboxes are resumed first. From
    here on, per-action delta sync and git commit/push cover this project."""
    sandbox_id = _resolve_sandbox_id(session_id)
    # Validate the project exists in VFS before mutating session state.
    try:
        data = await vfs_client.list_workspaces()
        known = set(data.get("workspaces") or [])
    except Exception as e:
        logger.error(f"[Management] Attach-project VFS lookup failed for '{session_id}': {e}")
        raise HTTPException(status_code=502, detail=f"VFS workspace lookup failed: {e}")
    if payload.project not in known:
        raise HTTPException(status_code=404, detail=f"Project '{payload.project}' not found in VFS")

    meta = active_metadata[session_id]
    if meta.get("status") == "PAUSED":
        try:
            get_provider().resume_sandbox(sandbox_id)
        except Exception as e:
            logger.error(f"[Management] Attach-project resume failed for '{session_id}': {e}")
            raise HTTPException(status_code=502, detail=f"Resume failed for sandbox '{sandbox_id}': {e}")
        meta["status"] = "RUNNING"

    # Function-level imports: agent.py owns the VFS<->sandbox sync machinery
    # (single source of truth for manifest bookkeeping).
    from broker.routes.agent import _build_sync_files, _session_synced_manifest
    from broker.services.opensandbox_executor import SYNC_FAILED_ERROR_CODE, get_executor

    meta["workspace"] = payload.project
    meta["lastActivity"] = datetime.now(timezone.utc).isoformat()
    _session_synced_manifest.pop(session_id, None)  # force full push
    delta, current = await _build_sync_files(session_id)
    synced = 0
    if delta:
        result = await get_executor().execute(
            session_id,
            sandbox_id,
            {"runShellCommand": {"command": "true"}},
            30.0,
            sync_files=delta,
        )
        err = result.get("error") or {}
        if err.get("code") == SYNC_FAILED_ERROR_CODE:
            _session_synced_manifest.pop(session_id, None)  # retry on next action
            logger.error(f"[Management] Attach-project sync failed for '{session_id}': {err}")
            raise HTTPException(
                status_code=502,
                detail=f"Project sync failed: {err.get('stderr') or err.get('message') or 'unknown error'}",
            )
        if current is not None:
            _session_synced_manifest[session_id] = current
        synced = len(delta.get("changed", []))
    elif current is not None:
        _session_synced_manifest[session_id] = current
    push_event(f"[attach-project] session '{session_id}' -> project '{payload.project}' ({synced} files synced)")
    return {
        "status": "success",
        "sessionId": session_id,
        "sandboxId": sandbox_id,
        "project": payload.project,
        "filesSynced": synced,
    }
