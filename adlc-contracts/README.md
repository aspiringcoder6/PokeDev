# ADLC contracts

## Unified Coding Agent contract verification v0.1

The additive [`coding-agent/v0.1/`](coding-agent/v0.1/README.md) report binds an approved contract and its predicate checks to the same candidate and specification as the task-loop behavioral report. The unified `coding-agent@0.2.0` package supports these features together in one run.

## Task loop v0.2 (Delivery B)

The separate [`task-loop/v0.2/`](task-loop/v0.2/README.md) contracts add pinned Git candidates and protected command verification for the opt-in live OpenCode package. They preserve the base v0.1 execution contracts and the v0.1 mock boundary.

## Task loop v0.1 (Delivery A)

The separately versioned [`task-loop/v0.1/`](task-loop/v0.1/README.md) boundary implements the opt-in deterministic
mock loop: one fixed specification, fresh session per task attempt, cumulative candidate snapshots, exact mock file
checks, bounded repetition, and final human approval. Live execution and durable loop checkpoints are Delivery B.

## Task and command execution v0.1

Status: **v0.1 FROZEN**

This directory is the source of truth for the first ADLC run lifecycle and the service-neutral payloads exchanged by the coordinator, executors, approval service, persistence layer, and UI event stream.

## Normative files

- [`../docs/state-machine.md`](../docs/state-machine.md) defines lifecycle meaning, guards, and event names.
- [`v0.1/state-machines.json`](v0.1/state-machines.json) is the machine-readable transition allow-list.
- [`v0.1/execution-contract.schema.json`](v0.1/execution-contract.schema.json) is a JSON Schema Draft 2020-12 bundle.
- [`v0.1/examples/`](v0.1/examples/) contains one valid payload for each public contract.

The ten public schema entry points are:

| Contract | Schema reference | Purpose |
|---|---|---|
| `TaskRequest` | `#/$defs/TaskRequest` | Immutable dispatch request for one task attempt. |
| `TaskResult` | `#/$defs/TaskResult` | Immutable terminal result for that attempt. |
| `RunEvent` | `#/$defs/RunEvent` | Ordered, durable fact in a workflow run timeline. |
| `Artifact` | `#/$defs/Artifact` | Immutable metadata and integrity information for an out-of-band result. |
| `ServiceError` | `#/$defs/ServiceError` | Safe, structured error shared across service boundaries. |
| `ApprovalRequest` | `#/$defs/ApprovalRequest` | Blocking, auditable human decision and its context. |
| `CommandExecutionRequest` | `#/$defs/CommandExecutionRequest` | Idempotent argv-style request for one process inside a sandbox. |
| `CommandExecutionResponse` | `#/$defs/CommandExecutionResponse` | Current or terminal command state, logs, errors, and outputs. |
| `ExecutionLogEntry` | `#/$defs/ExecutionLogEntry` | Ordered, redaction-aware command log record. |
| `ArtifactReference` | `#/$defs/ArtifactReference` | Lightweight pointer to artifact bytes stored out of band. |

Validate each payload against its named `$defs` entry, rather than the bundle root, when its type is already known.

## Wire conventions

1. Every independently transported request, response, event, artifact, error, or approval payload carries `schema_version: "0.1"`. Embedded value objects such as `ExecutionLogEntry` and `ArtifactReference` inherit the enclosing payload version.
2. Field names are `snake_case`; enum values are uppercase unless a field explicitly defines another pattern.
3. IDs typed as UUID are stable identifiers, not database row numbers. Timestamps are UTC RFC 3339 values.
4. Public objects reject unknown fields. Forward-compatible product data belongs only in a documented `metadata`, `details`, `payload`, `variables`, or `custom` extension object.
5. Extension objects must contain JSON values and must not contain secrets, credentials, raw environment variables, or unredacted sensitive data.
6. Producers must not change a payload after publishing it. Corrections are new events or new attempts, never in-place history edits.

## Contract semantics

### `TaskRequest`

- Represents exactly one dispatch attempt, identified by `request_id` and `attempt_id`, for a stable `task_run_id`.
- `idempotency_key` is required. Re-delivery of the same key and same semantic request must return/replay the existing outcome without starting duplicate work. Reuse with different content must fail with `ServiceError.code = "IDEMPOTENCY_CONFLICT"`.
- `input` is the executor input. `context` contains references and scoped variables; it must not embed artifact bytes.
- `dependency_task_run_ids` records the dependencies that were satisfied when the coordinator made the task ready.
- A retry creates a new `request_id` and `attempt_id`, while preserving `workflow_run_id`, `task_run_id`, and `task_definition_id`.

### `TaskResult`

- Represents only a terminal attempt result: `SUCCEEDED`, `FAILED`, or `CANCELLED`. Waiting for approval is represented by `ApprovalRequest` and `RunEvent`, not a partial result.
- All identity fields must match the accepted `TaskRequest`.
- `SUCCEEDED` requires `error: null`; `FAILED` requires a `ServiceError`; `CANCELLED` requires a `ServiceError` in the `CANCELLED` category.
- `output`, `artifacts`, and `error` are always present so consumers do not need to infer omitted values.
- Accepting a result and updating the task state must be atomic with the corresponding `RunEvent`. A different second result for the same `attempt_id` is a state conflict.

