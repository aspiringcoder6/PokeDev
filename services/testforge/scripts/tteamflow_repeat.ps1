param([int]$Count = 10)

$adminPassword = $env:STAGING_TTEAMFLOW_ADMIN_PASSWORD
if (-not $adminPassword) { $adminPassword = Read-Host -Prompt "TTeamFlow admin password" }
$env:STAGING_TTEAMFLOW_ADMIN_EMAIL = "admin@example.com"
$env:STAGING_TTEAMFLOW_ADMIN_PASSWORD = $adminPassword
if (-not $env:STAGING_TTEAMFLOW_MEMBER_PASSWORD) { $env:STAGING_TTEAMFLOW_MEMBER_PASSWORD = Read-Host -Prompt "TTeamFlow member password" }

$results = @()
for ($i = 1; $i -le $Count; $i++) {
    .\.venv\Scripts\python.exe scripts\tteamflow_session.py --email $env:STAGING_TTEAMFLOW_ADMIN_EMAIL `
        --password $adminPassword --state-out config\tteamflow.admin.state.local.json `
        --token-out config\tteamflow.fixture.token.local.json 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $results += [pscustomobject]@{ run = $i; exit_code = 2; note = "session mint failed" }
        "run $i -> session FAILED"
        continue
    }
    $env:STAGING_TTEAMFLOW_FIXTURE_AUTH = (Get-Content config\tteamflow.fixture.token.local.json -Raw).Trim()
    .\.venv\Scripts\python.exe scripts\run_staging.py --profile config\tteamflow.staging.example.json `
        --suite opt\staging\tteamflow_projects.example.json 2>&1 | Out-Null
    $code = $LASTEXITCODE
    $results += [pscustomobject]@{ run = $i; exit_code = $code; note = "" }
    "run $i -> exit $code"
}

$pass = @($results | Where-Object { $_.exit_code -eq 0 }).Count
"TOTAL: $pass/$Count gate passed"
if ($pass -eq $Count) { exit 0 } else { exit 1 }
