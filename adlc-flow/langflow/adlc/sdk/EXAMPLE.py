"""Example: using the DSH Task Loop SDK.

This example shows how to:
1. Build a task_loop_spec with all required fields
2. Validate it (catches missing fields before submission)
3. Submit it to DSH and wait for it to finish
4. Inspect the result

The loop is handled by DSH (via the vai-taskloop plugin), NOT by our SDK.
The ``loop_until_pass`` flag (default True) tells DSH whether to keep
iterating until all acceptance criteria pass.

Run with:
    cd adlc-flow
    .venv/bin/python -m langflow.adlc.sdk.EXAMPLE
"""

from __future__ import annotations

import asyncio
import os

from langflow.adlc.sdk.dsh_task_loop_sdk import (
    DSHTaskLoopCommand,
    DSHTaskLoopCriterion,
    DSHTaskLoopSDK,
    DSHTaskLoopSpec,
    LoopExitReason,
)


async def main() -> None:
    # ---- 1. Build the spec (all required fields) -------------------------
    spec = DSHTaskLoopSpec(
        # Required: full immutable objective
        specification=(
            "Create a simple Python file `hello.py` that defines a function "
            "`greet(name)` which returns the string 'Hello, {name}!'. "
            "Create a test file `test_hello.py` with one test that verifies "
            "`greet('World')` returns 'Hello, World!'. "
            "Do not modify any other files."
        ),
        # Required: 40-char hex Git commit (pinned base)
        base_commit="a1b2c3d4e5f6789012345678901234567890abcd",
        # Required: exact list of files the agent may write
        writable_paths=(
            "hello.py",
            "test_hello.py",
        ),
        # Required: 1..32 acceptance criteria, each mapped to checks
        acceptance_criteria=(
            DSHTaskLoopCriterion(
                criterion_id="greet_function_exists",
                description=(
                    "hello.py defines a function greet(name) that returns "
                    "'Hello, {name}!'"
                ),
                check_refs=("greet_test",),
            ),
            DSHTaskLoopCriterion(
                criterion_id="greet_test_passes",
                description="test_hello.py passes when run with pytest",
                check_refs=("greet_test",),
            ),
        ),
        # Required: 1..16 registered verification commands
        verification_commands=(
            DSHTaskLoopCommand(
                check_id="greet_test",
                test_path="test_hello.py",
                timeout_ms=30_000,
            ),
        ),
        # Optional: override defaults if needed
        loop_until_pass=True,        # default: DSH loops until pass
        # max_iterations=25,           # default: DSH-side budget hint
        # max_stalled_iterations=3,    # default
        # context_budget_chars=131072, # default (128 KiB)
        # max_duration_ms=1_800_000,   # default (30 min)
        # max_total_tokens=200_000,    # default
        # max_total_cost=10.0,         # default (USD)
    )

    # ---- 2. Validate (catches missing fields before submission) -----------
    sdk = DSHTaskLoopSDK.from_env()
    missing = sdk.missing_fields(spec)
    if missing:
        print(f"Spec is incomplete. Missing fields: {missing}")
        print("Please fill in the missing fields and re-submit.")
        return

    # ---- 3. Print the spec as JSON (for inspection / logging) --------------
    print("Submitting spec:")
    print(spec.to_json(indent=2))
    print()

    # ---- 4. Submit to DSH and wait for it to finish -----------------------
    # DSH (via vai-taskloop) handles the loop internally.
    result = await sdk.submit(spec)

    # ---- 5. Inspect the result --------------------------------------------
    print(f"Exit reason: {result.exit_reason.value}")
    print(f"Passed: {result.passed}")
    print(f"Session ID: {result.session_id}")
    print(f"Duration: {result.duration_seconds:.1f}s")
    print(f"Iterations: {result.iterations}")
    print()
    print("Final text from DSH agent:")
    print(result.final_text or "(empty)")


if __name__ == "__main__":
    # Make sure ADLC_HARNESS_* env vars are set before running.
    required = ("ADLC_HARNESS_BASE_URL", "ADLC_HARNESS_API_TOKEN")
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        print(f"Missing env vars: {missing}")
        print("Set them in .env or export them before running.")
    else:
        asyncio.run(main())
