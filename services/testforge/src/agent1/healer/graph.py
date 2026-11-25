"""Healing Graph — LangGraph orchestration cho Self-healing (Bước 16-17, M3.2).

    START -> analyze --[APPLICATION_DEFECT]--> END (STOP SELF-HEALING)
            --[not healable]-----------------> END (NOT_HEALABLE)
            --[healable]---------------------> tier1
          tier1 --[proposal]-----------------> validate
                --[None]---------------------> tier2
          tier2 --[proposal]-----------------> validate
                --[None]---------------------> END (FAILED: no proposal)
          validate --[pass]------------------> retest
                  --[anti-cheat reject]------> END (REJECTED)
          retest --[PASS]--------------------> END (HEALED_PASS)
                --[FAIL, count >= max]------> END (FAILED_HEAL)
                --[FAIL, count < max]-------> tier2 (đổi tầng tránh vòng lặp proposal cũ)

Bất biến:
- analyze dùng FailureAnalyzer đã FROZEN từ M3.1 (6/6 dev + eval) — không tune
- validate là deterministic gate: chống sửa/bỏ assertion (anti-false-PASS)
- Tier 1 luôn deterministic; Tier 2 là chỗ duy nhất nối LLM (Ngày 3)
"""

import time
import uuid
import difflib
import re
from typing import Any, Callable, Dict, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from ..analyzer.failure_analyzer import FailureAnalyzer
from ..generator.static_validator import StaticValidator
from .state import (
    OUTCOME_FAILED,
    OUTCOME_HEALED_PASS,
    OUTCOME_NOT_HEALABLE,
    OUTCOME_REJECTED,
    OUTCOME_STOP_DEFECT,
    HealingState,
)
from .tier1_deterministic import Tier1DeterministicHealer
from .tier2_ai_recovery import Tier2AIRecovery

HEALABLE_TYPES = ("LOCATOR", "TIMING", "SCRIPT")


def action_only_patch(original: str, repaired: str) -> bool:
    """Conservative generated-code guard: only locator/action timeout replacements.

    Added/deleted lines, control flow, hooks, assertions and data changes are rejected.
    Complex patches require review rather than accepting arbitrary TypeScript.
    """
    quoted = r"'(?:[^'\\\r\n]|\\.)*'"
    locator = rf"page\.(?:getByRole|getByLabel|getByText|getByTestId|locator)\({quoted}(?:,\s*\{{\s*name:\s*{quoted}(?:,\s*exact:\s*true)?\s*\}})?\)"
    action = re.compile(rf"\s*await\s+({locator})\.(click|fill|selectOption)\((.*?)\);\s*")
    matcher = difflib.SequenceMatcher(a=original.splitlines(), b=repaired.splitlines())
    for tag, i, j, k, l in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag != "replace" or j-i != l-k:
            return False
        for before, after in zip(original.splitlines()[i:j], repaired.splitlines()[k:l]):
            a, b = action.fullmatch(before), action.fullmatch(after)
            if not a or not b or a[2] != b[2]:
                return False
            # Only a numeric timeout may change; fill/select values must remain identical.
            scrub = lambda args: re.sub(r"timeout:\s*\d+", "timeout:N", args)
            if scrub(a[3]) != scrub(b[3]):
                return False
    return True


def _now_ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _failed_step_ctx(test_case: Dict[str, Any], execution_result: Dict[str, Any]) -> Dict[str, Any]:
    """Lấy target/action của step gây lỗi (mặc định step 1)."""
    failed_step = execution_result.get("failed_step") or 1
    steps = test_case.get("steps") or []
    if 1 <= failed_step <= len(steps):
        step = steps[failed_step - 1]
    else:
        step = steps[0] if steps else {}
    return {
        "failed_step": failed_step,
        "target": step.get("target", ""),
        "action": step.get("action", ""),
    }


