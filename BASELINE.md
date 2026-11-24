# ADLC Technical Baseline

## Purpose

This document records the observed state of the repository before further ADLC customization. It separates facts verified from the checkout and local smoke tests from facts that were not preserved or were not tested.

After approval, do not silently rewrite this baseline. Record corrections in the Amendments section or create a new baseline.

## Baseline Metadata

| Field | Value |
|---|---|
| Baseline ID | `ADLC-BASELINE-001` |
| Observation date | `2026-08-26` |
| Prepared from | `aspiringcoder6` |
| Reviewed by | Not yet reviewed |
| Repository | `https://github.com/VDT-2026/VDT-ADLC.git` |
| Branch | `main` |
| Baseline commit | `83c9a97ab86678db81e9d98ce16caf4e7c14fba8` |
| Commit subject/date | `First commit`, `2026-08-26T11:18:25+07:00` |
| Baseline tag | Not created; intended name is `adlc-baseline-v0.1.0` |
| Overall result | `BLOCKED` |

The baseline is blocked from acceptance because the exact upstream Langflow tag and commit were not preserved, the original license file is not tracked, the root documentation is not committed, and a clean-clone installation has not been demonstrated.

## Source Provenance

| Field | Value |
|---|---|
| Upstream project | Langflow |
| Upstream repository | `https://github.com/langflow-ai/langflow` |
| Upstream release/tag | `NONE`|
| Upstream commit | `NONE`|
| Import date | `2026-08-26` (date of the initial outer commit) |
| Import method | Flattened source import into `adlc-flow/` |
| Upstream Git history retained | No; `adlc-flow/.git` is absent and the outer commit has no parent |
| Original license retained | No tracked `LICENSE`, `COPYING`, or `NOTICE` file was found; `adlc-flow/pyproject.toml` only declares `MIT` |

The local `adlc-flow/pyproject.toml` and `adlc-flow/frontend/package.json` both declare Langflow `1.12.0`. This identifies the intended source version but is not sufficient to identify the exact upstream source revision or prove an unmodified release import.

## Repository State

Commands observed on `2026-08-26`:

```powershell
git status --short
git branch --show-current
git rev-parse HEAD
git remote -v
git tag --points-at HEAD
```

Observed result:

```text
Untracked: BASELINE.md, Readme.md
Branch: main
Commit: 83c9a97ab86678db81e9d98ce16caf4e7c14fba8
Remote: origin https://github.com/VDT-2026/VDT-ADLC.git
Tags at HEAD: none
```

The working tree is not clean because the two root documentation files are untracked. Empty directories are also not represented in Git.

### Included modules

| Path | Source | Observed state |
|---|---|---|
| `adlc-flow/` | Flattened Langflow/Erwin Engine source; manifests declare `1.12.0` | Imported in the initial commit; 6,875 tracked files; exact upstream-relative changes cannot be calculated |
| `adlc_components/` | Existing ADLC custom components and example flows | Imported in the initial commit; 15 tracked files |
| `adlc-contracts/` | Planned shared contracts | Empty and therefore absent from the commit |
| `docs/` | Planned ADLC documentation | Empty and therefore absent from the commit |

## Verified Environment

### Operating system

| Field | Value |
|---|---|
| OS | Microsoft Windows NT build `22631.6199`; registry reports Windows Home Single Language `23H2` |
| Shell | PowerShell `7.6.4` |
| Architecture | `x64` |
| WSL used | No |

### Toolchain

These versions were read from the local environment. They are observed versions, not yet a supported-version matrix.

| Tool | Observed version | Command |
|---|---|---|
| Git | `2.46.2.windows.1` | `git --version` |
| System Python | `3.14.3` | `python --version` |
| Virtual-environment Python | `3.13.12` | `.venv\Scripts\python.exe --version` |
| uv | `0.12.5` | `uv --version` |
| Node.js | `24.14.0` | `node --version` |
| npm | `11.9.0` | `npm --version` |
| pnpm | `11.19.0` | `pnpm --version` |
| Docker | `29.5.3` | `docker --version` |
| Docker Compose | `v5.1.4` | `docker compose version` |
| PostgreSQL client | N/A; `psql` is not installed or not on `PATH` | `psql --version` |

