# H8B — Durable Product Cycles and workspace history

Status: **IMPLEMENTED AND ACTIVATED LOCALLY** · 2026-10-19.

One work item now keeps an original execution cycle and a separate successor draft. Users can select cycles, read their goals/spec versions/plan history, and prepare or revise the next goal without replacing an existing run. **This is not yet the complete Product Loop:** detailed successor planning is H8C, feedback selection/replanning is H8D, and outcome/release closure is H8E.

## User-facing behavior

- `/work/{delivery_id}` remains cycle 1 for backward compatibility. `?cycle_id={uuid}` selects an exact cycle; invalid/foreign selections fail rather than fall back silently.
- **Chu kỳ đang xem** selects read-only context. **Lịch sử chu kỳ & kế hoạch** links to saved plan viewers; it does not regenerate or approve work.
- **Chuẩn bị chu kỳ tiếp theo** stores a draft and its frozen workflow reference. It does not call a model, alter code, authorize a baseline or inherit approvals.
- **Chỉnh mục tiêu** appends a draft-spec revision using the current digest/revision. Only one pending successor draft is allowed; a prior cycle offers **Mở bản nháp tiếp theo** instead of making duplicates.
- Notes/change requests are attributed to the source cycle. Intake does not select backlog or widen an active task's scope.
- Successor drafts explicitly show no plan/run and no execution authority. Both frontend and backend block compiling, approving or starting them through the first-cycle path. Read-only users can still browse permitted history.
- Long legacy requirements are summarized with the exact original text behind an expander. Goal, workflow version, spec version and plan version are separate concepts.

## Durable records

| Table | Responsibility |
| --- | --- |
| `adlc_product_cycle` | Product-local cycle number, predecessor, goal, state and plan/run/dispatch binding. |
| `adlc_cycle_head` | Transactional numbering/head revision and one execution reservation slot per product. |
| `adlc_cycle_spec` | Append-only spec payload/digest with author and revision. |
| `adlc_cycle_plan_revision` | Plan lineage, semantic digest, plan/workflow snapshots and approval provenance. |
| `adlc_cycle_feedback` | Attributed, source-key-deduplicated feedback. |
| `adlc_cycle_operation` | Durable command key, exact input digest/snapshot, status and acknowledged result. |

The initial cycle ID is deterministic from the Delivery ID. Existing Delivery authority fields remain the first cycle's compatibility authority; additive migration imports their values, archived predecessor plans, notes and any run/reservation. GET requests never create or rewrite cycle records.

The current draft spec is intentionally incomplete: it has workflow identity/version/digest/snapshot and goal, but `baseline=null`, empty acceptance/selected-feedback lists and `execution_ready=false`. `LEGACY_IMPORT` identifies imported cycle 1; `USER_DRAFT` identifies a prepared successor. A previous Task Loop's locked checks remain in its original plan; they are not silently promoted into a new accepted CycleSpec.

Stored cycle state (`PLANNING`, `DRAFT`, `DISPATCH_RESERVED`, `LINKED`) is not a claim of candidate acceptance, Verify PASS or release. Displayed execution status comes from the canonical bound run. Preparing another draft does not release an existing execution slot. Later slices must implement explicit successor acceptance and slot transition.

## API and authority rules

Prefix: `/api/v1/adlc/deliveries`.

| Endpoint | Contract |
| --- | --- |
| `GET /{id}?cycle_id={uuid}` | Exact cycle plus cycle summaries, spec/digest, plan-revision summaries, scoped notes and capabilities. Without a selection, returns cycle 1. |
| `POST /{id}/cycles` | `expected_revision`, `workflow_digest`, command UUID, predecessor UUID and goal; optional cycle scope inherited from the closed Delivery command schema. |
| `POST /{id}/cycles/{cycle_id}/spec` | Current revision/workflow digest, command UUID, current spec digest and replacement goal; appends a new spec. |
| Existing compile/approve/start/reconcile | Cycle-1-only during H8B; optionally carry `cycle_id`. A successor cannot borrow the first cycle's plan or receipts. |
| Existing notes | Optional source-cycle identity and command UUID; deduplicated with attributed feedback, not auto-selected scope. |

Server derives identity/ownership/approval; browser-supplied actor, status, run or approved flags are rejected. Source Flow read/write/execute checks remain in force. The private Delivery adapter still rejects managed/shared projects until the team-runtime adapter exists; superuser/folder ownership does not bypass that boundary.

