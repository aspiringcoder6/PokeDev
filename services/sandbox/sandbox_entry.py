"""Local deployment wrapper: protect upstream unauthenticated execution/control routes."""
import hmac
import os

from broker import auth
from fastapi.responses import JSONResponse

auth.AUTH_DB_PATH = "/app/broker-state/auth.db"

from broker.broker import app  # noqa: E402

TOKEN = os.environ.get("ADLC_SANDBOX_BROKER_TOKEN", "")
if len(TOKEN.encode()) < 32:
    raise RuntimeError("ADLC_SANDBOX_BROKER_TOKEN must be independently configured")


@app.middleware("http")
async def protect_control_plane(request, call_next):
    if request.url.path.startswith("/api/"):
        bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
        if not hmac.compare_digest(bearer.encode(), TOKEN.encode()):
            return JSONResponse({"error": "BROKER_AUTHENTICATION_REQUIRED"}, 401)
    return await call_next(request)
