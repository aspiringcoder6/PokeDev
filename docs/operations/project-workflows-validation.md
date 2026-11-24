# Project workspace validation — 26 October 2026

The local workspace now includes project-scoped workflow design, explicit workflow selection for requirements, editable proposed plans before approval, and the existing package canvas and delivery tools.

## Checks

- 29 frontend tests passed across the workspace, canvas, graph model, and package-canvas copy boundary.
- 30 backend tests passed, covering workflow compilation, owner/project scope, draft validation, version conflicts, immutable run snapshots, stale approvals, retry, and independent verification/review ordering.
- Browser interaction checks covered task selection, dependency edits, undo, save, reload, draft creation, selecting a workflow for a requirement, desktop layout, and the 600px breakpoint.
- The broader TypeScript check still reports existing errors in unrelated modules. It reported no errors in the changed workspace, workflow canvas, delivery API, or navigation modules.

## Real execution

[Saved canvas integration check](http://127.0.0.1:7861/work?project=36f89321-ea5a-4ebb-aae2-85358fd4d081&run=421996ff-220a-4cbb-84d4-84cc5a6f9cba) completed successfully against the isolated local counter repository using the configured 9router model.

The run used workflow version 1 exactly. Saving version 2 through the interface did not change that run's plan. Developer, Tester, independent Sandbox verification, Reviewer, and handover all completed. Protected Node tests, Python unittest checks, and real browser interactions passed. Verification confirmed that the protected source remained intact and the result matched the approved plan. Only `counter.mjs` and the new `tests/test_page.py` changed in the isolated candidate.

The production frontend is served at the existing app address. Prior frontend builds were retained in `adlc-flow/data/local-recovery/frontend-backups/` for recovery. Run data, existing project requirements, and credentials were preserved.
