import asyncio
import json
import os
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional
from fastapi import WebSocket
from pydantic import BaseModel

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Broker")

# Environment configurations for Langflow
LANGFLOW_SERVICE_URL = os.environ.get("LANGFLOW_SERVICE_URL", "http://localhost:7860")
LANGFLOW_SERVICE_TOKEN = os.environ.get("LANGFLOW_SERVICE_TOKEN", "")

# Default sandbox image / entrypoint (env-overridable; read at import time)
DEFAULT_SANDBOX_IMAGE = os.environ.get("SANDBOX_DEFAULT_IMAGE", "ubuntu:latest")


def _parse_default_entrypoint() -> Optional[List[str]]:
    """Parse SANDBOX_DEFAULT_ENTRYPOINT (a JSON list string, e.g.
    '["/usr/local/bin/entrypoint.sh"]'). Returns None when unset, invalid
    JSON, or not a JSON list."""
    raw = os.environ.get("SANDBOX_DEFAULT_ENTRYPOINT")
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    return parsed if isinstance(parsed, list) else None


DEFAULT_SANDBOX_ENTRYPOINT = _parse_default_entrypoint()


def _parse_default_extensions() -> Optional[Dict[str, str]]:
    """Parse SANDBOX_DEFAULT_EXTENSIONS (a JSON object string, e.g.
    '{"bootstrap.execd.isolation": "enable"}'). Returns None when unset,
    invalid JSON, or not a JSON object."""
    raw = os.environ.get("SANDBOX_DEFAULT_EXTENSIONS")
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    return {str(k): str(v) for k, v in parsed.items()}


DEFAULT_SANDBOX_EXTENSIONS = _parse_default_extensions()

# Shared in-memory registry state
active_runners: Dict[str, WebSocket] = {}
active_workspaces: Dict[str, str] = {}
active_metadata: Dict[str, dict] = {}

# Outstanding requests: request_id -> asyncio.Future
pending_requests: Dict[str, asyncio.Future] = {}

# Ring buffer of broker events shown in the dashboard Command Console
event_log: deque = deque(maxlen=300)


def push_event(message: str) -> None:
    """Append a timestamped event to the console feed (thread-safe enough for asyncio use)."""
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    event_log.append(f"[{ts}] {message}")

# Pydantic Request Models
class ExecutePayload(BaseModel):
    action: dict
    session_id: str

class CreateSessionPayload(BaseModel):
    session_id: Optional[str] = None
    project_path: Optional[str] = None
    image: Optional[str] = DEFAULT_SANDBOX_IMAGE
    cpu: Optional[str] = "2"
    memory: Optional[str] = "4Gi"
    ttl: Optional[int] = 3600
    create_sandbox_only: Optional[bool] = False
    entrypoint: Optional[List[str]] = None
    extensions: Optional[Dict[str, str]] = None

class LaunchRequest(BaseModel):
    project_path: Optional[str] = "/home/ntkien/sandbox-kit"
    session_id: Optional[str] = None
    image: Optional[str] = DEFAULT_SANDBOX_IMAGE
    ttl: Optional[int] = 3600
    create_sandbox_only: Optional[bool] = False
    entrypoint: Optional[List[str]] = None
    extensions: Optional[Dict[str, str]] = None

class RegisterStandbyRequest(BaseModel):
    session_id: str
    sandbox_id: str
    project_path: str
    image: str = DEFAULT_SANDBOX_IMAGE
    ttl: int = 3600

class AttachRunnerRequest(BaseModel):
    session_id: str
    sandbox_id: str
    project_path: Optional[str] = "/home/ntkien/sandbox-kit"
