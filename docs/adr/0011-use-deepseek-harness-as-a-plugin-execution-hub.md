# ADR 0011: Use DeepSeek Harness as a plugin execution hub

- Status: Accepted
- Date: 2026-09-23

## Context

ADLC already owns blueprint authoring, immutable node-package resolution, execution plans, workflow/task state, approval policy, and scheduler-facing `TaskExecutor` routing. The newly added `agent-harness-server` can host long-running agent sessions, tools, human interaction, verification, and delivery integrations. Wiring DeepSeek Harness directly into the orchestrator or treating every ADLC node package as a Harness plugin would duplicate policy and couple both systems to one runtime.

The required flow is asynchronous:

```text
resolved workflow configuration
  -> ADLC orchestrator / TaskAttempt
  -> Harness session
  -> optional human interaction
  -> verification plugins
  -> structured terminal result
  -> explicit or automatic submit
  -> signed webhook / durable outbox
  -> ADLC TaskResult acceptance
```

External callbacks may race the original create response, be delivered more than once, or arrive after a process restart. Secrets and callback addresses must not become workflow-authored data.

## Decision

DeepSeek Harness is an execution-plane hub behind the existing `TaskExecutor` port. ADLC remains the control plane and source of truth for workflow, plan, `WorkflowRun`, `TaskRun`, approval policy, retry budget, and final result acceptance.

### Composition model

- An ADLC **node package** is a trusted, immutable recipe resolved while compiling the workflow. It selects an executor, logical capabilities, policies, and a Harness profile.
- A Harness **plugin** is a runtime extension loaded inside the Harness process. It may implement execution drivers, tools, memory, interaction channels, verifiers, artifact publishers, or delivery sinks.
- The relationship is many-to-many and reference based. A node package carries an exact `plugin_lock`; it is not itself installed or executed as a Harness plugin.

Everything replaceable is a plugin, but security and consistency invariants remain in a small trusted kernel. The kernel owns authentication, session identity, idempotency, state transitions, event ordering, plugin-lock enforcement, persistence, outbox delivery, and cancellation. Verification is the first independently replaceable plugin.

### Service boundary

ADLC sends `HarnessSessionRequest` to a versioned service API. The request contains correlation IDs, an idempotency key, objective/input/context, constraints, a profile reference, operation, plugin lock, result-schema reference, submission mode, and a deployment-owned `callback_ref`. It contains neither raw secrets nor an arbitrary callback URL.

Harness returns a session projection. It records ordered events and builds a terminal `HarnessSessionResult`. `AUTO` submission enqueues that result immediately after verification; `MANUAL` submission leaves the session in `READY_FOR_SUBMISSION` until an explicit user action.

Delivery uses a durable outbox. The exact JSON bytes are signed with a timestamped HMAC and sent with a delivery ID. ADLC validates the replay window and signature, deduplicates delivery IDs, validates all correlation fields, and accepts exactly one immutable terminal result for the registered `TaskAttempt`.

### Human-in-the-loop semantics

Generic interaction and control-plane approval are distinct:

- Harness interactions collect information needed to continue a session and will use typed form/interaction records.
- ADLC approvals authorize lifecycle or sensitive actions and remain governed by `ApprovalRequest` and ADLC roles/policies.
- A plugin may request an ADLC approval, but it cannot approve itself or mutate coordinator state directly.

Waiting is not represented by a partial `TaskResult`.

### Activation and compatibility

The integration is opt-in. `coding-agent-deepseek-harness` versions are visible and their capability references are authorized only when `ADLC_HARNESS_ENABLED` is true. Existing mock, legacy-flow, and OpenCode paths remain unchanged.

The first vertical slice uses a deterministic fake execution driver in the Harness runtime while exercising the real API, state, verifier-plugin, persistence, outbox, HMAC, callback, and executor boundaries. Its published node package is fixed to `AUTO`; the control API already supports explicit submission, but workflow-selectable `MANUAL` mode is reserved until the interaction/submit UI is delivered. Replacing the fake driver with the real DSH SDK/session driver must not change the ADLC-Harness contracts.

### H2 implementation update (2026-09-24)

H2 completes the reserved extension without changing contract version `0.1`:

