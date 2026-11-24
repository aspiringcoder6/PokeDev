"""Demo scenario: end-to-end task execution via DSH.

This script runs a realistic coding task through the full ADLC → DSH
pipeline and collects metrics for the demo report.

Task: Create a Python module `string_utils.py` with three functions
(capitalize_words, reverse_string, count_vowels) and a test file
`test_string_utils.py` with unittest tests for each function.

Run with:
    cd adlc-flow
    .venv/bin/python -m langflow.adlc.sdk.DEMO_SCENARIO
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


DEMO_SPEC = DSHTaskLoopSpec(
    specification=(
        "Create a Python module `string_utils.py` with three functions:\n"
        "1. `capitalize_words(s: str) -> str`: capitalizes the first letter of each word.\n"
        "2. `reverse_string(s: str) -> str`: returns the string reversed.\n"
        "3. `count_vowels(s: str) -> int`: counts vowels (a, e, i, o, u) case-insensitive.\n"
        "\n"
        "Create `test_string_utils.py` with unittest tests for each function.\n"
        "All tests must pass. Do not modify any other files."
    ),
    base_commit="a1b2c3d4e5f6789012345678901234567890abcd",
    writable_paths=("string_utils.py", "test_string_utils.py"),
    acceptance_criteria=(
        DSHTaskLoopCriterion(
            criterion_id="capitalize_words_correct",
            description="capitalize_words('hello world') returns 'Hello World'",
            check_refs=("string_utils_test",),
        ),
        DSHTaskLoopCriterion(
            criterion_id="reverse_string_correct",
            description="reverse_string('hello') returns 'olleh'",
            check_refs=("string_utils_test",),
        ),
        DSHTaskLoopCriterion(
            criterion_id="count_vowels_correct",
            description="count_vowels('Hello World') returns 3",
            check_refs=("string_utils_test",),
        ),
        DSHTaskLoopCriterion(
            criterion_id="all_tests_pass",
            description="All unittest tests in test_string_utils.py pass",
            check_refs=("string_utils_test",),
        ),
    ),
    verification_commands=(
        DSHTaskLoopCommand(
            check_id="string_utils_test",
            test_path="test_string_utils.py",
            timeout_ms=30_000,
        ),
    ),
    loop_until_pass=True,
)


async def run_demo() -> dict:
    """Run the demo scenario and collect metrics."""
    sdk = DSHTaskLoopSDK.from_env()

    print("=" * 70)
    print("ADLC + DSH DEMO SCENARIO")
    print("=" * 70)
    print()
    print(f"Task: Create string_utils.py + test_string_utils.py")
    print(f"Acceptance criteria: {len(DEMO_SPEC.acceptance_criteria)}")
    print(f"Verification commands: {len(DEMO_SPEC.verification_commands)}")
    print(f"Loop until pass: {DEMO_SPEC.loop_until_pass}")
    print()
    print("-" * 70)
    print("STEP 1: Validate spec")
    print("-" * 70)
    missing = sdk.missing_fields(DEMO_SPEC)
    if missing:
        print(f"  ✗ Missing fields: {missing}")
        return {"error": "incomplete spec"}
    print(f"  ✓ All required fields present")
    print()

    print("-" * 70)
    print("STEP 2: Submit to DSH")
    print("-" * 70)
    submit_start = time.monotonic()
    submit_time = datetime.now(timezone.utc)
    print(f"  → Sending prompt to DSH at {submit_time.isoformat()}")
    print(f"  → Session will be created on DSH server")
    print()

    result = await sdk.submit(DEMO_SPEC)
    submit_duration = time.monotonic() - submit_start

    print("-" * 70)
    print("STEP 3: Result")
    print("-" * 70)
    print(f"  Exit reason: {result.exit_reason.value}")
    print(f"  Passed: {result.passed}")
    print(f"  Session ID: {result.session_id}")
    print(f"  Duration: {result.duration_seconds:.1f}s")
    print(f"  Iterations: {result.iterations}")
    print()

    # Collect metrics
    metrics = {
        "scenario": "string_utils_demo",
        "timestamp": submit_time.isoformat(),
        "exit_reason": result.exit_reason.value,
        "passed": result.passed,
        "session_id": result.session_id,
        "duration_seconds": round(result.duration_seconds, 1),
        "iterations": result.iterations,
        "acceptance_criteria_count": len(DEMO_SPEC.acceptance_criteria),
        "verification_commands_count": len(DEMO_SPEC.verification_commands),
        "writable_paths_count": len(DEMO_SPEC.writable_paths),
        "loop_until_pass": DEMO_SPEC.loop_until_pass,
        "final_text_length": len(result.final_text or ""),
        "final_text_preview": (result.final_text or "")[:500],
    }

    print("-" * 70)
    print("METRICS (JSON)")
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
