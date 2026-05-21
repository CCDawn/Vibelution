param(
    [ValidateSet("toggle", "start", "open", "stop", "close", "restart", "status")]
    [string]$Action = "start",
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$launcherScript = Join-Path $projectDir "scripts\vibelution_launcher.ps1"
$runtimeDir = Join-Path $projectDir ".runtime"
$launcherDir = Join-Path $runtimeDir "launcher"
$entryLogPath = Join-Path $launcherDir "desktop-entry.log"

function Ensure-EntryDirectories {
    if (-not (Test-Path $launcherDir)) {
        New-Item -ItemType Directory -Path $launcherDir -Force | Out-Null
    }
}

function Write-DesktopEntryLog {
    param(
        [string]$Event,
        [string]$Message,
        [string]$Level = "info",
        [hashtable]$Fields = @{}
    )

    try {
        Ensure-EntryDirectories
        $payload = @{
            ts = (Get-Date).ToUniversalTime().ToString("o")
            level = $Level
            event = $Event
            message = $Message
            fields = if ($Fields) { $Fields } else { @{} }
        }
        Add-Content -LiteralPath $entryLogPath -Value ($payload | ConvertTo-Json -Depth 8 -Compress) -Encoding utf8
    } catch {
    }
}

function Show-DesktopEntryFailure {
    param([string]$Message)

    $body = "$Message`n`nLog: $entryLogPath"
    try {
        Add-Type -AssemblyName PresentationFramework
        [System.Windows.MessageBox]::Show($body, "Vibelution Launcher", "OK", "Error") | Out-Null
        return
    } catch {
    }

    try {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show($body, "Vibelution Launcher", "OK", "Error") | Out-Null
    } catch {
    }
}

function Invoke-HiddenLauncherAction {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LauncherAction,
        [switch]$ForwardNoBrowser
    )

    Ensure-EntryDirectories
    $token = [guid]::NewGuid().ToString("N")
    $stdoutPath = Join-Path $launcherDir "desktop-entry-$token.out.log"
    $stderrPath = Join-Path $launcherDir "desktop-entry-$token.err.log"
    $powershellExe = Join-Path $PSHOME "powershell.exe"
    $arguments = @(
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $launcherScript,
        "-Action",
        $LauncherAction
    )
    if ($ForwardNoBrowser) {
        $arguments += "-NoBrowser"
    }

    Write-DesktopEntryLog `
        -Event "desktop_entry.launcher_action.started" `
        -Message "Starting hidden launcher action." `
        -Fields @{
            action = $LauncherAction
            no_browser = [bool]$ForwardNoBrowser
            stdout_log = $stdoutPath
            stderr_log = $stderrPath
        }

    $proc = Start-Process `
        -FilePath $powershellExe `
        -ArgumentList $arguments `
        -WorkingDirectory $projectDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -PassThru

    $proc.WaitForExit()

    $exitCode = [int]$proc.ExitCode
    $stdoutTail = ""
    $stderrTail = ""
    if (Test-Path $stdoutPath) {
        $stdoutTail = ((Get-Content -LiteralPath $stdoutPath -Tail 40 -ErrorAction SilentlyContinue) -join [Environment]::NewLine)
    }
    if (Test-Path $stderrPath) {
        $stderrTail = ((Get-Content -LiteralPath $stderrPath -Tail 40 -ErrorAction SilentlyContinue) -join [Environment]::NewLine)
    }

    if ($exitCode -ne 0) {
        Write-DesktopEntryLog `
            -Event "desktop_entry.launcher_action.failed" `
            -Message "Hidden launcher action failed." `
            -Level "error" `
            -Fields @{
                action = $LauncherAction
                exit_code = $exitCode
                stdout_log = $stdoutPath
                stderr_log = $stderrPath
                stdout_tail = $stdoutTail
                stderr_tail = $stderrTail
            }
        throw "Launcher action '$LauncherAction' failed with exit code $exitCode. $stderrTail"
    }

    Write-DesktopEntryLog `
        -Event "desktop_entry.launcher_action.succeeded" `
        -Message "Hidden launcher action succeeded." `
        -Fields @{
            action = $LauncherAction
            exit_code = $exitCode
            stdout_tail = $stdoutTail
        }

    Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
}

function Convert-ToLauncherAction {
    param([string]$RequestedAction)

    switch ($RequestedAction.ToLowerInvariant()) {
        "open" { return "start" }
        "close" { return "stop" }
        default { return $RequestedAction }
    }
}

Ensure-EntryDirectories
try {
    if (-not (Test-Path $launcherScript)) {
        throw "Launcher script not found: $launcherScript"
    }

    $launcherAction = Convert-ToLauncherAction -RequestedAction $Action
    $monitorAfterSuccess = @("start", "open", "restart") -contains $Action.ToLowerInvariant()

    Write-DesktopEntryLog `
        -Event "desktop_entry.started" `
        -Message "Desktop entry started." `
        -Fields @{ action = $Action; launcher_action = $launcherAction; no_browser = [bool]$NoBrowser }

    Invoke-HiddenLauncherAction -LauncherAction $launcherAction -ForwardNoBrowser:$NoBrowser

    if ($monitorAfterSuccess -and -not $NoBrowser) {
        Invoke-HiddenLauncherAction -LauncherAction "monitor"
    }

    Write-DesktopEntryLog `
        -Event "desktop_entry.completed" `
        -Message "Desktop entry completed." `
        -Fields @{ action = $Action; launcher_action = $launcherAction; no_browser = [bool]$NoBrowser }
} catch {
    $message = $_.Exception.Message
    Write-DesktopEntryLog `
        -Event "desktop_entry.failed" `
        -Message $message `
        -Level "error" `
        -Fields @{ action = $Action; no_browser = [bool]$NoBrowser }
    Show-DesktopEntryFailure -Message $message
    exit 1
}
