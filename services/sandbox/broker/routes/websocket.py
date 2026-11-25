import json
import uuid
import asyncio
from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from broker.state import (
    push_event,
    active_runners,
    active_workspaces,
    active_metadata,
    pending_requests,
    LANGFLOW_SERVICE_URL,
    LANGFLOW_SERVICE_TOKEN,
    logger,
)
from broker.services.langflow import fix_encoding, trigger_langflow_and_notify

router = APIRouter()

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("New WebSocket connection established.")
    
    current_session_id: Optional[str] = None
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                
                # Check for registration
                if msg.get("type") == "register" and msg.get("role") == "executor":
                    sessionid = msg.get("sessionId") or msg.get("sessionid")
                    if not sessionid:
                        logger.warning("Executor registration rejected: missing sessionid.")
                        await websocket.send_text(json.dumps({"type": "error", "message": "sessionid is required"}))
                        continue
                    
                    current_session_id = sessionid
                    active_runners[sessionid] = websocket
                    
                    runner_id = msg.get("runnerId") or f"runner-{uuid.uuid4().hex[:8]}"
                    sandbox_id = msg.get("sandboxId") or f"sbx-{uuid.uuid4().hex[:8]}"
                    status = msg.get("status") or "READY"
                    workspace = msg.get("workspace") or "/workspace"

                    # Preserve the project workspace recorded at provision time
                    # (e.g. a VFS project name) over the runner default "/workspace".
                    existing = active_metadata.get(sessionid) or {}
                    if existing.get("workspace") and existing.get("workspace") != "/workspace":
                        workspace = existing["workspace"]
                    
                    logger.info(f"Executor registered successfully: Session={sessionid}, Runner={runner_id}, Sandbox={sandbox_id}")
                    push_event(f"[runner] session '{sessionid}' connected ({sandbox_id})")
                    
                    active_workspaces[sessionid] = workspace
                    
                    # Broker-authoritative fields: the runner's env is stringly
                    # typed (TTL="0"), so letting it merge would corrupt the
                    # int ttl written by management.py and break the reaper's
                    # no-expiry invariant (ttl<=0).
                    control_keys = {
                        "type", "role", "sessionid", "sessionId",
                        "goal", "flowid", "ttl", "createdAt",
                    }
                    runner_fields = {k: v for k, v in msg.items() if k not in control_keys}
                    
                    now_str = datetime.now(timezone.utc).isoformat()
                    
                    # Build the fields the runner provides / we derive from the message
                    runner_fields["sessionId"] = sessionid
                    runner_fields["runnerId"] = runner_id
                    runner_fields["sandboxId"] = sandbox_id
                    runner_fields["workspace"] = workspace
                    runner_fields["status"] = status
                    runner_fields["runnerConnected"] = True
                    runner_fields["lastActivity"] = now_str
                    
                    # Merge into existing placeholder written by management.py
                    # (preserves image, cpu, memory, ttl, createdAt, etc.).
                    # If no placeholder exists (e.g. runner self-registered), create fresh.
                    # BUGFIX (TestForge): runner env values are ALL strings ("ttl": "0").
                    # Overwriting typed metadata (int ttl=0 = "no expiry") with string "0"
                    # makes ttl_reaper treat it as expired immediately. Preserve the
                    # management-written typed values; only keep runner connection state.
                    for _typed_key in ("ttl", "cpu", "memory", "image", "createdAt", "project_id"):
                        runner_fields.pop(_typed_key, None)
                    if sessionid not in active_metadata:
                        runner_fields["createdAt"] = now_str
                        active_metadata[sessionid] = runner_fields
                    else:
                        active_metadata[sessionid].update(runner_fields)
                    
                    mode = active_metadata[sessionid].get("mode", "IDLE")
                    
                    await websocket.send_text(json.dumps({"type": "registered", "sessionId": sessionid}))
                    
                    goal = msg.get("goal")
                    if goal:
                        goal = fix_encoding(goal)
                    flowid = msg.get("flowid")
                    if isinstance(flowid, str):
                        flowid = flowid.strip().strip('"').strip("'")
                    
                    reminder_prompt = ""
                    if goal:
                        clean_goal = goal.replace('\r\n', ' ').replace('\n', ' ')
                        reminder_prompt = (
                            f"[GOAL] Báº¡n Ä‘ang Ä‘Æ°á»£c giao nhiá»‡m vá»¥ trÃªn mÃ¡y remote CI Runner táº¡i thÆ° má»¥c má»¥c tiÃªu `{workspace}`: {clean_goal} [/GOAL] "
                            f"[REMOTE CI RUNNER PROTOCOL - Báº®T BUá»˜C TUÃ‚N THá»¦] "
                            f"- Báº N ÄANG CHáº Y TRONG MÃ”I TRÆ¯á»œNG REMOTE CI RUNNER. "
                            f"- Cáº¢NH BÃO THÆ¯ Má»¤C Gá»C: ThÆ° má»¥c hiá»‡n táº¡i báº¡n Ä‘ang cháº¡y CLI KHÃ”NG PHáº¢I lÃ  thÆ° má»¥c cá»§a dá»± Ã¡n nÃ y vÃ  KHÃ”NG liÃªn quan gÃ¬ Ä‘áº¿n dá»± Ã¡n nÃ y. HÃ£y phá»›t lá» hoÃ n toÃ n cÃ¡c tá»‡p tin trong thÆ° má»¥c hiá»‡n táº¡i Ä‘Ã³. "
                            f"- ThÆ° má»¥c lÃ m viá»‡c má»¥c tiÃªu thá»±c táº¿ (Target Workspace) cá»§a dá»± Ã¡n báº¡n cáº§n thá»±c hiá»‡n náº±m á»Ÿ mÃ¡y remote CI Runner táº¡i Ä‘Æ°á»ng dáº«n: `{workspace}`. "
                            f"- Báº¡n Báº®T BUá»˜C pháº£i sá»­ dá»¥ng cÃ´ng cá»¥/skill `remote-ci-runner` (báº±ng cÃ¡ch cháº¡y lá»‡nh qua `remote.py`) Ä‘á»ƒ thá»±c hiá»‡n táº¥t cáº£ cÃ¡c thao tÃ¡c (Ä‘á»c, viáº¿t, tÃ¬m kiáº¿m, liá»‡t kÃª, cháº¡y lá»‡nh) trong thÆ° má»¥c má»¥c tiÃªu trÃªn mÃ¡y remote. "
                            f"[/REMOTE CI RUNNER PROTOCOL - Báº®T BUá»˜C TUÃ‚N THá»¦]"
                        )
                    
                    # Trigger Langflow Flow if goal and flowid are provided and mode is LANGFLOW
                    if mode == "LANGFLOW" and flowid and goal:
                        base_url = LANGFLOW_SERVICE_URL.rstrip('/')
                        url = f"{base_url}/api/v1/run/{flowid}?stream=false"
                        headers = {
                            "Content-Type": "application/json"
                        }
                        if LANGFLOW_SERVICE_TOKEN:
                            headers["x-api-key"] = LANGFLOW_SERVICE_TOKEN
                        
                        data_payload = {
                            "input_value": reminder_prompt,
                            "input_type": "chat",
                            "output_type": "chat",
                            "session_id": sessionid
                        }
                            
                        # Trigger Langflow Flow and notify runner when completed
                        asyncio.create_task(trigger_langflow_and_notify(sessionid, websocket, url, headers, data_payload))
                    else:
                        logger.info(f"Langflow trigger skipped (Mode: {mode}, FLOW_ID/GOAL presence: {bool(flowid)}/{bool(goal)}). Ready for manual tool execution for session: {sessionid}")
                        if goal:
                            logger.info(f"\n--- YÃŠU Cáº¦U ---\n{reminder_prompt}\n------------------------\n")
                    
                    continue
                
                # Check for action response
                if "actionResponse" in msg:
                    response_data = msg["actionResponse"]
                    # CR-05 (hardened): canonical single key "requestId". Accept
                    # legacy "requestID" from older runner binaries in-flight.
                    request_id = response_data.get("requestId") or response_data.get("requestID")
                    logger.info(f"Received response for requestId: {request_id}")
                    if request_id in pending_requests:
                        future = pending_requests[request_id]
                        if not future.done():
                            future.set_result(response_data)
                    continue
                
            except json.JSONDecodeError:
                if data == "pong":
                    logger.debug("Received pong keepalive.")
                else:
                    logger.warning(f"Failed to parse incoming WebSocket message: {data}")
                    
    except WebSocketDisconnect:
        logger.info(f"WebSocket connection disconnected. Session ID: {current_session_id}")
    finally:
        if current_session_id and current_session_id in active_runners:
            if active_runners[current_session_id] == websocket:
                active_runners.pop(current_session_id, None)
                active_workspaces.pop(current_session_id, None)
                # Update metadata to STANDBY instead of deleting it entirely.
                # The sandbox container may still be alive and the user can re-attach
                # a new runner via the dashboard "Attach" button.
                if current_session_id in active_metadata:
                    now_str = datetime.now(timezone.utc).isoformat()
                    active_metadata[current_session_id].update({
                        "status": "STANDBY",
                        "runnerConnected": False,
                        "runnerId": "none (standby)",
                        "lastActivity": now_str,
                    })
                    logger.info(f"Runner disconnected for session '{current_session_id}': metadata updated to STANDBY (container still running).")
                    push_event(f"[runner] session '{current_session_id}' disconnected -> STANDBY")
                else:
                    logger.info(f"Unregistered runner for session '{current_session_id}' (no metadata entry found).")

