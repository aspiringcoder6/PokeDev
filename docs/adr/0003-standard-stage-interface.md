# ADR 0003: Use a standard stage interface and dependency edges

- Status: **Accepted**
- Date: 2026-09-07
- Scope: ADLC blueprint nodes and edges

## Context

Native Langflow edges connect component-specific input and output handles. This is valuable for building an internal component graph, but it forces an ADLC workflow author to understand how a model, prompt, tool, hook, memory component, and agent fit together.

High-level ADLC stages need stable connectivity even when their internal package implementation changes. The scheduler also needs explicit dependency semantics that do not depend on ReactFlow handle encodings.

## Decision

ADLC stage nodes expose a standard external interface.

1. An executable stage displays one dependency input and one dependency output handle in Blueprint mode.
2. A package declares named logical input and output slots with stable names and schema references.
3. A `WorkflowEdge` declares an acyclic dependency from one stage to another and may bind named source outputs to named target inputs.
4. Persisted bindings use slot names, not ReactFlow `sourceHandle` or `targetHandle` payloads as domain identity.
5. In authoring contract v0.1, every edge uses the `ON_SUCCESS` condition.
6. Source and target slot schemas must match exactly in v0.1.
7. Required target slots must be satisfied by workflow/run input, stage configuration, or a compatible edge binding.
8. Retry and rework are orchestration policies; they do not create cycles in the blueprint DAG.
9. Human approval is an explicit control-stage package rather than a special low-level wire.
10. At materialization, stage input/output values map into the frozen `TaskRequest` and `TaskResult` contracts.

## Consequences

### Benefits

- Most workflows require only one visible edge between stages.
- Internal package changes do not force canvas rewiring.
- DAG and data compatibility can be validated before execution.
- The scheduler receives explicit dependencies independent of frontend representation.
- Package implementations can use different agent/runtime technologies behind the same interface.

### Costs

- The compiler needs a slot-binding and required-input validator.
- Some advanced component-level mappings require package development rather than Blueprint-mode editing.
- Exact schema equality is intentionally restrictive until safe schema compatibility rules are designed.

## Alternatives considered

### Preserve all native Langflow handles on stage nodes

Rejected because it retains the manual wiring problem and couples workflow definitions to package internals.

### Carry only control dependencies with no data bindings

Rejected because downstream stages need a deterministic way to identify required outputs and artifacts. Bindings remain optional when context assembly can supply the input.

### Allow arbitrary expressions on edges

Rejected for v0.1 because executable expressions create security, reproducibility, and validation problems. Named-slot bindings are sufficient for the first vertical slice.

### Model retry and rework as graph cycles

Rejected because the runtime contract and DAG validator assume an acyclic plan. Retry creates a new attempt for the same task; rework creates an auditable plan/runtime decision rather than a static back edge.

## Implementation constraints

- Canvas handles are presentation details and may be regenerated without changing semantic edge identity.
- Slot names must be unique within each direction of one package interface.
- A binding may not broaden permissions or introduce a capability.
- Binary artifact bytes are not embedded in bindings; bindings carry values or references.
- Automatic same-name binding is a UI suggestion only. Persisted bindings are explicit.
- Invalid bindings prevent plan validation and run creation.

## Related decisions

- [ADR 0001](./0001-versioned-node-packages.md)
- [ADR 0002](./0002-compile-blueprints-to-execution-plans.md)