def build_healing_graph(
    retest_runner: Callable[[str, str], Dict[str, Any]],
    tier1_healer: Optional[Tier1DeterministicHealer] = None,
    tier2_healer: Optional[Any] = None,
    max_retries: int = 3,
):
    """Dựng compiled LangGraph healing. Invoke với HealingState initial.

    Args:
        retest_runner: Callable (test_case_id, repaired_script) -> {"status": "PASS"|"FAIL", ...}
        tier1_healer: Deterministic healer (mặc định Tier1DeterministicHealer)
        tier2_healer: Tier2 recovery (stub heuristic Ngày 1, LLM Ngày 3)
        max_retries: Số lần retest tối đa (Bước 17: 2-3)

    Returns:
        Compiled graph — invoke với HealingState, config thread_id cho checkpointer
    """
    tier1 = tier1_healer or Tier1DeterministicHealer()
    tier2 = tier2_healer or Tier2AIRecovery()

    # ---------------- Nodes ----------------
    def analyze_node(state: HealingState) -> Dict[str, Any]:
        exec_res = state["execution_result"]
        # Cho phép caller cung cấp analysis đã tính (unit test / pipeline reuse);
        # production path: chạy FailureAnalyzer FROZEN trên evidence thật (blind).
        precomputed = exec_res.get("_failure_analysis")
        analysis = precomputed or FailureAnalyzer.analyze(exec_res, state["test_case"])
        return {
            "failure_analysis": analysis,
            "retest_count": 0,
            "proposal": None,
            "proposal_source": "",
            "healing_events": [{
                "ts": _now_ts(),
                "stage": "analyze",
                "detail": f"classified={analysis['failure_type']} healable={analysis['healable']}",
            }],
        }

    def tier1_node(state: HealingState) -> Dict[str, Any]:
        ctx = _failed_step_ctx(state["test_case"], state["execution_result"])
        proposal = tier1.attempt_recovery(ctx["target"], ctx["action"], state["script_code"])
        if proposal:
            proposal = {**proposal, "failed_step": ctx["failed_step"]}
        return {
            "proposal": proposal,
            "proposal_source": "tier1" if proposal else "",
            "healing_events": state.get("healing_events", []) + [{
                "ts": _now_ts(),
                "stage": "tier1",
                "detail": f"proposal={'yes' if proposal else 'none'} target={ctx['target']} action={ctx['action']}",
            }],
        }

    def tier2_node(state: HealingState) -> Dict[str, Any]:
        ctx = _failed_step_ctx(state["test_case"], state["execution_result"])
        exec_res = state["execution_result"]
        ui_evidence = (exec_res or {}).get("ui_evidence") or {}
        proposal = tier2.generate_repair_proposal(
            state["test_case"],
            ctx["failed_step"],
            str((exec_res or {}).get("error") or ""),
            ui_evidence,
            state["script_code"],
            exclude_locators=state.get("tried_locators") or [],
        )
        if proposal:
            proposal = {**proposal, "failed_step": ctx["failed_step"]}
        tried = list(state.get("tried_locators") or [])
        if proposal and proposal.get("new_locator"):
            tried.append(proposal["new_locator"])
        return {
            "proposal": proposal,
            "proposal_source": "tier2" if proposal else "",
            "tried_locators": tried,
            "healing_events": state.get("healing_events", []) + [{
                "ts": _now_ts(),
                "stage": "tier2",
                "detail": f"proposal={'yes' if proposal else 'none'} strategy={proposal.get('strategy', '-') if proposal else '-'}",
            }],
        }

    def validate_node(state: HealingState) -> Dict[str, Any]:
        """Anti-cheat gate (deterministic): chống sửa assertion / hạ oracle."""
        proposal = state.get("proposal")
        script = state["script_code"]
        repaired = (proposal or {}).get("repaired_script") or ""
        reasons = []
        if not action_only_patch(script, repaired):
            reasons.append("patch_outside_locator_or_timeout")

        static_res = StaticValidator.validate(repaired, state["test_case"])
        if not static_res["valid"]:
            reasons.append("static_validation_failed:" + "; ".join(
                f"{e['code']}" for e in static_res["errors"][:3]
            ))
        if repaired.count("expect(") < script.count("expect("):
            reasons.append("assertion_removed")
        for exp in state["test_case"].get("expected_results") or []:
            # Oracle traceability (SV006 v2): assertion ĐÚNG NGHIỆP VỤ phải còn nguyên
            if exp and f"expect(page.getByText('{exp}'))" not in repaired:
                reasons.append(f"oracle_text_altered:{exp[:50]}")
        if (proposal or {}).get("confidence", 0) < 0.5:
            reasons.append("confidence_below_threshold")

        if reasons:
            return {
                "proposal": None,
                "outcome": OUTCOME_REJECTED,
                "rejected_reasons": state.get("rejected_reasons", []) + reasons,
                "healing_events": state.get("healing_events", []) + [{
                    "ts": _now_ts(),
                    "stage": "validate",
                    "detail": "REJECTED: " + "; ".join(reasons),
                }],
            }
        return {
            "healing_events": state.get("healing_events", []) + [{
                "ts": _now_ts(),
                "stage": "validate",
                "detail": f"OK source={state.get('proposal_source')} confidence={(proposal or {}).get('confidence')}",
            }],
        }

    def retest_node(state: HealingState) -> Dict[str, Any]:
        proposal = state["proposal"]
        result = retest_runner(state["test_case"].get("test_case_id", "TC"), proposal.get("repaired_script", ""))
        count = state.get("retest_count", 0) + 1
        analysis = FailureAnalyzer.analyze(result, state["test_case"]) if result.get("status") != "PASS" else state["failure_analysis"]
        outcome = OUTCOME_HEALED_PASS if result.get("status") == "PASS" else None
        if analysis.get("failure_type") == "APPLICATION_DEFECT":
            outcome = OUTCOME_STOP_DEFECT
        elif result.get("status") in ("ERROR", "SIMULATED", "SKIPPED") or (result.get("status") != "PASS" and not analysis.get("healable")):
            outcome = OUTCOME_FAILED
        return {
            "execution_result": result,
            "failure_analysis": analysis,
            "script_code": proposal.get("repaired_script", state["script_code"]),
            "retest_count": count,
            "retest_result": result,
            "outcome": outcome,
            "healing_events": state.get("healing_events", []) + [{
                "ts": _now_ts(),
                "stage": "retest",
                "detail": f"attempt={count} status={result.get('status')} source={state.get('proposal_source')}",
            }],
        }

    # ---------------- Routing ----------------
    def route_after_analyze(state: HealingState) -> str:
        fa = state.get("failure_analysis") or {}
        if fa.get("failure_type") == "APPLICATION_DEFECT":
            return "stop_defect"
        if fa.get("healable"):
            return "tier1"
        return "not_healable"

    def route_after_tier1(state: HealingState) -> str:
        return "validate" if state.get("proposal") else "tier2"

    def route_after_tier2(state: HealingState) -> str:
        return "validate" if state.get("proposal") else "no_proposal"

    def route_after_validate(state: HealingState) -> str:
        return "retest" if state.get("proposal") else "rejected"

    def route_after_retest(state: HealingState) -> str:
        if state.get("outcome") == OUTCOME_HEALED_PASS:
            return "healed"
        if state.get("outcome") in (OUTCOME_STOP_DEFECT, OUTCOME_FAILED):
            return "failed_max"
        if state.get("retest_count", 0) >= max_retries:
            return "failed_max"
        return "tier2"

    # ---------------- Graph ----------------
    builder = StateGraph(HealingState)
    builder.add_node("analyze", analyze_node)
    builder.add_node("tier1", tier1_node)
    builder.add_node("tier2", tier2_node)
    builder.add_node("validate", validate_node)
    builder.add_node("retest", retest_node)

    builder.set_entry_point("analyze")
    builder.add_conditional_edges("analyze", route_after_analyze, {
        "stop_defect": END,
        "tier1": "tier1",
        "not_healable": END,
    })
    builder.add_conditional_edges("tier1", route_after_tier1, {
        "validate": "validate",
        "tier2": "tier2",
    })
    builder.add_conditional_edges("tier2", route_after_tier2, {
        "validate": "validate",
        "no_proposal": END,
    })
    builder.add_conditional_edges("validate", route_after_validate, {
        "retest": "retest",
        "rejected": END,
        "no_proposal": END,
    })
    builder.add_conditional_edges("retest", route_after_retest, {
        "healed": END,
        "failed_max": END,
        "tier2": "tier2",
    })

    return builder.compile(checkpointer=MemorySaver())


