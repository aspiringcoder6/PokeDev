# ADLC workflow authoring contract v0.1

This contract covers reusable node packages, saved workflow definitions, and compiled execution plans. It is versioned
separately from the task/command execution contract in `../../v0.1/`.

The schemas are generated from the closed Pydantic models in `adlc-flow/langflow/adlc/blueprints/models.py`:

```powershell
cd adlc-flow
.\.venv\Scripts\python.exe -m scripts.generate_adlc_authoring_schemas
```

Published package definitions live in `adlc_components/packages/<package-id>/<version>/package.json`. Their digest is
calculated by the registry over canonical JSON, never trusted from an uploaded payload.

`examples/langflow-blueprint-flow-data.json` shows the exact v0.1 metadata embedded in a saved Langflow `Flow.data`
graph. The parser converts this canvas representation into `WorkflowDefinition`; presentation nodes, position, and
viewport do not affect the semantic plan digest.
