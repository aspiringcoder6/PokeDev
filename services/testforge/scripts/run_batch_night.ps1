# ============================================================
#  Chạy batch compose TOÀN BỘ thư viện testcase (đêm)
#  Đăng ký bằng Task Scheduler lúc 19:00 — xem docs/28
#  Log: artifacts\library\_batch_run_<timestamp>.log
# ============================================================
$ErrorActionPreference = "Continue"
$ROOT = "D:\VTS\TestAgent"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logDir = "$ROOT\artifacts\library"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = "$logDir\_batch_run_$stamp.log"
Start-Transcript -Path $log -Append | Out-Null

function Read-BrokerEnv {
  $path = "$ROOT\opt\broker.env"
  if (-not (Test-Path $path)) { throw "Thiếu $path (token/env broker)" }
  Get-Content $path -Encoding UTF8 | ForEach-Object {
    if ($_ -match "^\s*([A-Z_]+)\s*=\s*(.+)\s*$") { Set-Item -Path "env:$($Matches[1])" -Value $Matches[2] }
  }
}

Read-BrokerEnv
$hdr = @{ authorization = "Bearer $env:TESTFORGE_BROKER_TOKEN" }

# 1) Đảm bảo broker đang chạy
$up = $false
$BRK = "http://127.0.0.1:9099"
try {
  $h = Invoke-RestMethod "$BRK/api/v1/health" -Headers $hdr -TimeoutSec 5
  if ($h.status -eq "ok") { $up = $true }
} catch { $up = $false }

if (-not $up) {
  "[runner] broker chua chay -> start..." | Write-Output
  Start-Process -FilePath "$ROOT\.venv\Scripts\python.exe" `
    -ArgumentList "$ROOT\testforge_broker.py" -WorkingDirectory $ROOT `
    -WindowStyle Hidden `
    -RedirectStandardOutput "$ROOT\artifacts\broker\server.out.log" `
    -RedirectStandardError "$ROOT\artifacts\broker\server.err.log"
  Start-Sleep 6
}

# 2) Chạy batch toàn bộ (tự resume theo file tồn tại)
"[runner] bat dau batch_compose --all --judge luc $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Write-Output
& "$ROOT\.venv\Scripts\python.exe" "$ROOT\scripts\batch_compose.py" --all --judge 2>&1 | ForEach-Object { "$_" }
$code = $LASTEXITCODE
"[runner] batch ket thuc exit=$code luc $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Write-Output
Stop-Transcript | Out-Null
exit $code
