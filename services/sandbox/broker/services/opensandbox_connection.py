"""Shared OpenSandbox SDK connection settings for the broker.

By default the SDK reaches sandbox execd DIRECTLY (the sandbox container's
bridge IP:port, resolved via the lifecycle server's endpoint API). That path
breaks on servers where the broker cannot reach the sandbox network — firewalled
hosts (ufw/iptables dropping host->bridge traffic), Docker-in-Docker lifecycle
servers, or rootless Docker.

Setting OPENSANDBOX_USE_SERVER_PROXY=1 switches execd traffic (run commands,
file sync, metrics) to the lifecycle server's proxy route instead: requests go
to the same localhost:8080 hop that create/kill/lifecycle calls already use,
and the server forwards them into the sandbox over its own network access.
All business requests still enter through the broker — this only changes the
broker's internal transport to execd.
"""
import os

_TRUTHY = {"1", "true", "yes", "on"}


def use_server_proxy() -> bool:
    """Whether execd traffic should be routed via the lifecycle server proxy."""
    return os.getenv("OPENSANDBOX_USE_SERVER_PROXY", "").strip().lower() in _TRUTHY


def async_connection_config():
    """ConnectionConfig for the async SDK, or None to keep SDK defaults."""
    if not use_server_proxy():
        return None
    from opensandbox.config import ConnectionConfig

    return ConnectionConfig(use_server_proxy=True)


def sync_connection_config():
    """ConnectionConfigSync for the sync SDK, or None to keep SDK defaults."""
    if not use_server_proxy():
        return None
    from opensandbox.config import ConnectionConfigSync

    return ConnectionConfigSync(use_server_proxy=True)
