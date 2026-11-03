<#
.SYNOPSIS
  One-shot Windows setup for Vibelution desktop assistant and workbench.

.DESCRIPTION
  Checks Python / Node / Git and the VS C++ build toolchain, creates .venv,
  installs the Python runtime dependencies, ensures web and desktop/electron
  build dependencies (including the electron prebuilt binary), verifies the
  native Launcher, then builds and publishes the managed desktop package.
  Optionally starts a project.

  Build prerequisites are system Python 3.11+ and Node 22.12+ (Vite 8 and
  Electron 43 both require it). The managed desktop package build additionally
  needs Visual Studio 2022 Build Tools with the C++ workload. The managed
  desktop package carries the sealed assistant runtime produced by the shared
  owner.
#>
[CmdletBinding()]
param(
    [switch]$Start,
    [switch]$SkipFrontendBuild,
    [switch]$SkipFrontendInstall,
    # Force `npm run build` for web/dist even when dist looks fresh.
    # -SkipFrontendBuild wins if both are passed (existing skip semantics).
    [switch]$ForceFrontendBuild,
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
    if (@($rootMarkers | Where-Object { Test-Path -LiteralPath $_ }).Count -ge 2) {
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
$DesktopElectronDir = Join-Path $ProjectDir "desktop\electron"
$DistIndex = Join-Path $WebDir "dist\index.html"
$SyncLauncher = Join-Path $ProjectDir "scripts\windows_launcher_entry\sync_vibelution_launcher_entry.ps1"
$LocalAppData = [Environment]::GetFolderPath("LocalApplicationData")
$NativeLauncher = if ($LocalAppData) {
    Join-Path $LocalAppData "Vibelution\Launcher\VibelutionLauncher.exe"
} else {
    ""
}

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
        [string]$Label = $FilePath,
        # When set, run the child with this working directory via a bounded
        # process (used so relative tooling like electron/install.js resolves
        # against the right directory).
        [string]$WorkingDirectory = "",
        # When > 0, fail instead of hanging forever; the child is killed on
        # timeout. The child inherits the caller environment either way, so
        # ELECTRON_MIRROR and similar mirror variables stay effective.
        [int]$TimeoutSeconds = 0
    )
    Write-Host "  run: $Label"
    if ($WorkingDirectory -eq "" -and $TimeoutSeconds -le 0) {
        & $FilePath @ArgumentList
        if ($LASTEXITCODE -ne 0) {
            throw "$Label failed with exit code $LASTEXITCODE"
        }
        return
    }
    $quotedArguments = @($ArgumentList | ForEach-Object { '"{0}"' -f $_ })
    try {
        $process = Start-Process -FilePath $FilePath -ArgumentList $quotedArguments `
            -WorkingDirectory $WorkingDirectory -NoNewWindow -PassThru
    } catch {
        throw "$Label could not start: $($_.Exception.Message)"
    }
    # Windows PowerShell 5.1 quirk: the -PassThru object opens its process
    # handle lazily. If the child exits before the handle is touched,
    # ExitCode reads back as $null and a successful run would be reported as
    # a failure. Touching Handle now caches it so ExitCode stays readable.
    $null = $process.Handle
    $waitMilliseconds = if ($TimeoutSeconds -gt 0) { $TimeoutSeconds * 1000 } else { [int]::MaxValue }
    if (-not $process.WaitForExit($waitMilliseconds)) {
        try { $process.Kill() } catch { }
        throw "$Label timed out after $TimeoutSeconds seconds"
    }
    if ($null -eq $process.ExitCode) {
        throw "$Label finished but its exit code could not be read; treat the run as failed and re-run this installer."
    }
    if ($process.ExitCode -ne 0) {
        throw "$Label failed with exit code $($process.ExitCode)"
    }
}

function Ensure-ElectronBinary {
    # electron 43.x ships no postinstall hook, so `npm ci` verifies the
    # package tree but never downloads the prebuilt binary; the desktop
    # packaging step then dies with an opaque ENOENT on dist\electron.exe.
    # Re-run electron's own installer when the binary is absent.
    param(
        [string]$DesktopDir,
        [string]$NodeExecutable = "node",
        [int]$TimeoutSeconds = 900
    )
    $electronExe = Join-Path $DesktopDir "node_modules\electron\dist\electron.exe"
    if (Test-Path -LiteralPath $electronExe -PathType Leaf) {
        Write-Host "  electron binary present — reuse"
        return
    }
    $installScript = Join-Path $DesktopDir "node_modules\electron\install.js"
    if (-not (Test-Path -LiteralPath $installScript -PathType Leaf)) {
        throw "electron binary missing and installer not found: $installScript. Run 'npm ci --include=dev --prefix `"$DesktopDir`"' first, then re-run this installer."
    }
    Write-Host "  electron binary missing (electron 43+ has no postinstall) — running electron/install.js"
    try {
        Invoke-Native -FilePath $NodeExecutable -ArgumentList @($installScript) `
            -Label "node node_modules\electron\install.js (electron binary download)" `
            -WorkingDirectory $DesktopDir -TimeoutSeconds $TimeoutSeconds
    } catch {
        throw "electron binary download failed: $($_.Exception.Message). Self-help: from `"$DesktopDir`" run 'node node_modules\electron\install.js' with a reachable mirror (e.g. set ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/) or run 'npm rebuild electron', then re-run this installer."
    }
}

function Ensure-DesktopElectronDependencies {
    param([string]$DesktopDir)

    $current = $false
    if (Test-Path -LiteralPath (Join-Path $DesktopDir "node_modules") -PathType Container) {
        try {
            Invoke-Native -FilePath "npm" -ArgumentList @("ls", "--depth=0", "--include=dev", "--prefix", $DesktopDir) -Label "Verify desktop/electron dependencies" | Out-Host
            $current = $true
        } catch {
            Write-Host "  desktop/electron dependencies need installation"
        }
    }
    if (-not $current) {
        Invoke-Native -FilePath "npm" -ArgumentList @("ci", "--include=dev", "--prefix", $DesktopDir) -Label "npm ci (desktop/electron)"
    } else {
        Write-Host "  desktop/electron dependencies verified — reuse"
    }
    # npm-ls success does not imply the prebuilt electron binary exists.
    Ensure-ElectronBinary -DesktopDir $DesktopDir
}

function Sync-NativeLauncherForManagedInstall {
    param([string]$SyncScript, [string]$ProjectRoot, [string]$OutputPath)

    if (-not $OutputPath -or -not (Test-Path -LiteralPath $SyncScript -PathType Leaf)) {
        throw "Native Launcher sync is required before managed publication."
    }
    $powershellExe = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
    $raw = @(Invoke-Native -FilePath $powershellExe -ArgumentList @(
        "-NoLogo", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
        "-ExecutionPolicy", "Bypass", "-File", $SyncScript,
        "-ProjectDir", $ProjectRoot, "-OutputPath", $OutputPath
    ) -Label "Sync required native Launcher entry")
    try {
        $result = ($raw -join "`n") | ConvertFrom-Json -ErrorAction Stop
        $matchesOutput = [string]::Equals([IO.Path]::GetFullPath([string]$result.outputPath),
            [IO.Path]::GetFullPath($OutputPath), [StringComparison]::OrdinalIgnoreCase)
        if ([string]$result.status -cnotin @("current", "rebuilt") -or -not $matchesOutput -or
            -not (Test-Path -LiteralPath $OutputPath -PathType Leaf)) {
            throw "Native Launcher sync did not confirm the required executable."
        }
    } catch {
        throw "Native Launcher sync did not confirm a current executable; managed package was not published."
    }
}

