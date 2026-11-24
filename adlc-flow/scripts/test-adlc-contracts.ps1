param([switch]$Regression, [switch]$Frontend, [switch]$InstalledSdk)

$ErrorActionPreference = 'Stop'
$taskBackendRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).ProviderPath
$taskRepositoryRoot = Split-Path -Parent $taskBackendRoot
$taskHarnessRoot = Join-Path $taskRepositoryRoot 'agent-harness-server\deepseek-harness'
$taskPython = Join-Path $taskBackendRoot '.venv\Scripts\python.exe'
$taskNode = (Get-Command node -ErrorAction Stop).Source
if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) {
    throw 'Create the existing adlc-flow virtual environment before running contract tests.'
}

# Save/restore only task-owned settings; never load .env, tokens or provider keys.
$taskOverrides = @{
    ADLC_RUN_DB_PATH = ' '
    ADLC_HARNESS_ATTEMPT_DB_PATH = ' '
    ADLC_CONTRACT_DB_PATH = ' '
    ADLC_CONTRACT_EXECUTION_DB_PATH = ' '
    ADLC_HARNESS_ENABLED = 'false'
    ADLC_CONTRACTS_ENABLED = 'false'
    ADLC_CONTRACT_AUTHORING_ENABLED = 'false'
    ADLC_CONTRACT_EXECUTION_ENABLED = 'false'
    ADLC_CONTRACT_RECOVERY_ENABLED = 'false'
    ADLC_OPENCODE_ENABLED = 'false'
    PYTHONPATH = $taskBackendRoot
}
$taskSaved = @{}
$taskTestRoot = Join-Path $taskBackendRoot ('.adlc-h5a-tests-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $taskTestRoot | Out-Null

try {
    foreach ($taskName in $taskOverrides.Keys) {
        $taskSaved[$taskName] = [Environment]::GetEnvironmentVariable($taskName, 'Process')
        [Environment]::SetEnvironmentVariable($taskName, $taskOverrides[$taskName], 'Process')
    }
    Push-Location -LiteralPath $taskBackendRoot
    try {
        & $taskPython -m scripts.generate_adlc_contract_document_schemas --check
        if ($LASTEXITCODE -ne 0) { throw 'Contract schema parity check failed.' }
        & $taskPython -m scripts.generate_adlc_contract_execution_schemas --check
        if ($LASTEXITCODE -ne 0) { throw 'H5C schema parity check failed.' }

        $taskTests = @(
            'tests/unit/adlc/test_contract_documents.py', 'tests/unit/api/v1/test_adlc_contracts.py',
            'tests/unit/adlc/test_contract_authoring_package.py', 'tests/unit/adlc/test_harness_client.py'
            'tests/unit/adlc/test_contract_execution.py', 'tests/unit/api/v1/test_adlc_contract_execution.py'
            'tests/unit/adlc/test_contract_recovery.py', 'tests/unit/api/v1/test_adlc_contract_recovery.py'
        )
        if ($Regression) {
            $taskTests = @(
                'tests/unit/adlc', 'tests/unit/api/v1/test_adlc_runs.py',
                'tests/unit/api/v1/test_adlc_plans.py', 'tests/unit/api/v1/test_adlc_harness_results.py',
                'tests/unit/api/v1/test_adlc_artifacts.py', 'tests/unit/api/v1/test_adlc_contracts.py'
                'tests/unit/api/v1/test_adlc_contract_execution.py'
                'tests/unit/api/v1/test_adlc_contract_recovery.py'
            )
        }
        & $taskPython -m pytest @taskTests -q --tb=short -o log_cli=false -p no:cacheprovider --basetemp (Join-Path $taskTestRoot 'pytest')
        if ($LASTEXITCODE -ne 0) { throw 'ADLC contract/regression tests failed.' }
    } finally {
        Pop-Location
    }
    Push-Location -LiteralPath $taskHarnessRoot
    try {
        $taskNodeTests = @(
            'plugins/vai-adlc-skilltree/tests/*.test.mjs',
            'plugins/vai-adlc-contract-authoring/tests/*.test.mjs', 'plugins/vai-adlc-contract-ui/tests/*.test.mjs'
            'plugins/vai-adlc-contract-execution/tests/*.test.mjs'
            'plugins/vai-adlc-contract-recovery/tests/*.test.mjs'
        )
        if ($Regression) {
            $taskNodeTests += @(
                'plugins/vai-adlc-runtime/tests/*.test.mjs', 'plugins/vai-adlc-driver-deepseek/tests/*.test.mjs',
                'plugins/vai-adlc-artifacts-git/tests/*.test.mjs'
            )
        }
        & $taskNode --test @taskNodeTests
        if ($LASTEXITCODE -ne 0) { throw 'Harness contract/regression tests failed.' }
        & $taskNode scripts/sync-adlc-plugin-lock.mjs --check
        if ($LASTEXITCODE -ne 0) { throw 'Published H4 plugin locks drifted.' }
        & $taskNode scripts/check-adlc-authoring-lock.mjs --check
        if ($LASTEXITCODE -ne 0) { throw 'Published H5B authoring plugin locks drifted.' }
        & $taskNode scripts/check-adlc-contract-execution-lock.mjs --check
        if ($LASTEXITCODE -ne 0) { throw 'H5C execution plugin locks drifted.' }
        & $taskNode scripts/check-adlc-contract-recovery-lock.mjs --check
        if ($LASTEXITCODE -ne 0) { throw 'H5D recovery plugin locks drifted.' }
        if ($InstalledSdk) {
            & $taskNode scripts/check-adlc-authoring-sdk.mjs
            if ($LASTEXITCODE -ne 0) { throw 'Installed Harness SDK authoring boundary check failed.' }
            & $taskNode scripts/check-adlc-contract-execution-sdk.mjs
            if ($LASTEXITCODE -ne 0) { throw 'Installed Harness SDK contract execution boundary check failed.' }
        }
    } finally {
        Pop-Location
    }
    if ($Frontend) {
        Push-Location -LiteralPath (Join-Path $taskBackendRoot 'frontend')
        try {
            & .\node_modules\.bin\jest.cmd src/components/adlc/ContractViewer/index.test.tsx src/components/adlc/ContractPanel/index.test.tsx src/components/adlc/ContractExecutionPanel/index.test.tsx src/features/adlc-blueprint/approved-reference.test.ts src/features/adlc-blueprint/stage-editor-dialog.test.tsx src/pages/RunDetailPage --runInBand --silent
            if ($LASTEXITCODE -ne 0) { throw 'Contract/Run Detail frontend tests failed.' }
            & $taskNode scripts/check-contract-types.mjs
            if ($LASTEXITCODE -ne 0) { throw 'Focused contract frontend type check failed.' }
        } finally { Pop-Location }
    }
    Write-Output 'H5A/H5B/H5C/H5D offline checks passed. No live activation, model call or production database was used.'
} finally {
    foreach ($taskName in $taskSaved.Keys) {
        [Environment]::SetEnvironmentVariable($taskName, $taskSaved[$taskName], 'Process')
    }
    $taskResolved = (Resolve-Path -LiteralPath $taskTestRoot).ProviderPath
    $taskItem = Get-Item -LiteralPath $taskResolved
    if ((Split-Path -Parent $taskResolved) -ne $taskBackendRoot -or
        -not (Split-Path -Leaf $taskResolved).StartsWith('.adlc-h5a-tests-') -or
        ($taskItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Refusing cleanup: contract test directory did not resolve inside its exact workspace scope.'
    }
    Remove-Item -LiteralPath $taskResolved -Recurse -Force
}
