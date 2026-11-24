"""Real adapter implementations for production use.

This package contains real (non-mock) implementations of the ADLC
adapter interfaces. They are opt-in: the mock adapters remain the
default for backward compatibility.

Available adapters:
- PytestTestingAdapter: runs pytest on agent-generated code
- SQLiteMemoryAdapter: persistent memory backed by SQLite
- DockerSandboxAdapter: container-based isolation via Docker
"""

from langflow.adlc.adapters.docker_sandbox import (
    DockerSandboxAdapter,
    DockerSandboxConfig,
    DockerSandboxError,
)
from langflow.adlc.adapters.real_memory import (
    SQLiteMemoryAdapter,
    SQLiteMemoryConfig,
)
from langflow.adlc.adapters.real_testing import (
    PytestConfig,
    PytestTestingAdapter,
    TestOutcome,
)

__all__ = [
    "DockerSandboxAdapter",
    "DockerSandboxConfig",
    "DockerSandboxError",
    "PytestConfig",
    "PytestTestingAdapter",
    "SQLiteMemoryAdapter",
    "SQLiteMemoryConfig",
    "TestOutcome",
]