- `vai-adlc-driver-deepseek` now implements the execution-driver service with DeepSeek Harness `agents.create`, `agents.resume`, `followup`, and persisted DSH session identity.
- The runtime persists typed `APPROVAL`/`FORM` interactions, validates idempotent responses, and resumes the exact session. `MANUAL` is now a workflow-selectable submission mode.
- ADLC stores attempts and delivery deduplication in file-backed SQLite, polls session projections as a callback fallback, and exposes owner-scoped interaction, submit, and reconciliation commands.
- Run Detail renders agent interactions separately from lifecycle approvals. The existing `TaskRun.WAITING_APPROVAL` value is a UI/coordinator projection while either kind of human input is the sole blocker; it does not convert a Harness interaction into an `ApprovalRequest`.

The driver uses a strict JSON result/interaction envelope in assistant output. This protocol is intentionally behind the driver plugin so a future native structured-output adapter can replace it without changing the runtime or ADLC contracts.

### H3 implementation update (2026-09-27)

H3 hardens the deployment boundary without changing contract version `0.1`:

- The trusted runtime now hashes the installed files for every required plugin, verifies package identity/version and SHA-256 content against the deployment lock, and fails readiness, new sessions, and interaction continuation closed on any mismatch.
- An authenticated plugin-inventory projection exposes only plugin identities, versions, digests, and integrity status. ADLC readiness validates this typed projection instead of trusting a declared lock.
- A lock synchronization/check tool updates and verifies the Harness patch, immutable node-package recipe, and contract examples from one deterministic cross-platform digest implementation.
- H3 publishes `coding-agent-deepseek-harness@0.2.0` and `vai-adlc-runtime@0.2.0`; the H2 `0.1.0` recipe is preserved byte-for-byte instead of silently changing a published version.
- Fault-injection covers transient callback retry, retry backoff, dead-letter exhaustion, outbox restart recovery, and interruption of an active model turn.
- An opt-in live-E2E runner exercises the real DSH agent driver, typed interactions, verifier, manual submit, plugin integrity, and signed callback delivery against a configured model/provider.

### ADLC result archive update (2026-10-02)

- The DSH driver may dispose its agent handle after verification. This cleans up the live agent; it does not define result retention. The Harness runtime retains the prepared result, and ADLC retains the complete accepted `HarnessSessionResult` in its attempt ledger.
- `GET /api/v1/adlc/runs/{run_id}/harness-results` reads only ADLC's owner-scoped ledger. The live-session endpoint skips attempts whose result is already accepted, so deleting or disconnecting the remote session cannot hide an archived result.
- Run Detail keeps an **Agent results** section after completion, showing output, verifier checks, error details, artifact descriptors, model route, resolved human interactions, and a full JSON export. Each retry attempt has its own retained result.
- A prepared live result is a clearly labelled preview. Reading it never accepts the result, bypasses `MANUAL` submission, or changes workflow approval policy.
- Live control failures do not block loading the run or accepted results. Unavailable live actions are cleared instead of offering stale approvals.
- At this stage, result bytes survived an attempt-repository restart when `ADLC_HARNESS_ATTEMPT_DB_PATH` was configured, but workflow/run projections were still in-memory. The durable coordinator update below closes that gap. Artifact descriptors are retained, not arbitrary external workspace file bytes or the full model transcript.

### Durable run history and coordinator recovery (2026-10-04)

