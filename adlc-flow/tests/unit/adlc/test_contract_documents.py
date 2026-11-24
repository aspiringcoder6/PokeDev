"""H5A contract invariants: tool provenance, exact approval, replay, persistence and scope."""

# ruff: noqa: INP001, S101, S105, S106, PLR2004
from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from langflow.adlc.contract_bridge import ContractBridgeSettings, sign_contract_command
from langflow.adlc.contract_models import (
    TOOL_ARGUMENT_MODELS,
    ContractApprovalCommand,
    ContractBridgeCommand,
    ContractForkCommand,
    ContractPluginManifest,
    ContractScope,
    InitArguments,
    SkilltreeDocument,
)
from langflow.adlc.contract_presentation import contract_markdown
from langflow.adlc.contract_repository import ContractError, ContractRepository
from langflow.adlc.contract_validation import document_bytes, structural_issues, validate_document

OWNER = "human-owner"


@pytest.fixture(autouse=True)
def close_test_repositories(monkeypatch):
    """Release every test connection, including assertion-failure paths on Windows."""
    instances = []
    original = ContractRepository.__init__

    def tracked_init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        instances.append(self)

    monkeypatch.setattr(ContractRepository, "__init__", tracked_init)
    yield
    for repository in instances:
        repository.close()


@pytest.fixture
def scope():
    return ContractScope(
        workflow_run_id=uuid4(), task_run_id=uuid4(), request_id=uuid4(), attempt_id=uuid4(), session_id="h5a-session"
    )


def call(repository, binding, tool, **arguments):
    return repository.execute(
        tool,
        arguments,
        owner_id=OWNER,
        scope=binding,
        actor_id=f"harness-session:{binding.session_id}",
        authored_via="HARNESS_TOOL",
    )


def create(repository, scope):
    return call(
        repository,
        scope,
        "skilltree_init",
        idempotency_key="init-1",
        title="ADLC roadmap",
        scope={"objective": "Create a binding roadmap", "out_of_scope": ["Commit or push"]},
    )


def node(repository, scope, current, *, key="node-1", title="Implement the feature", node_id=None, criteria=None):
    return call(
        repository,
        scope,
        "skilltree_upsert_node",
        idempotency_key=key,
        contract_id=str(current.contract.document.contract_id),
        expected_revision=current.contract.document.revision,
        node_id=str(node_id) if node_id else None,
        node={
            "title": title,
            "acceptance_criteria": criteria
            if criteria is not None
            else [{"description": "Human reviews the evidence"}],
        },
    )


def validate(repository, scope, current, key="validate-1"):
    return call(
        repository,
        scope,
        "skilltree_validate",
        idempotency_key=key,
        contract_id=str(current.contract.document.contract_id),
        expected_revision=current.contract.document.revision,
    )


def approve(repository, scope, current, key="approval-1"):
    command = ContractApprovalCommand(reference=current.contract.reference, idempotency_key=key)
    return repository.approve(command, owner_id=OWNER, run_id=scope.workflow_run_id)


def expect_code(code, operation):
    with pytest.raises(ContractError) as error:
        operation()
    assert error.value.code == code