def run_healing(
    test_case: Dict[str, Any],
    execution_result: Dict[str, Any],
    script_code: str,
    retest_runner: Optional[Callable[[str, str], Dict[str, Any]]] = None,
    tier1_healer: Optional[Tier1DeterministicHealer] = None,
    tier2_healer: Optional[Any] = None,
    max_retries: int = 3,
    thread_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Chạy healing graph cho 1 test case FAIL — entry point duy nhất cho pipeline.

    Returns:
        {"outcome", "proposal", "proposal_source", "retest_result",
         "retest_count", "healing_events", "failure_analysis"}
    """
    retest = retest_runner or _default_retest_stub
    graph = build_healing_graph(retest, tier1_healer, tier2_healer, max_retries)
    thread = thread_id or f"heal-{test_case.get('test_case_id', 'TC')}-{uuid.uuid4().hex[:8]}"

    initial: HealingState = {
        "test_case": test_case,
        "execution_result": execution_result,
        "script_code": script_code,
        "max_retries": max_retries,
        "retest_count": 0,
        "rejected_reasons": [],
        "tried_locators": [],
        "healing_events": [],
    }
    final = graph.invoke(initial, config={"configurable": {"thread_id": thread}})

    outcome = final.get("outcome")
    if not outcome:
        fa = final.get("failure_analysis") or {}
        if fa.get("failure_type") == "APPLICATION_DEFECT":
            outcome = OUTCOME_STOP_DEFECT
        elif not fa.get("healable", False):
            outcome = OUTCOME_NOT_HEALABLE
        elif final.get("proposal") is None and final.get("rejected_reasons"):
            outcome = OUTCOME_REJECTED
        else:
            outcome = OUTCOME_FAILED

    return {
        "outcome": outcome,
        "proposal": final.get("proposal"),
        "proposal_source": final.get("proposal_source", ""),
        "retest_result": final.get("retest_result"),
        "retest_count": final.get("retest_count", 0),
        "tried_locators": final.get("tried_locators", []),
        "healing_events": final.get("healing_events", []),
        "failure_analysis": final.get("failure_analysis", {}),
    }


def _default_retest_stub(test_case_id: str, repaired_script: str) -> Dict[str, Any]:
    """Retest stub mặc định (backward compatible với pipeline simulated)."""
    return {"test_case_id": test_case_id, "status": "ERROR", "error": "A real retest runner is required", "duration_ms": 0}
