function Publish-FrontendBuild {
    param([Parameter(Mandatory)][string]$FrontendRoot, [Parameter(Mandatory)][string]$StagingRoot)
    $ErrorActionPreference = 'Stop'
    $publishWorkspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
    $publishRoot = (Resolve-Path -LiteralPath $FrontendRoot).Path.TrimEnd('\')
    $publishStage = (Resolve-Path -LiteralPath $StagingRoot).Path.TrimEnd('\')
    if (-not $publishRoot.StartsWith($publishWorkspace + '\', [StringComparison]::OrdinalIgnoreCase) -or
        (Split-Path -Parent $publishStage) -ne $publishRoot -or
        (Split-Path -Leaf $publishStage) -notlike '.build-staging-*') {
        throw 'Frontend publication paths must be isolated inside the workspace.'
    }
    $publishTarget = Join-Path $publishRoot 'build'
    foreach ($publishPath in @($publishRoot, $publishStage, $publishTarget)) {
        if ((Test-Path -LiteralPath $publishPath) -and
            ((Get-Item -LiteralPath $publishPath -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Frontend publication refuses directory links.'
        }
    }
    if (@(Get-ChildItem -LiteralPath $publishStage -Recurse -Force |
        Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count -gt 0) {
        throw 'Frontend staging contains links.'
    }
    $publishIndex = Join-Path $publishStage 'index.html'
    if (-not (Test-Path -LiteralPath $publishIndex -PathType Leaf)) { throw 'Staged index.html is missing.' }
    $publishHtml = Get-Content -LiteralPath $publishIndex -Raw
    foreach ($publishMatch in [regex]::Matches($publishHtml, '/assets/[^"''\s<>]+')) {
        $publishAsset = [IO.Path]::GetFullPath((Join-Path $publishStage $publishMatch.Value.TrimStart('/')))
        if (-not $publishAsset.StartsWith($publishStage + '\', [StringComparison]::OrdinalIgnoreCase) -or
            -not (Test-Path -LiteralPath $publishAsset -PathType Leaf)) { throw 'A staged frontend asset is missing.' }
    }
    New-Item -ItemType Directory -Path $publishTarget -Force | Out-Null
    # Keep previous hashed assets for open tabs. Publish the entrypoint only
    # after every new asset is present, using one atomic file replacement.
    foreach ($publishEntry in Get-ChildItem -LiteralPath $publishStage -Force) {
        if ($publishEntry.Name -ne 'index.html') {
            Copy-Item -LiteralPath $publishEntry.FullName -Destination $publishTarget -Recurse -Force
        }
    }
    $publishDestination = Join-Path $publishTarget 'index.html'
    if (Test-Path -LiteralPath $publishDestination) {
        [IO.File]::Replace($publishIndex, $publishDestination, (Join-Path $publishStage 'previous-index.html'))
    } else {
        [IO.File]::Move($publishIndex, $publishDestination)
    }
    # Both absolute paths were validated above; never remove the served build.
    Remove-Item -LiteralPath $publishStage -Recurse -Force
}
