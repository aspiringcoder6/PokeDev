$ErrorActionPreference = "SilentlyContinue"

function Test-Url($url) {
    try { (Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch { $false }
}

# Stack Docker: backend KHONG publish port — moi API di qua nginx (pm-frontend :80)
# LPTRNH~2 = ten 8.3 cua "D:\Lập trình web" (tránh lỗi encoding PS5.1 không BOM)
$composeFile = "D:\LPTRNH~2\TTeamFlow\docker-compose.yml"

if (-not (Test-Url "http://localhost/api/v1/health")) {
    docker info 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $dockerDesktop = Get-Item "$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe" -ErrorAction SilentlyContinue
        if (-not $dockerDesktop) { $dockerDesktop = Get-Item "C:\Program Files\Docker\Docker\Docker Desktop.exe" -ErrorAction SilentlyContinue }
        if ($dockerDesktop) { Start-Process $dockerDesktop.FullName }
        foreach ($i in 1..40) { Start-Sleep 4; docker info 2>$null | Out-Null; if ($LASTEXITCODE -eq 0) { break } }
    }
    docker compose -f "$composeFile" up -d 2>$null | Out-Null
    foreach ($i in 1..30) { Start-Sleep 3; if (Test-Url "http://localhost/api/v1/health") { break } }
}

"backend=$(Test-Url 'http://localhost/api/v1/health') frontend=$(Test-Url 'http://localhost')"
