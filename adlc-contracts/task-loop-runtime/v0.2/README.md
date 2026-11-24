# Task Loop runtime protocol v0.2

Additive unpriced-runtime profile. Published v0.1 and task-loop spec/candidate/proof
contracts remain unchanged. V0.2 exports seven closed schemas for binding, request,
session, outcome, usage, checkpoint and passive runtime view.

The pinned binding includes `cost_reporting:"UNAVAILABLE"`. Usage requires authoritative
integer input/output/total tokens and `cost:null`; no numeric zero or estimated price is
accepted. Monetary budgets are unsupported and rejected before allocation by this
Harness profile. Existing token/context/iteration/time budgets still apply.

Everything else retains the neutral boundary: exact request/session/runtime identity,
fresh context, independently captured cumulative candidate, candidate/proof-bound durable
checkpoint, and ADLC-owned verification/approval. An outcome has no PASS, approval, test
execution or callback field. The Harness adapter supports `FILE_PROPOSAL` only; changes
require exact scoped UTF-8 replacements, without deletions or mode changes.

Check generated schemas with `python -m scripts.generate_adlc_task_loop_harness_schemas
--check` from `adlc-flow`. The native plugin's aggregate schema must exactly match this
export. See [adapter setup and limitations](../../../docs/task-loop/bien-gioi-runtime.md).
