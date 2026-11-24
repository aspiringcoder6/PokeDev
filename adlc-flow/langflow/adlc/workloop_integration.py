"""Read the existing Workloop/Slack connection without creating a second bot."""
import asyncio
from datetime import datetime, timezone
import json
import os
from urllib.parse import urlencode, urlsplit

import httpx


def checked_url(value):
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("WORKLOOP_CONNECTION_URL_INVALID")
    return value.rstrip("/")


def bot_link(app_id, team_id=""):
    import re
    if not re.fullmatch(r"A[A-Z0-9]{5,30}", app_id):
        return None
    query = {"app": app_id}
    if team_id and re.fullmatch(r"T[A-Z0-9]{5,30}", team_id):
        query["team"] = team_id
    return "https://slack.com/app_redirect?" + urlencode(query)


class WorkloopIntegration:
    def __init__(self):
        # Only server configuration chooses these targets; no URL is accepted from API callers.
        self.base = checked_url(os.environ.get("VAI_WORKLOOP_URL", "http://10.0.10.195:8903"))
        self.mcp_url = checked_url(os.environ.get("VAI_WORKLOOP_MCP_URL", "http://10.0.10.195:8107/mcp"))

    async def health(self):
        async with httpx.AsyncClient(timeout=8, trust_env=False, follow_redirects=False) as client:
            response = await client.get(self.base + "/api/v1/webhooks/health")
            response.raise_for_status()
            if len(response.content) > 128000:
                raise ValueError("WORKLOOP_RESPONSE_TOO_LARGE")
            body = response.json()
            if body.get("ok") is not True:
                raise ValueError("WORKLOOP_UNAVAILABLE")
            return {"connector_connected": body.get("connector") is True}

    async def mcp(self):
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async with streamablehttp_client(self.mcp_url) as (read, write, _):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                listed = await session.list_tools()
                names = {tool.name for tool in listed.tools}
                server = {"name": initialized.serverInfo.name[:100], "version": initialized.serverInfo.version[:40]}
                if "integration_webhook_list" not in names:
                    return {"server": server, "registered": None, "registry_error": True}
                result = await session.call_tool("integration_webhook_list", {})
                if result.isError:
                    return {"server": server, "registered": None, "registry_error": True}
                body = result.structuredContent
                if not body:
                    text = "\n".join(item.text for item in result.content if item.type == "text")
                    if len(text) > 128000:
                        raise ValueError("WORKLOOP_RESPONSE_TOO_LARGE")
                    body = json.loads(text)
                entries = body.get("integrations")
                if not isinstance(entries, list):
                    return {"server": server, "registered": None, "registry_error": True}
                # Do not forward credential masks, event payloads or conversations to the browser.
                return {"server": server, "registered": any(item.get("source") == "slack" for item in entries), "registry_error": False}

    async def inspect(self):
        health, mcp = await asyncio.gather(
            asyncio.wait_for(self.health(), timeout=10),
            asyncio.wait_for(self.mcp(), timeout=15),
            return_exceptions=True,
        )
        health_ok, mcp_ok = isinstance(health, dict), isinstance(mcp, dict)
        errors = ([] if health_ok else ["workloop"]) + ([] if mcp_ok else ["mcp"])
        if mcp_ok and mcp.get("registry_error"):
            errors.append("slack_registry")
        app_id = os.environ.get("VAI_SLACK_APP_ID", "A0CA54Q7FV3")
        team_id = os.environ.get("VAI_SLACK_TEAM_ID", "")
        return {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "workloop": {"available": health_ok, "url": self.base, "integration_url": self.base + "/integration"},
            "mcp": {"available": mcp_ok, "url": self.mcp_url, "server": mcp.get("server") if mcp_ok else None},
            "slack": {
                "registered": mcp.get("registered") if mcp_ok else None,
                "connector_connected": health.get("connector_connected") if health_ok else None,
                "bot_response_status": "unverified",
                "app_id": app_id if bot_link(app_id) else None,
                "bot_url": bot_link(app_id, team_id),
                "workspace_url": "https://adlcfactory.slack.com/",
                "scope": "conversation_and_spec",
            },
            "errors": errors,
        }
