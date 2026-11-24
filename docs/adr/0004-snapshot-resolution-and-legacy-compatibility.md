# ADR 0004: Snapshot resolved packages and preserve legacy behavior

- Status: **Accepted**
- Date: 2026-09-07
- Scope: reproducibility, migration, and Langflow compatibility

## Context

A workflow stage references a package in a registry. Even when package versions are immutable, execution also depends on workflow defaults, stage overrides, selected capabilities, policy registries, and engine compatibility. Looking those values up again while a task is dispatched can produce drift or late failures.

The repository also contains three different graph use cases:

- native Langflow component flows;
- the first ADLC saved-flow mock path, which normalizes every eligible node into a task; and
- the new high-level ADLC blueprint model.

Changing the meaning of existing saved flows would risk breaking Langflow behavior and current regression tests.

## Decision

### Resolution snapshots

1. The compiler resolves package defaults, workflow defaults, allowed stage overrides, implementation references, capabilities, and policies before plan validation completes.
2. It creates an immutable `ResolvedNodeSpec` for every `PlanTask`.
3. The spec stores the exact published package digest and a separate digest of the complete effective semantic configuration.
4. An accepted plan stores or immutably references the resolved specs used by its tasks.
5. Runtime materialization and dispatch use the accepted snapshots, not current mutable registry lookups.
6. A digest mismatch or unavailable accepted snapshot blocks materialization and produces an explicit conflict; the runtime must not silently re-resolve.
7. Presentation-only data and resolved secrets are excluded from snapshots and digests.

### Compatibility modes

1. Native Langflow flows remain native unless explicitly marked as ADLC blueprints.
2. An ADLC blueprint has a flow-level `document_type=WORKFLOW_DEFINITION` marker and package references on its stage nodes.
3. The current behavior remains behind the explicitly named `normalize_legacy_flow_graph` boundary and legacy ADLC
   flow-ID endpoint during migration; `read_adlc_task_graph` is only a compatibility import.
4. The new planning endpoints accept only explicitly marked blueprints.
5. `/api/v2/workflows` and Langflow `Graph.from_payload` behavior are not changed.
6. The known orchestrator component flow is converted into the first reviewed package by hand. Automatic arbitrary-subgraph conversion is deferred.

## Consequences

### Benefits

- Accepted plans and historical runs are reproducible.
- A registry update cannot silently change a queued or retried task.
- Native Langflow users retain existing behavior.
- The project can migrate one workflow at a time.
- Legacy tests remain useful while the new compiler is built.

### Costs

- Resolved snapshots consume additional storage.
- Registry and policy changes require new plan versions before they affect a workflow run.
- The application must clearly identify native, legacy ADLC, and blueprint modes.
- The legacy endpoint remains temporarily supported and must later receive an explicit deprecation plan.

## Alternatives considered

### Resolve the package at every task dispatch

Rejected because retries or delayed tasks could execute with configuration different from the approved plan.

### Store only the package version

Rejected because effective workflow/stage overrides and referenced policy versions would not be captured.

### Replace all existing flow behavior at once

Rejected because it would conflate migration with the new architecture and could break native Langflow graphs.

### Automatically package every connected subgraph

Rejected for the first implementation because arbitrary component graphs do not declare stable logical interfaces, capabilities, policies, or safe override rules.

## Implementation constraints

- Canonicalization must have cross-platform test vectors.
- Snapshot digests must exclude ReactFlow position, dimensions, selection state, and other presentation fields.
- Secret reference identifiers may be stored; resolved secret values may not.
- An accepted plan and its snapshots are append-only.
- Retry reuses the accepted plan snapshot unless a new plan version is explicitly approved.
- Mode routing must be explicit and test-covered; name-based detection is forbidden.
- Removal of the legacy endpoint requires a separate ADR and migration evidence.

## Related decisions

- [ADR 0001](./0001-versioned-node-packages.md)
- [ADR 0002](./0002-compile-blueprints-to-execution-plans.md)
- [ADR 0003](./0003-standard-stage-interface.md)
