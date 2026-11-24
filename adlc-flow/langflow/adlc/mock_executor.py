"""Compatibility execution facade composed from the four mock adapters."""

from __future__ import annotations

from langflow.adlc.adapter_interfaces import AdapterBundle, StateChangeCallback
from langflow.adlc.adapter_runtime import AdapterTaskExecutor
from langflow.adlc.mock_adapters import (
    MockAgentAdapter,
    MockMemoryAdapter,
    MockSandboxAdapter,
    MockTestingAdapter,
    deterministic_attempt_artifact_id,
    utc_now,
)


class MockExecutor(AdapterTaskExecutor):
    """Preserve the original executor entry point while using mock adapters."""

    service_name = MockAgentAdapter.service_name
    capabilities = MockAgentAdapter.capabilities

    def __init__(
        self,
        *,
        sandbox: MockSandboxAdapter | None = None,
        memory: MockMemoryAdapter | None = None,
        testing: MockTestingAdapter | None = None,
        agent: MockAgentAdapter | None = None,
    ) -> None:
        super().__init__(
            AdapterBundle(
                sandbox=sandbox or MockSandboxAdapter(),
                memory=memory or MockMemoryAdapter(),
                testing=testing or MockTestingAdapter(),
                agent=agent or MockAgentAdapter(),
            )
        )


__all__ = ["MockExecutor", "StateChangeCallback", "deterministic_attempt_artifact_id", "utc_now"]