SQL compare-and-swap serializes Delivery revision, cycle numbering and head updates. Unique constraints cover cycle numbers, spec revisions, plan membership, feedback sources and command keys. A repeated key with identical input returns its durable result; a different payload conflicts. Stale scope/spec commands do not move the head.

For the original execution cycle:

1. Compile reserves the SQL revision and chooses the SQL plan version. The compiler builds a snapshot without changing shared process caches. Plan archive, cycle revision and operation receipt commit together; cache publication follows commit.
2. Approval reads the SQL snapshot and archives the exact accepted semantics with provenance before returning a receipt. SQLite/UTC timestamp normalization avoids spurious mismatches without changing the original receipt.
3. Start validates permissions, exact approvals and runtime readiness before reserving dispatch. Cycle/head/dispatch receipt commit before materialization; the existing canonical dispatch key is retained.
4. Unknown acknowledgement stays reserved. Reconciliation can link one canonical owner/flow/plan run, never retry paid work automatically.

Advanced create/regenerate/approve and proposal-generation/regeneration/acceptance APIs reject mutations of workspace-bound workflows (`DELIVERY_USE_WORKSPACE`). SQL archive reads are authoritative for those workspace plans across workers. Standalone legacy workflows retain their existing cache-first lifecycle behavior; H8B does not regress their superseded-plan status.

## Migration and activation

`h8b1c2d3e4f5` follows `dw01a2b3c4d5`. The migration uses frozen SQLAlchemy definitions with explicit constraints/indexes; it neither imports mutable runtime models nor alters old run/approval payloads. Empty pre-created tables are adopted only after strict schema validation. Incompatible or populated lookalikes fail closed. Destructive downgrade is refused.

Activation on this machine was explicitly authorized after runs were stopped:

- SQLite online backups of **9 stores** plus checksums were saved privately under `adlc-flow/data/backups/h8b-20261019T015246256218Z`.
- Migration was rehearsed on a separate backup copy, preserving critical business records and reporting no foreign-key errors.
- Normal backend startup applied Alembic; immediate verification reported `legacy_records_unchanged=true`, head `h8b1c2d3e4f5`, no changed protected tables and zero foreign-key errors.
- A single successor draft was then saved through the authenticated live UI. Root revision changed **5 → 6** as expected; protected authority, all plan archive records and all canonical run payloads remained equal to the backup.
- Backend was restarted with the final source; frontend was not stopped. Harness and service brokers were not reloaded. Offline Harness does not block read/history startup; no replacement token or model is invented, and real execution still needs authenticated readiness.