def test_tools_own_ids_full_text_json_and_distinct_approval(scope):
    with_repo = ContractRepository()
    draft = create(with_repo, scope)
    wording = "Preserve the full requirement, including its mandatory security and regression acceptance criteria."
    added = node(with_repo, scope, draft, title=wording)
    assert added.node_id is not None
    assert added.contract.document.nodes[0].title == wording
    assert added.contract.authored_via == "HARNESS_TOOL"
    assert added.contract.document.revision == 2
    assert "position" not in document_bytes(added.contract.document).decode()
    checked = validate(with_repo, scope, added)
    assert checked.contract.status == "VALIDATED"
    assert checked.contract.document.revision == 2
    assert checked.contract.validation.criteria_executed is False
    accepted = approve(with_repo, scope, checked)
    assert accepted.contract.status == "APPROVED"
    assert accepted.contract.approval.reference == checked.contract.reference
    assert accepted.contract.approval.approved_by == OWNER
    assert accepted.contract.reference.content_digest == checked.contract.reference.content_digest
    assert approve(with_repo, scope, checked).replayed is True
    expect_code("CONTRACT_TOOL_NOT_ALLOWED", lambda: call(with_repo, scope, "skilltree_approve"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("owner_id", "forged"),
        ("status", "APPROVED"),
        ("nodes", []),
        ("contract_id", str(uuid4())),
        ("file", "../../outside.json"),
    ],
)
def test_init_rejects_agent_control_of_identity_state_files_and_raw_documents(scope, field, value):
    repository = ContractRepository()
    args = {"idempotency_key": "bad", "title": "Draft", "scope": {"objective": "Goal"}, field: value}
    expect_code(
        "CONTRACT_ARGUMENTS_INVALID",
        lambda: repository.execute(
            "skilltree_init", args, owner_id=OWNER, scope=scope, actor_id="agent", authored_via="HARNESS_TOOL"
        ),
    )
    assert repository.list_for_run(scope.workflow_run_id, owner_id=OWNER) == []


def test_idempotent_creation_edit_and_conflicting_key(scope):
    repository = ContractRepository()
    first = create(repository, scope)
    replay = create(repository, scope)
    assert replay.replayed
    assert replay.contract.reference == first.contract.reference
    created = node(repository, scope, first)
    updated = node(repository, scope, created, key="edit", node_id=created.node_id, title="Revised content")
    replayed_node = node(repository, scope, first)
    assert replayed_node.replayed
    assert replayed_node.node_id == created.node_id
    assert (
        repository.get(first.contract.document.contract_id, owner_id=OWNER, run_id=scope.workflow_run_id).reference
        == updated.contract.reference
    )
    expect_code("CONTRACT_IDEMPOTENCY_CONFLICT", lambda: node(repository, scope, first, title="Different content"))


def test_stale_edit_and_stale_digest_cannot_be_approved(scope):
    repository = ContractRepository()
    draft = create(repository, scope)
    current = node(repository, scope, draft)
    expect_code("REVISION_CONFLICT", lambda: node(repository, scope, draft, key="stale"))
    expect_code("CONTRACT_NOT_VALIDATED", lambda: approve(repository, scope, current))
    checked = validate(repository, scope, current)
    bad_ref = checked.contract.reference.model_copy(update={"content_digest": "sha256:" + "0" * 64})
    expect_code(
        "REVISION_CONFLICT",
        lambda: repository.approve(
            ContractApprovalCommand(reference=bad_ref, idempotency_key="forged-hash"),
            owner_id=OWNER,
            run_id=scope.workflow_run_id,
        ),
    )
    assert (
        repository.get(current.contract.document.contract_id, owner_id=OWNER, run_id=scope.workflow_run_id).status
        == "VALIDATED"
    )


def test_edits_invalidate_validation_and_failed_declarations_never_approve(scope):
    repository = ContractRepository()
    current = node(repository, scope, create(repository, scope))
    checked = validate(repository, scope, current)
    changed = node(repository, scope, checked, key="missing-criteria", node_id=current.node_id, criteria=[])
    assert changed.contract.validation is None
    assert changed.contract.status == "DRAFT"
    failed = validate(repository, scope, changed, key="validate-empty")
    assert failed.contract.validation.passed is False
    expect_code("CONTRACT_NOT_VALIDATED", lambda: approve(repository, scope, failed))
    changed = node(
        repository,
        scope,
        failed,
        key="missing-verifier",
        node_id=current.node_id,
        criteria=[{"description": "Tests pass", "verification": "TEST"}],
    )
    failed = validate(repository, scope, changed, key="validate-no-verifier")
    assert not failed.contract.validation.passed
    empty = create(ContractRepository(), scope)
    assert empty.contract.status == "DRAFT"


