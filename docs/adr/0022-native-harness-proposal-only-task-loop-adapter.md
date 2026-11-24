# ADR 0022: Native Harness proposal-only Task Loop adapter

Status: Accepted (implementation and offline conformance; live sign-off pending)
Date: 2026-10-14
Extends: ADR 0021; preserves its kernel/runtime authority boundary.

## Context

ADR 0021 standardized iteration/candidate/checkpoint transport, but production loop
registration still selected OpenCode. Reusing the one-shot Harness driver's Verify,
Submit/callback or conversation lifecycle would bypass the loop kernel's scheduling,
independent proof and final human gate. The installed SDK reports tokens but no authoritative
monetary cost. Its native scope API permits tool denial before agent publication.

## Decision

Publish a separate `vai-adlc-task-loop@0.1.0` native plugin/API and opt-in exact
`coding-agent@0.3.0` variants. The public runtime selector chooses HARNESS or OPENCODE;
old accepted plans/packages/locks are not rerouted. Harness uses only my-codex /
cx/gpt-5.6-luna, fresh per-iteration agents, publication-time zero-tool scopes and a single
full-text file proposal. ADLC retains scoped materialization, protected reproduction,
contract validation, lineage/checkpoints/budgets and human approval.

Publish additive protocol v0.2 for explicitly unknown price (`cost:null`); reject money
budgets before any native call. Preserve frozen v0.1 and existing public loop evidence.
Use separate bearer authentication, exact plugin integrity and digest-bound native journals.
Duplicate or interrupted delivery never resumes/recreates a model session. A crashed writer
requires conservative operator recovery, not automatic stale-lease takeover. Ambiguous
HTTP dispatch is not automatically retried. Only bounded filesystem replacement may retry.

## Consequences

Both loop modes can genuinely select Harness when enabled, while using the same kernel.
UI shows the selected/recorded runtime and actual accounting limitations. Deletions,
file-mode changes, monetary budgets, native approvals and remote Verify are not supported
by this profile. The shared host and host-side Python verifier remain trusted-development
boundaries, not hostile-code isolation. Other plugin profiles are not claimed to have one
unified execution/recovery lifecycle.

Offline conformance must include real cross-language transport, capture/checks, contract
denial, manual gates, replay/deduplication, captured/verified recovery, usage and release
checks. Real SDK/provider and human UI sign-off are separately required for a live claim.
Setup, recovery and acceptance are specified in `docs/task-loop-harness-adapter.md`.

## Alternatives rejected

- Call the old one-shot driver and treat its accepted result as loop proof.
- Let native tools mutate a shared repository or approve their own candidate.
- Claim cost zero when SDK price is missing, or silently ignore a monetary cap.
- Change existing OpenCode package definitions or use a hidden runtime/model fallback.
