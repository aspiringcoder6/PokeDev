"""Capability-keyed mock executors speaking executor contract v1.

These executors exist so mix-executor and contract tests can exercise
service routing without real runtimes (OpenCode, DSH). Each one
implements the stable ``AgentAdapter`` protocol and is composed behind
the scheduler's ``TaskExecutor`` port exactly like ``MockExecutor`` —
proving a future executor only needs the adapter protocol to plug in.

Contract v1 (see ``docs/reference/hop-dong-executor.md``):

* input: one ``TaskRequest`` (optionally carrying ``executor_contract``);
* output: one ``TaskResult`` whose payload is ``summary`` plus
  ``artifacts`` only — never conversation, transcripts, or subagent
  logs;
* behavior: honor the sandbox/memory context the plane provides, record
  the received contract in metadata for observability, and never call
  back into the control plane.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import uuid4

from langflow.adlc.adapter_interfaces import AdapterBundle, MemoryContext, SandboxSession
from langflow.adlc.adapter_runtime import AdapterTaskExecutor
from langflow.adlc.mock_adapters import (
    MockMemoryAdapter,
    MockSandboxAdapter,
    MockTestingAdapter,
    utc_now,
)
from langflow.adlc.models import (
    Artifact,
    Checksum,
    ExecutorContract,
    TaskMetrics,
    TaskRequest,
    TaskResult,
    TaskResultStatus,
)

OPENCODE_LIKE_SERVICE = "mock:opencode-like"
DSH_LIKE_SERVICE = "mock:dsh-like"

CONTRACT_OUTPUT_KEYS = frozenset({"summary"})
"""The only key contract-v1 executors may place inside ``TaskResult.output``."""


class CapabilityMockAgentAdapter:
    """Minimal ``AgentAdapter`` implementing executor contract v1."""

    def __init__(self, *, service_name: str, capabilities: tuple[str, ...]) -> None:
        self.service_name = service_name
        self.capabilities = tuple(capabilities)
        self.executed_requests: list[TaskRequest] = []
        self.seen_contracts: list[ExecutorContract | None] = []

    async def execute(
        self,
        request: TaskRequest,
        *,
        sandbox: SandboxSession,
        memory: MemoryContext,
    ) -> TaskResult:
        started_at = utc_now()
        self.executed_requests.append(request)
        contract = request.executor_contract
        self.seen_contracts.append(contract)

        completed_at = utc_now()
        summary = f"[{self.service_name}] completed {request.name}"
        artifact = self._build_artifact(request, summary, completed_at)
        return TaskResult(
            request_id=request.request_id,
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
            status=TaskResultStatus.SUCCEEDED,
            output={"summary": summary},
            artifacts=[artifact],
            error=None,
            metrics=TaskMetrics(duration_ms=0),
            started_at=started_at,
            completed_at=completed_at,
            metadata={
                "agent_adapter": self.service_name,
                "sandbox_session_id": sandbox.session_id,
                "memory_refs": list(memory.memory_refs),
                "contract_allowed_paths": list(contract.allowed_paths) if contract else [],
                "contract_denied_permissions": list(contract.denied_permissions) if contract else [],
                "contract_cost_tier": contract.cost_tier if contract else None,
            },
        )

    def _build_artifact(self, request: TaskRequest, summary: str, created_at: datetime) -> Artifact:
        content = summary.encode("utf-8")
        artifact_id = uuid4()
        return Artifact(
            artifact_id=artifact_id,
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
            kind="DOCUMENT",
            name=f"{self.service_name}-result.txt",
            media_type="text/plain",
            uri=f"mock://artifacts/{artifact_id}",
            size_bytes=len(content),
            checksum=Checksum(value=hashlib.sha256(content).hexdigest()),
            producer=self.service_name,
            created_at=created_at,
            metadata={"contract_v1": True},
        )


class CapabilityMockExecutor(AdapterTaskExecutor):
    """Compose a capability mock agent behind the scheduler TaskExecutor port."""

    def __init__(self, *, agent: CapabilityMockAgentAdapter) -> None:
        self.agent_adapter = agent
        super().__init__(
            AdapterBundle(
                sandbox=MockSandboxAdapter(),
                memory=MockMemoryAdapter(),
                testing=MockTestingAdapter(),
                agent=agent,
            )
        )


def create_capability_mock_executor(
    service_name: str, capabilities: tuple[str, ...]
) -> CapabilityMockExecutor:
    """Build one capability-keyed mock executor for router registration."""
    return CapabilityMockExecutor(
        agent=CapabilityMockAgentAdapter(service_name=service_name, capabilities=capabilities)
    )


def create_opencode_like_executor() -> CapabilityMockExecutor:
    """Executor shaped like a future OpenCode integration: code generation."""
    return create_capability_mock_executor(OPENCODE_LIKE_SERVICE, ("code_generation",))


def create_dsh_like_executor() -> CapabilityMockExecutor:
    """Executor shaped like a future DSH integration: security scanning."""
    return create_capability_mock_executor(DSH_LIKE_SERVICE, ("security_scan",))
