"""G2: Zero-LLM Synthesizer — ExplorationTrace -> spec Playwright + fixtures + Promotion Gate.

Nguyên tắc (docs/20):
- Synthesis hoàn toàn deterministic: chỉ replay lại đúng locator/value đã ground
  trong trace, không tự suy luận gì thêm.
- Oracle KHÔNG do trace định nghĩa: các dòng expect() sinh ra từ step ASSERT,
  mà gốc rễ là step Then của contract Gherkin — Promotion Gate đối chiếu ngược
  feature file để bảo đảm đủ oracle từ contract.
- 7 tiêu chí promotion: step_coverage, oracle_from_contract, static_validation,
  replay_pass, verification_engine, cleanup_resolved, provenance_complete.
"""
import json
import re
from pathlib import Path

import jsonschema

from src.agent1.explorer.explorer import parse_feature
from src.agent1.explorer.login import browser_extra_headers
from src.agent1.explorer.navigator import PatternNavigator
from src.agent1.explorer.standard_input import derive_standard_input
from src.agent1.explorer.trace import read_trace
from src.agent1.generator.playwright_generator import PlaywrightGenerator
from src.agent1.generator.static_validator import StaticValidator

_STORAGE_STATE_NAME = "storage.state.json"
PROMOTION_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "promotion.schema.json"


class SynthesisError(ValueError):
    pass


def validate_promotion(promotion):
    """promotion.json phải khớp schemas/promotion.schema.json + check id unique."""
    jsonschema.validate(promotion, json.loads(PROMOTION_SCHEMA_PATH.read_text(encoding="utf-8")))
    ids = [c["id"] for c in promotion["checks"]]
    if len(set(ids)) != len(ids):
        raise SynthesisError("Duplicate promotion check ids: {0}".format(ids))


def _escape_js(value):
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def fresh_bindings(binding_list, fresh_id):
    """Cấp giá trị mới cho mỗi binding theo template, giữ tương quan trong 1 replay.

    ${run_id} -> REPLAY-<fresh_id> ; ${run_id_short} -> <fresh_id>.
    """
    values = {}
    for binding in binding_list:
        values[binding["name"]] = binding["template"] \
            .replace("${run_id}", "REPLAY-{0}".format(fresh_id)) \
            .replace("${run_id_short}", fresh_id)
    return values