function Get-RuntimeRequirementLines {
    # Mirrors _runtime_requirements() in scripts/build_assistant_runtime.py:
    # every line before the '# 开发/测试依赖' boundary is the runtime set and
    # per-line '# ...' comments are stripped. Emits one string per runtime
    # requirement (callers wrap with @() to normalise the single-line case).
    # Returns $null (fail-open) when the boundary is missing, the file cannot
    # be read/parsed, or the runtime section ends up empty; the caller then
    # falls back to installing the full requirements file instead of blocking
    # the user.
    param([string]$RequirementsPath)

    try {
        $text = [IO.File]::ReadAllText($RequirementsPath)
        $boundary = "# 开发/测试依赖"
        $boundaryIndex = $text.IndexOf($boundary, [StringComparison]::Ordinal)
        if ($boundaryIndex -lt 0) {
            return $null
        }
        $lines = @()
        foreach ($line in ($text.Substring(0, $boundaryIndex) -split "\r?\n|\r")) {
            $commentIndex = $line.IndexOf("#")
            if ($commentIndex -ge 0) {
                $line = $line.Substring(0, $commentIndex)
            }
            $line = $line.Trim()
            if ($line) {
                $lines += $line
            }
        }
        if (@($lines).Count -eq 0) {
            return $null
        }
        return $lines
    } catch {
        return $null
    }
}