def test_cycles_dangling_edges_and_referenced_removal_roll_back(scope):
    repository = ContractRepository()
    first = node(repository, scope, create(repository, scope))
    second = node(repository, scope, first, key="second", title="Second task")
    cid = str(first.contract.document.contract_id)

    def dependency(current, source, target, key, operation="ADD"):
        return call(
            repository,
            scope,
            "skilltree_set_dependency",
            contract_id=cid,
            expected_revision=current.contract.document.revision,
            idempotency_key=key,
            source_id=str(source),
            target_id=str(target),
            operation=operation,
        )

    connected = dependency(second, first.node_id, second.node_id, "edge")
    expect_code("CONTRACT_DEPENDENCY_CYCLE", lambda: dependency(connected, second.node_id, first.node_id, "cycle"))
    expect_code("CONTRACT_DEPENDENCY_NODE_MISSING", lambda: dependency(connected, uuid4(), first.node_id, "dangling"))
    expect_code(
        "CONTRACT_NODE_REFERENCED",
        lambda: call(
            repository,
            scope,
            "skilltree_remove_node",
            contract_id=cid,
            expected_revision=connected.contract.document.revision,
            idempotency_key="remove-ref",
            node_id=str(first.node_id),
        ),
    )
    removed_edge = dependency(connected, first.node_id, second.node_id, "remove-edge", "REMOVE")
    removed_node = call(
        repository,
        scope,
        "skilltree_remove_node",
        contract_id=cid,
        expected_revision=removed_edge.contract.document.revision,
        idempotency_key="remove-node",
        node_id=str(first.node_id),
    )
    assert len(removed_node.contract.document.nodes) == 1
    assert not removed_node.contract.document.dependencies


@pytest.mark.parametrize(
    ("tool", "extra"),
    [
        ("skilltree_upsert_node", {"node": {"title": "Bypass"}}),
        ("skilltree_remove_node", {"node_id": str(uuid4())}),
        ("skilltree_set_dependency", {"source_id": str(uuid4()), "target_id": str(uuid4())}),
        ("skilltree_validate", {}),
    ],
)
def test_every_mutating_tool_rejects_frozen_document(scope, tool, extra):
    repository = ContractRepository()
    accepted = approve(
        repository, scope, validate(repository, scope, node(repository, scope, create(repository, scope)))
    )
    expect_code(
        "CONTRACT_LOCKED",
        lambda: call(
            repository,
            scope,
            tool,
            contract_id=str(accepted.contract.document.contract_id),
            expected_revision=accepted.contract.document.revision,
            idempotency_key="late",
            **extra,
        ),
    )


def test_explicit_fork_preserves_approved_bytes_and_requires_new_approval(scope):
    repository = ContractRepository()
    accepted = approve(
        repository, scope, validate(repository, scope, node(repository, scope, create(repository, scope)))
    )
    command = ContractForkCommand(reference=accepted.contract.reference, idempotency_key="request-change")
    forked = repository.fork(command, owner_id=OWNER, run_id=scope.workflow_run_id)
    assert forked.contract.document.contract_id != accepted.contract.document.contract_id
    assert forked.contract.document.supersedes == accepted.contract.reference
    assert forked.contract.status == "DRAFT"
    assert forked.contract.approval is None
    assert repository.fork(command, owner_id=OWNER, run_id=scope.workflow_run_id).replayed
    edited = node(
        repository,
        scope,
        forked,
        key="fork-edit",
        node_id=forked.contract.document.nodes[0].node_id,
        title="New scope task",
    )
    expect_code("CONTRACT_NOT_VALIDATED", lambda: approve(repository, scope, edited, key="fork-approve"))
    assert document_bytes(
        repository.get(accepted.contract.document.contract_id, owner_id=OWNER, run_id=scope.workflow_run_id).document
    ) == document_bytes(accepted.contract.document)


def test_persistence_has_no_patch_expiry_or_harness_dependency(scope, tmp_path):
    path = tmp_path / "contracts.sqlite3"
    repository = ContractRepository(path)
    accepted = approve(
        repository, scope, validate(repository, scope, node(repository, scope, create(repository, scope)))
    )
    repository.close()
    reopened = ContractRepository(path, clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc))
    assert (
        reopened.get(accepted.contract.document.contract_id, owner_id=OWNER, run_id=scope.workflow_run_id)
        == accepted.contract
    )
    historic = reopened.get(
        accepted.contract.document.contract_id, owner_id=OWNER, run_id=scope.workflow_run_id, revision=1
    )
    assert historic.document.nodes == []
    assert historic.status == "DRAFT"
    reopened.close()


