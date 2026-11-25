import datetime
import os
import sys

# Ensure root directory is in sys.path and broker directory is removed from sys.path[0] to prevent module collision with broker.py
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
broker_dir = os.path.dirname(os.path.abspath(__file__))
if broker_dir in sys.path:
    sys.path.remove(broker_dir)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

from broker import auth

# Load environment variables from .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class RegisterPayload(BaseModel):
    email: str
    password: str


class LoginPayload(BaseModel):
    email: str
    password: str


class VerifyPayload(BaseModel):
    email: str
    code: str

from broker.routes import management, agent, execution, debug, websocket, vfs

app = FastAPI(
    title="OpenSandbox Kit Standalone Broker",
    description="Role-separated Remote Execution Broker for AI Orchestrators & Subagents",
    version="1.0.0"
)

# Include role-separated APIRouters
app.include_router(management.router)
app.include_router(agent.router)
app.include_router(execution.router)
app.include_router(debug.router)
app.include_router(websocket.router)
app.include_router(vfs.router)

# Resolve the sandbox provider eagerly so SANDBOX_PROVIDER problems (e.g.
# legacy "docker", whose support was removed) surface in the log at boot
# instead of on the first request.
from broker.services.runtime import get_provider as _get_provider
_get_provider()

# Mount Dashboard Static files & route
dashboard_static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard", "static")
if os.path.exists(dashboard_static_dir):
    app.mount("/static", StaticFiles(directory=dashboard_static_dir), name="static")

@app.get("/health")
def health_check():
    """Lightweight health endpoint for load balancers (HAProxy httpchk)."""
    return {"status": "ok"}


@app.get("/dashboard")
def get_dashboard():
    index_file = os.path.join(dashboard_static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"status": "ok", "message": "Dashboard UI under construction"}


@app.get("/guides")
def get_guides():
    """Usage guide page, styled after OpenSandbox docs (VitePress-like layout)."""
    guides_file = os.path.join(dashboard_static_dir, "guides.html")
    if os.path.exists(guides_file):
        return FileResponse(guides_file)
    return {"status": "error", "message": "Guides page not found"}


@app.get("/sandbox/{name}")
async def get_sandbox_workspace(name: str):
    """Sandbox Manager UI scoped to a specific workspace: /sandbox/<name>.
    Unknown workspace names are redirected to the first existing one.
    The SPA reads the workspace name from the URL on boot."""
    import httpx
    from fastapi.responses import RedirectResponse

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get("http://127.0.0.1:8001/api/vfs/workspaces")
            workspaces = res.json().get("workspaces", [])
    except Exception:
        workspaces = []

    if workspaces and name not in workspaces:
        return RedirectResponse(url=f"/sandbox/{workspaces[0]}")

    index_file = os.path.join(dashboard_static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"status": "ok", "message": "Dashboard UI under construction"}

@app.get("/legacy")
def get_legacy_dashboard():
    legacy_file = os.path.join(dashboard_static_dir, "legacy.html")
    if os.path.exists(legacy_file):
        return FileResponse(legacy_file)
    return {"status": "error", "message": "Legacy dashboard not found"}


# --- Authentication (Phase 1: register / login / me) ---

@app.post("/auth/register")
def auth_register(payload: RegisterPayload):
    ok, message, user = auth.register_user(payload.email, payload.password)
    if not ok:
        return {"success": False, "error": message}
    return {"success": True, "message": message, "email": user["email"], "role": user["role"], "pendingVerification": True}


@app.post("/auth/verify")
def auth_verify(payload: VerifyPayload):
    ok, message, user = auth.verify_code(payload.email, payload.code)
    if not ok or not user:
        return {"success": False, "error": message}
    token = auth.issue_token(user["email"], user["role"])
    return {"success": True, "message": message, "token": token, "email": user["email"], "role": user["role"]}


@app.post("/auth/resend")
def auth_resend(payload: RegisterPayload):
    """Re-send the verification code for an existing unverified account."""
    email = payload.email.strip().lower()
    if not auth.is_verified(email):
        sent, message = auth.issue_verification_code(email)
        if sent:
            return {"success": True, "message": "Code sent to your email."}
        return {"success": False, "error": message}
    return {"success": False, "error": "Email already verified — just log in."}


@app.post("/auth/login")
def auth_login(payload: LoginPayload):
    email = payload.email.strip().lower()
    if not auth.is_verified(email):
        return {"success": False, "error": "Email not verified. Check your inbox for the code.", "pendingVerification": True}
    user = auth.verify_user(email, payload.password)
    if not user:
        return {"success": False, "error": "Invalid email or password."}
    token = auth.issue_token(user["email"], user["role"])
    return {"success": True, "token": token, "email": user["email"], "role": user["role"]}


@app.get("/auth/me")
def auth_me(token: Optional[str] = None):
    user = auth.verify_token(token or "")
    if not user:
        return {"success": False, "error": "Not authenticated."}
    return {"success": True, **user}


@app.get("/auth/bootstrap-status")
def auth_bootstrap_status():
    """True when no user exists yet — the first registrant becomes admin."""
    return {"success": True, "hasUsers": auth.user_count() > 0}


# --- GitHub OAuth (fallback login when SMTP is not configured) ---

import secrets as _secrets
import time as _time
from urllib.parse import quote as _urlquote
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse

_github_states: dict = {}


@app.get("/auth/github/status")
def auth_github_status():
    return {"success": True, "enabled": bool(os.environ.get("GITHUB_CLIENT_ID"))}


