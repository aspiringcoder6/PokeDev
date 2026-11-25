"""Comprehensive Trial Run Script for Sandbox-Kit with Playwright in Docker.

Executes a full cycle:
1. Health check broker (http://localhost:8000)
2. Provision Docker container session (mcr.microsoft.com/playwright:v1.63.0-jammy)
3. Wait for Go runner to connect via WebSocket
4. Install @playwright/test in /workspace
5. Write playwright.config.ts and a realistic Playwright spec file via runWriteFile
6. Execute the test using `npx playwright test --reporter=json` via runShellCommand
7. Parse Playwright JSON report, verify assertion results and exitCode == 0
8. Verify evidence artifacts (screenshot)
9. Clean up and terminate session via DELETE endpoint
"""

import json
import sys
import time
import urllib.error
import urllib.request

BROKER_URL = "http://localhost:8000"
IMAGE = "mcr.microsoft.com/playwright:v1.63.0-jammy"
SESSION_ID = f"testforge-trial-{int(time.time())}"


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
    except Exception as e:
        log(f"Request failed for {method} {url}: {e}")
        raise


def run_action(session_id: str, action: dict) -> dict:
    payload = {"session_id": session_id, "action": action}
    return request("POST", "/api/v1/agent/execute", payload)


def run_trial():
    log("=" * 70)
    log(" TESTFORGE AI <-> SANDBOX-KIT LIVE TRIAL RUN")
    log("=" * 70)
    log(f"Broker Endpoint: {BROKER_URL}")
    log(f"Session ID:      {SESSION_ID}")
    log(f"Container Image: {IMAGE}")
    log("-" * 70)

    # 1. Health check
    log("\n[1/8] Checking Broker health...")
    health = request("GET", "/")
    log(f"Broker Health: {health}")
    assert health.get("status") == "ok", "Broker is not healthy"

    session_created = False
    try:
        # 2. Provision Sandbox Container
        log(f"\n[2/8] Provisioning container session '{SESSION_ID}'...")
        t0 = time.time()
        create_payload = {
            "session_id": SESSION_ID,
            "image": IMAGE,
            "cpu": "2",
            "memory": "4Gi",
            "ttl": 600,
        }
        res_create = request("POST", "/api/v1/management/sessions", create_payload)
        session_created = True
        log(f"Session Created ({time.time() - t0:.2f}s): {res_create}")

        # 3. Wait for Go Runner connection
        log("\n[3/8] Waiting for Go Runner WebSocket connection...")
        connected = False
        for attempt in range(30):
            time.sleep(1)
            status_res = request("GET", f"/api/v1/agent/sessions/{SESSION_ID}/status")
            runner_conn = status_res.get("runnerConnected", False)
            log(f"  Poll {attempt+1}/30: status={status_res.get('status')}, runnerConnected={runner_conn}")
            if runner_conn:
                connected = True
                log(f">>> Runner connected in {time.time() - t0:.2f}s! <<<")
                break

        if not connected:
            raise TimeoutError("Runner failed to connect within 30 seconds")

        # 4. Environment smoke check
        log("\n[4/8] Checking container runtime environment...")
        smoke_res = run_action(SESSION_ID, {
            "runShellCommand": {
                "command": "node -v && which python3 && uname -m"
            }
        })
        log(f"Environment output:\n{smoke_res.get('stdout', '').strip()}")
        assert smoke_res.get("exitCode") == 0, f"Smoke command failed: {smoke_res}"

        # 5. Prepare workspace and install @playwright/test
        log("\n[5/8] Initializing @playwright/test package in /workspace...")
        t_install = time.time()
        pkg_json = {
            "name": "sandbox-trial",
            "version": "1.0.0",
            "private": True,
            "devDependencies": {
                "@playwright/test": "1.63.0"
            }
        }
        run_action(SESSION_ID, {
            "runWriteFile": {
                "filepath": "/workspace/package.json",
                "contents": json.dumps(pkg_json, indent=2)
            }
        })

        install_res = run_action(SESSION_ID, {
            "runShellCommand": {
                "command": "cd /workspace && npm install --no-audit --no-fund"
            }
        })
        log(f"npm install completed ({time.time() - t_install:.2f}s), exitCode={install_res.get('exitCode')}")
        assert install_res.get("exitCode") == 0, f"npm install failed: {install_res.get('stderr') or install_res.get('stdout')}"

        # 6. Write playwright.config.ts and test spec
        log("\n[6/8] Writing playwright.config.ts and test spec file...")
        config_content = """import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 30000,
  use: {
    headless: true,
    screenshot: 'on',
    trace: 'on',
  },
  reporter: [['json'], ['list']],
});
"""
        run_action(SESSION_ID, {
            "runWriteFile": {
                "filepath": "/workspace/playwright.config.ts",
                "contents": config_content
            }
        })

        spec_content = """import { test, expect } from '@playwright/test';

test('verify interactive DOM and screenshot in sandbox', async ({ page }) => {
  await page.setContent(`
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <title>TestForge Sandbox Verification</title>
      <style>
        body { font-family: system-ui, sans-serif; background: #0f172a; color: #f8fafc; padding: 32px; }
        .card { background: #1e293b; border-radius: 8px; padding: 24px; border: 1px solid #334155; }
        h1 { color: #38bdf8; margin-top: 0; }
        button { background: #2563eb; color: white; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer; font-weight: bold; }
        #result { margin-top: 16px; padding: 12px; border-radius: 4px; background: #14532d; color: #4ade80; display: none; }
      </style>
    </head>
    <body>
      <div class="card">
        <h1 id="main-title">TestForge AI + Sandbox-Kit</h1>
        <p id="sub-desc">Playwright execution test inside isolated Linux container.</p>
        <button id="btn-run" onclick="document.getElementById('result').style.display = 'block'; document.getElementById('result').innerText = 'ACTION_COMPLETED_SUCCESSFULLY';">Trigger Test Action</button>
        <div id="result"></div>
      </div>
    </body>
    </html>
  `);

  // Assert initial state
  const title = page.locator('#main-title');
  await expect(title).toHaveText('TestForge AI + Sandbox-Kit');

  // Trigger button click
  const btn = page.locator('#btn-run');
  await btn.click();

  // Assert result banner
  const resultBanner = page.locator('#result');
  await expect(resultBanner).toBeVisible();
  await expect(resultBanner).toHaveText('ACTION_COMPLETED_SUCCESSFULLY');

  // Save screenshot artifact
  await page.screenshot({ path: '/workspace/artifacts/sandbox_trial_result.png' });
});
"""
        run_action(SESSION_ID, {
            "runWriteFile": {
                "filepath": "/workspace/tests/trial.spec.ts",
                "contents": spec_content
            }
        })

        # Verify file content via runReadFile
        read_res = run_action(SESSION_ID, {
            "runReadFile": {
                "filepath": "/workspace/tests/trial.spec.ts"
            }
        })
        log(f"File write/read verified: length={len(read_res.get('stdout', ''))} chars")
        assert "TestForge AI + Sandbox-Kit" in read_res.get("stdout", ""), "File content mismatch"

        # 7. Execute Playwright test
        log("\n[7/8] Executing Playwright test inside sandbox...")
        t_test = time.time()
        test_res = run_action(SESSION_ID, {
            "runShellCommand": {
                "command": "cd /workspace && npx playwright test tests/trial.spec.ts --reporter=json"
            }
        })
        test_duration = time.time() - t_test
        log(f"Playwright execution completed in {test_duration:.2f}s")
        log(f"ExitCode: {test_res.get('exitCode')}")
        log(f"Broker Status: {test_res.get('status')}")

        stdout = test_res.get("stdout", "")
        # Parse JSON report from stdout
        report = None
        json_start = stdout.find("{")
        if json_start != -1:
            try:
                report, _ = json.JSONDecoder().raw_decode(stdout[json_start:])
            except Exception as pe:
                log(f"Warning: JSON decode error: {pe}")

        if report:
            suites = report.get("suites", [])
            total_specs = report.get("stats", {}).get("expected", 0)
            passed = report.get("stats", {}).get("expected", 0)
            log(f"Report Summary: stats={report.get('stats')}")
            log(f"Test Suites Count: {len(suites)}")
        else:
            log(f"Raw stdout (truncated): {stdout[:500]}")

        assert test_res.get("exitCode") == 0, f"Playwright test failed with exitCode={test_res.get('exitCode')}, stderr={test_res.get('stderr')}"
        log(">>> Playwright Test PASSED! <<<")

        # 8. Check generated artifact
        log("\n[8/8] Verifying generated screenshot artifact...")
        artifact_res = run_action(SESSION_ID, {
            "runShellCommand": {
                "command": "ls -lh /workspace/artifacts/sandbox_trial_result.png"
            }
        })
        log(f"Artifact status:\n{artifact_res.get('stdout', '').strip()}")
        assert artifact_res.get("exitCode") == 0, "Screenshot artifact was not created"

        log("\n" + "=" * 70)
        log(" SANDBOX-KIT TRIAL RUN: 100% SUCCESSFUL!")
        log("=" * 70)

    finally:
        if session_created:
            log(f"\n[Teardown] Destroying session '{SESSION_ID}' and Docker container...")
            try:
                del_res = request("DELETE", f"/api/v1/management/sessions/{SESSION_ID}")
                log(f"Teardown Response: {del_res}")
            except Exception as e:
                log(f"Teardown Warning: {e}")


if __name__ == "__main__":
    run_trial()
