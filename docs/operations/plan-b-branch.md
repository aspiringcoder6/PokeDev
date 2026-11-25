# Plan B workflow branch

This branch contains only the requirement-readiness workflow changes, based on
`origin/main` at f38dacaa7f6bb18a7790c9e933922547b904c2a1. Workflow files are copied from
`Phuc/specification` at 7b9b33623444f689db28adb1c500059980ddf3f0.

## Ownership and scope

Plan B owns the three-stage workflow, eight role prompts, pinned skills, durable
checkpoints, clarification, impact analysis, assessment, Human Gates and internal API.
Plan A source readers, app credential exchange, gateway implementation, source-access
tests and source-access operator guide are intentionally excluded. No replacement
reader, credential fallback or fake gateway has been added. Docker setup changes
from the interrupted local setup are also excluded. Docker files already present in
`main` remain part of that baseline.

## Integration required

The contributor responsible for source access must supply the compatible
`langflow.adlc.source_access` package. The workflow still imports its `SourceRef`,
`Evidence`, `SourceError`, evidence coverage helpers, authorization policy,
`build_source_gateway` and `resolve_project_grant` contracts. Runtime source bindings
(`ADLC_7b9b33623444f689db28adb1c500059980ddf3f0_BINDINGS_FILE`, and optional source budgets) belong to that integration.

This is a workflow review/integration branch. It is not a standalone runnable
application: until source access is integrated, readiness imports and tests cannot
run, and the application router imports readiness. Do not enable or deploy it alone.

The 37 workflow tests previously passed with Plan A present on the source branch.
That result does not establish standalone execution on this branch. Live acceptance
also requires dedicated Harness presets/provider credentials, native framework
bindings and a real human bridge. See [the workflow guide](requirement-readiness.md).