function Test-FrontendDistFresh {
    # True only when web/dist/index.html exists and is at least as new as the
    # newest web source file. The source scan walks the whole web tree but
    # prunes dependency and build-output directories (node_modules, dist,
    # .vibelution-builds) at any depth, so stale or fresh inputs inside them
    # never skew the comparison and the (huge) node_modules tree is never
    # enumerated. Reparse points (junctions/symlinks) are skipped to avoid
    # cycles.
    param(
        [string]$WebRoot,
        [string]$DistIndex
    )

    if (-not (Test-Path -LiteralPath $DistIndex -PathType Leaf)) {
        return $false
    }
    $distWriteTime = (Get-Item -LiteralPath $DistIndex).LastWriteTimeUtc
    $excludedSegments = @{ "node_modules" = $true; "dist" = $true; ".vibelution-builds" = $true }
    $newestSourceTime = $null
    $pending = New-Object System.Collections.Generic.Stack[string]
    $pending.Push($WebRoot)
    while ($pending.Count -gt 0) {
        $directory = $pending.Pop()
        foreach ($entry in @(Get-ChildItem -LiteralPath $directory -Force -ErrorAction SilentlyContinue)) {
            if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                continue
            }
            if ($entry.PSIsContainer) {
                if (-not $excludedSegments.ContainsKey($entry.Name)) {
                    $pending.Push($entry.FullName)
                }
                continue
            }
            if ($null -eq $newestSourceTime -or $entry.LastWriteTimeUtc -gt $newestSourceTime) {
                $newestSourceTime = $entry.LastWriteTimeUtc
            }
        }
    }
    if ($null -eq $newestSourceTime) {
        # No source files found — freshness cannot be proven, rebuild instead.
        return $false
    }
    return ($distWriteTime -ge $newestSourceTime)
}

function Assert-VsCppBuildToolchain {
    # The managed desktop package build compiles workbench_job.node with
    # node-gyp, which needs the MSVC C++ toolchain. Detect it up front via
    # vswhere and fail with an actionable message instead of an opaque
    # compiler error buried in the packaging step.
    param(
        [string]$VswherePath = (Join-Path ([Environment]::GetFolderPath("ProgramFilesX86")) "Microsoft Visual Studio\Installer\vswhere.exe")
    )

    $installations = @()
    if (Test-Path -LiteralPath $VswherePath -PathType Leaf) {
        $rawOutput = @()
        try {
            $rawOutput = @(& $VswherePath "-products" "*" "-requires" "Microsoft.VisualStudio.Component.VC.Tools.x86.x64" "-property" "installationPath" 2>$null)
        } catch {
            $rawOutput = @()
        }
        $installations = @($rawOutput | Where-Object { $_ -and $_.Trim() })
    }
    if ($installations.Count -eq 0) {
        throw "Visual Studio C++ build tools are missing, but building the managed desktop package must compile workbench_job.node with node-gyp. Install Visual Studio 2022 Build Tools with the 'Desktop development with C++' workload (MSVC + Windows SDK):
  winget install --id Microsoft.VisualStudio.2022.BuildTools -e --override `"--quiet --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended`"
Then open a NEW terminal (refreshed PATH) and re-run this installer. Prerequisites are listed in docs\guides\install-windows.md ('你需要什么')."
    }
    Write-Host "  VS C++ toolchain found: $($installations[0].Trim())"
}

Write-Host "Vibelution Windows desktop install"
Write-Host "Project: $ProjectDir"

Write-Step "Check prerequisites"
$hostPython = Resolve-HostPython
Write-Host "  Python: $hostPython"
Assert-Command -Name "node" -Hint "Install Node.js 22.12+ from https://nodejs.org/ (include npm)." | Out-Null
Assert-Command -Name "npm" -Hint "npm must be on PATH (comes with Node.js)." | Out-Null
Assert-Command -Name "git" -Hint "Install Git for Windows: https://git-scm.com/download/win" | Out-Null
$nodeVer = (& node --version).Trim()
$npmVer = (& npm --version).Trim()
Write-Host "  Node: $nodeVer"
Write-Host "  npm:  $npmVer"
$nodeVersionMatch = [regex]::Match($nodeVer, '^v?(\d+)\.(\d+)')
if (-not $nodeVersionMatch.Success) {
    throw "Could not parse Node version '$nodeVer'. Node.js 22.12+ is required; install the current LTS from https://nodejs.org/ and re-run (see docs\guides\install-windows.md, '你需要什么')."
}
$nodeMajor = [int]$nodeVersionMatch.Groups[1].Value
$nodeMinor = [int]$nodeVersionMatch.Groups[2].Value
if ($nodeMajor -lt 22 -or ($nodeMajor -eq 22 -and $nodeMinor -lt 12)) {
    throw "Node.js 22.12+ is required (found $nodeVer); Vite 8 and Electron 43 both require it. Install the current LTS from https://nodejs.org/ and re-run (see docs\guides\install-windows.md, '你需要什么')."
}
# The managed desktop package build (last step) needs the MSVC C++ toolchain
# for node-gyp; check it here so a missing toolchain fails fast instead of
# after minutes of pip/npm/frontend work.
Assert-VsCppBuildToolchain

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
$runtimeRequirementLines = Get-RuntimeRequirementLines -RequirementsPath $Requirements
if ($null -ne $runtimeRequirementLines) {
    Write-Host "  installing runtime dependencies only (dev/test section of requirements.txt excluded)"
    Invoke-Native -FilePath $VenvPython `
        -ArgumentList (@("-m", "pip", "install") + @($runtimeRequirementLines)) `
        -Label "pip install (runtime requirements)"
} else {
    Write-Warning "Could not resolve the runtime/development boundary in requirements.txt; falling back to a full install (dev/test dependencies included)."
    Invoke-Native -FilePath $VenvPython -ArgumentList @("-m", "pip", "install", "-r", $Requirements) -Label "pip install -r requirements.txt (full)"
}

