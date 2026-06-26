$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$electronDir = Join-Path $projectDir "desktop/electron"
$desktopResourcesDir = Join-Path $projectDir "dist/desktop/win-unpacked/resources"
$desktopLaunchProfileWriter = Join-Path $electronDir "dist/scripts/writeLaunchProfile.js"
$operatorConfigPath = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Vibelution/config/config.toml"
$knownCodexPythonPath = Join-Path $env:USERPROFILE ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"

function Invoke-CheckedNative {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath failed with exit code $LASTEXITCODE"
    }
}

function Resolve-PythonPathForDesktopProfile {
    if ($env:VIBELUTION_PYTHON_PATH -and $env:VIBELUTION_PYTHON_PATH.Trim()) {
        return $env:VIBELUTION_PYTHON_PATH.Trim()
    }
    if ($env:PYTHON -and $env:PYTHON.Trim()) {
        return $env:PYTHON.Trim()
    }
    if (Test-Path -LiteralPath $knownCodexPythonPath) {
        return (Resolve-Path -LiteralPath $knownCodexPythonPath).Path
    }
    return ""
}

Invoke-CheckedNative npm @("--prefix", $electronDir, "install")
Invoke-CheckedNative npm @("--prefix", $electronDir, "run", "package:dir")

$pythonPath = Resolve-PythonPathForDesktopProfile
if (-not $pythonPath) {
    throw "Unable to resolve a Python executable for the Electron launch profile. Set VIBELUTION_PYTHON_PATH or PYTHON before packaging."
}

Invoke-CheckedNative node @(
    $desktopLaunchProfileWriter,
    "--resources-root", $desktopResourcesDir,
    "--workspace-root", $projectDir,
    "--operator-config", $operatorConfigPath,
    "--python-path", $pythonPath
)
