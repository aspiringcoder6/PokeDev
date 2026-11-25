import asyncio
from pathlib import Path

import pytest

from langflow.adlc.requirement_readiness.agent import DshAgentRunner
from langflow.adlc.requirement_readiness.models import NormalizedInput, PipelineConfig
from langflow.adlc.requirement_readiness.store import ReadinessStore


def test_completed_replay_and_uncertain_call_never_resend(tmp_path):
    async def scenario():
        calls = []
        class Session:
            async def run(self, text):
                calls.append(text)
                return {"final_text": '{"read_requests":[],"rationale":"enough"}', "timeout": False}
            async def history(self):
                return []
        class Client:
            async def create_session(self, **kwargs):
                return Session()
        store = ReadinessStore(tmp_path / "runs.db")
        run = store.create("svc", NormalizedInput(request_id="r", project_id="p", requirement="Read"), PipelineConfig())
        runner = DshAgentRunner(Client(), store, Path(__file__).parents[4] / "langflow/adlc/requirement_readiness/prompts",
                                None, {"collector": "collector"})
        snapshot = {"run_id": run.id, "digest": "d"}
        assert await runner.ask("collector", snapshot, {}, "op") == await runner.ask("collector", snapshot, {}, "op")
        assert len(calls) == 1
        from langflow.adlc.requirement_readiness.agent import session_id_for
        store.begin_operation(run.id, "uncertain", "collector", session_id_for("uncertain"))
        with pytest.raises(ValueError, match="READINESS_AGENT_UNCONFIRMED"):
            await runner.ask("collector", snapshot, {}, "uncertain")
        assert len(calls) == 1
    asyncio.run(scenario())
