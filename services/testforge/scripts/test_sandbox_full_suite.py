"""E2E Test Suite for TestForge AI on Sandbox-Kit.

Validates:
1. Session Provisioning & Go Runner connection
2. Environment Setup (Node.js, Playwright)
3. PASS Scenario: interactive test passes, outputs JSON report & screenshot
4. FAIL Scenario: selector timeout / assertion failure returns exitCode != 0 and error details
5. Artifact Retrieval: screenshot file extracted to host via base64
6. Teardown: container destroyed cleanly
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

BROKER_URL = "http://localhost:8000"
IMAGE = "mcr.microsoft.com/playwright:v1.63.0-jammy"
SESSION_ID = f"testforge-suite-{int(time.time())}"
HOST_ARTIFACTS_DIR = os.path.join(os.path.dirname(__file__), "..", "artifacts", "sandbox_test")


def log(msg: str):
    print(msg, flush=True)


def request(method: str, path: str, data: dict = None) -> dict:
    url = f"{BROKER_URL}{path}"
    headers = {"Content-Type": "application/json"} if data else {}
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            content = resp.read().decode("utf-8")
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        log(f"HTTP Error {e.code} for {method} {url}: {err_body}")
        raise


def run_action(session_id: str, action: dict) -> dict:
    payload = {"session_id": session_id, "action": action}
    return request("POST", "/api/v1/agent/execute", payload)


def run_full_suite():
    log("=" * 72)
    log(" TESTFORGE AI <-> SANDBOX-KIT FULL VERIFICATION SUITE")
    log("=" * 72)
    log(f"Broker Endpoint: {BROKER_URL}")
    log(f"Session ID:      {SESSION_ID}")
    log(f"Docker Image:    {IMAGE}")
    log("-" * 72)

    os.makedirs(HOST_ARTIFACTS_DIR, exist_ok=True)
    session_created = False

    try:
        # 1. Provision Sandbox Session
        log("\n[1/6] Provisioning Docker sandbox session...")
        t0 = time.time()
        res_create = request("POST", "/api/v1/management/sessions", {
            "session_id": SESSION_ID,
            "image": IMAGE,
            "cpu": "2",
            "memory": "4Gi",
            "ttl": 600,
        })
        session_created = True
        log(f"Session Created ({time.time() - t0:.2f}s): {res_create.get('sessionId')}")

        # 2. Wait for Runner
        log("\n[2/6] Waiting for container runner connection...")
        connected = False
        for i in range(30):
            time.sleep(1)
            status_res = request("GET", f"/api/v1/agent/sessions/{SESSION_ID}/status")
            if status_res.get("runnerConnected"):
                connected = True
                log(f">>> Runner connected in {time.time() - t0:.2f}s! <<<")
                break
        assert connected, "Runner connection timeout"

        # 3. Setup workspace & Playwright
        log("\n[3/6] Setting up Playwright dependencies in /workspace...")
        run_action(SESSION_ID, {
            "runWriteFile": {
                "filepath": "/workspace/package.json",
                "contents": json.dumps({"name": "sandbox-suite", "devDependencies": {"@playwright/test": "1.63.0"}})
            }
        })
        t_install = time.time()
        res_inst = run_action(SESSION_ID, {
            "runShellCommand": {
                "command": "cd /workspace && npm install --no-audit --no-fund"
            }
        })
        log(f"npm install completed in {time.time() - t_install:.2f}s (exitCode={res_inst.get('exitCode')})")
        assert res_inst.get("exitCode") == 0

        # Write playwright.config.ts
        config_ts = """
import { defineConfig } from '@playwright/test';
export default defineConfig({
  timeout: 10000,
  use: { headless: true, screenshot: 'only-on-failure' },
  reporter: [['json'], ['list']]
});
"""
        run_action(SESSION_ID, {
            "runWriteFile": {
                "filepath": "/workspace/playwright.config.ts",
                "contents": config_ts.strip()
            }
        })

        # 4. Test Case A: PASSING TEST
        log("\n[4/6] Running Test Case A (PASS Scenario)...")
        pass_spec = """
import { test, expect } from '@playwright/test';

