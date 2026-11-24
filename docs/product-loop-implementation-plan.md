# Product Loop and detailed task graphs

Status: **H8A–H8C PLANNING/ACCEPTANCE IMPLEMENTED — H8D–H8E PROPOSED**
Assessment updated: 2026-10-20
Scope: the Delivery Workspace (`/work`) and its existing ADLC planning/runtime boundaries.

This is a development plan, not an accepted execution contract. Writing this document does not approve a workflow, call a model, start a run, change an existing candidate, or authorize Git operations.

## 1. Current implementation

| Capability | Current state |
| --- | --- |
| Requirement → workflow → workflow approval → plan approval → explicit Start | Implemented in Delivery Workspace. |
| Executable task dependency graph | Exists in `ExecutionPlan.tasks`, including dependency IDs, package resolution, policies, inputs and expected artifacts. Created when compiling a plan, not merely when saving a workflow. |
| Graph visualization | H8A reuses `PlanTaskGraph` in the workspace's Plan step, with Graph/List views, stage labels, live status and a read-only task drawer. Timeline and board use the same task projection. The advanced Plan Detail viewer remains available. |
| Detailed decomposition | H8C adds a selected-successor-cycle Harness planner, durable generation receipts, deterministic proposal validation/expansion, exact compiled preview and separate human graph acceptance. Legacy first-cycle direct compilation remains compatible. |
| Direct workspace compilation | `_build_plan_tasks` creates one plan task per workflow stage. Recompiling unchanged stages does not, by itself, discover smaller implementation tasks or consume feedback. |
| Plan history | H8B adds SQL-owned cycle lineage, append-only spec revisions, plan snapshots/approval provenance, durable command receipts and a per-product execution slot. Workspace compilation uses SQL versions rather than process-local counters. |
| Task Loop | Exists, including the Harness adapter and candidate/checkpoint/check evidence. It improves a candidate within one frozen task specification. |
| Feedback intake | H8B attributes and deduplicates notes by source cycle. They do not automatically become selected backlog items, an approved scope, a successor plan or a new run. |
| Repeated product cycles in one workspace | H8B supports cycle selection/history. H8C adds frozen successor input and separately accepted task graphs. The first cycle retains its original plan/run/authority. Successor dispatch stays closed until the outcome/baseline handoff adapter is implemented. |

Conclusion: **Durable Product Cycle foundations and draft/history UI are implemented. The end-to-end feedback → next cycle → newly accepted task graph → execution loop is not yet implemented.** Preparing a draft is not authority to run it.

The current acceptance plan is `a4e3dde9-76bb-5457-95ae-2ccf0d549623`. Its graph has two tasks: implementation/verification, followed by handoff approval. Agent-authored steps inside a task prompt are not additional scheduler-visible graph nodes.

### Source locations

- `adlc-flow/langflow/api/v1/adlc_delivery.py`: compile/start guards, approval bindings and note intake.
- `adlc-flow/langflow/services/database/models/adlc_delivery.py`: single plan/run navigation record.
- `adlc-flow/langflow/adlc/delivery_cycles.py` and `services/database/models/adlc_product_cycle.py`: durable cycle/spec/head/plan/feedback/operation records; first-cycle compatibility boundary.
- `adlc-flow/langflow/adlc/planning/compiler.py`: deterministic stage-to-task projection.
- `adlc-flow/langflow/adlc/planning/proposals/`: decomposition proposal, validation and expansion.
- `adlc-flow/langflow/adlc/planning/service.py`: plan regeneration and lifecycle.
- `adlc-flow/langflow/services/database/models/adlc_execution_plan/`: durable execution-plan archive.
- `adlc-flow/frontend/src/pages/PlanDetailPage/index.tsx` and `features/adlc-blueprint/plan-task-graph.tsx`: existing dependency viewer.
- `adlc-flow/frontend/src/features/delivery-workspace/`: current user journey, task graph/list/drawer, timeline/board, results and notes.

## 2. Target model

### Separate process from the work selected for a cycle

