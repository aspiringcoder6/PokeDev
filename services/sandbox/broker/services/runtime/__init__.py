"""Pluggable sandbox runtime providers.

Public surface:
    SandboxProvider        -- abstract backend interface
    get_provider()         -- env-selected (SANDBOX_PROVIDER) provider singleton
    OpenSandboxProvider    -- OpenSandbox lifecycle-server backend (Python SDK)
"""
from broker.services.runtime.base import SandboxProvider, get_provider
from broker.services.runtime.opensandbox_provider import OpenSandboxProvider

__all__ = [
    "SandboxProvider",
    "get_provider",
    "OpenSandboxProvider",
]
