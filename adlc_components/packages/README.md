# Repository node-package registry

This directory is the first immutable registry used by the ADLC blueprint resolver. Each package lives at:

```text
<package-id>/<exact-semantic-version>/package.json
```

The loader validates every definition, rejects drafts and duplicate identities, validates defaults against the embedded
configuration schema, and calculates a canonical SHA-256 digest. Published files must not be edited in place; publish a
new version instead.

`coding-agent@0.2.1` is the latest public **Coding Agent** entry for a selected local project. It supports a simple requirement, an optional approved
contract, an optional task loop, and both options together in one run. The selected configuration resolves to a pinned
implementation and authorized references. The default catalogue hides the three replaced package families while
retaining exact-version access for existing workflows, including `coding-agent@0.2.0`. The project source is pinned in the
reviewed plan.

The default packages deliberately reference mock providers. The separately versioned
`coding-agent-opencode@0.1.0` package is visible only when `ADLC_OPENCODE_ENABLED=true`; it uses the local disposable
Git-worktree Sandbox and OpenCode Agent while Memory and Testing remain mock implementations.

`task-loop@0.1.0` is labelled **Task Loop (Mock)** and is visible only when
`ADLC_TASK_LOOP_MOCK_ENABLED=true`. It reuses coordinator attempts with fresh mock sessions, cumulative candidate
snapshots, exact mock file checks, and a final `AFTER_TASK` approval gate.

`task-loop-opencode@0.1.0` remains registered as **Task Loop (OpenCode)** for existing workflows when
`ADLC_TASK_LOOP_OPENCODE_ENABLED=true`. New stages use the unified Coding Agent's task-loop option.
It uses the separate task-loop v0.2 spec, fresh sessions,
durable candidate overlays, and protected unittest commands before final approval.