@app.get("/auth/github/start")
def auth_github_start():
    client_id = os.environ.get("GITHUB_CLIENT_ID")
    if not client_id:
        return JSONResponse({"success": False, "error": "GitHub OAuth is not configured (set GITHUB_CLIENT_ID/SECRET)."}, status_code=400)
    state = _secrets.token_urlsafe(16)
    _github_states[state] = time.time() + 600
    redirect_uri = os.environ.get("GITHUB_REDIRECT_URI", "http://localhost:8000/auth/github/callback")
    authorize = (
        "https://github.com/login/oauth/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={_urlquote(redirect_uri, safe='')}"
        "&scope=read:user%20user:email"
        f"&state={state}"
    )
    return RedirectResponse(authorize)


@app.get("/auth/github/callback")
async def auth_github_callback(code: str = "", state: str = ""):
    client_id = os.environ.get("GITHUB_CLIENT_ID")
    client_secret = os.environ.get("GITHUB_CLIENT_SECRET")
    redirect_uri = os.environ.get("GITHUB_REDIRECT_URI", "http://localhost:8000/auth/github/callback")

    error_page = lambda msg: HTMLResponse(
        f"<html><body style='background:#1e1f22;color:#ced0d6;font-family:sans-serif;text-align:center;padding-top:60px'>"
        f"<h2>GitHub login failed</h2><p>{msg}</p>"
        f"<a href='/dashboard' style='color:#5594fa'>Back to login</a></body></html>"
    )

    stored = _github_states.pop(state, None)
    if not code or not stored or stored < _time.time():
        return error_page("Invalid or expired OAuth state.")

    import httpx
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            token_res = await client.post(
                "https://github.com/login/oauth/access_token",
                json={"client_id": client_id, "client_secret": client_secret, "code": code, "redirect_uri": redirect_uri},
                headers={"Accept": "application/json"},
            )
            access_token = (token_res.json() or {}).get("access_token")
            if not access_token:
                return error_page("Could not exchange the OAuth code for a token.")

            headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"}
            gh_user = (await client.get("https://api.github.com/user", headers=headers)).json()
            gh_emails = (await client.get("https://api.github.com/user/emails", headers=headers)).json()

        primary = next((e for e in gh_user if e.get("primary") and e.get("verified")), None)
        email = (primary or {}).get("email") or gh_user.get("email")
        if not email:
            return error_page("Your GitHub account has no verified public email.")

        # Domain / org policy: vmail email always allowed; otherwise require
        # GITHUB_ORG membership when configured.
        gh_login = gh_user.get("login", "")
        org = os.environ.get("GITHUB_ORG")
        if not email.endswith(auth.ALLOWED_EMAIL_DOMAIN) and org:
            async with httpx.AsyncClient(timeout=20.0) as client:
                member = await client.get(
                    f"https://api.github.com/orgs/{org}/members/{gh_login}",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            if member.status_code != 204:
                return error_page(f"GitHub account '{gh_login}' is not a member of org '{org}'.")

        user = auth.upsert_external_user(email)
        token = auth.issue_token(user["email"], user["role"])
        push_event(f"[auth] github login '{gh_login}' -> {user['email']} ({user['role']})")
        return RedirectResponse(
            f"/dashboard#vai_token={token}&vai_email={_urlquote(user['email'])}&vai_role={user['role']}"
        )
    except Exception as e:
        return error_page(str(e))


# --- TTL Reaper: terminate sandboxes whose TTL has expired ---
def _is_session_expired(meta: dict, now: "datetime.datetime") -> bool:
    """Decide whether a session's sandbox should be reaped.

    PAUSED sessions are never expired (frozen by the runtime). An explicit
    `expiresAt` (stamped by renew/resume) takes precedence; naive datetimes
    are normalized to UTC. Falls back to createdAt + ttl, where ttl <= 0 or
    unparsable values mean "no expiry". Unparsable dates never expire
    (fail-safe).
    """
    if (meta.get("status") or "").upper() == "PAUSED":
        return False
    expires_at_raw = meta.get("expiresAt")
    if expires_at_raw:
        try:
            expires_dt = datetime.datetime.fromisoformat(str(expires_at_raw))
        except (ValueError, TypeError):
            return False
        if expires_dt.tzinfo is None:
            expires_dt = expires_dt.replace(tzinfo=datetime.timezone.utc)
        return now > expires_dt
    created = meta.get("createdAt")
    if not created:
        return False
    try:
        ttl_val = float(meta.get("ttl"))
    except (ValueError, TypeError):
        return False
    if ttl_val <= 0:
        return False
    try:
        created_dt = datetime.datetime.fromisoformat(created)
    except (ValueError, TypeError):
        return False
    if created_dt.tzinfo is None:
        created_dt = created_dt.replace(tzinfo=datetime.timezone.utc)
    return (now - created_dt).total_seconds() > ttl_val


async def ttl_reaper():
    import asyncio
    from broker.state import push_event, active_metadata, active_runners, logger
    from broker.services.runtime import get_provider

    while True:
        try:
            now = datetime.datetime.now(datetime.timezone.utc)
            for session_id, meta in list(active_metadata.items()):
                if not _is_session_expired(meta, now):
                    continue
                logger.info(f"[TTL Reaper] Session '{session_id}' expired, terminating sandbox")
                push_event(f"[ttl-reaper] session '{session_id}' expired and destroyed")
                sandbox_id = meta.get("sandboxId")
                if sandbox_id:
                    get_provider().terminate_sandbox(sandbox_id)
                ws = active_runners.pop(session_id, None)
                if ws:
                    try:
                        await ws.close()
                    except Exception:
                        pass
                active_metadata.pop(session_id, None)
        except Exception as e:
            logger.error(f"[TTL Reaper] Error: {e}")
        await asyncio.sleep(30)


@app.on_event("startup")
async def startup_ttl_reaper():
    import asyncio
    asyncio.create_task(ttl_reaper())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("broker.broker:app", host="0.0.0.0", port=8000, reload=False, ws_max_size=33_554_432)
