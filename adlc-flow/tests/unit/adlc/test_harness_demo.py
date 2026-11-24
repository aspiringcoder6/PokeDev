"""Offline model fixtures, real Git; optional actual Docker reproduction, never paid calls."""
# ruff: noqa: S101, PLR2004, INP001

import hashlib
from uuid import uuid4

import pytest

from langflow.adlc.harness_demo import HarnessDemoService
from langflow.adlc.harness_demo_models import DEMO_DIR, REQUIREMENT, SOURCE_PATH, DemoError, ToolCommand, digest
from langflow.adlc.harness_demo_sandbox import DockerDemoSandbox

FIX = """def paginate(items, page, size):
    if type(page) is not int or type(size) is not int or page < 1 or size < 1:
        raise ValueError('page and size must be positive integers')
    offset = (page - 1) * size
    return items[offset:offset + size]
"""
PLAN = {
    "objective": "Fix one-based pagination",
    "task_id": "pagination",
    "assignee": "harness-coding-agent",
    "steps": ["Use skill and memory", "Write brief", "Edit source and self-check", "Independent Verify and handoff"],
    "writable_paths": ["app.py"],
    "acceptance": "four-protected-pagination-tests",
}
BRIEF = {
    "task_id": "pagination",
    "approach": "Validate integer values and slice by offset",
    "steps": ["Read", "Edit", "Check"],
    "risks": ["bool is int"],
}
REPORT = {
    "summary": "Pagination source corrected; refer to separate reproduction receipt.",
    "changes": ["Input validation", "One-based offset"],
    "limitations": ["Four frozen checks only; not all Vanguard tests"],
}


class FixtureSandbox:
    """Explicit unit fixture; the production service never falls back to this."""

    async def health(self):
        return {"backend": "TEST_FIXTURE"}

    async def run(self, directory, operation, *, content=None):
        path = directory / "app.py"
        if operation == "write":
            path.write_bytes(content.encode())
        receipt = {
            "operation": operation,
            "container_name": "TEST_FIXTURE_NO_CONTAINER",
            "image_id": "TEST_FIXTURE",
            "source_digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
            "test_digest": "sha256:" + hashlib.sha256((directory / "test_acceptance.py").read_bytes()).hexdigest(),
            "exit_code": 0 if operation != "checks" or path.read_text() == FIX else 1,
            "timed_out": False,
            "stdout": "",
            "stderr": "Ran 4 tests in 0.001s\n",
        }
        if operation == "read":
            receipt["content"] = path.read_text()
        return receipt


class FixtureNative:
    """Not a production adapter. Generates tool calls without a model for integration assertions."""

    simulated = True

    def __init__(self):
        self.service = None
        self.commands = []

    async def request(self, *_):
        return {"ready": True, "runtime_version": "0.1.1", "provider": "my-codex", "model": "cx/gpt-5.6-luna"}

    async def run(self, command):
        self.commands.append(command)

        async def call(name, **arguments):
            return await self.service.tool(
                ToolCommand.model_validate_json(
                    __import__("json").dumps(
                        {
                            "session_id": command["session_id"],
                            "call_id": str(uuid4()),
                            "name": name,
                            "arguments": arguments,
                        }
                    )
                )
            )

        await call("demo_context")
        if command["stage"] == "PLAN":
            await call("demo_write_task_plan", **PLAN)
        elif command["stage"] == "ITERATE":
            await call("demo_load_skill")
            await call("demo_memory_recall")
            await call("demo_write_task_brief", **BRIEF)
            result = await call("demo_sandbox_read")
            await call("demo_sandbox_write", content=FIX, expected_digest=result["source_digest"])
            await call("demo_sandbox_checks")
            await call("demo_report_iteration", **REPORT)
        elif command["stage"] == "HANDOFF":
            await call("demo_report_task", **REPORT)
            await call("demo_commit_candidate")
        return {
            "status": "COMPLETED",
            "request_digest": digest(command),
            "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18, "cost": None},
        }

    async def cancel(self, _):
        return None


