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
$expectedPython = Join-Path $resolvedRoot ".venv\Scripts\python.exe"
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

$venvOk = Test-Path $expectedPython

$criticalModules = @(
    "rich",
    "pydantic",
    "langchain_openai",
    "pytest_asyncio"
)

$imports = @()
foreach ($moduleName in $criticalModules) {
    & $selectedPython -c "import $moduleName" 2>$null
    $imports += [PSCustomObject]@{
        name = $moduleName
        ok = ($LASTEXITCODE -eq 0)
    }
}
$pytestVersion = & $selectedPython -m pytest --version
$pytestOk = $LASTEXITCODE -eq 0
$ruffVersion = & $selectedPython -m ruff --version 2>$null
$ruffOk = ($LASTEXITCODE -eq 0)

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
        using_venv = ($selectedPython -eq $expectedPython)
    }
    checks = [PSCustomObject]@{
        venv = [PSCustomObject]@{
            ok = $venvOk
            path = $expectedPython
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
