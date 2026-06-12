param(
    [ValidateSet("launcher", "toggle", "start", "open", "stop", "close", "restart", "status")]
    [string]$Action = "launcher",
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$launcherScript = Join-Path $projectDir "scripts\vibelution_launcher.ps1"
$runtimeDir = Join-Path $projectDir ".runtime"
$launcherDir = Join-Path $runtimeDir "launcher"
$entryLogPath = Join-Path $launcherDir "desktop-entry.log"
$desktopEntryStartMutexName = [string]$env:VIBELUTION_DESKTOP_ENTRY_START_MUTEX_NAME
if (-not $desktopEntryStartMutexName.Trim()) {
    $desktopEntryStartMutexName = "Global\Vibelution.Workbench.DesktopEntry.Start"
}
$script:desktopEntryRunId = [guid]::NewGuid().ToString("N")
$script:desktopEntryStartedAt = (Get-Date).ToUniversalTime().ToString("o")
$script:desktopEntryStartMutex = $null

function Resolve-DesktopEntryActionTimeoutSeconds {
    param([string]$LauncherAction)

    $configured = [string]$env:VIBELUTION_DESKTOP_ENTRY_ACTION_TIMEOUT_SECONDS
    if ($configured.Trim()) {
        $parsed = 0
        if ([int]::TryParse($configured.Trim(), [ref]$parsed) -and $parsed -gt 0) {
            return $parsed
        }
    }

    switch (([string]$LauncherAction).ToLowerInvariant()) {
        "stop" { return 90 }
        "status" { return 45 }
        default { return 180 }
    }
}

function Stop-DesktopEntryProcessTree {
    param([int]$ProcessId)

    if ($ProcessId -le 0) {
        return
    }
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue | ForEach-Object {
        [int]$_.ProcessId
    })
    foreach ($childPid in $children) {
        Stop-DesktopEntryProcessTree -ProcessId $childPid
    }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Clear-StaleDesktopEntryStartProcesses {
    param(
        [string]$LauncherAction,
        [int]$TimeoutSeconds
    )

    if (-not (Test-DesktopEntryStartAction -LauncherAction $LauncherAction)) {
        return
    }

    $selfPid = [int]$PID
    $now = Get-Date
    $scriptMarker = [regex]::Escape((Resolve-Path -LiteralPath $PSCommandPath).Path)
    $actionPattern = '(?i)-Action\s+(?:"?(launcher|start|open)"?)'
    $staleAfterSeconds = [Math]::Max(60, $TimeoutSeconds + 15)
    $candidates = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessId -ne $selfPid `
            -and $_.Name -ieq "powershell.exe" `
            -and $_.CommandLine `
            -and $_.CommandLine -match $scriptMarker `
            -and $_.CommandLine -match $actionPattern
    })

    foreach ($candidate in $candidates) {
        $startedAt = $null
        try {
            $startedAt = [System.Management.ManagementDateTimeConverter]::ToDateTime([string]$candidate.CreationDate)
        } catch {
        }
        if (-not $startedAt) {
            continue
        }
        $ageSeconds = ($now - $startedAt).TotalSeconds
        if ($ageSeconds -lt $staleAfterSeconds) {
            continue
        }

        Write-DesktopEntryLog `
            -Event "desktop_entry.stale_start_process.cleaned" `
            -Message "Desktop entry cleaned a stale start process before acquiring the start gate." `
            -Level "warning" `
            -Fields @{
                action = $Action
                launcher_action = $LauncherAction
                stale_process_id = [int]$candidate.ProcessId
                stale_age_seconds = [int]$ageSeconds
                stale_after_seconds = [int]$staleAfterSeconds
            }
        Stop-DesktopEntryProcessTree -ProcessId ([int]$candidate.ProcessId)
    }
}

