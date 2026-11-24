# Task loop v0.1 — Delivery A

Status: **DETERMINISTIC MOCK IMPLEMENTED**. This is a separate boundary; frozen execution/authoring contracts remain
unchanged. An ADLC task represents one fixed objective, with one fresh agent session per coordinator attempt.

| Schema | Meaning |
| --- | --- |
| `task-loop-spec.schema.json` | Full specification, exact mock file criteria, initial candidate, and bounded iteration/context policy. |
| `task-loop-candidate.schema.json` | Versioned file snapshot, checksum, iteration, and explicit parent candidate identity. |
| `task-loop-verification.schema.json` | Nonempty per-criterion boolean evidence tied to the candidate ID/checksum; `mode=MOCK`. |
| `mock-configuration.schema.json` | Scripted edits, with null for deletions and notes retained only as trace data. |

`verifier:task-loop-mock-file/0.1.0` compares file text exactly. It never claims behavioral test or arbitrary
natural-language compliance. `TaskLoopSpec` rejects empty/duplicate criteria, unknown fields, and nonpositive or
boolean iteration budgets. Runtime validation additionally rejects unsafe paths, over 64 files/64 KiB per snapshot,
and inconsistent snapshot digests. Frozen Pydantic models and defensive copies protect stored candidates.

Canonical digests use sorted-key, compact UTF-8 JSON with all validated defaults included. A spec digest covers the
entire spec; a candidate content digest covers its file map. The `Artifact` descriptor checksum covers the exact
UTF-8 candidate JSON bytes instead. Changed candidate versions get different identities and retain parent links.

Schemas are generated from `langflow.adlc.task_loop_models`:

```powershell
# From adlc-flow
.\.venv\Scripts\python.exe -m scripts.generate_adlc_task_loop_schemas --check
```

The [spec fixture](examples/task-loop-spec.json) describes the reproducible fail/fail/pass example and its process-local storage limits.
