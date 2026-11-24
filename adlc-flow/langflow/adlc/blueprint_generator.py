"""AI blueprint generation through the DeepSeek Harness (DSH) web gateway.

The user submits a free-text requirement from the Blueprint request dialog.
This module composes one agent prompt that carries:

- the caller requirement (and optional extra instructions),
- the exact visible node-package catalogue (id, version, kind, interface),
- the required reply contract: a single ``blueprint.json`` file block.

The DSH session reply is parsed for the ``<adlc:file path="blueprint.json">``
block (the same capture convention the Harness executor uses for final
messages), validated against the registered packages, and mapped onto the
Langflow flow graph (``Flow.data``) as the ``WORKFLOW_DEFINITION/0.1`` marker,
``WORKFLOW_STAGE`` nodes and ``WORKFLOW_EDGE`` dependencies.

The user keeps full manual control after generation: stages and constraints
remain editable on the canvas exactly like hand-authored blueprints.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from langflow.adlc.harness_client import HarnessServerSettings

if TYPE_CHECKING:
    from dsh_web_sdk import DshClient

    from langflow.adlc.blueprints.models import NodePackageDefinition

BLUEPRINT_GENERATION_TIMEOUT_ENV = "ADLC_BLUEPRINT_DSH_GENERATION_TIMEOUT_SECONDS"
BLUEPRINT_DSH_BASE_URL_ENV = "ADLC_BLUEPRINT_DSH_BASE_URL"
BLUEPRINT_DSH_TOKEN_ENV = "ADLC_BLUEPRINT_DSH_TOKEN"  # noqa: S105 - environment variable name.
BLUEPRINT_FILE_PATH = "blueprint.json"

DEFAULT_GENERATION_TIMEOUT_SECONDS = 600.0
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_IDLE_GRACE_SECONDS = 5.0

STAGE_TYPE_BY_PACKAGE_KIND: dict[str, str] = {
    "AGENT": "IMPLEMENTATION",
    "TESTING": "TESTING",
    "REVIEW": "REVIEW",
    "APPROVAL": "APPROVAL",
    "ROUTER": "ROUTER",
    "JOIN": "JOIN",
}

_STAGE_NODE_PREFIX = "adlc-stage-"
_EDGE_ID_PREFIX = "adlc-edge-"

BLUEPRINT_CONFIGURATION_INVALID = "BLUEPRINT_GENERATION_CONFIGURATION_INVALID"
BLUEPRINT_NOT_CONFIGURED = "BLUEPRINT_GENERATION_NOT_CONFIGURED"
BLUEPRINT_SDK_UNAVAILABLE = "BLUEPRINT_GENERATION_SDK_UNAVAILABLE"
BLUEPRINT_REPLY_INVALID = "BLUEPRINT_REPLY_INVALID"
BLUEPRINT_REPLY_INVALID_JSON = "BLUEPRINT_REPLY_INVALID_JSON"
BLUEPRINT_REPLY_MISSING_FILE = "BLUEPRINT_REPLY_MISSING_FILE"
BLUEPRINT_REPLY_EMPTY = "BLUEPRINT_REPLY_EMPTY"
BLUEPRINT_APPLY_EMPTY = "BLUEPRINT_APPLY_EMPTY"
BLUEPRINT_DSH_FAILED = "BLUEPRINT_GENERATION_DSH_FAILED"
BLUEPRINT_MODEL_MISMATCH = "BLUEPRINT_MODEL_MISMATCH"
BLUEPRINT_TIMEOUT = "BLUEPRINT_GENERATION_TIMEOUT"

_FILE_BLOCK_PATTERN = re.compile(
    r'<adlc:file\s+path="(?P<path>[^"]+)"\s*>\s*\n(?P<content>.*?)\n?\s*</adlc:file\s*>',
    re.DOTALL,
)


class BlueprintGenerationError(Exception):
    """Raised when the DSH agent reply cannot produce an applicable blueprint."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int = 422,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details or {}


