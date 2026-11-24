"""Content-free passive reads of pinned runtime sidecars, including when dispatch is disabled."""

from __future__ import annotations

from typing import TYPE_CHECKING

from langflow.adlc.task_loop_runtime_models import LoopCandidateReference, LoopRuntimeView
from langflow.adlc.task_loop_runtime_v2 import BINDING, PROTOCOL_V2, LoopRuntimeViewV2
from langflow.adlc.task_loop_workspace import LiveLoopError

if TYPE_CHECKING:
    from langflow.adlc.models import TaskRequest
    from langflow.adlc.task_loop_store import TaskLoopStore


def inspect_runtime(store: TaskLoopStore, request: TaskRequest) -> LoopRuntimeView:
    state, attempts = store.inspect(request)
    if state is None:
        return LoopRuntimeView(
            workflow_run_id=request.workflow_run_id, task_run_id=request.task_run_id, binding_source="NOT_STARTED"
        )
    binding = BINDING.validate_python(state.runtime_binding) if state.runtime_binding else None
    for attempt in attempts:
        header = attempt.runtime_checkpoint
        if header is None:
            continue  # Existing checkpoint history is not relabelled as protocol-compliant.
        if (
            binding is None
            or header.runtime != binding
            or header.workflow_run_id != request.workflow_run_id
            or header.task_run_id != request.task_run_id
            or header.attempt_id != attempt.attempt_id
            or header.request_id != attempt.request_id
            or header.iteration != attempt.iteration
            or header.spec_digest != state.spec_digest
            or header.policy_digest != state.policy_digest
            or header.phase != attempt.phase
            or header.candidate != (LoopCandidateReference.of(attempt.candidate) if attempt.candidate else None)
            or (header.session.session_id if header.session else None) != attempt.session_id
        ):
            code = "TASK_LOOP_CHECKPOINT_CORRUPT"
            raise LiveLoopError(code)
    view_model = LoopRuntimeViewV2 if binding and binding.protocol_ref == PROTOCOL_V2 else LoopRuntimeView
    return view_model(
        workflow_run_id=request.workflow_run_id,
        task_run_id=request.task_run_id,
        binding_source="CHECKPOINT" if binding else "LEGACY",
        runtime=binding,
        protocol_ref=binding.protocol_ref if binding else None,
    )
