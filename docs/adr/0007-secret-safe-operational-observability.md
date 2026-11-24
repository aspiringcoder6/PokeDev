# ADR 0007: Emit secret-safe operational observations through a replaceable sink

- Status: Accepted
- Date: 2026-09-13
- Scope: ADLC package resolution, plan validation, materialization, and runtime dispatch

## Context

ADLC already stores state-change `RunEvent`s after a workflow run exists, and execution-plan tasks retain immutable
links back to source stages and resolved package digests. That is sufficient for the Run Detail UI but leaves the
pre-run planning path and operational latency/failure path invisible to deployment telemetry.

Logging whole workflow, package, task request, result, exception, or artifact objects would expose prompts,
requirements, configuration, bound values, output content, secret references, or credentials. Coupling each service
directly to a particular log, metrics, trace, or database implementation would also make the planning and scheduler
boundaries harder to replace.

## Decision

1. Define closed contract `AdlcOperationObservation` v0.1 and a synchronous `AdlcObservabilitySink` output port.
2. Emit exactly one completion observation for each package-resolution attempt, compiler validation, plan
   materialization request, and runtime task dispatch attempt.
3. Use low-cardinality outcomes `SUCCEEDED`, `INVALID`, `DENIED`, `FAILED`, and `CANCELLED`. Preserve known failures
   only as stable machine codes; never export exception messages or details.
4. Allow-list correlation IDs, exact package identity/version and digests, duration, executor service, retry/replay
   markers, validation codes, and non-content counts. The contract has no arbitrary metadata or payload field.
5. Do not export authorization-subject IDs, prompts, objectives, requirements, input/binding values, configuration,
   context, results, artifact references/content, logs, raw secrets, or opaque secret references.
6. Compose the HTTP application with `StructuredLogAdlcObservabilitySink`, which uses Langflow's configured
   structured log, redaction, and OpenTelemetry-aware pipeline. Provide an in-memory implementation for deterministic
   tests and future adapters.
7. Treat telemetry as non-authoritative and failure-isolated. A sink failure must not change resolution, validation,
   materialization, dispatch, scheduler, or state-machine behavior.
8. Keep `RunEvent` as the user-facing, per-run state transition history. Operational observations are not appended to
   a run, exposed through the ADLC API, or rendered in the frontend in this slice.
9. Export package identity/version only after successful trusted-registry resolution. Failed resolution keeps workflow
   and stage IDs plus the stable error code, avoiding an observability channel for arbitrary author-provided strings.

## Consequences

### Positive

- Operators can follow a stage from exact package resolution to accepted-plan dispatch using immutable IDs and
  digests.
- Invalid authoring, authorization denial, infrastructure failure, and cancellation remain distinguishable.
- The schema prevents an accidental `metadata={...}` dump from becoming telemetry.
- A future OTLP, metrics, audit, or durable database sink can replace or compose with logging without changing the
  compiler, materializer, or scheduler.
- Observability failures cannot prevent workflow progress.

### Trade-offs

- Completion-only observations do not show an in-flight operation until it finishes.
- Process-local tests can inspect observations, but ADLC does not yet provide its own durable query store.
- Per-stage and per-attempt records add log volume; production sampling and retention are deferred.
- This slice records operation durations but does not define histograms, dashboards, alerts, or SLOs.

## Alternatives considered

### Put planning events into `RunEvent`

Rejected because package resolution and validation happen before a `WorkflowRun` exists, and operational telemetry
does not represent a workflow state transition.

### Log full request and result objects

Rejected because those objects intentionally contain requirements, prompts, bound upstream values, execution
context, artifact references/content, outputs, and potentially secret references.

### Call the logger directly from every service

Rejected because tests and future exporters would need logging-specific interception and domain services would be
coupled to one transport. The sink keeps the emitted contract stable.

### Fail the operation when telemetry export fails

Rejected because logs and metrics are not authoritative workflow state. Exporter availability must not alter
scheduler outcomes or duplicate external work.

## Implementation constraints

- New observation fields require contract review; arbitrary dictionaries are forbidden.
- Durations must use a monotonic clock; completion timestamps must be timezone-aware UTC values.
- Error values must pass the stable uppercase machine-code format and must never fall back to exception text.
- Execution-plan dispatch must include plan task, source stage, resolved spec, package version, package digest, and
  resolved digest when the accepted snapshot provides them.
- Idempotent materialization replay must emit a materialization record but must not emit another dispatch record.
- Persisted or remote sinks must preserve failure isolation and the content-exclusion policy.

## Related decisions

- [ADR 0001](./0001-versioned-node-packages.md)
- [ADR 0002](./0002-compile-blueprints-to-execution-plans.md)
- [ADR 0004](./0004-snapshot-resolution-and-legacy-compatibility.md)
- [ADR 0005](./0005-versioned-plan-regeneration-and-supersession.md)
- [ADR 0006](./0006-package-and-capability-authorization.md)
