import importlib.util
from pathlib import Path

import httpx
import pytest


def load_configure():
    path = Path(__file__).resolve().parents[4] / "deploy/local-recovery/configure.py"
    spec = importlib.util.spec_from_file_location("local_recovery_configure", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_startup_waits_for_new_token_to_authenticate(monkeypatch):
    module = load_configure()
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    logs = iter(["old boot ?token=stale", "old boot ?token=stale\nnew boot ?token=current"])
    visited = []

    def handle(request):
        token = request.url.params["token"]
        visited.append(token)
        if token == "stale":
            return httpx.Response(401)
        return httpx.Response(303, headers={"set-cookie": "dsh-auth-local=verified; Path=/; HttpOnly", "location": "/"})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        token = module.ready_harness_token(client, lambda: next(logs), attempts=2)
    assert token == "current"
    assert visited == ["stale", "current"]


def test_successful_page_without_auth_cookie_is_not_ready(monkeypatch):
    module = load_configure()
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200))) as client:
        with pytest.raises(RuntimeError, match="authenticate"):
            module.ready_harness_token(client, lambda: "?token=stale", attempts=1)
