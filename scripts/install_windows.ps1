<#
.SYNOPSIS
  One-shot Windows setup for Vibelution workbench (Phase 1 end-user path).

.DESCRIPTION
  Checks Python / Node / Git, creates .venv, installs Python deps, ensures web
  dependencies and dist, and optionally starts the Launcher.

  Phase 1 still requires system Python 3.11+ and Node 18+. Phase 2 will embed
  runtimes in a portable package (see docs/product/2026-08-06-windows-end-user-install.md).
#>
[CmdletBinding()]
param(
    [switch]$Start,
    [switch]$SkipFrontendBuild,
    [switch]$SkipFrontendInstall,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-ProjectDir {
    # Supports both:
    #   scripts/install_windows.ps1  (repo layout)
    #   package-root layout when markers live next to this script
    $here = $PSScriptRoot
    $rootMarkers = @(
        (Join-Path $here "requirements.txt"),
        (Join-Path $here "scripts\vibelution_launcher.ps1")
    )
    if (($rootMarkers | Where-Object { Test-Path -LiteralPath $_ }).Count -ge 2) {
        return (Resolve-Path -LiteralPath $here).Path
    }
    $parent = (Resolve-Path -LiteralPath (Join-Path $here "..")).Path
    if (-not (Test-Path -LiteralPath (Join-Path $parent "requirements.txt"))) {
        throw "Cannot locate Vibelution project root from script location: $here"
    }
    return $parent
}

$ProjectDir = Resolve-ProjectDir
$VenvDir = Join-Path $ProjectDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPythonw = Join-Path $VenvDir "Scripts\pythonw.exe"
$Requirements = Join-Path $ProjectDir "requirements.txt"
$WebDir = Join-Path $ProjectDir "web"
$DistIndex = Join-Path $WebDir "dist\index.html"
$LauncherScript = Join-Path $ProjectDir "scripts\vibelution_launcher.ps1"
$SyncLauncher = Join-Path $ProjectDir "scripts\windows_launcher_entry\sync_vibelution_launcher_entry.ps1"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Assert-Command {
    param(
        [string]$Name,
        [string]$Hint
    )
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $cmd) {
        throw "Missing required command '$Name'. $Hint"
    }
    return $cmd
}

function Resolve-HostPython {
    if ($Python -and $Python.Trim()) {
        if (-not (Test-Path -LiteralPath $Python)) {
            throw "Python path not found: $Python"
        }
        return (Resolve-Path -LiteralPath $Python).Path
    }
    foreach ($candidate in @("py", "python", "python3")) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        try {
            if ($candidate -eq "py") {
                $ver = & py -3 -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>$null
                if ($LASTEXITCODE -eq 0 -and $ver) {
                    $parts = $ver.Trim().Split(".")
                    $major = [int]$parts[0]
                    $minor = [int]$parts[1]
                    if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 11)) {
                        return "py -3"
                    }
                }
            } else {
                $ver = & $cmd.Source -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>$null
                if ($LASTEXITCODE -eq 0 -and $ver) {
                    $parts = $ver.Trim().Split(".")
                    $major = [int]$parts[0]
                    $minor = [int]$parts[1]
                    if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 11)) {
                        return $cmd.Source
                    }
                }
            }
        } catch {
            continue
        }
    }
    throw "Python 3.11+ is required. Install from https://www.python.org/downloads/ and re-run. Tip: check 'Add python.exe to PATH'."
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList,
        [string]$Label = $FilePath
    )
    Write-Host "  run: $Label"
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

Write-Host "Vibelution Windows install (Phase 1)"
Write-Host "Project: $ProjectDir"

Write-Step "Check prerequisites"
$hostPython = Resolve-HostPython
Write-Host "  Python: $hostPython"
Assert-Command -Name "node" -Hint "Install Node.js 18+ from https://nodejs.org/ (include npm)." | Out-Null
Assert-Command -Name "npm" -Hint "npm must be on PATH (comes with Node.js)." | Out-Null
Assert-Command -Name "git" -Hint "Install Git for Windows: https://git-scm.com/download/win" | Out-Null
$nodeVer = (& node --version).Trim()
$npmVer = (& npm --version).Trim()
Write-Host "  Node: $nodeVer"
Write-Host "  npm:  $npmVer"
if ($nodeVer -match '^v?(\d+)\.') {
    $nodeMajor = [int]$Matches[1]
    if ($nodeMajor -lt 18) {
        throw "Node.js 18+ is required (found $nodeVer). Install from https://nodejs.org/ and re-run."
    }
}

