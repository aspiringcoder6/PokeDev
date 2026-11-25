# PokeDev service checks

Version 0.6.1 adds requirement-driven project verification at
`/api/v1/pokedev-services/projects`. PokeDev supplies the reviewed plan digest,
immutable source archive, argv test/build commands, protected tests and optional
preview/browser checks. Each job creates an isolated real Sandbox using the
TestForge worker image. TestForge records browser assertions; process exit codes,
source hashes and protected tests are checked independently of agent claims.
Jobs are scoped and durable. Replays and reads never create another Sandbox.
The preview forwards only to that Sandbox's port 8088, with no credentials or
caller-selected host. This route does not merge a branch or approve an ADLC cycle.
The existing TNQD result remains a historical project run.

Version 0.2.0 adds `product-loops`: native `vai-taskloop` contracts and the Harness
Goal service, with a single scoped proposal tool. The model is explicitly
`netmind / zai-org/GLM-5.3-Flash` (a separate profile from ADLC's Luna-only legacy
iteration API). PokeDev shows this binding before execution. No model fallback.

An explicit authenticated action submits a committed, owner-authorized Python
snapshot, immutable check files and up to three proposals. Every candidate gets
a fresh real Sandbox; only writable files may change. The fixed unittest runner
records exit codes and checks protected file hashes before and after execution.
Success requires both passing checks and a source delta, then a DONE native
contract and complete Goal. Goal rounds and elapsed time are bounded. Session
Memory is advisory and optional. TestForge's TNQD diagnostics remain separate;
they cannot verify this taskboard's Python acceptance criteria.

Receipts retain full candidate files, baseline findings, iterations and native
identities. Duplicate commands never create a second native agent. After a host
restart an uncertain execution stays UNCONFIRMED; GET never resumes the agent.
Signed platform cookies are checked on all custom routes. Only one live native
candidate is admitted. A candidate remains REVIEW_REQUIRED: this route does not
approve or complete an ADLC cycle, commit source, push or release the product.

The native task endpoint is `/api/v1/pokedev-services/product-loops`; GET
`/capabilities` does not create a session. POST uses a fresh `loop_id` and scope,
and GET `/{loop_id}?scope_id=...` only reads its receipt.

An authenticated HTTP adapter for the existing `vai-sandbox`, `vai_agentmemory`
and `vai_testforge` tools. It uses the platform's existing tool configuration and
credentials; it does not export credentials, choose a model, or create an agent.

`GET /api/v1/pokedev-services/capabilities` reports the tools available at runtime.
`POST /api/v1/pokedev-services/checks` starts a bounded check. `GET /checks/{id}`
observes its result. These routes use the platform's normal web authentication.

Each check uses a UUID and opaque owner scope supplied by PokeDev. Duplicate
commands reuse a durable receipt under `$DSH_HOME/pokedev-services`. After a restart,
known jobs are observed without another create/remember/explore operation. A lost
acknowledgment remains unconfirmed. PokeDev also retains its owner-protected history.
Results are diagnostics, not independent verification receipts or publication approval.

- Sandbox: creates only a new 10-minute session and checks a fixed file and Python command.
- Memory: uses Cognee's documented session-cache remember/recall mode, with
  `self_improvement=false`. Only a new synthetic session is used. Graph ingestion,
  permanent datasets and synthesis are disabled; this does not certify long-term
  graph storage. The server's session-cache route avoids the failing `.env` path.
- TestForge: runs five fixed read-only checks using the real `TraceRecorder`,
  `PlaywrightDriver` and `ExplorationSession` in the platform's pinned TestForge
  worker image, through Sandbox Kit. This adapter uses the user-selected Dev login
  button; the legacy broker Explorer requires API credentials. No fake password,
  graph ingestion, performance test, reset hook, cleanup DELETE or healing is used.
  Browser storage is excluded from traces. Service completion and application
  findings are reported separately; these smoke results are not Verify receipts.

The default allowed target is the dashboard explicitly selected for this integration.
Deployments may supply `allowedTargets` as trusted plugin configuration.
Run `npm test` to verify bounded commands, redaction and duplicate protection.

### Candidate previews (0.4.1)

`POST /api/v1/pokedev-services/previews` accepts only `preview_id`, an existing
completed `loop_id`, and its `scope_id`. It reruns the immutable protected tests
in a fresh one-hour Sandbox. No caller-selected source, commands or paths are
accepted. After `VERIFIED`, `POST /previews/{id}/deploy` starts the pinned Python
taskboard on port 8088 and probes five real HTTP operations. `GET /previews/{id}`
retains the test log, source hash, HTTP checks and expiry. The current broker's
`dind-sandbox:29` image is prepared with Python 3 before tests run. Its advertised
Docker endpoint is host-local, so PokeDev uses the authenticated, scoped
`POST /previews/{id}/http` relay. That endpoint accepts only the taskboard's
bounded HTTP routes, methods and body; it never accepts a URL, headers or shell.
PokeDev presents the app on a separate loopback origin; requests still execute
inside the remote Sandbox. Platform credentials stay server-side.
Repeated commands never provision or start a second sandbox. Unknown outcomes
remain `UNCONFIRMED`; a server restart does not replay a create or deployment.

The preview is a development deployment. Its HTTP smoke is not a signed,
independent Verify receipt and does not approve or release a delivery cycle.

### TNQD Angular workflow bridge (0.5.3)

The `/api/v1/pokedev-services/tnqd` routes bind immutable per-task inputs and native
TaskLoop artifacts to a project scope. Versioned documents use content-verified
Memory chunks when Cognee is reachable; PokeDev labels its separate project
document store explicitly during an outage. No graph ingestion is certified.

TNQD previews accept a hash-bound Angular archive through `previews/upload`,
`previews/{id}/chunks` and `previews/{id}/commit`. The fixed deployment uses the
pinned TestForge worker image, runs an isolated read-only API fixture with 45
synthetic records and checks the actual Sandbox's artifact binding over HTTP.
Static responses are cached from that same verified archive; data requests go
to the running Sandbox. The browser origin stays separate from PokeDev.

The fixed TestForge recorder checks seven browser scenarios, including searching
from page 3, late responses, empty/error states, read-only controls and 390px.
Results retain findings; a failed application check cannot become a passed run.
PokeDev may run a bounded TaskLoop repair, preserve the failed report and rerun
the same protected cases on a new artifact and Sandbox. These demo checks do not
certify the Java backend, database, backend RBAC or a production release.
