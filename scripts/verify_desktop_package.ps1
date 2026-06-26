param(
    [switch]$SkipBuild,
    [switch]$AllowRunningDesktop,
    [switch]$SkipResidualProcessCheck,
    [int]$SmokeTimeoutSeconds = 90,
    [int]$ResidualWaitSeconds = 10
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$buildScript = Join-Path $projectDir "scripts/build_desktop_package.ps1"
$desktopResourcesDir = Join-Path $projectDir "dist/desktop/win-unpacked/resources"
$desktopExe = Join-Path $projectDir "dist/desktop/win-unpacked/Vibelution.exe"
$desktopIconPath = Join-Path $projectDir "assets/icons/vibelution.ico"
$launchProfilePath = Join-Path $desktopResourcesDir "vibelution-launch-profile.json"
$summaryPath = Join-Path $projectDir ".runtime/launcher/electron-smoke-summary.json"

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

function Read-JsonFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Required JSON file is missing: $Path"
    }
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

function Get-DesktopPackageProcesses {
    if (-not (Test-Path -LiteralPath $desktopExe)) {
        return @()
    }

    $resolvedDesktopExe = (Resolve-Path -LiteralPath $desktopExe).Path
    return @(
        Get-CimInstance Win32_Process |
            Where-Object { $_.ExecutablePath -eq $resolvedDesktopExe }
    )
}

function Format-DesktopProcessList {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Processes
    )

    return ($Processes | ForEach-Object { "$($_.ProcessId): $($_.CommandLine)" }) -join "`n"
}

function Assert-NoDesktopPackageProcesses {
    if ($AllowRunningDesktop) {
        return
    }

    $processes = @(Get-DesktopPackageProcesses)
    if ($processes.Count -gt 0) {
        $details = Format-DesktopProcessList $processes
        throw "Vibelution desktop package is already running. Close it before package verification or pass -AllowRunningDesktop. Running processes:`n$details"
    }
}

function Wait-ForNoNewDesktopPackageProcesses {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [int[]]$BaselineProcessIds
    )

    if ($SkipResidualProcessCheck) {
        return
    }

    $deadline = (Get-Date).AddSeconds($ResidualWaitSeconds)
    do {
        $newProcesses = @(
            Get-DesktopPackageProcesses |
                Where-Object { $BaselineProcessIds -notcontains [int]$_.ProcessId }
        )
        if ($newProcesses.Count -eq 0) {
            return
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)

    $details = Format-DesktopProcessList $newProcesses
    throw "Desktop smoke left new Vibelution.exe processes running:`n$details"
}

function Get-IconBitmapHash {
    param(
        [Parameter(Mandatory = $true)]
        [System.Drawing.Icon]$Icon
    )

    $bitmap = $null
    $stream = $null
    $sha256 = $null
    try {
        $bitmap = $Icon.ToBitmap()
        $stream = New-Object System.IO.MemoryStream
        $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
        $sha256 = [System.Security.Cryptography.SHA256]::Create()
        return ([System.BitConverter]::ToString($sha256.ComputeHash($stream.ToArray())) -replace "-", "").ToLowerInvariant()
    } finally {
        if ($sha256) {
            $sha256.Dispose()
        }
        if ($stream) {
            $stream.Dispose()
        }
        if ($bitmap) {
            $bitmap.Dispose()
        }
    }
}

function Assert-DesktopExeIcon {
    if (-not (Test-Path -LiteralPath $desktopIconPath)) {
        throw "Shared Vibelution icon is missing: $desktopIconPath"
    }

    Add-Type -AssemblyName System.Drawing
    $extractedIcon = $null
    $sharedIcon = $null
    try {
        $extractedIcon = [System.Drawing.Icon]::ExtractAssociatedIcon($desktopExe)
        if ($null -eq $extractedIcon) {
            throw "Unable to extract desktop package executable icon: $desktopExe"
        }
        $sharedIcon = [System.Drawing.Icon]::ExtractAssociatedIcon($desktopIconPath)
        if ($null -eq $sharedIcon) {
            throw "Unable to extract shared Vibelution icon: $desktopIconPath"
        }
        $executableIconHash = Get-IconBitmapHash $extractedIcon
        $sharedIconHash = Get-IconBitmapHash $sharedIcon
        if ($executableIconHash -ne $sharedIconHash) {
            throw "Desktop package executable icon does not match shared Vibelution icon."
        }
    } finally {
        if ($sharedIcon) {
            $sharedIcon.Dispose()
        }
        if ($extractedIcon) {
            $extractedIcon.Dispose()
        }
    }
}