Write-Step "Prepare desktop/electron build dependencies"
Ensure-DesktopElectronDependencies -DesktopDir $DesktopElectronDir

Write-Step "Install web frontend dependencies"
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
    # Reuse web/dist when no web source file is newer than dist/index.html;
    # pass -ForceFrontendBuild to rebuild unconditionally.
    if ($ForceFrontendBuild) {
        Write-Host "  ForceFrontendBuild set — rebuilding web/dist"
        Invoke-Native -FilePath "npm" -ArgumentList @("run", "build", "--prefix", $WebDir) -Label "npm run build (web)"
    } elseif (Test-FrontendDistFresh -WebRoot $WebDir -DistIndex $DistIndex) {
        Write-Host "  web/dist is fresh — reuse"
    } elseif (-not (Test-Path -LiteralPath $DistIndex)) {
        Write-Host "  web/dist missing — building"
        Invoke-Native -FilePath "npm" -ArgumentList @("run", "build", "--prefix", $WebDir) -Label "npm run build (web)"
    } else {
        Write-Host "  web/dist is stale (web sources newer than dist) — rebuilding"
        Invoke-Native -FilePath "npm" -ArgumentList @("run", "build", "--prefix", $WebDir) -Label "npm run build (web)"
    }
    if (-not (Test-Path -LiteralPath $DistIndex)) {
        throw "web/dist/index.html missing after build"
    }
} else {
    if ($ForceFrontendBuild) {
        Write-Host "  both -SkipFrontendBuild and -ForceFrontendBuild set — skip wins"
    }
    if (-not (Test-Path -LiteralPath $DistIndex)) {
        throw "web/dist/index.html missing and -SkipFrontendBuild was set"
    }
    Write-Host "  using existing web/dist"
}

Write-Step "Sync and verify required native Launcher entry"
Sync-NativeLauncherForManagedInstall -SyncScript $SyncLauncher -ProjectRoot $ProjectDir -OutputPath $NativeLauncher

Write-Step "Build and publish managed desktop assistant package"
$ManagedDesktopInstaller = Join-Path $ProjectDir "scripts\install_managed_desktop.py"
Invoke-Native `
    -FilePath $VenvPython `
    -ArgumentList @($ManagedDesktopInstaller, "--project", $ProjectDir, "--apply") `
    -Label "Build and publish managed desktop package"

Write-Step "Refresh the canonical desktop Launcher shortcut"
. (Join-Path $ProjectDir "scripts\desktop_entry_catalog.ps1")
$catalog = Assert-DesktopEntryCatalog -ProjectDir $ProjectDir
$desktopEntry = Resolve-DesktopPublicEntryPath -Catalog $catalog -ProjectDir $ProjectDir
$shortcutShell = New-Object -ComObject WScript.Shell
$null = Set-VibelutionDesktopLauncherShortcut -Shell $shortcutShell -ProjectDir $ProjectDir `
    -TargetPath $desktopEntry -Arguments ('--workspace "{0}"' -f $ProjectDir) `
    -IconPath (Join-Path $ProjectDir "assets\icons\vibelution.ico")

$configHome = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Vibelution\config"
Write-Host ""
Write-Host "Install finished." -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "  1. Configure models/keys in: $configHome\config.toml"
Write-Host "     (created on first Launcher start if missing)"
Write-Host "  2. Start:"
Write-Host "       Desktop shortcut: Vibelution Launcher"
Write-Host "       or: $NativeLauncher --project `"$ProjectDir`" start"
Write-Host "       Independent assistant: $NativeLauncher --assistant"
Write-Host "  3. Guide: docs\guides\install-windows.md"
Write-Host ""
if (Test-Path -LiteralPath $VenvPythonw) {
    Write-Host "Runtime pythonw: $VenvPythonw"
}

if ($Start) {
    Write-Step "Start Launcher"
    if (-not $NativeLauncher -or -not (Test-Path -LiteralPath $NativeLauncher)) {
        throw "Native Launcher missing after sync: $NativeLauncher"
    }
    Invoke-Native `
        -FilePath $NativeLauncher `
        -ArgumentList @("--project", $ProjectDir, "start") `
        -Label "VibelutionLauncher.exe --project <root> start"
}
