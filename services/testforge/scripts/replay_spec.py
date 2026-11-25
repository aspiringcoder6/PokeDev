"""G2 replay: đăng nhập lại fresh state, chạy spec đã tổng hợp, chốt Promotion Gate.

Replay dùng storageState MỚI (login lại), không tái sử dụng cookie phiên khám phá —
đúng nguyên tắc replay fresh state trước khi promote.
"""
import argparse
import json
import os
import re
import sys
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright

from src.agent1.explorer.login import login_and_save_state
from src.agent1.explorer.synthesizer import TraceSynthesizer, fresh_bindings
from src.agent1.explorer.trace import read_trace
from src.agent1.executor.runner import PlaywrightExecutor
from src.agent1.executor.verification_engine import VerificationEngine
from src.agent1.healer.graph import run_healing
from src.agent1.healer.tier2_ai_recovery import Tier2AIRecovery
from src.agent1.healer.llm_client import OpenCodeChatClient


def matching_ids(payload, marker):
    """Id các resource trong list payload mà tên chứa marker (tìm thấy = state tồn tại)."""
    items = payload.get("data") if isinstance(payload, dict) else payload
    return [item.get("id") for item in (items or [])
            if marker in str(item.get("name", ""))]


def api_verify(api_url, token, list_path, marker):
    """Kiểm chứng trạng thái phía server: resource replay vừa tạo phải đọc được qua API GET."""
    request = urllib.request.Request(
        api_url.rstrip("/") + list_path,
        headers={"Authorization": "Bearer {0}".format(token)})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"passed": False, "detail": "api read failed: {0}".format(exc)}
    found = matching_ids(payload, marker)
    return {"passed": bool(found),
            "detail": "{0} matching resource(s) via GET {1}".format(len(found), list_path)}


_ACTION_LINE_RE = re.compile(r"await (page\.goto|page\.getBy\w+|expect)\(")


def infer_failed_step(replay_result, records, spec_text):
    """Executor không biết cấu trúc step của explorer (failed_step=None).

    Suy ra step fail theo thứ tự: (1) khớp chính xác giá trị name trong
    chosen_locator; (2) scan dòng action trong spec theo thứ tự step
    (controlled fault có thể đổi name nên phải soi spec).
    """
    if replay_result.get("failed_step"):
        return int(replay_result["failed_step"])
    error = str(replay_result.get("error") or "")
    value_match = re.search(r"name:\s*'([^']+)'", error) or \
        re.search(r"(?:getByText|getByLabel|getByTestId)\('([^']+)'", error)
    if not value_match:
        return None
    value = value_match.group(1)
    grounded = [r for r in records if r.get("status") == "GROUNDED"]
    for idx, record in enumerate(grounded, start=1):
        names = re.findall(r"name:\s*'([^']+)'", record.get("chosen_locator") or "")
        if value in names:
            return idx
    action_lines = [ln for ln in spec_text.splitlines() if _ACTION_LINE_RE.search(ln)]
    for idx in range(1, min(len(grounded), len(action_lines)) + 1):
        line = action_lines[idx - 1]
        if "'{0}'".format(value) in line or value in (grounded[idx - 1].get("target") or ""):
            return idx
    return None


def build_healing_test_case(spec_text, records, run_id):
    """Dịch trace đã ground + spec tổng hợp -> test_case cho healing graph (Bước 16).

    expected_results chỉ lấy ASSERT literal (không binding) để guardrail oracle
    trong validate_node khớp chính xác với nội dung spec.
    """
    steps = []
    for record in records:
        if record.get("status") != "GROUNDED":
            continue
        steps.append({
            "action": record.get("selected_action", ""),
            "target": record.get("target") or record.get("chosen_locator", ""),
        })
    expected_results = re.findall(r"expect\(page\.getByText\('([^']+)'\)\)", spec_text)
    return {
        "test_case_id": run_id,
        "steps": steps,
        "expected_results": expected_results,
    }


def make_retest_runner(executor, spec_path):
    """Retest runner chạy repaired script trong cùng synth dir (dùng chung config/state).

    Tên file phải kết thúc .spec.ts để khớp testMatch của Playwright.
    """
    healed_path = Path(str(spec_path).replace(".spec.ts", ".healed.spec.ts"))

    def retest(test_case_id, repaired_script):
        healed_path.write_text(repaired_script, encoding="utf-8")
        return executor.execute_script(test_case_id, str(healed_path),
                                       script_path=str(healed_path), real_runtime=True)
    return retest


def replay_cleanup(api_url, token, cleanup_template, run_id):
    """Dọn dữ liệu do spec replay tạo lại (tên entity chứa run_id của phiên khám phá)."""
    if not cleanup_template:
        return []
    request = urllib.request.Request(
        api_url.rstrip("/") + "/projects",
        headers={"Authorization": "Bearer {0}".format(token)})
    results = []
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return [{"cleanup_error": str(exc)}]
    items = payload.get("data") if isinstance(payload, dict) else payload
    for item in items or []:
        name = str(item.get("name", ""))
        if run_id not in name:
            continue
        entity_id = item.get("id")
        delete = urllib.request.Request(
            api_url.rstrip("/") + cleanup_template.replace("{id}", str(entity_id)),
            method="DELETE", headers={"Authorization": "Bearer {0}".format(token)})
        try:
            with urllib.request.urlopen(delete, timeout=15) as response:
                results.append({"id": entity_id, "cleanup_status": response.status})
        except Exception as exc:
            results.append({"id": entity_id, "cleanup_error": str(exc)})
    return results


