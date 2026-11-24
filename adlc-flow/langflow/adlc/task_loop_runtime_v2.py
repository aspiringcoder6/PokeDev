"""Additive protocol v0.2: unknown monetary usage is null, never fabricated zero."""

from typing import Literal

from pydantic import TypeAdapter, model_validator

from langflow.adlc.task_loop_runtime_models import (
    LoopIterationOutcome,
    LoopIterationRequest,
    LoopRuntimeBinding,
    LoopRuntimeCheckpoint,
    LoopRuntimeSession,
    LoopRuntimeUsage,
    LoopRuntimeView,
)

PROTOCOL_V2 = "task-loop-runtime:iteration/0.2.0"


class LoopRuntimeBindingV2(LoopRuntimeBinding):
    protocol_ref: Literal["task-loop-runtime:iteration/0.2.0"] = PROTOCOL_V2
    cost_reporting: Literal["UNAVAILABLE"] = "UNAVAILABLE"


class LoopRuntimeUsageV2(LoopRuntimeUsage):
    cost: None


class LoopIterationRequestV2(LoopIterationRequest):
    schema_version: Literal["0.2"] = "0.2"
    runtime: LoopRuntimeBindingV2


class LoopRuntimeSessionV2(LoopRuntimeSession):
    schema_version: Literal["0.2"] = "0.2"
    runtime: LoopRuntimeBindingV2


class LoopIterationOutcomeV2(LoopIterationOutcome):
    schema_version: Literal["0.2"] = "0.2"
    runtime: LoopRuntimeBindingV2
    usage: LoopRuntimeUsageV2

    @model_validator(mode="after")
    def no_fabricated_price(self):
        if self.usage.cost is not None:
            message = "This runtime has no authoritative monetary usage"
            raise ValueError(message)
        return self


class LoopRuntimeCheckpointV2(LoopRuntimeCheckpoint):
    schema_version: Literal["0.2"] = "0.2"
    runtime: LoopRuntimeBindingV2
    session: LoopRuntimeSessionV2 | None = None
    usage: LoopRuntimeUsageV2 | None = None


class LoopRuntimeViewV2(LoopRuntimeView):
    schema_version: Literal["0.2"] = "0.2"
    runtime: LoopRuntimeBindingV2 | None = None
    protocol_ref: Literal["task-loop-runtime:iteration/0.2.0"] | None = None


BINDING = TypeAdapter(LoopRuntimeBinding | LoopRuntimeBindingV2)
VIEW = TypeAdapter(LoopRuntimeView | LoopRuntimeViewV2)


def runtime_models(binding):
    if binding.protocol_ref == PROTOCOL_V2:
        return (
            LoopIterationRequestV2,
            LoopRuntimeSessionV2,
            LoopIterationOutcomeV2,
            LoopRuntimeCheckpointV2,
            LoopRuntimeUsageV2,
        )
    return (LoopIterationRequest, LoopRuntimeSession, LoopIterationOutcome, LoopRuntimeCheckpoint, LoopRuntimeUsage)


def add_cost(left: float | None, right: float | None) -> float | None:
    return left + right if left is not None and right is not None else None
