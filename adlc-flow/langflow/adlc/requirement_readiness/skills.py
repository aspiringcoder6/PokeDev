from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .models import canonical_digest


@dataclass(frozen=True)
class NativePrerequisites:
    ready: bool
    code: str = ""
    skill_names: tuple[str, ...] = ()
    instruction_text: str = ""
    required_receipt_kinds: tuple[str, ...] = ()


@dataclass(frozen=True)
class NativeReceipt:
    id: str
    operation_id: str
    snapshot_digest: str
    artifact_digests: dict[str, str]
    step_name: str
    command_digest: str
    runtime_version: str
    exit_code: int
    observed_at: str
    run_id: str = ""
    output_digest: str = ""


class NativeAuthorizationRequired(ValueError):
    def __init__(self, request):
        super().__init__("READINESS_NATIVE_AUTHORIZATION_REQUIRED")
        self.request = request


class SkillCatalog:
    def __init__(self, root, native_manifest, store=None):
        self.root = Path(root).resolve()
        self.manifest = json.loads(json.dumps(native_manifest))
        self.store = store
        self.artifact_workspace = Path(self.manifest.get("artifact_workspace", self.root)).resolve()

    @property
    def digest(self):
        return canonical_digest(self.manifest)

    def path(self, relative):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise ValueError("READINESS_NATIVE_DEPENDENCY_MISSING")
        return path

    def checked(self, entry, digest):
        data = self.path(entry).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("READINESS_RUNTIME_CHANGED")
        return data.decode("utf-8")

    def read(self, name):
        row = self.manifest.get("skills", {}).get(name)
        if not row:
            raise ValueError("READINESS_NATIVE_DEPENDENCY_MISSING")
        return self.checked(row["entry"], row["sha256"])

    def verify(self):
        for row in self.manifest.get("skills", {}).values():
            self.checked(row["entry"], row["sha256"])
        for package in self.manifest.get("packages", {}).values():
            if not re.fullmatch(r"[0-9a-f]{40}", package.get("commit", "")) or not package.get("repository"):
                raise ValueError("READINESS_NATIVE_DEPENDENCY_MISSING")
            for relative, digest in package["files"].items():
                self.checked(relative, digest)
        if self.manifest.get("host_policy_file"):
            self.checked(self.manifest["host_policy_file"], self.manifest["host_policy_sha256"])

    def _instructions(self, entries, files):
        seen, chunks = set(), []

        def load(relative):
            relative = self.path(relative).relative_to(self.root).as_posix()
            if relative in seen:
                return
            seen.add(relative)
            if relative not in files:
                raise ValueError("READINESS_NATIVE_DEPENDENCY_MISSING")
            text = self.checked(relative, files[relative])
            chunks.append(f"\nTrusted file: {relative}\n{text}")
            prose = re.sub(r"```.*?```", "", text, flags=re.S)
            for link in re.findall(r"\]\(([^)\s]+\.md)(?:#[^)]*)?\)", prose):
                if "://" not in link:
                    candidate = (self.path(relative).parent / link).resolve()
                    if not candidate.is_relative_to(self.root):
                        raise ValueError("READINESS_NATIVE_DEPENDENCY_MISSING")
                    load(candidate.relative_to(self.root).as_posix())

        for entry in entries:
            load(entry)
        return "\n".join(chunks)

    def check_role(self, role):
        try:
            row = self.manifest.get("role_skills", {}).get(role)
            if not row or self.manifest.get("artifact_host") != "readiness-run-store":
                raise ValueError("READINESS_NATIVE_DEPENDENCY_MISSING")
            package = self.manifest["packages"][row["package"]]
            self.verify()
            instructions = self._instructions((row["entry"], *row.get("dependencies", ())), package["files"])
            overlay = self.checked(self.manifest["host_policy_file"], self.manifest["host_policy_sha256"])
            return NativePrerequisites(True, instruction_text=instructions + "\nTrusted host overlay:\n" + overlay)
        except (ValueError, KeyError, OSError):
            return NativePrerequisites(False, "READINESS_NATIVE_DEPENDENCY_MISSING")

    def check_route(self, route):
        try:
            row = self.manifest.get("routes", {}).get(route)
            if not row or not row.get("skills") or not row.get("required_steps"):
                raise ValueError("READINESS_NATIVE_DEPENDENCY_MISSING")
            instructions = "\n".join(self.read(name) for name in row["skills"])
            for step in row["required_steps"]:
                command = self.manifest["commands"][step]
                if not command.get("argv") or not shutil.which(command["argv"][0]):
                    raise ValueError("READINESS_NATIVE_DEPENDENCY_MISSING")
            return NativePrerequisites(
                True,
                skill_names=tuple(row["skills"]),
                instruction_text=instructions,
                required_receipt_kinds=tuple(row["required_steps"]),
            )
        except (ValueError, KeyError, OSError):
            return NativePrerequisites(False, "READINESS_NATIVE_DEPENDENCY_MISSING")

    def validate_receipts(self, ids, snapshot_digest, artifacts, route=None, run_id=None):
        if not self.store or not ids:
            return False
        try:
            digests = {}
            for name in artifacts:
                path = (self.artifact_workspace / name).resolve()
                if not path.is_relative_to(self.artifact_workspace) or not path.is_file():
                    return False
                digests[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            receipts = [self.store.receipt(identity) for identity in ids]
            if any(
                not row
                or row["snapshot_digest"] != snapshot_digest
                or row["exit_code"] != 0
                or row["artifact_digests"] != digests
                or row.get("run_id") != run_id
                or row["command_digest"] != canonical_digest(self.manifest["commands"][row["step_name"]])
                or not self.store.observe_operation(row["operation_id"])
                or self.store.observe_operation(row["operation_id"]).run_id != run_id
                or self.store.observe_operation(row["operation_id"]).role not in {"reviewer-a", "reviewer-b"}
                for row in receipts
            ):
                return False
            required = set(self.manifest.get("routes", {}).get(route, {}).get("required_steps", ()))
            return bool(required) and required <= {row["step_name"] for row in receipts}
        except (ValueError, KeyError, OSError):
            return False


class NativeCommandRunner:
    def __init__(self, catalog, store, artifact_workspace):
        self.catalog, self.store = catalog, store
        self.workspace = Path(artifact_workspace).resolve()

    def execute(self, step_name, snapshot_digest, artifact_bindings, *, operation_id=None):
        row = self.catalog.manifest.get("commands", {}).get(step_name)
        if not row:
            raise ValueError("READINESS_NATIVE_DEPENDENCY_MISSING")
        operation = self.store.observe_operation(operation_id) if operation_id else None
        if not operation or operation.role not in {"reviewer-a", "reviewer-b"}:
            raise ValueError("READINESS_OPERATION_BINDING_INVALID")
        request = {
            "step_name": step_name,
            "snapshot_digest": snapshot_digest,
            "operation_id": operation_id,
            "artifact_bindings": dict(artifact_bindings),
            "command_digest": canonical_digest(row),
        }
        authorization_id = canonical_digest(request)
        request["authorization_id"] = authorization_id
        if row.get("mode") != "read-only":
            allowed = self.store.observe_operation(authorization_id)
            if (
                row.get("mode") != "requires-authorization"
                or not allowed
                or allowed.state != "COMPLETED"
                or allowed.result.get("decision") != "allowed-once"
                or allowed.result.get("request") != request
            ):
                raise NativeAuthorizationRequired(request)
        argv = list(row["argv"])
        digests = {}
        for name, relative in artifact_bindings.items():
            path = (self.workspace / relative).resolve()
            if not path.is_relative_to(self.workspace) or not path.is_file():
                raise ValueError("READINESS_NATIVE_ARTIFACT_INVALID")
            digests[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
            argv = [arg.replace("{" + name + "}", str(path)) for arg in argv]
        if any("{" in arg or "}" in arg for arg in argv):
            raise ValueError("READINESS_NATIVE_ARTIFACT_INVALID")
        if not row.get("version_argv"):
            raise ValueError("READINESS_NATIVE_DEPENDENCY_MISSING")
        observed_version = subprocess.run(
            row["version_argv"], shell=False, cwd=self.workspace, timeout=30, capture_output=True
        )
        version = observed_version.stdout.decode("utf-8").strip()
        if observed_version.returncode or version != row["version"]:
            raise ValueError("READINESS_RUNTIME_CHANGED")
        native_key = authorization_id + ":execution"
        native = self.store.begin_operation(operation.run_id, native_key, "native-command", native_key)
        if native.state == "COMPLETED":
            saved = self.store.receipt(native.result["receipt_id"])
            return NativeReceipt(**saved)
        if not native.is_new:
            raise ValueError("READINESS_AGENT_UNCONFIRMED")
        result = subprocess.run(argv, shell=False, cwd=self.workspace, timeout=30, capture_output=True)
        # A claimed read-only check must leave its artifacts intact.
        if row.get("mode") == "read-only" and any(
            hashlib.sha256((self.workspace / name).read_bytes()).hexdigest() != digest
            for name, digest in digests.items()
        ):
            raise ValueError("READINESS_NATIVE_ARTIFACT_INVALID")
        receipt = NativeReceipt(
            str(uuid4()),
            operation_id,
            snapshot_digest,
            digests,
            step_name,
            canonical_digest(row),
            version,
            result.returncode,
            datetime.now(timezone.utc).isoformat(),
            operation.run_id,
            hashlib.sha256(result.stdout + result.stderr).hexdigest(),
        )
        self.store.save_receipt(asdict(receipt))
        self.store.finish_operation(native_key, {"receipt_id": receipt.id})
        return receipt
