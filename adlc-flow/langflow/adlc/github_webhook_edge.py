"""Webhook-only edge for a local HTTPS tunnel. Never proxies UI, auth or broker APIs."""

# ruff: noqa: EM101, PLR2004 - fixed ingress limits and public error codes.
import hashlib
import hmac
import os

import httpx
from fastapi import FastAPI, HTTPException, Request, Response


def create_edge(secret, *, transport=None):
    if not isinstance(secret, str) or len(secret.encode()) < 32:
        raise ValueError("WEBHOOK_SECRET_REQUIRED")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/webhooks/github/issues")
    async def receive(request: Request):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 65536:
                raise HTTPException(413, {"code": "WEBHOOK_REQUEST_TOO_LARGE"})
        expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(request.headers.get("X-Hub-Signature-256", ""), expected):
            raise HTTPException(401, {"code": "WEBHOOK_UNAUTHENTICATED"})
        if request.headers.get("X-GitHub-Event") not in {"issues", "ping"}:
            raise HTTPException(403, {"code": "WEBHOOK_EVENT_DENIED"})
        headers = {
            key: request.headers[key]
            for key in ("X-Hub-Signature-256", "X-GitHub-Event", "X-GitHub-Delivery")
            if key in request.headers
        }
        headers["Content-Type"] = "application/json"
        try:
            async with httpx.AsyncClient(
                trust_env=False, follow_redirects=False, timeout=15, transport=transport
            ) as client:
                response = await client.post(
                    "http://127.0.0.1:7860/api/v1/adlc/harness-demo/github/webhook", content=bytes(raw), headers=headers
                )
            if len(response.content) > 8192:
                raise HTTPException(502, {"code": "WEBHOOK_RESPONSE_INVALID"})
            return Response(response.content, status_code=response.status_code, media_type="application/json")
        except httpx.HTTPError:
            # Unknown acknowledgements are never retried by this edge.
            raise HTTPException(502, {"code": "WEBHOOK_UPSTREAM_UNCONFIRMED"}) from None

    return app


def create_app():
    return create_edge(os.getenv("ADLC_DEMO_GITHUB_WEBHOOK_SECRET"))