### `CommandExecutionRequest`

- Represents one concrete command inside an already-provisioned sandbox. One task attempt may issue zero, one, or many command requests.
- Uses `executable` plus `arguments`; shell parsing is not implicit.
- `idempotency_key` prevents duplicate process starts when a request is redelivered.
- `environment` contains non-sensitive values. `secret_refs` contains opaque references, never resolved secret values.

### `CommandExecutionResponse`

- May represent `QUEUED`, `RUNNING`, or a terminal command state: `SUCCESS`, `FAILED`, `TIMEOUT`, or `CANCELLED`.
- Command `SUCCESS` is interpreted by an adapter and may contribute to task-level `SUCCEEDED`; it never completes a `TaskRun` by itself.
- A launch failure may move directly from `QUEUED` to `FAILED`, leaving `started_at` and `exit_code` null.
- `SUCCESS` requires `exit_code: 0` and `error: null`. `TIMEOUT` and `CANCELLED` require matching `ServiceError.category` values.
- Logs are ordered by unique increasing `sequence`. `logs_truncated: true` indicates that the response contains only a bounded window.
- `artifact_refs` contains references only. Full `Artifact` records are materialized when outputs are accepted at task level.

### `RunEvent`

- Is delivered at least once. Consumers deduplicate by `event_id`.
- `sequence` is monotonically increasing within one `workflow_run_id`; timeline consumers order by `(sequence, event_id)`, not wall-clock time.
- `aggregate_type` determines the allowed `previous_status` and `status` enum. For state events, both fields are required except creation events, which use `previous_status: null`.
- `aggregate_id` is the ID of the stated aggregate. When the corresponding scoped ID is present (`task_run_id` or `approval_request_id`), it must equal `aggregate_id`.
- `payload` is event-specific context. State snapshots belong in aggregate storage, not in this field.

### `Artifact`

- Describes a task-attempt-produced artifact. Bytes are stored out of band and addressed by `uri`.
- `checksum` is SHA-256 of the exact stored bytes. An artifact ID is immutable: changed bytes require a new `artifact_id`.
- `media_type`, `size_bytes`, producer identity, and provenance IDs are mandatory so the UI can inspect an artifact without downloading it.
- `kind` is an open uppercase vocabulary. Initial recommended values are `SOURCE_PATCH`, `TEST_REPORT`, `REVIEW_REPORT`, `LOG`, `TRACE`, and `DOCUMENT`.

### `ServiceError`

- `code` is a stable machine-readable value; `message` is a safe operator-facing summary. Consumers must not branch on message text.
- `retryable` says whether retrying the same operation could succeed. The coordinator still applies its own retry policy and budget.
- `details` may contain redacted diagnostics. Stack traces and provider responses stay in protected logs and may be linked by `correlation_id`.
- Reserved v0.1 codes include `STATE_CONFLICT`, `IDEMPOTENCY_CONFLICT`, `APPROVAL_REJECTED`, and `APPROVAL_EXPIRED`.

### `ApprovalRequest`

- Is blocking in v0.1 and belongs to one workflow, task, and attempt. A task may have history but at most one `PENDING` blocking approval.
- Must offer at least one `APPROVE` action and one `REJECT` action.
- `decision` is `null` while pending and immutable after resolution. Its effect must agree with the resulting approval status.
- `gate_type` fixes the approved task transition: `BEFORE_TASK -> READY`, `ACTION -> RUNNING`, and `AFTER_TASK -> SUCCEEDED`.
- Authorization is evaluated from `required_role` plus optional `reviewer_ids`; the payload itself is not proof that an actor is authorized.

## Compatibility policy

The combined task and command contracts under `v0.1/` are frozen. Because public objects are closed, adding or renaming a field, changing requiredness, narrowing a value, or changing lifecycle meaning requires a new version directory and a new `schema_version`. Documentation-only clarifications may be made without changing the contract.

Consumers must reject unsupported versions at ingress. During a migration, producers may dual-publish only when the transport assigns an unambiguous schema version. Extension fields inside the designated open objects must be preserved when a service forwards a payload, even when it does not understand them.

## Harness execution boundary v0.1

Status: **DRAFT — H0/H1/H2/H3 IMPLEMENTED**

The separately versioned [`harness/v0.1/`](harness/v0.1/) contract adapts an ADLC task attempt to an asynchronous
DeepSeek Harness session. It defines locked runtime plugins, typed interactions, verification reports, session events,
explicit submission, signed outbox delivery, callback receipts, durable external `TaskAttempt` projections, and
reconciliation without changing the frozen base task/command contract. H3 adds a typed, secret-free installed-plugin
inventory and fail-closed verification of runtime bytes against the execution lock.

The following remain intentionally outside v0.1: API endpoint shapes, database tables, a full `TaskAttempt` state machine, authentication/authorization protocols, artifact storage implementation, and transport-specific envelopes.

