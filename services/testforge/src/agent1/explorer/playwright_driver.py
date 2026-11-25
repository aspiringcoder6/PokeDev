"""Playwright implementation of the recorder driver protocol.

Actions supplied to TraceRecorder use high-level Playwright APIs on `driver.page`
so the synthesized spec can replay exactly what was grounded. This module only
adds read-only evidence capture: URL, ARIA snapshot, network responses, storage.
"""
from urllib.parse import urlsplit


class PlaywrightDriver:
    def __init__(self, page, actor="anonymous"):
        self.page = page
        self.actor = actor
        self._network_events = []
        self.created_resources = []
        page.on("response", self._on_response)

    def _on_response(self, response):
        self._network_events.append({
            "method": response.request.method,
            "path": urlsplit(response.url).path or "/",
            "status": response.status,
        })
        if response.request.method == "POST" and 200 <= response.status < 300:
            created_id = self._extract_created_id(response)
            if created_id is not None:
                self.created_resources.append({"path": urlsplit(response.url).path or "/", "id": created_id})

    @staticmethod
    def _extract_created_id(response):
        try:
            data = response.json()
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        inner = data.get("data") if isinstance(data.get("data"), dict) else data
        entity_id = inner.get("id") if isinstance(inner, dict) else None
        return str(entity_id) if entity_id not in (None, "") else None

    def url(self):
        return self.page.url

    def aria_snapshot(self):
        return self.page.locator("body").aria_snapshot()

    def network_events(self):
        return list(self._network_events)

    def storage_entries(self):
        try:
            origin = "{0.scheme}://{0.netloc}".format(urlsplit(self.page.url))
            items = self.page.evaluate("() => Object.fromEntries(Object.entries(localStorage))")
            return [{"origin": origin, "key": key, "value": str(value)} for key, value in items.items()]
        except Exception:
            return []
