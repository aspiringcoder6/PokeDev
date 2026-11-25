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
                result = Session()
                result.session_id = kwargs["session_id"]
                result.agent_preset = kwargs["agent_preset"]
                return result

        store = ReadinessStore(tmp_path / "runs.db")
        run = store.create("svc", NormalizedInput(request_id="r", project_id="p", requirement="Read"), PipelineConfig())
        runner = DshAgentRunner(
            Client(),
            store,
            Path(__file__).parents[4] / "langflow/adlc/requirement_readiness/prompts",
            None,
            {"collector": "collector"},
        )
        snapshot = {"run_id": run.id, "digest": "d"}
        assert await runner.ask("collector", snapshot, {}, "op") == await runner.ask("collector", snapshot, {}, "op")
        assert len(calls) == 1
        from langflow.adlc.requirement_readiness.agent import session_id_for

        store.begin_operation(run.id, "uncertain", "collector", session_id_for("uncertain"))
        with pytest.raises(ValueError, match="READINESS_AGENT_UNCONFIRMED"):
            await runner.ask("collector", snapshot, {}, "uncertain")
        assert len(calls) == 1

    asyncio.run(scenario())


def test_rejected_sdk_prompt_never_reuses_old_assistant_output(tmp_path):
    async def scenario():
        class Session:
            async def cursor(self):
                return 10

            async def prompt(self, text, **kwargs):
                return False

            async def history(self):
                return [
                    {
                        "type": "assistant/message",
                        "seq": 10,
                        "data": {"content": [{"type": "text", "text": '{"ok":true}'}]},
                    }
                ]

            async def wait(self):
                raise AssertionError("rejected prompt must not wait")

        class Client:
            async def create_session(self, **kwargs):
                result = Session()
                result.session_id = kwargs["session_id"]
                result.agent_preset = kwargs["agent_preset"]
                return result

        store = ReadinessStore(tmp_path / "r.db")
        run = store.create("svc", NormalizedInput(request_id="r", project_id="p", requirement="Read"), PipelineConfig())
        runner = DshAgentRunner(
            Client(),
            store,
            Path(__file__).parents[4] / "langflow/adlc/requirement_readiness/prompts",
            None,
            {"collector": "preset"},
        )
        with pytest.raises(ValueError, match="READINESS_AGENT_UNCONFIRMED"):
            await runner.ask("collector", {"run_id": run.id, "digest": "d"}, {}, "op")

    asyncio.run(scenario())


def test_real_native_command_is_requested_and_bound_through_review(tmp_path):
    import hashlib
    import json
    import subprocess
    import sys

    from langflow.adlc.requirement_readiness.models import ReviewResult
    from langflow.adlc.requirement_readiness.skills import NativeCommandRunner, SkillCatalog

    async def scenario():
        store = ReadinessStore(tmp_path / "r.db")
        run = store.create("svc", NormalizedInput(request_id="r", project_id="p", requirement="Read"), PipelineConfig())
        (tmp_path / "SKILL.md").write_text("Native fixture instructions")
        (tmp_path / "spec.md").write_text("Actual artifact")
        skill = {"entry": "SKILL.md", "sha256": hashlib.sha256((tmp_path / "SKILL.md").read_bytes()).hexdigest()}
        manifest = {
            "skills": {"specification-router": skill, "native": skill},
            "routes": {"openspec": {"skills": ["native"], "required_steps": ["check"]}},
            "commands": {
                "check": {
                    "argv": [sys.executable, "-c", "print('checked')"],
                    "version_argv": [sys.executable, "--version"],
                    "version": subprocess.check_output([sys.executable, "--version"]).decode().strip(),
                    "mode": "read-only",
                }
            },
        }
        catalog = SkillCatalog(tmp_path, manifest, store)
        prompts = []

        class Session:
            async def run(self, text):
                prompts.append(text)
                data = json.loads(text)
                if "routing_stage" in data:
                    output = {"route": "openspec", "route_reason": "existing", "status": "ready_for_spec"}
                elif "trusted_native_instructions" in data:
                    output = {
                        "type": "native_steps",
                        "steps": [{"step_name": "check", "artifact_bindings": {"spec": "spec.md"}}],
                    }
                else:
                    output = {
                        "reviewer_id": "a",
                        "snapshot_digest": "d",
                        "route": "openspec",
                        "route_reason": "existing",
                        "status": "spec_ready",
                        "artifacts": ["spec.md"],
                        "receipt_ids": data["trusted_receipt_ids"],
                    }
                return {"final_text": json.dumps(output)}

            async def history(self):
                return []

        class Client:
            async def create_session(self, **kwargs):
                result = Session()
                result.session_id = kwargs["session_id"]
                result.agent_preset = kwargs["agent_preset"]
                return result

        runner = DshAgentRunner(
            Client(),
            store,
            Path(__file__).parents[4] / "langflow/adlc/requirement_readiness/prompts",
            catalog,
            {"reviewer-a": "a"},
            native_runner=NativeCommandRunner(catalog, store, tmp_path),
        )
        snapshot = {"run_id": run.id, "digest": "d", "evidence": []}
        actual_native = runner.native_runner

        class SimulatedRestart(BaseException):
            pass

        class InterruptedNative:
            def execute(self, *args, **kwargs):
                raise SimulatedRestart()

        runner.native_runner = InterruptedNative()
        with pytest.raises(SimulatedRestart):
            await runner.ask("reviewer-a", snapshot, {}, "op")
        assert len(prompts) == 2
        runner.native_runner = actual_native
        report = ReviewResult.model_validate(await runner.ask("reviewer-a", snapshot, {}, "op"))
        assert report.status == "spec_ready"
        assert catalog.validate_receipts(report.receipt_ids, "d", ["spec.md"], "openspec", run.id)
        assert len(prompts) == 3
        assert await runner.ask("reviewer-a", snapshot, {}, "op") == report.model_dump(mode="json")
        assert len(prompts) == 3

    asyncio.run(scenario())
