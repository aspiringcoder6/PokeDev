# ADR 0002: Compile blueprints into execution plans before runtime

- Status: **Accepted**
- Date: 2026-09-07
- Scope: ADLC planning and orchestration

## Context

Langflow's native graph is an executable graph of component nodes and typed handles. The ADLC product needs a different authoring abstraction: users define lifecycle stages, objectives, policies, expected outputs, and dependencies, while the framework determines concrete executable tasks and assignments.

Executing an ADLC blueprint directly would mix author intent, planning decisions, package resolution, validation, and mutable runtime state. It would also make it difficult to review the concrete task DAG before work begins.

## Decision

ADLC uses three separate representations:

```text
WorkflowDefinition
  -> ExecutionPlan
  -> WorkflowRun
```

1. A `WorkflowDefinition` is an abstract, user-authored graph of high-level stages.
2. The ADLC planning service parses the blueprint, resolves package versions, validates the graph and policies, and produces a versioned `ExecutionPlan` containing concrete `PlanTask` records.
3. An invalid or unresolved plan cannot create runtime aggregates.
4. A plan requiring review must be approved before materialization.
5. Materialization creates `WorkflowRun` and `TaskRun` records from an accepted plan.
6. The existing ADLC scheduler executes materialized tasks through `TaskExecutor`.
7. A compiler invocation is side-effect free with respect to workflow/task runtime state.
8. Regeneration creates a new plan version; it never rewrites an accepted plan.

The ADLC blueprint is not passed to Langflow's native `Graph.from_payload` execution path.

## Consequences

### Benefits

- Users can review concrete tasks, dependencies, assignments, and risks before execution.
- Package and capability failures are detected before a run exists.
- Runtime state has a stable, immutable planning source.
- Plan generation and runtime scheduling can evolve independently.
- Every task can be traced back to user intent and planning rationale.

### Costs

- The system needs new plan models, APIs, persistence, validation, and UI.
- Starting a run becomes a multi-step operation rather than direct graph execution.
- Blueprint changes after plan generation require regeneration or a new plan version.

## Alternatives considered

### Execute every canvas node directly

Rejected as the target architecture because canvas-node granularity is authoring-dependent and does not establish a reviewed concrete plan. It remains only as the legacy mock vertical slice.

### Expand packages dynamically inside the scheduler

Rejected because scheduler dispatch would become non-deterministic and package resolution failures could occur after a run has partially started.

### Use Langflow's native graph as the execution plan

Rejected because it exposes component wiring rather than ADLC stage semantics and does not provide the required plan lifecycle, rationale, approval, or package snapshot.

## Implementation constraints

- The compiler may read repository/project context but must not start tasks, agents, commands, or sandboxes.
- Planning-model output is untrusted input and must pass deterministic validation.
- Every `PlanTask` must reference its source `WorkflowStage`.
- Only exact registered package and capability references may enter a validated plan.
- Materialization must be idempotent for one accepted plan and idempotency key.
- Runtime replanning is deferred; completed task history may never be rewritten.

## Related decisions

- [ADR 0001](./0001-versioned-node-packages.md)
- [ADR 0004](./0004-snapshot-resolution-and-legacy-compatibility.md)