@dataclass(frozen=True, slots=True)
class BlueprintGenerationSettings:
    """Deployment settings for the DSH blueprint-generation transport."""

    base_url: str = "http://127.0.0.1:3080"
    api_token: str | None = None
    allow_insecure_http: bool = False
    request_timeout_seconds: float = 30.0
    generation_timeout_seconds: float = DEFAULT_GENERATION_TIMEOUT_SECONDS
    idle_grace_seconds: float = DEFAULT_IDLE_GRACE_SECONDS
    provider: str = "my-codex"
    model: str = "cx/gpt-5.6-luna"
    cwd: str | None = None
    agent_preset: str = "minimal"

    @classmethod
    def from_environment(cls) -> BlueprintGenerationSettings:
        base_url = (
            os.getenv(BLUEPRINT_DSH_BASE_URL_ENV) or os.getenv("ADLC_HARNESS_BASE_URL") or "http://127.0.0.1:3080"
        )
        # Web-gateway login and the ADLC plugin bearer use different credentials.
        # An unrelated plugin token must not be silently sent to the web login.
        token = os.getenv(BLUEPRINT_DSH_TOKEN_ENV) or None
        allow_insecure_http = (
            os.getenv("ADLC_BLUEPRINT_DSH_ALLOW_INSECURE_HTTP", "").strip().lower() in {"1", "true", "yes", "on"}
        ) or (os.getenv("ADLC_HARNESS_ALLOW_INSECURE_HTTP", "").strip().lower() in {"1", "true", "yes", "on"})
        try:
            generation_timeout = float(
                os.getenv(BLUEPRINT_GENERATION_TIMEOUT_ENV, "") or DEFAULT_GENERATION_TIMEOUT_SECONDS
            )
        except ValueError:
            generation_timeout = DEFAULT_GENERATION_TIMEOUT_SECONDS

        server = HarnessServerSettings(
            base_url=base_url,
            api_token=token,
            allow_insecure_http=allow_insecure_http,
        )
        return cls(
            base_url=server.base_url,
            api_token=server.api_token,
            allow_insecure_http=allow_insecure_http,
            request_timeout_seconds=server.request_timeout_seconds,
            generation_timeout_seconds=max(generation_timeout, 30.0),
            provider=os.getenv("ADLC_BLUEPRINT_PROVIDER", "my-codex"),
            model=os.getenv("ADLC_BLUEPRINT_MODEL", "cx/gpt-5.6-luna"),
            cwd=os.getenv("ADLC_BLUEPRINT_CWD") or None,
        )

    def validate(self) -> None:
        if not self.provider.strip() or not self.model.strip():
            raise BlueprintGenerationError(
                BLUEPRINT_CONFIGURATION_INVALID, "Blueprint provider/model must be explicit.", http_status=503
            )
        server = HarnessServerSettings(
            base_url=self.base_url, api_token=self.api_token, allow_insecure_http=self.allow_insecure_http
        )
        try:
            server.validate()
        except ValueError as exc:
            raise BlueprintGenerationError(
                BLUEPRINT_CONFIGURATION_INVALID,
                str(exc),
                http_status=503,
            ) from exc
        if not self.api_token:
            msg = "Configure ADLC_BLUEPRINT_DSH_TOKEN with the Harness web-gateway credential."
            raise BlueprintGenerationError(
                BLUEPRINT_NOT_CONFIGURED,
                msg,
                http_status=503,
            )


def _package_kind_value(package: NodePackageDefinition) -> str:
    return package.kind.value if hasattr(package.kind, "value") else str(package.kind)


def _package_catalogue_entries(packages: list[NodePackageDefinition]) -> list[dict[str, Any]]:
    return [
        {
            "package_id": package.package_id,
            "version": package.version,
            "name": package.name,
            "kind": _package_kind_value(package),
            "description": package.description,
            "inputs": [
                {
                    "name": slot.name,
                    "required": slot.required,
                    "schema_ref": slot.schema_ref,
                    "description": slot.description,
                }
                for slot in package.interface.inputs
            ],
            "outputs": [slot.name for slot in package.interface.outputs],
            "configuration_schema": package.configuration_schema,
        }
        for package in packages
    ]


