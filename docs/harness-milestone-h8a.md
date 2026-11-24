# H8A — Canonical task graph in the Delivery Workspace

Status: **IMPLEMENTED** · 2026-10-18.

H8A exposes the saved execution plan in the main user journey. It does not introduce Product Cycles, call a planner, expand a workflow in the browser, or grant execution authority. H8B–H8E remain proposed in [the Product Loop plan](product-loop-implementation-plan.md).

## User journey

1. Open a work item at `/work/{delivery_id}` and select **Kế hoạch**.
2. **Sơ đồ** shows dependency arrows, parallel branches and joins, stage labels, plan version and task/link counts. Zoom is bounded to 50–150%, with a 100% reset.
3. **Danh sách** shows the same task IDs, objectives, outputs and statuses. On narrow screens, use the list or scroll the graph panel; the graph must not widen the page.
4. Select a task to open its read-only side drawer. It includes objective, declared inputs/outputs, prerequisites/dependents, acceptance criteria when available, package/executor and available scope limits. Use dependency links to move between tasks.
5. Open the existing run page for changes/evidence, or expand technical details for exact plan/task/runtime records. These are navigation actions, not approvals or retries.

Keyboard: native task buttons support Enter/Space; the graph scroll region is focusable. Escape closes the drawer when focus is inside it; focus returns to its opener. If a close-button tooltip is open, the first Escape may dismiss the tooltip.

The existing workflow approval, separate plan approval and explicit Start confirmation remain unchanged. No graph node is editable in H8A.

## Data and identity rules

- `ExecutionPlan.tasks` is canonical. Graph, list, Gantt and Kanban share `boardTasks(row)`; there is no additional UI task store.
- Branching uses the existing `PlanTaskGraph` DAG layout. Each task is rendered once and each declared dependency has its own arrow. SVG markers are unique per viewer instance.
- Stage labels use the original workflow-stage identity where the compiler preserves it in task metadata, otherwise the direct source-stage ID. Unknown lineage is labelled, not inferred from names or positions.
- Runtime overlay requires matching Delivery/flow/plan/run IDs plus `plan_traceability.execution_plan_id` and `plan_task_id`. Exactly one runtime record must match; missing, foreign or duplicate records remain **Chưa đối soát**.
- Selection is scoped to delivery, plan ID/digest and run ID. Changing that scope clears the old drawer. Within one scope, details follow the latest task projection rather than retaining a stale snapshot.
- Acceptance information is read from declared Task Loop specifications (object or JSON string). Missing/malformed information is unavailable; no PASS/FAIL, check execution or human assignment is fabricated.
- Task success is not independent Verify or release. The evidence link opens existing run review; it does not certify all evidence on that page or satisfy an approval gate.
- Current direct compilation is stage-level. When the plan has one task per workflow stage, the UI states this limitation. Detailed stage-to-many-task generation is future H8C work.

No backend endpoint, database schema, permissions policy, runtime adapter or approval contract was changed for this slice.

## Verification

| Check | Result |
| --- | --- |
| Frontend regression: Delivery Workspace, graph renderer, Plan Detail and all Run Detail tests | **186 passed / 18 suites** |
| Frozen branching fixture vs real backend BlueprintCompiler | **1 passed**; full JSON equality, 4 nodes, 4 edges and both join dependencies |
| Targeted semantic/syntax TypeScript diagnostics | **0**, across 8 H8A source/preview files |
| Ruff for the new backend fixture test | Passed |
| Live workspace | Existing 2-task / 1-edge plan; implementation completed, handoff pending; read-only viewing and keyboard selection checked |
| Labelled UI fixture | Parallel branches/join checked at desktop 1280×720; phone 390×844 with contained overflow, task drawer and Escape dismissal |

Frontend regression command, from `adlc-flow/frontend`:

```powershell
node node_modules/jest/bin/jest.js src/features/delivery-workspace src/features/adlc-blueprint/plan-task-graph.test.tsx src/pages/PlanDetailPage/index.test.tsx src/pages/RunDetailPage --runInBand --silent
```

Backend fixture check, from `adlc-flow` (use a fresh local test-temp directory if an older Windows temp directory has restricted permissions):

```powershell
$env:PYTHONPATH='.'
$env:OPENBLAS_NUM_THREADS='1'
$env:OMP_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
.\.venv\Scripts\python.exe -m pytest tests/unit/adlc/planning/test_h8a_task_graph_fixture.py -q -p no:cacheprovider --basetemp=data/test-tmp-h8a-graph-recheck
```

The fixture was generated from the real compiler, not by manually constructing a graph-shaped UI object. It is never dispatched; its mock executor reference is not evidence of a live agent session. The test preview remains outside the product router at `/tests/delivery-workspace-preview/index.html?scenario=task-graph`, with a visible sample-only banner.

These focused checks do not certify the repository-wide TypeScript build, every browser/device, or repeated Product Cycles. Existing broader-repository issues are not hidden by the H8A result.

## Live evidence

Observed existing delivery: `57c730a8-b21c-4dfd-9fe3-d8a440afb4de`.

- Plan: `a4e3dde9-76bb-5457-95ae-2ccf0d549623`.
- Run: `4d275bfc-6baf-416d-bddd-9c7d5d5639af`.
- The final handoff gate remained pending during H8A. No model call, new run, approval, candidate modification, commit, merge or push was performed. No service reload was needed.
- Browser recovery required a fresh tab after the old tab stopped capturing; a transient development-module import error cleared on reload. The final screenshots are of rendered UI, not reconstructed images. The temporary viewport override was reset.

![Live saved task graph](report/delivery-workspace/18-h8a-live-task-graph.jpg)

![Live read-only task details](report/delivery-workspace/19-h8a-live-task-details.jpg)

![Compiler-validated branching fixture — sample only, not execution](report/delivery-workspace/20-h8a-branching-fixture.jpg)

Phone-width captures: [graph](report/delivery-workspace/21-h8a-narrow-graph.jpg), [drawer](report/delivery-workspace/22-h8a-narrow-task-details.jpg). The graph's content scrolls inside its panel; document width remained 390px. Fixture screenshots are not live execution evidence.

## Main implementation files

- `adlc-flow/frontend/src/features/adlc-blueprint/plan-task-graph.tsx`: shared selectable/zoomable renderer with backward-compatible defaults.
- `adlc-flow/frontend/src/features/delivery-workspace/task-plan-view.tsx`: Graph/List and stage/status presentation.
- `adlc-flow/frontend/src/features/delivery-workspace/task-plan-model.ts`: stage lineage, declared acceptance and selection scope.
- `adlc-flow/frontend/src/features/delivery-workspace/task-details.tsx`: read-only drawer.
- `adlc-flow/frontend/src/features/delivery-workspace/model.ts`, `workspace-page.tsx`, `workspace.css`: common identity/status projection and integration.
- `adlc-flow/frontend/tests/delivery-workspace-preview/task-graph-plan.json`: frozen, compiler-validated branching plan.
- `adlc-flow/tests/unit/adlc/planning/test_h8a_task_graph_fixture.py`: compiler reproducibility/contract check.

## Next boundary

**H8B** adds durable cycle lifecycle/history while preserving this existing plan, run, evidence and pending authority. H8A does not yet let feedback regenerate another task graph in the same product workspace. Workflow versions, Product Cycles, plan revisions and per-task candidate loops remain distinct concepts.
