# Input readiness verification — 2026-11-25

Implemented Plan A and Plan B on `feat/input-readiness` in the existing isolated worktree.
Plan A resumed from the prior agent's A4 fix at `c2a1544`; verified A5/source review completion was
committed at `2666ccb`. Plan B has eight separate role prompts and durable service/API composition.
No implementation, merge, deployment or external messaging operation was run.

## Verification

| Check | Result |
| --- | --- |
| Source access suite | 215 passed |
| Requirement readiness suite | 37 passed |
| Existing harness client regression suite | 14 passed |
| Python correctness/import lint (Ruff E/F/I, E501 excluded) | Passed |
| Ruff formatting / git whitespace check | Passed |
| Pinned ECC, AI4RE and ACE dependency graph resolution | All three passed |
| Full application pytest collection | Blocked: missing `asgi_lifespan` in the independent test environment |
| Live GitHub/Lark/DSH/native framework acceptance | Not run; dedicated apps/presets/CLIs/human transport not provisioned |

The tests use real SQLite state, a minimal FastAPI app and its lifespan worker, HTTP fixtures,
and harmless local native-command fixtures with actual subprocess receipts. They verify source authorization,
pagination/completeness, total collection limits, replay and interrupted exchange recovery, concurrent
independent reports, final human confirmation, current backend policy, idempotent selection, and outbox
recovery without resending uncertain publications. Native fixture execution is not live Spec Kit/OpenSpec
acceptance. The full application suite is not claimed passing.

Run from this worktree with `PYTHONPATH=adlc-flow`, using the project-owned
`../.venv-readiness/Scripts/python.exe -m pytest -o addopts='' -p no:cacheprovider` and the respective
`--confcutdir=adlc-flow/tests/unit/adlc/source_access` or
`--confcutdir=adlc-flow/tests/unit/adlc/requirement_readiness` plus that suite directory.
The baseline harness uses `--confcutdir=adlc-flow/tests/unit/adlc` and
`adlc-flow/tests/unit/adlc/test_harness_client.py`.

## Review disposition

One fresh reviewer assessed each complete plan. Plan A's four Important findings and Plan B's four
Critical/nine Important findings were addressed in the implementation fix pass. Reproduction cases
were observed failing for authorization scope widening, mutable provenance, Lark coverage, policy and CAS
races, submission disclosure, rejected SDK prompts, native execution, named authorization, incomplete impact
retention and outbox failures. Covering suites are green. No second review was dispatched, per executing-plans.

Source reads remain application-owned and project-scoped. Default Human Gates remain required. Production
activation is opt-in; the example native manifest deliberately omits deployed presets/native route commands.
Provision those and run the live cases in the operator guides before claiming live acceptance.

## Deferred minors

- GitHub coerces malformed falsey non-null body values to empty text; valid provider data is unaffected.
- Lark Base permits more filter-condition values than the provider's limit of 10; the provider rejects them.
- The source-only guide does not explicitly say to rebuild the gateway after app-secret rotation; the
  requirement-readiness guide does. A gateway resolves secrets at construction.

## Execution decisions and costs

These preserve the exact rulings from both execution ledgers, including the previous agent's decisions.

### Plan A