def render_blueprint_prompt(
    requirement: str,
    packages: list[NodePackageDefinition],
    *,
    instructions: str | None = None,
    current_stages: list[dict[str, Any]] | None = None,
) -> str:
    """Compose the user prompt sent to the DSH agent session.

    Built on top of the shared :class:`dsh_web_sdk.prompt_builder.DshPrompt`
    standard so every ADLC prompt generator produces a payload that conforms
    to ``prompt_schema.json``.
    """
    catalogue = _package_catalogue_entries(packages)
    blueprint_shape = (
        "The blueprint JSON must match exactly this shape:\n"
        "{\n"
        '  "name": "Short human workflow name",\n'
        '  "stages": [\n'
        "    {\n"
        '      "key": "unique snake_case key referenced by edges",\n'
        '      "name": "Stage name",\n'
        '      "objective": "What this stage must accomplish",\n'
        '      "package_id": "exact package_id from the catalogue",\n'
        '      "version": "exact version from the catalogue",\n'
        '      "inputs": {},\n'
        '      "configuration_overrides": {},\n'
        '      "policy_overrides": {},\n'
        '      "execution_profile_overrides": {}\n'
        "    }\n"
        "  ],\n"
        '  "edges": [\n'
        '    {"from": "upstream stage key", "to": "downstream stage key"}\n'
        "  ]\n"
        "}"
    )
    rules = [
        "This is planning only: do not run commands, edit files, access external services, or start implementation.",
        "Use the supplied requirement and package catalogue; return the blueprint for a human to review.",
        "Use ONLY package_id@version pairs from the catalogue; never invent packages or versions.",
        "edges mean 'target depends on source'; keep the graph acyclic.",
        "inputs must only declare keys the package interface defines.",
        "Do not include secrets in inputs or configuration.",
        "The file block must contain complete, valid JSON and nothing else.",
    ]

    # Identify the default coding agent so the prompt can pin it explicitly.
    # Other agents in the catalogue are kept for reference but the prompt
    # tells DSH to prefer the unified coding agent for every stage.
    default_coding = next(
        (pkg for pkg in packages if pkg.package_id == "coding-agent" and pkg.version == "0.2.1"),
        None,
    )
    if default_coding is None:
        default_coding = next(
            (pkg for pkg in packages if pkg.package_id == "coding-agent" and pkg.version in {"0.2.0", "0.2.1"}),
            None,
        )

    if default_coding is not None:
        default_ref = f"{default_coding.package_id}@{default_coding.version}"
        rules.insert(
            0,
            (
                f"DEFAULT AGENT: Prefer '{default_ref}' when no package/version "
                "is explicitly requested. Honor an explicit compatible package/version "
                "from the supplied catalogue, including approval and testing gates. "
                "Packages outside the catalogue are not currently supported."
            ),
        )
        rules.insert(
            1,
            (
                "Do not override an explicitly requested package/version or widen "
                "its file scope, execution policy, approval gates or budget."
            ),
        )

    try:
        from dsh_web_sdk.prompt_builder import Catalogue, DshPrompt, FileSpec, PromptContext, ReplyContract
    except ModuleNotFoundError as exc:
        if exc.name and not exc.name.startswith("dsh_web_sdk"):
            raise
        # Keep pure rendering and injected transport tests usable without the
        # optional SDK. Real generation still requires DshClient below.
        return "\n".join(
            [
                "You are the ADLC blueprint planner.",
                "# Requirement",
                requirement.strip(),
                "# Extra instructions",
                instructions or "",
                "# Current blueprint stages",
                json.dumps(current_stages or [], ensure_ascii=False),
                "# Available node packages",
                json.dumps(catalogue, ensure_ascii=False, default=str),
                "# blueprint_shape",
                blueprint_shape,
                "# Rules",
                *rules,
                "# Reply contract",
                "Reply with a short summary and one complete blueprint JSON file block:",
                f'<adlc:file path="{BLUEPRINT_FILE_PATH}">',
                "...complete blueprint JSON...",
                "</adlc:file>",
            ]
        )
    context = PromptContext(
        current_state={"stages": current_stages} if current_stages else None,
        catalogues=[Catalogue(catalogue_id="node-packages", items=catalogue)],
        constraints={"blueprint_shape": blueprint_shape, "planning_only": True},
    )
    prompt = DshPrompt(
        role="the ADLC blueprint planner. Design an ADLC workflow blueprint for the requirement below",
        objective=requirement,
        instructions=instructions,
        context=context,
        reply_contract=ReplyContract(
            format="adlc-file-block",
            summary_required=True,
            files=[
                FileSpec(
                    path=BLUEPRINT_FILE_PATH,
                    format="json",
                    description="The complete blueprint document",
                )
            ],
            rules=rules,
        ),
    )
    return prompt.render()


