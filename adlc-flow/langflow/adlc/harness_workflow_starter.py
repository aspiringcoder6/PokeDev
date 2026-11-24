"""A non-executing, digest-pinned workflow starter for the bounded GitHub profile."""

from uuid import uuid4

from langflow.adlc.blueprints.models import PackageReference
from langflow.adlc.harness_demo_models import REQUIREMENT
from langflow.adlc.harness_workflow import PACKAGES, VERSION
from langflow.adlc.packages.defaults import create_default_package_registry


def starter():
    registry = create_default_package_registry()
    nodes, edges = [], []
    requirement_id = "requirement-" + str(uuid4())
    nodes.append(
        {
            "id": requirement_id,
            "type": "adlcStageNode",
            "position": {"x": 50, "y": 150},
            "data": {
                "id": requirement_id,
                "type": "adlcAuthoring",
                "adlcDraft": {
                    "document_type": "ADLC_AUTHORING_BLOCK",
                    "schema_version": "0.1",
                    "block_id": str(uuid4()),
                    "kind": "REQUIREMENT",
                    "name": "Yêu cầu thay đổi",
                    "objective": "Sửa pagination trong phạm vi source và test đã khóa.",
                    "requirement": REQUIREMENT,
                },
                "node": {
                    "display_name": "Yêu cầu thay đổi",
                    "description": "Python pagination · một source, bốn test bảo vệ",
                    "template": {},
                    "outputs": [],
                    "documentation": "",
                },
            },
        }
    )
    stages = [
        (PACKAGES["PLAN"], "Harness · Soạn kế hoạch", {}),
        (
            "approval",
            "Duyệt kế hoạch",
            {"message": "Đọc kế hoạch và duyệt đúng digest trước khi agent sửa source.", "required_role": "maintainer"},
        ),
        (PACKAGES["EXECUTE"], "Agent · Sandbox, memory và Verify", {}),
        (
            "approval",
            "Duyệt commit",
            {
                "message": "Đọc diff và Verify; chỉ duyệt commit cho nhánh GitHub đã chỉ định, không phải main.",
                "required_role": "maintainer",
            },
        ),
        (PACKAGES["PUBLISH"], "Orchestrator · Push GitHub", {}),
    ]
    for index, (package_id, name, configuration) in enumerate(stages):
        package = registry.get(PackageReference(package_id=package_id, version=VERSION))
        node_id = "stage-" + str(uuid4())
        stage = {
            "document_type": "WORKFLOW_STAGE",
            "schema_version": "0.1",
            "stage_id": str(uuid4()),
            "stage_type": "APPROVAL" if package_id == "approval" else "IMPLEMENTATION",
            "name": name,
            "objective": package.definition.description,
            "inputs": {},
            "expected_outputs": [slot.name for slot in package.definition.interface.outputs],
            "package_ref": {"package_id": package_id, "version": VERSION, "content_digest": package.content_digest},
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
                "position": {"x": 380 + 330 * index, "y": 150},
                "data": {
                    "id": node_id,
                    "type": "adlcStage",
                    "adlc": stage,
                    "node": {
                        "display_name": name,
                        "description": stage["objective"],
                        "type": "adlcStage",
                        "template": {},
                        "outputs": [],
                        "documentation": "",
                    },
                },
            }
        )
        previous = nodes[-2]["id"]
        edges.append(
            {
                "id": "edge-" + str(uuid4()),
                "source": previous,
                "target": node_id,
                "type": "adlcEdge",
                "data": {
                    "adlc": {
                        "document_type": "WORKFLOW_EDGE",
                        "schema_version": "0.1",
                        "edge_id": str(uuid4()),
                        "condition": "ON_SUCCESS",
                        "bindings": [],
                        "metadata": {"authoring_input": "requirement"} if index == 0 else {},
                    }
                },
            }
        )
    return {
        "name": "Triển khai thay đổi lên GitHub",
        "description": (
            "Harness soạn plan → duyệt → skill, memory, sandbox và Verify → duyệt commit → "
            "push nhánh GitHub riêng. Hồ sơ Python pagination; không sửa main."
        ),
        "data": {
            "nodes": nodes,
            "edges": edges,
            "viewport": {"x": 0, "y": 0, "zoom": 0.7},
            "adlc": {
                "document_type": "WORKFLOW_DEFINITION",
                "schema_version": "0.1",
                "workflow_definition_id": "",
                "version": 1,
                "status": "DRAFT",
                "default_policies": {},
                "metadata": {"starter_ref": "workflow:harness-github-publication/0.1.0"},
            },
        },
    }