test('PASS_01: Verify interactive button counter', async ({ page }) => {
  await page.setContent(`
    <button id="counter" onclick="this.innerText = parseInt(this.innerText) + 1">0</button>
  `);
  const btn = page.locator('#counter');
  await expect(btn).toHaveText('0');
  await btn.click();
  await expect(btn).toHaveText('1');
  await page.screenshot({ path: '/workspace/artifacts/pass_01.png' });
});
"""
        run_action(SESSION_ID, {
            "runWriteFile": {
                "filepath": "/workspace/tests/pass.spec.ts",
                "contents": pass_spec.strip()
            }
        })

        res_pass = run_action(SESSION_ID, {
            "runShellCommand": {
                "command": "cd /workspace && npx playwright test tests/pass.spec.ts --reporter=json"
            }
        })
        log(f"Test A exitCode: {res_pass.get('exitCode')}")
        assert res_pass.get("exitCode") == 0, f"Expected PASS but got exitCode {res_pass.get('exitCode')}"
        log(">>> Test Case A PASSED as expected! <<<")

        # 5. Test Case B: FAILING TEST (Intentional fault)
        log("\n[5/6] Running Test Case B (FAIL Scenario - intentional selector mismatch)...")
        fail_spec = """
import { test, expect } from '@playwright/test';

test('FAIL_01: Expect non-existent element with short timeout', async ({ page }) => {
  await page.setContent(`<div>Valid Content</div>`);
  // Will fail with timeout finding #missing-submit-button
  await page.locator('#missing-submit-button').click({ timeout: 2000 });
});
"""
        run_action(SESSION_ID, {
            "runWriteFile": {
                "filepath": "/workspace/tests/fail.spec.ts",
                "contents": fail_spec.strip()
            }
        })

        res_fail = run_action(SESSION_ID, {
            "runShellCommand": {
                "command": "cd /workspace && npx playwright test tests/fail.spec.ts --reporter=json"
            }
        })
        log(f"Test B exitCode: {res_fail.get('exitCode')}")
        log(f"Broker status: {res_fail.get('status')}")
        assert res_fail.get("exitCode") != 0, f"Expected non-zero exitCode for failure, got {res_fail.get('exitCode')}"

        # Parse Playwright JSON error
        stdout_fail = res_fail.get("stdout", "")
        start_idx = stdout_fail.find("{")
        if start_idx != -1:
            report_fail, _ = json.JSONDecoder().raw_decode(stdout_fail[start_idx:])
            stats = report_fail.get("stats", {})
            log(f"Failure Stats: unexpected={stats.get('unexpected')}, expected={stats.get('expected')}")
            assert stats.get("unexpected") == 1, "Expected 1 unexpected failure in report"
        log(">>> Test Case B FAILED and captured error diagnostics as expected! <<<")

        # 6. Retrieve Artifact (Screenshot) via direct runReadFile with encoding='base64' (CR-02)
        log("\n[6/6] Extracting screenshot artifact via direct runReadFile (CR-02 binary-safe)...")
        b64_res = run_action(SESSION_ID, {
            "runReadFile": {
                "filepath": "/workspace/artifacts/pass_01.png",
                "encoding": "base64"
            }
        })
        b64_data = b64_res.get("stdout", "").strip()
        assert len(b64_data) > 100, f"Base64 artifact is too short or missing: {b64_res}"

        host_image_path = os.path.join(HOST_ARTIFACTS_DIR, "sandbox_pass_01.png")
        with open(host_image_path, "wb") as f:
            f.write(base64.b64decode(b64_data))
        log(f"Saved screenshot to host via CR-02: {host_image_path} ({os.path.getsize(host_image_path)} bytes)")

        # 7. Verify CR-01 custom timeout
        log("\n[7/7] Testing CR-01 dynamic timeout on runShellCommand...")
        to_res = run_action(SESSION_ID, {
            "runShellCommand": {
                "command": "echo 'CR-01 timeout test pass'",
                "timeout": 45
            }
        })
        log(f"Custom timeout command result: {to_res.get('stdout', '').strip()} (exitCode={to_res.get('exitCode')})")
        assert to_res.get("exitCode") == 0, "Custom timeout command failed"


        log("\n" + "=" * 72)
        log(" ALL TESTFORGE AI VERIFICATION SCENARIOS PASSED ON SANDBOX-KIT!")
        log("=" * 72)

    finally:
        if session_created:
            log(f"\n[Teardown] Deleting session '{SESSION_ID}'...")
            try:
                res_del = request("DELETE", f"/api/v1/management/sessions/{SESSION_ID}")
                log(f"Session deleted: {res_del}")
            except Exception as e:
                log(f"Teardown error: {e}")


if __name__ == "__main__":
    run_full_suite()