def service(tmp_path, *, sandbox=None):
    client = FixtureNative()
    result = HarnessDemoService(tmp_path / "demo", client=client, sandbox=sandbox or FixtureSandbox())
    client.service = result
    return result


async def full_demo(service):
    run = await service.create("owner-a", REQUIREMENT)
    service.ledger.transition(run["id"], "owner-a", "DRAFT", "PLANNING")
    await service.plan(run["id"])
    planned = service.ledger.get(run["id"])
    assert planned["status"] == "AWAITING_PLAN_APPROVAL"
    assert planned["plan_digest"] == digest(planned["plan"])
    service.ledger.transition(run["id"], "owner-a", "AWAITING_PLAN_APPROVAL", "RUNNING")
    await service.execute(run["id"])
    handoff = service.ledger.get(run["id"])
    assert handoff["status"] == "AWAITING_MERGE_APPROVAL"
    assert handoff["handoff_digest"] == digest(handoff["handoff"])
    assert handoff["verification"]["candidate_digest"] == handoff["candidate"]["content_digest"]
    assert handoff["verification"]["checks"][0]["executed_tests"] == 4
    assert handoff["loop_result"]["metadata"]["task_loop"]["runtime"]["family"] == "HARNESS"
    assert service.scopes == {}
    source = service.repository(run["id"])
    assert await service.git(source, "rev-parse", "demo-main") == planned["base_commit"]
    assert await service.git(source, "show", f"{handoff['commit']}:{SOURCE_PATH}") == FIX.strip()
    service.ledger.transition(run["id"], "owner-a", "AWAITING_MERGE_APPROVAL", "PUBLISHING")
    await service.publish(run["id"])
    final = service.ledger.get(run["id"])
    assert final["status"] == "SUCCEEDED"
    assert final["publish_receipt"]["local_bare_pushed"]
    assert not final["publish_receipt"]["github_pushed"]
    assert await service.git(source.parent / "orchestrator-mirror.git", "rev-parse", "demo-main") == handoff["commit"]
    assert await service.git(source, "status", "--porcelain") == ""
    assert [c["stage"] for c in service.client.commands] == ["PLAN", "ITERATE", "HANDOFF"]
    return final


async def test_real_git_workflow_uses_existing_loop_kernel(tmp_path):
    await full_demo(service(tmp_path))


@pytest.mark.skipif(
    __import__("os").getenv("ADLC_DEMO_TEST_DOCKER") != "true", reason="explicit actual-Docker integration opt-in"
)
async def test_actual_docker_checks_commit_merge_and_local_push(tmp_path):
    final = await full_demo(service(tmp_path, sandbox=DockerDemoSandbox()))
    reproductions = [e["output"]["reproduction"] for e in final["events"] if e["stage"] == "verify"]
    assert reproductions
    assert reproductions[0]["image_id"].startswith("sha256:")
    assert reproductions[0]["network"] == "none"
    assert reproductions[0]["container_name"].startswith("adlc-demo-")


async def test_owner_scope_transition_and_no_implicit_resume(tmp_path):
    demo = service(tmp_path)
    run = await demo.create("a", REQUIREMENT)
    with pytest.raises(DemoError, match="DEMO_NOT_FOUND"):
        demo.ledger.get(run["id"], "b")
    demo.ledger.transition(run["id"], "a", "DRAFT", "PLANNING")
    with pytest.raises(DemoError, match="DEMO_STATE_CONFLICT"):
        demo.ledger.transition(run["id"], "a", "DRAFT", "PLANNING")
    restarted = service(tmp_path)
    assert not restarted.jobs
    assert not restarted.scopes
    assert not restarted.client.commands