function Assert-LaunchProfile {
    $bytes = [System.IO.File]::ReadAllBytes($launchProfilePath)
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xef -and $bytes[1] -eq 0xbb -and $bytes[2] -eq 0xbf) {
        throw "Launch profile must be UTF-8 without BOM: $launchProfilePath"
    }

    $profile = Read-JsonFile $launchProfilePath
    if ($profile.schemaVersion -ne 1) {
        throw "Launch profile schemaVersion must be 1."
    }
    if ((Resolve-Path -LiteralPath $profile.workspaceRoot).Path -ne $projectDir) {
        throw "Launch profile workspaceRoot does not match project root."
    }
    if (-not [string]::IsNullOrWhiteSpace([string]$profile.operatorConfigPath) -and -not (Test-Path -LiteralPath $profile.operatorConfigPath)) {
        Write-Warning "Operator config path is not present yet: $($profile.operatorConfigPath)"
    }
    if ([string]::IsNullOrWhiteSpace([string]$profile.pythonPath) -or -not (Test-Path -LiteralPath $profile.pythonPath)) {
        throw "Launch profile pythonPath is missing or does not exist."
    }
    return $profile
}

function Assert-SmokeSummary {
    $summary = Read-JsonFile $summaryPath
    if ($summary.schemaVersion -ne 1) {
        throw "Smoke summary schemaVersion must be 1."
    }
    if ($summary.mode -ne "electron_package_smoke") {
        throw "Smoke summary mode must be electron_package_smoke."
    }
    if ((Resolve-Path -LiteralPath $summary.workspaceRoot).Path -ne $projectDir) {
        throw "Smoke summary workspaceRoot does not match project root."
    }
    if ($summary.bootstrap.attempted -ne $true) {
        throw "Electron package smoke did not attempt Launcher bootstrap."
    }
    if ($summary.bootstrap.parsed -ne $true) {
        throw "Electron package smoke did not parse Launcher bootstrap."
    }
    if ($summary.shutdown.attempted -ne $true) {
        throw "Electron package smoke did not run the desktop shutdown path."
    }
    if ($summary.bootstrap.mode -eq "started") {
        if ($summary.shutdown.stopStatus -ne "stopped") {
            throw "Electron package smoke started an owned Launcher but did not stop it. Stop status: $($summary.shutdown.stopStatus)"
        }
        if ([int]$summary.shutdown.stoppedPidCount -lt 1) {
            throw "Electron package smoke reported no stopped Launcher processes."
        }
    }
    return $summary
}

Assert-NoDesktopPackageProcesses

if (-not $SkipBuild) {
    Invoke-CheckedNative powershell @("-ExecutionPolicy", "Bypass", "-File", $buildScript)
}

if (-not (Test-Path -LiteralPath $desktopExe)) {
    throw "Desktop package executable is missing: $desktopExe"
}

Assert-DesktopExeIcon
$profile = Assert-LaunchProfile
$baselineProcessIds = @((Get-DesktopPackageProcesses | ForEach-Object { [int]$_.ProcessId }))

Remove-Item -LiteralPath $summaryPath -Force -ErrorAction SilentlyContinue
$smokeProcess = Start-Process -FilePath $desktopExe -ArgumentList @("--smoke") -PassThru
if (-not $smokeProcess.WaitForExit($SmokeTimeoutSeconds * 1000)) {
    throw "Electron package smoke timed out after $SmokeTimeoutSeconds seconds. Smoke process id: $($smokeProcess.Id)"
}
if ($smokeProcess.ExitCode -ne 0) {
    throw "Electron package smoke exited with code $($smokeProcess.ExitCode)."
}

$summary = Assert-SmokeSummary
Wait-ForNoNewDesktopPackageProcesses $baselineProcessIds

[ordered]@{
    schemaVersion = 1
    ok = $true
    desktopExe = $desktopExe
    launchProfilePath = $launchProfilePath
    smokeSummaryPath = $summaryPath
    workspaceRoot = $profile.workspaceRoot
    operatorConfigPath = $summary.operatorConfigPath
    bootstrapMode = $summary.bootstrap.mode
    shutdownStopStatus = $summary.shutdown.stopStatus
    shutdownStoppedPidCount = $summary.shutdown.stoppedPidCount
    launcherOrigin = $summary.bootstrap.launcherOrigin
    workbenchOrigin = $summary.bootstrap.workbenchOrigin
} | ConvertTo-Json -Depth 4