def extract_blueprint_file(final_text: str) -> dict[str, Any]:
    """Extract and parse the ``blueprint.json`` file block from the reply."""
    for match in _FILE_BLOCK_PATTERN.finditer(final_text):
        path = match.group("path").strip().replace("\\", "/")
        if path != BLUEPRINT_FILE_PATH:
            continue
        content = match.group("content").strip()
        if not content:
            break
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            msg = "The DSH reply contained blueprint.json that is not valid JSON."
            raise BlueprintGenerationError(
                BLUEPRINT_REPLY_INVALID_JSON,
                msg,
                details={"parse_error": str(exc)},
            ) from exc
        if not isinstance(payload, dict):
            msg = "The blueprint file must be a JSON object."
            raise BlueprintGenerationError(BLUEPRINT_REPLY_INVALID, msg)
        return payload
    msg = f'The DSH reply did not include a <adlc:file path="{BLUEPRINT_FILE_PATH}"> block.'
    raise BlueprintGenerationError(
        BLUEPRINT_REPLY_MISSING_FILE,
        msg,
        details={"final_text_preview": final_text[:400]},
    )


def validate_blueprint_document(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate the top-level blueprint structure; returns (stages, edges)."""
    stages = payload.get("stages")
    if not isinstance(stages, list) or not stages:
        msg = "The blueprint must declare a non-empty 'stages' array."
        raise BlueprintGenerationError(BLUEPRINT_REPLY_INVALID, msg)
    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            msg = "Every blueprint stage must be an object."
            raise BlueprintGenerationError(
                BLUEPRINT_REPLY_INVALID,
                msg,
                details={"path": f"/stages/{index}"},
            )
    edges = payload.get("edges", [])
    if not isinstance(edges, list):
        msg = "The blueprint 'edges' must be an array when present."
        raise BlueprintGenerationError(BLUEPRINT_REPLY_INVALID, msg)
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            msg = "Every blueprint edge must be an object."
            raise BlueprintGenerationError(
                BLUEPRINT_REPLY_INVALID,
                msg,
                details={"path": f"/edges/{index}"},
            )
    return stages, edges


def _stage_inputs(raw_stage: dict[str, Any], package: NodePackageDefinition, warnings: list[str]) -> dict[str, Any]:
    raw_inputs = raw_stage.get("inputs")
    if raw_inputs is None:
        return {}
    if not isinstance(raw_inputs, dict):
        warnings.append(f"Stage '{raw_stage.get('key')}' declared non-object inputs; inputs were dropped.")
        return {}
    known = {slot.name for slot in package.interface.inputs}
    filtered = {key: value for key, value in raw_inputs.items() if key in known}
    dropped = sorted(set(raw_inputs) - known)
    if dropped:
        keys = ", ".join(dropped)
        msg = f"Stage '{raw_stage.get('key')}' declared inputs the package does not define ({keys}); they were dropped."
        warnings.append(msg)
    return filtered


def _edge_bindings(
    raw_edge: dict[str, Any],
    source_package: NodePackageDefinition,
    target_package: NodePackageDefinition,
    warnings: list[str],
) -> list[dict[str, str]]:
    raw_bindings = raw_edge.get("bindings")
    if raw_bindings is None:
        return []
    if not isinstance(raw_bindings, list):
        return []
    source_outputs = {slot.name for slot in source_package.interface.outputs}
    target_inputs = {slot.name for slot in target_package.interface.inputs}
    bindings: list[dict[str, str]] = []
    for binding in raw_bindings:
        if not isinstance(binding, dict):
            continue
        source_output = str(binding.get("source_output") or "").strip()
        target_input = str(binding.get("target_input") or "").strip()
        if source_output in source_outputs and target_input in target_inputs:
            bindings.append({"source_output": source_output, "target_input": target_input})
        else:
            warnings.append(
                f"Binding '{source_output or '?'} -> {target_input or '?'}' is not schema-compatible and was dropped."
            )
    return bindings


def _is_presentation_only(node: dict[str, Any]) -> bool:
    data = node.get("data")
    if isinstance(data, dict) and isinstance(data.get("adlc"), dict):
        return False
    return str(node.get("type") or "").lower() == "notenode"


def _topological_depths(
    stage_keys: list[str],
    edge_pairs: list[tuple[str, str]],
) -> tuple[dict[str, int], bool]:
    """Relax depths; a pass that still grows a depth means the graph has a cycle."""
    depth = dict.fromkeys(stage_keys, 0)
    for _ in range(len(stage_keys) + 1):
        changed = False
        for source, target in edge_pairs:
            if depth[target] < depth[source] + 1:
                depth[target] = depth[source] + 1
                changed = True
        if not changed:
            return depth, False
    return depth, True


def _layout_positions(depth_by_key: dict[str, int]) -> dict[str, dict[str, float]]:
    """Simple left-to-right layered layout: one column per topological depth."""
    columns: dict[int, list[str]] = {}
    for key, depth in depth_by_key.items():
        columns.setdefault(depth, []).append(key)
    positions: dict[str, dict[str, float]] = {}
    for depth in sorted(columns):
        for row, key in enumerate(columns[depth]):
            positions[key] = {"x": 80 + depth * 340, "y": 120 + row * 170}
    return positions


def apply_blueprint_to_flow_data(
    flow_data: dict[str, Any],
    blueprint: dict[str, Any],
    packages: list[NodePackageDefinition],
    *,
    flow_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Map a validated blueprint document onto the Langflow flow graph.

    Returns ``(updated_flow_data, stage_nodes, adlc_edges, warnings)``.
    Stages referencing unknown packages are skipped with a warning, together
    with every edge that references a skipped stage.
    """
    warnings: list[str] = []
    raw_stages, raw_edges = validate_blueprint_document(blueprint)

    packages_by_ref = {(package.package_id, package.version): package for package in packages}

    # Identify the default coding agent so we can warn when DSH picks
    # something else. Other agents are not currently supported.
    # Prefer 0.2.1 over 0.2.0 when both are available.
    default_coding_ref: tuple[str, str] | None = None
    for package in packages:
        if package.package_id == "coding-agent" and package.version == "0.2.1":
            default_coding_ref = (package.package_id, package.version)
            break
    if default_coding_ref is None:
        for package in packages:
            if package.package_id == "coding-agent" and package.version == "0.2.0":
                default_coding_ref = (package.package_id, package.version)
                break

    applied: list[tuple[str, dict[str, Any], NodePackageDefinition]] = []
    seen_keys: set[str] = set()
    for index, raw_stage in enumerate(raw_stages):
        key = str(raw_stage.get("key") or "").strip()
        package_id = str(raw_stage.get("package_id") or "").strip()
        version = str(raw_stage.get("version") or "").strip()
        if not key:
            msg = "Every generated stage requires a 'key'."
            raise BlueprintGenerationError(
                BLUEPRINT_REPLY_INVALID,
                msg,
                details={"path": f"/stages/{index}/key"},
            )
        if key in seen_keys:
            warnings.append(f"Stage key '{key}' is duplicated; only the first occurrence was applied.")
            continue
        package = packages_by_ref.get((package_id, version))
        if package is None:
            warnings.append(
                f"Stage '{key}' references unknown package {package_id or '?'}@{version or '?'} and was skipped."
            )
            continue
        # Warn when DSH picked a non-default agent. APPROVAL/REVIEW gates
        # are allowed to use their own packages.
        if (
            default_coding_ref is not None
            and (package_id, version) != default_coding_ref
            and _package_kind_value(package) not in {"APPROVAL", "REVIEW"}
        ):
            warnings.append(
                f"Stage '{key}' uses {package_id}@{version} which is not the "
                f"default coding agent ({default_coding_ref[0]}@{default_coding_ref[1]}). "
                "This agent may not be supported at runtime — consider switching "
                "to the default coding agent."
            )
        seen_keys.add(key)
        applied.append((key, raw_stage, package))

    if not applied:
        msg = "No generated stage referenced a known node package."
        raise BlueprintGenerationError(
            BLUEPRINT_APPLY_EMPTY,
            msg,
            details={"warnings": warnings},
        )

    valid_keys = {key for key, _, _ in applied}
    edge_pairs: list[tuple[dict[str, Any], str, str]] = []
    for raw_edge in raw_edges:
        source = str(raw_edge.get("from") or "").strip()
        target = str(raw_edge.get("to") or "").strip()
        if source not in valid_keys or target not in valid_keys:
            warnings.append(f"Edge '{source or '?'} -> {target or '?'}' references a skipped stage and was dropped.")
            continue
        if source == target:
            warnings.append("Self-dependency edges are not supported and were dropped.")
            continue
        edge_pairs.append((raw_edge, source, target))

    depth_by_key, has_cycle = _topological_depths(list(valid_keys), [(s, t) for _, s, t in edge_pairs])
    if has_cycle:
        warnings.append("The generated dependency graph contains a cycle; reconnect the stages manually.")

    positions = _layout_positions(depth_by_key)

    marker = flow_data.get("adlc")
    if not isinstance(marker, dict) or marker.get("document_type") != "WORKFLOW_DEFINITION":
        marker = {
            "document_type": "WORKFLOW_DEFINITION",
            "schema_version": "0.1",
            "workflow_definition_id": flow_id,
            "version": 1,
            "status": "DRAFT",
            "default_policies": {},
            "metadata": {},
        }
    marker["workflow_definition_id"] = flow_id

    presentation_nodes = [
        node for node in (flow_data.get("nodes") or []) if isinstance(node, dict) and _is_presentation_only(node)
    ]

    stage_nodes: list[dict[str, Any]] = []
    node_id_by_key: dict[str, str] = {}
    stage_contracts_by_key: dict[str, dict[str, Any]] = {}
    package_by_key: dict[str, NodePackageDefinition] = {}
    for key, raw_stage, package in applied:
        stage_id = str(uuid4())
        kind = _package_kind_value(package)
        name = str(raw_stage.get("name") or "").strip() or package.name
        objective = str(raw_stage.get("objective") or "").strip() or package.description or f"Complete {name}."
        contract = {
            "document_type": "WORKFLOW_STAGE",
            "schema_version": "0.1",
            "stage_id": stage_id,
            "stage_type": STAGE_TYPE_BY_PACKAGE_KIND.get(kind, "IMPLEMENTATION"),
            "name": name,
            "objective": objective,
            "inputs": _stage_inputs(raw_stage, package, warnings),
            "expected_outputs": [slot.name for slot in package.interface.outputs],
            "package_ref": {
                "package_id": package.package_id,
                "version": package.version,
            },
            "configuration_overrides": raw_stage.get("configuration_overrides")
            if isinstance(raw_stage.get("configuration_overrides"), dict)
            else {},
            "execution_profile_overrides": raw_stage.get("execution_profile_overrides")
            if isinstance(raw_stage.get("execution_profile_overrides"), dict)
            else {},
            "policy_overrides": raw_stage.get("policy_overrides")
            if isinstance(raw_stage.get("policy_overrides"), dict)
            else {},
            "secret_refs": {},
            "metadata": {"generated_by": "dsh-blueprint-request"},
        }
        node_id = f"{_STAGE_NODE_PREFIX}{stage_id}"
        node_id_by_key[key] = node_id
        stage_contracts_by_key[key] = contract
        package_by_key[key] = package
        stage_nodes.append(
            {
                "id": node_id,
                "type": "adlcStageNode",
                "position": positions.get(key, {"x": 80, "y": 120}),
                "data": {
                    "id": node_id,
                    "type": "adlcStage",
                    "adlc": contract,
                    "node": {
                        "description": objective,
                        "template": {},
                        "display_name": name,
                        "documentation": "",
                        "outputs": [],
                        "type": "adlcStage",
                    },
                },
            }
        )

    adlc_edges: list[dict[str, Any]] = []
    for raw_edge, source, target in edge_pairs:
        edge_id = str(uuid4())
        edge_contract = {
            "document_type": "WORKFLOW_EDGE",
            "schema_version": "0.1",
            "edge_id": edge_id,
            "condition": "ON_SUCCESS",
            "bindings": _edge_bindings(raw_edge, package_by_key[source], package_by_key[target], warnings),
            "metadata": {"generated_by": "dsh-blueprint-request"},
        }
        source_node_id = node_id_by_key[source]
        target_node_id = node_id_by_key[target]
        adlc_edges.append(
            {
                "id": f"{_EDGE_ID_PREFIX}{edge_id}",
                "source": source_node_id,
                "target": target_node_id,
                "type": "adlcEdge",
                "sourceHandle": "adlc-stage-output",
                "targetHandle": "adlc-stage-input",
                "reconnectable": False,
                "data": {
                    "adlc": edge_contract,
                    "sourceHandle": {
                        "dataType": "ADLC_DEPENDENCY",
                        "id": source_node_id,
                        "name": "dependency",
                        "output_types": ["ADLC_DEPENDENCY"],
                    },
                    "targetHandle": {
                        "fieldName": "dependency",
                        "id": target_node_id,
                        "name": "dependency",
                        "type": "ADLC_DEPENDENCY",
                        "inputTypes": ["ADLC_DEPENDENCY"],
                    },
                },
            }
        )

    updated_flow_data = dict(flow_data)
    updated_flow_data["adlc"] = marker
    updated_flow_data["nodes"] = presentation_nodes + stage_nodes
    updated_flow_data["edges"] = adlc_edges
    if not isinstance(updated_flow_data.get("viewport"), dict):
        updated_flow_data["viewport"] = {"x": 0, "y": 0, "zoom": 1}
    return updated_flow_data, stage_nodes, adlc_edges, warnings


async def generate_blueprint_document(
    requirement: str,
    packages: list[NodePackageDefinition],
    *,
    settings: BlueprintGenerationSettings,
    instructions: str | None = None,
    current_stages: list[dict[str, Any]] | None = None,
    dsh_client: DshClient | None = None,
) -> tuple[dict[str, Any], str]:
    """Run one DSH agent turn and return ``(blueprint_document, session_id)``."""
    settings.validate()
    prompt = render_blueprint_prompt(
        requirement,
        packages,
        instructions=instructions,
        current_stages=current_stages,
    )
    sdk_errors: tuple[type[Exception], ...] = ()
    try:
        from dsh_web_sdk import DshClient
        from dsh_web_sdk.errors import DshError
    except ModuleNotFoundError as exc:
        if dsh_client is None:
            msg = "Install the optional dsh_web_sdk to enable AI blueprint generation."
            raise BlueprintGenerationError(BLUEPRINT_SDK_UNAVAILABLE, msg, http_status=503) from exc
    else:
        sdk_errors = (DshError,)
    if dsh_client is not None:
        client = dsh_client
    else:
        from dsh_web_sdk import RetryConfig

        client = DshClient(
            settings.base_url,
            settings.api_token or "",
            timeout=settings.request_timeout_seconds,
            retry=RetryConfig(max_attempts=1),
        )
    try:
        async with client:
            session = await client.create_session(cwd=settings.cwd, agent_preset=settings.agent_preset)
            # Select and read back the route before the only model prompt. Never rely
            # on the last model clicked in the Harness UI, or silently fall back.
            route = await client.rpc(
                "session/selectModel",
                {
                    "request": {
                        "sessionId": session.session_id,
                        "provider": settings.provider,
                        "model": settings.model,
                    }
                },
            )
            selected = route.get("selected") or {}
            if selected.get("provider") != settings.provider or selected.get("model") != settings.model:
                raise BlueprintGenerationError(
                    BLUEPRINT_MODEL_MISMATCH, "Harness did not confirm the requested model.", http_status=502
                )
            if not await session.prompt(prompt):
                raise BlueprintGenerationError(
                    BLUEPRINT_DSH_FAILED, "Harness did not acknowledge the planning prompt.", http_status=502
                )
            # SDK 0.3.0 exposes poll_s/idle_s on wait(), not run().
            result = await session.wait(
                timeout_s=settings.generation_timeout_seconds,
                poll_s=DEFAULT_POLL_INTERVAL_SECONDS,
                idle_s=settings.idle_grace_seconds,
            )
    except sdk_errors as exc:
        cause = type(exc).__name__
        msg = f"The DSH web gateway failed to generate the blueprint ({cause})."
        raise BlueprintGenerationError(
            BLUEPRINT_DSH_FAILED,
            msg,
            http_status=502,
            details={"dsh_error": cause},
        ) from exc

    session_id = getattr(session, "session_id", "")
    final_text = result.get("final_text")
    if result.get("timeout"):
        msg = "The DSH blueprint session exceeded its time budget."
        raise BlueprintGenerationError(
            BLUEPRINT_TIMEOUT,
            msg,
            http_status=504,
            details={
                "session_id": session_id,
                "timeout_seconds": settings.generation_timeout_seconds,
            },
        )
    if not isinstance(final_text, str) or not final_text.strip():
        msg = "The DSH session ended without an assistant response."
        raise BlueprintGenerationError(
            BLUEPRINT_REPLY_EMPTY,
            msg,
            http_status=502,
            details={"session_id": session_id},
        )
    return extract_blueprint_file(final_text), session_id


def applied_stages_summary(stage_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Projection of applied stages returned to the caller for UI feedback."""
    summary = []
    for node in stage_nodes:
        contract = node["data"]["adlc"]
        summary.append(
            {
                "node_id": node["id"],
                "stage_id": contract["stage_id"],
                "name": contract["name"],
                "stage_type": contract["stage_type"],
                "package": f"{contract['package_ref']['package_id']}@{contract['package_ref']['version']}",
            }
        )
    return summary


def applied_edges_summary(adlc_edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary = []
    for edge in adlc_edges:
        contract = edge["data"]["adlc"]
        summary.append(
            {
                "edge_id": contract["edge_id"],
                "source": edge["source"],
                "target": edge["target"],
            }
        )
    return summary


def current_stages_projection(flow_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Compact stage list shared with the agent when editing an existing blueprint."""
    projection = []
    for node in flow_data.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        data = node.get("data")
        if not isinstance(data, dict):
            continue
        contract = data.get("adlc")
        if not isinstance(contract, dict) or contract.get("document_type") != "WORKFLOW_STAGE":
            continue
        projection.append(
            {
                "name": contract.get("name"),
                "objective": contract.get("objective"),
                "package": (
                    f"{(contract.get('package_ref') or {}).get('package_id')}"
                    f"@{(contract.get('package_ref') or {}).get('version')}"
                ),
            }
        )
    return projection


__all__ = [
    "BLUEPRINT_FILE_PATH",
    "BlueprintGenerationError",
    "BlueprintGenerationSettings",
    "applied_edges_summary",
    "applied_stages_summary",
    "apply_blueprint_to_flow_data",
    "current_stages_projection",
    "extract_blueprint_file",
    "generate_blueprint_document",
    "render_blueprint_prompt",
]
