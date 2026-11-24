# ADR 0006: Authorize package discovery, planning, and new run materialization

- Status: Accepted
- Date: 2026-09-11
- Scope: ADLC package catalogue, blueprint planning, and execution-plan materialization

## Context

The repository package registry proves that a package definition and each opaque provider, policy, or capability
reference are trusted by this ADLC deployment. Trust is not the same as permission. An authenticated user may be
allowed to see only part of the package catalogue or may lack permission to use a tool, model, Sandbox policy, or
other execution reference contained by an otherwise visible package.

Authorization can also change after a plan is accepted. The accepted plan must remain an immutable historical
snapshot, but a revoked permission must prevent a new execution from being created. Separately, package deprecation
must discourage new use without rewriting published package bytes or changing their digest.

## Decision

1. Introduce a `PackageAccessPolicy` port shared by package discovery, package resolution, and plan materialization.
2. Address package grants by exact `(package_id, version)` and capability grants by their opaque reference string.
3. Filter `GET /api/v1/adlc/node-packages` for the current subject. An exact hidden-package lookup returns HTTP 404
   with `PACKAGE_NOT_VISIBLE`.
4. During compilation, first verify that every reference is registered and then verify that the current subject may
   use it. Package denial becomes `PACKAGE_NOT_VISIBLE`; reference denial becomes `CAPABILITY_NOT_AUTHORIZED`.
   Both are stage-addressed validation issues on an `INVALID` plan and no run is created.
5. Before creating a new run, recheck the accepted plan's exact package identities and execution references against
   current grants. This check reads only `ResolvedNodeSpec` snapshots; it does not resolve packages again or change
   plan digests. A denial returns HTTP 403 for capability access or concealed HTTP 404 for package visibility.
6. An idempotent request that already created a run returns that owner-scoped run before this new-run check. Reading
   historical plans and runs is not disabled by later package or capability revocation.
7. Store deprecation as catalogue lifecycle metadata outside immutable package JSON. New compilation and
   revalidation reject a deprecated version with `PACKAGE_DEPRECATED`. An already accepted plan may still be
   materialized if its current access grants remain valid.
8. Use a thread-safe in-memory allow-list implementation for this mock slice. Authenticated users receive the two
   mock packages and their mock/control references by default. A durable tenant-, role-, and project-aware policy may
   replace it through the same port.

## Why registration and authorization are separate

`CAPABILITY_NOT_REGISTERED` means package content references something the deployment does not trust or know.
`CAPABILITY_NOT_AUTHORIZED` means the reference is registered, but the current caller is not permitted to use it.
Checking registration first keeps configuration failures deterministic and prevents an allow-list from making an
unknown implementation trusted.

## Consequences

### Positive

- The package picker cannot disclose packages outside the caller's catalogue.
- Manually edited flow JSON cannot bypass package or capability permissions during compilation.
- Permission revocation blocks new external work without corrupting audit history.
- Published package bytes, content digests, accepted plans, and historical runs remain reproducible.
- The scheduler and adapters remain unaware of identity and authorization policy.

### Trade-offs

- The current policy and deprecation overlay disappear on process restart and are not synchronized across workers.
- Catalogue filtering is user-scoped only at the policy seam; the mock implementation has no roles or projects.
- A deprecated package remains visible so an existing workflow can explain why revalidation fails.

## Alternatives considered

### Treat every registered package as authorized

Rejected because trusted package installation would silently grant every user access to all providers and tools.

### Authorize only when a task is dispatched

Rejected because a plan could be accepted and a run partially started before a denied downstream task is found.

### Copy authorization decisions into the plan and never recheck

Rejected because revoked permissions would continue to create new work indefinitely. Authorization is a current
precondition, not reproducible semantic plan content.

### Change `status` inside published package JSON to deprecate it

Rejected because that changes the immutable package content digest for the same exact version.

## Implementation constraints

- Authorization subject IDs and grants must not enter resolved-node or plan digest payloads.
- Materialization must inspect accepted snapshots and must not query the package registry.
- Access failures must occur before a new `WorkflowRun`, `TaskRun`, event, log, or artifact is created.
- Hidden exact-package lookup must use the same not-found posture for authenticated API callers.
- A future database implementation must preserve atomic policy reads appropriate to new-run authorization.

## Related decisions

- [ADR 0001](./0001-versioned-node-packages.md)
- [ADR 0002](./0002-compile-blueprints-to-execution-plans.md)
- [ADR 0004](./0004-snapshot-resolution-and-legacy-compatibility.md)
- [ADR 0005](./0005-versioned-plan-regeneration-and-supersession.md)
