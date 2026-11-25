# ============================================================
#  DEMO TNQD E2E - VERBOSE (show input/output per stage,
#  browser VISIBLE so you can watch the agent operate)
#  5-field KHÔNG hardcode: LLM đọc chunks cognee và chuẩn hoá
#  tại chỗ (compose_testcase.py --quiet) mỗi lần chạy.
#  Run:  powershell -ExecutionPolicy Bypass -File scripts\demo_tnqd.ps1
# ============================================================
$ROOT = "D:\VTS\TestAgent"
$TOK  = $env:TESTFORGE_BROKER_TOKEN
if (-not $TOK) { throw "Thiếu TESTFORGE_BROKER_TOKEN (env) — đặt trước khi chạy demo" }
$BRK  = $env:TESTFORGE_BROKER_URL; if (-not $BRK) { $BRK = "http://127.0.0.1:9099" }
$HDR  = @{ authorization = "Bearer $TOK" }
$JSON = "application/json; charset=utf-8"
$SLOW = 400          # ms delay per action -> easy to watch in headed browser
$PY   = "$ROOT\.venv\Scripts\python.exe"

# ---- DEMO TARGET (chỉ chọn CHỦ ĐỀ — nội dung testcase do LLM soạn từ cognee) ----
$DS    = "testforge-TNQD-P01"
$FID   = "FUNC-PTT-VIEW-LIST"
$QUERY = "4.6.2.4 Xem danh sách phát động Phong trào"

function Post-Json($uri, $obj) {
  $b = [System.Text.Encoding]::UTF8.GetBytes(($obj | ConvertTo-Json -Depth 6))
  Invoke-RestMethod -Uri $uri -Method Post -ContentType $JSON -Headers $HDR -Body $b -TimeoutSec 300
}
function Wait-Job($jobId) {
  do { Start-Sleep 8
    $j = Invoke-RestMethod "$BRK/api/v1/result/$jobId" -Headers $HDR -TimeoutSec 15
    "      [poll] $($j.status) ($($j.elapsed_seconds)s)"
  } while ($j.status -notin @("completed","failed"))
  return $j
}
function Get-Report {
  param($j)
  if ($j -and $j.output -and $j.output.parsed) { return $j.output.parsed }
  if ($j -and $j.output -and $j.output.log_path) {
    $txt = Get-Content $j.output.log_path -Raw -Encoding UTF8
    return $txt.Substring($txt.IndexOf('{')) | ConvertFrom-Json
  }
  throw "Job has no output: $($j.job_id) status=$($j.status)"
}
function Show-Trace($runId) {
  $p = Join-Path $ROOT "artifacts\automation\exploration\$runId\trace.jsonl"
  if (-not (Test-Path $p)) { "      (trace.jsonl not found: $p)"; return }
  Get-Content $p -Encoding UTF8 | ForEach-Object {
    $r = $_ | ConvertFrom-Json
    $nav = $r.observed_ui.navigator
    "      {0}: INPUT  step = {1}" -f $r.step_id, $r.user_intent
    "      {0}: OUTPUT {1} target='{2}' -> {3} (via {4})" -f $r.step_id,
        $r.selected_action, $r.target, $r.status, $nav.source
  }
}

# ============ [0] HEALTH ============
"`n===== [0] HEALTH ====="
$h = Invoke-RestMethod "$BRK/api/v1/health" -Headers $HDR
"  broker v$($h.version) | agent_memory=$($h.agent_memory.reachable) | k6=$($h.k6_installed)"

# ============ [1] COGNEE RECALL ============
"`n===== [1] TESTFORGE -> COGNEE (fetch-testcase) ====="
$fcInput = @{
  dataset = $DS; function_id = $FID
  query = $QUERY; top_k = 5 }
"  INPUT : dataset=$($fcInput.dataset) query='$($fcInput.query)' top_k=$($fcInput.top_k)"
$fc = Post-Json "$BRK/api/v1/fetch-testcase" $fcInput
"  OUTPUT: dataset_id=$($fc.dataset_id) | chunks=$($fc.chunks.Count) | entities=$($fc.entities.Count)"
$i = 0; foreach ($c in $fc.chunks) {
  $t = $c.text
  $head = ($t.Substring(0, [Math]::Min(200, $t.Length)) -replace "\s+", " ")
  "   chunk[$i] len=$($t.Length): $head..."
  $i++ }

# ============ [2] COMPOSE 5-FIELD (LLM + COGNEE — KHÔNG HARDCODE) ============
"`n===== [2] COMPOSE 5-FIELD (LLM đọc chunks cognee, chuẩn hoá tại chỗ) ====="
"  INPUT : $fcInput chunks (stage [1]) + query -> LLM soạn 5-field"
$env:TESTFORGE_BROKER_TOKEN = $TOK
$composeOut = & $PY "$ROOT\scripts\compose_testcase.py" --quiet `
  --dataset $DS --query $QUERY --function-id $FID --top-k 5
if ($LASTEXITCODE -ne 0) { throw "Composer FAIL (exit=$LASTEXITCODE) — xem stderr ở trên" }
$std = ($composeOut -join "`n") | ConvertFrom-Json
"  OUTPUT (LLM+grounding lines ở trên):"
$std | ConvertTo-Json -Depth 5 | ForEach-Object { "  $_" }

# ============ [3] EXPLORE (BROWSER VISIBLE) ============
"`n===== [3] EXPLORE (headed browser, slowmo=${SLOW}ms — watch the agent) ====="
$ex = Post-Json "$BRK/api/v1/explore" @{
  input_inline = $std
  base_url = "http://localhost:4200"; api_url = "http://localhost:7004"
  email = "admin@tnqd.local"; actor = "admin"
  password_env = "TNQD_ADMIN_PASSWORD"
  headed = $true; slowmo = $SLOW
  job_timeout_seconds = 1200 }
"  job=$($ex.job_id) | broker materialized -> $($ex.input_file)"
"  materialized input on broker host:"
Get-Content $ex.input_file -Encoding UTF8 | ForEach-Object { "    $_" }
$rep = Get-Report (Wait-Job $ex.job_id)
$sc = $rep.scenarios[0].summary
$runId = $sc.run_id
"  OUTPUT: status=$($sc.status) | grounded=$($sc.coverage.grounded)/$($sc.coverage.required) | run=$runId"
"  --- trace per step (input -> LLM output) ---"
Show-Trace $runId

# ============ [4] REPLAY + PROMOTION GATE (BROWSER VISIBLE) ============
"`n===== [4] REPLAY + PROMOTION GATE (headed browser, slowmo=${SLOW}ms) ====="
$rp = Post-Json "$BRK/api/v1/replay" @{
  session = "artifacts/automation/exploration/$runId"
  api_url = "http://localhost:7004"; email = "admin@tnqd.local"
  password_env = "TNQD_ADMIN_PASSWORD"; heal = $true
  headed = $true; slowmo = $SLOW
  job_timeout_seconds = 1200 }
"  job=$($rp.job_id)"
$rep2 = Get-Report (Wait-Job $rp.job_id)
$gate = $rep2.promotion

# ============ [5] GATE REPORT ============
"`n===== [5] PROMOTION GATE ====="
$gate.checks | ForEach-Object {
  "   {0,-25} {1}" -f $_.id, $(if ($_.passed) {"PASS"} else {"FAIL: $($_.detail)"}) }
"=> PROMOTED: $($gate.promoted) | blocking: [$($gate.blocking -join ', ')]"
