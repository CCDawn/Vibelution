<#
.SYNOPSIS
  Stage a Windows release folder for Vibelution (Phase 1 scaffolding).

.DESCRIPTION
  Produces dist/release/windows/Vibelution-<version>/ with:
    - install_windows.ps1 entry
    - launcher scripts
    - README-安装.txt
    - optional copy of prebuilt web/dist and selected project files for portable layout

  Phase 1 does NOT yet embed Python/Node. The package is a "ready repo snapshot"
  plus one-click install for machines that already have those runtimes.
  Phase 2 will add embeddable Python and omit Node from user machines.
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
        $robocopyArgs += "/XD"
        $robocopyArgs += (Join-Path $ProjectDir $d)
    }
    & robocopy @robocopyArgs | Out-Null
    # robocopy exit 0-7 success
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy failed with exit $LASTEXITCODE"
    }
} else {
    throw "IncludeFullRepo:`$false is reserved for Phase 2 slim layout"
}

# Always ensure install entry + Chinese readme at package root
$installSrc = Join-Path $ProjectDir "scripts\install_windows.ps1"
$installDst = Join-Path $StageDir "安装-Windows.ps1"
Copy-Item -LiteralPath $installSrc -Destination $installDst -Force

$readmeZh = @"
Vibelution $Version — Windows 包（Phase 1）
========================================

这是「可安装的项目快照」，不是完全离线绿色免环境包。

安装（需本机已有 Python 3.11+ 与 Node 18+）：
  1. 右键「安装-Windows.ps1」→ 使用 PowerShell 运行
     或在本目录打开 PowerShell 执行：
       powershell -ExecutionPolicy Bypass -File .\安装-Windows.ps1
  2. 按脚本提示配置
       %USERPROFILE%\Documents\Vibelution\config\config.toml
  3. 双击桌面 Vibelution Launcher，或：
       powershell -ExecutionPolicy Bypass -File .\scripts\vibelution_launcher.ps1 -Action start

说明文档：
  docs\guides\install-windows.md
  docs\product\2026-08-06-windows-end-user-install.md

Phase 2 将提供内嵌 Python、无需本机 Node 的便携包。
"@
Set-Content -LiteralPath (Join-Path $StageDir "请先阅读-安装说明.txt") -Value $readmeZh -Encoding UTF8

# Zip
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
$zipPath = Join-Path $OutputRoot "$StageName.zip"
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
Write-Host "Compressing $zipPath ..."
Compress-Archive -Path $StageDir -DestinationPath $zipPath -CompressionLevel Optimal

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "  Folder: $StageDir"
Write-Host "  Zip:    $zipPath"
