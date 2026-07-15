param(
    [string]$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\\..")).Path,
    [string]$OutputPath,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = (Resolve-Path -LiteralPath $ProjectDir).Path
if (-not $OutputPath) {
    $localAppData = [Environment]::GetFolderPath("LocalApplicationData")
    if (-not $localAppData) {
        $localAppData = Join-Path $projectRoot ".runtime\\launcher"
    }
    $OutputPath = Join-Path $localAppData "Vibelution\\Launcher\\VibelutionLauncher.exe"
}

$buildScriptPath = Join-Path $projectRoot "scripts\\windows_launcher_entry\\build_vibelution_launcher_entry.ps1"
$sourcePath = Join-Path $projectRoot "scripts\\windows_launcher_entry\\VibelutionLauncher.cs"
$iconPath = Join-Path $projectRoot "assets\\icons\\vibelution.ico"
$syncLogPath = Join-Path $projectRoot ".runtime\\launcher\\native-entry-sync.log"

function Write-NativeLauncherSyncLog {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Event,
        [Parameter(Mandatory = $true)]
        [hashtable]$Fields,
        [string]$Level = "info"
    )

    try {
        $logDirectory = Split-Path -Parent $syncLogPath
        if (-not (Test-Path -LiteralPath $logDirectory)) {
            New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
        }
        @{
            ts = (Get-Date).ToUniversalTime().ToString("o")
            level = $Level
            event = $Event
            fields = $Fields
        } | ConvertTo-Json -Depth 6 -Compress | Add-Content -LiteralPath $syncLogPath -Encoding utf8
    } catch {
        # A lifecycle sync must never make a successful Git merge fail because its audit log is unavailable.
    }
}

function Get-NativeLauncherSyncInputs {
    $inputs = @($buildScriptPath, $sourcePath, $iconPath)
    $missing = @($inputs | Where-Object { -not (Test-Path -LiteralPath $_) })
    if ($missing.Count -gt 0) {
        throw "Native Launcher sync inputs are missing: $($missing -join '; ')"
    }
    return @($inputs | ForEach-Object { Get-Item -LiteralPath $_ })
}

function Test-NativeLauncherEntryCurrent {
    param([System.IO.FileInfo[]]$Inputs)

    if (-not (Test-Path -LiteralPath $OutputPath)) {
        return $false
    }
    $outputItem = Get-Item -LiteralPath $OutputPath
    return -not @($Inputs | Where-Object { $_.LastWriteTimeUtc -gt $outputItem.LastWriteTimeUtc }).Count
}

$result = [ordered]@{
    outputPath = $OutputPath
    status = "unknown"
    rebuilt = $false
}

try {
    $inputs = Get-NativeLauncherSyncInputs
    if (Test-NativeLauncherEntryCurrent -Inputs $inputs) {
        $result.status = "current"
    } else {
        $buildOutput = & $buildScriptPath -ProjectDir $projectRoot -OutputPath $OutputPath
        $outputItem = if (Test-Path -LiteralPath $OutputPath) { Get-Item -LiteralPath $OutputPath } else { $null }
        if (-not $outputItem -or -not (Test-NativeLauncherEntryCurrent -Inputs $inputs)) {
            throw "Native Launcher build completed without producing a current executable: $OutputPath"
        }
        $result.status = "rebuilt"
        $result.rebuilt = $true
        Write-NativeLauncherSyncLog `
            -Event "native_launcher.sync.rebuilt" `
            -Fields @{
                output_path = $OutputPath
                output_last_write_utc = $outputItem.LastWriteTimeUtc.ToString("o")
                trigger_inputs = @($inputs | Where-Object { $_.LastWriteTimeUtc -ge $outputItem.LastWriteTimeUtc.AddSeconds(-2) } | ForEach-Object { $_.FullName })
                build_output = ($buildOutput -join "`n")
            }
    }
} catch {
    $result.status = "deferred"
    $result.error = $_.Exception.Message
    Write-NativeLauncherSyncLog `
        -Event "native_launcher.sync.deferred" `
        -Level "warning" `
        -Fields @{ output_path = $OutputPath; error = $_.Exception.Message }
}

if (-not $Quiet) {
    $result | ConvertTo-Json -Depth 4
}

exit 0
