"""Explorer: điều hướng từng Gherkin step qua navigator, ground + record mỗi bước.

Vòng lặp một bước (docs/20 G1):
    step text -> navigator đề xuất action -> grounding trên ARIA snapshot thật
    -> executor chạy Playwright high-level (bounded) -> TraceRecorder ghi evidence
    -> POST 2xx được tự động nhận diện thành owned candidate (persist ngay).

Tier-3 HITL (docs/20): step DEVIATED/FAILED -> hỏi QA một locator thủ công
(overlay in-page hoặc stdin) -> retry bounded; trace ghi source:"human".
"""
import re
from pathlib import Path

from .grounding import chosen_element, js_locator_expr, locator_candidates, parse_snapshot
from .hitl import (
    HITL_MAX_RETRIES,
    manual_candidate,
    manual_element,
    manual_js_expr,
    parse_manual_locator,
)
from .navigator import NavigationError
from .session import ExplorerError

_PROBE_ACTION = "PROBE"
_STEP_ACTIONS = {"CLICK": True, "FILL": True, "SELECT": True, "SUBMIT": True}


def parse_feature(path):
    """Parser Gherkin tối giản: Feature name + Tags + Background + Scenario + step text.

    Tags dòng `@...` phía trên Scenario gắn định danh theo convention kiến trúc:
    @TC-xxx -> test_case_id, @FUNC-xxx -> function_id, @REQ-xxx -> requirement_refs.
    Background steps được chèn đầu mỗi scenario với step_id đánh số lại
    (STEP-<scenario>-<i>) để trace/coverage_gate khớp từng dòng scenario.
    """
    scenarios = []
    background = []
    current = None
    in_background = False
    feature_name = ""
    pending_tags = []
    last_keyword = "Given"
    for raw in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line.startswith("@"):
            pending_tags.extend(t for t in line.split() if len(t) > 1)
            continue
        if line.startswith("Feature:"):
            feature_name = line.split(":", 1)[1].strip()
            continue
        if line.startswith("Background:"):
            in_background = True
            background = []
            last_keyword = "Given"
        elif line.startswith("Scenario:"):
            in_background = False
            if current is not None:
                scenarios.append(current)
            tags = list(pending_tags)
            pending_tags = []
            current = {
                "name": line.split(":", 1)[1].strip(), "steps": [], "tags": tags,
                "feature_name": feature_name,
                "test_case_id": next((t[1:] for t in tags if t.startswith("@TC-")), None),
                "function_id": next((t[1:] for t in tags if t.startswith("@FUNC-")), None),
                "requirement_refs": [t[1:] for t in tags if t.startswith("@REQ-")],
            }
            for index, bg_step in enumerate(background):
                current["steps"].append({
                    **bg_step,
                    "step_id": "STEP-{0}-{1}".format(len(scenarios) + 1, index + 1),
                })
            last_keyword = "Given"
        elif current is not None or in_background:
            match = re.match(r"^(Given|When|Then|And|But)\s+", line)
            if not match:
                continue
            keyword = match.group(1)
            if keyword not in ("And", "But"):
                last_keyword = keyword
            text = re.sub(r"^(Given|When|Then|And|But)\s+", "", line)
            step = {"text": text, "keyword": last_keyword}
            if in_background:
                background.append(step)
            else:
                step["step_id"] = "STEP-{0}-{1}".format(
                    len(scenarios) + 1, len(current["steps"]) + 1)
                current["steps"].append(step)
    if current is not None:
        scenarios.append(current)
    return scenarios


class Explorer:
    def __init__(self, session, driver, recorder, navigator, executor, cleanup_template=None,
                 assist=None):
        self.session = session
        self.driver = driver
        self.recorder = recorder
        self.navigator = navigator
        self.executor = executor
        self.cleanup_template = cleanup_template or ""
        self.assist = assist
        self._owned_cursor = 0
        self._last_manual_raw = None

    def run_scenario(self, scenario):
        for step in scenario["steps"]:
            self._run_step(step)
        required = [s["step_id"] for s in scenario["steps"]]
        return self.recorder.coverage_gate(required)

    def _substitute(self, text):
        short_id = self.session.run_id.split("-", 1)[-1][:8]
        return text.replace("${run_id}", self.session.run_id).replace("${run_id_short}", short_id)

    def _run_step(self, step):
        text = self._substitute(step["text"])
        snapshot = self.driver.aria_snapshot()
        try:
            decision = self.navigator.propose(text, snapshot, self.driver.url())
        except NavigationError as exc:
            self.recorder.record(
                step["step_id"], text, _PROBE_ACTION, _raise_action(exc),
                status_if_ok="FAILED", target="")
            return

        element = None
        candidates = []
        chosen_expr = ""
        if decision.selected_action in _STEP_ACTIONS:
            candidates = locator_candidates(parse_snapshot(snapshot), decision.target,
                                            decision.selected_action)
            if candidates:
                element = chosen_element(candidates[0])
                chosen_expr = js_locator_expr(element)
            elif self.assist is None:
                error = "Target not found in ARIA snapshot: '{0}'".format(decision.target)
                self.recorder.record(step["step_id"], text, decision.selected_action,
                                     _raise_action(ValueError(error)), status_if_ok="FAILED",
                                     target=decision.target)
                return

        timeout_ms = self.recorder.step_deadline_ms
        attempt = 0
        hitl_notes = []
        navigator_note = {"source": decision.source}
        if decision.reasoning:
            navigator_note["reasoning"] = decision.reasoning[:200]
        if decision.value and decision.selected_action in ("FILL", "SELECT", "ASSERT"):
            navigator_note["value"] = decision.value
        while True:
            observed_extra = {"navigator": navigator_note}
            if hitl_notes:
                observed_extra["hitl"] = hitl_notes

            def action(driver):
                self.executor.execute(driver, decision, element, timeout_ms)

            record = self.recorder.record(
                step["step_id"], text, decision.selected_action, action,
                chosen_locator=chosen_expr,
                target=decision.target, candidates=candidates,
                observed_extra=observed_extra)
            if record["status"] == "GROUNDED" or self.assist is None \
                    or attempt >= HITL_MAX_RETRIES:
                break
            parsed = self._ask_manual(record, attempt)
            if parsed is None:
                if self._last_manual_raw:
                    # QA nhập nhưng sai format → tính một lần thử bounded
                    attempt += 1
                    hitl_notes.append({"attempt": attempt, "source": "human",
                                       "locator": self._last_manual_raw})
                    continue
                break
            attempt += 1
            element = manual_element(parsed)
            candidates = [manual_candidate(parsed)]
            chosen_expr = manual_js_expr(parsed)
            hitl_notes.append({"attempt": attempt, "source": "human",
                               "locator": self._last_manual_raw})
        self._drain_created()

    def _ask_manual(self, record, attempt):
        message = "Step failed [{0}]: {1}".format(
            record["status"], str(record["observed_ui"].get("error", ""))[:140])
        raw = self.assist.request(message)
        self._last_manual_raw = raw
        parsed = parse_manual_locator(raw) if raw else None
        if parsed is None and raw:
            self._last_manual_raw = "{0} [invalid format]".format(raw)
        return parsed

    def _drain_created(self):
        new_resources = self.driver.created_resources[self._owned_cursor:]
        self._owned_cursor = len(self.driver.created_resources)
        for resource in new_resources:
            cleanup_path = self.cleanup_template.replace("{id}", str(resource["id"])) \
                if self.cleanup_template else None
            self.session.register_owned(resource["id"], cleanup_path)


def _raise_action(exc):
    def action(driver):
        raise exc
    return action
