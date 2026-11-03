# Hardening tests for scripts/install_windows.ps1 (installer lane).
# Runs under Windows PowerShell 5.1, no Pester dependency: prints PASS/FAIL
# lines and exits non-zero when anything fails. The installer's pure logic is
# extracted verbatim from the real script via the language parser AST, so
# these tests exercise the shipped code, not a copy. External effects (VS
# install, electron download) are mocked with throwaway .cmd fixtures.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$InstallerPath = Join-Path $RepoRoot "scripts\install_windows.ps1"

$script:Passed = 0
$script:Failed = 0

function Assert-True {
    param([string]$Name, [bool]$Condition, [string]$Detail = "")
    if ($Condition) {
        $script:Passed++
        Write-Host "  PASS $Name" -ForegroundColor Green
    } else {
        $script:Failed++
        Write-Host "  FAIL $Name $Detail" -ForegroundColor Red
    }
}

function Expect-Throw {
    param([string]$Name, [scriptblock]$Block, [string[]]$MustContain = @())
    $threw = $false
    $message = ""
    try {
        $null = & $Block
    } catch {
        $threw = $true
        $message = [string]$_.Exception.Message
    }
    $missing = @($MustContain | Where-Object { $message -notlike "*$_*" })
    Assert-True -Name $Name -Condition ($threw -and $missing.Count -eq 0) `
        -Detail "(threw=$threw; missing=[$($missing -join ' | ')])"
}

function Expect-NoThrow {
    param([string]$Name, [scriptblock]$Block)
    try {
        $null = & $Block
        Assert-True -Name $Name -Condition $true
    } catch {
        Assert-True -Name $Name -Condition $false -Detail "(unexpected: $($_.Exception.Message))"
    }
}

function New-TempDir {
    $path = Join-Path ([IO.Path]::GetTempPath()) ("vibelution-installer-tests-" + [Guid]::NewGuid().ToString("N"))
    $null = New-Item -ItemType Directory -Path $path -Force
    return $path
}

function Set-FileWriteTimeUtc {
    param([string]$Path, [datetime]$Time)
    $item = Get-Item -LiteralPath $Path -Force
    $item.LastWriteTimeUtc = $Time
}

function New-FixtureCmd {
    param([string]$Path, [string[]]$Lines)
    Set-Content -LiteralPath $Path -Value (($Lines -join "`r`n") + "`r`n") -Encoding Ascii
}

Write-Host "== install_windows.ps1 hardening harness =="

# --- Parser gate -----------------------------------------------------------
Write-Host "-- Parser gate --"
$parseTokens = $null
$parseErrors = $null
$null = [System.Management.Automation.Language.Parser]::ParseFile($InstallerPath, [ref]$parseTokens, [ref]$parseErrors)
$parseErrorLines = @($parseErrors | ForEach-Object { "$($_.Extent.StartLineNumber): $($_.Message)" })
Assert-True -Name "installer parses with zero errors" -Condition (@($parseErrors).Count -eq 0) `
    -Detail "(errors: $($parseErrorLines -join '; '))"

# --- Extract the real functions under test from the installer --------------
$wantedFunctions = @("Invoke-Native", "Ensure-ElectronBinary", "Get-RuntimeRequirementLines", "Test-FrontendDistFresh", "Assert-VsCppBuildToolchain")
$ast = [System.Management.Automation.Language.Parser]::ParseFile($InstallerPath, [ref]$parseTokens, [ref]$parseErrors)
$definitions = @($ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $wantedFunctions -contains $node.Name }, $true))
Assert-True -Name "all target functions extractable" -Condition ($definitions.Count -eq $wantedFunctions.Count) `
    -Detail "(found: $($definitions | ForEach-Object { $_.Name }))"
foreach ($definition in $definitions) {
    Invoke-Expression $definition.Extent.Text
}

$tempRoot = New-TempDir
try {
    # --- Get-RuntimeRequirementLines ---------------------------------------
    Write-Host "-- Get-RuntimeRequirementLines --"
    $reqPath = Join-Path $tempRoot "requirements.txt"
    $fixture = @(
        "# AgentRuntime deps",
        "",
        "# 核心依赖",
        "requests>=2.28.0",
        "tiktoken>=0.7.0            # Token 计数",
        "regex==2026.5.9",
        'pywinpty>=3.0.5; platform_system == "Windows"  # ConPTY',
        "",
        "# LangChain 依赖",
        "litellm>=1.96.0,<2.0",
        "",
        "# 开发/测试依赖",
        "pytest>=7.0.0            # 单元测试框架",
        "ruff>=0.6.0",
        ""
    ) -join "`r`n"
    [IO.File]::WriteAllText($reqPath, $fixture, (New-Object System.Text.UTF8Encoding($true)))
    $lines = @(Get-RuntimeRequirementLines -RequirementsPath $reqPath)
    Assert-True -Name "keeps only pre-boundary runtime lines" -Condition ($lines.Count -eq 5) `
        -Detail "(got: $($lines -join ' ;; '))"
    Assert-True -Name "strips inline comments" -Condition (@($lines | Where-Object { $_ -eq "tiktoken>=0.7.0" }).Count -eq 1)
    Assert-True -Name "keeps environment markers intact" -Condition (@($lines | Where-Object { $_ -like 'pywinpty>=3.0.5; platform_system == "Windows"' }).Count -eq 1)
    Assert-True -Name "drops dev/test dependencies" -Condition (@($lines | Where-Object { $_ -match '^(pytest|ruff)' }).Count -eq 0)

    $noBomPath = Join-Path $tempRoot "requirements-nobom.txt"
    [IO.File]::WriteAllText($noBomPath, $fixture, (New-Object System.Text.UTF8Encoding($false)))
    $noBomLines = @(Get-RuntimeRequirementLines -RequirementsPath $noBomPath)
    Assert-True -Name "works without BOM" -Condition ($noBomLines.Count -eq 5)

    # Single runtime line must still arrive as a flat 1-element array (the
    # installer splices the result into the pip argument list with @()).
    $singlePath = Join-Path $tempRoot "single.txt"
    [IO.File]::WriteAllText($singlePath, "requests>=2.28.0`r`n# 开发/测试依赖`r`npytest`r`n", [System.Text.Encoding]::UTF8)
    $singleLines = @(Get-RuntimeRequirementLines -RequirementsPath $singlePath)
    Assert-True -Name "single runtime line is a flat 1-element array" -Condition (
        $singleLines.Count -eq 1 -and $singleLines[0] -is [string] -and $singleLines[0] -eq "requests>=2.28.0")
    $pipArgs = @("-m", "pip", "install") + @(Get-RuntimeRequirementLines -RequirementsPath $reqPath)
    Assert-True -Name "pip argument splice stays flat" -Condition (
        $pipArgs.Count -eq 8 -and @($pipArgs | Where-Object { $_ -isnot [string] }).Count -eq 0)

    $noBoundaryPath = Join-Path $tempRoot "no-boundary.txt"
    [IO.File]::WriteAllText($noBoundaryPath, "requests>=2.28.0`r`n", [System.Text.Encoding]::UTF8)
    Assert-True -Name "missing boundary fail-opens to null" -Condition ($null -eq (Get-RuntimeRequirementLines -RequirementsPath $noBoundaryPath))

    $emptyRuntimePath = Join-Path $tempRoot "empty-runtime.txt"
    [IO.File]::WriteAllText($emptyRuntimePath, "# 开发/测试依赖`r`npytest>=7.0.0`r`n", [System.Text.Encoding]::UTF8)
    Assert-True -Name "empty runtime section fail-opens to null" -Condition ($null -eq (Get-RuntimeRequirementLines -RequirementsPath $emptyRuntimePath))
    Assert-True -Name "unreadable file fail-opens to null" -Condition ($null -eq (Get-RuntimeRequirementLines -RequirementsPath (Join-Path $tempRoot "does-not-exist.txt")))

    $repoLines = @(Get-RuntimeRequirementLines -RequirementsPath (Join-Path $RepoRoot "requirements.txt"))
    Assert-True -Name "real requirements: dev/test deps excluded" -Condition (
        $repoLines.Count -gt 0 -and @($repoLines | Where-Object { $_ -match '^(pytest|pytest-|coverage|ruff|jedi)\b' }).Count -eq 0)
    Assert-True -Name "real requirements: core runtime deps kept" -Condition (
        (@($repoLines | Where-Object { $_ -like 'requests>=*' }).Count -ge 1) -and
        (@($repoLines | Where-Object { $_ -like 'litellm*' }).Count -ge 1))
    Assert-True -Name "real requirements: marker lines preserved" -Condition (
        @($repoLines | Where-Object { $_ -like 'pywinpty>*' -and $_ -like '*platform_system*' }).Count -eq 1)

    # --- Test-FrontendDistFresh --------------------------------------------
    Write-Host "-- Test-FrontendDistFresh --"
    $webRoot = Join-Path $tempRoot "web"
    $distDir = Join-Path $webRoot "dist"
    $srcDir = Join-Path $webRoot "src"
    $null = New-Item -ItemType Directory -Path $srcDir -Force
    $null = New-Item -ItemType Directory -Path $distDir -Force
    $distIndex = Join-Path $distDir "index.html"
    $sourceFile = Join-Path $srcDir "main.ts"
    Set-Content -LiteralPath $sourceFile -Value "export {}" -Encoding Ascii
    Set-Content -LiteralPath $distIndex -Value "<html></html>" -Encoding Ascii
    $now = (Get-Date).ToUniversalTime()
    Set-FileWriteTimeUtc -Path $sourceFile -Time $now.AddMinutes(-30)
    Set-FileWriteTimeUtc -Path $distIndex -Time $now.AddMinutes(-5)
    Assert-True -Name "fresh dist reuses" -Condition (Test-FrontendDistFresh -WebRoot $webRoot -DistIndex $distIndex)

    Set-FileWriteTimeUtc -Path $sourceFile -Time $now.AddMinutes(-1)
    Assert-True -Name "newer source triggers rebuild" -Condition (-not (Test-FrontendDistFresh -WebRoot $webRoot -DistIndex $distIndex))
    Set-FileWriteTimeUtc -Path $sourceFile -Time $now.AddMinutes(-30)

    $staleCandidates = @(
        (Join-Path $webRoot "node_modules\vite\chunk.js"),
        (Join-Path $webRoot ".vibelution-builds\cache\asset.bin"),
        (Join-Path $webRoot "public\dist\logo.svg")
    )
    foreach ($staleCandidate in $staleCandidates) {
        $null = New-Item -ItemType Directory -Path (Split-Path -Parent $staleCandidate) -Force
        Set-Content -LiteralPath $staleCandidate -Value "x" -Encoding Ascii
        Set-FileWriteTimeUtc -Path $staleCandidate -Time $now.AddMinutes(-1)
    }
    Assert-True -Name "node_modules/.vibelution-builds/nested dist ignored" -Condition (Test-FrontendDistFresh -WebRoot $webRoot -DistIndex $distIndex)

    # A junction inside web pointing at a newer tree must not count as source
    # (and must not recurse forever when it points back into web itself).
    $junctionTarget = Join-Path $tempRoot "outside-tree"
    $null = New-Item -ItemType Directory -Path $junctionTarget -Force
    $junctionNewer = Join-Path $junctionTarget "newer.ts"
    Set-Content -LiteralPath $junctionNewer -Value "export {}" -Encoding Ascii
    Set-FileWriteTimeUtc -Path $junctionNewer -Time $now.AddMinutes(-1)
    $junctionPath = Join-Path $webRoot "linked"
    $junctionCreated = $false
    try {
        $null = New-Item -ItemType Junction -Path $junctionPath -Target $junctionTarget -ErrorAction Stop
        $junctionCreated = $true
    } catch {
        Write-Host "  SKIP junction fixture unavailable: $($_.Exception.Message)"
    }
    if ($junctionCreated) {
        $selfLoop = Join-Path $webRoot "src\loop"
        $null = New-Item -ItemType Junction -Path $selfLoop -Target $webRoot -ErrorAction SilentlyContinue
        Assert-True -Name "junctions/reparse points skipped (no newer source, no loop)" -Condition (Test-FrontendDistFresh -WebRoot $webRoot -DistIndex $distIndex)
        if (Test-Path -LiteralPath $selfLoop) { [IO.Directory]::Delete($selfLoop) }
        [IO.Directory]::Delete($junctionPath)
    }

    $distBackup = Join-Path $tempRoot "index.bak.html"
    Move-Item -LiteralPath $distIndex -Destination $distBackup
    Assert-True -Name "missing dist rebuilds" -Condition (-not (Test-FrontendDistFresh -WebRoot $webRoot -DistIndex $distIndex))
    Move-Item -LiteralPath $distBackup -Destination $distIndex

    $emptyWeb = Join-Path $tempRoot "empty-web"
    $emptyDist = Join-Path $emptyWeb "dist"
    $null = New-Item -ItemType Directory -Path $emptyDist -Force
    $emptyIndex = Join-Path $emptyDist "index.html"
    Set-Content -LiteralPath $emptyIndex -Value "<html></html>" -Encoding Ascii
    Set-FileWriteTimeUtc -Path $emptyIndex -Time $now
    Assert-True -Name "no sources at all -> rebuild" -Condition (-not (Test-FrontendDistFresh -WebRoot $emptyWeb -DistIndex $emptyIndex))

    # --- Ensure-ElectronBinary (mocked node) ---------------------------------
    Write-Host "-- Ensure-ElectronBinary --"
    $desktopDir = Join-Path $tempRoot "desktop\electron"
    $electronModule = Join-Path $desktopDir "node_modules\electron"
    $null = New-Item -ItemType Directory -Path (Join-Path $electronModule "dist") -Force
    $electronExe = Join-Path $electronModule "dist\electron.exe"
    Set-Content -LiteralPath $electronExe -Value "stub" -Encoding Ascii

    $markerPath = Join-Path $tempRoot "node-ran.marker"
    $fakeNodeMarker = Join-Path $tempRoot "fake_node_marker.cmd"
    New-FixtureCmd -Path $fakeNodeMarker -Lines @("@echo off", "type NUL > `"$markerPath`"", "exit /b 0")
    Expect-NoThrow -Name "electron.exe present short-circuits" `
        -Block { Ensure-ElectronBinary -DesktopDir $desktopDir -NodeExecutable $fakeNodeMarker }
    Assert-True -Name "node not invoked when binary present" -Condition (-not (Test-Path -LiteralPath $markerPath))

    Remove-Item -LiteralPath $electronExe -Force
    Set-Content -LiteralPath (Join-Path $electronModule "install.js") -Value "// stub installer" -Encoding Ascii
    $fakeNodeCreate = Join-Path $tempRoot "fake_node_create.cmd"
    New-FixtureCmd -Path $fakeNodeCreate -Lines @(
        "@echo off",
        "if not exist `"node_modules\electron\install.js`" exit /b 9",
        "mkdir `"node_modules\electron\dist`" 2>nul",
        "type NUL > `"node_modules\electron\dist\electron.exe`"",
        "exit /b 0"
    )
    Expect-NoThrow -Name "fallback runs electron/install.js" `
        -Block { Ensure-ElectronBinary -DesktopDir $desktopDir -NodeExecutable $fakeNodeCreate }
    Assert-True -Name "fallback produced electron.exe" -Condition (Test-Path -LiteralPath $electronExe)

    Remove-Item -LiteralPath $electronExe -Force
    $fakeNodeTimeout = Join-Path $tempRoot "fake_node_timeout.cmd"
    New-FixtureCmd -Path $fakeNodeTimeout -Lines @("@echo off", "ping -n 6 127.0.0.1 >nul", "exit /b 0")
    Expect-Throw -Name "bounded run times out" `
        -Block { Ensure-ElectronBinary -DesktopDir $desktopDir -NodeExecutable $fakeNodeTimeout -TimeoutSeconds 2 } `
        -MustContain @("timed out")

    $fakeNodeFail = Join-Path $tempRoot "fake_node_fail.cmd"
    New-FixtureCmd -Path $fakeNodeFail -Lines @("@echo off", "echo download mirror unreachable 1>&2", "exit /b 3")
    Expect-Throw -Name "fallback failure surfaces self-help with real exit code" `
        -Block { Ensure-ElectronBinary -DesktopDir $desktopDir -NodeExecutable $fakeNodeFail } `
        -MustContain @("electron binary download failed", "exit code 3", "ELECTRON_MIRROR", "npm rebuild electron")

    Remove-Item -LiteralPath (Join-Path $electronModule "install.js") -Force
    Expect-Throw -Name "missing installer message is actionable" `
        -Block { Ensure-ElectronBinary -DesktopDir $desktopDir -NodeExecutable $fakeNodeCreate } `
        -MustContain @("installer not found", "npm ci")

    # --- Assert-VsCppBuildToolchain (mocked vswhere) -------------------------
    Write-Host "-- Assert-VsCppBuildToolchain --"
    Expect-Throw -Name "missing vswhere -> actionable error" `
        -Block { Assert-VsCppBuildToolchain -VswherePath (Join-Path $tempRoot "no-such-vswhere.exe") } `
        -MustContain @("winget install --id Microsoft.VisualStudio.2022.BuildTools", "workbench_job.node", "docs\guides\install-windows.md")

    $vswhereEmpty = Join-Path $tempRoot "vswhere_empty.cmd"
    New-FixtureCmd -Path $vswhereEmpty -Lines @("@echo off", "exit /b 0")
    Expect-Throw -Name "no VC tools -> actionable error" `
        -Block { Assert-VsCppBuildToolchain -VswherePath $vswhereEmpty } `
        -MustContain @("winget install --id Microsoft.VisualStudio.2022.BuildTools", "Desktop development with C++")

    $vswhereOk = Join-Path $tempRoot "vswhere_ok.cmd"
    New-FixtureCmd -Path $vswhereOk -Lines @("@echo off", "echo C:\Program Files\Microsoft Visual Studio\2022\BuildTools", "exit /b 0")
    Expect-NoThrow -Name "vswhere with VC tools passes" `
        -Block { Assert-VsCppBuildToolchain -VswherePath $vswhereOk }
} finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# --- Installer source contract ---------------------------------------------
Write-Host "-- Installer source contract --"
$source = [IO.File]::ReadAllText($InstallerPath)
Assert-True -Name "Node gate raised to 22.12" -Condition (
    $source.Contains("Node.js 22.12+ is required") -and (-not $source.Contains("-lt 18")))
Assert-True -Name "electron fallback wired into dependency step" -Condition (
    $source.Contains('Ensure-ElectronBinary -DesktopDir $DesktopDir') -and
    $source.Contains("node_modules\electron\dist\electron.exe"))
Assert-True -Name "VS precheck uses required component id" -Condition (
    $source.Contains("Microsoft.VisualStudio.Component.VC.Tools.x86.x64") -and
    $source.Contains("winget install --id Microsoft.VisualStudio.2022.BuildTools"))
# Fail-fast: the toolchain check must run in the prerequisites step, before
# any venv/pip/npm work, and before the managed package build that needs it.
$vsCallIndex = $source.IndexOf("`nAssert-VsCppBuildToolchain")
$venvStepIndex = $source.IndexOf('Write-Step "Create / reuse project virtualenv"')
$managedBuildIndex = $source.IndexOf('Write-Step "Build and publish managed desktop assistant package"')
Assert-True -Name "VS precheck runs in prerequisites (before venv and managed build)" -Condition (
    $vsCallIndex -ge 0 -and $venvStepIndex -gt $vsCallIndex -and $managedBuildIndex -gt $vsCallIndex)
Assert-True -Name "runtime-only pip install with fail-open fallback" -Condition (
    $source.Contains("installing runtime dependencies only") -and
    $source.Contains("Write-Warning") -and
    $source.Contains('"-r", $Requirements'))
Assert-True -Name "dist reuse plus ForceFrontendBuild switch" -Condition (
    $source.Contains("web/dist is fresh — reuse") -and
    $source.Contains('[switch]$ForceFrontendBuild'))

# Existing repo contract: shortcut owner must stay after managed publication.
$publishedIndex = $source.IndexOf('-Label "Build and publish managed desktop package"')
$shortcutIndex = $source.IndexOf('$null = Set-VibelutionDesktopLauncherShortcut')
Assert-True -Name "shortcut owner stays after managed publication" -Condition (
    $publishedIndex -ge 0 -and $shortcutIndex -gt $publishedIndex -and (-not $source.Contains("CreateShortcut")))

Write-Host ""
Write-Host "Passed: $script:Passed  Failed: $script:Failed"
if ($script:Failed -gt 0) {
    exit 1
}
exit 0
