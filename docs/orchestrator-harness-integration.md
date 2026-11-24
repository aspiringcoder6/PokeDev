# Orchestrator and agent harness integration

Integration verified on 2026-10-09. This completes the merge already in progress
on `agentHarness`, combining `7a9cc0d` with `origin/orchestrator` at `84fde0a`.

The scheduler and the harness now share one execution path. The merge preserves
the orchestrator's control plane while restoring the harness's durable attempt
identity, human decisions, contract verification, and source-patch review.

## Integrated behavior

| Area | Result |
| --- | --- |
| Scheduling | Dependency ordering, concurrency limits, conditional success/failure/always edges, router/join/barrier/delay behavior, automatic retry with backoff, pause/resume/cancel, and deadlines coexist with harness execution. Plan materialization carries the concurrency budget and retains contract validation. |
| Restart recovery | Recovery observes the original frozen request and attempt. Signed results accepted during downtime are adopted from the callback ledger; an existing live session is resumed through the executor's observer. Missing or unsupported recovery requires explicit retry and does not launch a replacement automatically. |
| Human decisions | Harness interactions and lifecycle approvals survive restart. Offline completion still passes contract evidence checks and approval gates. Approval and external-event continuations reuse the active scheduler. |
| Durable history | Repository snapshots retain their revision for optimistic write fencing. A failed required snapshot write stops dispatch. Existing local harness history and explicit `ADLC_RUN_DB_PATH` settings remain usable; fresh installations use Langflow SQL run snapshots. |
| Artifacts | The executor, callback importer, and review API share the durable bounded artifact store. Source-patch lookup can resolve historical attempts while preserving owner scoping. |
| Planner proposals | All six proposal API routes are registered. The blueprint toolbar now opens task proposals, supports validation/regeneration/rejection, and converts an approved proposal into the existing immutable plan pipeline. Starting a run remains a separate action. The configured MOCK/LLM provider is respected and proposal identities are isolated by owner. |
| Application lifecycle | Startup restores runs before starting scheduled triggers. Shutdown stops triggers and observers and releases service singletons. Cron/webhook triggers, approval SLA handling, quality gates, expressions, metrics, and notifications remain available. |
| Run and plan UI | Plan dependency graphs, task activity, attempts, artifacts, and source-patch review are combined. Older saved plans without executor metadata display safely. |

## Conflict resolution and cleanup

- Combined the scheduler implementation in `run_service.py` with harness recovery,
  contract-authoring/execution context, signed-result adoption, and artifact access.
- Combined API imports and preserved owner-scoped contract/recovery routes while
  connecting planner proposals and application service composition.
- Kept both contract validation and concurrency propagation in the materializer.
- Removed the runtime attempts database from Git tracking and retained the local
  file. Local runtime databases remain ignored.
- Kept accepted H5 ADRs and the proposed v0.2 documentation. Renumbered the proposed
  v0.2 ADR to `0016` to avoid the existing accepted `0012`, and updated its links.
- Removed conflict markers already present in the incoming `.env.example` while
  retaining both operator notification settings and the harness source-repo setting.
- Restored the harness recovery tests that the orchestrator branch had skipped.

## Verification

- Combined backend ADLC and controller suite: **584 tests passed**.
- Frontend blueprint, proposal-to-run, plan detail, run detail, attempts, API client,
  and history coverage: **64 tests passed across 8 suites**.
- Frontend production build: **passed**.
- Frontend type comparison against the original `agentHarness` revision:
  **282 existing errors before and after; no new errors introduced**. The full
  repository type check is therefore not clean, despite the successful build.
- Orchestrator migration `99685e5e0f03`: verified as an Alembic head; all four
  new tables upgraded and downgraded successfully in isolated SQLite.
- Existing local run database: **24 snapshots validated successfully** in
  read-only mode, without resuming any run.
- Lint checks passed for the conflict-resolution and integration runtime files.

