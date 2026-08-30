param(
    [switch]$Json,
    [string]$ProjectRoot = $(Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"

function New-CheckResult {
    param(
        [string]$Name,
        [bool]$Ok,
        [string]$Detail = ""
    )

    [PSCustomObject]@{
        name = $Name
        ok = $Ok
        detail = $Detail
    }
}

$resolvedRoot = (Resolve-Path $ProjectRoot).Path
$localPython = Join-Path $resolvedRoot ".venv\Scripts\python.exe"
$gitCommonDir = (& git -C $resolvedRoot rev-parse --path-format=absolute --git-common-dir 2>$null)
$integrationRoot = $resolvedRoot
if (($LASTEXITCODE -eq 0) -and -not [string]::IsNullOrWhiteSpace(($gitCommonDir -join "").Trim())) {
    $resolvedCommonDir = [System.IO.Path]::GetFullPath(($gitCommonDir -join "").Trim())
    if ((Split-Path -Leaf $resolvedCommonDir) -eq ".git") {
        $integrationRoot = Split-Path -Parent $resolvedCommonDir
    } else {
        $integrationRoot = $resolvedCommonDir
    }
}
$integrationPython = Join-Path $integrationRoot ".venv\Scripts\python.exe"
$bootstrapPython = if (Test-Path $localPython) { $localPython } else { $integrationPython }
$toolchainScript = Join-Path $resolvedRoot "scripts\validation_toolchain.py"
$toolchainPayload = $null
$toolchainError = "validation_toolchain_missing"
if ((Test-Path $bootstrapPython) -and (Test-Path $toolchainScript)) {
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $toolchainOutput = & $bootstrapPython $toolchainScript --checkout $resolvedRoot --json 2>$null
    $toolchainExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousPreference
    try {
        $toolchainPayload = ($toolchainOutput -join "`n") | ConvertFrom-Json
    } catch {
        $toolchainPayload = $null
    }
    if (($null -ne $toolchainPayload) -and -not $toolchainPayload.ok) {
        $toolchainError = [string]$toolchainPayload.error
    } elseif (($toolchainExitCode -ne 0) -or ($null -eq $toolchainPayload)) {
        $toolchainError = "validation_toolchain_unhealthy"
    }
}
$toolchainOk = ($null -ne $toolchainPayload) -and [bool]$toolchainPayload.ok
$expectedPython = if ($toolchainOk) { [string]$toolchainPayload.pythonExecutable } else { $integrationPython }
$selectedPython = $expectedPython
$expectedHooksPath = ".githooks"
$configuredHooksPath = (& git -C $resolvedRoot config --get core.hooksPath 2>$null)
$hooksPathOk = ($LASTEXITCODE -eq 0) -and (($configuredHooksPath -join "").Trim() -eq $expectedHooksPath)
$preCommitHook = Join-Path $resolvedRoot ".githooks\pre-commit"
$qualityGateScript = Join-Path $resolvedRoot "scripts\local_quality_gate.py"

if (-not (Test-Path $selectedPython)) {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $pythonCmd) {
        $selectedPython = $pythonCmd.Source
    }
}

$venvOk = $toolchainOk -and (Test-Path $expectedPython)

$criticalModules = @(
    "rich",
    "pydantic",
    "langchain_openai",
    "pytest_asyncio"
)

$imports = @()
foreach ($moduleName in $criticalModules) {
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $selectedPython -c "import $moduleName" 2>$null
    $moduleOk = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $previousPreference
    $imports += [PSCustomObject]@{
        name = $moduleName
        ok = $moduleOk
    }
}
$previousPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$pytestVersion = & $selectedPython -m pytest --version
$pytestOk = $LASTEXITCODE -eq 0
$ruffVersion = & $selectedPython -m ruff --version 2>$null
$ruffOk = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $previousPreference

$importChecksOk = (($imports | Where-Object { -not $_.ok }).Count -eq 0)
$preCommitHookOk = Test-Path $preCommitHook
$qualityGateScriptOk = Test-Path $qualityGateScript
$allChecksOk = (
    $venvOk -and
    $pytestOk -and
    $importChecksOk -and
    $preCommitHookOk -and
    $qualityGateScriptOk -and
    $ruffOk
)

$report = [PSCustomObject]@{
    ok = $allChecksOk
    project_root = $resolvedRoot
    python = [PSCustomObject]@{
        expected = $expectedPython
        selected = $selectedPython
        using_venv = $toolchainOk
    }
    checks = [PSCustomObject]@{
        venv = [PSCustomObject]@{
            ok = $venvOk
            path = $expectedPython
        }
        validation_toolchain = [PSCustomObject]@{
            ok = $toolchainOk
            source = $(if ($toolchainOk) { [string]$toolchainPayload.source } else { "" })
            fingerprint = $(if ($toolchainOk) { [string]$toolchainPayload.fingerprint } else { "" })
            error = $(if ($toolchainOk) { "" } else { $toolchainError })
        }
        imports = @($imports)
        pytest_module = [PSCustomObject]@{
            ok = $pytestOk
            version = ($pytestVersion -join "`n")
        }
        git_hooks_path = [PSCustomObject]@{
            ok = $hooksPathOk
            expected = $expectedHooksPath
            configured = (($configuredHooksPath -join "").Trim())
            repair = "git config core.hooksPath .githooks"
        }
        pre_commit_hook = [PSCustomObject]@{
            ok = $preCommitHookOk
            path = $preCommitHook
        }
        local_quality_gate = [PSCustomObject]@{
            ok = $qualityGateScriptOk
            path = $qualityGateScript
        }
        ruff = [PSCustomObject]@{
            ok = $ruffOk
            version = ($ruffVersion -join "`n")
            executable = $selectedPython
        }
    }
}

if ($Json) {
    $report | ConvertTo-Json -Depth 6
    exit 0
}

Write-Host "== Vibelution Environment Doctor =="
Write-Host "ProjectRoot : $($report.project_root)"
Write-Host "Python      : $($report.python.selected)"
Write-Host "Venv        : $(if ($report.checks.venv.ok) { 'OK' } else { 'MISSING' })"
Write-Host "Toolchain   : $(if ($report.checks.validation_toolchain.ok) { $report.checks.validation_toolchain.source } else { $report.checks.validation_toolchain.error })"

foreach ($item in $report.checks.imports) {
    Write-Host ("Import {0,-18}: {1}" -f $item.name, $(if ($item.ok) { "OK" } else { "FAIL" }))
}

Write-Host "Pytest      : $(if ($report.checks.pytest_module.ok) { $report.checks.pytest_module.version } else { 'FAIL' })"
Write-Host "Ruff        : $(if ($report.checks.ruff.ok) { $report.checks.ruff.version } else { 'FAIL' })"
Write-Host "Hooks path  : configured='$($report.checks.git_hooks_path.configured)' expected='$($report.checks.git_hooks_path.expected)'"
if (-not $report.checks.git_hooks_path.ok) {
    Write-Host "Repair      : $($report.checks.git_hooks_path.repair)"
}
if ($report.ok) {
    exit 0
}
exit 1
