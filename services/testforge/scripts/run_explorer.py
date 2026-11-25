"""G1 entrypoint: run the browser-grounded Explorer against a live app.

Mỗi scenario dùng session mới (login API per-case, đúng nguyên tắc per-case
storageState của staging). POST 2xx trong lúc khám phá -> owned candidate tự
động; cleanup chỉ chạy khi có --cleanup-template do tester review trước.
"""
import argparse
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright

from src.agent1.explorer.executor import DecisionExecutor
from src.agent1.explorer.explorer import Explorer, parse_feature
from src.agent1.explorer.hitl import ManualLocatorAssist
from src.agent1.explorer.login import browser_extra_headers, login_and_save_state
from src.agent1.explorer.navigator import CompositeNavigator, LLMNavigator, PatternNavigator
from src.agent1.explorer.playwright_driver import PlaywrightDriver
from src.agent1.explorer.recorder import TraceRecorder
from src.agent1.explorer.session import ExplorationSession


def cleanup_owned(api_url, token, owned):
    results = []
    for item in owned:
        if not item.get("resolved") or not item.get("cleanup_path"):
            continue
        request = urllib.request.Request(
            api_url.rstrip("/") + item["cleanup_path"], method="DELETE",
            headers={"Authorization": "Bearer {0}".format(token)})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                results.append({"id": item["id"], "cleanup_status": response.status})
        except Exception as exc:
            results.append({"id": item["id"], "cleanup_error": str(exc)})
    return results


