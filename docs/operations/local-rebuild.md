# Rebuild PokeDev without the old VPN server

**Implementation completed on 25 October 2026.** Use the
[local operating guide](../../deploy/local-recovery/README.md) and its combined
startup script. The sections below preserve the initial recovery plan and
preimplementation observations; their standalone commands are superseded by
the operating guide.

Reviewed against this Windows workspace on 25 October 2026.

The replacement consists of PokeDev, a new Gitea instance, a local Harness,
Sandbox Kit/OpenSandbox, TestForge, and optional Cognee memory. New application
workflows can run without the old VPN after those services are connected and
verified. Existing local files provide much of the software; credentials,
plugin installation, broker compatibility and data recovery still need work.

This guide is a recovery plan with an executable Gitea starter. A successful
complete replacement has **not** been tested. Docker Desktop's Linux engine
was stopped during this inspection. No existing environment files, databases,
Harness settings or running services were changed while preparing it.

## 1. Preserve what is already here

Stop application processes and finish or stop any active jobs before taking a
consistent backup. Copy the complete `D:\coding\ADLC` folder to another disk,
including hidden and Git-ignored files. A new Git clone omits critical local
deployment sources, databases, provider settings and credentials.

In particular, retain:

- The root `.env` and `.env.vai-platform.local` files, privately.
- `adlc-flow/adlc-local.db` and `adlc-flow/data/`, including project sources,
  cached Git repositories, Workloop runtime repositories, artifacts and history.
- The entire `agent-harness-server/` directory, particularly
  `deepseek-harness/workspace/.dsh/` and `deepseek-harness/data/`.
- `integration-sources/`, including the ignored `broker-services/` sources and
  the cached plugin releases.
- `deploy/harness-brokers/.env`, privately, plus any existing Docker volumes.

The inspected machine has approximately 16 GB RAM, 8 GB free on C: and 18 GB
free on D:. Make room for Docker images, its virtual disk, build caches and
runtime artifacts before building the whole stack. As a practical planning
target, reserve at least 50 GB additional free space; this is an estimate,
not a measured build requirement. Run optional Memory separately if memory
pressure prevents core services and a test worker from running together.

## 2. Create a replacement Gitea and administrator

Start Docker Desktop with Linux containers. From PowerShell:

```powershell
Set-Location 'D:\coding\ADLC'
docker compose -f .\deploy\local-gitea\compose.yml up -d
```

Open <http://localhost:3001/> and complete the first-install form. Keep SQLite,
retain the displayed HTTP port 3000 inside the container, and use
`http://localhost:3001/` as the public base URL. Create your administrator in
the install form. Public account registration is disabled in the Compose file.
HTTP Git access is sufficient for the current PokeDev integration; this starter
does not publish SSH.

Create a separate account/token for PokeDev with the repository permissions
needed to list, create, clone and push its private repositories. Store its
credentials only in the application's private configuration. The new instance
has its own accounts and tokens; the old server's tokens will not authenticate
to it. Check the pinned Gitea release's API compatibility with the app during
the workflow test below.

Publish locally available source into new empty repositories, preserving the
branches and tags that are actually present. For a normal local checkout, add
a separate recovery remote and explicitly push the branches/tags you want.
Review unpublished local changes separately. Preserve the original remotes for
provenance and avoid mirroring unreviewed refs into a populated repository.

A local clone can recover its available Git history. Full restoration of old
Gitea users, repository identities, issues, pull requests, attachments and
settings requires a server backup. Git LFS objects and submodule repositories
also need their own available copies. The official backup guide describes
full-instance recovery:
<https://docs.gitea.com/administration/backup-and-restore/>.

## 3. Bring up the supporting local services

The checked-in local deployment and downloaded backend sources are already
available. After resolving storage capacity:

```powershell
Set-Location 'D:\coding\ADLC'
.\deploy\harness-brokers\start.ps1 -Build
```

Add `-MemoryMcp` if the Cognee MCP integration is required. The existing script
generates private broker credentials only when its `.env` is absent, preserving
any existing file. Keep persistent volumes when stopping or rebuilding services.

Use [the local services runbook](dich-vu-cuc-bo.md) for the service-specific
health and sandbox lifecycle checks. Starting the Compose services alone does
not demonstrate compatibility with the latest PokeDev workflow: verify its
expected worker image, Python/browser dependencies, file upload/execution,
preview reachability, and TestForge response format. The previous live setup
used a different sandbox deployment and a specifically named TestForge worker.

## 4. Restore the local Harness runtime and its plugins

The Harness source, Dockerfile, sandbox wrapper and local settings already
exist under `agent-harness-server/deepseek-harness/`.

Before startup, add a local Compose override that binds the published Harness
port to `127.0.0.1:3080`, configure its connections to the local broker stack,
and review the container network paths. The existing base Compose file publishes
3080 on all host interfaces. Then build/start that deployment with the local
override and retain its existing bind-mounted data and workspace.

Use `open-webui.ps1` in the Harness directory to open its authenticated UI.
Keep the generated login token private. In Settings, restore provider access
and configure the service tools.

The local web profile currently contains `vai_agentmemory` and `vai_testforge`.
The latest live product flow also needs the reviewed `vai-sandbox`,
`vai-taskloop` and `vai-pokedev-services` releases and their dependencies.
Their local sources/cached releases are available in the Harness plugins and
`integration-sources/` directories. Install the compatible reviewed releases
into the **local** web profile, or publish them to the replacement Gitea and
install from there. Repoint Plugin Hub/catalog URLs and any Git dependencies
that still reference the old server. Do not assume a cached source directory
is an installed, loaded plugin.

Use the plugin's supported configuration surface for each URL and credential:

