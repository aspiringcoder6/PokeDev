# H6D closed test-extension sidecars v0.1

Twelve schemas generated from `langflow.adlc.test_extension_models`; all object
inputs forbid additional properties. They do not modify any H4/H5/H6A/B/C schema.

`test-extension-profile:proposals/0.1.0` defines the exact proposal/reference/source,
six-tool command and purpose-separated bridge envelope, owner decision and capability
objects. Exploration/performance are **not executable**, not evidence and use no models.
The target/data envelope and performance budget constrain proposals only.

`evidence-profile:supplementary-png/0.1.0` defines owner-uploaded static PNG references,
exact replay/execution/case binding, input/sanitized checksums and explicitly unverified
capture provenance. They have no verdict authority. PNG byte decoding/normalization,
scope/freshness, contract mappings, lifecycle, quotas and approval are backend invariants
in addition to JSON Schema validation.

Run from `adlc-flow` with its virtual environment and `PYTHONPATH` set to that directory:

```powershell
.\.venv\Scripts\python.exe scripts/generate_adlc_test_extension_schemas.py --check
```

The generator without `--check` prints JSON for review; it does not overwrite files.
See [H6D setup, authority and limitations](../../../docs/milestones/harness-h6.md).