Docker reported that the current user's Docker configuration file could not be read. Docker execution was not tested.

### Python and frontend environments

| Field | Value |
|---|---|
| Virtual environment path | `adlc-flow/.venv` |
| Python executable | `.venv\Scripts\python.exe` from inside `adlc-flow/` |
| Backend dependency specification | `adlc-flow/requirements.txt`; mostly unpinned |
| Backend lock file | None; `uv.lock` is absent |
| Langflow version | `1.12.0` in source manifests; the `langflow` distribution is not installed in the virtual environment |
| Frontend dependency lock | `adlc-flow/frontend/package-lock.json` |
| Frontend installed dependencies | `adlc-flow/frontend/node_modules` is present |

Selected installed Python packages include FastAPI `0.141.1`, Uvicorn `0.52.4`, pytest `9.1.1`, `langchain-openai` `1.6.0`, and SQLModel `0.0.39`.

## Configuration

| Setting | Baseline value |
|---|---|
| Database | SQLite for the verified smoke launch; source defaults to SQLite when `LANGFLOW_DATABASE_URL` is unset |
| Backend host/port | Source default `localhost:7860`; verified on `127.0.0.1:7861` to avoid port conflicts |
| Frontend port | `3000` according to the component README; startup not verified |
| Authentication | Automatic login defaults to enabled in source; no production auth configuration was verified |
| Custom component path | `..\adlc_components\custom_component` when launched from `adlc-flow/` |
| ADLC feature flag | Not implemented; no `ADLC_ENABLED` reference was found in source |
| OpenCode integration | Component implemented, but live requests are disabled until an API key is supplied |
| Root environment example | Missing; `.env.example` does not exist |
| Compose configuration | Missing at repository root |

Secrets are intentionally omitted.

## Installation Procedure

The checkout already contained `.venv` and `frontend/node_modules`, so installation was **not** re-run. The following are the repository-documented commands, not a clean-clone verification:

### Backend installation

```powershell
Set-Location adlc-flow
uv venv .venv --clear
uv pip install -r requirements.txt
```

The dependency specification is not locked and does not currently install `asgi_lifespan`, which is required by `tests/conftest.py`.

### Frontend installation

```powershell
Set-Location adlc-flow/frontend
npm install
```

For a reproducible clean install, prefer `npm ci` after confirming the committed lock file is current.

### Database initialization

No separate command was required for the smoke test. The backend created and migrated a temporary SQLite database during startup.

## Startup Procedure

### Start backend

The following repository-relative command was verified, with `LANGFLOW_CONFIG_DIR` and `LANGFLOW_DATABASE_URL` pointed at a disposable temporary directory during the test:

```powershell
Set-Location adlc-flow
$env:PYTHONPATH = (Resolve-Path .).Path
.venv\Scripts\python.exe -m langflow.__main__ run `
  --host 127.0.0.1 `
  --port 7861 `
  --backend-only `
  --components-path ..\adlc_components\custom_component `
  --log-level info
```

Verified result:

```text
Application startup complete.
Uvicorn running on http://127.0.0.1:7861
GET /health_check -> 200
{"status":"ok","chat":"ok","db":"ok"}
```

The normal documented backend port remains `7860`.

### Start frontend

```powershell
Set-Location adlc-flow/frontend
npm run dev
```

Expected URL from the component README: `http://localhost:3000`.

Status: `NOT TESTED`. Only a focused frontend unit test was executed.

## Baseline Smoke Tests

Status values are `PASS`, `FAIL`, `BLOCKED`, and `NOT TESTED`. A test is only marked `PASS` when it was executed.

