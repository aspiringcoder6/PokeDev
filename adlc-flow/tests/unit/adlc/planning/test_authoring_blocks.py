# ruff: noqa: S101, PLR2004
from copy import deepcopy

import pytest

from langflow.adlc.planning.authoring import prepare_authoring_graph
from langflow.adlc.planning.errors import BlueprintParseError


def _graph():
    return {
        "nodes": [
            {
                "id": "brief",
                "type": "adlcStageNode",
                "data": {
                    "adlcDraft": {
                        "document_type": "ADLC_AUTHORING_BLOCK",
                        "schema_version": "0.1",
                        "block_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                        "kind": "REQUIREMENT",
                        "name": "Requirement",
                        "objective": "Implement the request.",
                        "requirement": "Add a user endpoint and verify it.",
                    }
                },
            },
            {"id": "coding", "data": {"adlc": {"document_type": "WORKFLOW_STAGE", "inputs": {}}}},
        ],
        "edges": [
            {
                "id": "edge-1",
                "source": "brief",
                "target": "coding",
                "data": {
                    "adlc": {
                        "document_type": "WORKFLOW_EDGE",
                        "edge_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                        "schema_version": "0.1",
                        "condition": "ON_SUCCESS",
                        "bindings": [],
                        "metadata": {"authoring_input": "requirement"},
                    }
                },
            }
        ],
    }


def test_requirement_is_literal_input_with_provenance_and_source_is_unchanged():
    graph = _graph()
    original = deepcopy(graph)
    resolved = prepare_authoring_graph(graph)
    assert graph == original
    assert [n["id"] for n in resolved["nodes"]] == ["coding"]
    assert resolved["edges"] == []
    stage = resolved["nodes"][0]["data"]["adlc"]
    assert stage["inputs"] == {"requirement": "Add a user endpoint and verify it."}
    assert stage["metadata"]["authoring_inputs"]["requirement"]["block_id"] == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def test_requirement_can_supply_independent_named_stage_inputs():
    graph = _graph()
    graph["nodes"].append({"id": "second", "data": {"adlc": {"document_type": "WORKFLOW_STAGE", "inputs": {}}}})
    edge = deepcopy(graph["edges"][0])
    edge["id"], edge["target"] = "edge-2", "second"
    graph["edges"].append(edge)
    resolved = prepare_authoring_graph(graph)
    assert len(resolved["nodes"]) == 2
    assert resolved["nodes"][0]["data"]["adlc"]["inputs"] == resolved["nodes"][1]["data"]["adlc"]["inputs"]


def test_wip_cannot_enter_the_execution_parser_even_when_flagged_executable():
    graph = _graph()
    graph["nodes"][0]["data"]["adlcDraft"].update(
        kind="PLANNED_PACKAGE", proposed_package_id="security-scan", executable=True
    )
    with pytest.raises(BlueprintParseError) as exc:
        prepare_authoring_graph(graph)
    assert exc.value.issues[0].code == "AUTHORING_PACKAGE_WIP"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda g: g["nodes"][0]["data"]["adlcDraft"].update(schema_version="99"),
        lambda g: g["nodes"][0]["data"].update(adlc={"document_type": "WORKFLOW_STAGE"}),
        lambda g: g["nodes"][0]["data"]["adlcDraft"].update(kind="UNKNOWN"),
        lambda g: g["nodes"][0]["data"]["adlcDraft"].update(requirement=""),
        lambda g: g["nodes"][0]["data"]["adlcDraft"].update(requirement="x" * 20001),
        lambda g: g.update(edges=[]),
        lambda g: g["edges"][0].update(target="missing"),
        lambda g: g["edges"][0].update(target="brief"),
        lambda g: g["edges"][0].update(source=[]),
        lambda g: g["edges"][0].update(data="bad"),
        lambda g: g["edges"][0]["data"]["adlc"].update(metadata="bad"),
        lambda g: g["edges"][0]["data"]["adlc"].update(
            bindings=[{"source_output": "fake", "target_input": "requirement"}]
        ),
        lambda g: g["nodes"][1]["data"]["adlc"].update(inputs={"requirement": "Existing direct input"}),
        lambda g: g["nodes"][1]["data"]["adlc"].update(metadata={"authoring_inputs": "bad"}),
        lambda g: g["edges"].append(deepcopy(g["edges"][0])),
        lambda g: g["nodes"].append(deepcopy(g["nodes"][0])),
    ],
)
def test_invalid_authoring_inputs_fail_closed(mutation):
    graph = _graph()
    mutation(graph)
    with pytest.raises(BlueprintParseError):
        prepare_authoring_graph(graph)


def test_graphs_without_authoring_blocks_keep_the_original_parser_path():
    graph = {"nodes": [{"id": "existing", "data": {"adlc": {"document_type": "WORKFLOW_STAGE"}}}], "edges": []}
    assert prepare_authoring_graph(graph) is graph