- A replaceable `RunRepository` port stores the owner, frozen runtime task definitions, workflow, task requests/results, lifecycle approvals/decisions, and ordered events in one atomic versioned snapshot. SQLite is the local implementation; stale snapshot writes fail closed.
- The production coordinator and Harness attempt ledger default to file-backed databases under `adlc-flow/data`, independent of the launch directory. `ADLC_RUN_DB_PATH` and `ADLC_HARNESS_ATTEMPT_DB_PATH` can select other file paths. Explicit blank values retain the hermetic in-memory mode for tests.
- Every task request, attempt ID, and idempotency key is saved before external dispatch. Graceful backend shutdown stops observers, not remote Harness sessions. Startup uses the same request/attempt/session to observe an interrupted Harness task; it never calls `create_session` to recover it.
- An already accepted result is applied locally without a Harness client. Pending lifecycle approvals retain their exact IDs and result snapshots; live FORM/APPROVAL and manual-submit controls reconnect through the stored external session ID. Reading a preview still does not accept or submit it.
- If recovery cannot establish the existing session, the task receives a retryable, structured recovery diagnostic and the run pauses. No replacement model execution is automatically started. A late accepted result is preferred over a new attempt on the next restart or explicit Retry.
- Source patches already captured by ADLC retain their checksummed, run/task/attempt-scoped bytes across restart within the existing 2 MiB per-patch, 32 MiB total and 24-hour retention limits. Restart does not extend expiry or snapshot arbitrary workspace files.
- Protected `GET /api/v1/adlc/runs` returns only the current owner's summaries, with status/workflow filters and bounded pagination. **Run History** in the app header opens `/runs`; a row opens the original Run Detail and archived Agent results.
- This slice supports one coordinator process per shared database pair. It does not add distributed leases, automatic model-turn continuation, persistence of unmaterialized plans, or reconstruction of previously lost in-memory runs. Existing frozen plan-task traceability survives with the saved run even if the planning cache is gone.

Restart checks and test commands were recorded in the recovery guide of the corresponding delivery.

## Consequences

H4A adds the publisher-owned Git artifact path, bounded authenticated byte reads,
retention-before-acceptance, and owner-scoped preview/download without moving workflow
approval policy into a plugin. See milestone H4 notes for exact
package versions, limits, deployment changes and the separate H4B verification boundary.

Orchestrator integration note (2026-10-08): the orchestrator branch wires the same recovery
semantics through its SQL run-snapshot persistence (`SqlAdlcRunPersistence` wired at
composition plus one-shot lazy startup hydration and shutdown hooks) instead of the
standalone SQLite `RunRepository`, and keeps Durable event rows tracked under
[ADR 0016](./0016-adlc-contract-v0.2-control-flow-compensation-durable-events.md).

### Positive

- ADLC can adopt DeepSeek Harness without moving orchestration policy into the execution plane.
- Runtime capabilities, especially verification, can evolve independently as plugins.
- Signed, idempotent asynchronous delivery handles callback races and retries explicitly.
- Exact plugin locks make a run explainable and reproducible.
- Existing scheduler and node-package contracts remain the stable integration surface.

### Costs and limitations

- There are two related state machines (`TaskAttempt` and Harness session) that require correlation and reconciliation.
- SQLite is the current durable run and attempt store. This slice requires a single coordinator; horizontally scaled deployments need a shared transactional store, worker ownership and leases.
- A Harness-server restart during an actively running model turn produces a structured interrupted result rather than an unsafe duplicate continuation. An ADLC-only restart instead reattaches the unchanged remote session. Persisted waiting interactions can still resume through the DSH session ID.
- A policy-governed bridge from a plugin request to a true ADLC `ApprovalRequest` remains a separate future feature.
- The live-E2E runner still requires an operator-configured model/provider, callback credential, and reachable Docker deployment; it is intentionally not part of the hermetic unit suite.

## Rejected alternatives

### Make Harness the workflow orchestrator

Rejected because it would duplicate ADLC plans, policy, approvals, retry, and lifecycle state and would weaken the current control-plane boundary.

### Treat node packages and Harness plugins as the same artifact

Rejected because authoring-time recipes and runtime extensions have different trust, lifecycle, deployment, and compatibility concerns.

### Poll only, without callbacks

Rejected as the primary completion path because it increases latency and load and does not remove the need for durable attempt state. Session reads remain useful for reconciliation.

### Let each request provide its callback URL or secrets

Rejected because workflow-authored transport destinations create SSRF and secret-leakage risks. Deployments own callback references and resolve credentials locally.

## Implementation constraints

1. Public Harness payloads are closed, versioned models with generated Draft 2020-12 schemas.
2. ADLC must register the attempt before creating the remote session so an immediate callback is valid.
3. Reuse of an idempotency key with different semantic content is a conflict.
4. A verifier failure must produce a failed result even if webhook delivery succeeds.
5. Callback authentication is independent of end-user API authentication.
6. Logs and readiness responses must never expose bearer tokens, HMAC secrets, provider responses, or raw credentials.
7. Further persistence or approval-bridge work must preserve the separation between Harness interactions and ADLC approval policy and must not change the v0.1 boundary silently.
