import pytest

from langflow.adlc.requirement_readiness.models import NormalizedInput, PipelineConfig
from langflow.adlc.requirement_readiness.store import ReadinessStore


def test_restart_idempotency_revision_and_ownership(tmp_path):
    path = tmp_path / "runs.sqlite"
    store = ReadinessStore(path)
    request = NormalizedInput(request_id="q", project_id="p", requirement="Read inputs")
    run = store.create("svc", request, PipelineConfig())
    assert store.create("svc", request, PipelineConfig()).id == run.id
    updated = store.update(run.id, run.revision, {"round_count": 2})
    with pytest.raises(ValueError, match="READINESS_REVISION_CONFLICT"):
        store.update(run.id, run.revision, {"round_count": 0})
    assert ReadinessStore(path).load(run.id, "svc").round_count == 2
    with pytest.raises(ValueError, match="READINESS_NOT_FOUND"):
        store.load(run.id, "other")
    with pytest.raises(ValueError, match="READINESS_IDEMPOTENCY_CONFLICT"):
        store.create("svc", request.model_copy(update={"requirement": "changed"}), PipelineConfig())
    assert store.begin_operation(run.id, "op", "collector", "session").is_new
    assert not store.begin_operation(run.id, "op", "collector", "session").is_new
    store.finish_operation("op", {"ok": True})
    assert store.observe_operation("op").result == {"ok": True}
    assert updated.revision == 1
