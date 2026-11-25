"""OpenSandbox lifecycle-server sandbox provider (via the opensandbox Python SDK).

The broker executes actions directly against the sandbox's built-in execd
agent (see `broker/services/opensandbox_executor.py`); this provider only
handles lifecycle (create / resume / terminate) and workspace volume seeding.
"""
import os
import subprocess
import datetime
from typing import Dict, List, Optional

from broker.state import logger

from broker.services.runtime.base import SandboxProvider
from broker.services.opensandbox_connection import sync_connection_config

try:
    import opensandbox
    from opensandbox.models.sandboxes import Volume, PVC
except ImportError:
    opensandbox = None


def prepare_workspace_volume(session_id: str, host_project_path: str) -> str:
    """Seed the host project into a docker named volume and return its name.

    Uses the local Docker CLI to create a named volume `sandbox-workspace-{session_id}`
    and fill it with an alpine copy of the host project: the OpenSandbox server's
    docker runtime maps PVC claim_names to docker volumes, so creating+seeding
    this volume is the mechanism that puts project files into the sandbox at
    /workspace. (The Docker CLI is required here even though sandboxes run on
    OpenSandbox — the OpenSandbox server itself launches containers via docker.)
    """
    abs_host_path = os.path.abspath(host_project_path)
    volume_name = f"sandbox-workspace-{session_id}"

    inspect_cmd = ["docker", "volume", "inspect", volume_name]
    res = subprocess.run(inspect_cmd, capture_output=True, text=True)
    if res.returncode != 0:
        logger.info(f"[Workspace] Creating Docker Named Volume '{volume_name}'...")
        create_res = subprocess.run(["docker", "volume", "create", volume_name], capture_output=True, text=True)
        if create_res.returncode != 0:
            raise RuntimeError(f"Failed to create Docker volume '{volume_name}': {create_res.stderr}")

        logger.info(f"[Workspace] Seeding project '{abs_host_path}' (read-only) into volume '{volume_name}'...")
        seed_cmd = [
            "docker", "run", "--rm",
            "-v", f"{volume_name}:/workspace",
            "-v", f"{abs_host_path}:/source:ro",
            "alpine",
            "sh", "-c", "cp -a /source/. /workspace/"
        ]
        seed_res = subprocess.run(seed_cmd, capture_output=True, text=True)
        if seed_res.returncode != 0:
            raise RuntimeError(f"Failed to seed project into Docker volume '{volume_name}': {seed_res.stderr}")
    return volume_name