- Ruling: Use the isolated feature worktree as the default execution location authorized by the requested execution workflow; the earlier question is an optional workspace preference, not a provider/security approval ? preserves main and allows reversible progress ? if the user prefers in-place work, deliver the completed commits there later without losing their files.
- Ruling: Test setup installs the dependencies actually needed by focused suites in a project-owned venv with existing base packages, rather than the entire unrelated Langflow application dependency tree ? no new runtime dependencies are declared ? full application startup remains a separate acceptance check.
- Ruling: Amend A4's fixture to include a real chat-binding lookup before thread list pages, and let the gateway reauthorize the resolved Wiki object before its content read ? global authorization requirements govern the illustrative fixture/signature gap ? costs one extra metadata request and a small resolver seam.
- Ruling: GitHub 403 rate limits and documented Lark token-expiry payload codes use provider-aware sanitized retry/error mapping ? provider semantics refine the illustrative HTTP-only mapping ? incorrect mappings would require connector correction, never a personal-token fallback.
- Ruling: Use a numeric scratch mirror solely for task-brief extraction because the installed helper matches numeric task headings while these approved plans use A/B task IDs ? original requirements remain unchanged ? costs no runtime change.
- Ruling: Expose SourceGateway.resolve_revision(grant, ref) -> SourceRef for authorized GitHub branch/tag/HEAD pinning, delegating to GitHubReader.resolve_revision only after authorization — B3 needs a gateway-owned way to pin code before reads without bypassing the grant — costs one narrow backend method and its deny-before-I/O test. B3 persists a per-connection/repo requested-ref -> commit map before file reads so later rounds/analysts cannot drift branches.
- Ruling: Reject colon-bearing connection IDs in both SourceRef and server grant construction, retaining the documented connection:resource configuration keys — removes composite-key ambiguity without changing the source-access port — costs a new restriction on future connection configuration; no deployed connector exists yet.
- Ruling: Add optional Evidence.requested_source (default None) for a resolved alias, and make_evidence keyword requested_source=None whose identity includes that binding when present — preserves both original Wiki input and actual object in the frozen evidence rather than losing the alias-to-object relation — costs one backward-compatible optional field in the new undeployed evidence contract. Existing direct-source behavior stays unchanged.
- Ruling: Add explicit pending source references and hard incomplete reasons to evidence, with defaults omitted from direct wire output, plus a pure effective-coverage helper for a collected evidence set — successful authorized child reads can close a parent reference gap without rewriting raw evidence or allowing pagination/unsupported binary failures to pass — costs a small new metadata/helper contract and requires B3 to consume effective coverage instead of blindly requiring every raw complete flag.
- Ruling: Treat an ordinary external hyperlink as reference metadata, not proof of extracted document text or an automatic unsupported-content blocker; recognized separately required Lark document/thread references remain pending until matching evidence is collected — aligns source-operation facts with the context verifier and avoids requiring an out-of-scope web crawler for URL cells — costs reliance on the requirement verifier to request genuinely needed external content, which remains blocked if no authorized tool exists.
- Ruling: Apply Lark page, response-byte and one-forced-refresh allowances to the original logical gateway read across its phases, including Wiki metadata and actual document retrieval, while retaining both source checks — compound operations must not silently multiply configured limits — costs an internal request-scoped preparation/context seam; public gateway read and revision-pinning ports stay stable.
- Ruling: Reject ambiguous pagination envelopes that omit has_more while carrying continuation (and non-boolean pagination flags), rather than accepting the sample's false default — completeness requirement overrides illustrative sample — malformed provider data stays explicit and cannot pass the context gate.
- Ruling: Use native PowerShell/Python equivalents of bash helpers for A/B task headings on Windows; preserve per-plan ledger and briefs — avoids WSL dependency — cost: helper output format differs, verification evidence retained.
- Ruling: Chat windows enumerate older roots within existing page budget and request window-filtered thread reads — older roots can contain in-window replies — cost: more reads or explicit partial result on large chats.

### Plan B

- Ruling: Use native Python/PowerShell equivalents for task helpers on Windows, with exact extracted briefs and per-task test logs — existing bash helpers require numeric headings — cost: manual ledger maintenance.
- Ruling: Ignore Markdown links inside fenced examples when walking dependencies — sample artifact paths are not installed dependencies — cost: executable dependencies must be linked in prose or declared in manifest.
- Ruling: Use acknowledged SDK prompt plus a persisted cursor and correlated history instead of SDK run() and default transport retries — observed SDK can replay uncertain submissions or reuse prior output — cost: genuinely uncorrelatable outcomes remain blocked for operator reconciliation.
- Ruling: Preserve only the complete selected upstream dependency closure and root licenses/provenance, with original bytes pinned by .gitattributes — unrelated translations and example packages are not runtime dependencies — cost: a newly required optional skill needs an explicit manifest/package update.
- Ruling: Keep full application dependency installation and live acceptance separate from the independent plan suites; install compatible Starlette only inside the existing test venv — full app collection currently fails on missing asgi_lifespan — cost: full application startup/regression and provisioned provider/DSH acceptance remain unverified.

## Review boundaries retained

- Live providers, remote preset compatibility and native framework checks require provisioned services;
  cost: offline success does not establish production compatibility.
- Normalization and actual human-channel delivery remain the other contributor's ports; cost: an absent
  bridge blocks interviews or leaves an authorized API selection waiting, rather than inventing a response.
- Full application startup and unrelated deployment/vendor behavior remain outside these independent
  suites; cost: the missing full-app dependency must be resolved in that deployment environment.
