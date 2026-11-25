import base64
import json
import uuid
import os
from typing import Optional
from fastapi import APIRouter, HTTPException
from broker.state import (
    active_runners,
    active_workspaces,
    active_metadata,
    push_event,
    ExecutePayload,
    logger,
)

from broker.services.vfs_client import vfs_client, is_scratch_path
from broker.services.command_policy import command_policy

router = APIRouter(prefix="/api/v1/agent", tags=["Subagent Execution"])

# Last synced VFS manifest per session (path -> sha256) used for delta sync
_session_synced_manifest: dict = {}


def _runner_path(p: str) -> str:
    """Convert a VFS path to the runner's workspace-relative form.

    The Go runner treats every path as workspace-relative (safePath joins it
    under the container's workspace root, default /workspace). Sending VFS
    paths as absolute "/workspace/x" would double-nest them to
    /workspace/workspace/x, so strip the prefix at the source.
    """
    if not p:
        return p
    norm = p.replace("\\", "/")
    if norm == "/workspace":
        return ""
    if norm.startswith("/workspace/"):
        return norm[len("/workspace/"):]
    return norm


def _first_path_segment(path: str) -> str:
    return path.replace("\\", "/").lstrip("/").split("/", 1)[0]


async def _has_vfs_workspace_entry(session_id: str, entries: dict | None = None) -> bool:
    """True when the session's VFS workspace contains a top-level entry literally
    named 'workspace' (a real project folder). In that case '/workspace/...' action
    paths are project-relative paths INTO that folder — NOT a container-root
    prefix — and must NOT be stripped (otherwise the folder level is silently
    flattened inside the sandbox while VFS/tree keeps it).
    """
    try:
        if entries is None:
            entries = await vfs_client.list_files(_vfs_workspace(session_id))
        return any(
            _first_path_segment(f.get("path", "")) == "workspace"
            for f in entries.get("files", [])
        )
    except Exception as e:
        logger.warning(f"[Agent Execution] workspace-entry check failed (defaulting to strip): {e}")
        return False


async def _resolve_write_paths(session_id: str, p: str) -> tuple[str, str]:
    """Path resolution for MUTATING actions (runWriteFile / runEditFile).

    Returns (vfs_path, runner_path). Disambiguates '/workspace/X' BEFORE the
    write (pre-write manifest — never self-fulfilling):
    - Project HAS a top-level entry named 'workspace'  -> p is project-relative:
      vfs_path = p (folder 'workspace' kept in VFS tree), runner = p without
      leading slash (container /workspace/workspace/...).
    - Project has NO such entry -> p is a legacy container-absolute path:
      vfs_path = '/' + rest (stripped — no phantom 'workspace' folder poisons
      the manifest), runner = rest (container root).
    Both sides always agree because VFS stores the canonical resolved path.
    """
    if not p:
        return p, p
    norm = p.replace("\\", "/")
    if norm == "/workspace":
        return "/", ""
    if not norm.startswith("/workspace/"):
        return norm, norm
    rest = norm[len("/workspace/"):]
    if await _has_vfs_workspace_entry(session_id):
        return norm, norm.lstrip("/")
    return "/" + rest, rest


async def _resolve_readonly_runner_path(session_id: str, p: str) -> str:
    """Path resolution for READ-ONLY actions (runReadFile fallback / listDirectory).

    Exact-match disambiguation: if the VFS manifest has an entry exactly at p,
    p is a project-relative path (the folder 'workspace' is real) — keep it.
    Otherwise treat p as a legacy container-absolute path and strip the
    '/workspace/' prefix. Safe against self-fulfilling matches because these
    actions never create manifest entries.
    """
    if not p:
        return p
    norm = p.replace("\\", "/")
    if norm == "/workspace" or not norm.startswith("/workspace/"):
        return _runner_path(norm)
    try:
        entries = await vfs_client.list_files(_vfs_workspace(session_id))
        vfs_paths = {f.get("path", "") for f in entries.get("files", [])}
        if norm in vfs_paths:
            return norm
    except Exception as e:
        logger.warning(f"[Agent Execution] readonly path check failed (defaulting to strip): {e}")
    return _runner_path(norm)


def _vfs_workspace(session_id: str) -> str:
    """Resolve the VFS workspace that owns files written/edited/read by a session.

    Sessions provisioned with a project (meta.workspace != "/workspace") share the
    project's VFS workspace — so files appear in the project tree, are delta-synced
    before shell commands, and are covered by git commit/push. Sessions without a
    project fall back to a session-scoped workspace (session_id).
    Must be used consistently by runReadFile / runEditFile / runWriteFile so that
    read-after-write stays within one workspace (same key as _build_sync_files).
    """
    ws = active_metadata.get(session_id, {}).get("workspace")
    return ws if ws and ws != "/workspace" else session_id


