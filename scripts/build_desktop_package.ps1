$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$electronDir = Join-Path $projectDir "desktop/electron"
$desktopResourcesDir = Join-Path $projectDir "dist/desktop/win-unpacked/resources"
$desktopLaunchProfilePath = Join-Path $desktopResourcesDir "vibelution-launch-profile.json"
$operatorConfigPath = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Vibelution/config/config.toml"
$knownCodexPythonPath = Join-Path $env:USERPROFILE ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"

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

npm --prefix $electronDir install
npm --prefix $electronDir run package:dir

$desktopLaunchProfile = [ordered]@{
    schemaVersion = 1
    workspaceRoot = $projectDir
    operatorConfigPath = $operatorConfigPath
    pythonPath = Resolve-PythonPathForDesktopProfile
}

New-Item -ItemType Directory -Path $desktopResourcesDir -Force | Out-Null
$desktopLaunchProfileJson = $desktopLaunchProfile | ConvertTo-Json -Depth 4
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($desktopLaunchProfilePath, $desktopLaunchProfileJson, $utf8NoBom)
Write-Host "Wrote desktop launch profile: $desktopLaunchProfilePath"
