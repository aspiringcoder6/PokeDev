"""Opt-in backend composition. All operator files are reloaded at trust boundaries."""

import json
import os
from pathlib import Path

from langflow.adlc.source_access import build_source_gateway, resolve_project_grant

from .agent import ROLES, DshAgentRunner
from .models import HumanGatePolicy, PipelineConfig
from .service import ReadinessService
from .service_auth import revalidate_principal
from .skills import NativeCommandRunner, SkillCatalog
from .store import ReadinessStore


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def service_bindings():
    path = os.environ.get("ADLC_READINESS_SERVICE_BINDINGS_FILE")
    return load_json(path) if path else {"credentials": []}


def build_runtime():
    from dsh_web_sdk import DshClient
    from dsh_web_sdk.config import RetryConfig

    bindings_file = os.environ["ADLC_SOURCE_BINDINGS_FILE"]
    manifest_path = Path(os.environ["ADLC_READINESS_NATIVE_MANIFEST"])
    manifest = load_json(manifest_path)
    presets = manifest.get("presets", {})
    if (
        set(presets) != set(ROLES)
        or any(not isinstance(v, str) or not v.strip() for v in presets.values())
        or len(set(presets.values())) != len(ROLES)
    ):
        raise ValueError("READINESS_PRESETS_INVALID")
    path = Path(os.environ.get("ADLC_READINESS_STORE_PATH", "./data/requirement-readiness.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    store = ReadinessStore(path)
    skills = SkillCatalog(manifest_path.parent, manifest, store)
    skills.verify()
    gateway = build_source_gateway(load_json(bindings_file), lambda reference: os.environ[reference])

    def grants(run):
        return resolve_project_grant(run.principal_id, run.request.project_id, run.id, load_json(bindings_file))

    def policy(project):
        path = os.environ.get("ADLC_READINESS_HUMAN_GATE_POLICY_FILE")
        row = load_json(path).get("projects", {}).get(project) if path else None
        return HumanGatePolicy.model_validate(row) if row is not None else HumanGatePolicy()

    def principal(authenticated):
        return revalidate_principal(authenticated, service_bindings())

    agents = DshAgentRunner(
        DshClient(retry=RetryConfig(max_attempts=1)),
        store,
        Path(__file__).parent / "prompts",
        skills,
        presets,
        native_runner=NativeCommandRunner(skills, store, manifest.get("artifact_workspace", manifest_path.parent)),
    )
    config = PipelineConfig(
        max_context_rounds=int(os.environ.get("ADLC_CONTEXT_MAX_ROUNDS", "3")),
        max_tool_calls=int(os.environ.get("ADLC_SOURCE_MAX_READS", "24")),
        max_context_bytes=int(os.environ.get("ADLC_SOURCE_MAX_BYTES", "500000")),
    )
    return ReadinessService(store, agents, gateway, skills, grants, policy, None, config, principal)
