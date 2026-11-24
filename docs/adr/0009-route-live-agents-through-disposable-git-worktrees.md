# ADR 0009: Route live agents through service-specific disposable Git worktrees

- Status: Superseded by [ADR 0010](./0010-retain-reviewable-source-patches-temporarily.md)
- Date: 2026-09-16
- Scope: ADLC executor routing and local OpenCode workspace isolation

## Context

Slice 6A established `OpenCodeAgentAdapter`, but the scheduler still owned one mock executor and the only Sandbox
implementation returned a descriptive `mock://` URI. Activating OpenCode against the main checkout would let a task
modify user work directly, while selecting an executor from labels or package metadata without an allow-listed route
could silently fall back to the wrong implementation.

Database persistence and a remote/container Sandbox are intentionally deferred. The next vertical slice still needs
one real, inspectable execution path without changing DAG scheduling, retry, approval, Memory, or Testing behavior.

## Decision

1. Keep the scheduler-facing `TaskExecutor` port unchanged. Place `TaskExecutorRouter` behind it and dispatch by the
   exact `TaskRequest.executor.service` resolved from the immutable package snapshot.
2. Register the existing `agent-provider:mock` package service to `MockExecutor`. An unregistered service fails closed
   with `EXECUTOR_SERVICE_NOT_REGISTERED`; it never falls back to mock execution.
3. Add immutable package `coding-agent-opencode@0.1.0`. It fixes the OpenCode provider/model/prompt/rule/hook/tool,
   mock Memory and Testing boundaries, and `sandbox:local-git-worktree/0.1.0` policy reference.
4. Hide that package and withhold its references unless `ADLC_OPENCODE_ENABLED=true`. Existing mock packages and
   native or legacy Langflow execution remain unchanged.
5. For each live attempt, create a detached Git worktree from the configured repository and base revision. The source
   repository must be the Git top-level and the worktree root must be disjoint from it.
6. Give OpenCode only the disposable worktree directory. On every adapter exit, dispose OpenCode's directory-scoped
   runtime instance to release watchers and subprocesses. Then, on success, failure, cancellation, or adapter error,
   remove that exact registered worktree and prune Git metadata. Never recursively remove an unvalidated or
   caller-provided path.
7. Treat worktree contents as ephemeral. Read and checksum the OpenCode workspace VCS diff before cleanup, and return
   an opaque `opencode://sessions/{sessionId}/captured-vcs-diff` Artifact reference for correlation. Its payload is
   not retained or downloadable after cleanup; durable artifact bytes remain future work.
   Aggregate `patch` parts across every new assistant message for changed-file reporting; the terminal message need
   not repeat earlier tool-call patches. Do not use the legacy session-diff endpoint because the supported OpenCode
   line currently returns no historical diff data there.
8. Expose authenticated, credential-free readiness at `GET /api/v1/adlc/executors/opencode/readiness`. It checks the
   opt-in flag, model syntax, OpenCode health, source repository, Git base revision, and sandbox configuration without
   running a model.
9. Continue using `MockMemoryAdapter` and `MockTestingAdapter` in the OpenCode bundle. This slice changes only Agent and
   Sandbox implementations.
10. Keep activation process-local and configuration-driven. A backend restart is required after changing activation
    environment variables because runtime composition and package policy are cached.

## Consequences

### Positive

- The scheduling and state-machine code does not know about OpenCode or Git worktrees.
- Mock and live package execution can coexist in one accepted plan without label-based routing.
- The main checkout, including its uncommitted files, is outside the task workspace.
- Every allocated workspace has one attempt identity and a bounded cleanup target.
- Operators can distinguish disabled, misconfigured, server-down, and sandbox-unready states without exposing
  credentials.

### Trade-offs

- A local Git worktree is filesystem isolation, not a security boundary against hostile commands. A container or
  remote Sandbox remains required before untrusted multi-tenant execution.
- A worktree starts from a committed revision, so uncommitted main-checkout changes are intentionally absent.
- Run state, Memory, Testing evidence, and artifact bytes are still process-local or provider-owned.
- Closing the worktree prevents later inspection of generated files through its local path. The returned Artifact
  identifies the capture and changed files, but cannot reconstruct or download the patch until artifact storage is
  added.
- The package is tied to the exact model reference in version `0.1.0`; changing provider/model requires a new package
  version.

## Alternatives considered

### Let OpenCode edit the current checkout

Rejected because concurrent tasks and cancellation could overwrite user work, and cleanup could not distinguish task
files from pre-existing files.

### Choose the executor from a node name or stage type

Rejected because labels are author-controlled presentation data. Runtime routing must come from the resolved,
authorized package snapshot.

### Fall back to the mock executor when a service is unavailable

Rejected because a run could report success without performing the requested live operation.

### Wait for the final remote Sandbox and database

Rejected for this development slice. The disposable worktree supplies a narrow local integration seam while keeping
the future Sandbox and persistence ports intact.

## Follow-up

- Persist runs, results, events, artifact payloads, and OpenCode session/diff snapshots.
- Replace the local worktree adapter with a container or remote Sandbox for untrusted execution.
- Replace mock Memory and Testing independently behind their existing ports.
- Add bounded, redacted OpenCode progress events and explicit tool-permission handling.

## Related decisions

- [ADR 0006](./0006-package-and-capability-authorization.md)
- [ADR 0007](./0007-secret-safe-operational-observability.md)
- [ADR 0008](./0008-integrate-opencode-through-agent-adapter.md)
