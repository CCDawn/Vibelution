<#
.SYNOPSIS
  Stage a Windows release folder for Vibelution (Phase 1 scaffolding).

.DESCRIPTION
  Produces dist/release/windows/Vibelution-<version>/ with:
    - Install-Windows.ps1 entry wrapper
    - launcher scripts
    - START_HERE.txt
    - filtered project snapshot (optional prebuilt web/dist)

  Phase 1 does NOT embed Python/Node. The package is a ready repo snapshot
  plus one-click install for machines that already have those runtimes.
  Phase 2 will add embeddable Python and omit Node from user machines.

  Keep this script ASCII-only so Windows PowerShell 5.1 parses it without
  depending on UTF-8 BOM.
#>
[CmdletBinding()]
param(
    [switch]$SkipFrontendBuild,
    [switch]$IncludeFullRepo = $true,
    [string]$OutputRoot = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VersionPath = Join-Path $ProjectDir "VERSION"
$Version = if (Test-Path $VersionPath) {
    (Get-Content -LiteralPath $VersionPath -Raw).Trim()
} else {
    "0.0.0-dev"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $ProjectDir "dist\release\windows"
}
$StageName = "Vibelution-$Version-win"
$StageDir = Join-Path $OutputRoot $StageName

function Invoke-Native {
    param([string]$FilePath, [string[]]$ArgumentList, [string]$Label)
    Write-Host "  $Label"
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) { throw "$Label failed: $LASTEXITCODE" }
}

Write-Host "Package Windows release: $StageName"

if (-not $SkipFrontendBuild) {
    $webDir = Join-Path $ProjectDir "web"
    Invoke-Native "npm" @("run", "build", "--prefix", $webDir) "npm run build (web)"
}

if (Test-Path -LiteralPath $StageDir) {
    Remove-Item -LiteralPath $StageDir -Recurse -Force
}
New-Item -ItemType Directory -Path $StageDir -Force | Out-Null

# Phase 1: copy project tree excluding heavy/dev noise for a runnable snapshot.
$excludeDirs = @(
    ".git", ".venv", "node_modules", "web\node_modules", ".pytest_cache", ".ruff_cache",
    ".runtime", "logs", "tmp", "backups", "dist\release", "dist\desktop",
    ".docs\project-memory", "__pycache__"
)

if ($IncludeFullRepo) {
    Write-Host "Copying project snapshot (filtered)..."
    $robocopyArgs = @(
        $ProjectDir, $StageDir, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/nc", "/ns", "/np"
    )
    foreach ($d in $excludeDirs) {
        # /XD expects directory names (or relative path segments), not absolute paths
        $robocopyArgs += "/XD"
        $robocopyArgs += $d
    }
    # Windows reserved device names break Compress-Archive / some extractors
    foreach ($xf in @("nul", "con", "prn", "aux")) {
        $robocopyArgs += "/XF"
        $robocopyArgs += $xf
    }
    & robocopy @robocopyArgs | Out-Null
    # robocopy exit 0-7 success
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy failed with exit $LASTEXITCODE"
    }
} else {
    throw "IncludeFullRepo:`$false is reserved for Phase 2 slim layout"
}

# Root entry: thin wrapper -> scripts\install_windows.ps1 (correct ProjectDir).
$installWrapper = @'
# Vibelution Windows install entry (release package root)
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$inner = Join-Path $here "scripts\install_windows.ps1"
if (-not (Test-Path -LiteralPath $inner)) {
    throw "Missing scripts\install_windows.ps1 under $here"
}
& powershell -NoProfile -ExecutionPolicy Bypass -File $inner @args
exit $LASTEXITCODE
'@
Set-Content -LiteralPath (Join-Path $StageDir "Install-Windows.ps1") -Value $installWrapper -Encoding UTF8

$startHere = @(
    "Vibelution $Version - Windows package (Phase 1)",
    "========================================",
    "",
    "This is an installable project snapshot, NOT a fully offline portable runtime.",
    "You still need Python 3.11+ and Node.js 18+ on the machine.",
    "",
    "Install:",
    "  1. In this folder, run PowerShell:",
    "       powershell -ExecutionPolicy Bypass -File .\Install-Windows.ps1",
    "     Optional auto-start:",
    "       powershell -ExecutionPolicy Bypass -File .\Install-Windows.ps1 -Start",
    "  2. Configure models/keys:",
    "       %USERPROFILE%\Documents\Vibelution\config\config.toml",
    "  3. Start Desktop shortcut Vibelution Launcher, or:",
    "       powershell -ExecutionPolicy Bypass -File .\scripts\vibelution_launcher.ps1 -Action start",
    "",
    "Chinese end-user guide:",
    "  docs\guides\install-windows.md",
    "Product plan:",
    "  docs\product\2026-08-06-windows-end-user-install.md",
    "",
    "Phase 2 will embed Python and avoid requiring Node on user machines."
) -join [Environment]::NewLine
Set-Content -LiteralPath (Join-Path $StageDir "START_HERE.txt") -Value $startHere -Encoding UTF8

# Zip
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
$zipPath = Join-Path $OutputRoot "$StageName.zip"
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
Write-Host "Compressing $zipPath ..."
# Prefer tar: Compress-Archive fails on Windows reserved names (e.g. accidental "nul" files).
$tar = Get-Command tar -ErrorAction SilentlyContinue
if ($tar) {
    # tar -C parent so zip root is the stage folder name
    $parent = Split-Path -Parent $StageDir
    $leaf = Split-Path -Leaf $StageDir
    Push-Location $parent
    try {
        & tar -a -cf $zipPath $leaf
        if ($LASTEXITCODE -ne 0) { throw "tar failed with exit $LASTEXITCODE" }
    } finally {
        Pop-Location
    }
} else {
    Compress-Archive -Path $StageDir -DestinationPath $zipPath -CompressionLevel Optimal
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "  Folder: $StageDir"
Write-Host "  Zip:    $zipPath"
