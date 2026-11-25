import importlib.util
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


def route_module():
    path = Path(__file__).parents[4] / "langflow/api/v1/adlc_requirement_readiness.py"
    spec = importlib.util.spec_from_file_location("readiness_api_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_service_auth_and_three_stage_handoff_endpoint(runtime):
    module = route_module()
    app = FastAPI()
    app.state.readiness_service = runtime.service
    app.include_router(module.router, prefix="/api/v1")
    with TestClient(app) as client:
        url = "/api/v1/adlc/requirement-readiness/runs"
        body = {"request_id": "r", "project_id": "p", "requirement": "Assess"}
        assert client.post(url, json=body).status_code == 401
        app.dependency_overrides[module.authenticate] = lambda: runtime.principal
        response = client.post(url, json=body)
        assert response.status_code == 202
        assert set(response.json()) <= {"id", "status", "revision"}
        identity = response.json()["id"]
        import asyncio

        from test_service import drive

        asyncio.run(drive(runtime.service, runtime.store.load(identity)))
        handoff = client.get(url + f"/{identity}/handoff")
        assert handoff.status_code == 200
        assert handoff.json()["decision"]["selected_option_id"] == "a"


def test_idle_lifespan_worker_wakes_from_http_without_manual_ticks(runtime):
    import asyncio
    import time
    from contextlib import asynccontextmanager

    module = route_module()

    @asynccontextmanager
    async def life(app):
        asyncio.get_running_loop().set_debug(True)
        await runtime.service.start_worker()
        try:
            yield
        finally:
            await runtime.service.close()

    app = FastAPI(lifespan=life)
    app.state.readiness_service = runtime.service
    app.dependency_overrides[module.authenticate] = lambda: runtime.principal
    app.include_router(module.router, prefix="/api/v1")
    with TestClient(app) as client:
        base = "/api/v1/adlc/requirement-readiness/runs"
        response = client.post(base, json={"request_id": "worker", "project_id": "p", "requirement": "Assess"})
        assert response.status_code == 202
        identity = response.json()["id"]
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            result = client.get(base + f"/{identity}/handoff")
            if result.status_code == 200:
                break
            time.sleep(0.01)
        assert result.status_code == 200
