param(
    [switch]$SkipPackageVerification,
    [int]$StartTimeoutSeconds = 45,
    [int]$SecondInstanceSettleSeconds = 5,
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
$MaxCommandLineLength = 260

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

function Format-DesktopCommandLine {
    param(
        [AllowNull()]
        [string]$CommandLine
    )

    if ([string]::IsNullOrWhiteSpace($CommandLine)) {
        return "(no command line)"
    }
    if ($CommandLine.Length -le $MaxCommandLineLength) {
        return $CommandLine
    }
    return "$($CommandLine.Substring(0, $MaxCommandLineLength))..."
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
    return ($Processes | ForEach-Object { "$($_.ProcessId): $(Format-DesktopCommandLine $_.CommandLine)" }) -join "`n"
}

function Assert-NoDesktopPackageProcesses {
    $processes = @(Get-DesktopPackageProcesses)
    if ($processes.Count -gt 0) {
        $details = Format-DesktopProcessList $processes
        throw "Vibelution desktop package is already running. Close it before lifecycle verification. Running processes:`n$details"
    }
}

function Assert-NoOtherVibelutionDesktopProcesses {
    $processes = @(Get-AllVibelutionDesktopProcesses)
    if ($processes.Count -gt 0) {
        $details = Format-DesktopProcessList $processes
        throw "Another Vibelution desktop package is already running. Close it before lifecycle verification because Electron single-instance locks are shared across package paths. Running processes:`n$details"
    }
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

function Wait-ForSecondInstanceToSettle {
    param(
        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Process]$SecondProcess
    )

    $deadline = (Get-Date).AddSeconds($SecondInstanceSettleSeconds)
    do {
        try {
            $SecondProcess.Refresh()
            if ($SecondProcess.HasExited) {
                return
            }
        } catch {
            return
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
}

function Stop-OwnedDesktopProcesses {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [int[]]$OwnedProcessIds
    )

    $uniqueProcessIds = @($OwnedProcessIds | Sort-Object -Unique)
    if ($uniqueProcessIds.Count -eq 0) {
        return
    }

    $currentProcesses = @(
        Get-DesktopPackageProcesses |
            Where-Object { $uniqueProcessIds -contains [int]$_.ProcessId }
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

    $uniqueProcessIds = @($OwnedProcessIds | Sort-Object -Unique)
    if ($uniqueProcessIds.Count -eq 0) {
        return
    }

    $deadline = (Get-Date).AddSeconds($ShutdownTimeoutSeconds)
    do {
        $remaining = @(
            Get-DesktopPackageProcesses |
                Where-Object { $uniqueProcessIds -contains [int]$_.ProcessId }
        )
        if ($remaining.Count -eq 0) {
            return
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)

    $details = Format-DesktopProcessList $remaining
    throw "Timed out waiting for owned desktop package processes to stop:`n$details"
}

Assert-NoOtherVibelutionDesktopProcesses
Assert-NoDesktopPackageProcesses

if (-not $SkipPackageVerification) {
    Invoke-CheckedNative powershell @("-ExecutionPolicy", "Bypass", "-File", $packageVerifier)
}

Assert-NoOtherVibelutionDesktopProcesses

if (-not (Test-Path -LiteralPath $desktopExe)) {
    throw "Desktop package executable is missing: $desktopExe"
}

$baselineProcessIds = @((Get-DesktopPackageProcesses | ForEach-Object { [int]$_.ProcessId }))
$startedProcessIds = @()
$ownedProcessIds = @()

try {
    $firstProcess = Start-Process -FilePath $desktopExe -PassThru
    $startedProcessIds += [int]$firstProcess.Id
    $firstRoot = Wait-ForDesktopRootProcess $baselineProcessIds

    $beforeSecondProcesses = @(
        Get-DesktopPackageProcesses |
            Where-Object { $baselineProcessIds -notcontains [int]$_.ProcessId }
    )
    $beforeSecondRoots = @(Get-RootDesktopProcesses $beforeSecondProcesses)
    $firstInstanceStayedRunning = $beforeSecondRoots.Count -ge 1
    if (-not $firstInstanceStayedRunning) {
        throw "First desktop launch did not remain running."
    }

    $secondProcess = Start-Process -FilePath $desktopExe -PassThru
    $startedProcessIds += [int]$secondProcess.Id
    Wait-ForSecondInstanceToSettle $secondProcess

    $afterSecondProcesses = @(
        Get-DesktopPackageProcesses |
            Where-Object { $baselineProcessIds -notcontains [int]$_.ProcessId }
    )
    $afterSecondRoots = @(Get-RootDesktopProcesses $afterSecondProcesses)
    $ownedProcessIds = @(
        $afterSecondProcesses | ForEach-Object { [int]$_.ProcessId }
        $startedProcessIds
    ) | Sort-Object -Unique

    $secondInstanceCreatedExtraRoot = $afterSecondRoots.Count -gt $beforeSecondRoots.Count
    if ($secondInstanceCreatedExtraRoot) {
        $details = Format-DesktopProcessList $afterSecondRoots
        throw "Second desktop launch created an extra root process. Running roots:`n$details"
    }

    Stop-OwnedDesktopProcesses $ownedProcessIds
    Wait-ForNoOwnedDesktopProcesses $ownedProcessIds

    [ordered]@{
        schemaVersion = 1
        ok = $true
        desktopExe = $desktopExe
        firstProcessId = [int]$firstProcess.Id
        firstRootProcessId = [int]$firstRoot.ProcessId
        firstInstanceStayedRunning = $firstInstanceStayedRunning
        secondProcessId = [int]$secondProcess.Id
        rootsBeforeSecondLaunch = $beforeSecondRoots.Count
        rootsAfterSecondLaunch = $afterSecondRoots.Count
        secondInstanceCreatedExtraRoot = $secondInstanceCreatedExtraRoot
        cleanedProcessIds = @($ownedProcessIds)
    } | ConvertTo-Json -Depth 4
} finally {
    $remainingOwnedProcessIds = @(
        Get-DesktopPackageProcesses |
            Where-Object { $baselineProcessIds -notcontains [int]$_.ProcessId } |
            ForEach-Object { [int]$_.ProcessId }
        $startedProcessIds
    ) | Sort-Object -Unique
    Stop-OwnedDesktopProcesses $remainingOwnedProcessIds
}