- Sandbox: `VAI_SANDBOX_BROKER_URL` and `VAI_SANDBOX_TOKEN`.
- TestForge: `TESTFORGE_BROKER_URL` and `TESTFORGE_BROKER_TOKEN`.
- AgentMemory: plugin URL configuration or `AGENT_MEMORY_MCP_URL`, and its
  configured account/tenant where required. Confirm how configuration reaches
  the sandboxed Harness process; a root `.env` entry alone does not forward it.

The latest Workloop and product-loop code selects
`netmind / zai-org/GLM-5.3-Flash`. The saved local Harness settings currently
define other provider names, including `opencode-viettel`, but no `netmind`
provider. Configure that exact provider/model binding with a reachable endpoint
and valid credentials, or deliberately update all relevant live bindings and
test them together. Changing the default chat model alone is insufficient.
Existing local provider credentials may be reusable; their validity and
network access have not been tested.

## 5. Connect PokeDev to the replacement services

After backing up the current files, change these nonsecret addresses and the
corresponding private credentials:

| Caller / configuration | Replacement target |
| --- | --- |
| Windows PokeDev UI | `http://127.0.0.1:7861/work` |
| Root `.env`: `ADLC_HARNESS_BASE_URL` | `http://127.0.0.1:3080` |
| Root `.env`: `ADLC_BLUEPRINT_DSH_BASE_URL` | `http://127.0.0.1:3080` |
| `.env.vai-platform.local`: `VAI_PLATFORM_URL` | `http://127.0.0.1:3080` |
| `.env.vai-platform.local`: `VAI_GITEA_URL` | `http://127.0.0.1:3001` |
| Windows Sandbox broker probes | `http://127.0.0.1:8000` |
| Windows TestForge health probe | `http://127.0.0.1:9099/api/v1/health` |
| Windows Cognee API, if enabled | `http://127.0.0.1:8010` |
| Windows Cognee MCP, if enabled | `http://127.0.0.1:8011/mcp` |

Update `VAI_GITEA_USER` / `VAI_GITEA_TOKEN` for the new account and
`VAI_PLATFORM_TOKEN` / `ADLC_BLUEPRINT_DSH_TOKEN` for the local Harness web
authentication. An enabled ADLC control API uses its own separately configured
service token and callback secret. Keep these token types separate.

Container callers need container-reachable URLs. Inside Harness, `localhost`
means Harness itself. Use an explicitly configured shared Docker network with
service names or a verified Docker Desktop host route. Check clone URLs
returned by Gitea as well as the API URL: browser-facing `localhost:3001`
links will not automatically work inside Harness. The standalone Gitea starter
above serves Windows callers; connecting its network to Harness is a separate
deployment step.

The existing Harness firewall permits a narrow set of host callback ports and
the old server IP. Add only the specific local service destinations/ports
needed before its private-network deny rules, with matching sandbox network
access. The current host-port list defaults to `7860,17861`; include 7861 if
that process receives callbacks. Do not assume either a common network or a
host gateway automatically satisfies all firewall and sandbox restrictions.

The new Gitea's numeric repository IDs differ from the old instance. Reconnect
recovered repositories as new project bindings and keep historical run records
and receipts intact. Existing in-progress jobs and expired previews need
reconciliation; infrastructure startup does not resume them automatically.

## 6. Start the app using the already built interface

The virtual environment, frontend build and local application database already
exist. Start the backend in a dedicated terminal after updating configuration:

```powershell
Set-Location 'D:\coding\ADLC'
$env:PYTHONPATH = 'D:\coding\ADLC\sdk;D:\coding\ADLC\adlc-flow'
& 'D:\coding\ADLC\adlc-flow\.venv\Scripts\python.exe' -m langflow run `
  --host 127.0.0.1 --port 7861 `
  --env-file 'D:\coding\ADLC\.env' `
  --frontend-path 'D:\coding\ADLC\adlc-flow\frontend\build'
```

Open <http://127.0.0.1:7861/work>. Existing local application accounts and
history remain in the existing application database.

## 7. Confirm normal operation with one new project

Verify these in order before declaring the replacement ready:

1. Sign in to the new Gitea; create and clone a private repository.
2. Sign in to local Harness; confirm required plugins loaded and provider
   configuration is usable. A model request is a separate, billable check.
3. Create a disposable Sandbox; upload a file, execute a Python check, read its
   result, and verify the worker can start and serve a candidate application.
4. Confirm TestForge's health and an actual browser/test job, with stored output.
5. If Memory is enabled, verify the selected project's remember/recall path.
6. In PokeDev, connect the new repository and submit a small requirement.
   Inspect and approve the new plan, execute it, review the real test results,
   and open its preview.
7. Use the existing human-controlled export action to publish the new result
   branch into the replacement Gitea and verify the resulting commit there.

The historical TNQD dashboard at `10.0.10.195:3011` is a separate application.
Its old fixed service-check target appears in both the backend and the service
plugin. Restoring that exact demo requires its source, dependencies and data,
then a reviewed replacement target; rebuilding Harness/Gitea does not recreate
the dashboard's contents.

Useful references:

- [Existing live app startup and workflow](../demos/huong-dan-chay-live-pokedev.md).
- [Local broker stack](dich-vu-cuc-bo.md).
- [PokeDev service bridge](../../integration-sources/pokedev-services-plugin/README.md).
- [Workloop sources and bootstrap](../../integration-sources/workloop/README.md).
- [Official Gitea Docker installation](https://docs.gitea.com/installation/install-with-docker/).
- [Gitea 28.2.0 release](https://github.com/go-gitea/gitea/releases/tag/v28.2.0).