function Set-DesktopEntryPythonRuntime {
    $pythonPath = Join-Path $projectDir ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $pythonPath) {
        $env:VIBELUTION_PYTHON_EXE = $pythonPath
        Write-DesktopEntryLog `
            -Event "desktop_entry.python_runtime.selected" `
            -Message "Using Python runtime for desktop launch." `
            -Fields @{ path = $pythonPath }
    }
}

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
        $safeFields = if ($Fields) { $Fields.Clone() } else { @{} }
        $safeFields["run_id"] = $script:desktopEntryRunId
        $payload = @{
            ts = (Get-Date).ToUniversalTime().ToString("o")
            level = $Level
            event = $Event
            message = $Message
            fields = $safeFields
        }
        Add-Content -LiteralPath $entryLogPath -Value ($payload | ConvertTo-Json -Depth 8 -Compress) -Encoding utf8
    } catch {
    }
}

function Sync-DesktopEntryLogsIntoRuntimeScene {
    try {
        $sceneDir = Get-DesktopEntryRuntimeSceneDir
        if (-not $sceneDir -or -not (Test-Path -LiteralPath $sceneDir)) {
            return
        }

        Sync-DesktopEntryLogFile `
            -SourcePath $entryLogPath `
            -TargetPath (Join-Path $sceneDir "raw\desktop-entry.log") `
            -Matcher {
                param($payload)
                return (Get-JsonPayloadField -Payload $payload -FieldName "run_id") -eq $script:desktopEntryRunId
            }

        $vbsRunId = [string]$env:VIBELUTION_DESKTOP_ENTRY_VBS_RUN_ID
        if ($vbsRunId) {
            Sync-DesktopEntryLogFile `
                -SourcePath (Join-Path $launcherDir "desktop-entry-vbs.log") `
                -TargetPath (Join-Path $sceneDir "raw\desktop-entry-vbs.log") `
                -Matcher {
                    param($payload)
                    return ([string]$payload.details) -match [regex]::Escape("run_id=$vbsRunId")
                }
        }
    } catch {
    }
}

function Get-DesktopEntryRuntimeSceneDir {
    foreach ($path in @(
        (Join-Path $launcherDir "state.json"),
        (Join-Path $launcherDir "active-runtime-scene.json")
    )) {
        if (-not (Test-Path -LiteralPath $path)) {
            continue
        }
        try {
            $payload = Get-Content -LiteralPath $path -Raw -Encoding utf8 | ConvertFrom-Json
            $sceneDir = [string]$payload.runtimeSceneDir
            if ($sceneDir) {
                return $sceneDir
            }
        } catch {
        }
    }
    return ""
}

function Get-JsonPayloadField {
    param(
        $Payload,
        [string]$FieldName
    )

    if ($null -eq $Payload) {
        return ""
    }
    $fieldsProperty = $Payload.PSObject.Properties["fields"]
    if ($null -eq $fieldsProperty -or $null -eq $fieldsProperty.Value) {
        return ""
    }
    $fieldProperty = $fieldsProperty.Value.PSObject.Properties[$FieldName]
    if ($null -eq $fieldProperty) {
        return ""
    }
    return [string]$fieldProperty.Value
}

function Sync-DesktopEntryLogFile {
    param(
        [string]$SourcePath,
        [string]$TargetPath,
        [scriptblock]$Matcher
    )

    if (-not (Test-Path -LiteralPath $SourcePath)) {
        return
    }
    $lines = @()
    foreach ($line in Get-Content -LiteralPath $SourcePath -Encoding utf8 -ErrorAction SilentlyContinue) {
        if ([string]::IsNullOrWhiteSpace([string]$line)) {
            continue
        }
        try {
            $payload = $line | ConvertFrom-Json -ErrorAction Stop
        } catch {
            continue
        }
        if (& $Matcher $payload) {
            $lines += [string]$line
        }
    }
    if ($lines.Count -eq 0) {
        return
    }
    $targetDir = Split-Path -Parent $TargetPath
    if (-not (Test-Path -LiteralPath $targetDir)) {
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    }
    Set-Content -LiteralPath $TargetPath -Value $lines -Encoding utf8
}

function Write-DesktopEntryFailureNotice {
    param([string]$Message)

    Write-DesktopEntryLog `
        -Event "desktop_entry.failure.notice.requested" `
        -Message "Desktop entry requested visible failure feedback." `
        -Level "error" `
        -Fields @{
            error = $Message
            log_path = $entryLogPath
        }
    Show-DesktopEntryFeedback `
        -Title "Vibelution start failed" `
        -Message "Vibelution did not start. Details were written to $entryLogPath" `
        -Seconds 8 `
        -Kind "error"
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
        "-WindowStyle",
        "Hidden",
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

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo.FileName = $powershellExe
    $proc.StartInfo.Arguments = ConvertTo-DesktopEntryProcessArgumentString -ArgumentList $arguments
    $proc.StartInfo.WorkingDirectory = $projectDir
    $proc.StartInfo.UseShellExecute = $false
    $proc.StartInfo.CreateNoWindow = $true
    $proc.StartInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    $proc.StartInfo.RedirectStandardOutput = $true
    $proc.StartInfo.RedirectStandardError = $true
    $proc.StartInfo.EnvironmentVariables["VIBELUTION_DESKTOP_ENTRY_RUN_ID"] = $script:desktopEntryRunId
    $proc.StartInfo.EnvironmentVariables["VIBELUTION_DESKTOP_ENTRY_STARTED_AT"] = $script:desktopEntryStartedAt

    if (-not $proc.Start()) {
        throw "Failed to start launcher action '$LauncherAction'."
    }

    $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
    $stderrTask = $proc.StandardError.ReadToEndAsync()
    $timeoutSeconds = Resolve-DesktopEntryActionTimeoutSeconds -LauncherAction $LauncherAction
    $exited = $proc.WaitForExit([Math]::Max(1, $timeoutSeconds) * 1000)
    if (-not $exited) {
        Write-DesktopEntryLog `
            -Event "desktop_entry.launcher_action.timed_out" `
            -Message "Hidden launcher action timed out." `
            -Level "error" `
            -Fields @{
                action = $LauncherAction
                timeout_seconds = $timeoutSeconds
                process_id = [int]$proc.Id
                stdout_log = $stdoutPath
                stderr_log = $stderrPath
            }
        Stop-DesktopEntryProcessTree -ProcessId ([int]$proc.Id)
        throw "Launcher action '$LauncherAction' timed out after $timeoutSeconds seconds."
    }

    $stdoutCaptured = $stdoutTask.Wait(2000)
    $stderrCaptured = $stderrTask.Wait(2000)

    $exitCode = [int]$proc.ExitCode
    $stdout = if ($stdoutCaptured) { [string]$stdoutTask.Result } else { "" }
    $stderr = if ($stderrCaptured) { [string]$stderrTask.Result } else { "" }
    if (-not $stdoutCaptured -or -not $stderrCaptured) {
        Write-DesktopEntryLog `
            -Event "desktop_entry.launcher_action.stream_capture_timed_out" `
            -Message "Hidden launcher action exited but redirected stream capture did not finish promptly." `
            -Level "warning" `
            -Fields @{
                action = $LauncherAction
                stdout_captured = [bool]$stdoutCaptured
                stderr_captured = [bool]$stderrCaptured
                stdout_log = $stdoutPath
                stderr_log = $stderrPath
            }
    }
    if ($stdout) {
        [System.IO.File]::WriteAllText($stdoutPath, $stdout, (New-Object System.Text.UTF8Encoding -ArgumentList $false))
    }
    if ($stderr) {
        [System.IO.File]::WriteAllText($stderrPath, $stderr, (New-Object System.Text.UTF8Encoding -ArgumentList $false))
    }
    $stdoutTail = (($stdout -split "\r?\n") | Select-Object -Last 40) -join [Environment]::NewLine
    $stderrTail = (($stderr -split "\r?\n") | Select-Object -Last 40) -join [Environment]::NewLine

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

function ConvertTo-DesktopEntryProcessArgument {
    param([AllowNull()][string]$Value)

    $text = [string]$Value
    if ($text.Length -eq 0) {
        return '""'
    }
    if ($text -notmatch '[\s"]') {
        return $text
    }

    $result = '"'
    $backslashes = 0
    foreach ($char in $text.ToCharArray()) {
        if ($char -eq '\') {
            $backslashes += 1
            continue
        }
        if ($char -eq '"') {
            if ($backslashes -gt 0) {
                $result += ('\' * ($backslashes * 2))
                $backslashes = 0
            }
            $result += '\"'
            continue
        }
        if ($backslashes -gt 0) {
            $result += ('\' * $backslashes)
            $backslashes = 0
        }
        $result += $char
    }
    if ($backslashes -gt 0) {
        $result += ('\' * ($backslashes * 2))
    }
    $result += '"'
    return $result
}

function ConvertTo-DesktopEntryProcessArgumentString {
    param([string[]]$ArgumentList = @())

    return (@($ArgumentList) | ForEach-Object { ConvertTo-DesktopEntryProcessArgument -Value $_ }) -join " "
}

function Convert-ToLauncherAction {
    param([string]$RequestedAction)

    switch ($RequestedAction.ToLowerInvariant()) {
        "open" { return "launcher" }
        "start" { return "launcher" }
        "close" { return "stop" }
        default { return $RequestedAction }
    }
}

function Test-DesktopEntryStartAction {
    param([string]$LauncherAction)

    return @("launcher", "start") -contains ([string]$LauncherAction).ToLowerInvariant()
}

function Test-DesktopEntryFeedbackSuppressed {
    $value = [string]$env:VIBELUTION_DESKTOP_ENTRY_SUPPRESS_FEEDBACK
    return @("1", "true", "yes", "on") -contains $value.Trim().ToLowerInvariant()
}

function Test-DesktopEntryFeedbackEnabled {
    $value = [string]$env:VIBELUTION_DESKTOP_ENTRY_SHOW_FEEDBACK
    return @("1", "true", "yes", "on") -contains $value.Trim().ToLowerInvariant()
}

function Show-DesktopEntryFeedback {
    param(
        [string]$Title,
        [string]$Message,
        [int]$Seconds = 3,
        [ValidateSet("info", "warning", "error")]
        [string]$Kind = "info"
    )

    if (Test-DesktopEntryFeedbackSuppressed) {
        Write-DesktopEntryLog `
            -Event "desktop_entry.feedback.suppressed" `
            -Message "Desktop entry visible feedback was suppressed by environment." `
            -Fields @{ title = $Title; kind = $Kind }
        return
    }

    if ($Kind -ne "error" -and -not (Test-DesktopEntryFeedbackEnabled)) {
        Write-DesktopEntryLog `
            -Event "desktop_entry.feedback.suppressed" `
            -Message "Desktop entry visible feedback is quiet by default." `
            -Fields @{ title = $Title; kind = $Kind; reason = "default_quiet" }
        return
    }

    try {
        $wshShell = New-Object -ComObject WScript.Shell
        $icon = switch ($Kind) {
            "error" { 16 }
            "warning" { 48 }
            default { 64 }
        }
        [void]$wshShell.Popup($Message, $Seconds, $Title, $icon)
        Write-DesktopEntryLog `
            -Event "desktop_entry.feedback.shown" `
            -Message "Desktop entry visible feedback was shown." `
            -Fields @{ title = $Title; kind = $Kind; timeout_seconds = $Seconds }
    } catch {
        Write-DesktopEntryLog `
            -Event "desktop_entry.feedback.failed" `
            -Message "Desktop entry visible feedback failed." `
            -Level "warning" `
            -Fields @{ title = $Title; kind = $Kind; error = $_.Exception.Message }
    }
}

