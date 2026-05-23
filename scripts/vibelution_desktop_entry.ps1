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

function Set-DesktopEntryPythonRuntime {
    $pythonwPath = Join-Path $projectDir ".venv\Scripts\pythonw.exe"
    $pythonPath = Join-Path $projectDir ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $pythonwPath) {
        $env:VIBELUTION_PYTHON_EXE = $pythonwPath
        Write-DesktopEntryLog `
            -Event "desktop_entry.python_runtime.selected" `
            -Message "Using windowless Python runtime for desktop launch." `
            -Fields @{ path = $pythonwPath }
        return
    }
    if (Test-Path -LiteralPath $pythonPath) {
        $env:VIBELUTION_PYTHON_EXE = $pythonPath
        Write-DesktopEntryLog `
            -Event "desktop_entry.python_runtime.selected" `
            -Message "Windowless Python runtime was not found; falling back to console Python." `
            -Level "warning" `
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

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo.FileName = $powershellExe
    $proc.StartInfo.Arguments = ConvertTo-DesktopEntryProcessArgumentString -ArgumentList $arguments
    $proc.StartInfo.WorkingDirectory = $projectDir
    $proc.StartInfo.UseShellExecute = $false
    $proc.StartInfo.CreateNoWindow = $true
    $proc.StartInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    $proc.StartInfo.RedirectStandardOutput = $true
    $proc.StartInfo.RedirectStandardError = $true

    if (-not $proc.Start()) {
        throw "Failed to start launcher action '$LauncherAction'."
    }

    $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
    $stderrTask = $proc.StandardError.ReadToEndAsync()
    $proc.WaitForExit()
    $stdoutTask.Wait()
    $stderrTask.Wait()

    $exitCode = [int]$proc.ExitCode
    $stdout = [string]$stdoutTask.Result
    $stderr = [string]$stderrTask.Result
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
        "open" { return "start" }
        "close" { return "stop" }
        default { return $RequestedAction }
    }
}

Ensure-EntryDirectories
try {
    Set-DesktopEntryPythonRuntime

    if (-not (Test-Path $launcherScript)) {
        throw "Launcher script not found: $launcherScript"
    }

    $launcherAction = Convert-ToLauncherAction -RequestedAction $Action
    $monitorWouldAttach = @("start", "open", "restart") -contains $Action.ToLowerInvariant()

    Write-DesktopEntryLog `
        -Event "desktop_entry.started" `
        -Message "Desktop entry started." `
        -Fields @{ action = $Action; launcher_action = $launcherAction; no_browser = [bool]$NoBrowser }

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
