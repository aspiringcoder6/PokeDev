# Thu nghiem explore/replay tren testcase thu vien (task 2, docs/28)
$ErrorActionPreference = "Continue"
$ROOT = "D:\VTS\TestAgent"
$BRK = "http://127.0.0.1:9099"
$HDR = @{ authorization = "Bearer $($env:TESTFORGE_BROKER_TOKEN)" }
$JSON = "application/json; charset=utf-8"
if (-not $env:TESTFORGE_BROKER_TOKEN) {
  Get-Content "$ROOT\opt\broker.env" -Encoding UTF8 | ForEach-Object {
    if ($_ -match "^\s*([A-Z_]+)\s*=\s*(.+)\s*$") { Set-Item -Path "env:$($Matches[1])" -Value $Matches[2] }
  }
  $HDR = @{ authorization = "Bearer $env:TESTFORGE_BROKER_TOKEN" }
}

function Post-Json($uri, $obj) {
  $b = [System.Text.Encoding]::UTF8.GetBytes(($obj | ConvertTo-Json -Depth 6))
  Invoke-RestMethod -Uri $uri -Method Post -ContentType $JSON -Headers $HDR -Body $b -TimeoutSec 300
}
function Wait-Job2($jobId) {
  do { Start-Sleep 8
    $j = Invoke-RestMethod "$BRK/api/v1/result/$jobId" -Headers $HDR -TimeoutSec 15
    "      [poll] $($j.status) ($($j.elapsed_seconds)s)"
  } while ($j.status -notin @("completed","failed"))
  return $j
}
function Get-Report($j) {
  if ($j -and $j.output -and $j.output.parsed) { return $j.output.parsed }
  if ($j -and $j.output -and $j.output.log_path) {
    $txt = Get-Content $j.output.log_path -Raw -Encoding UTF8
    return $txt.Substring($txt.IndexOf('{')) | ConvertFrom-Json
  }
  return $null
}

$targets = @("FUNC-46210-PHE-DUYET-PHONG-TRAO","FUNC-46212-BAO-CAO-KET-QUA-PHAT-DONG-PHONG-TRAO",
             "FUNC-46213-LICH-SU-XU-LY","FUNC-4628-XOA-PHAT-DONG-PHONG-TRAO")
$results = @()
foreach ($fid in $targets) {
  $f = "$ROOT\artifacts\library\$fid.json"
  if (-not (Test-Path $f)) { "SKIP (khong co file): $fid"; continue }
  $std = Get-Content $f -Raw -Encoding UTF8 | ConvertFrom-Json
  "`n=== EXPLORE $fid ==="
  "  INPUT: $($std.feature) | steps=$($std.steps.Count) expected=$($std.expected_result.Count)"
  try {
    $ex = Post-Json "$BRK/api/v1/explore" @{
      input_inline = $std
      base_url = "http://localhost:4200"; api_url = "http://localhost:7004"
      email = "admin@tnqd.local"; actor = "admin"; password_env = "TNQD_ADMIN_PASSWORD"
      headed = $false; job_timeout_seconds = 900 }
    $rep = Get-Report (Wait-Job2 $ex.job_id)
    $runId = $rep.scenarios[0].summary.run_id
    $cov = $rep.scenarios[0].summary.coverage
    "  explore: run=$runId grounded=$($cov.grounded)/$($cov.required)"
    if ($rep.scenarios[0].summary.status -ne "GROUNDED") {
      "  -> PARTIAL/FAILED, bo qua replay"
      $results += [pscustomobject]@{ fid=$fid; explore="PARTIAL"; grounded="$($cov.grounded)/$($cov.required)"; promoted="n/a" }
      continue
    }
    "=== REPLAY $runId ==="
    $rp = Post-Json "$BRK/api/v1/replay" @{
      session = "artifacts/automation/exploration/$runId"
      api_url = "http://localhost:7004"; email = "admin@tnqd.local"
      password_env = "TNQD_ADMIN_PASSWORD"; heal = $true; headed = $false
      job_timeout_seconds = 1200 }
    $rep2 = Get-Report (Wait-Job2 $rp.job_id)
    $gate = $rep2.promotion
    $passN = ($gate.checks | Where-Object { $_.passed -eq $true }).Count
    "  gate: PROMOTED=$($gate.promoted) checks=$($passN)/$($gate.checks.Count) blocking=[$($gate.blocking -join ',')]"
    $results += [pscustomobject]@{ fid=$fid; explore="GROUNDED"; grounded="$($cov.grounded)/$($cov.required)"; promoted="$gate.promoted ($passN/$($gate.checks.Count))" }
  } catch {
    "  ERROR: $($_.Exception.Message)"
    $results += [pscustomobject]@{ fid=$fid; explore="ERROR"; grounded="?"; promoted="n/a" }
  }
}
"`n===== TONG KET ====="
$results | Format-Table -AutoSize | Out-String -Width 140
$results | ConvertTo-Json -Depth 3 | Out-File "$ROOT\artifacts\library\_e2e_validation.json" -Encoding UTF8