async def _build_sync_files(session_id: str) -> tuple[dict | None, dict | None]:
    """Compute the VFS delta for the session's project workspace.
    Writes go to VFS (master); execution happens in the sandbox, so changed
    project files are pushed to the container before every shell command.

    Returns (delta, current_manifest). `delta` is None when there is nothing
    to push (or on error); `current` is the full manifest snapshot the caller
    should store in `_session_synced_manifest` AFTER the sync was delivered
    successfully (None on error / no project workspace)."""
    try:
        workspace = active_metadata.get(session_id, {}).get("workspace")
        if not workspace or workspace == "/workspace":
            return None, None
        entries = await vfs_client.list_files(workspace)
        current = {
            f["path"]: f["sha256"]
            for f in entries.get("files", [])
            if not is_scratch_path(f["path"])
        }
        last = _session_synced_manifest.get(session_id, {})
        # Manifest-aware: when the project really has a top-level folder named
        # 'workspace', VFS paths under '/workspace/...' must NOT be stripped.
        keep_workspace_prefix = await _has_vfs_workspace_entry(session_id, entries)

        def _sync_path(p: str) -> str:
            if keep_workspace_prefix and p.replace("\\", "/").startswith("/workspace/"):
                return p.replace("\\", "/")
            return _runner_path(p)

        changed = []
        for path, sha in current.items():
            if last.get(path) != sha:
                record = await vfs_client.read_file(workspace, path)
                content = record.get("content", "")
                if record.get("isBinary"):
                    content_b64 = content
                else:
                    content_b64 = base64.b64encode(content.encode("utf-8")).decode()
                changed.append({"path": _sync_path(path), "contentBase64": content_b64})

        deleted = [_sync_path(p) for p in last if p not in current]

        if not changed and not deleted:
            return None, current
        return {"changed": changed, "deleted": deleted}, current
    except Exception as e:
        logger.warning(f"[Agent Execution] VFS delta sync failed (will retry next command): {e}")
        _session_synced_manifest.pop(session_id, None)
        return None, None


def _canonical_response(
    request_id: str,
    session_id: str,
    status: Optional[str],
    stdout: Optional[str],
    stderr: Optional[str],
    exit_code: Optional[int],
    error_obj: Optional[dict],
    duration_ms: Optional[int],
    response_text: Optional[str],
    spec_warning: Optional[str],
) -> dict:
    """Build the canonical /execute response for the direct-executor path.

    CR-04 invariant: status="success" ⇔ exitCode == 0. Runners historically
    returned status="success" together with a truthful non-zero exitCode
    (only spawn/exec failures were reported as status="error"). Normalize at
    the API boundary so every consumer sees the invariant while
    exitCode/stderr stay truthful. error_obj is intentionally NOT fabricated
    here: existing clients key off exitCode for failure handling, and
    fabricating one would change their error-message behavior.
    """
    if status == "success" and exit_code is not None and exit_code != 0:
        status = "error"

    canonical_response = {
        # CR-05 (hardened): single canonical key "requestId" everywhere
        # (HTTP + WS dispatch). Inbound still tolerates legacy "requestID".
        "requestId": request_id,
        "sessionId": session_id,
        "status": status,
        "stdout": stdout if stdout is not None else "",
        "stderr": stderr if stderr is not None else "",
        "exitCode": exit_code,
        "error": error_obj,
        "durationMs": duration_ms,
        "response": response_text,
    }
    if spec_warning:
        canonical_response["specWarning"] = spec_warning
    return canonical_response