See [the local runbook](delivery-workspace.md#nâng-cấp-h8b) for backup/rehearsal/start/verification. Backup verification is an immediate post-migration check: after legitimate user edits, compare protected fields rather than treating an expected revision/timestamp change as migration damage. Never restore a rehearsal database over the live one or use `stamp head` to conceal missing schema.

## Verification

| Check | Result |
| --- | --- |
| Delivery, product cycles/migration, existing Delivery migration, Harness bootstrap, advanced planning routes and planning suite | **155 passed**, 2 existing pytest configuration warnings (`timeout`, `timeout_method`). |
| Delivery UI/API, canonical graph, Plan Detail and Run Detail regressions | **206 passed / 20 suites**. |
| Targeted TypeScript semantic/syntax diagnostics | **0 across 9 H8B source/test/preview files**; not a repository-wide build claim. |
| Ruff | Passed for Python files in the H8B scope, including advanced route changes. |
| SQL concurrency | Independent sessions cannot create two successors or dispatch two runs for one revision. Real control-gate materialization is used, not a model call. |
| Restart/idempotency | Empty planner caches preserve SQL plan versions/command results; real backend restart preserves the saved draft. |
| Isolation/authority | Foreign cycles/owners rejected; draft cannot inherit compile/approval/start; advanced bypass routes blocked; legacy standalone supersession preserved. |
| UI | Selector/history, compact long goal, draft save/edit dialog, stale commands, read-only permissions, keyboard dismissal and axe tests; live desktop plus 390×844 narrow layout with document width 390px. |

Backend command from `adlc-flow`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/adlc/test_delivery.py tests/unit/adlc/test_product_cycles.py tests/unit/adlc/test_product_cycle_migration.py tests/unit/adlc/test_delivery_migration.py tests/unit/adlc/test_delivery_harness_bootstrap.py tests/unit/api/v1/test_adlc_plans.py tests/unit/adlc/planning -q -p no:cacheprovider --basetemp=data/test-tmp-h8b-final-20261019 --junitxml=data/h8b-backend-tests.xml
```

Use a fresh test-temp directory on reruns where Windows retains restricted old temp files. Do not weaken OS permissions.

Frontend command from `adlc-flow/frontend`:

```powershell
node node_modules/jest/bin/jest.js src/features/delivery-workspace src/controllers/API/delivery.test.ts src/features/adlc-blueprint/plan-task-graph.test.tsx src/pages/PlanDetailPage/index.test.tsx src/pages/RunDetailPage --runInBand --silent --json --outputFile=../data/h8b-frontend-tests.json
```

Formatting used the existing Biome through stdin because the repository has a pre-existing nested-root CLI configuration conflict. No repository formatter configuration was changed. The focused test results do not certify a full repository build, every database engine or arbitrary applications.

## Live evidence and remaining work

Product: `57c730a8-b21c-4dfd-9fe3-d8a440afb4de`.

- Cycle 1: `93e8be01-6d18-5726-bba7-74a023a91255`; plan `a4e3dde9-76bb-5457-95ae-2ccf0d549623`; run `4d275bfc-6baf-416d-bddd-9c7d5d5639af`. Its handoff gate remains pending. No prior candidate was changed or approved.
- Cycle 2: [`d743a50a-89ff-45bd-8550-affb596e5558`](http://localhost:3000/work/57c730a8-b21c-4dfd-9fe3-d8a440afb4de?cycle_id=d743a50a-89ff-45bd-8550-affb596e5558), `DRAFT`, spec v1, no plan/run/approval. Goal: prepare the next increment and explicitly settle scope, baseline and criteria before planning.
- Live images: [draft](report/delivery-workspace/26-h8b-live-cycle-draft.jpg), [narrow layout](report/delivery-workspace/27-h8b-live-cycle-mobile.jpg), [history](report/delivery-workspace/28-h8b-live-cycle-history.jpg). Preview images `23`–`25` are labelled fixtures, not live executions; `25-h8b-draft-layout-preview.jpg` is desktop, not mobile evidence.
- Structured acceptance record: [h8b-live-cycle-evidence.json](report/delivery-workspace/h8b-live-cycle-evidence.json), including the post-restart protected-record comparison. It is a local observation record, not a Verify/release receipt.

No model call, new live run, human approval, commit, merge or push was performed during H8B acceptance. Unit-test control-gate runs are isolated from the live repository. Previous kernel test evidence is historical and remains distinct from this slice's software tests.

Next: **H8C** should resolve a safe frozen baseline/criteria and persist Harness-backed detailed task proposals for the selected successor, validate/preview/accept the exact task graph, then enable explicit execution only through that accepted cycle contract. Feedback triage, outcome acceptance and release remain separately authorized steps.

## Integration with main — 2026-10-19

Integrated the latest fetched main (`cee1900`) with the UI/H8B branch (`bd75307`). The merged tree retains the compact review/quality tabs, canonical task graph, cycle history, and legacy orchestrator subtask views. Rejection records an explicit reason; the workspace does not present an unsupported automatic redo as an implemented action.

Legacy subtask preparation and on-demand generation are blocked for Delivery-bound workflows. Reading a workspace must not trigger a second paid decomposition or replace its accepted graph. Materializing its frozen plan does not launch the legacy background planner. Detailed cycle proposals remain H8C work. Standalone legacy workflows keep their orchestrator adapter.

The shared SDK prompt builder is retained, together with dedicated web credentials, explicit model selection/readback and single-attempt generation. Planning-only restrictions and an explicitly requested compatible package/version take precedence over the default agent hint. The two historical orchestrator JSON fixtures now live under `adlc-flow/tests/fixtures/adlc-planning/`, not among runtime examples removed by main's cleanup.

Post-merge focused verification: **253 backend tests passed**, **288 frontend tests / 29 suites passed**, **0 targeted TypeScript diagnostics across 39 files**, and Ruff passed for the integration's Python changes. Two pre-existing pytest configuration warnings remain. No model, live run/approval, database migration or remote push was performed as part of this Git integration. These are focused integration checks, not a repository-wide build or live Product Loop acceptance.
