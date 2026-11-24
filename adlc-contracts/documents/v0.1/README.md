# Tool-authored contract documents v0.1 — H5A

Status: **DRAFT — SKILLTREE FOUNDATION IMPLEMENTED; OPT-IN**. This is a new namespace;
frozen task/command contracts and existing Harness result/artifact contracts are unchanged.

The ADLC writer, not assistant prose or an uploaded JSON file, produces canonical Skilltree content.
These schemas are generated from `langflow.adlc.contract_models`. The package manifest and six argument
schema copies in `vai-adlc-skilltree` must match. Schema `$id` values are logical publication identifiers,
not a promise that an external web server hosts them.

## Public objects

| File | Meaning |
| --- | --- |
| `skilltree-document.schema.json` | Portable full-content JSON: no ownership credentials, pixels, progress or mutable approval field. |
| `contract-reference.schema.json` | Exact schema/document/revision/SHA256 reference. |
| `contract-read.schema.json` | Owner-authorized content plus server binding, validation and approval receipts. |
| `contract-tool-command.schema.json` | Tool dispatch envelope; `arguments` are then checked by the selected closed argument model. |
| `contract-tool-result.schema.json` | Writer read projection, returned node ID and idempotent replay flag. |
| `skilltree_*.schema.json` | Exactly six small argument contracts, with no caller-supplied owner/session/file/state. |
| `contract-bridge-command.schema.json` | Purpose-authenticated Harness transport; session comes from execution context. |
| `contract-approval-command.schema.json` | Human-only exact-reference approval request, not an agent tool. |
| `contract-fork-command.schema.json` | Human-only new draft superseding an approved reference. |
| `contract-plugin.schema.json` | Skilltree plugin schema/tool/renderer inventory and authority declaration. |

`examples/skilltree-document.json` is a semantic example, not an import endpoint. Init/upsert examples are valid
tool payloads; `invalid-*` examples are deliberately rejected. Example UUIDs are placeholders; real IDs are writer-assigned.
There is no raw-document create/import endpoint.

## Beyond JSON Schema

The typed writer checks identity/ownership, revision/digest and idempotency, graph integrity, quotas and atomic approval.
JSON Schema alone does not authorize a request, enforce DAG semantics or certify execution.
Approval freezes one reference after declaration validation; it does not complete a workflow or grant execution permission.
Validation always reports `criteria_executed=false`. H5B now renders these unchanged schemas through a
[separate descriptor](../../renderers/skilltree/0.1/manifest.json) and hands off an exact reference through the
[new authoring result resource](../authoring/v0.1/skilltree-authoring-result.schema.json).
H5C uses [separate execution resources](../execution/v0.1/README.md) to bind approved references to
guarded repository tools and registered machine predicates; this does not alter H5A declaration/approval semantics.

Canonical bytes are the validated model's full JSON with explicit defaults/nulls, sorted keys, compact separators,
UTF-8 non-ASCII text and no NaN. The `/file` endpoint exports those bytes. Summaries and formatted copies do not share that byte hash.
Receipts and server binding are outside the content hash and available through the read projection.

## Generate/check

From `adlc-flow`, using the existing virtual environment:

```powershell
.\.venv\Scripts\python.exe -m scripts.generate_adlc_contract_document_schemas --check
```

Without `--check`, the generator mechanically rewrites root schemas and identical package copies.
Model/schema behavior changes require deliberate versioning before publication; never resync immutable historical plugin locks.
See [ADR 0012](../../../docs/adr/0012-tool-authored-approved-contract-documents.md).
