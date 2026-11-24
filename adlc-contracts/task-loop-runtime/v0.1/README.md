# Task-loop runtime boundary v0.1

Status: **implemented for OpenCode and offline adapter conformance; not a deployed Harness loop**.

`task-loop-runtime:iteration/0.1.0` is an additive, closed protocol for replacing an
iteration runtime without replacing ADLC's loop kernel. It does not change published
task-loop v0.1/v0.2, operator v0.1, Coding Agent, Harness results or plugin locks.

| Record | Purpose | Authority |
| --- | --- | --- |
| Runtime binding | Exact adapter version, family, provider/model/agent and modes | Kernel pins it for the loop |
| Iteration request | Run/task/request/attempt identity, full spec, parent overlay, policy digest, bounded prompt and deadline | Kernel creates it; no keys, host paths or past conversations |
| Runtime session | Fresh-session acknowledgement, command digest and tool-denial acknowledgement | Adapter acknowledges; kernel checks before prompting |
| Iteration outcome | Bound session/command, measured usage and optional replacement files | Untrusted proposal; cannot contain PASS, checks, approval or artifacts |
| Candidate reference | Candidate ID, cumulative-overlay digest and iteration | Kernel captures actual Git bytes using existing v0.2 candidates |
| Runtime checkpoint | Runtime/identity/spec/policy/parent binding, phase, session, outcome digest, candidate and proof digest | Kernel seals it with the attempt |
| Runtime view | Content-free, owner-scoped stored identity | Passive read; never dispatches work |

Two modes are supported: `WORKSPACE_EDIT` (kernel captures an isolated local worktree)
and `FILE_PROPOSAL` (tool-free, bounded full-text file replacements; kernel enforces
contract paths/read-only policy before applying). Deletions and mode changes remain
unsupported for contract proposals. A local adapter's directory is an out-of-band
kernel-owned capability, **not** an agent-authored wire field or a public host path.
Remote adapters need validated proposals or an audited workspace materializer; a
container path cannot be treated as a host worktree.

The retained patch serializer/media type keeps its published `opencode-vcs-diff-v1`
name for review compatibility. That format name is not a claim about which runtime
created the candidate; use the sealed runtime binding instead.

Schemas specify shape. Python validators additionally check digests, lineage, budgets,
usage totals and mode-dependent restrictions. Use the conformance suite too.

## Recovery and replacement

Ledger phases stay `RESERVED → AGENT_RUNNING → CANDIDATE_CAPTURED → VERIFIED → FINISHED`.
A session handle is saved before prompting. Captured candidates recover without a model
call; verified attempts recover without another model **or** test execution. Interrupted
calls are aborted through their bound adapter and need an explicit successor attempt.
No automatic fallback, interrupted-call re-prompting or human approval is added.

Runtime version, model, agent and capabilities cannot change in a continuing loop.
Replacement needs a new accepted task/run with a registered, authorized adapter. Session
uniqueness is scoped to the exact runtime reference; legacy OpenCode uniqueness remains.
Existing completed results retain their original saved values after configuration changes:
this is a read of old evidence, not execution by the replacement runtime.

Pre-protocol checkpoints remain usable only under their original OpenCode binding/policy.
Recovery never relabels old attempts as protocol compliant. At the next explicitly
dispatched iteration, the original binding can be added to the aggregate transactionally;
older attempts/results remain unchanged. Mixed legacy/new history is not retrospective
conformance for old sessions.

## Operator read API

`GET /api/v1/adlc/runs/{run_id}/tasks/{task_run_id}/task-loop-runtime` returns the runtime
view. Ownership and run/task checks precede ledger reads. It works from retained
checkpoints when dispatch is disabled and exposes no prompts, source, test output,
host directories or keys. Legacy/unavailable/not-started identities are explicit; current
configuration is never substituted for missing history. Existing `/task-loop` stays unchanged.

`execution_unified_with_harness` is deliberately `false`: a standard iteration protocol
does not prove that all Harness plugins share one deployed runtime.

See [implementation and acceptance criteria](../../../docs/task-loop/bien-gioi-runtime.md).