Write-Step "Create / reuse project virtualenv"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    if ($hostPython -eq "py -3") {
        Invoke-Native -FilePath "py" -ArgumentList @("-3", "-m", "venv", $VenvDir) -Label "py -3 -m venv .venv"
    } else {
        Invoke-Native -FilePath $hostPython -ArgumentList @("-m", "venv", $VenvDir) -Label "python -m venv .venv"
    }
} else {
    Write-Host "  .venv already exists"
}
if (-not (Test-Path -LiteralPath $VenvPython)) {
    throw "venv python missing after create: $VenvPython"
}

Write-Step "Install Python dependencies"
if (-not (Test-Path -LiteralPath $Requirements)) {
    throw "requirements.txt not found: $Requirements"
}
Invoke-Native -FilePath $VenvPython -ArgumentList @("-m", "pip", "install", "--upgrade", "pip") -Label "pip upgrade"
Invoke-Native -FilePath $VenvPython -ArgumentList @("-m", "pip", "install", "-r", $Requirements) -Label "pip install -r requirements.txt"

Write-Step "Install frontend dependencies"
if (-not $SkipFrontendInstall) {
    $nodeModules = Join-Path $WebDir "node_modules"
    if (-not (Test-Path -LiteralPath $nodeModules)) {
        Invoke-Native -FilePath "npm" -ArgumentList @("install", "--prefix", $WebDir) -Label "npm install (web)"
    } else {
        Write-Host "  web/node_modules present — skip npm install (pass reinstall manually if needed)"
    }
} else {
    Write-Host "  SkipFrontendInstall set"
}

Write-Step "Build frontend dist"
if (-not $SkipFrontendBuild) {
    if (-not (Test-Path -LiteralPath $DistIndex)) {
        Write-Host "  web/dist missing — building"
        Invoke-Native -FilePath "npm" -ArgumentList @("run", "build", "--prefix", $WebDir) -Label "npm run build (web)"
    } else {
        # Force a build when sources are commonly newer after pull; cheap enough for install path.
        Write-Host "  building web/dist (install path always refreshes unless -SkipFrontendBuild)"
        Invoke-Native -FilePath "npm" -ArgumentList @("run", "build", "--prefix", $WebDir) -Label "npm run build (web)"
    }
    if (-not (Test-Path -LiteralPath $DistIndex)) {
        throw "web/dist/index.html missing after build"
    }
} else {
    if (-not (Test-Path -LiteralPath $DistIndex)) {
        throw "web/dist/index.html missing and -SkipFrontendBuild was set"
    }
    Write-Host "  using existing web/dist"
}

Write-Step "Sync native Launcher entry (best-effort)"
if (Test-Path -LiteralPath $SyncLauncher) {
    try {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $SyncLauncher
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  warning: launcher sync returned $LASTEXITCODE (you can still start via scripts/vibelution_launcher.ps1)" -ForegroundColor Yellow
        } else {
            Write-Host "  launcher sync finished"
        }
    } catch {
        Write-Host "  warning: launcher sync failed: $($_.Exception.Message)" -ForegroundColor Yellow
    }
} else {
    Write-Host "  sync script not found — skip"
}

$configHome = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Vibelution\config"
Write-Host ""
Write-Host "Install finished." -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "  1. Configure models/keys in: $configHome\config.toml"
Write-Host "     (created on first Launcher start if missing)"
Write-Host "  2. Start:"
Write-Host "       Desktop shortcut: Vibelution Launcher"
Write-Host "       or: powershell -ExecutionPolicy Bypass -File scripts\vibelution_launcher.ps1 -Action start"
Write-Host "  3. Guide: docs\guides\install-windows.md"
Write-Host ""
if (Test-Path -LiteralPath $VenvPythonw) {
    Write-Host "Runtime pythonw: $VenvPythonw"
}

if ($Start) {
    Write-Step "Start Launcher"
    if (-not (Test-Path -LiteralPath $LauncherScript)) {
        throw "Launcher script missing: $LauncherScript"
    }
    & powershell -NoProfile -ExecutionPolicy Bypass -File $LauncherScript -Action start
}