async def test_tool_scope_and_required_brief(tmp_path):
    demo = service(tmp_path)
    run = await demo.create("a", REQUIREMENT)
    await demo.prepare(run["id"])
    session = uuid4()
    directory = demo.repository(run["id"])
    await demo.update(run["id"], plan_digest=digest(PLAN))
    demo.bind(session, run["id"], "ITERATE", directory=directory, iteration=1)

    def command(name, **arguments):
        return ToolCommand(session_id=session, call_id=uuid4(), name=name, arguments=arguments)

    with pytest.raises(DemoError, match="DEMO_TOOL_SCOPE_DENIED"):
        await demo.tool(command("demo_commit_candidate"))
    with pytest.raises(DemoError, match="DEMO_BRIEF_SKILL_MEMORY_REQUIRED"):
        await demo.tool(command("demo_sandbox_write", content=FIX, expected_digest="sha256:" + "0" * 64))
    await demo.tool(command("demo_load_skill"))
    memory = await demo.tool(command("demo_memory_recall"))
    assert memory["source"] == "CURATED_LOCAL"
    assert not memory["verification_evidence"]
    await demo.tool(command("demo_write_task_brief", **BRIEF))
    await demo.tool(command("demo_sandbox_read"))
    with pytest.raises(DemoError, match="DEMO_WRITE_DIGEST_CONFLICT"):
        await demo.tool(command("demo_sandbox_write", content=FIX, expected_digest="sha256:" + "0" * 64))
    with pytest.raises(DemoError, match="DEMO_ARGUMENTS_INVALID"):
        await demo.tool(command("demo_sandbox_read", path="../../.env"))
    assert (directory / DEMO_DIR / "app.py").read_text() != FIX


async def test_tool_idempotency_and_plan_immutability(tmp_path):
    demo = service(tmp_path)
    run = await demo.create("a", REQUIREMENT)
    await demo.prepare(run["id"])
    session = uuid4()
    demo.bind(session, run["id"], "PLAN")
    call = ToolCommand(session_id=session, call_id=uuid4(), name="demo_write_task_plan", arguments=PLAN)
    assert await demo.tool(call) == await demo.tool(call)
    assert len(demo.ledger.get(run["id"])["events"]) == 2
    with pytest.raises(DemoError, match="DEMO_PLAN_IMMUTABLE"):
        await demo.tool(call.model_copy(update={"call_id": uuid4()}))
    with pytest.raises(DemoError, match="DEMO_TOOL_REPLAY_CONFLICT"):
        await demo.tool(call.model_copy(update={"arguments": {**PLAN, "objective": "other"}}))


async def test_merge_rejects_changed_branch(tmp_path):
    demo = service(tmp_path)
    run = await full_demo(demo)
    source = demo.repository(run["id"])
    await demo.git(source, "commit", "--allow-empty", "-qm", "unexpected change")
    with pytest.raises(DemoError, match="DEMO_MERGE_BASE_CHANGED"):
        await demo.publish(run["id"])


@pytest.mark.parametrize("explicit_crlf", [False, True])
async def test_checkout_line_endings_are_canonical_and_protected_guard_runs_before_agent(tmp_path, explicit_crlf):
    demo = service(tmp_path)
    prepare = demo.prepare

    async def project_with_attributes(run_id):
        await prepare(run_id)
        source = demo.repository(run_id)
        (source / ".gitattributes").write_bytes(b"*.py text eol=crlf\n" if explicit_crlf else b"* text=auto\n")
        await demo.git(source, "add", "--", ".gitattributes")
        await demo.git(source, "commit", "-qm", "test: seed upstream checkout attributes")
        await demo.git(source, "config", "core.eol", "crlf")
        await demo.update(run_id, base_commit=await demo.git(source, "rev-parse", "HEAD"))

    demo.prepare = project_with_attributes
    if explicit_crlf:
        with pytest.raises(DemoError, match="TASK_LOOP_PROTECTED_TEST_CHANGED"):
            await full_demo(demo)
        assert [command["stage"] for command in demo.client.commands] == ["PLAN"]
    else:
        final = await full_demo(demo)
        assert final["status"] == "SUCCEEDED"