Recovery coverage includes downtime callbacks, late accepted results, restored
approval gates, interaction resumption, unavailable attempts, frozen snapshots,
write failures, revision conflicts, concurrency restoration, and application
factory selection of existing versus fresh run storage. The companion harness
Git capture/callback/restart regression also passed with the available checkout.

## Remaining limits

- The DSH adapter remains an optional integration. Its SDK import is lazy so
  ordinary REST/mock startup works without `dsh_web_sdk`. That SDK is absent in
  this environment; selecting it directly gives `DSH_SDK_UNAVAILABLE`. DSH adapter
  behavior was tested with injected clients, not a live gateway or paid model.
- The DSH gateway adapter's session mapping remains process-local, and it does
  not provide the REST harness's full submission and interaction semantics.
- Proposal drafts remain process-local. Approved execution plans are archived
  through the existing SQL plan archive; draft persistence is separate future work.
- The v0.2 control-flow/compensation/durable-event schemas remain proposed
  documentation. This merge does not claim to implement their complete runtime.
- The database check used isolated SQLite, not a deployment database. The
  production build still reports existing chunk-size and mixed import warnings.
- Existing local changes inside `agent-harness-server` were preserved and are
  excluded from this merge. No remote branch has been pushed.

## Follow-up merge on 2026-10-17

This merge combines `agentHarness` at `1a4b738` with `origin/orchestrator` at
`b48010b` (DSH-backed AI blueprint requests). The pre-merge branch is retained as
`codex/backup-agentharness-before-orchestrator-20261017`.

The Blueprint toolbar retains compact mode, permission/loading checks, WIP
guards and the proposal-to-approved-plan pipeline while adding AI generation.
Generated graphs clear stale plans and are applied through the shared canvas
loader. Existing local-project routes and both read/write authorization helpers
remain available.

Verification found and fixed two issues in the incoming AI feature: its eager
SDK import prevented the entire backend from starting without `dsh_web_sdk`,
and its HTTP 503 error category was incompatible with the shared `ServiceError`
schema. The SDK now loads only when generation is requested; an unavailable SDK
returns a structured 503 response and leaves the saved graph unchanged.

Fresh-database startup also exposed an existing bootstrap collision: SQLModel
creates the ADLC tables before Alembic reaches the orchestrator/local-project
migrations. Those migrations now recognize already-created tables. SQLite
regression tests check repeat upgrades, preserved rows/indexes and rollback.

Validation for this merge:

- Backend ADLC and controller regression: **1,001 passed, 1 optional Docker
  test skipped** in the full sweep. After correcting the new SQLite UUID test
  fixture, both migration checks passed in a focused rerun (**2 passed**),
  validating **1,002 unique backend cases** overall.
- Frontend Blueprint, proposal, plan/run detail and API tests: **150 passed in
  15 suites**.
- Production build: **passed**, using `NODE_OPTIONS=--max-old-space-size=6144`,
  `UV_THREADPOOL_SIZE=2` and `RAYON_NUM_THREADS=2` on this Windows host. Existing
  chunk-size/mixed-import warnings remain.
- Whole-frontend TypeScript comparison: **281 existing errors before and after;
  zero new errors**. The full type check remains nonzero.
- Isolated application startup, fresh SQLite migrations, `/health`,
  `/health_check`, OpenAPI route coexistence and shutdown: **passed**; database
  and chat health both reported `ok`. Live providers and the optional telemetry
  writer were disabled for this isolated smoke check.
- Focused Python and frontend lint checks: **passed**.

Tests use a fresh, short temporary directory to avoid the host's default pytest
directory permissions and Windows Git path-length limits. SDK behavior is tested
with injected clients; live AI generation still requires the optional DSH SDK
and configured gateway credentials. The optional real-Docker test is excluded
unless explicitly enabled. Existing changes in `agent-harness-server` and
`docs/report/` remain outside the merge, and no remote branch was pushed.