1. **Workflow version** defines the process: stages, stage dependency rules, available capabilities, quality gates and authority boundaries. Reuse it while that process remains appropriate.
2. **Product Cycle** defines one increment: goal, selected requirements/backlog, baseline repository snapshot, acceptance criteria, budget and pinned workflow version.
3. **Plan revision / task graph** defines the executable work for that cycle: concrete tasks, dependencies, inputs/outputs, assignments and resolved execution policies.
4. **Run** executes one accepted plan snapshot through the existing coordinator.
5. **Task Loop** retries/improves one task's candidate under its frozen scope and criteria. It does not regenerate the product plan on each model turn.
6. **Feedback** proposes a later increment. Intake is not approval to edit an active run or spend more model budget.

Workflow versions may remain the same across many cycles. Each newly planned cycle gets its own reviewed graph snapshot; its shape may legitimately be similar to a previous graph. New requirements, affected code and prior evidence determine which work is necessary. Regeneration must not mean blindly recreating and rerunning all previous tasks.

The existing blueprint also carries task-specific inputs, including Task Loop specifications. To make the process reusable, keep the legacy format supported but introduce a separate frozen cycle input contract. The planner binds cycle inputs into tasks; it must not silently edit the approved workflow template.

### Versioning rules

- Changing process stages, gates or permission policy requires a new workflow version and its own review.
- Changing cycle scope or acceptance criteria requires a new cycle-spec revision and an explicitly reviewed successor plan.
- After acceptance, semantic plan contents are immutable. A graph cannot be edited underneath an executing run.
- A new product increment links to the previous cycle; it does not retroactively invalidate that cycle's completion. A replacement plan within one cycle uses the existing supersession semantics.
- Runtime task graphs remain DAGs. The feedback loop is represented by linked cycles/plans, not a cyclic dependency edge in the scheduler.
- Graph, list, timeline and Kanban are projections of the same canonical plan/run records, not separate task stores.
- Prior evidence is a reference with provenance, not a fresh test execution. Automatic reuse requires an explicit validity rule over baseline, inputs, task/spec, dependencies, toolchain and evidence. Start with no automatic cross-cycle result reuse.

## 3. Shared contracts

Proposed versioned records, to be validated by the backend and read by both agent tools and UI:

**CycleSpec**

- Product/delivery ID, cycle ID/number, predecessor cycle and optimistic revision.
- Workflow version/digest and parent cycle's accepted output reference.
- Goal, selected backlog IDs, requirement/contract references and acceptance criterion IDs.
- Repository identity plus immutable baseline commit or separately accepted candidate snapshot. Resolve branch names to a snapshot before approval; reject stale bindings at Start.
- Allowed changes and stage capability constraints, model/runtime/plugin locks and resource limits.
- Content digest and approval provenance.

**TaskGraphProposal / ExecutionPlan**

- Cycle-spec reference, proposal/plan revision and predecessor references.
- Stable task keys for cross-revision comparison; revision-specific task IDs for execution.
- Original workflow stage ID, requirement/criterion references, objective and planning rationale.
- Explicit dependency edges and typed input/output bindings, including required joins.
- Expected artifacts, task-specific scope, acceptance/check profiles and risk classification.
- Human/agent responsibility and a resolved package/runtime binding. Requested access never grants authority by itself.
- Semantic digest, validation findings and human approval provenance for the exact executable snapshot.

**CycleOutcome / FeedbackItem**

- Candidate/artifact references, exact evidence and remaining gaps.
- Accepted/rejected/deferred decisions, optional separately authorized release reference.
- Attributed feedback, source event identity, triage status and links to the next cycle.
- Separate statuses for candidate acceptance, cycle completion and release. A successful task or test is not proof that the product was shipped.

These records extend existing planning/materialization boundaries rather than introducing another scheduler. Persist proposals and generation operations before depending on them across restarts.

## 4. Implementation slices

### H8A — Show the canonical task graph in the main workspace

**Status: implemented, 2026-10-18.** See [H8A implementation and verification](harness-milestone-h8a.md). This is a read-only projection of saved tasks, not detailed-task generation or a Product Cycle engine.

**Outcome:** users can see the graph that actually exists today, before granting execution authority.

