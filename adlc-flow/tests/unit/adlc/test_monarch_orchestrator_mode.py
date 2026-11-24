# ruff: noqa: PLR2004, S101

"""Unit tests for the Monarch component's orchestrator mode ("handless
brain", G4 Phần 2): execution tools are stripped from the toolset while
read-only, diagnostics, task and agent-connector tools survive."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[4]
COMPONENT_PATH = ROOT / "adlc_components/custom_component/agents/orchestrator.py"


@pytest.fixture(scope="module")
def orchestrator_module():
    spec = importlib.util.spec_from_file_location("adlc_orchestrator_component", COMPONENT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tool(name: str, **attributes):
    return SimpleNamespace(name=name, **attributes)


class TestIsExecutionTool:
    def test_execution_tools_by_name_and_token(self, orchestrator_module):
        is_execution_tool = orchestrator_module.is_execution_tool
        for name in ("edit", "Write", "bash", "apply_patch", "python_repl", "run_tests", "file_editor", "terminal"):
            assert is_execution_tool(_tool(name)), name

    def test_safe_tools_kept(self, orchestrator_module):
        is_execution_tool = orchestrator_module.is_execution_tool
        # read-only, diagnostics, task tracking, agent connectors, contract tools
        for name in (
            "read_file",
            "grep",
            "glob",
            "list_dir",
            "lsp_diagnostics",
            "task_create",
            "task_update",
            "todowrite",
            "Call_Agent",
            "A2A_Call",
            "skilltree_upsert_node",
            "web_search",
        ):
            assert not is_execution_tool(_tool(name)), name

    def test_dangerous_attributes_flag_execution(self, orchestrator_module):
        assert orchestrator_module.is_execution_tool(_tool("custom_runner", dangerous=True))
        assert orchestrator_module.is_execution_tool(_tool("file_helper", writes_files=True))
        assert not orchestrator_module.is_execution_tool(_tool("file_helper", dangerous=False))


class TestPartitionExecutionTools:
    def test_filtered_toolset_has_no_execution_tool_and_keeps_connectors(self, orchestrator_module):
        toolset = [
            _tool("read_file"),
            _tool("grep"),
            _tool("lsp_diagnostics"),
            _tool("task_create"),
            _tool("task_update"),
            _tool("todowrite"),
            _tool("Call_Agent"),
            _tool("A2A_Call"),
            _tool("edit"),
            _tool("write"),
            _tool("patch"),
            _tool("shell"),
            _tool("bash"),
            _tool("run_tests"),
            _tool("python_repl"),
        ]
        kept, removed = orchestrator_module.partition_execution_tools(toolset)

        kept_names = [tool.name for tool in kept]
        removed_names = {tool.name for tool in removed}

        # No execution tool survives the filter.
        assert not any(orchestrator_module.is_execution_tool(tool) for tool in kept)
        assert {"edit", "write", "patch", "shell", "bash", "run_tests", "python_repl"} <= removed_names
        # Every agent connector and every read/task tool survives.
        assert {"Call_Agent", "A2A_Call", "task_create", "task_update", "lsp_diagnostics", "read_file", "grep"} <= set(
            kept_names
        )

    def test_partition_empty_toolset(self, orchestrator_module):
        kept, removed = orchestrator_module.partition_execution_tools([])
        assert kept == [] and removed == []
        kept, removed = orchestrator_module.partition_execution_tools(None)
        assert kept == [] and removed == []


def _bare_component(orchestrator_module, *, orchestrator_mode, tools):
    """Instantiate the component without the component runtime."""
    component = object.__new__(orchestrator_module.AgentComponent)
    if orchestrator_mode is not None:
        component.orchestrator_mode = orchestrator_mode
    component.tools = list(tools)
    return component


class TestAgentToolPolicyEnforcement:
    def test_orchestrator_mode_strips_execution_tools(self, orchestrator_module):
        component = _bare_component(
            orchestrator_module,
            orchestrator_mode=True,
            tools=[_tool("read_file"), _tool("edit"), _tool("Call_Agent"), _tool("bash")],
        )
        component._enforce_orchestrator_tool_policy()
        assert [tool.name for tool in component.tools] == ["read_file", "Call_Agent"]

    def test_mode_off_keeps_toolset_untouched(self, orchestrator_module):
        toolset = [_tool("read_file"), _tool("edit")]
        component = _bare_component(orchestrator_module, orchestrator_mode=False, tools=toolset)
        component._enforce_orchestrator_tool_policy()
        assert [tool.name for tool in component.tools] == ["read_file", "edit"]

    def test_missing_flag_keeps_legacy_toolset(self, orchestrator_module):
        """Saved flows created before the field exist keep working."""
        toolset = [_tool("read_file"), _tool("edit")]
        component = _bare_component(orchestrator_module, orchestrator_mode=None, tools=toolset)
        assert not hasattr(component, "orchestrator_mode")
        component._enforce_orchestrator_tool_policy()
        assert [tool.name for tool in component.tools] == ["read_file", "edit"]


class TestOrchestratorModeInput:
    def test_flag_declared_with_default_true(self, orchestrator_module):
        inputs = {inp.name: inp for inp in orchestrator_module.AgentComponent.inputs}
        flag = inputs["orchestrator_mode"]
        assert getattr(flag, "value", None) is True
        assert "orchestrator" in flag.name

    def test_get_agent_requirements_filters_after_tool_gathering(self, orchestrator_module, monkeypatch):
        """The enforcement step runs inside get_agent_requirements, after
        the wrap-tools hooks — the returned toolset is execution-free."""
        calls = {"filtered": 0}
        original_enforce = orchestrator_module.AgentComponent._enforce_orchestrator_tool_policy

        def counting_enforce(self):
            calls["filtered"] += 1
            original_enforce(self)

        monkeypatch.setattr(orchestrator_module.AgentComponent, "_enforce_orchestrator_tool_policy", counting_enforce)
        assert calls["filtered"] == 0  # sanity: not called at import time
        # The wiring itself is asserted structurally: the method must be
        # invoked between the wrap-tools hooks and the return. Verified by
        # source inspection to keep this test free of the model runtime.
        import inspect

        source = inspect.getsource(orchestrator_module.AgentComponent.get_agent_requirements)
        enforce_index = source.index("_enforce_orchestrator_tool_policy")
        wrap_index = source.index("_run_wrap_tools_hooks")
        return_index = source.rindex("return llm_model")
        assert wrap_index < enforce_index < return_index
