"""Authenticated Harness event stream and explicit human responses."""

from __future__ import annotations

import asyncio
import json
from urllib.parse import urlsplit, urlunsplit

from .errors import DshProtocolError


class HarnessEvents:
    """Keep the remote client alive while a question is waiting for its user."""

    def __init__(self, client):
        self.client = client
        self.socket = None
        self.client_id = None

    async def __aenter__(self):
        from websockets.asyncio.client import connect

        parsed = urlsplit(self.client.base_url)
        url = urlunsplit(
            (
                "wss" if parsed.scheme == "https" else "ws",
                parsed.netloc,
                "/api/remote.mux",
                "",
                "",
            )
        )
        cookie = "; ".join(item.name + "=" + item.value for item in self.client._jar)
        self.socket = await connect(
            url,
            additional_headers={"Cookie": cookie},
            open_timeout=15,
            close_timeout=5,
            max_size=4 * 1024 * 1024,
        )
        try:
            await self.socket.send(
                json.dumps(
                    {
                        "type": "open",
                        "streamId": "human-input",
                        "endpoint": "$events",
                        "payload": {"args": {}},
                    }
                )
            )
            frame = json.loads(await asyncio.wait_for(self.socket.recv(), timeout=15))
            ready = frame.get("value") or {}
            self.client_id = ready.get("clientId")
            if not self.client_id:
                raise DshProtocolError(
                    "Harness did not establish its human input stream"
                )
            return self
        except BaseException:
            await self.socket.close()
            raise

    async def __aexit__(self, *_):
        if self.socket:
            await self.socket.close()

    async def events(self):
        async for raw in self.socket:
            frame = json.loads(raw)
            if frame.get("type") == "error":
                raise DshProtocolError("Harness human input stream stopped")
            value = frame.get("value") if frame.get("type") == "item" else frame
            if isinstance(value, dict):
                yield value

    async def answer(self, event_id, value):
        # DshClient validates the RPC acknowledgement. Its retry policy MUST be
        # one attempt: an uncertain response is reconciled, never blindly replayed.
        if not self.client_id:
            raise DshProtocolError("Harness human input stream is not connected")
        return await self.client.rpc(
            "$events/result",
            {
                "clientId": self.client_id,
                "eventId": event_id,
                "outcome": {"kind": "result", "value": value},
            },
            timeout=20,
        )