@router.post("/execute")
async def execute_action(payload: ExecutePayload):
    """
    [Subagent] Execute an action inside the target sandbox session (runShellCommand, readFiles, writeFiles, listDirectory, etc.).
    Routes project files to VFS SQLite and scratchpad files to ephemeral container RAM.
    """
    request_id = str(uuid.uuid4())

    # 0. Command Policy gate — safety (Tier 1) + spec-conformance (Tier 2).
    #    Blocks dangerous commands outright and fences shell file-mutations that
    #    would bypass the VFS dual-write contract (runWriteFile/runEditFile).
    shell_spec = payload.action.get("runShellCommand")
    spec_warning: Optional[str] = None
    if isinstance(shell_spec, dict) and isinstance(shell_spec.get("command"), str) and shell_spec["command"].strip():
        verdict = command_policy.evaluate(shell_spec["command"])
        if verdict.verdict == "block" and command_policy.mode == "enforce":
            logger.warning(
                f"[Command Policy] BLOCKED session={payload.session_id} "
                f"reason='{verdict.reason}' matched='{verdict.matched}'"
            )
            push_event(f"[policy] BLOCKED {payload.session_id}: {verdict.reason} | {verdict.matched}")
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "COMMAND_BLOCKED",
                    "message": verdict.reason,
                    "matched": verdict.matched,
                    "suggestion": verdict.suggestion,
                },
            )
        if verdict.verdict in ("block", "warn"):
            # mode == "audit": blocks are downgraded to warnings
            spec_warning = f"{verdict.reason} {verdict.suggestion or ''}".strip()
            logger.warning(
                f"[Command Policy] WARN (mode={command_policy.mode}) session={payload.session_id} "
                f"reason='{verdict.reason}' matched='{verdict.matched}'"
            )
            push_event(f"[policy] WARN {payload.session_id}: {verdict.matched}")

    # 1. Check if action is runReadFile for a project file -> serve directly from VFS
    read_data = payload.action.get("runReadFile")
    if read_data and isinstance(read_data, dict):
        filepath = read_data.get("filepath", "")
        if filepath and not is_scratch_path(filepath):
            # Try the raw path first (older raw-stored entries), then the
            # canonical stripped form ('/workspace/x' -> '/x') for files written
            # after canonical-path normalization.
            norm = filepath.replace("\\", "/")
            candidates = [filepath]
            if norm.startswith("/workspace/") and norm != filepath:
                candidates.append(filepath)
            if norm.startswith("/workspace/"):
                candidates.append("/" + norm[len("/workspace/"):])
            vfs_res = None
            for candidate in candidates:
                try:
                    vfs_res = await vfs_client.read_file(_vfs_workspace(payload.session_id), candidate)
                    break
                except Exception:
                    continue
            if vfs_res is not None:
                content = vfs_res.get("content", "")
                return {
                    "requestId": request_id,
                    "sessionId": payload.session_id,
                    "status": "success",
                    "stdout": content,
                    "stderr": "",
                    "exitCode": 0,
                    "error": None,
                    "durationMs": 1,
                    "response": content,
                    "source": "vfs",
                }
            logger.info(f"[Agent Execution] VFS file not found ({filepath}), falling back to sandbox executor")

    logger.info(f"[Agent Execution] Executing action (session={payload.session_id}, req={request_id}): {json.dumps(payload.action)}")

    msg = payload.action.copy()
    msg["requestId"] = request_id

    # 2. If runEditFile on project file -> apply fuzzy edit in VFS and sync patched content to runner
    edit_data = payload.action.get("runEditFile")
    if edit_data and isinstance(edit_data, dict):
        filepath = edit_data.get("filepath", "")
        old_str = edit_data.get("oldString", "")
        new_str = edit_data.get("newString", "")
        if filepath and not is_scratch_path(filepath):
            try:
                # Resolve BEFORE the edit (pre-write manifest — never self-fulfilling)
                vfs_path, runner_path = await _resolve_write_paths(payload.session_id, filepath)
                vfs_res = await vfs_client.edit_file(
                    _vfs_workspace(payload.session_id), vfs_path, [{"oldText": old_str, "newText": new_str}]
                )
                logger.info(f"[Agent Execution] Applied fuzzy diff edit in VFS: {vfs_path}")
                # Morph message into runWriteFile to sync patched content to runner
                msg = {
                    "runWriteFile": {
                        "filepath": runner_path,
                        "contents": vfs_res.get("after", "")
                    },
                    "requestId": request_id
                }
            except Exception as edit_err:
                logger.warning(f"[Agent Execution] VFS edit fallback: {edit_err}")

    # 3. If runWriteFile on project file -> persist to VFS as well
    write_data = payload.action.get("runWriteFile")
    if write_data and isinstance(write_data, dict):
        filepath = write_data.get("filepath", "")
        contents = write_data.get("contents", "")
        if filepath and not is_scratch_path(filepath):
            try:
                # Resolve BEFORE the write (pre-write manifest — never self-fulfilling):
                # both VFS and the runner get the SAME canonical path, so the tree
                # and the sandbox structure can never diverge.
                vfs_path, runner_path = await _resolve_write_paths(payload.session_id, filepath)
                await vfs_client.write_file(_vfs_workspace(payload.session_id), vfs_path, contents)
                logger.info(f"[Agent Execution] Saved file to VFS: {vfs_path}")
                write_data = {**write_data, "filepath": runner_path}
                msg = {**msg, "runWriteFile": write_data}
            except Exception as write_err:
                logger.warning(f"[Agent Execution] Failed saving to VFS: {write_err}")

    # Normalize fallback action paths for the runner (see _resolve_runner_path):
    # the runner treats paths as workspace-relative, so "/workspace/x" would
    # double-nest to /workspace/workspace inside the container — unless the
    # project really has a top-level folder named 'workspace' (then keep).
    for _action_key in ("runReadFile", "runWriteFile"):
        _spec = msg.get(_action_key)
        if isinstance(_spec, dict) and _spec.get("filepath"):
            msg[_action_key] = {
                **_spec,
                "filepath": await _resolve_readonly_runner_path(payload.session_id, _spec["filepath"]),
            }

    # listDirectory uses "path" instead of "filepath" — same double-nesting
    # hazard ("/workspace" + "/workspace" = /workspace/workspace), so normalize
    # it with the same manifest-aware rule.
    _ls_spec = msg.get("listDirectory")
    if isinstance(_ls_spec, dict) and _ls_spec.get("path"):
        msg["listDirectory"] = {
            **_ls_spec,
            "path": await _resolve_readonly_runner_path(payload.session_id, _ls_spec["path"]),
        }

    # Push changed VFS files into the sandbox before executing shell commands.
    # (delta, current): the delta is pushed with the action; the manifest
    # snapshot is recorded only after the sync was delivered successfully.
    sync_delta: dict | None = None
    sync_current: dict | None = None
    if "runShellCommand" in payload.action:
        sync_delta, sync_current = await _build_sync_files(payload.session_id)
        if sync_delta:
            msg["sync_files"] = sync_delta
            logger.info(
                f"[Agent Execution] Delta sync for session '{payload.session_id}': "
                f"{len(sync_delta['changed'])} changed, {len(sync_delta['deleted'])} deleted"
            )

    # CR-01: configurable execute timeout (read from payload.action.runShellCommand.timeout)
    execute_timeout_default = float(os.environ.get("BROKER_EXECUTE_TIMEOUT", "300.0"))
    requested_timeout = None
    if isinstance(payload.action.get("runShellCommand"), dict):
        requested_timeout = payload.action["runShellCommand"].get("timeout")
    effective_timeout = (
        min(max(float(requested_timeout) + 15.0, 30.0), 1800.0)
        if requested_timeout
        else execute_timeout_default
    )

    # Direct-execution path: execute the action straight against the
    # sandbox's execd agent — no host-side runner process, no WebSocket
    # relay. The executor reads sync_files from the action dict itself.
    sandbox_id = active_metadata.get(payload.session_id, {}).get("sandboxId")
    if not sandbox_id:
        logger.error(f"[Agent Execution] No active sandbox found for session: {payload.session_id}")
        raise HTTPException(
            status_code=404,
            detail=f"No active sandbox connected for session '{payload.session_id}'."
        )

    try:
        from broker.services.opensandbox_executor import SYNC_FAILED_ERROR_CODE, get_executor

        execution = await get_executor().execute(payload.session_id, sandbox_id, msg, effective_timeout)
    except Exception as e:
        logger.error(f"[Agent Execution] Error executing request {request_id}: {str(e)}")
        return {
            "requestId": request_id,
            "sessionId": payload.session_id,
            "status": "error",
            "stdout": "",
            "stderr": "",
            "exitCode": None,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": str(e)
            },
            "durationMs": None,
            "response": "",
        }

    # Manifest bookkeeping: the executor already applied sync_files unless it
    # failed (SYNC_FAILED) — leave the manifest untouched in that case so the
    # delta is recomputed and retried by the next shell command.
    sync_failed = isinstance(execution.get("error"), dict) and execution["error"].get("code") == SYNC_FAILED_ERROR_CODE
    if sync_current is not None and not sync_failed:
        _session_synced_manifest[payload.session_id] = sync_current

    canonical_response = _canonical_response(
        request_id,
        payload.session_id,
        execution.get("status"),
        execution.get("stdout"),
        execution.get("stderr"),
        execution.get("exitCode"),
        execution.get("error"),
        execution.get("durationMs"),
        execution.get("stdout"),
        spec_warning,
    )

    cmd_preview = ""
    shell = payload.action.get("runShellCommand")
    if isinstance(shell, dict):
        cmd_preview = shell.get("command", "")[:120]
    push_event(f"[execute] {payload.session_id} exit={canonical_response.get('exitCode')} {cmd_preview}")

    return canonical_response

@router.get("/sessions/{session_id}/workspace")
def get_session_workspace(session_id: str):
    """
    [Subagent] Query the workspace mount path for a session.
    """
    if session_id in active_workspaces:
        return {"workspace": active_workspaces[session_id]}
    workspace_env = os.environ.get("WORKSPACE_PATH")
    if workspace_env:
        return {"workspace": workspace_env}
    return {"workspace": "/workspace"}

@router.get("/sessions/{session_id}/status")
def get_session_status(session_id: str):
    """
    [Subagent] Check if a session is ready and has an active runner connected.
    """
    meta = active_metadata.get(session_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    is_connected = session_id in active_runners
    return {
        "sessionId": session_id,
        "status": "READY" if is_connected else meta.get("status", "STANDBY"),
        "runnerConnected": is_connected,
        "sandboxId": meta.get("sandboxId"),
        "workspace": meta.get("workspace", "/workspace"),
    }
