import asyncio

import pytest

from langflow.adlc.requirement_readiness.collection import CollectionEngine, SourceReadBroker
from langflow.adlc.requirement_readiness.models import NormalizedInput, PipelineConfig
from langflow.adlc.requirement_readiness.store import ReadinessStore
from langflow.adlc.source_access import SourceGateway, SourceGrant, SourceRef, make_evidence


def grant(run):
    return SourceGrant(project_id="p", run_id=run.id, principal_id="svc", resources={"gh": {"org/repo"}})


@pytest.mark.parametrize(
    "limit,verdicts,want,status",
    [
        (3, [True], 1, "context_ready"),
        (3, [False, False, True], 3, "context_ready"),
        (3, [False] * 3, 3, "needs_context"),
        (1, [False], 1, "needs_context"),
        (5, [False] * 4 + [True], 5, "context_ready"),
    ],
)
def test_rounds_include_first_and_never_create_extra_round(tmp_path, limit, verdicts, want, status):
    async def scenario():
        store = ReadinessStore(tmp_path / "r.db")
        run = store.create(
            "svc",
            NormalizedInput(request_id="r", project_id="p", requirement="Read"),
            PipelineConfig(max_context_rounds=limit),
        )
        calls = []

        class Agents:
            async def ask(self, role, snapshot, payload, operation_id):
                calls.append(role)
                if role == "collector":
                    return {"read_requests": [], "rationale": "none"}
                return {"sufficient": verdicts[calls.count("context-verifier") - 1]}

        engine = CollectionEngine(Agents(), SourceGateway({}), store, grant_resolver=grant)
        result = await engine.advance(run, grant(run))
        assert result.round_count == want
        assert result.status == status
        assert calls.count("collector") == calls.count("context-verifier") == want

    asyncio.run(scenario())


def test_broker_budget_pinning_and_restart_reuse(tmp_path):
    async def scenario():
        ref = SourceRef(kind="github_file", connection_id="gh", resource_id="org/repo", locator={"path": "a"})
        calls = []

        class Gateway:
            async def resolve_revision(self, scope, requested):
                return requested.model_copy(update={"revision": "a" * 40})

            async def read(self, scope, refs):
                calls.extend(refs)
                return [make_evidence(r, "body", "v") for r in refs]

        store = ReadinessStore(tmp_path / "r.db")
        run = store.create(
            "svc", NormalizedInput(request_id="r", project_id="p", requirement="Read"), PipelineConfig(max_tool_calls=1)
        )
        broker = SourceReadBroker(Gateway(), store, grant)
        first = await broker.read(run.id, "read1", [ref])
        assert first == await broker.read(run.id, "read1", [ref])
        assert len(calls) == 1
        assert calls[0].revision == "a" * 40
        with pytest.raises(ValueError, match="SOURCE_READ_LIMIT"):
            await broker.read(run.id, "read2", [ref])
        assert store.load(run.id).tool_calls == 1

    asyncio.run(scenario())


def test_restart_after_insufficient_verdict_resumes_remaining_round(runtime):
    async def scenario():
        s, store = runtime.service, runtime.store
        request = NormalizedInput(request_id="restart", project_id="p", requirement="Assess")
        run = s.start(runtime.principal, request)
        original_ask = runtime.agents.ask
        verdicts = iter([False, True])

        async def ask(role, *args):
            if role == "context-verifier":
                runtime.agents.calls.append((role, *args))
                return {"sufficient": next(verdicts)}
            return await original_ask(role, *args)

        runtime.agents.ask = ask
        original_update = store.update

        class ProcessRestart(BaseException):
            pass

        def update(identity, revision, changes):
            result = original_update(identity, revision, changes)
            if changes.get("verdict") is not None and not changes["verdict"].sufficient:
                raise ProcessRestart()
            return result

        store.update = update
        with pytest.raises(ProcessRestart):
            await s.collection.advance(run, grant(run))
        assert store.load(run.id).status == "created"
        assert store.load(run.id).round_count == 1
        store.update = original_update
        resumed = await s.collection.advance(store.load(run.id), grant(run))
        assert resumed.status == "context_ready"
        assert resumed.round_count == 2

    asyncio.run(scenario())