class TraceSynthesizer:
    def __init__(self, session_root, feature_path=None):
        self.root = Path(session_root)
        self.feature_path = feature_path

    # ------------------------------------------------------------------
    def synthesize(self):
        """Sinh spec + fixtures + promotion.json (các check tĩnh; replay/verify = pending)."""
        records = read_trace(self.root)
        if not records:
            raise SynthesisError("Empty trace: nothing to synthesize")
        summary_path = self.root / "session_summary.json"
        if not summary_path.is_file():
            raise SynthesisError("Missing session_summary.json")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        scenario_obj = self._load_scenario(summary)
        if scenario_obj:
            summary = {**summary,
                       "test_case_id": scenario_obj.get("test_case_id"),
                       "function_id": scenario_obj.get("function_id"),
                       "requirement_refs": scenario_obj.get("requirement_refs") or []}
        owned_path = self.root / "owned.json"
        owned = json.loads(owned_path.read_text(encoding="utf-8")) if owned_path.is_file() else []

        spec_text, binding_order = self._generate_spec(records, summary)
        static = StaticValidator.validate(spec_text, test_case={
            "test_case_id": summary.get("test_case_id") or summary["run_id"],
            "function_id": summary.get("function_id") or summary.get("scenario", ""),
        })

        synth_dir = self.root / "synthesis"
        synth_dir.mkdir(exist_ok=True)
        spec_path = synth_dir / "{0}.spec.ts".format(summary["run_id"])
        spec_path.write_text(spec_text, encoding="utf-8")
        self._write_config(synth_dir, summary)
        (synth_dir / "replay-data.json").write_text(json.dumps({
            "exploration_run_id": summary["run_id"],
            "replay_id": "GROUNDED",
            **{b["name"]: b["grounded"] for b in binding_order},
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        fixtures = {
            "owned": owned,
            "unresolved_cleanup": [o for o in owned if not o.get("resolved")],
        }
        (synth_dir / "fixtures.json").write_text(
            json.dumps(fixtures, indent=2, ensure_ascii=False), encoding="utf-8")

        promotion = self._promotion(records, summary, owned, static)
        (synth_dir / "promotion.json").write_text(
            json.dumps(promotion, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"spec_path": str(spec_path), "spec_text": spec_text,
                "bindings": binding_order,
                "fixtures": fixtures, "promotion": promotion}

    # ------------------------------------------------------------------
    def _generate_spec(self, records, summary):
        run_id = summary["run_id"]
        short_id = run_id.split("-", 1)[-1][:8]
        scenario = summary.get("scenario") or "Exploration scenario"
        navigator = PatternNavigator()
        bindings = {}
        binding_order = []

        def bind(value):
            """Value chứa run id -> binding replay (SUT soft-delete khóa unique key)."""
            template = value.replace(run_id, "${run_id}").replace(short_id, "${run_id_short}")
            if "${run_id}" not in template and "${run_id_short}" not in template:
                return None
            if template not in bindings:
                name = "binding_{0}".format(len(bindings) + 1)
                bindings[template] = name
                binding_order.append({"name": name, "template": template, "grounded": value})
            return bindings[template]

        header = PlaywrightGenerator.metadata_header(
            summary.get("test_case_id") or run_id,
            summary.get("function_id") or scenario, scenario,
            script_version="explorer-synth-1",
            generator_model="zero-llm-trace-synthesis",
            extra_meta={
                "exploration_run_id": run_id,
                "actor": summary.get("actor", ""),
                "replay_bindings": ", ".join(b["name"] for b in binding_order) or "none",
                "source": "browser-grounded exploration trace - Zero-LLM synthesis",
                "requirement_refs": ", ".join(summary.get("requirement_refs") or []) or "none",
            },
        ) + "import data from './replay-data.json';\n" \
            + PlaywrightGenerator.evidence_prelude(
            "{0} - {1}".format(scenario, run_id), "{0}: {1}".format(run_id, scenario))
        lines = [header]
        grounded = [r for r in records if r.get("status") == "GROUNDED"]
        # Trace SPA bắt đầu từ trang đã đăng nhập (không có OPEN step) ->
        # replay phải mở root trước (baseURL trong config tự resolve).
        if not (grounded and grounded[0].get("selected_action") == "OPEN"):
            lines.append("  await page.goto('/');")
        for record in records:
            if record["status"] != "GROUNDED":
                continue
            action = record["selected_action"]
            decision = navigator.propose(record["user_intent"], "", record.get("url", ""))
            if action == "OPEN":
                lines.append("  await page.goto('{0}');".format(_escape_js(record["url"])))
            elif action in ("CLICK", "SUBMIT"):
                lines.append("  await {0}.click();".format(record["chosen_locator"]))
            elif action == "PRESS":
                lines.append("  await page.keyboard.press('Enter');")
            elif action in ("FILL", "SELECT"):
                method = "fill" if action == "FILL" else "selectOption"
                value = decision.value if decision else self._decision_value(record, "value")
                bound = bind(value)
                argument = "data.{0}".format(bound) if bound else "'{0}'".format(_escape_js(value))
                lines.append("  await {0}.{1}({2});".format(record["chosen_locator"], method, argument))
            elif action == "ASSERT":
                note = (record.get("observed_ui") or {}).get("navigator") or {}
                absent = (decision and decision.value == "absent") or note.get("value") == "absent"
                expect_method = "toBeHidden()" if absent else "toBeVisible()"
                bound = bind(record["target"])
                argument = "data.{0}".format(bound) if bound else "'{0}'".format(_escape_js(record["target"]))
                locator_expr = "page.getByText({0})".format(argument)
                lines.append("  await expect({0}).{1};".format(locator_expr, expect_method))
        lines.append(PlaywrightGenerator.evidence_footer())
        lines.append("  });")
        lines.append("});")
        lines.append("")
        return "\n".join(lines), binding_order

    @staticmethod
    def _decision_value(record, field):
        """Value từ PatternNavigator; fallback sang decision LLM lưu trong observed_ui."""
        navigator_note = (record.get("observed_ui") or {}).get("navigator") or {}
        return str(navigator_note.get(field, ""))

    @staticmethod
    def _write_config(synth_dir, summary):
        # storageState resolve theo CWD của process Playwright -> phải dùng path tuyệt đối
        state_path = (Path(synth_dir) / _STORAGE_STATE_NAME).resolve().as_posix()
        # Identity gateway-injected (VD X-Username cho TNQD local) — replay cũng phải có
        extra_headers = browser_extra_headers()
        headers_ts = ""
        if extra_headers:
            items = ", ".join(
                "{0}: {1}".format(json.dumps(k), json.dumps(v))
                for k, v in sorted(extra_headers.items()))
            headers_ts = "    extraHTTPHeaders: {{ {0} }},\n".format(items)
        config = (
            "import { defineConfig } from '@playwright/test';\n"
            "\n"
            "// Auto-generated by TestForge G2 synthesizer - replay exploration spec\n"
            "// với storageState mới đăng nhập lại (per-case session, không tái sử dụng cookie cũ).\n"
            "export default defineConfig({\n"
            "  testDir: '.',\n"
            "  timeout: 60000,\n"
            "  retries: 0,\n"
            "  workers: 1,\n"
            "  fullyParallel: false,\n"
            "  outputDir: 'test-results',\n"
            "  use: {\n"
            "    baseURL: '__BASE_URL__',\n"
            "    storageState: '__STORAGE_STATE__',\n"
            "{EXTRA_HEADERS}"
            "    headless: true,\n"
            "    trace: 'retain-on-failure',\n"
            "    actionTimeout: 15000,\n"
            "  },\n"
            "});\n"
        ).replace("__BASE_URL__", summary.get("base_url", "")) \
         .replace("__STORAGE_STATE__", state_path) \
         .replace("{EXTRA_HEADERS}", headers_ts)
        (synth_dir / "playwright.config.ts").write_text(config, encoding="utf-8")

    # ------------------------------------------------------------------
    def _promotion(self, records, summary, owned, static):
        grounded = [r for r in records if r["status"] == "GROUNDED"]
        checks = [
            {"id": "step_coverage", "passed": bool(records) and len(grounded) == len(records),
             "detail": "{0}/{1} GROUNDED".format(len(grounded), len(records))},
            self._oracle_check(records, summary),
            {"id": "static_validation", "passed": bool(static.get("valid")),
             "detail": "; ".join(e.get("message", "") for e in static.get("errors", [])) or "0 errors"},
            {"id": "replay_pass", "passed": None, "detail": "pending replay"},
            {"id": "verification_engine", "passed": None, "detail": "pending replay"},
            {"id": "cleanup_resolved", "passed": all(o.get("resolved") for o in owned),
             "detail": "{0} owned, {1} unresolved".format(
                 len(owned), sum(1 for o in owned if not o.get("resolved")))},
            self._provenance_check(summary),
        ]
        if summary.get("video"):
            checks.append(self._video_check())
        if owned:
            checks.append({"id": "api_state_verify", "passed": None, "detail": "pending replay"})
        checks.append(self._standard_input_check(summary))
        return self._assemble(checks, summary)

    def _load_scenario(self, summary):
        """Feature file + scenario name -> scenario đã parse (tags/feature_name) hoặc None."""
        feature_path = summary.get("feature")
        scenario_name = summary.get("scenario")
        if not feature_path or not Path(feature_path).is_file() or not scenario_name:
            return None
        for scenario in parse_feature(feature_path):
            if scenario["name"] == scenario_name:
                return scenario
        return None

    def _standard_input_check(self, summary):
        """Chuẩn 5 trường: mọi spec sinh ra phải truy vết được về Standard Test Input.

        Gherkin -> derive 5 trường (Given=precondition, When=steps, Then=expected).
        Không derive được (thiếu steps/expected) -> passed=False; không có feature
        file -> passed=None (pending, chặn promote).
        """
        scenario = self._load_scenario(summary)
        if scenario is None:
            return {"id": "standard_input_contract", "passed": None,
                    "detail": "feature/scenario unavailable for 5-field derivation"}
        std, errors = derive_standard_input(scenario)
        if errors:
            return {"id": "standard_input_contract", "passed": False,
                    "detail": "; ".join(errors[:2])}
        artifact = self.root / "synthesis" / "standard_test_input.json"
        artifact.write_text(json.dumps(std, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"id": "standard_input_contract", "passed": True,
                "detail": "5-field contract validated (function_id={0}, steps={1}, expected={2})"
                .format(std["function_id"], len(std["steps"]), len(std["expected_result"]))}

    def _video_check(self):
        videos = [p for p in (self.root / "video").glob("*.webm")
                  if p.is_file() and p.stat().st_size > 0]
        return {"id": "video_evidence", "passed": bool(videos),
                "detail": "{0} non-empty video file(s) in {1}".format(len(videos), "video/")}

    @staticmethod
    def _assemble(checks, summary):
        promotion = {
            "run_id": summary["run_id"],
            "promoted": all(c["passed"] is True for c in checks),
            "checks": checks,
            "blocking": [c["id"] for c in checks if c["passed"] is not True],
        }
        validate_promotion(promotion)
        return promotion

    def _oracle_check(self, records, summary):
        feature_path = summary.get("feature")
        scenario_name = summary.get("scenario")
        then_ids = set()
        if feature_path and Path(feature_path).is_file() and scenario_name:
            for scenario in parse_feature(feature_path):
                if scenario["name"] == scenario_name:
                    then_ids = {s["step_id"] for s in scenario["steps"] if s["keyword"] == "Then"}
                    break
        assert_ids = {r["step_id"] for r in records if r["selected_action"] == "ASSERT"}
        if not then_ids:
            return {"id": "oracle_from_contract", "passed": None,
                    "detail": "feature/Then steps unavailable for comparison"}
        passed = then_ids == assert_ids
        return {"id": "oracle_from_contract", "passed": passed,
                "detail": "{0}/{1} Then steps grounded as ASSERT".format(len(assert_ids), len(then_ids))}

    @staticmethod
    def _provenance_check(summary):
        missing = [k for k in ("base_url", "actor", "scenario", "feature") if not summary.get(k)]
        return {"id": "provenance_complete", "passed": not missing,
                "detail": "missing: {0}".format(", ".join(missing)) if missing else "all fields present"}

    # ------------------------------------------------------------------
    def finalize_promotion(self, replay_result, verification_result, api_verification=None):
        promotion_path = self.root / "synthesis" / "promotion.json"
        promotion = json.loads(promotion_path.read_text(encoding="utf-8"))
        for check in promotion["checks"]:
            if check["id"] == "replay_pass":
                check["passed"] = replay_result.get("status") == "PASS"
                check["detail"] = "{0} in {1}ms".format(
                    replay_result.get("status"), replay_result.get("duration_ms", 0))
            elif check["id"] == "verification_engine":
                status = verification_result.get("final_status") \
                    if isinstance(verification_result, dict) else None
                check["passed"] = status == "PASS"
                check["detail"] = str((verification_result or {}).get("reason", status))
            elif check["id"] == "api_state_verify":
                check["passed"] = bool((api_verification or {}).get("passed"))
                check["detail"] = str((api_verification or {}).get(
                    "detail", "no api verification provided"))
        promotion["promoted"] = all(c["passed"] is True for c in promotion["checks"])
        promotion["blocking"] = [c["id"] for c in promotion["checks"] if c["passed"] is not True]
        validate_promotion(promotion)
        promotion_path.write_text(json.dumps(promotion, indent=2, ensure_ascii=False),
                                  encoding="utf-8")
        return promotion
