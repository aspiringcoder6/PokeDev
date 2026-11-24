# Advisory project memory v0.1 — H6C

Status: implemented and opt-in; local curated pilot only, not live Cognee certification.
Profile: `memory-profile:project-context/0.1.0`.
Gateway contract: `gateway:adlc-memory-readonly/0.1.0`.

Ten closed JSON Schemas mirror the Pydantic runtime. They define the compiler-pinned
binding, bounded query/bridge command, provenance-bearing chunks, scoped gateway
context/status and retained read/view/capabilities. They do not change Harness v0.1,
H5 Skilltree approval/execution proofs or H6A/B reproduction receipts.

The only model-facing tools are `adlc_memory_context`, `adlc_memory_status` and
`adlc_memory_health`. Arguments cannot contain owner, tenant, dataset, backend URL,
credential, source path or permission boolean. Identity is derived by ADLC. Scope
schemas and the reviewed gateway policy must be present before reads, including
first call and reconnect. The adapter never services server-side sampling requests.

Text is untrusted advisory context. A source's whole-document digest/citation is
backend-declared and displayed as such; retained chunk text is checksum-validated.
No content can be promoted automatically into an approved plan, expected value,
permission, verification evidence or completed verdict. Stale/expired/unknown context
stays labelled. Source expiry is a freshness date; archive retention is a separate
reviewed policy, with no automatic deletion in H6C.

Schema parity:

```powershell
cd D:\coding\ADLC\adlc-flow
$env:PYTHONPATH=$PWD.Path
.\.venv\Scripts\python.exe scripts\generate_adlc_memory_schemas.py --check
```

The exporter prints JSON for authoring via the normal patch workflow; it does not
overwrite published schema files itself. See [rollout/limitations](../../../docs/milestones/harness-h6.md).