def main():
    parser = argparse.ArgumentParser(description="G2 replay + Promotion Gate")
    parser.add_argument("--session", required=True,
                        help="Thư mục run khám phá (chứa trace.jsonl + session_summary.json)")
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password-env", default="STAGING_TTEAMFLOW_ADMIN_PASSWORD")
    parser.add_argument("--cleanup-template", default="",
                        help="Ví dụ '/projects/{id}' — reviewer phê duyệt trước")
    parser.add_argument("--heal", action="store_true",
                        help="Bước 16-17: chạy healing graph khi replay FAIL (LOCATOR/TIMING)")
    parser.add_argument("--fault-locator", action="append", default=[],
                        help="Controlled fault demo: 'OLD=NEW' thay vào spec sau synthesize")
    parser.add_argument("--headed", action="store_true",
                        help="Chạy Playwright với giao diện trình duyệt trực quan")
    parser.add_argument("--slowmo", type=int, default=0,
                        help="Độ trễ mỗi hành động trên browser (ms) để người xem kịp theo dõi")
    args = parser.parse_args()

    password = os.environ.get(args.password_env, "")
    if not password:
        raise SystemExit("Missing password env: {0}".format(args.password_env))

    session_dir = Path(args.session)
    summary = json.loads((session_dir / "session_summary.json").read_text(encoding="utf-8"))
    run_id = summary["run_id"]

    synthesizer = TraceSynthesizer(session_dir, feature_path=summary.get("feature"))
    synthesis = synthesizer.synthesize()
    synth_dir = Path(synthesis["spec_path"]).parent

    # Mỗi replay cấp fresh unique id (SUT soft-delete làm key cũ không dùng lại được)
    fresh_id = uuid.uuid4().hex[:8]
    values = fresh_bindings(synthesis["bindings"], fresh_id)
    (synth_dir / "replay-data.json").write_text(json.dumps({
        "exploration_run_id": run_id,
        "replay_id": "REPLAY-{0}".format(fresh_id),
        **values,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    replay_marker = "REPLAY-{0}".format(fresh_id)

    with sync_playwright() as pw:
        token = login_and_save_state(pw, args.api_url, args.email, password,
                                     synth_dir / "storage.state.json",
                                     base_url=summary.get("base_url", ""))

    spec_path = Path(synthesis["spec_path"])
    controlled_faults = []
    for fault in args.fault_locator:
        old, _, new = fault.partition("=")
        current = spec_path.read_text(encoding="utf-8")
        if old in current:
            spec_path.write_text(current.replace(old, new, 1), encoding="utf-8")
            controlled_faults.append({"old": old, "new": new})

    slow_mo_ms = args.slowmo if args.slowmo > 0 else (600 if args.headed else 0)
    if slow_mo_ms > 0:
        cfg_path = synth_dir / "playwright.config.ts"
        if cfg_path.exists():
            cfg_text = cfg_path.read_text(encoding="utf-8")
            if "launchOptions" not in cfg_text:
                cfg_text = cfg_text.replace(
                    "use: {",
                    "use: {\n    launchOptions: { slowMo: " + str(slow_mo_ms) + " },"
                )
                cfg_path.write_text(cfg_text, encoding="utf-8")

    executor = PlaywrightExecutor(config_path=str(synth_dir / "playwright.config.ts"),
                                  project_root=Path(__file__).resolve().parents[1],
                                  headless=not args.headed,
                                  timeout_ms=60000)
    discovery = executor.discovery_check(str(spec_path))
    if not discovery["ok"]:
        replay_result = {"status": "ERROR", "duration_ms": 0, "error": discovery["stderr"]}
    else:
        replay_result = executor.execute_script(
            run_id, str(spec_path), script_path=str(spec_path), real_runtime=True)

    healing = None
    if args.heal and replay_result.get("status") == "FAIL":
        records = [r for r in read_trace(session_dir) if r.get("status") == "GROUNDED"]
        inferred = infer_failed_step(replay_result, records, synthesis["spec_text"])
        if inferred and not replay_result.get("failed_step"):
            replay_result["failed_step"] = inferred
        # Healing làm việc trên script THỰC ĐÃ CHẠY (đã áp controlled fault nếu có)
        faulted_spec_text = spec_path.read_text(encoding="utf-8")
        healing_case = build_healing_test_case(faulted_spec_text, records, run_id)
        healing = run_healing(
            healing_case, replay_result, faulted_spec_text,
            retest_runner=make_retest_runner(executor, spec_path),
            tier2_healer=Tier2AIRecovery(llm_client=OpenCodeChatClient()),
            max_retries=2,
        )
        (synth_dir / "healing.json").write_text(
            json.dumps(healing, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        if healing.get("outcome") == "HEALED_PASS":
            replay_result = healing.get("retest_result") or replay_result

    verification = VerificationEngine().verify(replay_result)

    list_path = args.cleanup_template.replace("{id}", "").rstrip("/")
    if synthesis["bindings"] and list_path:
        api_verification = api_verify(args.api_url, token, list_path, replay_marker)
    else:
        api_verification = None
    promotion = synthesizer.finalize_promotion(replay_result, verification,
                                               api_verification=api_verification)
    cleanups = replay_cleanup(args.api_url, token, args.cleanup_template, replay_marker)

    report = {"run_id": run_id, "replay": replay_result, "promotion": promotion,
              "api_verification": api_verification, "controlled_faults": controlled_faults,
              "healing": healing and {
                  "outcome": healing["outcome"],
                  "proposal_source": healing["proposal_source"],
                  "strategy": (healing.get("proposal") or {}).get("strategy", ""),
                  "retest_count": healing["retest_count"],
              }, "cleanups": cleanups}
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    sys.exit(0 if promotion["promoted"] else 1)


if __name__ == "__main__":
    main()
