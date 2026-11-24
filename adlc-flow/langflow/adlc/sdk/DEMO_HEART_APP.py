"""Demo: Build a frontend website with a clickable heart.

Task: Create a single HTML file with:
- A heart shape (CSS-based, red color)
- Click on heart → show "Hello World!" message
- Red as the main color theme
- Simple, single-page, no build tools needed

This demo showcases:
- Practical frontend development
- Visual output (easy to verify)
- Interactive element (click handler)
- Simple enough to avoid errors (1 file)

Run with:
    cd adlc-flow
    set -a && source ../.env && set +a
    .venv/bin/python -m langflow.adlc.sdk.DEMO_HEART_APP
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone

from langflow.adlc.sdk.dsh_task_loop_sdk import (
    DSHTaskLoopCommand,
    DSHTaskLoopCriterion,
    DSHTaskLoopSDK,
    DSHTaskLoopSpec,
    LoopExitReason,
)


# ---- Task specification ---------------------------------------------------

HEART_APP_REQUIREMENT = (
    "Create a single HTML file `index.html` for a simple frontend website.\n"
    "\n"
    "Requirements:\n"
    "1. Display a heart shape in the center of the page (use CSS, not image).\n"
    "2. The heart must be RED (main color theme of the website).\n"
    "3. When the user CLICKS on the heart, show a message 'Hello World!' "
    "below or near the heart.\n"
    "4. The page should have a clean, centered layout.\n"
    "5. Use only HTML, CSS, and vanilla JavaScript (no frameworks, no build tools).\n"
    "6. The file must work when opened directly in a browser (file:// protocol).\n"
    "\n"
    "Do not create any other files. Do not modify any existing files."
)


# ---- Demo spec ------------------------------------------------------------

DEMO_SPEC = DSHTaskLoopSpec(
    specification=HEART_APP_REQUIREMENT,
    base_commit="a1b2c3d4e5f6789012345678901234567890abcd",
    writable_paths=("index.html",),
    acceptance_criteria=(
        DSHTaskLoopCriterion(
            criterion_id="heart_shape_visible",
            description=(
                "The page displays a heart shape in the center, "
                "rendered with CSS (not an image file)"
            ),
            check_refs=("html_test",),
        ),
        DSHTaskLoopCriterion(
            criterion_id="heart_is_red",
            description="The heart is red (main color theme)",
            check_refs=("html_test",),
        ),
        DSHTaskLoopCriterion(
            criterion_id="click_shows_hello_world",
            description=(
                "Clicking the heart shows 'Hello World!' message"
            ),
            check_refs=("html_test",),
        ),
        DSHTaskLoopCriterion(
            criterion_id="single_file_no_dependencies",
            description=(
                "Single HTML file with embedded CSS/JS, "
                "no external dependencies, works with file:// protocol"
            ),
            check_refs=("html_test",),
        ),
    ),
    verification_commands=(
        DSHTaskLoopCommand(
            check_id="html_test",
            test_path="index.html",
            timeout_ms=15_000,
        ),
    ),
    loop_until_pass=True,
)


# ---- Expected output (for reference) --------------------------------------

EXPECTED_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Heart App</title>
  <style>
    body {
      margin: 0;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      background: #fff5f5;
      font-family: -apple-system, BlinkMacSystemFont, sans-serif;
    }
    h1 { color: #c00; margin-bottom: 2rem; }
    .heart {
      width: 100px;
      height: 100px;
      background: #e63946;
      position: relative;
      transform: rotate(-45deg);
      cursor: pointer;
      transition: transform 0.2s;
      box-shadow: 0 4px 20px rgba(230,57,70,0.4);
    }
    .heart:hover { transform: rotate(-45deg) scale(1.1); }
    .heart::before, .heart::after {
      content: '';
      width: 100px;
      height: 100px;
      background: #e63946;
      border-radius: 50%;
      position: absolute;
    }
    .heart::before { top: -50px; left: 0; }
    .heart::after  { top: 0; left: 50px; }
    #message {
      margin-top: 2rem;
      font-size: 2rem;
      color: #c00;
      opacity: 0;
      transition: opacity 0.3s;
    }
    #message.show { opacity: 1; }
  </style>
</head>
<body>
  <h1>Click the heart</h1>
  <div class="heart" id="heart" onclick="showMessage()"></div>
  <div id="message">Hello World!</div>
  <script>
    function showMessage() {
      document.getElementById('message').classList.add('show');
    }
  </script>
</body>
</html>
"""


# ---- Demo runner ----------------------------------------------------------

async def run_demo() -> dict:
    """Run the heart app demo and collect metrics."""
    sdk = DSHTaskLoopSDK.from_env()

    print()
    print("=" * 70)
    print("HEART APP DEMO")
    print("Frontend: clickable heart -> Hello World")
    print("=" * 70)
    print()
    print("  Task: Create index.html with clickable red heart")
    print("  Acceptance criteria: 4")
    print("  Verification commands: 1")
    print("  Writable paths: 1 (index.html)")
    print("  Loop until pass: True")
    print()

    # Step 1: Validate
    print("-" * 70)
    print("STEP 1: Validate spec")
    print("-" * 70)
    missing = sdk.missing_fields(DEMO_SPEC)
    if missing:
        print(f"  X Missing fields: {missing}")
        return {"error": "incomplete spec"}
    print("  OK All required fields present")
    print()

    # Step 2: Submit
    print("-" * 70)
    print("STEP 2: Submit to DSH")
    print("-" * 70)
    submit_start = time.monotonic()
    print(f"  -> Sending prompt to DSH...")
    print(f"  -> DSH agent will create index.html")
    print()

    result = await sdk.submit(DEMO_SPEC)
    submit_duration = time.monotonic() - submit_start

    # Step 3: Result
    print("-" * 70)
    print("STEP 3: Result")
    print("-" * 70)
    print(f"  Exit reason: {result.exit_reason.value}")
    print(f"  Passed: {result.passed}")
    print(f"  Session ID: {result.session_id}")
    print(f"  Duration: {result.duration_seconds:.1f}s")
    print()

    # Step 4: Show expected output
    print("-" * 70)
    print("STEP 4: Expected output (index.html)")
    print("-" * 70)
    print("  File: index.html")
    print("     - Heart shape (CSS, red #e63946)")
    print("     - Click handler -> shows 'Hello World!'")
    print("     - Single file, no dependencies")
    print("     - Works with file:// protocol")
    print()

    # Metrics
    metrics = {
        "scenario": "heart_app_demo",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "exit_reason": result.exit_reason.value,
        "passed": result.passed,
        "session_id": result.session_id,
        "duration_seconds": round(result.duration_seconds, 1),
        "acceptance_criteria_count": len(DEMO_SPEC.acceptance_criteria),
        "verification_commands_count": len(DEMO_SPEC.verification_commands),
        "writable_paths_count": len(DEMO_SPEC.writable_paths),
        "loop_until_pass": DEMO_SPEC.loop_until_pass,
        "files_created": 1,
        "framework": "vanilla HTML/CSS/JS",
        "interactive": True,
    }

    print("-" * 70)
    print("METRICS")
    print("-" * 70)
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    print()

    return metrics


if __name__ == "__main__":
    required = ("ADLC_HARNESS_BASE_URL", "ADLC_HARNESS_API_TOKEN")
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        print(f"Missing env vars: {missing}")
    else:
        asyncio.run(run_demo())
