"""Intent intake — turn raw requests into structured orchestrator intents (G3).

The intake gate is the control-plane entry point of the ADLC loop: a raw
feature idea / bug report / task description becomes an :class:`Intent`,
and the orchestrator plugin proposes an :class:`ExecutionPlan`. The
proposal is advisory only — nothing runs and nothing materializes until
the caller follows the existing plan approval and materialization path.

Classification is deliberately rule-based (verbalize → classify by
keyword, the Monarch Intent Gate spirit) with **no LLM call**; package
G4 will upgrade the plugin planning itself.
"""

from __future__ import annotations

from threading import RLock
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from langflow.adlc.orchestrator_plugin.host import get_production_host
from langflow.adlc.orchestrator_plugin.interface import (
    ExecutionPlan,
    Intent,
    IntentType,
)
from langflow.adlc.orchestrator_routing import orchestrator_routing_enabled
from langflow.adlc.resource_manager import AgentCapability

# Keyword heuristic per intent type, checked in order. The first type
# with a keyword hit wins; CODE_GENERATION is the catch-all default.
# Vietnamese and English keywords are supported on purpose (the ADLC
# UI defaults to Vietnamese).
_INTENT_KEYWORD_RULES: tuple[tuple[IntentType, tuple[str, ...]], ...] = (
    (
        IntentType.CODE_REVIEW,
        (
            "review",
            "code review",
            "audit",
            "soát",
            "rà soát",
            "đánh giá code",
        ),
    ),
    (
        IntentType.TESTING,
        (
            "test",
            "unit test",
            "pytest",
            "kiểm thử",
            "viết test",
            "kiểm tra lại",
        ),
    ),
    (
        IntentType.PLANNING,
        (
            "plan",
            "roadmap",
            "kiến trúc",
            "kế hoạch",
            "lập kế hoạch",
            "thiết kế",
        ),
    ),
    (
        IntentType.REFLECTION,
        (
            "retrospective",
            "reflect",
            "tổng kết",
            "rút kinh nghiệm",
        ),
    ),
    (
        IntentType.ORCHESTRATION,
        (
            "orchestrate",
            "coordinate",
            "điều phối",
            "phối hợp",
        ),
    ),
)

DEFAULT_INTENT_TYPE = IntentType.CODE_GENERATION

ORCHESTRATOR_ROUTING_DISABLED = "ORCHESTRATOR_ROUTING_DISABLED"


class IntentPlanProposalRequest(BaseModel):
    """Body of POST /api/v1/adlc/intents/plan-proposals."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=4096)
    intent_type: IntentType | None = None
    context: dict[str, str] = Field(default_factory=dict)
    required_capabilities: list[AgentCapability] = Field(default_factory=list)
    idempotency_key: str | None = Field(default=None, max_length=256)


class IntentRoutingDisabledError(RuntimeError):
    """Raised when the intake endpoint is used while routing is disabled."""

    code = ORCHESTRATOR_ROUTING_DISABLED

    def __init__(self) -> None:
        super().__init__(
            "Orchestrator routing is disabled; enable ADLC_ORCHESTRATOR_ROUTING to propose plans."
        )


def classify_intent(description: str) -> tuple[IntentType, list[str]]:
    """Classify one description into an IntentType by keyword matching.

    Returns the intent type plus the keywords that matched (audit trail).
    Falls back to CODE_GENERATION when no rule matches. No LLM involved.
    """
    text = description.lower()
    for intent_type, keywords in _INTENT_KEYWORD_RULES:
        hits = [keyword for keyword in keywords if keyword in text]
        if hits:
            return intent_type, hits
    return DEFAULT_INTENT_TYPE, []


def build_plan_proposal_payload(
    plan: ExecutionPlan,
    *,
    intent: Intent,
    classification_source: str,
    matched_keywords: list[str],
) -> dict:
    """Shape one ExecutionPlan into the public plan-proposal contract."""
    return {
        "plan_id": str(plan.plan_id),
        "intent_id": str(intent.intent_id),
        "intent_type": intent.intent_type.value,
        "classification": {
            "source": classification_source,
            "matched_keywords": matched_keywords,
            "heuristic": "keyword-rules-v1",
        },
        "plugin_id": plan.plugin_id,
        "steps": [
            {
                "step_id": str(step.step_id),
                "name": step.name,
                "description": step.description,
                "required_capabilities": sorted(
                    capability.value for capability in step.required_capabilities
                ),
                "depends_on": [str(dependency) for dependency in step.depends_on],
                "expected_outputs": list(step.expected_outputs),
            }
            for step in plan.steps
        ],
        "metadata": dict(plan.metadata),
        "created_at": plan.created_at.isoformat(),
    }


class IntentProposalStore:
    """Owner-scoped idempotency store for plan proposals.

    Same ``(owner_id, idempotency_key)`` replays the exact same proposal
    payload instead of dispatching a second plan. In-memory by design:
    proposals are advisory, never authoritative state.
    """

    def __init__(self) -> None:
        self._proposals: dict[tuple[str, str], dict] = {}
        self._lock = RLock()

    def get(self, owner_id: str, idempotency_key: str) -> dict | None:
        with self._lock:
            return self._proposals.get((owner_id, idempotency_key))

    def put(self, owner_id: str, idempotency_key: str, payload: dict) -> None:
        with self._lock:
            self._proposals[(owner_id, idempotency_key)] = payload

    def clear(self) -> None:
        with self._lock:
            self._proposals.clear()


_proposal_store: IntentProposalStore | None = None


def get_intent_proposal_store() -> IntentProposalStore:
    """Return the process-wide idempotency store for intent proposals."""
    global _proposal_store
    if _proposal_store is None:
        _proposal_store = IntentProposalStore()
    return _proposal_store


def reset_intent_proposal_store() -> None:
    """Reset the process-wide store (for tests)."""
    global _proposal_store
    _proposal_store = None


async def create_intent_plan_proposal(
    request: IntentPlanProposalRequest,
    *,
    owner_id: str,
) -> dict:
    """Classify the raw description and return one plugin plan proposal.

    Raises :class:`IntentRoutingDisabledError` when the orchestrator
    routing flag is off; the API layer maps it to a 503.
    """
    if not orchestrator_routing_enabled():
        raise IntentRoutingDisabledError

    store = get_intent_proposal_store()
    if request.idempotency_key:
        existing = store.get(owner_id, request.idempotency_key)
        if existing is not None:
            return existing

    if request.intent_type is not None:
        intent_type = request.intent_type
        classification_source = "explicit"
        matched_keywords: list[str] = []
    else:
        intent_type, matched_keywords = classify_intent(request.description)
        classification_source = "heuristic"

    intent = Intent(
        intent_type=intent_type,
        description=request.description,
        context=dict(request.context),
        required_capabilities=frozenset(request.required_capabilities),
        submitted_by=owner_id,
    )
    host = get_production_host()
    plan: ExecutionPlan = await host.dispatch_plan(intent)
    payload = build_plan_proposal_payload(
        plan,
        intent=intent,
        classification_source=classification_source,
        matched_keywords=matched_keywords,
    )
    if request.idempotency_key:
        store.put(owner_id, request.idempotency_key, payload)
    return payload


__all__ = [
    "DEFAULT_INTENT_TYPE",
    "IntentPlanProposalRequest",
    "IntentProposalStore",
    "IntentRoutingDisabledError",
    "ORCHESTRATOR_ROUTING_DISABLED",
    "classify_intent",
    "create_intent_plan_proposal",
    "get_intent_proposal_store",
    "reset_intent_proposal_store",
]
