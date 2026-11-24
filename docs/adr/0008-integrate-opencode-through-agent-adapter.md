# ADR 0008: Integrate OpenCode through the Agent Adapter and headless server API

- Status: Accepted
- Date: 2026-09-15
- Scope: ADLC agent execution provider boundary

## Context

ADLC has a stable scheduler-facing `TaskExecutor` and separate Sandbox, Memory, Agent, and Testing adapter ports. The
default composition is intentionally deterministic and mock-only. The next provider is OpenCode, but there are two
different integration concepts in the repository:

- the existing Langflow `OpenCode Model` component calls an OpenAI-compatible Zen model endpoint; and
- the OpenCode coding-agent runtime exposes sessions, messages, abort, diffs, and events through a headless server.

Only the second option represents the requested agent runtime. Calling it directly from the scheduler would couple
DAG/state logic to a changing provider API. Giving ADLC the provider API key would also duplicate OpenCode's own
credential store and create new paths for secrets to enter task requests, events, logs, plans, or artifacts.

The current `MockSandboxAdapter` does not allocate a filesystem. Its `mock://` URI is descriptive, so enabling a live
coding agent against the repository would falsely imply isolation and could modify user files outside the intended
sandbox boundary.

## Decision

1. Implement OpenCode as `OpenCodeAgentAdapter`; the scheduler and `AdapterTaskExecutor` contracts do not change.
2. Use the documented OpenCode headless HTTP server API for programmatic execution: health, session creation,
   asynchronous prompt submission, bounded message polling, workspace VCS diff, and session abort. Snapshot the workspace's
   message IDs before submission and accept only a new terminal assistant message, so polling cannot return a result
   from an earlier turn or prematurely treat an intermediate `finish=tool-calls` step as task completion.
3. Keep a small internal `OpenCodeClient` protocol and test the adapter against a deterministic fake client. Use a
   raw `httpx` implementation so ADLC is not tied to a pre-release generated SDK package.
4. Treat OpenCode provider credentials as OpenCode-owned configuration. ADLC does not parse credential JSON, call the
   OpenCode `/auth` endpoint, or put raw keys in `TaskRequest`.
5. ADLC may hold only connection credentials for the headless server. Passwords are excluded from object
   representation; credentials embedded in URLs are rejected; non-loopback plain HTTP is rejected.
6. Build the prompt from allow-listed task fields and resolved context. Do not forward arbitrary task metadata,
   plan metadata, exceptions, provider responses, or secret references.
7. Normalize HTTP and assistant-message failures to stable `ServiceError` codes. Do not expose response bodies or
   upstream exception text.
8. Enforce the task deadline and best-effort abort the OpenCode session on timeout or cancellation. Dispose the
   directory-scoped OpenCode instance on every adapter exit so its runtime resources do not outlive the Sandbox
   workspace.
9. Represent accepted changes as an opaque `opencode://sessions/{id}/captured-vcs-diff` Artifact correlation reference
   with a checksum of the retrieved workspace VCS diff. The payload is not retained after cleanup; ADR 0009 records
   the live-worktree behavior, and durable artifact storage is deferred.
10. Require the Sandbox adapter to supply `SandboxSession.metadata.opencode_directory`. Reject mock sessions by
    default; an explicitly constructed development adapter may opt in to a mock workspace.
11. Do not add the OpenCode package to default discovery or scheduler routing in Slice 6A. Activation requires the
    explicit workspace and opt-in policy defined later by [ADR 0009](./0009-route-live-agents-through-disposable-git-worktrees.md).

## Consequences

### Positive

- OpenCode can replace the mock agent without changing DAG scheduling, retry, approval, or run-state mutation.
- Session IDs, message IDs, actual provider/model, token counts, finish reason, and diff artifacts map into v0.1
  results without exposing credentials.
- Timeouts and provider authentication failures become predictable task failures.
- Unit tests do not require network access, a provider account, a key file, or an OpenCode installation.
- The server API leaves room for event streaming and interactive permission handling in later slices.

### Trade-offs

- Slice 6A is a provider boundary, not a live Blueprint execution path.
- Session retention depends on the external OpenCode server; the captured VCS diff is not retained after cleanup.
- Polling does not yet stream intermediate tool/log events into `RunEvent` and adds bounded read traffic while a task
  is running.
- A future generated-client migration will require compatibility tests against this internal protocol.
- The current symbolic model configuration is not yet part of the package/reference registry.

### OpenCode 1.18.31 compatibility finding

Live validation on 2026-09-16 showed that `POST /session/{id}/message` could complete and persist the assistant
message while leaving the HTTP response open until the ADLC client timed out. The same provider, model, server, and
workspace completed through `POST /session/{id}/prompt_async` followed by `GET /session/{id}/message`. The client
therefore uses the async path while preserving the synchronous `OpenCodeClient.prompt()` contract presented to the
adapter.

## Alternatives considered

### Call the OpenCode Zen model endpoint

Rejected because a chat-completions provider is not the OpenCode coding-agent runtime and does not expose sessions,
workspace edits, diffs, abort, or agent tools.

### Launch `opencode run --format json` for every task

Deferred. The CLI is useful for local smoke tests, but the server gives ADLC explicit session identity and abort/diff
operations, avoids repeated process startup, and is the documented programmatic integration surface.

### Parse the user's credential JSON in ADLC

Rejected. OpenCode already owns provider credential loading. Duplicating that parser expands the secret-handling
surface and couples ADLC to provider-specific schemas.

### Enable OpenCode against the current repository using MockSandboxAdapter

Rejected as a default because the mock adapter provides no isolation, cleanup, or workspace ownership guarantee.

## Follow-up status

- The local-development workspace, immutable package, service router, and readiness endpoint are implemented by ADR
  0009 and Slice 6B.
- Stream bounded, redacted OpenCode progress events into the existing observability boundary.

## Related decisions

- [ADR 0001](./0001-versioned-node-packages.md)
- [ADR 0002](./0002-compile-blueprints-to-execution-plans.md)
- [ADR 0006](./0006-package-and-capability-authorization.md)
- [ADR 0007](./0007-secret-safe-operational-observability.md)
- [ADR 0009](./0009-route-live-agents-through-disposable-git-worktrees.md)
