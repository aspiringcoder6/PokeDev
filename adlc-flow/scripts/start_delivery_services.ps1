# Starts local development services independently of the chat's terminal sessions.
# Does not stop existing listeners, reload Harness, change roles, or send model prompts.
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$deliveryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$deliveryLogRoot = Join-Path $deliveryRoot 'data\delivery-services'
New-Item -ItemType Directory -Path $deliveryLogRoot -Force | Out-Null

$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
$env:NUMEXPR_NUM_THREADS = '1'
$env:PYTHONPATH = $deliveryRoot
$env:VITE_PROXY_TARGET = 'http://127.0.0.1:7860'

function Start-DeliveryService {
    param(
        [string]$Label,
        [int]$Port,
        [string]$Executable,
        [string[]]$Arguments,
        [string]$Signature,
        [string]$Directory
    )
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        Write-Output "$Label port $Port already has a listener; nothing was restarted."
        return
    }
    $starting = Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -and $_.CommandLine.Contains($deliveryRoot) -and
        $_.CommandLine.Contains($Signature)
    } | Select-Object -First 1
    if ($starting) {
        Write-Output "$Label is already starting (PID $($starting.ProcessId)); nothing was restarted."
        return
    }
    $logId = "$Label-$([guid]::NewGuid().ToString('N'))"
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments `
        -WorkingDirectory $Directory -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $deliveryLogRoot "$logId.stdout.log") `
        -RedirectStandardError (Join-Path $deliveryLogRoot "$logId.stderr.log")
    Write-Output "$Label started (launcher PID $($process.Id)); waiting for port $Port."
}

Start-DeliveryService -Label 'backend' -Port 7860 `
    -Executable (Join-Path $deliveryRoot '.venv\Scripts\python.exe') `
    -Arguments @('-X', 'utf8', ('"' + (Join-Path $deliveryRoot 'scripts/start_delivery_workspace.py') + '"')) `
    -Signature 'start_delivery_workspace.py' `
    -Directory $deliveryRoot

Start-DeliveryService -Label 'frontend' -Port 3000 `
    -Executable (Get-Command node -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source `
    -Arguments @(('"' + (Join-Path $deliveryRoot 'frontend/node_modules/vite/bin/vite.js') + '"'), '--host', '127.0.0.1', '--port', '3000', '--strictPort') `
    -Signature 'vite.js' `
    -Directory (Join-Path $deliveryRoot 'frontend')

Write-Output 'Open http://localhost:3000/work after startup. Private logs are in data/delivery-services.'