def test_owner_run_attempt_and_session_boundaries(scope):
    repository = ContractRepository()
    created = create(repository, scope)
    cid = created.contract.document.contract_id
    for kwargs in [
        {"owner_id": "different", "run_id": scope.workflow_run_id},
        {"owner_id": OWNER, "run_id": uuid4()},
        {
            "owner_id": OWNER,
            "run_id": scope.workflow_run_id,
            "scope": scope.model_copy(update={"session_id": "other-session"}),
        },
    ]:
        expect_code("CONTRACT_NOT_FOUND", lambda kwargs=kwargs: repository.get(cid, **kwargs))
    assert repository.list_for_run(scope.workflow_run_id, owner_id="different") == []
    expect_code(
        "CONTRACT_NOT_FOUND",
        lambda: call(
            repository, scope.model_copy(update={"attempt_id": uuid4()}), "skilltree_get_status", contract_id=str(cid)
        ),
    )


def test_storage_quota_rolls_back_without_evicting(scope):
    repository = ContractRepository(max_total_bytes=10)
    expect_code("CONTRACT_STORE_FULL", lambda: create(repository, scope))
    assert repository.list_for_run(scope.workflow_run_id, owner_id=OWNER) == []


def test_two_repository_instances_fence_concurrent_edits(scope, tmp_path):
    path = tmp_path / "shared.sqlite3"
    first, second = ContractRepository(path), ContractRepository(path)
    current = create(first, scope)

    def edit(repository, key):
        try:
            return node(repository, scope, current, key=key)
        except ContractError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda item: edit(*item), [(first, "a"), (second, "b")]))
    assert sum(isinstance(item, str) and item == "REVISION_CONFLICT" for item in outcomes) == 1
    assert (
        first.get(current.contract.document.contract_id, owner_id=OWNER, run_id=scope.workflow_run_id).document.revision
        == 2
    )
    first.close()
    second.close()


def test_approval_edit_race_cannot_freeze_a_stale_revision(scope, tmp_path):
    path = tmp_path / "approval-race.sqlite3"
    first, second = ContractRepository(path), ContractRepository(path)
    checked = validate(first, scope, node(first, scope, create(first, scope)))

    def invoke(operation):
        try:
            return operation()
        except ContractError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                invoke,
                [lambda: approve(first, scope, checked), lambda: node(second, scope, checked, key="racing-edit")],
            )
        )
    current = first.get(checked.contract.document.contract_id, owner_id=OWNER, run_id=scope.workflow_run_id)
    if current.status == "APPROVED":
        assert "CONTRACT_LOCKED" in outcomes
        assert current.reference == checked.contract.reference
    else:
        assert "REVISION_CONFLICT" in outcomes
        assert current.document.revision == 3
        assert current.approval is None
    first.close()
    second.close()


def test_direct_payload_tampering_fails_closed(scope, tmp_path):
    path = tmp_path / "tampered.sqlite3"
    repository = ContractRepository(path)
    current = create(repository, scope)
    changed = current.contract.document.model_copy(update={"title": "Tampered"})
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE adlc_contract_revisions SET payload=?", (document_bytes(changed),))
    expect_code(
        "CONTRACT_STORE_INVALID",
        lambda: repository.get(current.contract.document.contract_id, owner_id=OWNER, run_id=scope.workflow_run_id),
    )
    repository.close()


def test_human_summary_escapes_markup_without_truncating(scope):
    repository = ContractRepository()
    current = node(
        repository, scope, create(repository, scope), title="[full requirement](javascript:alert(1)) <script>"
    )
    summary = contract_markdown(current.contract)
    assert "&lt;script&gt;" in summary
    assert "\\[full requirement\\]" in summary
    assert "acceptance criteria have NOT been executed" in summary


@pytest.mark.parametrize("invalid", ["../escape", "/root", "C:/outside", "src\\file", "src//file", "src/../secrets"])
def test_declared_paths_are_relative_not_file_write_destinations(invalid):
    with pytest.raises(ValidationError):
        InitArguments(
            idempotency_key="init", title="Draft", scope={"objective": "Goal"}, constraints={"allowed_paths": [invalid]}
        )