function Enter-DesktopEntryStartGate {
    param([string]$LauncherAction)

    if (-not (Test-DesktopEntryStartAction -LauncherAction $LauncherAction)) {
        return $true
    }

    $script:desktopEntryStartMutex = New-Object System.Threading.Mutex($false, $desktopEntryStartMutexName)
    $acquired = $script:desktopEntryStartMutex.WaitOne(0)
    if ($acquired) {
        return $true
    }

    try {
        $script:desktopEntryStartMutex.Dispose()
    } catch {
    }
    $script:desktopEntryStartMutex = $null

    Write-DesktopEntryLog `
        -Event "desktop_entry.start.skipped_in_progress" `
        -Message "Desktop entry ignored a duplicate start while another start is already running." `
        -Fields @{ action = $Action; launcher_action = $LauncherAction; no_browser = [bool]$NoBrowser }
    Show-DesktopEntryFeedback `
        -Title "Vibelution is opening" `
        -Message "Vibelution is already starting. Please wait for the app window to appear." `
        -Seconds 3 `
        -Kind "info"
    return $false
}

function Exit-DesktopEntryStartGate {
    if ($null -eq $script:desktopEntryStartMutex) {
        return
    }
    try {
        $script:desktopEntryStartMutex.ReleaseMutex() | Out-Null
    } catch {
    }
    try {
        $script:desktopEntryStartMutex.Dispose()
    } catch {
    }
    $script:desktopEntryStartMutex = $null
}

Ensure-EntryDirectories
$startGateAcquired = $false
try {
    Set-DesktopEntryPythonRuntime

    if (-not (Test-Path $launcherScript)) {
        throw "Launcher script not found: $launcherScript"
    }

    $launcherAction = Convert-ToLauncherAction -RequestedAction $Action
    $monitorWouldAttach = @("launcher", "start", "open", "restart") -contains $Action.ToLowerInvariant()

    Write-DesktopEntryLog `
        -Event "desktop_entry.started" `
        -Message "Desktop entry started." `
        -Fields @{ action = $Action; launcher_action = $launcherAction; no_browser = [bool]$NoBrowser }

    Clear-StaleDesktopEntryStartProcesses `
        -LauncherAction $launcherAction `
        -TimeoutSeconds (Resolve-DesktopEntryActionTimeoutSeconds -LauncherAction $launcherAction)

    $startGateAcquired = Enter-DesktopEntryStartGate -LauncherAction $launcherAction
    if (-not $startGateAcquired) {
        Sync-DesktopEntryLogsIntoRuntimeScene
        exit 0
    }

    Invoke-HiddenLauncherAction -LauncherAction $launcherAction -ForwardNoBrowser:$NoBrowser

    if ($monitorWouldAttach) {
        Write-DesktopEntryLog `
            -Event "desktop_entry.monitor.skipped" `
            -Message "Desktop entry skipped the visible lifecycle monitor; the managed workbench owns lifecycle feedback." `
            -Fields @{ action = $Action; launcher_action = $launcherAction; no_browser = [bool]$NoBrowser }
    }

    Write-DesktopEntryLog `
        -Event "desktop_entry.completed" `
        -Message "Desktop entry completed." `
        -Fields @{ action = $Action; launcher_action = $launcherAction; no_browser = [bool]$NoBrowser }
    Sync-DesktopEntryLogsIntoRuntimeScene
} catch {
    $message = $_.Exception.Message
    Write-DesktopEntryLog `
        -Event "desktop_entry.failed" `
        -Message $message `
        -Level "error" `
        -Fields @{ action = $Action; no_browser = [bool]$NoBrowser }
    Write-DesktopEntryFailureNotice -Message $message
    Sync-DesktopEntryLogsIntoRuntimeScene
    exit 1
} finally {
    if ($startGateAcquired) {
        Exit-DesktopEntryStartGate
    }
}
