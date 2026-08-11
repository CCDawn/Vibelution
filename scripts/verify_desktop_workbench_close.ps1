param(
    [switch]$SkipPackageVerification,
    [int]$StartTimeoutSeconds = 45,
    [int]$TransactionTimeoutSeconds = 60,
    [int]$ShutdownTimeoutSeconds = 15
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$entryCatalogScript = Join-Path $projectDir "scripts/desktop_entry_catalog.ps1"
. $entryCatalogScript
$entryCatalog = Assert-DesktopEntryCatalog -ProjectDir $projectDir
$packageVerifier = Join-Path $projectDir "scripts/verify_desktop_package.ps1"
$desktopExe = Resolve-DesktopPublicEntryPath -Catalog $entryCatalog -ProjectDir $projectDir
$canaryUserDataRoot = Join-Path $projectDir ".runtime/electron-workbench-close-canary-user-data"
$canarySummaryPath = Join-Path $projectDir ".runtime/launcher/electron-workbench-close-canary-summary.json"
$workbenchWindowTitle = "Vibelution Workbench"
$WM_CLOSE = [uint32]0x0010

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

function Get-AllVibelutionDesktopProcesses {
    return @(
        Get-CimInstance Win32_Process |
            Where-Object { $_.Name -eq "Vibelution.exe" }
    )
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

function Get-RootDesktopProcesses {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [object[]]$Processes
    )

    $processIds = @($Processes | ForEach-Object { [int]$_.ProcessId })
    return @(
        $Processes |
            Where-Object { $processIds -notcontains [int]$_.ParentProcessId }
    )
}

function Format-DesktopProcessList {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [object[]]$Processes
    )

    if ($Processes.Count -eq 0) {
        return "(none)"
    }
    return ($Processes | ForEach-Object { "$($_.ProcessId): $($_.CommandLine)" }) -join "`n"
}

function Assert-NoOtherVibelutionDesktopProcesses {
    $processes = @(Get-AllVibelutionDesktopProcesses)
    if ($processes.Count -gt 0) {
        $details = Format-DesktopProcessList $processes
        throw "Another Vibelution desktop package is already running. Close it before Workbench-close verification. Running processes:`n$details"
    }
}

function Assert-NoActiveWorkbenchWork {
    $launcherStatePath = Join-Path $projectDir ".runtime/launcher/state.json"
    if (-not (Test-Path -LiteralPath $launcherStatePath)) {
        throw "Launcher state is unavailable; refusing to run a Workbench-close canary without an active-work check."
    }
    $launcherState = Get-Content -LiteralPath $launcherStatePath -Raw | ConvertFrom-Json
    $launcherControlUrl = [string]$launcherState.launcherControlUrl
    if ([string]::IsNullOrWhiteSpace($launcherControlUrl)) {
        throw "Launcher control URL is unavailable; refusing to run a Workbench-close canary without an active-work check."
    }
    $launcherOrigin = ([uri]$launcherControlUrl).GetLeftPart([System.UriPartial]::Authority)
    $status = Invoke-RestMethod -Uri "$launcherOrigin/api/launcher/status"
    $activeWorkCount = [int]$status.lifecycleProof.activeWorkRuns.count
    if ($activeWorkCount -gt 0) {
        throw "Active work blocks the Workbench-close canary. Complete or stop the active work before retrying."
    }
    return $activeWorkCount
}

function Wait-ForDesktopRootProcess {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [int[]]$BaselineProcessIds
    )

    $deadline = (Get-Date).AddSeconds($StartTimeoutSeconds)
    do {
        $newProcesses = @(
            Get-DesktopPackageProcesses |
                Where-Object { $BaselineProcessIds -notcontains [int]$_.ProcessId }
        )
        $roots = @(Get-RootDesktopProcesses $newProcesses)
        if ($roots.Count -gt 0) {
            return $roots[0]
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)

    $details = Format-DesktopProcessList @(Get-DesktopPackageProcesses)
    throw "Timed out waiting for the desktop package root process. Running processes:`n$details"
}

