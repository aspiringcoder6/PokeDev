# ADR 0021: Runtime-neutral Task Loop iteration and checkpoints

Status: Accepted (OpenCode deployment; Harness adapter pending)
Date: 2026-10-13

## Context

The public Coding Agent composes requirements, contracts and loops, but requirement/
contract-only work uses Harness while loops directly use OpenCode. Unified configuration
is not a unified Harness execution runtime. Provider-specific calls in two loop executors
prevent safe runtime replacement and obscure recovery semantics.

## Decision

ADLC owns the loop kernel, iteration scheduling, cumulative candidates, protected checks,
checkpoints and human gates. Adapters use the additive `task-loop-runtime:iteration/0.1.0`
request/session/outcome/checkpoint protocol. Move both loops' OpenCode transport behind
that port. Exact bindings remain fixed across a loop; replacement needs a new approved
task/run. Runtime replies propose work, never verification, artifacts or approval.

Seal adapter/model/capabilities, run/task/attempt/request, fixed spec/policy, parent/captured
candidate, usage and kernel proof in each checkpoint. Retain conservative interruption
and candidate/proof recovery. Legacy OpenCode checkpoints remain usable without rewriting
old attempts or claiming retroactive conformance. Scope session uniqueness by runtime.

Provide a passive, owner-scoped content-free projection separately from frozen operator
v0.1. UI/docs distinguish protocol unification from Harness deployment. Preserve published
schemas, package versions, accepted plans and locks.

## Consequences and alternatives

Independent adapter conformance proves substitution and real verification/recovery, not
live Harness execution. Production retains OpenCode until Harness passes capability,
materialization, model, cancellation, recovery and live sign-off checks. There is no arbitrary
workflow-authored adapter, auto-fallback or second scheduler.

Renaming OpenCode "Harness" would not change execution. Delegating the whole loop to
one-shot Harness success/Verify/Submit would bypass per-iteration evidence/gates. Rewriting
plans or moving an active checkpoint to another runtime breaks accepted identity.

## Constraints

Preserve public services and legacy client constructors. Runtime schemas are bounded and
closed; file text stays untrusted. Contracts require acknowledged tool restriction before
prompting and cumulative validation before writes. Local runners are not a hostile-code
boundary. See [adapter acceptance criteria](../task-loop/bien-gioi-runtime.md).
