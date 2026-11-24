# ruff: noqa: PLR2004, S101

"""Delegation contract tests (G4 Phần 3): the old 6-section markdown
template materializes into the existing skilltree contract system, and
the orchestrator system prompt stays in sync with that schema."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from langflow.adlc.contract_models import SkilltreeNode
from langflow.adlc.contract_validation import structural_issues, validate_document
from langflow.adlc.orchestrator_plugin.delegation import (
    DELEGATION_OUTPUT_SCHEMA,
    DelegatedTask,
    build_skilltree_document,
    delegation_schema_example,
    parse_delegated_task,
    to_roadmap_constraints,
    to_skilltree_node_spec,
)

ROOT = Path(__file__).resolve().parents[4]
PROMPT_PATH = ROOT / "adlc_components/custom_component/system_prompts/orchestrator.py"


@pytest.fixture(scope="module")
def prompt_module():
    spec = importlib.util.spec_from_file_location("adlc_orchestrator_prompt", PROMPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _task(**overrides) -> DelegatedTask:
    payload = {
        "task_name": "Implement payment retry",
        "objective": "Add idempotent retry following the notify service pattern.",
        "expected_files": ["src/services/payment_retry.py"],
        "scope_paths": ["src/services", "tests/unit"],
        "must_not_do": ["Do not add dependencies"],
        "acceptance_criteria": ["pytest tests/unit/test_payment_retry.py passes"],
    }
    payload.update(overrides)
    return DelegatedTask(**payload)


class TestDelegatedTaskParsing:
    def test_parse_strips_and_ignores_extra_keys(self):
        parsed = parse_delegated_task(
            {
                "task_name": "  Implement payment retry  ",
                "objective": " Add idempotent retry. ",
                "expected_files": [" src/services/payment_retry.py ", ""],
                "must_not_do": "Do not add dependencies",
                "unrelated": "noise",
            }
        )
        assert parsed.task_name == "Implement payment retry"
        assert parsed.expected_files == ["src/services/payment_retry.py"]
        assert parsed.must_not_do == ["Do not add dependencies"]
        assert parsed.acceptance_criteria == []

    def test_blank_task_name_rejected(self):
        with pytest.raises(ValidationError):
            DelegatedTask(task_name="   ", objective="Do the thing.")

    def test_schema_example_names_all_six_fields(self):
        example = delegation_schema_example()
        for field in ("task_name", "objective", "expected_files", "scope_paths", "must_not_do", "acceptance_criteria"):
            assert field in example

    def test_output_schema_covers_six_fields(self):
        names = {row["name"] for row in DELEGATION_OUTPUT_SCHEMA}
        assert names == {"task_name", "objective", "expected_files", "scope_paths", "must_not_do", "acceptance_criteria"}


class TestContractMaterialization:
    def test_task_node_spec_maps_six_fields(self):
        node = to_skilltree_node_spec(_task())
        assert node.kind == "TASK"
        assert node.title == "Implement payment retry"
        assert node.description.startswith("Add idempotent retry")
        assert "Expected files:" in node.description
        assert "- src/services/payment_retry.py" in node.description
        criteria = node.acceptance_criteria
        assert len(criteria) == 1
        assert criteria[0].verification == "HUMAN"
        assert criteria[0].description == "pytest tests/unit/test_payment_retry.py passes"

    def test_constraints_from_scope_and_prohibitions(self):
        constraints = to_roadmap_constraints([_task()])
        assert constraints.allowed_paths == ["src/services", "tests/unit"]
        assert constraints.forbidden_actions == ["Do not add dependencies"]

    def test_constraints_defaults_without_scope(self):
        constraints = to_roadmap_constraints(
            [DelegatedTask(task_name="T", objective="Objective text here.")]
        )
        assert constraints.allowed_paths == ["*"]
        assert constraints.forbidden_actions == ["commit", "push"]

    def test_document_is_valid_and_deterministic(self):
        tasks = [
            _task(),
            DelegatedTask(
                task_name="Write retry docs",
                objective="Document the retry semantics for operators.",
                scope_paths=["docs"],
                acceptance_criteria=["Docs cover backoff and idempotency"],
            ),
        ]
        contract_id = uuid4()
        doc = build_skilltree_document(
            title="Payment retry batch",
            objective="Ship idempotent payment retries.",
            tasks=tasks,
            contract_id=contract_id,
            dependencies={"Write retry docs": ["Implement payment retry"]},
        )
        assert structural_issues(doc) == []
        validation = validate_document(doc, datetime.now(tz=UTC))
        assert validation.passed, [check.summary for check in validation.checks]
        assert {node.kind for node in doc.nodes} == {"TASK"}
        # REQUIRES edges mirror the delegation DAG.
        assert len(doc.dependencies) == 1
        edge = doc.dependencies[0]
        by_title = {node.title: node for node in doc.nodes}
        assert edge.source_id == by_title["Write retry docs"].node_id
        assert edge.target_id == by_title["Implement payment retry"].node_id
        # Deterministic node IDs (uuid5 over contract + task name).
        rebuilt = build_skilltree_document(
            title="Payment retry batch",
            objective="Ship idempotent payment retries.",
            tasks=tasks,
            contract_id=contract_id,
        )
        assert {node.node_id for node in rebuilt.nodes} == {node.node_id for node in doc.nodes}

    def test_document_nodes_are_skilltree_nodes(self):
        doc = build_skilltree_document(
            title="Batch",
            objective="Objective for the batch.",
            tasks=[_task()],
            contract_id=uuid4(),
        )
        assert all(isinstance(node, SkilltreeNode) for node in doc.nodes)

    def test_unknown_dependency_name_raises(self):
        with pytest.raises(ValueError, match="unknown task"):
            build_skilltree_document(
                title="Batch",
                objective="Objective for the batch.",
                tasks=[_task()],
                contract_id=uuid4(),
                dependencies={"Implement payment retry": ["Ghost task"]},
            )

    def test_duplicate_task_names_raise(self):
        with pytest.raises(ValueError, match="Duplicate task names"):
            build_skilltree_document(
                title="Batch",
                objective="Objective for the batch.",
                tasks=[_task(), _task()],
                contract_id=uuid4(),
            )

    def test_invalid_scope_path_surfaces_contract_validation(self):
        """Contract path rules are inherited, not bypassed."""
        bad = DelegatedTask(
            task_name="T",
            objective="Objective text here.",
            scope_paths=["/abs/path"],
        )
        with pytest.raises(ValidationError):
            to_roadmap_constraints([bad])


class TestOrchestratorSystemPrompt:
    def test_intent_gate_and_delegation_framework_kept(self, prompt_module):
        prompt = prompt_module.build_orchestrator_prompt(
            specialists_table_markdown="| None | - | - |",
            helpers_markdown="*(No atomic helper tools connected)*",
            hard_blocks_markdown="- No strict constraints defined.",
            additional_context="workspace: /demo",
            current_date="2026-10-19",
            delegation_schema_json=delegation_schema_example(),
        )
        assert "Phase 0 - Intent Gate" in prompt
        assert "delegation_framework" in prompt
        assert "Specialist Agent Directory" in prompt

    def test_delegation_template_is_structured_contract(self, prompt_module):
        prompt = prompt_module.build_orchestrator_prompt(
            specialists_table_markdown="| None | - | - |",
            helpers_markdown="*(No atomic helper tools connected)*",
            hard_blocks_markdown="- No strict constraints defined.",
            additional_context="",
            current_date="2026-10-19",
            delegation_schema_json=delegation_schema_example(),
        )
        for field in ("task_name", "objective", "expected_files", "scope_paths", "must_not_do", "acceptance_criteria"):
            assert field in prompt
        # The old free-form markdown template is gone.
        assert "## 1. TASK" not in prompt
        assert "## 6. CONTEXT" not in prompt

    def test_manual_file_review_replaced_by_evidence_verdict(self, prompt_module):
        prompt = prompt_module.build_orchestrator_prompt(
            specialists_table_markdown="| None | - | - |",
            helpers_markdown="*(No atomic helper tools connected)*",
            hard_blocks_markdown="- No strict constraints defined.",
            additional_context="",
            current_date="2026-10-19",
            delegation_schema_json=delegation_schema_example(),
        )
        assert "Read EVERY file the subagent created" not in prompt
        assert "Manual Code Review (NON-NEGOTIABLE)" not in prompt
        assert "PROPOSED, NOT FINAL" in prompt
        assert "quality gate" in prompt
        assert "NO EVIDENCE = NOT DONE" in prompt