| ID | Test | Expected result | Actual result | Status | Evidence |
|---|---|---|---|---|---|
| BL-01 | Backend starts | API starts without fatal error | Startup completed and health returned HTTP 200 with chat/database OK | `PASS` | Verified command and output above |
| BL-02 | Frontend starts | UI opens successfully | Development server was not started | `NOT TESTED` | None |
| BL-03 | User can open Langflow | Main page renders | No browser test was performed | `NOT TESTED` | None |
| BL-04 | Flow can be created | New flow is saved | Not exercised | `NOT TESTED` | None |
| BL-05 | Basic flow can run | Output is returned | Not exercised | `NOT TESTED` | None |
| BL-06 | Flow persists after restart | Saved flow remains available | Not exercised | `NOT TESTED` | None |
| BL-07 | Custom components load in UI | ADLC categories/components appear | Python imports passed, but UI visibility was not exercised; startup also reported empty `hooks`, `plugins`, and `skills` bundles | `NOT TESTED` | Startup log and BL-08 import check |
| BL-08 | OpenCode component initializes | Component loads without import failure | `OpenCodeModel`, `AgentComponent`, and `TaskToolkitComponent` imported; display names were printed | `PASS` | Direct import exited `0` |
| BL-09 | OpenCode request completes | A basic prompt returns a result | No API key or live provider call was used | `BLOCKED` | Requires an authorized OpenCode account/key |
| BL-10 | Backend tests run | Documented test command completes | Test collection stopped with `ModuleNotFoundError: asgi_lifespan` | `FAIL` | `pytest tests\unit\graph\graph\test_branch_traversal.py -o asyncio_mode=auto -q`, exit `4` |
| BL-11 | Frontend tests run | Test command completes | Focused suite passed: 1 suite, 2 tests | `PASS` | `npm test -- --runInBand src\utils\__tests__\sidebarBundles.test.ts`, exit `0` |
| BL-12 | Clean-clone setup works | A second environment reproduces setup | Not performed | `NOT TESTED` | None |

## Existing ADLC Functionality

| Capability | Status | Notes |
|---|---|---|
| OpenCode model component | `IMPLEMENTED / IMPORT PASS` | OpenAI-compatible Zen endpoint, streaming, reasoning-tag handling, API-key fallback via `OPENCODE_API_KEY`; live request not tested |
| Orchestrator agent | `IMPLEMENTED / IMPORT PASS` | Display name `Monarch`; contains tool-calling, chat-history, hooks, and token-usage integration; execution not tested |
| Task toolkit | `IMPLEMENTED / IMPORT PASS` | Component imports successfully; task execution not tested |
| Tool-call monitoring | `PARTIAL / NOT TESTED` | Orchestrator handles tool-call structures, but no end-to-end monitoring view or persistence was verified |
| Token monitoring | `PARTIAL / NOT TESTED` | Orchestrator uses `TokenUsageCallbackHandler`; reporting and UI visibility were not verified |
| Skill monitoring | `NOT IMPLEMENTED` | No component implementation; `custom_component/skills` only contains an empty `__init__.py` |
| Plugin loading | `NOT IMPLEMENTED` | No component implementation; `custom_component/plugins` only contains an empty `__init__.py` |
| Sandbox integration | `NOT VERIFIED` | Langflow contains generic sandbox-related code, but no ADLC sandbox service integration or configured endpoint was demonstrated |
| Memory integration | `PARTIAL / NOT TESTED` | The orchestrator references Langflow memory helpers; no ADLC memory service integration was demonstrated |
| Testing integration | `NOT IMPLEMENTED` | No ADLC testing-service component or endpoint was found |

Two example flow files are tracked: `adlc_components/flow/opencode provider.json` and `adlc_components/flow/orchestrator.json`. Neither was imported or executed during this verification.

## Known Issues

### ISSUE-001 — Upstream revision and license were not preserved

**Status:** `BLOCKED`

`adlc-flow/.git` is absent, the outer repository has one root commit with no parent, and no upstream tag or SHA is recorded. No license or notice file is tracked even though `pyproject.toml` declares the MIT license.

**Impact:** The exact source cannot be reproduced or reliably diffed against upstream, and license-attribution completeness cannot be demonstrated.

**Resolution:** Identify the source repository/tag/SHA from the importer or original checkout, record it here, and restore the corresponding upstream license and notices before accepting the baseline.

