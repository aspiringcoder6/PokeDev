"""Published plugin node templates; creation does not execute a backend job."""

from uuid import uuid4

from langflow.adlc.blueprints.models import PackageReference
from langflow.adlc.packages.defaults import create_default_package_registry


def starter(*, check_only=False):
    registry = create_default_package_registry()
    package_ids = (
        ["workflow-plugin-check"]
        if check_only
        else [
            "workflow-plugin-check",
            "agent-memory-context",
            "testforge-replay",
        ]
    )
    nodes, edges = [], []
    for index, package_id in enumerate(package_ids):
        package = registry.get(PackageReference(package_id=package_id, version="0.1.0"))
        node_id = "plugin-stage-" + str(uuid4())
        definition = package.definition
        configuration = (
            {"query": "Bối cảnh kiến trúc và yêu cầu của project vAIPlatform"}
            if package_id == "agent-memory-context"
            else {}
        )
        stage = {
            "document_type": "WORKFLOW_STAGE",
            "schema_version": "0.1",
            "stage_id": str(uuid4()),
            "stage_type": "TESTING" if package_id == "testforge-replay" else "IMPLEMENTATION",
            "name": definition.name,
            "objective": definition.description,
            "inputs": {},
            "expected_outputs": [slot.name for slot in definition.interface.outputs],
            "package_ref": {"package_id": package_id, "version": "0.1.0", "content_digest": package.content_digest},
            "configuration_overrides": configuration,
            "execution_profile_overrides": {},
            "policy_overrides": {},
            "secret_refs": {},
            "metadata": {},
        }
        nodes.append(
            {
                "id": node_id,
                "type": "adlcStageNode",
                "position": {"x": 80 + index * 360, "y": 160},
                "data": {
                    "id": node_id,
                    "type": "adlcStage",
                    "adlc": stage,
                    "node": {
                        "display_name": definition.name,
                        "description": definition.description,
                        "type": "adlcStage",
                        "template": {},
                        "outputs": [],
                        "documentation": "",
                    },
                },
            }
        )
        if index:
            edges.append(
                {
                    "id": "edge-" + str(uuid4()),
                    "source": nodes[index - 1]["id"],
                    "target": node_id,
                    "type": "adlcEdge",
                    "data": {
                        "adlc": {
                            "document_type": "WORKFLOW_EDGE",
                            "schema_version": "0.1",
                            "edge_id": str(uuid4()),
                            "condition": "ON_SUCCESS",
                            "bindings": [],
                            "metadata": {},
                        }
                    },
                }
            )
    return {
        "name": "Kiểm tra plugin trong workflow" if check_only else "AgentMemory và TestForge",
        "description": "Kiểm tra kết nối → lấy ngữ cảnh project → chạy replay đã cấu hình. Kết quả được giữ theo run; không thay phán quyết Verify.",
        "data": {
            "nodes": nodes,
            "edges": edges,
            "viewport": {"x": 0, "y": 0, "zoom": 0.8},
            "adlc": {
                "document_type": "WORKFLOW_DEFINITION",
                "schema_version": "0.1",
                "workflow_definition_id": "",
                "version": 1,
                "status": "DRAFT",
                "default_policies": {},
                "metadata": {"starter_ref": "workflow:plugins/0.1.0"},
            },
        },
    }