- Add `Graph / List` views to the plan step, reusing `PlanTaskGraph`.
- Show parallel branches, dependency arrows and joins, with grouping by original workflow stage where available.
- Selecting a node opens a compact drawer: objective, inputs, expected output, acceptance information actually present, dependencies, executor/responsibility and links to evidence. Missing fields are shown as unavailable, not generated in the browser.
- Overlay run status using `plan_traceability.plan_task_id`; link to existing candidate/check evidence.
- Keep timeline/Kanban on the same task identities and selected plan version. Retain clear estimated-versus-measured time labels.
- Explain that the current direct compiler is stage-level when a plan only has one task per stage. Do not expand it visually into tasks that do not exist.

**Acceptance:** the existing two-task plan appears as two linked nodes; a validated branching fixture shows distinct branches and a join once each; graph/list/board counts and dependency relationships agree. Viewing the graph never starts a model/run or approves work. Check keyboard navigation and narrow layout.

### H8B — Durable cycle lifecycle and history

**Status: implemented and activated locally, 2026-10-19.** See [H8B implementation, activation and evidence](harness-milestone-h8b.md). Successors are draft-only; no new planner, automatic baseline selection or cross-cycle execution is claimed.

**Outcome:** one product workspace can contain multiple cycles without losing the current run.

- Add durable cycle/spec, plan-revision binding, feedback/backlog and generation-operation records through an additive migration.
- Keep the existing Delivery ID as the product navigation anchor. Import its existing plan/run/approvals as the first historical cycle; do not reset or restart it. Preserve its current authority bindings until an explicit new cycle is accepted.
- Move future plan/run selection into the selected cycle; retain compatibility for current links and archived records.
- Use transactional revisions/idempotency for cycle numbering, selected scope, plan attachment and dispatch reservation. For the first release allow one active execution cycle per product.
- Strengthen durable lineage/head/idempotency management instead of treating in-memory plan counters and proposal dictionaries as a multi-worker source of truth.
- Preserve server-side owner/project permissions. Managed/shared project execution stays blocked until its explicit team-authorization adapter exists; do not bypass that guard via a new route.
- UI: cycle selector, current goal, plan version and read-only history, with an explicit `Prepare next cycle` action. This action creates a draft only.

**Acceptance:** old URLs and evidence remain readable; a second draft can coexist with first-cycle history; restart preserves state; stale commands and duplicate requests cannot replace the head or create a second dispatch. Alternate advanced APIs cannot silently swap the workspace's approved plan.

**Delivered boundary:** six additive SQL tables; import of existing Delivery bindings as cycle 1; SQL-owned compile/approval/dispatch for that cycle; one pending successor draft with append-only goal revisions and attributed notes. The root URL still opens cycle 1; `?cycle_id=` selects a specific cycle. Successor drafts have no inherited plan/run/approval and cannot compile/start through either workspace or advanced planning APIs. Releasing the execution slot for a newly accepted successor belongs to subsequent planning/outcome slices, not a draft action.

### H8C — Integrate detailed proposal planning through Harness

**Status: planning/acceptance implemented and activated locally, 2026-10-20.** See [H8C implementation, activation and limits](harness-milestone-h8c.md). Live Luna generation still needs a user-frozen CycleSpec; readiness/fixtures are not live acceptance. Successor Start remains deliberately blocked pending the H8D–H8E outcome/baseline boundary.

**Outcome:** one workflow stage can produce several real, inspectable tasks for the selected cycle.

- Reuse the planner protocol, proposal schema, deterministic validator and expansion/compiler pipeline; supply the frozen CycleSpec, repository context, selected feedback and allowed package capabilities.
- Add a Harness-backed planner adapter; do not create an unrelated execution runtime. Live acceptance uses only `my-codex / cx/gpt-5.6-luna`, with no model fallback.
- Persist generation identity/status and its exact input snapshot. An unknown acknowledgement is reconciled, not automatically retried as another paid generation.
- Validate stage/requirement coverage, dependency DAG, stage entry/exit ordering, joins, input bindings, executable package inputs, scope, gates, limits and effective permissions. Block unsupported or uncovered required work.
- Maintain original stage lineage through expanded tasks; keep the authoring workflow separate from its expanded executable projection.
- Preview the exact compiled graph, then accept that snapshot; do not inherit or silently subsume approval through the legacy proposal action. Explicit Start remains a distinct action.
- UI: `Generate detailed tasks`, generation progress, graph preview, validation findings, task detail and revision comparison. Use concise summaries with optional advanced JSON.