### ISSUE-002 — The current checkout is not a reproducible clean baseline

**Status:** `OPEN`

`BASELINE.md` and `Readme.md` are untracked, the intended baseline tag does not exist, `adlc-flow/requirements.txt` is mostly unpinned, and `uv.lock`, `.env.example`, and a root Compose file are absent. The planned `docs/` and `adlc-contracts/` directories are empty and therefore absent from Git.

**Impact:** Another developer cannot reproduce this exact environment from the recorded commit alone.

**Resolution:** Complete and commit the documentation/configuration artifacts, create a backend lock file, verify a clean clone, and only then create the baseline tag.

### ISSUE-003 — Documented backend test cannot collect

**Status:** `OPEN`

**Reproduction:**

```powershell
Set-Location adlc-flow
$env:PYTHONPATH = (Resolve-Path .).Path
.venv\Scripts\pytest.exe tests\unit\graph\graph\test_branch_traversal.py -o asyncio_mode=auto -q
```

**Actual:** `tests/conftest.py` fails to import `asgi_lifespan`; pytest exits with code `4`.

**Expected:** Tests collect and run to completion.

**Resolution:** Add the test dependency to the documented development environment and re-run the suite. Do not mark BL-10 as passing until then.

### ISSUE-004 — Empty custom-component bundles produce startup errors

**Status:** `OPEN`

When the backend scans `adlc_components/custom_component`, it reports `bundle-empty` errors for `hooks`, `plugins`, and `skills` because each directory has an `__init__.py` but no component class.

**Impact:** Startup succeeds, but the error output obscures real component-load failures and BL-07 cannot yet be considered verified.

**Resolution:** Remove empty bundles from the scanned component path, add valid components, or configure discovery so placeholders are ignored.

### ISSUE-005 — Telemetry writer falls back on this Windows environment

**Status:** `OPEN`

During the verified backend launch, the telemetry writer failed with `[WinError 87] The parameter is incorrect`. The application continued using its legacy direct-write path and the health check passed.

**Impact:** Telemetry persistence may differ from the intended path even though the backend remains operational.

**Resolution:** Reproduce with debug logging, identify the failing Windows process/IPC operation, and verify transaction and vertex-build writes.

## Deviations From Upstream

A complete upstream diff cannot be produced until ISSUE-001 is resolved. The following local customizations are directly observable:

| Change | File/module | Reason | Reversible? |
|---|---|---|---:|
| Flattened/custom source layout without upstream Git metadata | `adlc-flow/` | Import the engine into the ADLC repository | Yes, with a provenance-preserving re-import |
| Erwin Engine branding and operating instructions | `adlc-flow/README.md` and backend banner | Local product customization | Yes |
| OpenCode model, Monarch orchestrator, prompt builder, and task toolkit | `adlc_components/custom_component/` | ADLC agent workflow support | Yes |
| OpenCode and orchestrator example flows | `adlc_components/flow/` | Demonstration/importable workflows | Yes |

## Baseline Acceptance Criteria

- [ ] Exact upstream tag and commit are recorded.
- [ ] Repository commit and baseline tag are both recorded and present.
- [ ] Clean-checkout installation has been tested.
- [x] Backend startup command and health check are verified on the observed machine.
- [ ] Frontend startup is verified.
- [ ] Basic flow creation, execution, and persistence are tested.
- [ ] Custom components are visible and usable through the UI.
- [x] Existing custom component imports are tested.
- [x] Known issues found during verification are documented.
- [ ] A dedicated secret scan confirms no secrets are committed.
- [ ] At least one teammate has reviewed the baseline.

## Approval

| Role | Name | Decision | Date |
|---|---|---|---|
| Framework owner | Not recorded | Pending | — |
| Integration reviewer | Not recorded | Pending | — |

## Amendments

No amendments at baseline creation.

Future corrections must use this format:

| Date | Change | Reason | Author |
|---|---|---|---|
| YYYY-MM-DD | Description of correction | Why the correction was required | Author name |