function Initialize-NativeWindowApi {
    if ("Vibelution.DesktopCanary.NativeWindowApi" -as [type]) {
        return
    }
    Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;

namespace Vibelution.DesktopCanary {
    public static class NativeWindowApi {
        public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool IsWindowVisible(IntPtr hWnd);

        [DllImport("user32.dll", SetLastError = true)]
        public static extern int GetWindowTextLength(IntPtr hWnd);

        [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int maxCount);

        [DllImport("user32.dll", SetLastError = true)]
        public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool PostMessage(IntPtr hWnd, uint message, IntPtr wParam, IntPtr lParam);
    }
}
"@
}

function Get-WorkbenchNativeWindows {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [int[]]$OwnedProcessIds
    )

    Initialize-NativeWindowApi
    $matches = [System.Collections.Generic.List[object]]::new()
    $callback = [Vibelution.DesktopCanary.NativeWindowApi+EnumWindowsProc] {
        param([IntPtr]$Handle, [IntPtr]$Ignored)

        if (-not [Vibelution.DesktopCanary.NativeWindowApi]::IsWindowVisible($Handle)) {
            return $true
        }
        [uint32]$processId = 0
        $null = [Vibelution.DesktopCanary.NativeWindowApi]::GetWindowThreadProcessId($Handle, [ref]$processId)
        if ($OwnedProcessIds -notcontains [int]$processId) {
            return $true
        }
        $textLength = [Vibelution.DesktopCanary.NativeWindowApi]::GetWindowTextLength($Handle)
        if ($textLength -le 0) {
            return $true
        }
        $titleBuilder = [System.Text.StringBuilder]::new($textLength + 1)
        $null = [Vibelution.DesktopCanary.NativeWindowApi]::GetWindowText($Handle, $titleBuilder, $titleBuilder.Capacity)
        if ($titleBuilder.ToString() -eq $workbenchWindowTitle) {
            $matches.Add([pscustomobject]@{
                Handle = $Handle
                ProcessId = [int]$processId
                Title = $titleBuilder.ToString()
            })
        }
        return $true
    }
    $null = [Vibelution.DesktopCanary.NativeWindowApi]::EnumWindows($callback, [IntPtr]::Zero)
    return @($matches)
}