## Workflow authoring v0.1

Status: **DRAFT — PLANNING AND MOCK MATERIALIZATION IMPLEMENTED**

The separately versioned [`workflow/v0.1/`](workflow/v0.1/) contract contains standalone JSON Schemas and examples for
`NodePackageDefinition`, `WorkflowDefinition`, and `ExecutionPlan`, including their nested public objects. These schemas
are generated from closed Pydantic models and are covered by schema/runtime parity tests. Blueprint compilation,
edge-slot validation, plan approval, and snapshot-to-mock-runtime materialization are implemented. Database-backed
persistence and non-mock providers remain future work.

## Tool-authored documents v0.1

Status: **DRAFT — H5A/H5B/H5C IMPLEMENTED; OPT-IN**

The new [`documents/v0.1/`](documents/v0.1/) boundary defines Skilltree semantic JSON, exact references,
six authoring commands, server read/validation/approval projections and plugin metadata. ADLC owns durable
revisions and human approval; Harness exposes scoped typed tools. This does not change the frozen execution
contract or H4 artifact retention. H5B adds a [separate renderer descriptor](renderers/skilltree/0.1/manifest.json)
and [authoring result schema](documents/authoring/v0.1/skilltree-authoring-result.schema.json).
H5C adds [separate execution policy/binding/proof/result resources](documents/execution/v0.1/README.md)
and guarded repository tools tied to an exact owner-approved reference. Only registered machine predicates
and bounded file/action policy are enforced; approval/authoring success never proves arbitrary roadmap correctness.
## Independent verification v0.1 (H6A)

H6A adds the independent [verification v0.1 boundary](verification/v0.1/README.md):
frozen JSON-fixture plans, authenticated reproduction receipts and retained comparisons.
This opt-in foundation does not change the Harness v0.1 verification enum, H5 proofs or
original coding-run status. See [H6A rollout and limitations](../docs/milestones/harness-h6.md).

## Frozen HTTP replay v0.1 (H6B local pilot)

The separate [verification-replay boundary](verification-replay/v0.1/README.md) freezes a required
suite, allocated fixture target and typed assertions; accepts only bound, authenticated JSON/JUnit
evidence; and retains cancellation/recovery state in ADLC. This is a protected local HTTP-JSON
fixture, **not** live TestForge, browser regression or application verification. H6A schemas and
old TaskResult/callback behavior are unchanged. See [H6B rollout](../docs/milestones/harness-h6.md).

## Advisory project memory v0.1 (H6C)

The separate [project-memory boundary](project-memory/v0.1/README.md) adds authenticated
owner/project routing, provenance-preserving raw reads and retained advisory context.
A protected curated local gateway uses lexical search without models. Synthesis,
ingestion and deletion remain off; neither context nor a connectivity check is Verify
evidence. See [H6C activation and live Cognee prerequisites](../docs/milestones/harness-h6.md).

## Test proposals and supplementary PNG v0.1 (H6D)

The additive [test-extensions boundary](test-extensions/v0.1/README.md) defines six-tool
proposal authoring, exact owner review, immutable successor revisions and bounded
performance planning. Exploration/load execution stays disabled. Supplementary,
owner-attached PNG references cannot alter a verification verdict. Both UIs share
protected coverage/history/proposal/image views. See [H6D setup and boundaries](../docs/milestones/harness-h6.md).

>>>>>>> agentHarness
## Task and command execution v0.2 (PROPOSED)

Status: **PROPOSED — schemas shipped, runtime adoption pending**

The additively versioned [`v0.2/`](v0.2/) and [`workflow/v0.2/`](workflow/v0.2/) directories extend the frozen v0.1
contract with dynamic control flow (MAP/WHILE/SUBWORKFLOW plan specs and their wire fields), saga compensation
(`COMPENSATING`/`COMPENSATED` states, `purpose: COMPENSATION` dispatches), and the `MapExpansionRecord` /
`CompensationRecord` event payload shapes. v0.2 is coexistent: v0.1 payloads and runs keep working unchanged, and
v0.1-only consumers reject v0.2 payloads by their `schema_version` const. See
[`v0.2/README.md`](v0.2/README.md) and [`workflow/v0.2/README.md`](workflow/v0.2/README.md), and
[ADR 0016](../docs/adr/0016-adlc-contract-v0.2-control-flow-compensation-durable-events.md) for the binding decision.
The additive [task-loop operator read schemas](task-loop-operator/v0.1/README.md) cover Slice C inspection and run controls. They are separate from the frozen task-loop execution inputs and evidence schemas.

The separate [task-loop runtime v0.1 boundary](task-loop-runtime/v0.1/README.md) defines exact runtime bindings, per-iteration commands/outcomes, candidate references and portable checkpoint headers. The additive [v0.2 unpriced profile](task-loop-runtime/v0.2/README.md) supports native Harness proposals with authoritative tokens and explicitly unknown monetary cost. OpenCode and Harness adapters share the kernel; the native adapter has offline conformance with live SDK/provider sign-off pending. Existing execution/operator schemas and accepted plans are unchanged.
