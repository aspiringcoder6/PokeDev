# ADLC execution contract v0.2

Status: **PROPOSED — schemas shipped, runtime adoption pending (ADR 0016 implementation plan)**

This directory extends the frozen [`v0.1/`](../v0.1/) execution contract with dynamic control flow
(MAP/WHILE/SUBWORKFLOW), saga compensation, and the identity fields that make expanded children and
compensation steps addressable on the wire. It is **additive and coexistent**: v0.1 files are never edited,
v0.1 payloads and runs keep working unchanged, and every v0.2 payload carries `schema_version: "0.2"`.

## Normative files

- [`state-machines.json`](state-machines.json) is the v0.2 transition allow-list. It is a strict superset of
  v0.1: every v0.1 state, transition, guard, and reopenable state is preserved.
- [`execution-contract.schema.json`](execution-contract.schema.json) is the Draft 2020-12 bundle mirroring the
  v0.1 bundle with the v0.2 additions below.
- [`examples/`](examples/) contains valid v0.2 payloads, including a map child request, a compensation
  request, and the expansion/compensation events that carry the new record shapes.

## What v0.2 adds

### New states

| Machine | New states | New transitions |
|---|---|---|
| `workflow_run` | `COMPENSATING`, `COMPENSATED` | `SUCCEEDED → COMPENSATING`, `FAILED → COMPENSATING`, `COMPENSATING → COMPENSATED`, `COMPENSATING → FAILED` |
| `task_run` | `COMPENSATING`, `COMPENSATED` | `SUCCEEDED → COMPENSATING`, `COMPENSATING → COMPENSATED`, `COMPENSATING → FAILED` |

`SUCCEEDED` and `FAILED` (run) and `SUCCEEDED` (task) keep their v0.1 meaning but gain exactly one guarded exit
(`authorized_compensation_command`), so they are no longer absorbing states. `COMPENSATED` is terminal for the
run's lifetime: a compensated run can never be retried; start a fresh run instead.

### New `TaskRequest` fields

Expansion children and compensation dispatches are ordinary task attempts, so the scheduler and executors need
no structural changes. The coordinator stamps the following optional fields on the v0.2 `TaskRequest`:

| Field | Type | Meaning |
|---|---|---|
| `purpose` | `EXECUTION \| COMPENSATION` (default `EXECUTION`) | Distinguishes a compensation dispatch from business work. |
| `parent_task_run_id` | UUID | Set on control-flow children; identifies the MAP/WHILE parent task run. |
| `map_index` | integer ≥ 0 | Zero-based position of a MAP child within the expansion. |
| `map_key` | string ≥ 1 | Stable, human-readable key of a MAP child (derived from the collection item). |
| `compensates_task_run_id` | UUID | Set when `purpose: COMPENSATION`; names the `SUCCEEDED` task being undone. |

A `WHILE` iteration is a child with `parent_task_run_id` only. Compensation dispatches set `purpose` and
`compensates_task_run_id` but never `map_index`/`map_key`.

### New payload records

`RunEvent.payload` remains an open extension object. Two closed record shapes are defined in `$defs` for
producers to embed so consumers can parse expansion and saga facts without out-of-band knowledge:

- `MapExpansionRecord` — canonical payload of `task_run.map_expanded`; enumerates the child task runs with
  their `map_index`, `map_key`, and `task_run_id`.
- `CompensationRecord` — canonical payload of `workflow_run.compensation_started` and
  `workflow_run.compensation_finished`; links the compensation child to the task it undoes with its reverse
  topological `saga_sequence`.

Suggested event type vocabulary (all match the v0.1 `event_type` pattern):
`task_run.map_expanded`, `task_run.map_joined`, `task_run.while_iteration_started`,
`task_run.while_iteration_finished`, `workflow_run.subworkflow_started`,
`workflow_run.compensation_started`, `workflow_run.compensation_finished`,
`workflow_run.compensation_failed`.

## Normative rules

1. v0.2 control-flow or compensation semantics on a run created against v0.1 are a validation error, never a
   silent downgrade. Runs record the contract version they were created with.
2. The plan stays frozen and static: it contains the control-flow *specification*, never the expanded
   children. Expansion is a runtime fact recorded as `RunEvent`s and ordinary child task runs.
3. Expansion depth is capped at one level in v0.2: a MAP/WHILE body task must not declare `control_flow`.
   This is a plan-validation rule enforced by the coordinator; deeper nesting requires a later contract
   version.
4. `SUBWORKFLOW` dispatch starts a nested run with a `subworkflow_of_run_id` back-reference; the parent task
   mirrors the child's terminal status (`SUCCEEDED → SUCCEEDED`, anything else → `FAILED` unless
   `failure_propagation: CONTINUE`).
5. Compensation executes only via the explicit run-level compensate command. There is no automatic
   compensation, no automatic inverse derivation, and a compensation failure terminalizes the run `FAILED`.
6. Unknown fields continue to be rejected. Extension data belongs in `metadata`, `details`, or `payload`.

## Compatibility policy

Consumers must reject unsupported versions at ingress. A v0.2-aware consumer accepts both directories and
branches on `schema_version`; a v0.1-only consumer rejects every `"0.2"` payload because its `ContractVersion`
is a `const: "0.1"` — which is the intended coexistence behavior, not a defect.