function Wait-ForWorkbenchNativeWindow {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [int[]]$OwnedProcessIds
    )

    $deadline = (Get-Date).AddSeconds($StartTimeoutSeconds)
    do {
        $matches = @(Get-WorkbenchNativeWindows $OwnedProcessIds)
        if ($matches.Count -eq 1) {
            return $matches[0]
        }
        if ($matches.Count -gt 1) {
            throw "Workbench-close canary found more than one named Workbench window."
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    throw "Timed out waiting for the named Workbench native window."
}

function Wait-ForNoWorkbenchNativeWindow {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [int[]]$OwnedProcessIds
    )

    $deadline = (Get-Date).AddSeconds($TransactionTimeoutSeconds)
    do {
        if (@(Get-WorkbenchNativeWindows $OwnedProcessIds).Count -eq 0) {
            return
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    throw "Workbench native window remained open after its close transaction completed."
}

function Wait-ForWorkbenchCloseCanarySummary {
    $deadline = (Get-Date).AddSeconds($TransactionTimeoutSeconds)
    do {
        if (Test-Path -LiteralPath $canarySummaryPath) {
            $summary = Get-Content -LiteralPath $canarySummaryPath -Raw | ConvertFrom-Json
            if ($summary.phase -eq "succeeded") {
                return $summary
            }
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    throw "Timed out waiting for the Electron Workbench-close transaction acknowledgement."
}

function Request-OwnedDesktopClose {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [int[]]$OwnedProcessIds
    )

    $currentProcesses = @(
        Get-DesktopPackageProcesses |
            Where-Object { $OwnedProcessIds -contains [int]$_.ProcessId }
    )
    $requestedCount = 0
    foreach ($process in @(Get-RootDesktopProcesses $currentProcesses)) {
        try {
            $desktopProcess = Get-Process -Id ([int]$process.ProcessId) -ErrorAction Stop
            if ($desktopProcess.CloseMainWindow()) {
                $requestedCount += 1
            }
        } catch {
            Write-Warning "Unable to request normal Electron close for process $($process.ProcessId): $($_.Exception.Message)"
        }
    }
    return $requestedCount
}

function Stop-OwnedDesktopProcesses {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [int[]]$OwnedProcessIds
    )

    $currentProcesses = @(
        Get-DesktopPackageProcesses |
            Where-Object { $OwnedProcessIds -contains [int]$_.ProcessId }
    )
    foreach ($process in ($currentProcesses | Sort-Object -Property ProcessId -Descending)) {
        Stop-Process -Id ([int]$process.ProcessId) -Force -ErrorAction SilentlyContinue
    }
}

function Wait-ForNoOwnedDesktopProcesses {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [int[]]$OwnedProcessIds
    )

    $deadline = (Get-Date).AddSeconds($ShutdownTimeoutSeconds)
    do {
        $remaining = @(
            Get-DesktopPackageProcesses |
                Where-Object { $OwnedProcessIds -contains [int]$_.ProcessId }
        )
        if ($remaining.Count -eq 0) {
            return
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)

    $details = Format-DesktopProcessList $remaining
    throw "Timed out waiting for owned desktop package processes to stop:`n$details"
}

function Restore-ManagedWorkbench {
    $launcherExecutable = Join-Path $env:LOCALAPPDATA "Vibelution/Launcher/VibelutionLauncher.exe"
    if (-not (Test-Path -LiteralPath $launcherExecutable)) {
        throw "Official Vibelution Launcher is missing; cannot restore the managed Workbench."
    }
    $launcherProcess = Start-Process -FilePath $launcherExecutable -ArgumentList @("--project", $projectDir, "start") -WindowStyle Hidden -PassThru -Wait
    if ($launcherProcess.ExitCode -ne 0) {
        throw "Official Vibelution Launcher start failed with exit code $($launcherProcess.ExitCode)."
    }
    $launcherStatePath = Join-Path $projectDir ".runtime/launcher/state.json"
    $deadline = (Get-Date).AddSeconds($StartTimeoutSeconds)
    do {
        if (Test-Path -LiteralPath $launcherStatePath) {
            $launcherState = Get-Content -LiteralPath $launcherStatePath -Raw | ConvertFrom-Json
            $launcherControlUrl = [string]$launcherState.launcherControlUrl
            if (-not [string]::IsNullOrWhiteSpace($launcherControlUrl)) {
                $launcherOrigin = ([uri]$launcherControlUrl).GetLeftPart([System.UriPartial]::Authority)
                $status = Invoke-RestMethod -Uri "$launcherOrigin/api/launcher/status"
                if ($status.overallState -eq "ready" -and $status.observedState -eq "open") {
                    return [pscustomobject]@{
                        OverallState = [string]$status.overallState
                        ObservedState = [string]$status.observedState
                    }
                }
            }
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    throw "Workbench-close canary did not restore the managed Workbench."
}

Assert-NoOtherVibelutionDesktopProcesses
$activeWorkCountBeforeCanary = Assert-NoActiveWorkbenchWork
if (-not $SkipPackageVerification) {
    Invoke-CheckedNative powershell @("-ExecutionPolicy", "Bypass", "-File", $packageVerifier)
}
Assert-NoOtherVibelutionDesktopProcesses

if (-not (Test-Path -LiteralPath $desktopExe)) {
    throw "Desktop package executable is missing: $desktopExe"
}

$baselineProcessIds = @()
$ownedProcessIds = @()
$previousDeepLinkRegistration = $env:VIBELUTION_ELECTRON_REGISTER_DEEP_LINKS
$nativeCloseMessagePosted = $false
$recovery = $null

try {
    $env:VIBELUTION_ELECTRON_REGISTER_DEEP_LINKS = "0"
    New-Item -ItemType Directory -Path $canaryUserDataRoot -Force | Out-Null
    Remove-Item -LiteralPath $canarySummaryPath -Force -ErrorAction SilentlyContinue
    $baselineProcessIds = @((Get-DesktopPackageProcesses | ForEach-Object { [int]$_.ProcessId }))
    $startedProcess = Start-Process -FilePath $desktopExe -ArgumentList @(
        "--user-data-dir=$canaryUserDataRoot",
        "--workbench-close-canary"
    ) -PassThru
    $rootProcess = Wait-ForDesktopRootProcess $baselineProcessIds
    $ownedProcessIds = @(
        Get-DesktopPackageProcesses |
            Where-Object { $baselineProcessIds -notcontains [int]$_.ProcessId } |
            ForEach-Object { [int]$_.ProcessId }
        [int]$startedProcess.Id
    ) | Sort-Object -Unique

    $workbenchWindow = Wait-ForWorkbenchNativeWindow $ownedProcessIds
    $activeWorkCount = $activeWorkCountBeforeCanary
    $nativeCloseMessagePosted = [Vibelution.DesktopCanary.NativeWindowApi]::PostMessage(
        $workbenchWindow.Handle,
        $WM_CLOSE,
        [IntPtr]::Zero,
        [IntPtr]::Zero
    )
    if (-not $nativeCloseMessagePosted) {
        throw "Unable to post WM_CLOSE to the named Workbench window."
    }

    $summary = Wait-ForWorkbenchCloseCanarySummary
    if ($summary.schemaVersion -ne 1) {
        throw "Workbench-close canary summary schemaVersion must be 1."
    }
    if ($summary.mode -ne "electron_workbench_close_canary") {
        throw "Workbench-close canary summary mode is invalid: $($summary.mode)"
    }
    if ($summary.phase -ne "succeeded") {
        throw "Workbench-close canary transaction did not succeed: $($summary.phase)"
    }
    if ([string]::IsNullOrWhiteSpace([string]$summary.closeId)) {
        throw "Workbench-close canary summary is missing closeId."
    }
    Wait-ForNoWorkbenchNativeWindow $ownedProcessIds

    $ownedProcessIds = @(
        Get-DesktopPackageProcesses |
            Where-Object { $baselineProcessIds -notcontains [int]$_.ProcessId } |
            ForEach-Object { [int]$_.ProcessId }
        $ownedProcessIds
    ) | Sort-Object -Unique
    $normalCloseRequested = (Request-OwnedDesktopClose $ownedProcessIds) -gt 0
    if (-not $normalCloseRequested) {
        throw "Unable to request normal close for the Electron Workbench-close canary."
    }
    Wait-ForNoOwnedDesktopProcesses $ownedProcessIds
    $recovery = Restore-ManagedWorkbench

    [ordered]@{
        schemaVersion = 1
        ok = $true
        desktopExe = $desktopExe
        firstProcessId = [int]$startedProcess.Id
        firstRootProcessId = [int]$rootProcess.ProcessId
        workbenchWindowTitle = $workbenchWindow.Title
        nativeCloseMessage = "WM_CLOSE"
        nativeCloseMessagePosted = $nativeCloseMessagePosted
        activeWorkCountBeforeClose = $activeWorkCount
        closeId = $summary.closeId
        transactionPhase = $summary.phase
        normalCloseRequested = $normalCloseRequested
        recoveryOverallState = $recovery.OverallState
        recoveryObservedState = $recovery.ObservedState
    } | ConvertTo-Json -Depth 4
} finally {
    $remainingOwnedProcessIds = @(
        Get-DesktopPackageProcesses |
            Where-Object { $baselineProcessIds -notcontains [int]$_.ProcessId } |
            ForEach-Object { [int]$_.ProcessId }
        $ownedProcessIds
    ) | Sort-Object -Unique
    if ($remainingOwnedProcessIds.Count -gt 0) {
        $null = Request-OwnedDesktopClose $remainingOwnedProcessIds
        try {
            Wait-ForNoOwnedDesktopProcesses $remainingOwnedProcessIds
        } catch {
            Stop-OwnedDesktopProcesses $remainingOwnedProcessIds
        }
    }
    if ($nativeCloseMessagePosted -and $null -eq $recovery) {
        try {
            $recovery = Restore-ManagedWorkbench
        } catch {
            Write-Warning "Workbench-close canary recovery failed: $($_.Exception.Message)"
        }
    }
    if ($null -eq $previousDeepLinkRegistration) {
        Remove-Item Env:VIBELUTION_ELECTRON_REGISTER_DEEP_LINKS -ErrorAction SilentlyContinue
    } else {
        $env:VIBELUTION_ELECTRON_REGISTER_DEEP_LINKS = $previousDeepLinkRegistration
    }
}
