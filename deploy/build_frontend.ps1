$ErrorActionPreference = 'Stop'
$taskFrontend = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\adlc-flow\frontend'))
$taskStaging = Join-Path $taskFrontend ('.build-staging-' + [guid]::NewGuid().ToString('N'))
. (Join-Path $PSScriptRoot 'publish_frontend.ps1')
$taskPreviousBuildEnvironment = @{
    GOMAXPROCS = $env:GOMAXPROCS
    GOMEMLIMIT = $env:GOMEMLIMIT
    NODE_OPTIONS = $env:NODE_OPTIONS
}
$taskLocationChanged = $false
try {
    # Bound esbuild concurrency and heap usage on Windows machines running the desktop app.
    $env:GOMAXPROCS = '2'
    $env:GOMEMLIMIT = '768MiB'
    $env:NODE_OPTIONS = '--max-old-space-size=3072'
    Push-Location -LiteralPath $taskFrontend
    $taskLocationChanged = $true
    & '.\node_modules\.bin\vite.cmd' build --outDir $taskStaging --emptyOutDir
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build did not complete.' }
    Publish-FrontendBuild -FrontendRoot $taskFrontend -StagingRoot $taskStaging
}
finally {
    if ($taskLocationChanged) { Pop-Location }
    foreach ($taskBuildKey in $taskPreviousBuildEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($taskBuildKey, $taskPreviousBuildEnvironment[$taskBuildKey], 'Process')
    }
}