**Acceptance:** a representative high-level workflow produces multiple implementation/testing tasks with correct parallel joins. Unauthorized packages, widened file scope, absent gates, stale baselines and unsupported test executors fail closed. Restart/uncertain acknowledgement does not duplicate a model call. Displayed/approved/executed graph digests match.

### H8D — Feedback → successor cycle and impact-aware replanning

**Outcome:** feedback can drive the next increment while the process workflow remains unchanged.

- Triage notes, verification failures and optional signed issue/webhook intake into attributed backlog records. Deduplicate source events; external text is data, not permission.
- Let the user select backlog items, goal, baseline, budget and acceptance changes for the next cycle. Do not automatically include every comment or unresolved suggestion.
- Generate the next cycle's graph from those inputs, linking its parent outcome and feedback. Show tasks added, removed, affected and referenced from earlier work using stable keys.
- Preserve completed tasks, decisions and evidence from earlier runs. Initially reference prior results without automatic reuse; re-execute affected checks on the new integrated candidate.
- For changed scope during execution, offer an explicit pause/revision path at a safe boundary. A successor plan/run requires a new decision; it must not mutate an active graph or inherit approval.
- Add bounded cycle/iteration budgets and an explicit stop/continue decision. Feedback collection alone does not authorize unattended paid loops.
- UI: backlog triage, `Plan next cycle`, semantic change summary and cycle history. Keep workflow versions distinct from cycle/plan revisions.

**Acceptance:** two cycles use the same workflow digest but have different goals/graph snapshots; a selected change becomes traceable new work; duplicate feedback does not create duplicate cycles; no old result or approval is rewritten. An out-of-process requirement requests a workflow revision instead of bypassing its gates.

### H8E — Close the execution/evidence loop and validate two real cycles

**Outcome:** the product journey works across two cycles with truthful evidence and explicit delivery authority.

- Connect cycle completion to canonical run/candidate decisions and real evidence providers. Keep Task Loop tests, independent Verify, TestForge and UI observations distinct.
- Only publish PASS/FAIL from the appropriate validated execution evidence. Existing sample UI must remain labelled and cannot satisfy a gate.
- Reuse existing Git/release adapters where configured, binding authorization to the exact candidate/repository/branch. Commit, merge and push remain separately scoped actions, not a side effect of replanning or test success.
- Choose the next baseline from an accepted output or verified repository snapshot. A prior rejected or still-pending candidate is not an automatic baseline.
- UI: per-cycle outcome, limitations/open backlog, evidence/release links and a clear next-cycle action.
- Add coverage for restart, conflicting commands, permission revocation, graph/result binding, budget exhaustion, stopped loops and uncertain external acknowledgements.

**Acceptance:** in an explicitly approved test repository, cycle one delivers a small application increment; selected feedback creates cycle two with a different task graph; the second increment is checked against locked new criteria plus relevant regressions. Both cycles preserve workflow/plan/run/candidate/evidence lineage. No fabricated service evidence, approval inheritance or unapproved Git operations. Only Luna is used for real model tests.

## 5. Scope and rollout

Recommended order: **H8A → H8B → H8C → H8D → H8E**. Each slice includes its UI, backend changes where needed, regression tests and updated limitations. H8A is immediately useful and does not need a model call or a runtime reload.

The first complete Product Loop is human-directed: feedback may be collected automatically, but cycle scope, plan acceptance and execution authority stay explicit. Policy-governed unattended cycles, automatic cross-cycle result reuse, parallel product cycles and full shared-team delegation are later increments, not claims for this rollout.

Do not mark Product Loop implemented merely because another plan can be generated. Completion requires the second-cycle lineage, selected feedback, immutable acceptance boundary, real execution/evidence and truthful user-facing outcome to work together.
