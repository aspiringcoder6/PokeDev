param([switch]$Regression)

$ErrorActionPreference = 'Stop'
$taskBackendRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).ProviderPath
$taskPython = Join-Path $taskBackendRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) {
    throw 'Create the existing adlc-flow virtual environment before running task-loop checks.'
}

# Keep offline checks separate from configured providers and existing data stores.
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
    ADLC_TASK_LOOP_MOCK_ENABLED = 'false'
    ADLC_TASK_LOOP_OPENCODE_ENABLED = 'false'
    ADLC_TASK_LOOP_HARNESS_ENABLED = 'false'
    OPENBLAS_NUM_THREADS = '1'
    OMP_NUM_THREADS = '1'
    MKL_NUM_THREADS = '1'
    PYTHONPATH = $taskBackendRoot
}
$taskSaved = @{}
$taskTempRoot = (Resolve-Path -LiteralPath ([IO.Path]::GetTempPath())).ProviderPath
$taskBaseTemp = [IO.Path]::GetFullPath((Join-Path $taskTempRoot ('adlc-task-loop-checks-' + [guid]::NewGuid().ToString('N'))))
if (-not $taskBaseTemp.StartsWith($taskTempRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -or (Test-Path -LiteralPath $taskBaseTemp)) {
    throw 'Task-loop checks require a new directory contained in the resolved temporary root.'
}
try {
    foreach ($taskName in $taskOverrides.Keys) {
        $taskSaved[$taskName] = [Environment]::GetEnvironmentVariable($taskName, 'Process')
        [Environment]::SetEnvironmentVariable($taskName, $taskOverrides[$taskName], 'Process')
    }
    Push-Location -LiteralPath $taskBackendRoot
    try {
        & $taskPython -m scripts.generate_adlc_task_loop_schemas --check
        if ($LASTEXITCODE -ne 0) { throw 'Task-loop schema parity check failed.' }
        & $taskPython -m scripts.generate_adlc_coding_agent_schemas --check
        if ($LASTEXITCODE -ne 0) { throw 'Unified Coding Agent schema parity check failed.' }
        & $taskPython -m scripts.generate_adlc_task_loop_operator_schemas --check
        if ($LASTEXITCODE -ne 0) { throw 'Task-loop operator schema parity check failed.' }
        & $taskPython -m scripts.generate_adlc_task_loop_runtime_schemas --check
        if ($LASTEXITCODE -ne 0) { throw 'Task-loop runtime schema parity check failed.' }
        & $taskPython -m scripts.generate_adlc_task_loop_harness_schemas --check
        if ($LASTEXITCODE -ne 0) { throw 'Harness iteration schema parity check failed.' }
        $taskTests = @(
            'tests/unit/adlc/test_task_loop.py', 'tests/unit/adlc/test_task_loop_live.py', 'tests/unit/adlc/test_package_registry.py',
            'tests/unit/adlc/test_package_access.py', 'tests/unit/adlc/test_package_resolver.py',
            'tests/unit/adlc/test_executor_router.py', 'tests/unit/adlc/test_opencode_runtime.py'
            'tests/unit/adlc/test_artifact_payload_store.py'
            'tests/unit/adlc/test_opencode_client.py'
            'tests/unit/adlc/test_coding_agent.py'
            'tests/unit/adlc/test_task_loop_inspection.py'
            'tests/unit/adlc/test_task_loop_runtime.py'
            'tests/unit/adlc/test_task_loop_harness.py'
        )
        if ($Regression) {
            $taskTests += @(
                'tests/unit/adlc/test_flow_run.py', 'tests/unit/adlc/test_orchestration_control.py',
                'tests/unit/adlc/test_orchestration_core.py', 'tests/unit/adlc/test_run_persistence.py',
                'tests/unit/adlc/test_mock_workflow.py', 'tests/unit/adlc/test_authoring_contract.py',
                'tests/unit/adlc/planning/test_plan_materialization.py',
                'tests/unit/adlc/planning/test_plan_proposal.py',
                'tests/unit/api/v1/test_adlc_runs.py', 'tests/unit/api/v1/test_adlc_plans.py'
                'tests/unit/api/v1/test_adlc_proposals.py'
                'tests/unit/api/v1/test_adlc_contract_execution.py', 'tests/unit/api/v1/test_adlc_contract_recovery.py'
                'tests/unit/adlc/test_contract_execution.py', 'tests/unit/adlc/test_contract_recovery.py'
                'tests/unit/adlc/test_harness_executor.py', 'tests/unit/adlc/test_harness_client.py'
                'tests/unit/adlc/test_harness_runtime.py', 'tests/unit/adlc/test_harness_callbacks.py'
            )
        }
        & $taskPython -m pytest @taskTests -q --tb=short -o log_cli=false -p no:cacheprovider --basetemp $taskBaseTemp
        if ($LASTEXITCODE -ne 0) { throw 'Task-loop checks failed.' }
        Write-Output 'Unified Coding Agent and task-loop offline checks passed. Git and verification commands ran; model calls were simulated.'
    } finally {
        Pop-Location
    }
} finally {
    foreach ($taskName in $taskSaved.Keys) {
        [Environment]::SetEnvironmentVariable($taskName, $taskSaved[$taskName], 'Process')
    }
}
