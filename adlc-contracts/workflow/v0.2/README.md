# Workflow authoring v0.2 — execution plan

Status: **PROPOSED — schemas shipped, compiler adoption pending (ADR 0016 implementation plan)**

This directory mirrors [`workflow/v0.1/`](../../workflow/v0.1/) with the v0.2 execution-plan schema. It is
additive: the v0.1 workflow-definition and node-package schemas are unchanged and stay the source of truth for
authoring; only the *plan* carries the new dispatch semantics.

## Files

- [`execution-plan.schema.json`](execution-plan.schema.json) — the v0.1 plan schema plus the additions below;
  `schema_version` is pinned to `"0.2"` at the top level and inside `ResolvedNodeSpec`.
- [`examples/execution-plan.json`](examples/execution-plan.json) — a valid v0.2 plan with a MAP task, its body
  task carrying a compensation spec, and the trailing approval task.

## What v0.2 adds to `PlanTask`

### `control_flow` (optional, closed, discriminated by `shape`)

| Shape | Required | Optional | Meaning |
|---|---|---|---|
| `MAP` | `collection_source`, `join`, `body` | `item_alias`, `max_fanout` (default 100), `failure_policy` (default `FAIL_FAST`) | Expands at dispatch into one child task run per resolved collection item. |
| `WHILE` | `condition`, `body` | `max_iterations` (default 100) | Dispatches the body as one child attempt per iteration until the condition is false or the budget is spent. |
| `SUBWORKFLOW` | `workflow_ref` | `input_mapping`, `output_binding`, `failure_propagation` (default `PROPAGATE`) | Starts a nested workflow run as a child; the parent task mirrors its terminal status. |

- `join` is `{kind: ALL \| ANY \| QUORUM, quorum_size?}`; `quorum_size` is required when `kind: "QUORUM"`.
- `failure_policy` is `FAIL_FAST \| COMPLETE_THEN_FAIL \| SKIP_FAILURES`.
- `body` is a non-empty list of `plan_task_id` references into the same plan's `tasks`.
- `collection_source` and `condition` are strict template expressions using the `{{run.*}}` / `{{task.*}}`
  grammar; `input_mapping` values and `compensation.input_template` follow the same grammar.

### `compensation` (optional, closed)

`{task_type, executor: {service, operation}, input_template, timeout_ms?, max_attempts}` — declares the
executor dispatch that undoes this task's effects. `max_attempts` is pinned to `1`: compensations never retry.
Compensation runs only via the explicit run-level compensate command; it is never scheduled automatically and
never derivable from the task body.

## Normative rules

1. The plan contains the control-flow *specification*, never expanded children. Expansion happens at runtime
   and is recorded as events plus ordinary child task runs.
2. A body task referenced by `control_flow.body` must not itself declare `control_flow` (depth cap of one
   level in v0.2). Plan validation outside the JSON Schema enforces this together with referential checks
   (body ids exist, body tasks are not independently scheduled).
3. `contract_version: "0.2"` (optional, defaults to `"0.2"`) records which execution-contract version the
   plan's dispatch semantics assume.
4. `additionalProperties: false` is preserved everywhere: a plan task carrying `control_flow` or
   `compensation` is **rejected by the v0.1 schema**, which is exactly how v0.1-only consumers fail closed.
