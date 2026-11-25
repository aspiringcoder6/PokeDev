"""Pluggable sandbox runtime provider abstraction.

OpenSandbox is the only supported sandbox backend; it implements the
`SandboxProvider` interface. The broker routes talk to the interface only;
`get_provider()` resolves the provider from the `SANDBOX_PROVIDER`
environment variable (default: "opensandbox", the only supported value).
"""
import os
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from broker.state import logger


class SandboxProvider(ABC):
    """Abstract interface for sandbox lifecycle backends."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier, e.g. "opensandbox"."""

    @abstractmethod
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
        """Provision a sandbox for the session and return its sandbox_id
        (server-assigned sandbox ID). The optional entrypoint becomes the
        container CMD (the server overrides the image ENTRYPOINT); None lets
        the SDK default ("tail -f /dev/null") apply. Optional extensions map
        to OpenSandbox create extensions (e.g. bootstrap.execd.isolation)."""

    @abstractmethod
    def start_sandbox(self, sandbox_id: str) -> bool:
        """Resume a paused/stopped sandbox. True if resumed now, False if
        already running or the resume failed."""

    @abstractmethod
    def terminate_sandbox(self, sandbox_id: str) -> bool:
        """Terminate (and remove) a sandbox. True on success."""

    @abstractmethod
    def prepare_workspace(self, session_id: str, host_project_path: str) -> str:
        """Seed the host project into backend storage and return the volume /
        claim name to mount at /workspace."""

    # --- Optional lifecycle operations (raise NotImplementedError by default;
    # concrete providers implement them via their backend SDK) ---

    def pause_sandbox(self, sandbox_id: str) -> bool:
        """Pause a running sandbox. Raises on SDK failure."""
        raise NotImplementedError

    def resume_sandbox(self, sandbox_id: str) -> bool:
        """Resume a paused sandbox. Raises on SDK failure."""
        raise NotImplementedError

    def renew_sandbox(self, sandbox_id: str, ttl_seconds: int) -> dict:
        """Extend sandbox expiry by ttl_seconds from now. Returns
        {"expiresAt": <iso8601>} when the backend reports the new expiry.
        Raises on SDK failure."""
        raise NotImplementedError

    def get_sandbox_metrics(self, sandbox_id: str) -> dict:
        """Return sandbox resource metrics as a JSON-safe dict."""
        raise NotImplementedError

    def get_sandbox_diagnostics(self, sandbox_id: str, scope: str = "all") -> dict:
        """Return {"events": ..., "logs": ...} diagnostic payloads."""
        raise NotImplementedError

    def get_sandbox_endpoint(self, sandbox_id: str, port: int) -> dict:
        """Return {"url": ...} — the public endpoint of a service listening
        on `port` inside the sandbox. Raises on SDK failure."""
        raise NotImplementedError


# Known provider backends, imported lazily to avoid circular imports
# (concrete providers import this module for the SandboxProvider base class).
_KNOWN_PROVIDERS = ("opensandbox",)

# Module-level singleton cache, keyed by the resolved provider name.
_cached_provider: Optional[SandboxProvider] = None


def get_provider() -> SandboxProvider:
    """Return the SandboxProvider singleton selected by SANDBOX_PROVIDER.

    Reads `os.environ["SANDBOX_PROVIDER"]` (default "opensandbox",
    case-insensitive — the only supported value). Unknown values (e.g. legacy
    "docker", whose support was removed) log a warning and fall back to
    opensandbox. The instance is cached module-level; a changed env var swaps
    to the matching singleton.
    """
    from broker.services.runtime.opensandbox_provider import OpenSandboxProvider

    global _cached_provider
    provider_name = os.environ.get("SANDBOX_PROVIDER", "opensandbox").lower()
    if provider_name not in _KNOWN_PROVIDERS:
        logger.warning(
            f"[Runtime] Unknown SANDBOX_PROVIDER '{provider_name}' "
            f"(docker support was removed); using 'opensandbox'."
        )
        provider_name = "opensandbox"
    if _cached_provider is None or _cached_provider.name != provider_name:
        _cached_provider = OpenSandboxProvider()
    return _cached_provider
