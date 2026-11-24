# Task-loop operator reads v0.1

Additive Slice C schemas for authenticated read-only monitoring:

- `task-loop-inspection.schema.json`: one owner-scoped task, at most 100 iteration records, check outcomes, candidate identities, resource usage, stopping reason, recurring failures, and retry/recovery availability.
- `run-operator-controls.schema.json`: owner-scoped pause/resume/cancel availability and the coordinator's pause state.

These are projections, not inputs or execution authority. They exclude full prompts, candidate bytes, test output, executable arguments, and host paths. `history_complete=false` explicitly marks a partial or unavailable history; it cannot enable iteration retry. Mock results remain distinct from behavioral tests and have unknown provider usage.

Regenerate or check from `adlc-flow`:

```powershell
.\.venv\Scripts\python.exe -m scripts.generate_adlc_task_loop_operator_schemas
.\.venv\Scripts\python.exe -m scripts.generate_adlc_task_loop_operator_schemas --check
```

Frozen task-loop and Coding Agent execution schemas are unchanged. Product behavior and boundaries follow the Delivery C iteration timelines and operator controls design.
