# ADR 0001: Use immutable versioned node packages

- Status: **Accepted**
- Date: 2026-09-07
- Scope: ADLC blueprint authoring and package registry

## Context

A normal Langflow agent graph requires separate nodes and edges for the model, prompt, rules, hooks, tools, skills, plugins, Memory, and Sandbox. Repeating that structure for every logical ADLC task makes the canvas difficult to author and makes a logical task boundary ambiguous.

Copying all internal configuration into a larger canvas node would remove edges but introduce duplicated configuration, uncontrolled overrides, secret exposure, and configuration drift. Referencing a mutable global profile would make historical plans irreproducible.

## Decision

ADLC will represent reusable execution composition as `NodePackageDefinition` objects in a trusted package registry.

1. A package is addressed by an exact `(package_id, version)` pair.
2. Published versions are immutable. Changes require a new semantic version.
3. The registry calculates and stores a SHA-256 content digest over canonical semantic JSON.
4. A `WorkflowStage` stores an exact package reference plus package-approved overrides; it does not copy the package body.
5. Each package declares its kind, logical interface, configuration schema, defaults, override allow-list, implementation, capabilities, execution profile, policies, and compatibility.
6. Secrets are opaque references and are never package configuration values.
7. The first registry implementation loads reviewed JSON packages from `adlc_components/packages/`.
8. Future database or remote registries must implement the same lookup and visibility boundary and must preserve exact-version semantics.

## Consequences

### Benefits

- Users connect a small number of meaningful stage nodes.
- Agent composition is reused without copying internal graphs.
- Configuration is validated before execution.
- Security policy can reason about declared capabilities.
- Package upgrades are explicit and reviewable.
- Historical workflow plans can identify exactly what implementation they used.

### Costs

- The product needs package lifecycle, registry, resolver, and compatibility logic.
- Package authors must publish new versions instead of editing live definitions.
- The UI needs separate package selection and stage configuration experiences.
- A package may hide internal complexity, so observability must expose logs, artifacts, and traces without exposing secrets.

## Alternatives considered

### Copy the complete package into every stage

Rejected because it produces configuration drift, larger flow JSON, weak upgrade semantics, and increased secret exposure risk.

### Reference one mutable global profile

Rejected because updating the profile silently changes future execution of an unchanged workflow and makes historical plans difficult to reproduce.

### Save every package only as a nested Langflow subflow

Rejected as the public contract. A package implementation may internally use a reviewed Langflow component/subflow, but the ADLC boundary requires explicit interface, policy, capability, version, and digest metadata that an arbitrary subflow does not guarantee.

### Continue manual component wiring

Rejected for normal ADLC blueprint authoring. Native Langflow mode remains available for component and package development.

## Implementation constraints

- Persisted stage references may not use version ranges or `latest`.
- Published package bytes may not be overwritten in place.
- Package resolution must be deterministic and side-effect free.
- Package content cannot directly modify `WorkflowRun` or `TaskRun` state.
- A package implementation must execute through the stable adapter/runtime boundaries.
- Package capabilities are allow-lists, not documentation-only hints.
- Raw credentials are rejected by schema and runtime validation.

## Related decisions

- [ADR 0002](./0002-compile-blueprints-to-execution-plans.md)
- [ADR 0003](./0003-standard-stage-interface.md)
- [ADR 0004](./0004-snapshot-resolution-and-legacy-compatibility.md)
