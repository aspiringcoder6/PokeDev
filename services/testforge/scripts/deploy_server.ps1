#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Deploy TestForge broker + plugin vai-testforce lên server 10.0.10.195 (runbook docs/27).

.DESCRIPTION
  B1: tar repo TestAgent -> /opt/testforge-ai, docker compose build + up broker, health
  B2: health broker từ Windows (LAN)
  B3: plugin vai-testforce: scp từ plugin\testforge-ai (bản portable, NGUỒN CHUẨN là
      server — local agent-harness-server clone ĐÃ CŨ, không push từ đó) +
      patch patch.yml idempotent trên server + git commit trên server +
      docker build harness + restart container + verify tools + health từ trong container

  Chạy: powershell -ExecutionPolicy Bypass -File scripts\deploy_server.ps1 [-SkipHarness]
#>
param(
    [string]$Server = "10.0.10.195",
    [string]$User = "root",
    [switch]$SkipHarness
)

$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot | Split-Path
$remote = "$User@$Server"
$har = "/opt/agent-harness-server/deepseek-harness"

function Ssh([string]$cmd) {
    Write-Host ">>> $cmd" -ForegroundColor Cyan
    ssh -o StrictHostKeyChecking=no $remote $cmd
    if ($LASTEXITCODE -ne 0) { throw "SSH step failed: $cmd" }
}

# 0. Preflight
Write-Host "== Preflight: ping $Server ==" -ForegroundColor Yellow
if (-not (Test-Connection $Server -Count 2 -Quiet)) { throw "Server $Server unreachable (VPN/network?)" }

# 1. Đồng bộ repo TestAgent -> /opt/testforge-ai
Write-Host "== B1: đồng bộ TestAgent -> /opt/testforge-ai ==" -ForegroundColor Yellow
Ssh "mkdir -p /opt/testforge-ai"
Push-Location $repo
tar -cf - --exclude=.venv --exclude=.git --exclude=artifacts --exclude=.pytest_cache `
    --exclude=__pycache__ --exclude=.pytest_* --exclude=plugin `
    src schemas opt scripts testforge_broker.py requirements.txt requirements.lock.txt `
    Dockerfile docker-compose.yml | ssh -o StrictHostKeyChecking=no $remote "tar -xf - -C /opt/testforge-ai"
Pop-Location
if ($LASTEXITCODE -ne 0) { throw "tar/scp repo thất bại" }
scp -o StrictHostKeyChecking=no "$repo\opt\broker.env" "${remote}:/opt/testforge-ai/opt/broker.env"
Ssh "cd /opt/testforge-ai && docker compose build broker && docker compose up -d broker"
Start-Sleep -Seconds 6
Ssh "curl -s -m 5 http://127.0.0.1:9099/api/v1/health"

# 2. Health từ Windows
Write-Host "== B2: health từ Windows ==" -ForegroundColor Yellow
$health = Invoke-RestMethod "http://${Server}:9099/api/v1/health" -TimeoutSec 8
Write-Host ("broker v{0} / project_root={1} / k6={2}" -f $health.version, $health.project_root, $health.k6_installed)

# 3. Plugin vai-testforce: scp lên server + patch.yml idempotent + commit TRÊN SERVER
if (-not $SkipHarness) {
    Write-Host "== B3: plugin vai-testforce -> server (server là nguồn chuẩn) ==" -ForegroundColor Yellow
    Ssh "mkdir -p $har/plugins/testforge-ai/lib $har/plugins/testforge-ai/skills/testforge-ai"
    scp -o StrictHostKeyChecking=no "$repo\plugin\testforge-ai\lib\index.js" "${remote}:$har/plugins/testforge-ai/lib/index.js"
    scp -o StrictHostKeyChecking=no "$repo\plugin\testforge-ai\package.json" "${remote}:$har/plugins/testforge-ai/package.json"
    scp -o StrictHostKeyChecking=no "$repo\plugin\testforge-ai\skills\testforge-ai\SKILL.md" "${remote}:$har/plugins/testforge-ai/skills/testforge-ai/SKILL.md"
    # patch.yml: thêm plugin row + skills dir nếu chưa có (idempotent — script python scp sang)
    scp -o StrictHostKeyChecking=no "$repo\scripts\patch_harness_patchyml.py" "${remote}:/tmp/patch_harness_patchyml.py"
    Ssh "python3 /tmp/patch_harness_patchyml.py"
    Ssh "cd /opt/agent-harness-server && git add deepseek-harness/plugins/patch.yml deepseek-harness/plugins/testforge-ai && git commit -m 'feat(testforge-ai): plugin 8 tools (health/explore/replay/staging/perf/fetch-testcase/recommend/result) + SKILL.md 6 luong + patch.yml dang ky' --no-verify || echo 'nothing to commit'"
    Ssh "cd /opt/agent-harness-server && docker build -t agent-harness:latest deepseek-harness/"
    Ssh "docker rm -f deepseek-harness-bwrap && docker run -d --name deepseek-harness-bwrap -p 3080-3082:3080-3082 agent-harness:latest"
    Start-Sleep -Seconds 5
    Ssh "docker logs deepseek-harness-bwrap 2>&1 | grep -i testforge | tail -5"
    Ssh "docker exec deepseek-harness-bwrap node -e `"fetch('http://10.0.10.195:9099/api/v1/health').then(r=>r.text()).then(t=>console.log('broker-from-harness:',t)).catch(e=>console.log('ERR',e.message))`""
}

Write-Host "== DONE. Nợ: đặt TESTFORGE_BROKER_URL + TESTFORGE_BROKER_TOKEN vào Secrets vault (UI Settings -> Secrets) nếu chưa; chat 'kiểm tra health TestForge' để verify E2E ==" -ForegroundColor Green
