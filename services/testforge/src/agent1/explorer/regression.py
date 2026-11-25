"""G3: Promotion -> Regression Asset (Zero-LLM, HITL bắt buộc).

Dịch ExplorationTrace đã PROMOTED thành case của staging suite, chạy qua đúng
run_suite hiện tại (VerificationEngine + Quality Gate + ProofStore + JUnit).
Nguyên tắc (docs/20): hệ thống KHÔNG tự promote — asset chỉ được sinh khi có
dấu tay người (--approved-by) và promotion.json phải promoted=true. Bundle ghi
ra opt/staging/generated/ để reviewer merge vào reviewed suite, không tự đè.

Value khớp binding replay được map về placeholder của staging:
  ${run_id} -> ${run_id}, ${run_id_short} -> ${short_id}.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from src.agent1.explorer.navigator import PatternNavigator
from src.agent1.explorer.trace import read_trace

_ROLE_LOCATOR_RE = re.compile(r"page\.getByRole\('([^']+)', \{ name: '(.*)', exact: true \}\)")


class PromotionError(ValueError):
    pass


def _slug(text):
    slug = re.sub(r"[^A-Za-z0-9]+", "-", str(text).lower()).strip("-")
    return slug or "scenario"


def _match_locator(locators, by, value, name=None):
    for key, locator in locators.items():
        if locator.get("by") == by and str(locator.get("value", "")) == str(value) \
                and locator.get("name", "") == (name or ""):
            return key
    return None


def build_regression_asset(session_root, profile_path, approved_by, requirement_ref=None):
    root = Path(session_root)
    promotion = json.loads((root / "synthesis" / "promotion.json").read_text(encoding="utf-8"))
    if not promotion.get("promoted"):
        raise PromotionError("Exploration run is not promoted; refusing to build regression asset")
    if not approved_by or not str(approved_by).strip():
        raise PromotionError("Human sign-off required: provide --approved-by")

    summary = json.loads((root / "session_summary.json").read_text(encoding="utf-8"))
    records = [r for r in read_trace(root) if r["status"] == "GROUNDED"]
    if not records:
        raise PromotionError("No GROUNDED steps to translate")
    profile = json.loads(Path(profile_path).read_text(encoding="utf-8-sig"))
    actor = summary.get("actor")
    if actor not in profile.get("actors", {}):
        raise PromotionError("Actor '{0}' missing in target profile".format(actor))

    run_id = summary["run_id"]
    short_id = run_id.split("-", 1)[-1][:8]
    ref = requirement_ref or "REQ-EXPLORER-{0}".format(short_id)

    replay_data_path = root / "synthesis" / "replay-data.json"
    binding_values = {}
    if replay_data_path.is_file():
        data = json.loads(replay_data_path.read_text(encoding="utf-8"))
        for key, value in data.items():
            if key.startswith("binding_"):
                binding_values[value] = value.replace(run_id, "${run_id}") \
                    .replace(short_id, "${short_id}")

    def staging_value(text):
        return binding_values.get(text, str(text).replace(run_id, "${run_id}")
                                  .replace(short_id, "${short_id}"))

    profile_locators = dict(profile.get("locators", {}))
    profile_routes = dict(profile.get("routes", {}))
    new_locators, new_routes = {}, {}

    def locator_key(by, value, name=None, scope=None):
        for pool in (profile_locators, new_locators):
            key = _match_locator(pool, by, value, name)
            if key and pool[key].get("scope_css", "") == (scope or ""):
                return key
        key = "explorer-{0}-{1}".format(_slug(name or value), len(new_locators) + 1)
        entry = {"by": by, "value": value}
        if name:
            entry["name"] = name
        if scope:
            entry["scope_css"] = scope
        new_locators[key] = entry
        return key

    def role_key(chosen_locator):
        match = _ROLE_LOCATOR_RE.match(chosen_locator)
        if not match:
            raise PromotionError(
                "Unsupported chosen_locator for staging translation: {0}".format(chosen_locator))
        return locator_key("role", match.group(1), name=match.group(2))

    steps, oracles = [], []
    navigator = PatternNavigator()
    for record in records:
        action = record["selected_action"]
        if action == "OPEN":
            path = urlsplit(record["url"]).path or "/"
            route_key = next((k for k, v in {**profile_routes, **new_routes}.items() if v == path),
                             None)
            if not route_key:
                route_key = "explorer-route-{0}".format(len(new_routes) + 1)
                new_routes[route_key] = path
            steps.append({"action": "OPEN", "target": route_key})
        elif action in ("CLICK", "SUBMIT"):
            steps.append({"action": "CLICK", "target": role_key(record["chosen_locator"])})
        elif action == "FILL":
            decision = navigator.propose(record["user_intent"], "", record.get("url", ""))
            steps.append({
                "action": "FILL",
                "target": role_key(record["chosen_locator"]),
                "value": staging_value(decision.value if decision else ""),
            })
        elif action == "ASSERT":
            absent = bool(decision_value_absent(record["user_intent"], navigator))
            oracle_type = "ABSENT" if absent else "VISIBLE"
            # scope main: sidebar/dashboard cũng render cùng text -> strict mode ambiguity
            oracles.append({
                "source_ref": ref,
                "type": oracle_type,
                "target": locator_key("text", staging_value(record["target"]), scope="main"),
                "timeout_ms": 10000,
            })
        else:
            raise PromotionError(
                "Action not translatable to staging step: {0}".format(action))

    case = {
        "test_case_id": "explorer-{0}".format(short_id),
        "actor": actor,
        "requirement_refs": [ref],
        "steps": steps,
    }
    if oracles:
        case["ui_oracles"] = oracles
    else:
        raise PromotionError("Trace has no ASSERT step; staging requires explicit oracles")

    merged_profile = json.loads(json.dumps(profile))
    merged_profile["locators"].update(new_locators)
    merged_profile["routes"].update(new_routes)

    manifest = {
        "exploration_run_id": run_id,
        "scenario": summary.get("scenario"),
        "approved_by": str(approved_by).strip(),
        "approved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "requirement_ref": ref,
        "owned": json.loads((root / "owned.json").read_text(encoding="utf-8"))
        if (root / "owned.json").is_file() else [],
        "new_locators": new_locators,
        "new_routes": new_routes,
        "review_notes": [
            "requirement_ref is a placeholder - remap to the real requirement id during review",
            "UI-created data is not auto-cleaned by run_suite; keys are unique per run so no collision",
            "merge this bundle into the reviewed suite manually - system never promotes on its own",
        ],
    }
    return {"profile": merged_profile, "suite": {
        "version": 1,
        "name": "Explorer regression - {0}".format(summary.get("scenario", scenario_fallback(summary))),
        "cases": [case],
    }, "manifest": manifest}


def decision_value_absent(user_intent, navigator):
    decision = navigator.propose(user_intent, "", "")
    return bool(decision and decision.value == "absent")


def scenario_fallback(summary):
    return "scenario"