class OpenSandboxProvider(SandboxProvider):
    """Sandbox backend driving an OpenSandbox lifecycle server via its SDK."""

    @property
    def name(self) -> str:
        return "opensandbox"

    def create_sandbox(
        self,
        session_id: str,
        project_path: Optional[str],
        image: str,
        ttl: int,
        cpu: str,
        memory: str,
        entrypoint: Optional[List[str]] = None,
        extensions: Optional[Dict[str, str]] = None,
    ) -> str:
        if opensandbox is None:
            raise RuntimeError("SANDBOX_PROVIDER=opensandbox but the opensandbox SDK is not installed")

        volumes = []
        if project_path and os.path.exists(project_path):
            volume_name = self.prepare_workspace(session_id, project_path)
            vol = Volume(
                name="workspace",
                pvc=PVC(claim_name=volume_name, create_if_not_exists=True),
                mount_path="/workspace",
                read_only=False
            )
            volumes.append(vol)

        res_limits = {"cpu": cpu, "memory": memory}

        logger.info(f"[Broker Provisioner] Creating OpenSandbox Container for session '{session_id}' (image='{image}', CPU={cpu}, Mem={memory}, TTL={'no expiry' if ttl <= 0 else ttl})...")
        sandbox = opensandbox.SandboxSync.create(
            image=image,
            volumes=volumes if volumes else None,
            resource=res_limits,
            timeout=datetime.timedelta(seconds=ttl) if ttl and ttl > 0 else datetime.timedelta(days=3650),
            entrypoint=entrypoint,
            extensions=extensions,
            skip_health_check=True
        )
        logger.info(f"[Broker Provisioner] Sandbox created successfully with ID: {sandbox.id}")
        return sandbox.id

    def start_sandbox(self, sandbox_id: str) -> bool:
        """Start (resume) a paused/stopped OpenSandbox sandbox.

        Returns True if resumed now, False if already healthy/running or if
        the start attempt failed.
        """
        if opensandbox is None:
            logger.warning("[Broker Provisioner] opensandbox SDK not installed, cannot start")
            return False
        try:
            sandbox = opensandbox.SandboxSync.connect(sandbox_id, connection_config=sync_connection_config(), skip_health_check=True)
            if sandbox.is_healthy():
                return False  # already running
            opensandbox.SandboxSync.resume(sandbox_id, skip_health_check=True)
            logger.info(f"[Broker Provisioner] OpenSandbox Container '{sandbox_id}' resumed.")
            return True
        except Exception as e:
            logger.warning(f"[Broker Provisioner] Failed to start OpenSandbox Container '{sandbox_id}': {e}")
            return False

    def terminate_sandbox(self, sandbox_id: str) -> bool:
        logger.info(f"[Broker Provisioner] Terminating sandbox '{sandbox_id}' (provider={self.name})...")
        if opensandbox is None:
            logger.warning("[Broker Provisioner] opensandbox SDK not installed, cannot terminate")
            return False
        try:
            sandbox = opensandbox.SandboxSync.connect(sandbox_id, connection_config=sync_connection_config(), skip_health_check=True)
            sandbox.kill()
            logger.info(f"[Broker Provisioner] OpenSandbox Container '{sandbox_id}' terminated successfully.")
            return True
        except Exception as e:
            logger.warning(f"[Broker Provisioner] Failed to kill OpenSandbox Container '{sandbox_id}': {e}")
            return False

    def _manager(self):
        """Manager-level SDK client (lifecycle ops, no retained handles).

        Uses the SDK's `create()` factory (default connection config) — the
        raw constructor requires prebuilt service objects.
        """
        return opensandbox.SandboxManagerSync.create()

    def pause_sandbox(self, sandbox_id: str) -> bool:
        if opensandbox is None:
            raise RuntimeError("opensandbox SDK is not installed")
        self._manager().pause_sandbox(sandbox_id)
        logger.info(f"[Broker Provisioner] Sandbox '{sandbox_id}' paused.")
        return True

    def resume_sandbox(self, sandbox_id: str) -> bool:
        if opensandbox is None:
            raise RuntimeError("opensandbox SDK is not installed")
        self._manager().resume_sandbox(sandbox_id)
        logger.info(f"[Broker Provisioner] Sandbox '{sandbox_id}' resumed.")
        return True

    def renew_sandbox(self, sandbox_id: str, ttl_seconds: int) -> dict:
        if opensandbox is None:
            raise RuntimeError("opensandbox SDK is not installed")
        resp = self._manager().renew_sandbox(
            sandbox_id, timeout=datetime.timedelta(seconds=int(ttl_seconds))
        )
        expires_at = getattr(resp, "expires_at", None)
        result = {"expiresAt": expires_at.isoformat()} if expires_at else {}
        logger.info(f"[Broker Provisioner] Sandbox '{sandbox_id}' renewed (+{ttl_seconds}s) -> {result}")
        return result

    def get_sandbox_metrics(self, sandbox_id: str) -> dict:
        if opensandbox is None:
            raise RuntimeError("opensandbox SDK is not installed")
        sandbox = opensandbox.SandboxSync.connect(sandbox_id, connection_config=sync_connection_config(), skip_health_check=True)
        metrics = sandbox.get_metrics()
        dump = getattr(metrics, "model_dump", None)
        return dump(mode="json") if dump else dict(metrics)

    def get_sandbox_diagnostics(self, sandbox_id: str, scope: str = "all") -> dict:
        if opensandbox is None:
            raise RuntimeError("opensandbox SDK is not installed")
        manager = self._manager()
        events = manager.get_diagnostic_events(sandbox_id, scope)
        logs = manager.get_diagnostic_logs(sandbox_id, scope)
        to_json = lambda obj: obj.model_dump(mode="json") if hasattr(obj, "model_dump") else str(obj)
        return {"events": to_json(events), "logs": to_json(logs)}

    def get_sandbox_endpoint(self, sandbox_id: str, port: int) -> dict:
        if opensandbox is None:
            raise RuntimeError("opensandbox SDK is not installed")
        sandbox = opensandbox.SandboxSync.connect(sandbox_id, connection_config=sync_connection_config(), skip_health_check=True)
        endpoint = sandbox.get_endpoint(port)
        return {"url": endpoint.endpoint}

    def prepare_workspace(self, session_id: str, host_project_path: str) -> str:
        """Seed the host project into the workspace volume and return its name.

        The OpenSandbox server's docker runtime maps PVC claim_names to docker
        volumes, so the seeded volume name doubles as the PVC claim_name.
        """
        return prepare_workspace_volume(session_id, host_project_path)