@pytest.mark.parametrize("invalid", [False, True, -1, "0", 0.0])
def test_init_revision_is_exact_integer_zero(invalid):
    with pytest.raises(ValidationError):
        InitArguments(idempotency_key="init", expected_revision=invalid, title="Draft", scope={"objective": "Goal"})


@pytest.mark.parametrize("value", ["null\x00byte", "surrogate\ud800"])
def test_nested_unsafe_text_is_rejected(value):
    with pytest.raises(ValidationError):
        InitArguments(idempotency_key="init", title="Draft", scope={"objective": "Goal", "in_scope": [value]})


def test_signed_bridge_is_purpose_bound_and_secret_safe():
    secret = "tool-secret-with-at-least-thirty-two-bytes"
    body = b'{"tool":"skilltree_get_status"}'
    signature = sign_contract_command(secret, "1700000000", body)
    settings = ContractBridgeSettings(secret=secret)
    settings.authenticate("1700000000", signature, body, now=1700000000)
    assert secret not in repr(settings)
    expect_code(
        "CONTRACT_BRIDGE_UNAUTHENTICATED",
        lambda: settings.authenticate("1700000000", signature, body + b" ", now=1700000000),
    )
    expect_code("CONTRACT_BRIDGE_EXPIRED", lambda: settings.authenticate("1700000000", signature, body, now=1700000600))
    expect_code(
        "CONTRACT_BRIDGE_NOT_CONFIGURED", lambda: ContractBridgeSettings(secret="short").authenticate("1", "x", body)
    )


def test_published_schemas_plugin_inventory_and_copies_match_models(scope):
    root = Path(__file__).resolve().parents[4]
    schemas = root / "adlc-contracts" / "documents" / "v0.1"
    plugin = root / "agent-harness-server" / "deepseek-harness" / "plugins" / "vai-adlc-skilltree"
    manifest = ContractPluginManifest.model_validate_json((plugin / "contract-plugin.json").read_bytes())
    assert {tool.name for tool in manifest.tools} == set(TOOL_ARGUMENT_MODELS)
    assert not manifest.renderer_available
    models = {
        "skilltree-document.schema.json": SkilltreeDocument,
        **{f"{name}.schema.json": model for name, model in TOOL_ARGUMENT_MODELS.items()},
    }
    for name, model in models.items():
        schema = json.loads((schemas / name).read_text(encoding="utf-8"))
        assert schema == {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://adlc.dev/contracts/documents/v0.1/{name}",
            **model.model_json_schema(),
        }
        Draft202012Validator.check_schema(schema)
        assert (plugin / "contracts" / name).read_bytes() == (schemas / name).read_bytes()
    document = create(ContractRepository(), scope).contract.document
    Draft202012Validator(
        json.loads((schemas / "skilltree-document.schema.json").read_text()), format_checker=FormatChecker()
    ).validate(document.model_dump(mode="json"))


def test_published_examples_and_explicitly_invalid_agent_payloads():
    root = Path(__file__).resolve().parents[4]
    examples = root / "adlc-contracts/documents/v0.1/examples"
    for name, model in [
        ("skilltree-init.json", InitArguments),
        ("skilltree-upsert-node.json", TOOL_ARGUMENT_MODELS["skilltree_upsert_node"]),
    ]:
        command = json.loads((examples / name).read_text(encoding="utf-8"))
        model.model_validate(command["arguments"])
    document = SkilltreeDocument.model_validate_json((examples / "skilltree-document.json").read_bytes())
    assert not structural_issues(document)
    assert validate_document(document, datetime.now(timezone.utc)).passed
    with pytest.raises(ValidationError):
        ContractBridgeCommand.model_validate_json((examples / "invalid-agent-approval.json").read_bytes())
    invalid = json.loads((examples / "invalid-agent-file.json").read_text(encoding="utf-8"))
    with pytest.raises(ValidationError):
        InitArguments.model_validate(invalid["arguments"])