def main():
    parser = argparse.ArgumentParser(description="Browser-grounded Explorer (G1)")
    parser.add_argument("--feature", default="opt/gherkin/tteamflow_explorer.feature")
    parser.add_argument("--input-json", default="",
                        help="Tài liệu đầu vào 5 trường (Standard Test Input) — explorer "
                             "sinh Gherkin bổ sung kèm tags rồi chạy browser thật")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--actor", default="admin")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password-env", default="STAGING_TTEAMFLOW_ADMIN_PASSWORD")
    parser.add_argument("--cleanup-template", default="",
                        help="Reviewed DELETE contract, e.g. '/projects/{id}'")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--slowmo", type=int, default=0,
                        help="Độ trễ mỗi hành động trên browser (ms) để người xem kịp theo dõi")
    parser.add_argument("--video", action="store_true")
    parser.add_argument("--output", default="artifacts/automation/exploration")
    parser.add_argument("--step-deadline-ms", type=int, default=20000)
    parser.add_argument("--total-deadline-ms", type=int, default=600000)
    parser.add_argument("--no-llm", action="store_true",
                        help="Chỉ dùng PatternNavigator (deterministic-first)")
    parser.add_argument("--hitl", action="store_true",
                        help="Tier-3 HITL: hỏi QA locator thủ công khi step DEVIATED/FAILED")
    parser.add_argument("--hitl-channel", choices=["auto", "overlay", "stdin"], default="auto")
    parser.add_argument("--hitl-timeout-ms", type=int, default=120000)
    args = parser.parse_args()

    password = os.environ.get(args.password_env, "")
    if not password:
        raise SystemExit("Missing password env: {0}".format(args.password_env))

    if args.input_json:
        from src.agent1.explorer.standard_input import (load_standard_input,
                                                        write_standard_feature)
        std_input = load_standard_input(args.input_json)
        feature_path = write_standard_feature(
            std_input, Path(args.output) / "standard_input.feature")
        args.feature = str(feature_path)
        print("Standard input 5-field -> Gherkin: {0}".format(feature_path))

    scenarios = parse_feature(args.feature)
    if not scenarios:
        raise SystemExit("No scenarios parsed from: {0}".format(args.feature))

    navigator = PatternNavigator() if args.no_llm else CompositeNavigator(
        [PatternNavigator(), LLMNavigator()])

    exit_code = 0
    token = ""
    summaries = []
    owned_by_session = []
    with sync_playwright() as pw:
        slow_mo_ms = args.slowmo if args.slowmo > 0 else (600 if args.headed else 0)
        browser = pw.chromium.launch(headless=not args.headed, slow_mo=slow_mo_ms)
        try:
            for scenario in scenarios:
                state_path = Path(tempfile.gettempdir()) / "explorer_{0}.state.json".format(args.actor)
                token = login_and_save_state(pw, args.api_url, args.email, password, state_path,
                                             base_url=args.base_url) or token
                # Silent session validation qua API (không mở browser) — nếu
                # token stale thì re-login ngay, user không bao giờ thấy /login.
                _verify = pw.request.new_context()
                _resp = _verify.get(
                    args.api_url.rstrip("/") + "/auth/me",
                    headers={"Authorization": "Bearer {0}".format(token)})
                if not _resp.ok:
                    token = login_and_save_state(pw, args.api_url, args.email, password,
                                                 state_path,
                                                 base_url=args.base_url) or token
                _verify.dispose()
                context_kwargs = {"storage_state": str(state_path)}
                _extra_headers = browser_extra_headers()
                if _extra_headers:
                    # Identity gateway-injected (VD X-Username cho TNQD local không qua APISIX)
                    context_kwargs["extra_http_headers"] = _extra_headers
                session = ExplorationSession(
                    output_root=args.output, base_url=args.base_url, actor=args.actor,
                    total_deadline_ms=args.total_deadline_ms, video=args.video)
                if args.video:
                    context_kwargs["record_video_dir"] = str(session.root / "video")

                context = browser.new_context(**context_kwargs)
                page = context.new_page()
                # Warmup: SPA bootstrap /auth/refresh có thể thua race khi stack vừa dậy
                # (health 200 nhưng app chưa kịp phục vụ) -> /projects rớt về /login.
                # Kiểm tra thật và login lại đúng một lần nếu mất phiên.
                page.goto(args.base_url.rstrip("/") + "/",
                          timeout=args.step_deadline_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                if "/login" in page.url or "/auth" in page.url:
                    token = login_and_save_state(pw, args.api_url, args.email, password,
                                                 state_path, base_url=args.base_url) or token
                    context.close()
                    context = browser.new_context(**context_kwargs)
                    page = context.new_page()
                    page.goto(args.base_url.rstrip("/") + "/",
                              timeout=args.step_deadline_ms)
                    try:
                        page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass
                session.provenance["scenario"] = scenario["name"]
                session.provenance["feature"] = str(Path(args.feature).resolve())
                driver = PlaywrightDriver(page, actor=args.actor)
                recorder = TraceRecorder(session, driver, step_deadline_ms=args.step_deadline_ms)
                assist = ManualLocatorAssist(page, channel=args.hitl_channel,
                                             timeout_ms=args.hitl_timeout_ms) if args.hitl else None
                explorer = Explorer(session, driver, recorder, navigator,
                                    DecisionExecutor(), cleanup_template=args.cleanup_template,
                                    assist=assist)
                try:
                    coverage = explorer.run_scenario(scenario)
                    statuses = [r["status"] for r in session.records]
                    status = "GROUNDED" if statuses and all(s == "GROUNDED" for s in statuses) else "PARTIAL"
                    summary = session.finalize(status)
                    summary["coverage"] = {"covered": coverage["covered"], "required": coverage["required"],
                                           "grounded": coverage["grounded"]}
                    if not coverage["grounded"]:
                        exit_code = 1
                except Exception as exc:
                    summary = session.finalize("FAILED")
                    summary["error"] = "{0}: {1}".format(type(exc).__name__, exc)
                    exit_code = 1
                context.close()
                summary["owned"] = session.owned
                owned_by_session.extend(session.owned)
                summaries.append({"scenario": scenario["name"], "summary": summary})
        finally:
            browser.close()

    # Crash-safe: cleanup owned chạy cả khi scenario giữa chừng nổ (owned persist sẵn trong owned.json)
    cleanups = cleanup_owned(args.api_url, token, owned_by_session)
    report = {"scenarios": summaries, "cleanups": cleanups, "exit": exit_code}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
