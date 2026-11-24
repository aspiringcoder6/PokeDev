"""Small authenticated client for Harness's sealed, tool-free planning plugin."""

import json
import os
from http import HTTPStatus

import httpx
from pydantic import Field

from langflow.adlc import delivery as d
from langflow.adlc.harness_client import HarnessServerSettings
from langflow.adlc.task_loop_harness import TOKEN_ENV, _closed_object, _nonfinite
from langflow.adlc.task_loop_models import LoopModel
from langflow.adlc.task_loop_runtime_v2 import LoopRuntimeUsageV2

ROOT = "/api/v1/adlc-harness-plans"
ROUTE = {"provider": "my-codex", "model": "cx/gpt-5.6-luna", "tools_disabled": True}
MIN_TOKEN_BYTES = 32
MAX_RESPONSE_BYTES = 524_288


class PlanningRead(LoopModel):
    generation_id: str
    request_digest: d.Digest
    route: dict
    state: str
    proposal_text: str | None = Field(default=None, max_length=131_072)
    usage: LoopRuntimeUsageV2 | None = None
    error_code: str | None = None
    released: bool


class HarnessPlanningClient:
    def __init__(self, settings=None, *, transport=None, plugin_digest=None):
        from langflow.adlc.cycle_planning_release import PLUGIN_DIGEST

        if settings is None:
            base = HarnessServerSettings.from_environment()
            settings = HarnessServerSettings(
                base_url=base.base_url, api_token=os.getenv(TOKEN_ENV), allow_insecure_http=base.allow_insecure_http
            )
        settings.validate()
        if not settings.api_token or len(settings.api_token.encode()) < MIN_TOKEN_BYTES:
            d.fail("CYCLE_PLANNER_NOT_CONFIGURED", 503)
        self.plugin_digest = plugin_digest or PLUGIN_DIGEST
        self.client = httpx.AsyncClient(
            base_url=settings.base_url.rstrip("/"),
            transport=transport,
            timeout=15,
            follow_redirects=False,
            headers={"authorization": f"Bearer {settings.api_token}"},
        )

    async def aclose(self):
        await self.client.aclose()

    async def request(self, method, path, **kwargs):
        try:
            async with self.client.stream(method, ROOT + path, **kwargs) as response:
                if not HTTPStatus.OK <= response.status_code < HTTPStatus.MULTIPLE_CHOICES:
                    d.fail("CYCLE_PLANNER_UNAVAILABLE", 503)
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        d.fail("CYCLE_PLANNER_RESPONSE_INVALID", 502)
                    chunks.append(chunk)
            return json.loads(b"".join(chunks), object_pairs_hook=_closed_object, parse_constant=_nonfinite)
        except (httpx.TransportError, ValueError, RecursionError) as exc:
            raise d.HTTPException(503, {"code": "CYCLE_PLANNER_UNAVAILABLE"}) from exc

    async def readiness(self):
        value = await self.request("GET", "/health")
        if (
            value.get("ready") is not True
            or value.get("route") != ROUTE
            or value.get("plugin_digest") != self.plugin_digest
        ):
            d.fail("CYCLE_PLANNER_RELEASE_MISMATCH", 503)

    async def create(self, command):
        # Exactly one POST; never retry a possibly acknowledged paid generation.
        return self.checked(await self.request("POST", "/generations", json=command), command)

    async def observe(self, command):
        return self.checked(
            await self.request(
                "GET", f"/generations/{command['generation_id']}", params={"request_digest": command["request_digest"]}
            ),
            command,
        )

    @staticmethod
    def checked(raw, command):
        value = PlanningRead.model_validate(raw)
        if (
            value.generation_id != command["generation_id"]
            or value.request_digest != command["request_digest"]
            or value.route != ROUTE
            or value.state not in {"RESERVED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED", "UNCONFIRMED"}
            or (
                value.state == "COMPLETED"
                and (not value.proposal_text or not value.released or value.error_code or not value.usage)
            )
        ):
            d.fail("CYCLE_PLANNER_RESPONSE_INVALID", 502)
        return value


def planner_client():
    if os.getenv("ADLC_CYCLE_PLANNING_ENABLED", "").lower() not in {"true", "1", "yes", "on"}:
        d.fail("CYCLE_PLANNER_DISABLED", 503)
    return HarnessPlanningClient()
