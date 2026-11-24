# ADR 0014 — Exact approved contract execution and bounded machine evidence

Status: Accepted. Date: 2026-10-08. Extends ADRs 0012/0013; does not change their writer or approval authority.

## Context

H5A/H5B make a roadmap authoritative and readable, but approval alone does not constrain coding tools or prove execution.
Putting an approved document in a prompt would not prevent another file, action or model-authored success claim.
Published H4/H5A/H5B bytes and recipes must remain reproducible, and free-text requirements cannot be honestly
certified by a structural validator or a syntactically valid JSON response.

## Decision

1. Publish a separate opt-in MANUAL recipe `coding-agent-contract-harness@0.1.0` and
   `vai-adlc-contract-execution@0.1.0` with its own fixed API/state/workspace namespace.
   Reuse unchanged H4 driver/runtime/Git collector libraries with a new exact four-plugin lock.
   Pin the tested route to `my-codex / cx/gpt-5.6-luna`.
2. The human selects the four-field `approved_contract_ref`. ADLC resolves its exact immutable revision,
   owner and approval receipt at compilation, approval, new materialization and current-attempt binding.
   Freeze it in the resolved configuration/digest; no latest, caller-selected owner or model-selected reference.
   A null recipe default is an unconfigured registry sentinel, never an executable default.
3. Compile only the versioned, explicitly supported policy. Allow exact repository-relative paths,
   directory prefixes or `*`, subject to always-on sensitive/type/boundary guards. Expose only context,
   list, read and optimistic text-write tools; read-only omits write. Native SDK dispatch checks the actual
   agent and original tool identities. No shell, code runner, network, subagent, delete, commit, push or deploy.
4. Unsupported paths/actions/verifiers and contradictory declarations reject before clone/model execution.
   Initially register only nonempty-patch, no-changes and changed-JSON-syntax predicates with fixed meanings.
   Criterion descriptions are not executable tests. HUMAN criteria are unsupported in this machine recipe,
   not silently reinterpreted as a later Submit approval.
5. Freeze/drain tool calls before the pinned collector captures real bytes. Verify the actual artifact checksum,
   base commit and changed paths, including coverage of remaining tool writes. Mint criterion evidence in the
   trusted verifier, not by parsing assistant JSON. Persist immutable binding/proof in ADLC under a purpose-separated
   signed execution bridge. Submit rereads that proof; the coordinator independently checks successful task outcomes.
6. Store machine evidence independently of patch expiry and project it read-only through one shared ADLC panel
   in Run Detail and the existing Harness viewer route. Inconsistent data uses escaped JSON without success badges.
   Keep `natural_language_enforced=false` visible. Contract approval, interaction approval, plan acceptance and
   Submit remain distinct decisions; the restricted four-tool recipe cannot initiate native ask-user tools.

## Consequences and limits

- Approval freezes meaning and exact identity; enforced paths/actions limit the agent's available operations.
  Passing machine predicates proves neither semantic implementation correctness nor the entire free-text roadmap.
  DAG execution chronology, arbitrary test suites, security completeness and automatic deployment are not certified.
- Existing HUMAN/unknown-verifier roadmaps must be deliberately forked/re-authored with supported declarations
  and independently approved before using this recipe. Never mutate or relax the original approved contract.
- The source is a committed read-only mount; edits occur in an isolated local clone. Human review/Submit accepts
  the captured result, not a commit, push, merge or deployment.
- Binding/report retries are idempotent only for identical authority/evidence. Changed bindings/evidence conflict.
  A crash after proof persistence but before Harness result persistence fails closed rather than accepting a new artifact
  or implicitly rerunning the model. Comprehensive recovery/live campaigns remain H5D.
  Waiting execution may continue in-process; a fresh process without its write ledger must reject resume before bind/clone/model.
- Backup run, attempt, contract, execution and Harness state coherently. A host administrator, privileged plugin,
  provider service or direct process/DB/checkout access is outside this capability boundary.
- Flags and plugin rows remain disabled by default; repository implementation does not authorize live activation.
  New bytes after publication require a new version, never automatic historical lock synchronization.

## Alternatives rejected

- Prompt-only scope, arbitrary shell/test commands or name-only tool masks: bypassable execution authority.
- A generic agent-authored `passed:true` or unsigned output JSON: not evidence tied to captured bytes.
- Silently skipping HUMAN/unknown criteria or claiming all natural language is enforced: false assurance.
- Binding to the newest revision or interpreting a human fork as revocation: breaks exact historical identity.
- Expanding H4/H5B tool rights or rewriting their released locks: invalidates existing guarantees and history.

## Verification

Offline tests cover compile/approval/materialization gates, exact ownership/correlation, signed purpose separation,
immutable proof/replay/conflicts, real temporary Git clones, path/type/link/ignore/concurrency boundaries,
native tool guards, failed preflight/turns, MANUAL result/Submit and coordinator rejection of forged success.
SDK checks validate the actual declarations and dispatch on the installed SDK in an isolated image without
model calls or user mounts. Deployment and visual/live sign-off are reported separately in the H5C milestone.
