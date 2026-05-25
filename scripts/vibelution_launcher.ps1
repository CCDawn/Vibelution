param(
    [ValidateSet("toggle", "start", "stop", "restart", "status", "monitor", "supervise", "internal-start", "internal-stop", "internal-restart", "internal-status")]
    [string]$Action = "start",
    [switch]$NoBrowser,
    [string]$SessionId
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$projectVenvDir = Join-Path $projectDir ".venv"
$preferredPythonExe = Join-Path $projectDir ".venv\Scripts\python.exe"
$launcherPythonOverride = $env:VIBELUTION_PYTHON_EXE
$requirementsPath = Join-Path $projectDir "requirements.txt"
$webDir = Join-Path $projectDir "web"
$webDistDir = Join-Path $webDir "dist"
$webDistIndex = Join-Path $webDistDir "index.html"
$runtimeDir = Join-Path $projectDir ".runtime"
$launcherDir = Join-Path $runtimeDir "launcher"
$runtimeManagerStatePath = Join-Path $runtimeDir "runtime-manager\state.json"
$launcherControlLogPath = Join-Path $launcherDir "launcher-control.log"
$runtimeSceneRoot = Join-Path $projectDir "logs\runtime_scenes"
$browserProfileDir = Join-Path $launcherDir "edge-app-profile"
$statePath = Join-Path $launcherDir "state.json"
$activeRuntimeScenePath = Join-Path $launcherDir "active-runtime-scene.json"
$pythonDepsStampPath = Join-Path $launcherDir "python-deps.stamp"
$frontendDepsStampPath = Join-Path $launcherDir "frontend-deps.stamp"
$bindHost = "127.0.0.1"
$configPath = Join-Path $projectDir "config.toml"
$managedBackendMarkerArg = "--managed-by-launcher"

function Resolve-ConfiguredWorkbenchPort {
    param([int]$DefaultPort = 8000)

    $resolvedPort = $DefaultPort
    if (Test-Path $configPath) {
        try {
            $inWorkbenchBlock = $false
            foreach ($line in Get-Content -LiteralPath $configPath -Encoding utf8) {
                $trimmed = ([string]$line).Trim()
                if ($trimmed -match '^\[(.+)\]$') {
                    $inWorkbenchBlock = ($matches[1] -eq "workbench")
                    continue
                }
                if (-not $inWorkbenchBlock) {
                    continue
                }
                if ($trimmed -match '^backend_port\s*=\s*"?([0-9]+)"?\s*(?:#.*)?$') {
                    $candidate = 0
                    if ([int]::TryParse($matches[1], [ref]$candidate) -and $candidate -gt 0 -and $candidate -lt 65536) {
                        $resolvedPort = $candidate
                    }
                    break
                }
            }
        } catch {
        }
    }

    $envPortValue = $env:VIBELUTION_PORT
    if (-not $envPortValue) {
        $envPortValue = $env:AGENT_WORKBENCH_BACKEND_PORT
    }
    if ($envPortValue) {
        $envPort = 0
        if ([int]::TryParse($envPortValue, [ref]$envPort) -and $envPort -gt 0 -and $envPort -lt 65536) {
            $resolvedPort = $envPort
        }
    }

    return $resolvedPort
}
$port = Resolve-ConfiguredWorkbenchPort
$url = "http://$bindHost`:$port"
$healthUrl = "$url/api/health"
$mode = "single_service_bundled_edge_app"
$mutexName = "Global\Vibelution.Workbench.Launcher"
$selfProcessId = $PID
$sceneSchemaVersion = 2
$script:currentRuntimeSceneId = $null
$script:currentRuntimeSceneDir = $null
$script:sceneEventSequence = @{}
$script:launcherStateWriteMaxAttempts = 25
$script:launcherStateWriteRetryDelayMilliseconds = 120
$script:runtimeSceneWriteMaxAttempts = 8
$script:runtimeSceneWriteRetryDelayMilliseconds = 120

function Set-LauncherEndpoint {
    param(
        [int]$ResolvedPort,
        [string]$ResolvedUrl = ""
    )

    if ($ResolvedPort -gt 0 -and $ResolvedPort -lt 65536) {
        $script:port = $ResolvedPort
    }

    $normalizedUrl = [string]::Empty
    if ($ResolvedUrl) {
        $normalizedUrl = ([string]$ResolvedUrl).Trim().TrimEnd("/")
    }
    if (-not $normalizedUrl) {
        $normalizedUrl = "http://$bindHost`:$script:port"
    }

    $script:url = $normalizedUrl
    $script:healthUrl = "$normalizedUrl/api/health"
}

function Sync-LauncherEndpointFromState {
    $state = Get-State
    if (-not $state) {
        return
    }

    $resolvedPort = $script:port
    $statePort = 0
    $rawPort = [string]$state.port
    if ($rawPort -and [int]::TryParse($rawPort, [ref]$statePort) -and $statePort -gt 0 -and $statePort -lt 65536) {
        $resolvedPort = $statePort
    }

    $resolvedUrl = if ($state.url) { [string]$state.url } else { "" }
    Set-LauncherEndpoint -ResolvedPort $resolvedPort -ResolvedUrl $resolvedUrl
}

function Write-Note {
    param([string]$Message)
    Write-Host "[Vibelution] $Message"
}

function Set-LauncherWindowTitle {
    try {
        $Host.UI.RawUI.WindowTitle = "Vibelution Launcher"
    } catch {
    }
}

function Get-ObjectPropertyValue {
    param(
        $Object,
        [string]$Name,
        $Default = $null
    )

    if ($null -eq $Object) {
        return $Default
    }

    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $Default
    }
    return $property.Value
}

function Write-LauncherControlLog {
    param(
        [string]$Event,
        [string]$Message,
        [string]$Level = "info",
        [hashtable]$Fields = @{}
    )

    try {
        Ensure-Directories
        $payload = @{
            ts = (Get-Date).ToUniversalTime().ToString("o")
            level = $Level
            event = $Event
            message = $Message
            fields = if ($Fields) { $Fields } else { @{} }
        }
        $line = $payload | ConvertTo-Json -Depth 8 -Compress
        Add-Content -Path $launcherControlLogPath -Value $line -Encoding utf8

        if ($script:currentRuntimeSceneDir) {
            $relativePath = (Get-RuntimeSceneRelativePaths).LauncherControl
            $targetPath = Get-CurrentRuntimeSceneFilePath $relativePath
            $targetDir = Split-Path -Parent $targetPath
            if (-not (Test-Path $targetDir)) {
                New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
            }
            Add-Content -Path $targetPath -Value $line -Encoding utf8
        }
    } catch {
    }
}

function Write-LauncherMonitorEvent {
    param(
        [string]$EventCode,
        [string]$Message,
        [string]$Level = "info",
        [string]$Outcome = "observed",
        [hashtable]$Fields = @{}
    )

    Write-LauncherControlLog -Event $EventCode -Message $Message -Level $Level -Fields $Fields
    if ($script:currentRuntimeSceneId) {
        Write-RuntimeSceneEvent `
            -Component "launcher" `
            -Phase "desktop_monitor" `
            -EventCode $EventCode `
            -Message $Message `
            -Level $Level `
            -Outcome $Outcome `
            -Fields $Fields `
            -RawRefs @(New-RuntimeSceneRawRef -RelativePath (Get-RuntimeSceneRelativePaths).LauncherControl -TailLines 80)
    }
}

function Invoke-RuntimeManagerClient {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Mode,
        [string]$CommandType = "",
        [string]$Reason = "",
        [switch]$ForwardNoBrowser,
        [switch]$StopManager
    )

    Ensure-ProjectPythonDependencies
    $pythonRuntime = Resolve-PythonRuntime
    $pythonArgs = @()
    if ($pythonRuntime.PrefixArgs) {
        $pythonArgs += $pythonRuntime.PrefixArgs
    }

    if ($Mode -eq "status") {
        $pythonArgs += @("-m", "core.runtime_manager.cli", "status")
        $exitCode = Invoke-HiddenNativeCommand -CommandPath $pythonRuntime.FilePath -ArgumentList $pythonArgs
        Set-LauncherWindowTitle
        if ($exitCode -ne 0) {
            throw "Runtime manager status failed with exit code $exitCode."
        }
        return 0
    }

    if (-not $CommandType) {
        throw "Runtime manager command mode requires -CommandType."
    }

    $timeoutSeconds = switch ($CommandType) {
        "open_workbench" { 90 }
        "close_workbench" { 60 }
        "restart_workbench" { 120 }
        default { 45 }
    }

    $pythonArgs += @("-m", "core.runtime_manager.cli", "command", $CommandType, "--requested-by", "launcher_ps", "--wait", "--timeout", "$timeoutSeconds")
    if ($Reason) {
        $pythonArgs += @("--reason", $Reason)
    }
    if ($ForwardNoBrowser) {
        $pythonArgs += "--no-browser"
    }
    if ($StopManager) {
        $pythonArgs += "--stop-manager"
    }

    $exitCode = Invoke-HiddenNativeCommand -CommandPath $pythonRuntime.FilePath -ArgumentList $pythonArgs
    Set-LauncherWindowTitle
    if ($exitCode -ne 0) {
        throw "Runtime manager command '$CommandType' failed with exit code $exitCode."
    }
    return 0
}

function Ensure-Directories {
    foreach ($path in @($runtimeDir, $launcherDir, $browserProfileDir, $runtimeSceneRoot)) {
        if (-not (Test-Path $path)) {
            New-Item -ItemType Directory -Path $path -Force | Out-Null
        }
    }
}

function ConvertTo-PortableTimestampToken {
    param([datetime]$Value)

    return $Value.ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
}

function ConvertTo-RuntimeSceneIndexToken {
    param(
        [string]$Value,
        [string]$Default = "unknown"
    )

    $text = ([string]$Value).Trim().ToLowerInvariant()
    if (-not $text) {
        return $Default
    }
    $normalized = ($text -replace "[^a-z0-9]+", "-").Trim("-")
    if ($normalized) {
        return $normalized
    }
    return $Default
}

function Get-RuntimeSceneTriggerIndexToken {
    param([string]$Trigger)

    $normalized = ([string]$Trigger).Trim().ToLowerInvariant()
    switch ($normalized) {
        "start" { return "workbench-start" }
        "internal-start" { return "workbench-start" }
        "restart" { return "workbench-restart" }
        "internal-restart" { return "workbench-restart" }
        "open" { return "workbench-open" }
        "stop" { return "workbench-stop" }
        "shutdown" { return "workbench-shutdown" }
        default { return ConvertTo-RuntimeSceneIndexToken -Value $normalized -Default "workbench-run" }
    }
}

function Get-RuntimeSceneStatusIndexToken {
    param(
        [string]$Status,
        [string]$Result,
        [string]$StopReason
    )

    $normalizedStatus = ([string]$Status).Trim().ToLowerInvariant()
    $normalizedResult = ([string]$Result).Trim().ToLowerInvariant()
    if ($normalizedStatus -eq "stopped" -and $normalizedResult) {
        switch ($normalizedResult) {
            "explicit_stop" { return "manual-stop" }
            "explicit stop" { return "manual-stop" }
            "browser_window_closed" { return "window-closed" }
            "startup_failed" { return "startup-failed" }
            "backend_exited" { return "backend-exited" }
            default { return ConvertTo-RuntimeSceneIndexToken -Value $normalizedResult -Default "stopped" }
        }
    }
    return ConvertTo-RuntimeSceneIndexToken -Value $normalizedStatus -Default "unknown"
}

function Get-RuntimeSceneStatusDisplayLabel {
    param(
        [string]$Status,
        [string]$Result,
        [string]$StopReason
    )

    $normalizedStatus = ([string]$Status).Trim().ToLowerInvariant()
    $normalizedResult = ([string]$Result).Trim().ToLowerInvariant()
    $normalizedStopReason = ([string]$StopReason).Trim().ToLowerInvariant()
    if ($normalizedStatus -eq "stopped" -and ($normalizedResult -or $normalizedStopReason)) {
        switch ($normalizedResult) {
            "explicit_stop" { return "手动停止" }
            "explicit stop" { return "手动停止" }
            "browser_window_closed" { return "窗口关闭" }
            "app window closed" { return "窗口关闭" }
            "startup_failed" { return "启动失败" }
            "backend_exited" { return "后端退出" }
            "runtime_manager_stop" { return "运行管理器停止" }
            "runtime manager stop" { return "运行管理器停止" }
            default {
                if ($normalizedStopReason) {
                    switch ($normalizedStopReason) {
                        "runtime_manager_stop" { return "运行管理器停止" }
                        "runtime manager stop" { return "运行管理器停止" }
                        "manual stop" { return "手动停止" }
                        "explicit_stop" { return "手动停止" }
                        "explicit stop" { return "手动停止" }
                        default { return $normalizedStopReason -replace "[-_]+", " " }
                    }
                }
                return $normalizedResult -replace "[-_]+", " "
            }
        }
    }
    switch ($normalizedStatus) {
        "running" { return "运行中" }
        "starting" { return "启动中" }
        "queued" { return "等待中" }
        "stopping" { return "停止中" }
        "stopped" { return "已停止" }
        "failed" { return "失败" }
        "success" { return "成功" }
        "succeeded" { return "成功" }
        default {
            if ($normalizedStatus) {
                return $normalizedStatus -replace "[-_]+", " "
            }
            return "unknown"
        }
    }
}

function Get-RuntimeSceneEffectiveStatus {
    param(
        [string]$Status,
        [string]$EndedAt = "",
        [string]$Default = "unknown"
    )

    $normalizedStatus = ([string]$Status).Trim().ToLowerInvariant()
    if ($normalizedStatus -and $normalizedStatus -ne "unknown") {
        return $normalizedStatus
    }
    if (-not ([string]$EndedAt).Trim()) {
        return "running"
    }
    if ($normalizedStatus) {
        return $normalizedStatus
    }
    return $Default
}

function Get-RuntimeSceneTriggerDisplayLabel {
    param([string]$Trigger)

    $normalized = ([string]$Trigger).Trim().ToLowerInvariant()
    switch ($normalized) {
        "start" { return "工作台启动" }
        "internal-start" { return "工作台启动" }
        "restart" { return "工作台重启" }
        "internal-restart" { return "工作台重启" }
        "open" { return "打开工作台" }
        "stop" { return "关闭工作台" }
        "shutdown" { return "关闭工作台" }
        default {
            if ($normalized) {
                return $normalized -replace "[-_]+", " "
            }
            return "工作台运行"
        }
    }
}

function Get-RuntimeScenePackageIndex {
    param(
        [string]$SceneId,
        [datetime]$StartedAt,
        [string]$Trigger,
        [string]$Status = "running",
        [string]$Result = "",
        [string]$StopReason = "",
        [string]$EndedAt = ""
    )

    $localStarted = $StartedAt.ToLocalTime()
    $effectiveStatus = Get-RuntimeSceneEffectiveStatus -Status $Status -EndedAt $EndedAt -Default "unknown"
    $startedDate = $localStarted.ToString("yyyy-MM-dd")
    $startedTime = $localStarted.ToString("HH:mm:ss")
    $triggerToken = Get-RuntimeSceneTriggerIndexToken -Trigger $Trigger
    $statusToken = Get-RuntimeSceneStatusIndexToken -Status $effectiveStatus -Result $Result -StopReason $StopReason
    $displayName = "{0} {1} · {2} · {3}" -f $startedDate, $startedTime, (Get-RuntimeSceneTriggerDisplayLabel -Trigger $Trigger), (Get-RuntimeSceneStatusDisplayLabel -Status $effectiveStatus -Result $Result -StopReason $StopReason)
    $indexKey = "{0}_{1}_{2}_{3}" -f $startedDate, ($startedTime -replace ":", "-"), $triggerToken, $statusToken
    $tags = @(
        "runtime-scene",
        "workbench-lifecycle",
        $triggerToken,
        $statusToken,
        (ConvertTo-RuntimeSceneIndexToken -Value $effectiveStatus -Default ""),
        (ConvertTo-RuntimeSceneIndexToken -Value $Result -Default ""),
        (ConvertTo-RuntimeSceneIndexToken -Value $Trigger -Default ""),
        "managed"
    ) | Where-Object { $_ } | Select-Object -Unique
    $durationSeconds = $null
    if ($EndedAt) {
        try {
            $endedDateTime = [datetime]$EndedAt
            $durationSeconds = [Math]::Max(0, [Math]::Round(($endedDateTime.ToUniversalTime() - $StartedAt.ToUniversalTime()).TotalSeconds, 3))
        } catch {
            $durationSeconds = $null
        }
    }

    $searchText = @(
        $displayName,
        $indexKey,
        $SceneId,
        $StartedAt.ToUniversalTime().ToString("o"),
        $localStarted.ToString("o"),
        $startedDate,
        $startedTime,
        $Trigger,
        $effectiveStatus,
        $Result,
        $StopReason
    ) | Where-Object { $_ }
    $searchText += @($tags)

    return @{
        schema_version = 1
        package_id = $SceneId
        display_name = $displayName
        index_key = $indexKey
        sortable_timestamp = $StartedAt.ToUniversalTime().ToString("o")
        started_at = $StartedAt.ToUniversalTime().ToString("o")
        started_at_local = $localStarted.ToString("o")
        started_date = $startedDate
        started_time = $startedTime
        ended_at = $EndedAt
        duration_seconds = $durationSeconds
        search_text = ($searchText -join " ")
        tags = @($tags)
    }
}

function Get-RuntimeScenePackageSummary {
    param(
        [hashtable]$Manifest,
        [hashtable]$PackageIndex
    )

    $status = Get-RuntimeSceneEffectiveStatus -Status ([string]$Manifest.status) -EndedAt ([string]$Manifest.ended_at) -Default "unknown"

    $timelineEvents = Get-RuntimeSceneJsonlEventCount -RelativePath "timeline.jsonl"
    $lifecycleEvents = Get-RuntimeSceneJsonlEventCount -RelativePath "lifecycle.jsonl"
    $severity = Get-RuntimeSceneSeverityCounts -RelativePath "timeline.jsonl"
    $supervisedLogCount = (Get-RuntimeSceneChildFileCount -RelativePath "agent/supervised_runs") + (Get-RuntimeSceneChildFileCount -RelativePath "agent/supervised_worktree_runs")
    $selfEvolutionLogCount = Get-RuntimeSceneChildFileCount -RelativePath "agent/self_evolution_runs"

    return @{
        schema_version = 1
        package_id = [string]$PackageIndex.package_id
        display_name = [string]$PackageIndex.display_name
        index_key = [string]$PackageIndex.index_key
        status = $status
        result = Get-HashtableStringValue -Table $Manifest -Key "result"
        stop_reason = Get-HashtableStringValue -Table $Manifest -Key "stop_reason"
        trigger = Get-HashtableStringValue -Table $Manifest -Key "trigger"
        started_at = [string]$PackageIndex.started_at
        started_at_local = [string]$PackageIndex.started_at_local
        started_date = [string]$PackageIndex.started_date
        started_time = [string]$PackageIndex.started_time
        ended_at = [string]$PackageIndex.ended_at
        duration_seconds = $PackageIndex.duration_seconds
        event_counts = @{
            timeline_events = $timelineEvents
            lifecycle_events = $lifecycleEvents
            raw_logs = Get-RuntimeSceneChildFileCount -RelativePath "raw"
            conversation_logs = Get-RuntimeSceneChildFileCount -RelativePath "conversations"
            agent_logs = Get-RuntimeSceneChildFileCount -RelativePath "agent"
            artifacts = Get-RuntimeSceneChildFileCount -RelativePath "artifacts"
            event_logs = Get-RuntimeSceneChildFileCount -RelativePath "events"
            supervised_evolution_logs = $supervisedLogCount
            self_evolution_logs = $selfEvolutionLogCount
            errors = $severity.Errors
            warnings = $severity.Warnings
        }
        primary_files = @{
            summary = "summary.json"
            package_index = "package_index.json"
            manifest = "manifest.json"
            timeline = "timeline.jsonl"
            lifecycle = "lifecycle.jsonl"
            startup = "raw/desktop-entry.log"
        }
        sections = @{
            startup = @{
                path = "raw/desktop-entry.log"
                vbs_path = "raw/desktop-entry-vbs.log"
                launcher_path = "raw/launcher-control.log"
                purpose = "Desktop entry, launcher handoff, runtime manager, backend, browser, and supervisor startup breadcrumbs."
            }
            lifecycle = @{
                path = "lifecycle.jsonl"
                purpose = "Workbench startup, shutdown, recovery, supervision, and lifecycle state changes."
            }
            timeline = @{
                path = "timeline.jsonl"
                purpose = "Merged chronological event stream for the whole runtime scene package."
            }
            raw = @{
                path = "raw"
                purpose = "Raw launcher, backend, frontend, browser, supervisor, and API output."
            }
            conversations = @{
                path = "conversations"
                purpose = "Per-session user, assistant, tool-call, and chat-review conversation breadcrumbs."
            }
            agent = @{
                path = "agent"
                purpose = "Agent turn and tool-call child logs used to diagnose reasoning and execution flow."
            }
            supervised_evolution = @{
                path = "agent/supervised_runs"
                worktree_path = "agent/supervised_worktree_runs"
                purpose = "Supervised evolution run, candidate, review, selection, promotion, and rollback breadcrumbs when present."
            }
            self_evolution = @{
                path = "agent/self_evolution_runs"
                purpose = "Unsupervised self-evolution run, checkpoint, reflection, guard, and validation breadcrumbs when present."
            }
            artifacts = @{
                path = "artifacts"
                purpose = "Reports, generated files, snapshots, and other run artifacts referenced by events."
            }
            events = @{
                path = "events"
                purpose = "Component-specific structured event streams backing the merged timeline."
            }
        }
        diagnostic_entrypoint = @{
            first_read = "summary.json"
            purpose = "Agent first-read summary for reconstructing this lifecycle package before opening child logs."
            recommended_order = @(
                "summary.json",
                "package_index.json",
                "raw/desktop-entry-vbs.log",
                "raw/desktop-entry.log",
                "raw/launcher-control.log",
                "timeline.jsonl",
                "lifecycle.jsonl",
                "conversations/",
                "agent/turns.jsonl",
                "agent/tool_calls.jsonl",
                "agent/supervised_runs/",
                "agent/supervised_worktree_runs/",
                "agent/self_evolution_runs/",
                "raw/",
                "artifacts/"
            )
        }
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
    }
}

function Get-HashtableStringValue {
    param(
        [hashtable]$Table,
        [string]$Key,
        [string]$Default = ""
    )

    if ($Table -and $Table.ContainsKey($Key)) {
        return [string]$Table[$Key]
    }
    return $Default
}

function Get-RuntimeSceneJsonlEventCount {
    param([string]$RelativePath)

    if (-not $script:currentRuntimeSceneDir) {
        return 0
    }
    try {
        $target = Get-CurrentRuntimeSceneFilePath $RelativePath
        if (-not (Test-Path -LiteralPath $target)) {
            return 0
        }
        $item = Get-Item -LiteralPath $target -ErrorAction Stop
        if ($item.PSIsContainer) {
            return 0
        }
        return @(
            Get-Content -LiteralPath $target -Encoding UTF8 -ErrorAction Stop |
                Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) }
        ).Count
    } catch {
        return 0
    }
}

function Get-RuntimeSceneSeverityCounts {
    param([string]$RelativePath)

    $counts = @{
        Errors = 0
        Warnings = 0
    }
    if (-not $script:currentRuntimeSceneDir) {
        return $counts
    }
    try {
        $target = Get-CurrentRuntimeSceneFilePath $RelativePath
        if (-not (Test-Path -LiteralPath $target)) {
            return $counts
        }
        foreach ($line in Get-Content -LiteralPath $target -Encoding UTF8 -ErrorAction Stop) {
            if ([string]::IsNullOrWhiteSpace([string]$line)) {
                continue
            }
            try {
                $event = $line | ConvertFrom-Json -ErrorAction Stop
            } catch {
                continue
            }
            $severity = Get-RuntimeSceneEventSeverity -Event $event
            if ($severity -eq "error") {
                $counts.Errors += 1
            } elseif ($severity -eq "warning") {
                $counts.Warnings += 1
            }
        }
    } catch {
        return $counts
    }
    return $counts
}

function Get-RuntimeSceneEventSeverity {
    param($Event)

    $payload = ConvertTo-PlainHashtable $Event
    $level = ([string]$(if ($payload.ContainsKey("level")) { $payload["level"] } else { "" })).Trim().ToLowerInvariant()
    $outcome = ([string]$(if ($payload.ContainsKey("outcome")) { $payload["outcome"] } else { "" })).Trim().ToLowerInvariant()
    $status = ([string]$(if ($payload.ContainsKey("status")) { $payload["status"] } else { "" })).Trim().ToLowerInvariant()
    $fieldStatus = ""
    $fieldOutcome = ""
    $hasErrorMarker = $false
    if ($payload.ContainsKey("fields") -and $null -ne $payload["fields"]) {
        $fields = ConvertTo-PlainHashtable $payload["fields"]
        $fieldStatusRaw = ""
        if ($fields.ContainsKey("status")) {
            $fieldStatusRaw = $fields["status"]
        } elseif ($fields.ContainsKey("resultStatus")) {
            $fieldStatusRaw = $fields["resultStatus"]
        }
        $fieldStatus = ([string]$fieldStatusRaw).Trim().ToLowerInvariant()
        $fieldOutcome = ([string]$(if ($fields.ContainsKey("outcome")) { $fields["outcome"] } else { "" })).Trim().ToLowerInvariant()
        foreach ($name in @("error", "errorType", "exceptionType", "exceptionMessage", "failureMessage")) {
            if ($fields.ContainsKey($name) -and -not [string]::IsNullOrWhiteSpace([string]$fields[$name])) {
                $hasErrorMarker = $true
                break
            }
        }
    }

    if (@("warning", "warn") -contains $level) {
        return "warning"
    }
    if (@("error", "fatal", "critical") -contains $level) {
        return "error"
    }
    if (@("error", "failed", "failure") -contains $outcome -or @("error", "failed", "failure") -contains $fieldOutcome) {
        return "error"
    }
    if (@("error", "failed") -contains $status -or @("error", "failed") -contains $fieldStatus) {
        return "error"
    }
    if (@("warning", "warn", "partial", "client_error", "degraded") -contains $outcome -or @("warning", "warn", "partial", "client_error", "degraded") -contains $fieldOutcome) {
        return "warning"
    }
    if (@("warning", "warn", "partial", "degraded") -contains $status -or @("warning", "warn", "partial", "degraded") -contains $fieldStatus) {
        return "warning"
    }
    if ($hasErrorMarker) {
        return "error"
    }
    return "info"
}

function Get-RuntimeSceneChildFileCount {
    param([string]$RelativePath)

    if (-not $script:currentRuntimeSceneDir) {
        return 0
    }
    try {
        $target = Get-CurrentRuntimeSceneFilePath $RelativePath
        if (-not (Test-Path $target)) {
            return 0
        }
        $item = Get-Item -LiteralPath $target -ErrorAction Stop
        if (-not $item.PSIsContainer) {
            return 1
        }
        return @(
            Get-ChildItem -LiteralPath $target -File -Recurse -ErrorAction SilentlyContinue
        ).Count
    } catch {
        return 0
    }
}

function New-RuntimeSceneId {
    return ([guid]::NewGuid().ToString("N")).Substring(0, 12)
}

function ConvertTo-PlainHashtable {
    param($Value)

    if ($null -eq $Value) {
        return @{}
    }
    if ($Value -is [System.Collections.IDictionary]) {
        $result = @{}
        foreach ($key in $Value.Keys) {
            $current = $Value[$key]
            if ($current -is [System.Collections.IDictionary] -or $current -is [pscustomobject]) {
                $result[$key] = ConvertTo-PlainHashtable $current
            } else {
                $result[$key] = $current
            }
        }
        return $result
    }

    $properties = @($Value.PSObject.Properties)
    if ($properties.Count -eq 0) {
        return @{}
    }

    $result = @{}
    foreach ($prop in $properties) {
        $current = $prop.Value
        if ($current -is [System.Collections.IDictionary] -or $current -is [pscustomobject]) {
            $result[$prop.Name] = ConvertTo-PlainHashtable $current
        } else {
            $result[$prop.Name] = $current
        }
    }
    return $result
}

function Merge-HashtableRecursively {
    param(
        [hashtable]$Base,
        [hashtable]$Changes
    )

    foreach ($key in $Changes.Keys) {
        $nextValue = $Changes[$key]
        if ($nextValue -is [System.Collections.IDictionary]) {
            $childBase = @{}
            if ($Base.ContainsKey($key) -and $Base[$key] -is [System.Collections.IDictionary]) {
                $childBase = ConvertTo-PlainHashtable $Base[$key]
            }
            $Base[$key] = Merge-HashtableRecursively -Base $childBase -Changes (ConvertTo-PlainHashtable $nextValue)
        } else {
            $Base[$key] = $nextValue
        }
    }
    return $Base
}

function Get-RuntimeSceneRelativePaths {
    return @{
        DesktopEntry = "raw/desktop-entry.log"
        DesktopEntryVbs = "raw/desktop-entry-vbs.log"
        LauncherControl = "raw/launcher-control.log"
        FrontendBuild = "raw/frontend.build.log"
        BackendStdout = "raw/backend.stdout.log"
        BackendStderr = "raw/backend.stderr.log"
        Supervisor = "raw/supervisor.log"
        SupervisorStderr = "raw/supervisor.stderr.log"
        Browser = "raw/browser.log"
    }
}

function Set-CurrentRuntimeSceneContext {
    param(
        [string]$SceneId,
        [string]$SceneDir
    )

    $script:currentRuntimeSceneId = $SceneId
    $script:currentRuntimeSceneDir = $SceneDir
}

function Save-ActiveRuntimeSceneReference {
    param(
        [string]$SceneId,
        [string]$SceneDir,
        [string]$Trigger
    )

    if (-not $SceneId -or -not $SceneDir) {
        return
    }

    $payload = @{
        runtimeSceneId = $SceneId
        runtimeSceneDir = $SceneDir
        trigger = $Trigger
        startedAt = (Get-Date).ToUniversalTime().ToString("o")
        launcherPid = $PID
    }
    $payloadJson = $payload | ConvertTo-Json -Depth 6
    Write-LauncherStateFile -Path $activeRuntimeScenePath -Value $payloadJson
}

function Restore-RuntimeSceneContextFromState {
    $state = Get-State
    if (-not $state) {
        return $false
    }
    $sceneId = [string]$state.runtimeSceneId
    $sceneDir = [string]$state.runtimeSceneDir
    if (-not $sceneId -or -not $sceneDir) {
        return $false
    }
    Set-CurrentRuntimeSceneContext -SceneId $sceneId -SceneDir $sceneDir
    return $true
}

function Get-CurrentRuntimeSceneFilePath {
    param([string]$RelativePath)

    if (-not $script:currentRuntimeSceneDir) {
        throw "No runtime scene is active."
    }
    return Join-Path $script:currentRuntimeSceneDir $RelativePath
}

function Ensure-CurrentRuntimeSceneSubdirs {
    if (-not $script:currentRuntimeSceneDir) {
        return
    }
    foreach ($path in @(
        $script:currentRuntimeSceneDir,
        (Join-Path $script:currentRuntimeSceneDir "events"),
        (Join-Path $script:currentRuntimeSceneDir "raw"),
        (Join-Path $script:currentRuntimeSceneDir "conversations"),
        (Join-Path $script:currentRuntimeSceneDir "agent"),
        (Join-Path $script:currentRuntimeSceneDir "artifacts")
    )) {
        if (-not (Test-Path $path)) {
            New-Item -ItemType Directory -Path $path -Force | Out-Null
        }
    }
}

function Save-RuntimeSceneManifest {
    param([hashtable]$Manifest)

    Ensure-CurrentRuntimeSceneSubdirs
    if ($Manifest.ContainsKey("started_at")) {
        try {
            $startedAt = [datetime]$Manifest.started_at
            $status = Get-HashtableStringValue -Table $Manifest -Key "status"
            $result = Get-HashtableStringValue -Table $Manifest -Key "result"
            $stopReason = Get-HashtableStringValue -Table $Manifest -Key "stop_reason"
            $endedAt = Get-HashtableStringValue -Table $Manifest -Key "ended_at"
            $packageIndex = Get-RuntimeScenePackageIndex `
                -SceneId ([string]$Manifest.runtime_scene_id) `
                -StartedAt $startedAt `
                -Trigger ([string]$Manifest.trigger) `
                -Status $status `
                -Result $result `
                -StopReason $stopReason `
                -EndedAt $endedAt
            $package = @{}
            if ($Manifest.ContainsKey("package") -and $Manifest.package -is [System.Collections.IDictionary]) {
                $package = ConvertTo-PlainHashtable $Manifest.package
            }
            $package.index_schema_version = $packageIndex.schema_version
            $package.package_id = $packageIndex.package_id
            $package.display_name = $packageIndex.display_name
            $package.index_key = $packageIndex.index_key
            $package.sortable_timestamp = $packageIndex.sortable_timestamp
            $package.started_at = $packageIndex.started_at
            $package.started_at_local = $packageIndex.started_at_local
            $package.started_date = $packageIndex.started_date
            $package.started_time = $packageIndex.started_time
            $package.ended_at = $packageIndex.ended_at
            $package.duration_seconds = $packageIndex.duration_seconds
            $package.search_text = $packageIndex.search_text
            $package.tags = $packageIndex.tags
            $package.package_index_path = "package_index.json"
            $package.summary_path = "summary.json"
            $Manifest.package = $package
            $packageIndexPath = Get-CurrentRuntimeSceneFilePath "package_index.json"
            [void](Write-RuntimeSceneJsonFile -Path $packageIndexPath -Value $packageIndex -Depth 8)
            $summary = Get-RuntimeScenePackageSummary -Manifest $Manifest -PackageIndex $packageIndex
            $summaryPath = Get-CurrentRuntimeSceneFilePath "summary.json"
            [void](Write-RuntimeSceneJsonFile -Path $summaryPath -Value $summary -Depth 12)
        } catch {
        }
    }
    $manifestPath = Get-CurrentRuntimeSceneFilePath "manifest.json"
    [void](Write-RuntimeSceneJsonFile -Path $manifestPath -Value $Manifest -Depth 8)
}

function Write-RuntimeSceneJsonFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        $Value,
        [int]$Depth = 8
    )

    $targetDir = Split-Path -Parent $Path
    if (-not (Test-Path $targetDir)) {
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    }

    $payloadJson = $Value | ConvertTo-Json -Depth $Depth
    $maxAttempts = [Math]::Max(1, [int]$script:runtimeSceneWriteMaxAttempts)
    $delayMilliseconds = [Math]::Max(0, [int]$script:runtimeSceneWriteRetryDelayMilliseconds)
    $lastError = $null

    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        $tempName = ".{0}.{1}.{2}.tmp" -f (Split-Path -Leaf $Path), $PID, ([guid]::NewGuid().ToString("N"))
        $tempPath = Join-Path $targetDir $tempName
        try {
            $utf8NoBom = New-Object System.Text.UTF8Encoding -ArgumentList $false
            [System.IO.File]::WriteAllText($tempPath, $payloadJson, $utf8NoBom)
            Move-Item -LiteralPath $tempPath -Destination $Path -Force -ErrorAction Stop

            if ($attempt -gt 1) {
                Write-LauncherControlLog `
                    -Event "launcher.runtime_scene.write.recovered" `
                    -Message "Runtime scene JSON write recovered after retry." `
                    -Level "warning" `
                    -Fields @{ path = $Path; attempts = $attempt }
            }
            return $true
        } catch {
            $lastError = $_.Exception
            if ($tempPath -and (Test-Path $tempPath)) {
                Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
            }
            if ($attempt -lt $maxAttempts) {
                Start-Sleep -Milliseconds $delayMilliseconds
            }
        }
    }

    $errorMessage = if ($lastError) { $lastError.Message } else { "unknown error" }
    Write-LauncherControlLog `
        -Event "launcher.runtime_scene.write.failed" `
        -Message "Runtime scene JSON write failed after retries." `
        -Level "warning" `
        -Fields @{ path = $Path; attempts = $maxAttempts; error = $errorMessage }
    return $false
}

function Write-RuntimeSceneTextLine {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Value,
        [string]$Kind = "jsonl"
    )

    $targetDir = Split-Path -Parent $Path
    if (-not (Test-Path $targetDir)) {
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    }

    $maxAttempts = [Math]::Max(1, [int]$script:runtimeSceneWriteMaxAttempts)
    $delayMilliseconds = [Math]::Max(0, [int]$script:runtimeSceneWriteRetryDelayMilliseconds)
    $lastError = $null

    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        try {
            Add-Content -LiteralPath $Path -Value $Value -Encoding utf8 -ErrorAction Stop
            if ($attempt -gt 1) {
                Write-LauncherControlLog `
                    -Event "launcher.runtime_scene.append.recovered" `
                    -Message "Runtime scene append recovered after retry." `
                    -Level "warning" `
                    -Fields @{ path = $Path; kind = $Kind; attempts = $attempt }
            }
            return $true
        } catch {
            $lastError = $_.Exception
            if ($attempt -lt $maxAttempts) {
                Start-Sleep -Milliseconds $delayMilliseconds
            }
        }
    }

    $errorMessage = if ($lastError) { $lastError.Message } else { "unknown error" }
    Write-LauncherControlLog `
        -Event "launcher.runtime_scene.append.failed" `
        -Message "Runtime scene append failed after retries." `
        -Level "warning" `
        -Fields @{ path = $Path; kind = $Kind; attempts = $maxAttempts; error = $errorMessage }
    return $false
}

function Get-RuntimeSceneManifest {
    if (-not $script:currentRuntimeSceneDir) {
        return @{}
    }

    $manifestPath = Get-CurrentRuntimeSceneFilePath "manifest.json"
    if (-not (Test-Path $manifestPath)) {
        return @{}
    }

    try {
        return ConvertTo-PlainHashtable (Get-Content $manifestPath -Raw | ConvertFrom-Json)
    } catch {
        return @{}
    }
}

function Update-RuntimeSceneManifest {
    param([hashtable]$Changes)

    if (-not $script:currentRuntimeSceneDir) {
        return
    }
    $manifest = Get-RuntimeSceneManifest
    if (-not ($manifest -is [System.Collections.IDictionary])) {
        $manifest = @{}
    }
    $merged = Merge-HashtableRecursively -Base (ConvertTo-PlainHashtable $manifest) -Changes (ConvertTo-PlainHashtable $Changes)
    Save-RuntimeSceneManifest -Manifest $merged
}

function Append-RuntimeSceneRawLog {
    param(
        [string]$RelativePath,
        [string]$Message
    )

    if (-not $script:currentRuntimeSceneDir) {
        return
    }

    Ensure-CurrentRuntimeSceneSubdirs
    $targetPath = Get-CurrentRuntimeSceneFilePath $RelativePath
    $targetDir = Split-Path -Parent $targetPath
    if (-not (Test-Path $targetDir)) {
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    }
    [void](Write-RuntimeSceneTextLine `
        -Path $targetPath `
        -Value "[$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss.fff'))] $Message" `
        -Kind "raw_log")
}

function New-RuntimeSceneRawRef {
    param(
        [string]$RelativePath,
        [int]$TailLines = 40
    )

    return @{
        path = $RelativePath
        tail_lines = $TailLines
    }
}

function Test-RuntimeSceneLifecycleEvent {
    param([hashtable]$Payload)

    $phase = ([string]$Payload.phase).Trim().ToLowerInvariant()
    $eventCode = ([string]$Payload.event_code).Trim()
    $component = ([string]$Payload.component).Trim().ToLowerInvariant()
    if ($eventCode.StartsWith("runtime.scene.")) {
        return $true
    }
    if (@(
        "session",
        "startup",
        "shutdown",
        "build",
        "health",
        "supervision",
        "dependencies",
        "python_dependencies",
        "window",
        "api",
        "desktop_monitor",
        "lifecycle",
        "navigation"
    ) -contains $phase) {
        return $true
    }
    return (@("launcher", "supervisor") -contains $component) -and (@("session", "shutdown") -contains $phase)
}

function Write-RuntimeSceneEvent {
    param(
        [string]$Component,
        [string]$Phase,
        [string]$EventCode,
        [string]$Message,
        [string]$Level = "info",
        [string]$Outcome = "observed",
        [hashtable]$Fields = @{},
        [object[]]$RawRefs = @()
    )

    if (-not $script:currentRuntimeSceneDir -or -not $script:currentRuntimeSceneId) {
        return
    }

    Ensure-CurrentRuntimeSceneSubdirs
    $sequenceKey = ([string]$Component).ToLowerInvariant()
    if (-not $script:sceneEventSequence.ContainsKey($sequenceKey)) {
        $script:sceneEventSequence[$sequenceKey] = 0
    }
    $script:sceneEventSequence[$sequenceKey] = [int]$script:sceneEventSequence[$sequenceKey] + 1

    $payload = @{
        schema_version = $sceneSchemaVersion
        runtime_scene_id = $script:currentRuntimeSceneId
        ts = (Get-Date).ToUniversalTime().ToString("o")
        seq = [int]$script:sceneEventSequence[$sequenceKey]
        component = $Component
        phase = $Phase
        event_code = $EventCode
        level = $Level
        outcome = $Outcome
        message = $Message
        fields = if ($Fields) { $Fields } else { @{} }
        raw_refs = if ($RawRefs) { @($RawRefs) } else { @() }
    }

    $eventsPath = Get-CurrentRuntimeSceneFilePath ("events/{0}.jsonl" -f $sequenceKey)
    $payloadJson = $payload | ConvertTo-Json -Depth 8 -Compress
    [void](Write-RuntimeSceneTextLine -Path $eventsPath -Value $payloadJson -Kind "component_event")
    [void](Write-RuntimeSceneTextLine -Path (Get-CurrentRuntimeSceneFilePath "timeline.jsonl") -Value $payloadJson -Kind "timeline")
    if (Test-RuntimeSceneLifecycleEvent -Payload $payload) {
        [void](Write-RuntimeSceneTextLine -Path (Get-CurrentRuntimeSceneFilePath "lifecycle.jsonl") -Value $payloadJson -Kind "lifecycle")
    }
}

function Initialize-RuntimeScene {
    param(
        [string]$Trigger,
        [bool]$BrowserManaged
    )

    Ensure-Directories
    $startedAt = (Get-Date).ToUniversalTime()
    $sceneId = New-RuntimeSceneId
    $directoryName = "{0}__{1}" -f (ConvertTo-PortableTimestampToken $startedAt), $sceneId
    $sceneDir = Join-Path $runtimeSceneRoot $directoryName
    Set-CurrentRuntimeSceneContext -SceneId $sceneId -SceneDir $sceneDir
    Ensure-CurrentRuntimeSceneSubdirs
    Save-ActiveRuntimeSceneReference -SceneId $sceneId -SceneDir $sceneDir -Trigger $Trigger
    $packageIndex = Get-RuntimeScenePackageIndex -SceneId $sceneId -StartedAt $startedAt -Trigger $Trigger -Status "running"

    $rawPaths = Get-RuntimeSceneRelativePaths
    foreach ($relativePath in $rawPaths.Values) {
        $targetPath = Get-CurrentRuntimeSceneFilePath $relativePath
        $targetDir = Split-Path -Parent $targetPath
        if (-not (Test-Path $targetDir)) {
            New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
        }
        Set-Content -Path $targetPath -Value "" -Encoding utf8
    }

    Save-RuntimeSceneManifest -Manifest @{
        schema_version = $sceneSchemaVersion
        runtime_scene_id = $sceneId
        title = "Managed workbench run $sceneId"
        package = @{
            schema_version = 2
            index_schema_version = $packageIndex.schema_version
            package_id = $packageIndex.package_id
            display_name = $packageIndex.display_name
            index_key = $packageIndex.index_key
            sortable_timestamp = $packageIndex.sortable_timestamp
            started_at = $packageIndex.started_at
            started_at_local = $packageIndex.started_at_local
            started_date = $packageIndex.started_date
            started_time = $packageIndex.started_time
            ended_at = $packageIndex.ended_at
            duration_seconds = $packageIndex.duration_seconds
            search_text = $packageIndex.search_text
            tags = $packageIndex.tags
            package_index_path = "package_index.json"
            summary_path = "summary.json"
            timeline_path = "timeline.jsonl"
            lifecycle_path = "lifecycle.jsonl"
            raw_dir = "raw"
            conversations_dir = "conversations"
            agent_dir = "agent"
            artifacts_dir = "artifacts"
            entry_log_path = $rawPaths.DesktopEntry
            entry_vbs_log_path = $rawPaths.DesktopEntryVbs
            updated_at = $startedAt.ToString("o")
        }
        started_at = $startedAt.ToString("o")
        ended_at = ""
        status = "running"
        result = ""
        stop_reason = ""
        trigger = $Trigger
        session_mode = "managed"
        project_root = $projectDir
        host = $bindHost
        port = $port
        url = $url
        frontend = @{
            build_status = "pending"
            build_reason = ""
            log_path = $rawPaths.FrontendBuild
        }
        backend = @{
            pid = 0
            health_status = "pending"
            stdout_path = $rawPaths.BackendStdout
            stderr_path = $rawPaths.BackendStderr
        }
        browser = @{
            managed = $BrowserManaged
            status = if ($BrowserManaged) { "pending" } else { "disabled" }
            log_path = $rawPaths.Browser
            executable = ""
            launch_pid = 0
            window_pid = 0
        }
        launcher = @{
            control_log_path = $rawPaths.LauncherControl
            entry_log_path = $rawPaths.DesktopEntry
            entry_vbs_log_path = $rawPaths.DesktopEntryVbs
            visible_monitor = "not_started"
        }
        supervisor = @{
            pid = 0
            status = if ($BrowserManaged) { "pending" } else { "disabled" }
            log_path = $rawPaths.Supervisor
        }
    }

    Write-RuntimeSceneEvent `
        -Component "launcher" `
        -Phase "session" `
        -EventCode "runtime.scene.created" `
        -Message "Created runtime scene bundle." `
        -Outcome "started" `
        -Fields @{
            directory_name = $directoryName
            browser_managed = $BrowserManaged
            trigger = $Trigger
        }
}

function Get-RuntimeSceneFinalState {
    param([string]$Reason)

    $normalized = ([string]$Reason).Trim().ToLowerInvariant()
    if ($normalized -match "startup failure") {
        return @{ status = "failed"; result = "startup_failed" }
    }
    if ($normalized -match "backend exited") {
        return @{ status = "failed"; result = "backend_exited" }
    }
    if ($normalized -match "app window closed") {
        return @{ status = "stopped"; result = "browser_window_closed" }
    }
    return @{ status = "stopped"; result = ($normalized -replace "[^a-z0-9]+", "_").Trim('_') }
}

function Get-StringHash {
    param([string]$Value)

    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
        return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Get-FileFingerprint {
    param([string[]]$Paths)

    $parts = New-Object System.Collections.Generic.List[string]
    foreach ($path in @($Paths | Where-Object { $_ })) {
        if (-not (Test-Path $path)) {
            [void]$parts.Add("$path|missing")
            continue
        }

        $item = Get-Item $path
        if ($item -is [System.IO.DirectoryInfo]) {
            throw "Get-FileFingerprint only accepts files. Received directory: $path"
        }

        $hash = (Get-FileHash -Path $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        [void]$parts.Add("$($item.FullName)|$($item.Length)|$hash")
    }

    return Get-StringHash -Value ($parts -join "`n")
}

function Get-StoredStampValue {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return $null
    }

    return (Get-Content $Path -Raw).Trim()
}

function Set-StoredStampValue {
    param(
        [string]$Path,
        [string]$Value
    )

    Ensure-Directories
    Set-Content -Path $Path -Value $Value -Encoding ascii
}

function Get-RuntimeManagerState {
    if (-not (Test-Path $runtimeManagerStatePath)) {
        return $null
    }

    try {
        return Get-Content $runtimeManagerStatePath -Raw | ConvertFrom-Json
    } catch {
        Write-LauncherControlLog `
            -Event "launcher.monitor.runtime_manager_state_unreadable" `
            -Message "Runtime manager state file is unreadable." `
            -Level "warning" `
            -Fields @{ path = $runtimeManagerStatePath; error = $_.Exception.Message }
        return $null
    }
}

function Get-RuntimeManagerWorkbench {
    $managerState = Get-RuntimeManagerState
    if (-not $managerState) {
        return $null
    }

    return Get-ObjectPropertyValue -Object $managerState -Name "workbench" -Default $null
}

function Get-RuntimeManagerWorkbenchReason {
    param(
        $Workbench,
        [string]$Fallback = "workbench lifecycle closed"
    )

    $reason = [string](Get-ObjectPropertyValue -Object $Workbench -Name "lastReason" -Default "")
    if ($reason) {
        return $reason
    }
    return $Fallback
}

function Get-RuntimeManagerWorkbenchSource {
    param(
        $Workbench,
        [string]$Fallback = "runtime_manager"
    )

    $source = [string](Get-ObjectPropertyValue -Object $Workbench -Name "lastSource" -Default "")
    if ($source) {
        return $source
    }
    return $Fallback
}

function Wait-ForRuntimeManagerWorkbenchOpen {
    param([int]$TimeoutSeconds = 45)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $workbench = Get-RuntimeManagerWorkbench
        if ($workbench) {
            $desiredState = [string](Get-ObjectPropertyValue -Object $workbench -Name "desiredState" -Default "")
            $observedState = [string](Get-ObjectPropertyValue -Object $workbench -Name "observedState" -Default "")
            $phase = [string](Get-ObjectPropertyValue -Object $workbench -Name "phase" -Default "")
            if ($desiredState -eq "open" -and $observedState -eq "open" -and $phase -eq "steady") {
                return $true
            }
            if ($phase -eq "failed") {
                return $false
            }
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Get-LatestInputTimeUtc {
    param(
        [string[]]$Paths,
        [string[]]$Extensions = @()
    )

    $normalizedExtensions = @($Extensions | Where-Object { $_ } | ForEach-Object { $_.ToLowerInvariant() })
    $latestInput = [datetime]::MinValue

    foreach ($path in @($Paths | Where-Object { $_ })) {
        if (-not (Test-Path $path)) {
            continue
        }

        $rootItem = Get-Item $path
        $items = @()
        if ($rootItem -is [System.IO.DirectoryInfo]) {
            $items = @(Get-ChildItem $path -Recurse -File)
        } else {
            $items = @($rootItem)
        }

        foreach ($item in $items) {
            if ($normalizedExtensions.Count -gt 0 -and ($normalizedExtensions -notcontains $item.Extension.ToLowerInvariant())) {
                continue
            }
            if ($item.LastWriteTimeUtc -gt $latestInput) {
                $latestInput = $item.LastWriteTimeUtc
            }
        }
    }

    return $latestInput
}

function Get-FrontendInputTimeUtc {
    return Get-LatestInputTimeUtc -Paths @(
        (Join-Path $webDir "src"),
        (Join-Path $webDir "public"),
        (Join-Path $webDir "package.json"),
        (Join-Path $webDir "package-lock.json"),
        (Join-Path $webDir "tsconfig.json"),
        (Join-Path $webDir "tsconfig.app.json"),
        (Join-Path $webDir "tsconfig.node.json"),
        (Join-Path $webDir "vite.config.ts"),
        (Join-Path $webDir "vite.config.js")
    )
}

function Get-BackendInputTimeUtc {
    return Get-LatestInputTimeUtc `
        -Paths @(
            (Join-Path $projectDir "agent.py"),
            (Join-Path $projectDir "core"),
            (Join-Path $projectDir "scripts"),
            (Join-Path $projectDir "config"),
            $requirementsPath,
            (Join-Path $projectDir "config.toml")
        ) `
        -Extensions @(".py", ".ps1", ".psm1", ".json", ".toml", ".txt", ".html", ".css", ".js", ".ts", ".tsx")
}

function Get-WebDistTimeUtc {
    if (-not (Test-Path $webDistIndex)) {
        return [datetime]::MinValue
    }

    return (Get-Item $webDistIndex).LastWriteTimeUtc
}

function Acquire-LauncherMutex {
    if ($Action -eq "supervise" -or $Action -eq "monitor") {
        return
    }

    $script:launcherMutex = New-Object System.Threading.Mutex($false, $mutexName)
    $acquired = $script:launcherMutex.WaitOne([TimeSpan]::FromSeconds(30))
    if (-not $acquired) {
        throw "Another Vibelution launcher action is still running. Try again in a moment."
    }
}

function Release-LauncherMutex {
    if ($Action -eq "supervise" -or $Action -eq "monitor") {
        return
    }

    if ($script:launcherMutex) {
        try {
            $script:launcherMutex.ReleaseMutex() | Out-Null
        } catch {
        }
        $script:launcherMutex.Dispose()
    }
}

function Get-State {
    if (-not (Test-Path $statePath)) {
        return $null
    }

    try {
        return Get-Content $statePath -Raw | ConvertFrom-Json
    } catch {
        Write-Note "State file is unreadable. Removing stale launcher state."
        Remove-Item $statePath -Force -ErrorAction SilentlyContinue
        return $null
    }
}

function Write-LauncherStateFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    $targetDir = Split-Path -Parent $Path
    if (-not (Test-Path $targetDir)) {
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    }

    $maxAttempts = [Math]::Max(1, [int]$script:launcherStateWriteMaxAttempts)
    $delayMilliseconds = [Math]::Max(0, [int]$script:launcherStateWriteRetryDelayMilliseconds)
    $lastError = $null

    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        $tempName = ".{0}.{1}.{2}.tmp" -f (Split-Path -Leaf $Path), $PID, ([guid]::NewGuid().ToString("N"))
        $tempPath = Join-Path $targetDir $tempName
        try {
            $utf8NoBom = New-Object System.Text.UTF8Encoding -ArgumentList $false
            [System.IO.File]::WriteAllText($tempPath, $Value, $utf8NoBom)
            Move-Item -LiteralPath $tempPath -Destination $Path -Force -ErrorAction Stop

            if ($attempt -gt 1) {
                Write-LauncherControlLog `
                    -Event "launcher.state.write.recovered" `
                    -Message "Launcher state file write recovered after retry." `
                    -Level "warning" `
                    -Fields @{ path = $Path; attempts = $attempt }
            }
            return
        } catch {
            $lastError = $_.Exception
            if ($tempPath -and (Test-Path $tempPath)) {
                Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
            }
            if ($attempt -lt $maxAttempts) {
                Start-Sleep -Milliseconds $delayMilliseconds
            }
        }
    }

    $errorMessage = if ($lastError) { $lastError.Message } else { "unknown error" }
    Write-LauncherControlLog `
        -Event "launcher.state.write.failed" `
        -Message "Launcher state file write failed after retries." `
        -Level "error" `
        -Fields @{ path = $Path; attempts = $maxAttempts; error = $errorMessage }
    throw "Launcher state file write failed after $maxAttempts attempts: $errorMessage"
}

function Save-State {
    param([hashtable]$State)

    Ensure-Directories
    $payloadJson = $State | ConvertTo-Json -Depth 6
    Write-LauncherStateFile -Path $statePath -Value $payloadJson
}

function Remove-State {
    if (Test-Path $statePath) {
        Remove-Item $statePath -Force -ErrorAction SilentlyContinue
    }
}

function Test-ProcessAlive {
    param([int]$ProcessId)

    return $null -ne (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
}

function Stop-ProcessesById {
    param([int[]]$ProcessIds)

    foreach ($processId in @($ProcessIds | Sort-Object -Unique)) {
        if (-not $processId) {
            continue
        }
        $childPids = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $processId" -ErrorAction SilentlyContinue | ForEach-Object {
            [int]$_.ProcessId
        })
        if ($childPids.Count -gt 0) {
            Stop-ProcessesById -ProcessIds $childPids
        }
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
}

function Get-ListeningPid {
    param([int]$Port)

    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($listener) {
        return [int]$listener.OwningProcess
    }
    return $null
}

function Wait-ForPortClosed {
    param([int]$Port, [int]$TimeoutSeconds = 12)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-ListeningPid $Port)) {
            return $true
        }
        Start-Sleep -Milliseconds 250
    }
    return $false
}

function Wait-ForBackendHealthy {
    param(
        [int]$ProcessId,
        [int]$TimeoutSeconds = 25
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $liveness = Get-ManagedBackendLiveness -TrackedPid $ProcessId
        if ($liveness.Healthy) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Get-LogTail {
    param([string]$Path, [int]$Lines = 40)

    if (-not (Test-Path $Path)) {
        return ""
    }

    return ((Get-Content $Path -Tail $Lines) -join [Environment]::NewLine)
}

function Get-FrontendBuildFailureSummary {
    param([int]$ExitCode)

    $summary = "npm run build failed with exit code $ExitCode."
    if (-not $script:currentRuntimeSceneDir) {
        return $summary
    }
    $buildLogPath = Get-CurrentRuntimeSceneFilePath (Get-RuntimeSceneRelativePaths).FrontendBuild
    $tail = Get-LogTail -Path $buildLogPath -Lines 80
    if (-not $tail) {
        return $summary
    }
    $signalLines = @()
    foreach ($line in ($tail -split "\r?\n")) {
        $text = ([string]$line).Trim()
        if (-not $text) {
            continue
        }
        if ($text -match '(?i)(src|web[\\/]+src).+\(\d+,\d+\):\s+error\s+TS\d+' -or $text -match '(?i)\berror\s+TS\d+\b') {
            $signalLines += $text
        }
    }
    if ($signalLines.Count -gt 0) {
        $parts = @($summary, "frontend.build.failed") + @($signalLines | Select-Object -First 5)
        return $parts -join [Environment]::NewLine
    }
    return @($summary, "frontend.build.failed", $tail) -join [Environment]::NewLine
}

function Test-WebHealthy {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Resolve-NpmInvocation {
    $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
    if (-not $nodeCommand) {
        $nodeCommand = Get-Command node -ErrorAction SilentlyContinue
    }
    if (-not $nodeCommand -or -not $nodeCommand.Source) {
        throw "Node.js is not available on PATH."
    }

    $nodePath = [string]$nodeCommand.Source
    if (Test-Path -LiteralPath $nodePath) {
        $nodePath = (Resolve-Path -LiteralPath $nodePath).Path
    }

    $npmSources = New-Object System.Collections.Generic.List[string]
    foreach ($commandName in @("npm.cmd", "npm.ps1", "npm")) {
        $npmCommand = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($npmCommand -and $npmCommand.Source) {
            $source = [string]$npmCommand.Source
            if (Test-Path -LiteralPath $source) {
                $source = (Resolve-Path -LiteralPath $source).Path
            }
            if (-not $npmSources.Contains($source)) {
                [void]$npmSources.Add($source)
            }
        }
    }

    $npmCliCandidates = New-Object System.Collections.Generic.List[string]
    $nodeDir = Split-Path -Parent $nodePath
    if ($nodeDir) {
        [void]$npmCliCandidates.Add((Join-Path $nodeDir "node_modules\npm\bin\npm-cli.js"))
    }
    foreach ($source in $npmSources) {
        $sourceDir = Split-Path -Parent $source
        if ($sourceDir) {
            [void]$npmCliCandidates.Add((Join-Path $sourceDir "node_modules\npm\bin\npm-cli.js"))
        }
    }
    if ($env:APPDATA) {
        [void]$npmCliCandidates.Add((Join-Path $env:APPDATA "npm\node_modules\npm\bin\npm-cli.js"))
    }

    $seenCandidates = @{}
    foreach ($candidate in $npmCliCandidates) {
        if (-not $candidate -or $seenCandidates.ContainsKey($candidate)) {
            continue
        }
        $seenCandidates[$candidate] = $true
        if (Test-Path -LiteralPath $candidate) {
            $npmCliPath = (Resolve-Path -LiteralPath $candidate).Path
            return [pscustomobject]@{
                CommandPath = $nodePath
                PrefixArgs = @($npmCliPath)
                DisplayName = "node.exe npm-cli.js"
                SourceCommand = if ($npmSources.Count -gt 0) { $npmSources[0] } else { "" }
                LaunchStrategy = "node_npm_cli"
                ShellAdapter = "none"
            }
        }
    }

    $directNpm = $npmSources | Where-Object {
        $extension = [System.IO.Path]::GetExtension([string]$_).ToLowerInvariant()
        -not (@(".cmd", ".bat", ".ps1") -contains $extension)
    } | Select-Object -First 1
    if ($directNpm) {
        return [pscustomobject]@{
            CommandPath = [string]$directNpm
            PrefixArgs = @()
            DisplayName = [System.IO.Path]::GetFileName([string]$directNpm)
            SourceCommand = [string]$directNpm
            LaunchStrategy = "direct_executable"
            ShellAdapter = "none"
        }
    }

    throw "npm is available only through a shell wrapper. Install a standard Node.js/npm distribution so npm-cli.js can be launched through node.exe without opening cmd.exe."
}

function ConvertTo-ProcessArgument {
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

function ConvertTo-ProcessArgumentString {
    param([string[]]$ArgumentList = @())

    return (@($ArgumentList) | ForEach-Object { ConvertTo-ProcessArgument -Value $_ }) -join " "
}

function Get-SafeProcessArgumentPreview {
    param(
        [string[]]$ArgumentList = @(),
        [int]$MaxArguments = 8
    )

    $preview = New-Object System.Collections.Generic.List[string]
    $redactNext = $false
    $arguments = @($ArgumentList)
    for ($index = 0; $index -lt $arguments.Count -and $index -lt $MaxArguments; $index++) {
        $text = [string]$arguments[$index]
        if ($redactNext) {
            [void]$preview.Add("<redacted>")
            $redactNext = $false
            continue
        }
        if ($text -match '(?i)(api[_-]?key|token|secret|password|credential)') {
            if ($text -match '^(--?[^=]+)=') {
                [void]$preview.Add("$($Matches[1])=<redacted>")
            } else {
                [void]$preview.Add("<redacted>")
                $redactNext = $true
            }
            continue
        }
        if ($text.Length -gt 160) {
            $text = $text.Substring(0, 157) + "..."
        }
        [void]$preview.Add($text)
    }

    if ($arguments.Count -gt $MaxArguments) {
        [void]$preview.Add("...(+$($arguments.Count - $MaxArguments))")
    }
    return @($preview)
}

function Invoke-HiddenProcessCapture {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$ArgumentList = @(),
        [string]$WorkingDirectory = $projectDir
    )

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo.FileName = $FilePath
    $process.StartInfo.Arguments = ConvertTo-ProcessArgumentString -ArgumentList $ArgumentList
    $process.StartInfo.WorkingDirectory = $WorkingDirectory
    $process.StartInfo.UseShellExecute = $false
    $process.StartInfo.CreateNoWindow = $true
    $process.StartInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    $process.StartInfo.RedirectStandardOutput = $true
    $process.StartInfo.RedirectStandardError = $true

    if (-not $process.Start()) {
        throw "Failed to start hidden process: $FilePath"
    }

    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()
    $stdoutTask.Wait()
    $stderrTask.Wait()

    return [pscustomobject]@{
        ProcessId = [int]$process.Id
        ExitCode = [int]$process.ExitCode
        Stdout = [string]$stdoutTask.Result
        Stderr = [string]$stderrTask.Result
    }
}

function Start-HiddenBackgroundProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$ArgumentList = @(),
        [string]$WorkingDirectory = $projectDir
    )

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo.FileName = $FilePath
    $process.StartInfo.Arguments = ConvertTo-ProcessArgumentString -ArgumentList $ArgumentList
    $process.StartInfo.WorkingDirectory = $WorkingDirectory
    $process.StartInfo.UseShellExecute = $false
    $process.StartInfo.CreateNoWindow = $true
    $process.StartInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden

    if (-not $process.Start()) {
        throw "Failed to start hidden background process: $FilePath"
    }

    return $process
}

function Start-GuiProcessWithoutConsole {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$ArgumentList = @(),
        [string]$WorkingDirectory = $projectDir
    )

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo.FileName = $FilePath
    $process.StartInfo.Arguments = ConvertTo-ProcessArgumentString -ArgumentList $ArgumentList
    $process.StartInfo.WorkingDirectory = $WorkingDirectory
    $process.StartInfo.UseShellExecute = $false
    $process.StartInfo.CreateNoWindow = $true
    $process.StartInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Normal

    if (-not $process.Start()) {
        throw "Failed to start GUI process without console: $FilePath"
    }

    return $process
}

function Ensure-HiddenRedirectedProcessApi {
    if ("VibelutionLauncher.HiddenRedirectedProcess" -as [type]) {
        return
    }

    Add-Type @"
using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;

namespace VibelutionLauncher {
    public static class HiddenRedirectedProcess {
        private const uint GENERIC_WRITE = 0x40000000;
        private const uint FILE_SHARE_READ = 0x00000001;
        private const uint FILE_SHARE_WRITE = 0x00000002;
        private const uint CREATE_ALWAYS = 2;
        private const uint FILE_ATTRIBUTE_NORMAL = 0x00000080;
        private const uint STARTF_USESTDHANDLES = 0x00000100;
        private const uint STARTF_USESHOWWINDOW = 0x00000001;
        private const ushort SW_HIDE = 0;
        private const uint DETACHED_PROCESS = 0x00000008;
        private const uint CREATE_NEW_PROCESS_GROUP = 0x00000200;
        private const uint CREATE_NO_WINDOW = 0x08000000;

        [StructLayout(LayoutKind.Sequential)]
        private struct SECURITY_ATTRIBUTES {
            public int nLength;
            public IntPtr lpSecurityDescriptor;
            [MarshalAs(UnmanagedType.Bool)]
            public bool bInheritHandle;
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct STARTUPINFO {
            public int cb;
            public string lpReserved;
            public string lpDesktop;
            public string lpTitle;
            public int dwX;
            public int dwY;
            public int dwXSize;
            public int dwYSize;
            public int dwXCountChars;
            public int dwYCountChars;
            public int dwFillAttribute;
            public int dwFlags;
            public ushort wShowWindow;
            public ushort cbReserved2;
            public IntPtr lpReserved2;
            public IntPtr hStdInput;
            public IntPtr hStdOutput;
            public IntPtr hStdError;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct PROCESS_INFORMATION {
            public IntPtr hProcess;
            public IntPtr hThread;
            public int dwProcessId;
            public int dwThreadId;
        }

        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        private static extern bool CreateProcess(
            string lpApplicationName,
            string lpCommandLine,
            IntPtr lpProcessAttributes,
            IntPtr lpThreadAttributes,
            bool bInheritHandles,
            uint dwCreationFlags,
            IntPtr lpEnvironment,
            string lpCurrentDirectory,
            ref STARTUPINFO lpStartupInfo,
            out PROCESS_INFORMATION lpProcessInformation);

        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        private static extern IntPtr CreateFile(
            string lpFileName,
            uint dwDesiredAccess,
            uint dwShareMode,
            ref SECURITY_ATTRIBUTES lpSecurityAttributes,
            uint dwCreationDisposition,
            uint dwFlagsAndAttributes,
            IntPtr hTemplateFile);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool CloseHandle(IntPtr hObject);

        private static IntPtr OpenInheritableWriteHandle(string path) {
            SECURITY_ATTRIBUTES attributes = new SECURITY_ATTRIBUTES();
            attributes.nLength = Marshal.SizeOf(typeof(SECURITY_ATTRIBUTES));
            attributes.lpSecurityDescriptor = IntPtr.Zero;
            attributes.bInheritHandle = true;
            IntPtr handle = CreateFile(
                path,
                GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                ref attributes,
                CREATE_ALWAYS,
                FILE_ATTRIBUTE_NORMAL,
                IntPtr.Zero);
            if (handle == new IntPtr(-1)) {
                throw new Win32Exception(Marshal.GetLastWin32Error(), "Failed to open redirected process log file: " + path);
            }
            return handle;
        }

        public static int StartHiddenRedirected(string applicationName, string commandLine, string workingDirectory, string stdoutPath, string stderrPath) {
            IntPtr stdoutHandle = IntPtr.Zero;
            IntPtr stderrHandle = IntPtr.Zero;
            PROCESS_INFORMATION processInformation = new PROCESS_INFORMATION();
            try {
                stdoutHandle = OpenInheritableWriteHandle(stdoutPath);
                stderrHandle = OpenInheritableWriteHandle(String.IsNullOrWhiteSpace(stderrPath) ? stdoutPath : stderrPath);

                STARTUPINFO startupInfo = new STARTUPINFO();
                startupInfo.cb = Marshal.SizeOf(typeof(STARTUPINFO));
                startupInfo.dwFlags = (int)(STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW);
                startupInfo.wShowWindow = SW_HIDE;
                startupInfo.hStdInput = IntPtr.Zero;
                startupInfo.hStdOutput = stdoutHandle;
                startupInfo.hStdError = stderrHandle;

                bool started = CreateProcess(
                    applicationName,
                    commandLine,
                    IntPtr.Zero,
                    IntPtr.Zero,
                    true,
                    DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
                    IntPtr.Zero,
                    workingDirectory,
                    ref startupInfo,
                    out processInformation);
                if (!started) {
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "Failed to start hidden redirected process: " + applicationName);
                }
                return processInformation.dwProcessId;
            } finally {
                if (processInformation.hThread != IntPtr.Zero) {
                    CloseHandle(processInformation.hThread);
                }
                if (processInformation.hProcess != IntPtr.Zero) {
                    CloseHandle(processInformation.hProcess);
                }
                if (stdoutHandle != IntPtr.Zero) {
                    CloseHandle(stdoutHandle);
                }
                if (stderrHandle != IntPtr.Zero && stderrHandle != stdoutHandle) {
                    CloseHandle(stderrHandle);
                }
            }
        }
    }
}
"@
}

function Start-RedirectedBackgroundProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandPath,
        [string[]]$ArgumentList = @(),
        [Parameter(Mandatory = $true)]
        [string]$StdoutPath,
        [string]$StderrPath = "",
        [string]$WorkingDirectory = $projectDir
    )

    foreach ($logPath in @($StdoutPath, $StderrPath)) {
        if (-not $logPath) {
            continue
        }
        $logDir = Split-Path -Parent $logPath
        if ($logDir -and -not (Test-Path -LiteralPath $logDir)) {
            New-Item -ItemType Directory -Path $logDir -Force | Out-Null
        }
    }

    if ($StderrPath -and $StderrPath -eq $StdoutPath) {
        throw "Redirected background processes require distinct stdout and stderr log paths."
    }

    if (-not $StderrPath) {
        $StderrPath = $StdoutPath
    }

    Ensure-HiddenRedirectedProcessApi
    $commandLine = ConvertTo-ProcessArgumentString -ArgumentList @(@($CommandPath) + @($ArgumentList))
    $processId = [VibelutionLauncher.HiddenRedirectedProcess]::StartHiddenRedirected(
        $CommandPath,
        $commandLine,
        $WorkingDirectory,
        $StdoutPath,
        $StderrPath
    )
    return Get-Process -Id $processId -ErrorAction Stop
}

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandPath,
        [string[]]$ArgumentList = @(),
        [string]$RedirectPath = "",
        [switch]$SuppressOutput
    )

    Ensure-Directories
    $token = [guid]::NewGuid().ToString("N")
    $stdoutPath = Join-Path $launcherDir "native-command-$token.out.log"
    $stderrPath = Join-Path $launcherDir "native-command-$token.err.log"
    $workingDirectory = (Get-Location).Path
    $launchFields = @{
        command_path = $CommandPath
        argument_count = @($ArgumentList).Count
        argument_preview = @(Get-SafeProcessArgumentPreview -ArgumentList $ArgumentList)
        working_directory = $workingDirectory
        redirect_path = $RedirectPath
        stdout_log = $stdoutPath
        stderr_log = $stderrPath
        use_shell_execute = $false
        create_no_window = $true
        console_window_suppressed = $true
        launch_api = "System.Diagnostics.Process"
    }

    if ($RedirectPath) {
        $redirectDir = Split-Path -Parent $RedirectPath
        if ($redirectDir -and -not (Test-Path $redirectDir)) {
            New-Item -ItemType Directory -Path $redirectDir -Force | Out-Null
        }
    }

    Write-LauncherControlLog `
        -Event "launcher.native_command.started" `
        -Message "Starting hidden native command." `
        -Fields $launchFields
    if ($script:currentRuntimeSceneId) {
        Write-RuntimeSceneEvent `
            -Component "launcher" `
            -Phase "lifecycle" `
            -EventCode "launcher.native_command.started" `
            -Message "Starting hidden native command." `
            -Outcome "started" `
            -Fields $launchFields
    }

    try {
        $result = Invoke-HiddenProcessCapture `
            -FilePath $CommandPath `
            -ArgumentList $ArgumentList `
            -WorkingDirectory $workingDirectory
        $stdout = $result.Stdout
        $stderr = $result.Stderr
        if ($stdout) {
            [System.IO.File]::WriteAllText($stdoutPath, $stdout, (New-Object System.Text.UTF8Encoding -ArgumentList $false))
        }
        if ($stderr) {
            [System.IO.File]::WriteAllText($stderrPath, $stderr, (New-Object System.Text.UTF8Encoding -ArgumentList $false))
        }

        if ($RedirectPath) {
            foreach ($content in @($stdout, $stderr)) {
                if ($content) {
                    Add-Content -LiteralPath $RedirectPath -Value $content -Encoding utf8
                }
            }
        } elseif (-not $SuppressOutput) {
            if ($stdout) {
                [Console]::Out.Write($stdout)
            }
            if ($stderr) {
                [Console]::Error.Write($stderr)
            }
        }

        $exitCode = [int]$result.ExitCode
        $completedFields = @{} + $launchFields
        $completedFields["process_id"] = [int]$result.ProcessId
        $completedFields["exit_code"] = $exitCode
        Write-LauncherControlLog `
            -Event "launcher.native_command.completed" `
            -Message "Hidden native command completed." `
            -Fields $completedFields
        if ($script:currentRuntimeSceneId) {
            Write-RuntimeSceneEvent `
                -Component "launcher" `
                -Phase "lifecycle" `
                -EventCode "launcher.native_command.completed" `
                -Message "Hidden native command completed." `
                -Outcome "completed" `
                -Fields $completedFields
        }

        return $exitCode
    } catch {
        $failedFields = @{} + $launchFields
        $failedFields["errorType"] = $_.Exception.GetType().Name
        $failedFields["error"] = $_.Exception.Message
        Write-LauncherControlLog `
            -Event "launcher.native_command.spawn_failed" `
            -Message "Hidden native command could not be started." `
            -Level "error" `
            -Fields $failedFields
        if ($script:currentRuntimeSceneId) {
            Write-RuntimeSceneEvent `
                -Component "launcher" `
                -Phase "lifecycle" `
                -EventCode "launcher.native_command.spawn_failed" `
                -Message "Hidden native command could not be started." `
                -Level "error" `
                -Outcome "failed" `
                -Fields $failedFields
        }
        throw
    } finally {
        Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-HiddenNativeCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandPath,
        [string[]]$ArgumentList = @()
    )

    Ensure-Directories
    $token = [guid]::NewGuid().ToString("N")
    $stdoutPath = Join-Path $launcherDir "runtime-manager-client-$token.out.log"
    $stderrPath = Join-Path $launcherDir "runtime-manager-client-$token.err.log"
    $launchFields = @{
        command_path = $CommandPath
        argument_count = @($ArgumentList).Count
        argument_preview = @(Get-SafeProcessArgumentPreview -ArgumentList $ArgumentList)
        working_directory = $projectDir
        stdout_log = $stdoutPath
        stderr_log = $stderrPath
        use_shell_execute = $false
        create_no_window = $true
        console_window_suppressed = $true
        launch_api = "System.Diagnostics.Process"
    }

    Write-LauncherControlLog `
        -Event "launcher.runtime_manager_client.started" `
        -Message "Starting hidden runtime manager client command." `
        -Fields $launchFields
    if ($script:currentRuntimeSceneId) {
        Write-RuntimeSceneEvent `
            -Component "launcher" `
            -Phase "lifecycle" `
            -EventCode "launcher.runtime_manager_client.started" `
            -Message "Starting hidden runtime manager client command." `
            -Outcome "started" `
            -Fields $launchFields
    }

    try {
        $result = Invoke-HiddenProcessCapture `
            -FilePath $CommandPath `
            -ArgumentList $ArgumentList `
            -WorkingDirectory $projectDir
        $stdout = $result.Stdout
        $stderr = $result.Stderr
        if ($stdout) {
            [System.IO.File]::WriteAllText($stdoutPath, $stdout, (New-Object System.Text.UTF8Encoding -ArgumentList $false))
        }
        if ($stderr) {
            [System.IO.File]::WriteAllText($stderrPath, $stderr, (New-Object System.Text.UTF8Encoding -ArgumentList $false))
        }

        if ($stdout) {
            [Console]::Out.Write($stdout)
        }
        if ($stderr) {
            [Console]::Error.Write($stderr)
        }

        $exitCode = [int]$result.ExitCode
        $completedFields = @{} + $launchFields
        $completedFields["process_id"] = [int]$result.ProcessId
        $completedFields["exit_code"] = $exitCode
        Write-LauncherControlLog `
            -Event "launcher.runtime_manager_client.completed" `
            -Message "Hidden runtime manager client command completed." `
            -Fields $completedFields
        if ($script:currentRuntimeSceneId) {
            Write-RuntimeSceneEvent `
                -Component "launcher" `
                -Phase "lifecycle" `
                -EventCode "launcher.runtime_manager_client.completed" `
                -Message "Hidden runtime manager client command completed." `
                -Outcome "completed" `
                -Fields $completedFields
        }
        if ($exitCode -ne 0) {
            $failedResultFields = @{} + $completedFields
            $failedResultFields["stdout_log"] = $stdoutPath
            $failedResultFields["stderr_log"] = $stderrPath
            Write-LauncherControlLog `
                -Event "launcher.runtime_manager_client.failed" `
                -Message "Runtime manager client command failed." `
                -Level "error" `
                -Fields $failedResultFields
            if ($script:currentRuntimeSceneId) {
                Write-RuntimeSceneEvent `
                    -Component "launcher" `
                    -Phase "lifecycle" `
                    -EventCode "launcher.runtime_manager_client.failed" `
                    -Message "Runtime manager client command failed." `
                    -Level "error" `
                    -Outcome "failed" `
                    -Fields $failedResultFields
            }
        } else {
            Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
        }
        return $exitCode
    } catch {
        $failedFields = @{} + $launchFields
        $failedFields["error"] = $_.Exception.Message
        $failedFields["errorType"] = $_.Exception.GetType().Name
        Write-LauncherControlLog `
            -Event "launcher.runtime_manager_client.spawn_failed" `
            -Message "Runtime manager client command could not be started." `
            -Level "error" `
            -Fields $failedFields
        if ($script:currentRuntimeSceneId) {
            Write-RuntimeSceneEvent `
                -Component "launcher" `
                -Phase "lifecycle" `
                -EventCode "launcher.runtime_manager_client.spawn_failed" `
                -Message "Runtime manager client command could not be started." `
                -Level "error" `
                -Outcome "failed" `
                -Fields $failedFields
        }
        throw
    }
}

function Test-PythonRuntime {
    param(
        [string]$CommandPath,
        [string[]]$PrefixArgs = @()
    )

    try {
        $exitCode = Invoke-NativeCommand `
            -CommandPath $CommandPath `
            -ArgumentList @($PrefixArgs + @("-c", "import fastapi, uvicorn")) `
            -SuppressOutput
        return $exitCode -eq 0
    } catch {
        return $false
    }
}

function Ensure-ProjectVirtualEnvironment {
    if (Test-Path -LiteralPath $preferredPythonExe) {
        return
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "Project virtual environment is missing and Python was not found on PATH. Install Python 3.11 or 3.12 first."
    }

    $pythonPath = (Resolve-Path -LiteralPath $pythonCommand.Source).Path
    Write-Note "Project virtual environment is missing. Creating .venv ..."
    Write-LauncherControlLog `
        -Event "bootstrap.virtualenv.create.started" `
        -Message "Creating project virtual environment." `
        -Fields @{
            python = $pythonPath
            venv_path = $projectVenvDir
        }
    if ($script:currentRuntimeSceneId) {
        Write-RuntimeSceneEvent `
            -Component "launcher" `
            -Phase "python_dependencies" `
            -EventCode "bootstrap.virtualenv.create.started" `
            -Message "Creating project virtual environment." `
            -Outcome "started" `
            -Fields @{ python = $pythonPath; venv_path = $projectVenvDir }
    }

    $exitCode = Invoke-NativeCommand `
        -CommandPath $pythonPath `
        -ArgumentList @("-m", "venv", $projectVenvDir)
    if ($exitCode -ne 0 -or -not (Test-Path -LiteralPath $preferredPythonExe)) {
        Write-LauncherControlLog `
            -Event "bootstrap.virtualenv.create.failed" `
            -Message "Creating project virtual environment failed." `
            -Level "error" `
            -Fields @{
                python = $pythonPath
                venv_path = $projectVenvDir
                exit_code = $exitCode
            }
        if ($script:currentRuntimeSceneId) {
            Write-RuntimeSceneEvent `
                -Component "launcher" `
                -Phase "python_dependencies" `
                -EventCode "bootstrap.virtualenv.create.failed" `
                -Message "Creating project virtual environment failed." `
                -Level "error" `
                -Outcome "failed" `
                -Fields @{ python = $pythonPath; venv_path = $projectVenvDir; exit_code = $exitCode }
        }
        throw "Creating project virtual environment failed with exit code $exitCode."
    }

    Write-LauncherControlLog `
        -Event "bootstrap.virtualenv.create.succeeded" `
        -Message "Project virtual environment created." `
        -Fields @{
            python = $pythonPath
            venv_path = $projectVenvDir
        }
    if ($script:currentRuntimeSceneId) {
        Write-RuntimeSceneEvent `
            -Component "launcher" `
            -Phase "python_dependencies" `
            -EventCode "bootstrap.virtualenv.create.succeeded" `
            -Message "Project virtual environment created." `
            -Outcome "succeeded" `
            -Fields @{ python = $pythonPath; venv_path = $projectVenvDir }
    }
}

function Get-ProjectPythonCandidates {
    $venvCandidates = New-Object System.Collections.Generic.List[object]
    $seenPaths = New-Object System.Collections.Generic.HashSet[string]([System.StringComparer]::OrdinalIgnoreCase)

    function Add-PythonCandidate {
        param(
            [string]$Path,
            [string]$Label
        )

        if (-not $Path -or -not (Test-Path -LiteralPath $Path)) {
            return
        }

        $resolvedPath = (Resolve-Path -LiteralPath $Path).Path
        $fileName = [System.IO.Path]::GetFileName($resolvedPath)
        if (-not $seenPaths.Add($resolvedPath)) {
            return
        }

        [void]$venvCandidates.Add([pscustomobject]@{
            FilePath = $resolvedPath
            PrefixArgs = @()
            Label = $Label
        })
    }

    Add-PythonCandidate -Path $launcherPythonOverride -Label "launcher virtual environment"
    Add-PythonCandidate -Path $preferredPythonExe -Label "project venv"

    return $venvCandidates.ToArray()
}

function Ensure-ProjectPythonDependencies {
    Ensure-ProjectVirtualEnvironment
    $venvCandidates = @(Get-ProjectPythonCandidates)
    if ($venvCandidates.Count -eq 0) {
        return
    }

    $requirementsFingerprint = $null
    if (Test-Path $requirementsPath) {
        $requirementsFingerprint = Get-FileFingerprint -Paths @($requirementsPath)
    }
    $storedFingerprint = Get-StoredStampValue -Path $pythonDepsStampPath
    $runtimeReady = $false

    foreach ($candidate in $venvCandidates) {
        if (Test-PythonRuntime -CommandPath $candidate.FilePath -PrefixArgs $candidate.PrefixArgs) {
            $runtimeReady = $true
            break
        }
    }

    if ($runtimeReady -and -not $requirementsFingerprint) {
        if ($script:currentRuntimeSceneId) {
            Write-RuntimeSceneEvent `
                -Component "launcher" `
                -Phase "python_dependencies" `
                -EventCode "backend.dependencies.current" `
                -Message "Backend runtime dependencies are current." `
                -Outcome "succeeded"
        }
        return
    }

    if ($runtimeReady -and $requirementsFingerprint -and $storedFingerprint -eq $requirementsFingerprint) {
        if ($script:currentRuntimeSceneId) {
            Write-RuntimeSceneEvent `
                -Component "launcher" `
                -Phase "python_dependencies" `
                -EventCode "backend.dependencies.current" `
                -Message "Backend runtime dependencies are current." `
                -Outcome "succeeded"
        }
        return
    }

    if ($runtimeReady -and $requirementsFingerprint -and -not $storedFingerprint) {
        Write-Note "Recording the current Python dependency fingerprint."
        Set-StoredStampValue -Path $pythonDepsStampPath -Value $requirementsFingerprint
        if ($script:currentRuntimeSceneId) {
            Write-RuntimeSceneEvent `
                -Component "launcher" `
                -Phase "python_dependencies" `
                -EventCode "backend.dependencies.stamped" `
                -Message "Recorded the current Python dependency fingerprint." `
                -Outcome "succeeded"
        }
        return
    }

    if (-not (Test-Path $requirementsPath)) {
        throw "Project virtual environment was found, but requirements.txt is missing at $requirementsPath"
    }

    $installTarget = $venvCandidates[0]
    $installExitCode = 0
    $maxInstallAttempts = 3
    $installReason = if (-not $runtimeReady) {
        "backend runtime imports are incomplete"
    } elseif (-not $storedFingerprint) {
        "dependency stamp is missing"
    } else {
        "requirements.txt changed"
    }

    for ($attempt = 1; $attempt -le $maxInstallAttempts; $attempt++) {
        Write-Note "Installing Python dependencies into $($installTarget.Label) ($installReason, attempt $attempt/$maxInstallAttempts) ..."
        if ($script:currentRuntimeSceneId) {
            Write-RuntimeSceneEvent `
                -Component "launcher" `
                -Phase "python_dependencies" `
                -EventCode "backend.dependencies.install.started" `
                -Message "Installing Python dependencies." `
                -Outcome "started" `
                -Fields @{ reason = $installReason; attempt = $attempt; max_attempts = $maxInstallAttempts }
        }
        $installExitCode = Invoke-NativeCommand `
            -CommandPath $installTarget.FilePath `
            -ArgumentList @($installTarget.PrefixArgs + @("-m", "pip", "install", "--disable-pip-version-check", "-r", $requirementsPath))
        if ($installExitCode -eq 0) {
            break
        }
        if ($attempt -lt $maxInstallAttempts) {
            Write-Note "Dependency install attempt $attempt failed with exit code $installExitCode. Retrying in 2 seconds..."
            Start-Sleep -Seconds 2
        }
    }

    if ($installExitCode -ne 0) {
        if ($script:currentRuntimeSceneId) {
            Write-RuntimeSceneEvent `
                -Component "launcher" `
                -Phase "python_dependencies" `
                -EventCode "backend.dependencies.install.failed" `
                -Message "Installing Python dependencies failed." `
                -Level "error" `
                -Outcome "failed" `
                -Fields @{ reason = $installReason; exit_code = $installExitCode }
        }
        throw "Installing Python dependencies failed with exit code $installExitCode."
    }

    foreach ($candidate in $venvCandidates) {
        if (Test-PythonRuntime -CommandPath $candidate.FilePath -PrefixArgs $candidate.PrefixArgs) {
            if ($requirementsFingerprint) {
                Set-StoredStampValue -Path $pythonDepsStampPath -Value $requirementsFingerprint
            }
            if ($script:currentRuntimeSceneId) {
                Write-RuntimeSceneEvent `
                    -Component "launcher" `
                    -Phase "python_dependencies" `
                    -EventCode "backend.dependencies.install.succeeded" `
                    -Message "Python dependencies are ready." `
                    -Outcome "succeeded" `
                    -Fields @{ runtime = $candidate.Label }
            }
            return
        }
    }

    $venvPaths = ($venvCandidates | ForEach-Object { $_.FilePath } | Sort-Object -Unique) -join ", "
    throw "Project virtual environment dependency install completed, but backend imports still failed. Checked: $venvPaths"
}

function Resolve-PythonRuntime {
    $venvCandidates = @(Get-ProjectPythonCandidates)

    foreach ($candidate in $venvCandidates) {
        if (Test-PythonRuntime -CommandPath $candidate.FilePath -PrefixArgs $candidate.PrefixArgs) {
            Write-PythonRuntimeSelectedLog -PythonRuntime $candidate
            return $candidate
        }
    }

    if ($venvCandidates.Count -gt 0) {
        $venvPaths = ($venvCandidates | ForEach-Object { $_.FilePath } | Sort-Object -Unique) -join ", "
        throw "Project virtual environment was found but is not usable. Expected a Python runtime that can import uvicorn. Checked: $venvPaths"
    }

    $candidates = New-Object System.Collections.Generic.List[object]

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $resolvedPythonPath = (Resolve-Path -LiteralPath $pythonCommand.Source).Path
        if (-not @($candidates | Where-Object { $_.FilePath -eq $resolvedPythonPath })) {
            [void]$candidates.Add([pscustomobject]@{
                FilePath = $resolvedPythonPath
                PrefixArgs = @()
                Label = "python on PATH"
            })
        }
    }

    foreach ($candidate in $candidates) {
        if (Test-PythonRuntime -CommandPath $candidate.FilePath -PrefixArgs $candidate.PrefixArgs) {
            Write-PythonRuntimeSelectedLog -PythonRuntime $candidate
            return $candidate
        }
    }

    throw "No usable Python runtime was found. Expected one that can import uvicorn."
}

function Write-PythonRuntimeSelectedLog {
    param([pscustomobject]$PythonRuntime)

    if (-not $PythonRuntime) {
        return
    }
    $fields = @{
        path = [string]$PythonRuntime.FilePath
        label = [string]$PythonRuntime.Label
    }
    Write-LauncherControlLog `
        -Event "launcher.python_runtime.selected" `
        -Message "Selected Python runtime for launcher-managed work." `
        -Fields $fields
    if ($script:currentRuntimeSceneId) {
        Write-RuntimeSceneEvent `
            -Component "launcher" `
            -Phase "python_dependencies" `
            -EventCode "launcher.python_runtime.selected" `
            -Message "Selected Python runtime for launcher-managed work." `
            -Outcome "succeeded" `
            -Fields $fields
    }
}

function Resolve-EdgeExecutable {
    $pathCandidates = @()

    if ($env:ProgramFiles -and (Test-Path $env:ProgramFiles)) {
        $pathCandidates += (Join-Path $env:ProgramFiles "Microsoft\Edge\Application\msedge.exe")
    }
    if (${env:ProgramFiles(x86)} -and (Test-Path ${env:ProgramFiles(x86)})) {
        $pathCandidates += (Join-Path ${env:ProgramFiles(x86)} "Microsoft\Edge\Application\msedge.exe")
    }
    if ($env:LocalAppData -and (Test-Path $env:LocalAppData)) {
        $pathCandidates += (Join-Path $env:LocalAppData "Microsoft\Edge\Application\msedge.exe")
    }

    foreach ($candidate in $pathCandidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return (Resolve-Path $candidate).Path
        }
    }

    $edgeCommand = Get-Command msedge.exe -ErrorAction SilentlyContinue
    if ($edgeCommand) {
        return $edgeCommand.Source
    }

    $edgeProcess = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -ieq "msedge.exe" -and $_.ExecutablePath
    } | Select-Object -First 1
    if ($edgeProcess -and (Test-Path $edgeProcess.ExecutablePath)) {
        return (Resolve-Path $edgeProcess.ExecutablePath).Path
    }

    throw "Microsoft Edge was not found. Install Edge or update the launcher path."
}

function Get-WebBuildReason {
    if (-not (Test-Path $webDistIndex)) {
        return "web/dist is missing"
    }

    $latestInput = Get-FrontendInputTimeUtc
    $distTime = Get-WebDistTimeUtc
    if ($latestInput -gt $distTime) {
        return "frontend sources changed"
    }

    return $null
}

function Ensure-FrontendDependencies {
    $packageJsonPath = Join-Path $webDir "package.json"
    $packageLockPath = Join-Path $webDir "package-lock.json"
    $dependencyFiles = @($packageLockPath, $packageJsonPath) | Where-Object { Test-Path $_ }
    if ($dependencyFiles.Count -eq 0) {
        throw "Frontend dependency manifests are missing from $webDir"
    }

    $nodeModulesDir = Join-Path $webDir "node_modules"
    $tscBinPath = Join-Path $nodeModulesDir ".bin\tsc.cmd"
    $viteBinPath = Join-Path $nodeModulesDir ".bin\vite.cmd"
    $toolchainReady = (Test-Path $tscBinPath) -and (Test-Path $viteBinPath)
    $dependencyFingerprint = Get-FileFingerprint -Paths $dependencyFiles
    $storedFingerprint = Get-StoredStampValue -Path $frontendDepsStampPath
    if ((Test-Path $nodeModulesDir) -and $toolchainReady -and $storedFingerprint -eq $dependencyFingerprint) {
        if ($script:currentRuntimeSceneId) {
            Write-RuntimeSceneEvent `
                -Component "frontend" `
                -Phase "dependencies" `
                -EventCode "frontend.dependencies.current" `
                -Message "Frontend dependencies are current." `
                -Outcome "succeeded"
        }
        return
    }

    if ((Test-Path $nodeModulesDir) -and $toolchainReady -and -not $storedFingerprint) {
        Write-Note "Recording the current frontend dependency fingerprint."
        Set-StoredStampValue -Path $frontendDepsStampPath -Value $dependencyFingerprint
        if ($script:currentRuntimeSceneId) {
            Write-RuntimeSceneEvent `
                -Component "frontend" `
                -Phase "dependencies" `
                -EventCode "frontend.dependencies.stamped" `
                -Message "Recorded the current frontend dependency fingerprint." `
                -Outcome "succeeded"
        }
        return
    }

    $npmInvocation = Resolve-NpmInvocation
    $installCommandName = if ((-not (Test-Path $nodeModulesDir)) -and (Test-Path $packageLockPath)) {
        "ci"
    } else {
        "install"
    }
    $installReason = if (-not (Test-Path $nodeModulesDir)) {
        "node_modules is missing"
    } elseif (-not $toolchainReady) {
        "frontend build tools are missing from node_modules"
    } elseif (-not $storedFingerprint) {
        "dependency stamp is missing"
    } else {
        "frontend dependency manifests changed"
    }

    Write-Note "Installing frontend dependencies ($installReason)..."
    if ($script:currentRuntimeSceneId) {
        Append-RuntimeSceneRawLog -RelativePath (Get-RuntimeSceneRelativePaths).FrontendBuild -Message "Installing frontend dependencies ($installReason)."
        Write-RuntimeSceneEvent `
                -Component "frontend" `
                -Phase "dependencies" `
                -EventCode "frontend.dependencies.install.started" `
                -Message "Installing frontend dependencies." `
                -Outcome "started" `
                -Fields @{
                    reason = $installReason
                    command = $installCommandName
                    command_path = $npmInvocation.CommandPath
                    npm_source = $npmInvocation.SourceCommand
                    npm_launch_strategy = $npmInvocation.LaunchStrategy
                    shell_adapter = $npmInvocation.ShellAdapter
                }
    }
    Push-Location $webDir
    try {
        $frontendBuildLogPath = $null
        if ($script:currentRuntimeSceneId) {
                $frontendBuildLogPath = Get-CurrentRuntimeSceneFilePath (Get-RuntimeSceneRelativePaths).FrontendBuild
        }
        $installArgs = @(@($npmInvocation.PrefixArgs) + @($installCommandName))
        $exitCode = Invoke-NativeCommand -CommandPath $npmInvocation.CommandPath -ArgumentList $installArgs -RedirectPath $frontendBuildLogPath
        if ($exitCode -ne 0) {
            if ($script:currentRuntimeSceneId) {
                Write-RuntimeSceneEvent `
                    -Component "frontend" `
                    -Phase "dependencies" `
                    -EventCode "frontend.dependencies.install.failed" `
                    -Message "Installing frontend dependencies failed." `
                    -Level "error" `
                    -Outcome "failed" `
                    -Fields @{
                        reason = $installReason
                        command = $installCommandName
                        command_path = $npmInvocation.CommandPath
                        npm_source = $npmInvocation.SourceCommand
                        npm_launch_strategy = $npmInvocation.LaunchStrategy
                        shell_adapter = $npmInvocation.ShellAdapter
                        exit_code = $exitCode
                    } `
                    -RawRefs @(New-RuntimeSceneRawRef -RelativePath (Get-RuntimeSceneRelativePaths).FrontendBuild -TailLines 80)
            }
            throw "$($npmInvocation.DisplayName) $installCommandName failed with exit code $exitCode."
        }
    } finally {
        Pop-Location
    }

    Set-StoredStampValue -Path $frontendDepsStampPath -Value $dependencyFingerprint
    if ($script:currentRuntimeSceneId) {
        Write-RuntimeSceneEvent `
            -Component "frontend" `
            -Phase "dependencies" `
            -EventCode "frontend.dependencies.install.succeeded" `
            -Message "Frontend dependencies installed successfully." `
            -Outcome "succeeded" `
            -Fields @{
                reason = $installReason
                command = $installCommandName
                command_path = $npmInvocation.CommandPath
                npm_source = $npmInvocation.SourceCommand
                npm_launch_strategy = $npmInvocation.LaunchStrategy
                shell_adapter = $npmInvocation.ShellAdapter
            }
    }
}

function Ensure-WebBuild {
    Ensure-FrontendDependencies

    $buildReason = Get-WebBuildReason
    if (-not $buildReason) {
        Write-Note "Frontend build is current."
        if ($script:currentRuntimeSceneId) {
            Update-RuntimeSceneManifest @{ frontend = @{ build_status = "current"; build_reason = "" } }
            Write-RuntimeSceneEvent `
                -Component "frontend" `
                -Phase "build" `
                -EventCode "frontend.build.current" `
                -Message "Frontend build is current." `
                -Outcome "succeeded"
        }
        return
    }

    $npmInvocation = Resolve-NpmInvocation
    Push-Location $webDir
    try {
        Write-Note "Building frontend bundle ($buildReason)..."
        if ($script:currentRuntimeSceneId) {
            Update-RuntimeSceneManifest @{ frontend = @{ build_status = "running"; build_reason = $buildReason } }
            Write-RuntimeSceneEvent `
                -Component "frontend" `
                -Phase "build" `
                -EventCode "frontend.build.started" `
                -Message "Starting frontend build." `
                -Outcome "started" `
                -Fields @{
                    reason = $buildReason
                    command_path = $npmInvocation.CommandPath
                    npm_source = $npmInvocation.SourceCommand
                    npm_launch_strategy = $npmInvocation.LaunchStrategy
                    shell_adapter = $npmInvocation.ShellAdapter
                }
            $exitCode = Invoke-NativeCommand `
                -CommandPath $npmInvocation.CommandPath `
                -ArgumentList @(@($npmInvocation.PrefixArgs) + @("run", "build")) `
                -RedirectPath (Get-CurrentRuntimeSceneFilePath (Get-RuntimeSceneRelativePaths).FrontendBuild)
        } else {
            $exitCode = Invoke-NativeCommand -CommandPath $npmInvocation.CommandPath -ArgumentList @(@($npmInvocation.PrefixArgs) + @("run", "build"))
        }
        if ($exitCode -ne 0) {
            if ($script:currentRuntimeSceneId) {
                Update-RuntimeSceneManifest @{ frontend = @{ build_status = "failed"; build_reason = $buildReason } }
                Write-RuntimeSceneEvent `
                    -Component "frontend" `
                    -Phase "build" `
                    -EventCode "frontend.build.failed" `
                    -Message "Frontend build failed." `
                    -Level "error" `
                    -Outcome "failed" `
                    -Fields @{
                        reason = $buildReason
                        command_path = $npmInvocation.CommandPath
                        npm_source = $npmInvocation.SourceCommand
                        npm_launch_strategy = $npmInvocation.LaunchStrategy
                        shell_adapter = $npmInvocation.ShellAdapter
                        exit_code = $exitCode
                    } `
                    -RawRefs @(New-RuntimeSceneRawRef -RelativePath (Get-RuntimeSceneRelativePaths).FrontendBuild -TailLines 120)
            }
            throw (Get-FrontendBuildFailureSummary -ExitCode $exitCode)
        }
    } finally {
        Pop-Location
    }

    if (-not (Test-Path $webDistIndex)) {
        if ($script:currentRuntimeSceneId) {
            Update-RuntimeSceneManifest @{ frontend = @{ build_status = "failed"; build_reason = $buildReason } }
            Write-RuntimeSceneEvent `
                -Component "frontend" `
                -Phase "build" `
                -EventCode "frontend.build.missing_output" `
                -Message "Frontend build completed without index.html." `
                -Level "error" `
                -Outcome "failed" `
                -Fields @{ reason = $buildReason }
        }
        throw "Frontend build finished without producing web/dist/index.html."
    }

    if ($script:currentRuntimeSceneId) {
        Update-RuntimeSceneManifest @{ frontend = @{ build_status = "success"; build_reason = $buildReason } }
        Write-RuntimeSceneEvent `
            -Component "frontend" `
            -Phase "build" `
            -EventCode "frontend.build.succeeded" `
            -Message "Frontend build completed successfully." `
            -Outcome "succeeded" `
            -Fields @{
                reason = $buildReason
                output = "web/dist/index.html"
                command_path = $npmInvocation.CommandPath
                npm_source = $npmInvocation.SourceCommand
                npm_launch_strategy = $npmInvocation.LaunchStrategy
                shell_adapter = $npmInvocation.ShellAdapter
            }
    }
}

function Get-ManagedBackendCandidatePids {
    $pids = New-Object System.Collections.Generic.List[int]
    $state = Get-State
    if ($state -and $state.backendPid) {
        $trackedPid = [int]$state.backendPid
        if (Test-ProcessAlive $trackedPid) {
            [void]$pids.Add($trackedPid)
        }
    }
    if ($state -and $state.backendLaunchPid) {
        $trackedLaunchPid = [int]$state.backendLaunchPid
        if (Test-ProcessAlive $trackedLaunchPid) {
            [void]$pids.Add($trackedLaunchPid)
        }
    }

    $listenerPid = Get-ListeningPid $port
    if ($listenerPid) {
        $listenerProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $listenerPid" -ErrorAction SilentlyContinue
        $listenerLooksManaged = Test-CommandLineLooksLikeManagedBackend -CommandLine ([string]$listenerProcess.CommandLine)
        if ($listenerLooksManaged) {
            [void]$pids.Add([int]$listenerPid)
        }
    }

    $scanPids = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and (Test-CommandLineLooksLikeManagedBackend -CommandLine ([string]$_.CommandLine)) -and $_.CommandLine -match "--port\s+$port\b"
    } | ForEach-Object {
        [int]$_.ProcessId
    })

    foreach ($candidatePid in $scanPids) {
        [void]$pids.Add($candidatePid)
    }

    return @($pids | Sort-Object -Unique)
}

function Test-CommandLineLooksLikeManagedBackend {
    param([string]$CommandLine)

    if (-not $CommandLine) {
        return $false
    }

    return [bool](
        (Test-CommandLineMentionsWorkbenchScript -CommandLine $CommandLine) -and
        $CommandLine -match "(^|\s)--managed-by-launcher(\s|$)"
    )
}

function ConvertTo-LauncherComparableText {
    param([string]$Value)

    $text = if ($null -eq $Value) { "" } else { [string]$Value }
    return $text.Replace("\", "/").ToLowerInvariant()
}

function Test-NormalizedTextContainsPathSegment {
    param(
        [string]$Text,
        [string]$PathText
    )

    if (-not $Text -or -not $PathText) {
        return $false
    }

    $startIndex = 0
    while ($true) {
        $index = $Text.IndexOf($PathText, $startIndex, [System.StringComparison]::Ordinal)
        if ($index -lt 0) {
            return $false
        }

        $afterIndex = $index + $PathText.Length
        $beforeOk = $index -eq 0
        if (-not $beforeOk) {
            $before = [char]$Text[$index - 1]
            $beforeOk = [char]::IsWhiteSpace($before) -or $before -in @([char]34, [char]39, [char]61, [char]58)
        }

        $afterOk = $afterIndex -ge $Text.Length
        if (-not $afterOk) {
            $after = [char]$Text[$afterIndex]
            $afterOk = [char]::IsWhiteSpace($after) -or $after -in @([char]34, [char]39, [char]47)
        }

        if ($beforeOk -and $afterOk) {
            return $true
        }
        $startIndex = $index + 1
    }
}

function Test-TextReferencesProjectPath {
    param([string]$Text)

    if (-not $Text) {
        return $false
    }

    $normalizedText = ConvertTo-LauncherComparableText -Value $Text
    $projectFullPath = ([System.IO.Path]::GetFullPath($projectDir)).TrimEnd([char[]]@([char]92, [char]47))
    $normalizedProjectDir = ConvertTo-LauncherComparableText -Value $projectFullPath
    return Test-NormalizedTextContainsPathSegment -Text $normalizedText -PathText $normalizedProjectDir
}

function Test-CommandLineMentionsWorkbenchScript {
    param([string]$CommandLine)

    if (-not $CommandLine) {
        return $false
    }
    return [bool]((ConvertTo-LauncherComparableText -Value $CommandLine) -match "scripts[\\/]+web_workbench\.py")
}

function Test-CommandLineUsesRelativeWorkbenchScript {
    param([string]$CommandLine)

    if (-not $CommandLine) {
        return $false
    }
    return [bool]((ConvertTo-LauncherComparableText -Value $CommandLine) -match "(^|\s)scripts[\\/]+web_workbench\.py(\s|$)")
}

function Get-LauncherProcessPropertyValue {
    param(
        $Process,
        [string]$Name,
        $Default = $null
    )

    if ($null -eq $Process) {
        return $Default
    }
    $property = $Process.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $Default
    }
    return $property.Value
}

function Test-CommandLineLooksLikeRepoWorkbenchBackend {
    param([string]$CommandLine)

    return [bool](
        (Test-CommandLineMentionsWorkbenchScript -CommandLine $CommandLine) -and
        (Test-TextReferencesProjectPath -Text $CommandLine)
    )
}

function Test-ProcessLooksLikeRepoWorkbenchBackend {
    param($Process)

    if ($null -eq $Process) {
        return $false
    }

    $commandLine = [string](Get-LauncherProcessPropertyValue -Process $Process -Name "CommandLine" -Default "")
    if (-not (Test-CommandLineMentionsWorkbenchScript -CommandLine $commandLine)) {
        return $false
    }
    if (Test-CommandLineLooksLikeRepoWorkbenchBackend -CommandLine $commandLine) {
        return $true
    }

    $executablePath = [string](Get-LauncherProcessPropertyValue -Process $Process -Name "ExecutablePath" -Default "")
    if (Test-TextReferencesProjectPath -Text $executablePath) {
        return $true
    }

    if (-not (Test-CommandLineUsesRelativeWorkbenchScript -CommandLine $commandLine)) {
        return $false
    }

    $parentPid = 0
    [void][int]::TryParse([string](Get-LauncherProcessPropertyValue -Process $Process -Name "ParentProcessId" -Default "0"), [ref]$parentPid)
    $visited = @{}
    for ($depth = 0; $depth -lt 8 -and $parentPid -gt 0; $depth++) {
        if ($visited.ContainsKey($parentPid)) {
            break
        }
        $visited[$parentPid] = $true
        $parentProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $parentPid" -ErrorAction SilentlyContinue
        if ($null -eq $parentProcess) {
            break
        }
        $parentCommandLine = [string](Get-LauncherProcessPropertyValue -Process $parentProcess -Name "CommandLine" -Default "")
        $parentExecutablePath = [string](Get-LauncherProcessPropertyValue -Process $parentProcess -Name "ExecutablePath" -Default "")
        if ((Test-TextReferencesProjectPath -Text $parentCommandLine) -or (Test-TextReferencesProjectPath -Text $parentExecutablePath)) {
            return $true
        }
        $parentPid = 0
        [void][int]::TryParse([string](Get-LauncherProcessPropertyValue -Process $parentProcess -Name "ParentProcessId" -Default "0"), [ref]$parentPid)
    }

    return $false
}

function Resolve-ResidualCleanupPythonPath {
    if ($launcherPythonOverride -and (Test-Path $launcherPythonOverride)) {
        return (Resolve-Path -LiteralPath $launcherPythonOverride).Path
    }
    if (Test-Path $preferredPythonExe) {
        return (Resolve-Path -LiteralPath $preferredPythonExe).Path
    }
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        return $pythonCommand.Source
    }
    return ""
}

function Invoke-RepoResidualWorkbenchCleanup {
    param([int[]]$ExcludePids = @())

    $pythonPath = Resolve-ResidualCleanupPythonPath
    if (-not $pythonPath) {
        return [pscustomobject]@{
            supported = $false
            reason = "python_unavailable"
            requested = @()
            terminated = @()
            remaining = @()
        }
    }

    $arguments = @(
        "-m",
        "core.runtime_manager.process_inventory",
        "--cleanup-residual-workbench",
        "--json",
        "--timeout-seconds",
        "4"
    )
    foreach ($excludePid in @(($ExcludePids + $selfProcessId) | Sort-Object -Unique)) {
        if ($excludePid -gt 0) {
            $arguments += @("--exclude-pid", "$excludePid")
        }
    }

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $pythonPath
    $psi.WorkingDirectory = $projectDir
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    foreach ($argument in $arguments) {
        [void]$psi.ArgumentList.Add($argument)
    }

    try {
        $process = [System.Diagnostics.Process]::Start($psi)
        if (-not $process.WaitForExit(8000)) {
            try {
                $process.Kill()
            } catch {
            }
            return [pscustomobject]@{
                supported = $false
                reason = "cleanup_timeout"
                requested = @()
                terminated = @()
                remaining = @()
            }
        }
        $stdout = $process.StandardOutput.ReadToEnd()
        $stderr = $process.StandardError.ReadToEnd()
        if ($process.ExitCode -ne 0) {
            return [pscustomobject]@{
                supported = $false
                reason = "cleanup_failed"
                exitCode = $process.ExitCode
                stderr = $stderr
                requested = @()
                terminated = @()
                remaining = @()
            }
        }
        $parsed = $stdout | ConvertFrom-Json -ErrorAction Stop
        return $parsed
    } catch {
        return [pscustomobject]@{
            supported = $false
            reason = "cleanup_exception"
            error = $_.Exception.Message
            requested = @()
            terminated = @()
            remaining = @()
        }
    }
}

function Get-PrimaryManagedBackendPid {
    param([int]$FallbackPid = 0)

    $candidatePids = @(Get-ManagedBackendCandidatePids)
    if ($candidatePids.Count -gt 0) {
        return [int]$candidatePids[0]
    }
    if ($FallbackPid -gt 0) {
        return $FallbackPid
    }
    return 0
}

function Get-ManagedBackendLiveness {
    param([int]$TrackedPid = 0)

    $candidatePids = @(Get-ManagedBackendCandidatePids)
    $trackedPidAlive = $false
    if ($TrackedPid -gt 0) {
        $trackedPidAlive = Test-ProcessAlive $TrackedPid
    }
    $healthy = Test-WebHealthy

    return [pscustomobject]@{
        Alive = [bool]($trackedPidAlive -or $candidatePids.Count -gt 0 -or $healthy)
        Healthy = [bool]$healthy
        TrackedPid = if ($TrackedPid -gt 0) { $TrackedPid } else { $null }
        TrackedPidAlive = [bool]$trackedPidAlive
        CandidatePids = @($candidatePids)
    }
}

function Test-ManagedBackendAlive {
    param([int]$TrackedPid = 0)

    $liveness = Get-ManagedBackendLiveness -TrackedPid $TrackedPid
    return [bool]$liveness.Alive
}

function Get-ManagedBrowserCandidatePids {
    $pids = New-Object System.Collections.Generic.List[int]
    $state = Get-State
    if ($state -and $state.browserWindowPid) {
        $trackedWindowPid = [int]$state.browserWindowPid
        if (Test-ProcessAlive $trackedWindowPid) {
            [void]$pids.Add($trackedWindowPid)
        }
    }
    if ($state -and $state.browserLaunchPid) {
        $trackedLaunchPid = [int]$state.browserLaunchPid
        if (Test-ProcessAlive $trackedLaunchPid) {
            [void]$pids.Add($trackedLaunchPid)
        }
    }

    Ensure-Directories
    $profileMarker = [regex]::Escape([System.IO.Path]::GetFullPath($browserProfileDir))
    $profileProcesses = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -ieq "msedge.exe" -and $_.CommandLine -and $_.CommandLine -match $profileMarker
    })
    foreach ($process in $profileProcesses) {
        [void]$pids.Add([int]$process.ProcessId)
    }

    return @($pids | Sort-Object -Unique)
}

function Get-ManagedBrowserProcesses {
    $candidatePids = @(Get-ManagedBrowserCandidatePids)
    if ($candidatePids.Count -eq 0) {
        return @()
    }

    return @(Get-Process -Id $candidatePids -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessName -ieq "msedge"
    } | Sort-Object Id -Unique)
}

function Get-ManagedBrowserPids {
    return @(Get-ManagedBrowserProcesses | ForEach-Object { [int]$_.Id } | Sort-Object -Unique)
}

function Get-ManagedBrowserWindowProcesses {
    $browserPids = @(Get-ManagedBrowserPids)
    if ($browserPids.Count -eq 0) {
        return @()
    }

    return @(Get-Process -Id $browserPids -ErrorAction SilentlyContinue | Where-Object {
        $_.MainWindowHandle -ne 0
    })
}

function Get-ManagedBrowserWindowProcess {
    $windowProcesses = @(Get-ManagedBrowserWindowProcesses)
    if ($windowProcesses.Count -gt 0) {
        return $windowProcesses[0]
    }
    return $null
}

function Wait-ForBrowserWindow {
    param(
        [int]$LaunchProcessId,
        [int]$TimeoutSeconds = 18
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $windowProcess = Get-ManagedBrowserWindowProcess
        if ($windowProcess) {
            return $windowProcess
        }

        $browserPids = @(Get-ManagedBrowserPids)
        if ($browserPids.Count -eq 0 -and -not (Test-ProcessAlive $LaunchProcessId)) {
            return $null
        }

        Start-Sleep -Milliseconds 400
    }
    return $null
}

function Wait-ForBrowserStopped {
    param([int]$TimeoutSeconds = 12)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (@(Get-ManagedBrowserPids).Count -eq 0) {
            return $true
        }
        Start-Sleep -Milliseconds 300
    }
    return $false
}

function Ensure-WinApi {
    if (-not ("VibelutionLauncher.WinApi" -as [type])) {
        Add-Type @"
using System;
using System.Runtime.InteropServices;

namespace VibelutionLauncher {
    public static class WinApi {
        [DllImport("user32.dll")]
        public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);

        [DllImport("user32.dll")]
        public static extern bool SetForegroundWindow(IntPtr hWnd);
    }
}
"@
    }
}

function Focus-ManagedBrowserWindow {
    $windowProcess = Get-ManagedBrowserWindowProcess
    if (-not $windowProcess) {
        Write-LauncherControlLog `
            -Event "launcher.browser.focus.failed" `
            -Message "No managed browser window was available to focus." `
            -Level "warning" `
            -Fields @{
                reason = "window_not_found"
                browser_pids = @(Get-ManagedBrowserPids)
            }
        if ($script:currentRuntimeSceneId) {
            Write-RuntimeSceneEvent `
                -Component "launcher" `
                -Phase "window" `
                -EventCode "launcher.browser.focus.failed" `
                -Message "No managed browser window was available to focus." `
                -Level "warning" `
                -Outcome "failed" `
                -Fields @{
                    reason = "window_not_found"
                    browser_pids = @(Get-ManagedBrowserPids)
                }
        }
        return $false
    }

    $showWindowResult = $false
    $setForegroundResult = $false
    $appActivateResult = $false
    $focusError = ""
    Ensure-WinApi
    try {
        $showWindowResult = [bool][VibelutionLauncher.WinApi]::ShowWindowAsync([IntPtr]$windowProcess.MainWindowHandle, 9)
        Start-Sleep -Milliseconds 120
        $setForegroundResult = [bool][VibelutionLauncher.WinApi]::SetForegroundWindow([IntPtr]$windowProcess.MainWindowHandle)
    } catch {
        $focusError = $_.Exception.Message
    }

    try {
        $wshShell = New-Object -ComObject WScript.Shell
        $appActivateResult = [bool]$wshShell.AppActivate($windowProcess.Id)
    } catch {
        if (-not $focusError) {
            $focusError = $_.Exception.Message
        }
    }

    $focused = [bool]($showWindowResult -or $setForegroundResult -or $appActivateResult)
    $fields = @{
        window_pid = [int]$windowProcess.Id
        main_window_handle = [string]$windowProcess.MainWindowHandle
        show_window = [bool]$showWindowResult
        set_foreground = [bool]$setForegroundResult
        app_activate = [bool]$appActivateResult
    }
    if ($focusError) {
        $fields.error = $focusError
    }

    Write-LauncherControlLog `
        -Event $(if ($focused) { "launcher.browser.focus.succeeded" } else { "launcher.browser.focus.failed" }) `
        -Message $(if ($focused) { "Managed browser window focus was requested." } else { "Managed browser window focus request did not report success." }) `
        -Level $(if ($focused) { "info" } else { "warning" }) `
        -Fields $fields
    if ($script:currentRuntimeSceneId) {
        Write-RuntimeSceneEvent `
            -Component "launcher" `
            -Phase "window" `
            -EventCode $(if ($focused) { "launcher.browser.focus.succeeded" } else { "launcher.browser.focus.failed" }) `
            -Message $(if ($focused) { "Managed browser window focus was requested." } else { "Managed browser window focus request did not report success." }) `
            -Level $(if ($focused) { "info" } else { "warning" }) `
            -Outcome $(if ($focused) { "succeeded" } else { "failed" }) `
            -Fields $fields `
            -RawRefs @(New-RuntimeSceneRawRef -RelativePath (Get-RuntimeSceneRelativePaths).LauncherControl -TailLines 80)
    }

    return $focused
}

function Start-ManagedBackend {
    param([pscustomobject]$PythonRuntime)

    $backendStdoutLog = if ($script:currentRuntimeSceneId) {
        Get-CurrentRuntimeSceneFilePath (Get-RuntimeSceneRelativePaths).BackendStdout
    } else {
        Join-Path $launcherDir "web-backend.out.log"
    }
    $backendStderrLog = if ($script:currentRuntimeSceneId) {
        Get-CurrentRuntimeSceneFilePath (Get-RuntimeSceneRelativePaths).BackendStderr
    } else {
        Join-Path $launcherDir "web-backend.err.log"
    }

    Write-Note "Starting bundled web service at $url ..."
    Write-Note "Python runtime: $($PythonRuntime.Label) -> $($PythonRuntime.FilePath)"
    if ($script:currentRuntimeSceneId) {
        Update-RuntimeSceneManifest @{
            backend = @{
                pid = 0
                health_status = "starting"
                python_label = $PythonRuntime.Label
                python_command = $PythonRuntime.FilePath
                managed_marker = $managedBackendMarkerArg
            }
        }
        Write-RuntimeSceneEvent `
            -Component "backend" `
            -Phase "startup" `
            -EventCode "backend.start.requested" `
            -Message "Starting bundled backend service." `
            -Outcome "started" `
            -Fields @{ host = $bindHost; port = $port; python_label = $PythonRuntime.Label; python_command = $PythonRuntime.FilePath; managed_marker = $managedBackendMarkerArg }
    }
    $proc = Start-RedirectedBackgroundProcess `
        -CommandPath $PythonRuntime.FilePath `
        -ArgumentList @($PythonRuntime.PrefixArgs + @("scripts/web_workbench.py", "--host", $bindHost, "--port", "$port", "--no-browser", $managedBackendMarkerArg)) `
        -WorkingDirectory $projectDir `
        -StdoutPath $backendStdoutLog `
        -StderrPath $backendStderrLog

    if ($script:currentRuntimeSceneId) {
        Update-RuntimeSceneManifest @{ backend = @{ pid = $proc.Id; health_status = "starting" } }
        Write-RuntimeSceneEvent `
            -Component "backend" `
            -Phase "startup" `
            -EventCode "backend.process.started" `
            -Message "Backend process started." `
            -Outcome "started" `
            -Fields @{ pid = $proc.Id; managed_marker = $managedBackendMarkerArg }
    }

    if (-not (Wait-ForBackendHealthy -ProcessId $proc.Id)) {
        Stop-ProcessesById @($proc.Id)
        $tail = Get-LogTail -Path $backendStderrLog
        if ($script:currentRuntimeSceneId) {
            Update-RuntimeSceneManifest @{ backend = @{ pid = $proc.Id; health_status = "failed" } }
            Write-RuntimeSceneEvent `
                -Component "backend" `
                -Phase "health" `
                -EventCode "backend.health.failed" `
                -Message "Backend failed to become healthy." `
                -Level "error" `
                -Outcome "failed" `
                -Fields @{ pid = $proc.Id } `
                -RawRefs @(New-RuntimeSceneRawRef -RelativePath (Get-RuntimeSceneRelativePaths).BackendStderr -TailLines 80)
        }
        throw "Bundled web service failed to become healthy.$([Environment]::NewLine)$tail"
    }

    $backendPid = Get-PrimaryManagedBackendPid -FallbackPid $proc.Id
    if ($script:currentRuntimeSceneId) {
        $healthFields = @{ pid = $backendPid; url = $url }
        if ($backendPid -ne $proc.Id) {
            $healthFields.launcher_pid = $proc.Id
        }
        Update-RuntimeSceneManifest @{ backend = @{ pid = $backendPid; launcher_pid = $proc.Id; health_status = "healthy" } }
        Write-RuntimeSceneEvent `
            -Component "backend" `
            -Phase "health" `
            -EventCode "backend.health.succeeded" `
            -Message "Backend passed health checks." `
            -Outcome "succeeded" `
            -Fields $healthFields
    }

    return [pscustomobject]@{
        Id = $backendPid
        LauncherPid = $proc.Id
        Process = $proc
    }
}

function Start-ManagedBrowser {
    param([string]$BrowserExecutable)

    $browserArgs = @(
        "--user-data-dir=$browserProfileDir",
        "--app=$url",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble"
    )

    Write-Note "Starting managed Edge app window ..."
    if ($script:currentRuntimeSceneId) {
        Update-RuntimeSceneManifest @{ browser = @{ status = "launching"; executable = $BrowserExecutable } }
        Append-RuntimeSceneRawLog -RelativePath (Get-RuntimeSceneRelativePaths).Browser -Message "Launching managed browser window."
        Write-RuntimeSceneEvent `
            -Component "browser" `
            -Phase "window" `
            -EventCode "browser.window.launch.requested" `
            -Message "Launching managed browser window." `
            -Outcome "started" `
            -Fields @{
                executable = $BrowserExecutable
                launch_api = "gui_process_without_console"
                console_window_suppressed = $true
            }
    }
    $proc = Start-GuiProcessWithoutConsole `
        -FilePath $BrowserExecutable `
        -ArgumentList $browserArgs `
        -WorkingDirectory $projectDir

    $windowProcess = Wait-ForBrowserWindow -LaunchProcessId $proc.Id
    if (-not $windowProcess) {
        Stop-ProcessesById (Get-ManagedBrowserPids)
        if ($script:currentRuntimeSceneId) {
            Update-RuntimeSceneManifest @{ browser = @{ status = "failed"; executable = $BrowserExecutable; launch_pid = $proc.Id; window_pid = 0 } }
            Append-RuntimeSceneRawLog -RelativePath (Get-RuntimeSceneRelativePaths).Browser -Message "Managed browser window did not open successfully."
            Write-RuntimeSceneEvent `
                -Component "browser" `
                -Phase "window" `
                -EventCode "browser.window.launch.failed" `
                -Message "Managed browser window did not open successfully." `
                -Level "error" `
                -Outcome "failed" `
                -Fields @{
                    executable = $BrowserExecutable
                    launch_pid = $proc.Id
                    launch_api = "gui_process_without_console"
                    console_window_suppressed = $true
                }
        }
        throw "Managed Edge app window did not open successfully."
    }

    if ($script:currentRuntimeSceneId) {
        Update-RuntimeSceneManifest @{ browser = @{ status = "open"; executable = $BrowserExecutable; launch_pid = $proc.Id; window_pid = $windowProcess.Id } }
        Append-RuntimeSceneRawLog -RelativePath (Get-RuntimeSceneRelativePaths).Browser -Message "Managed browser window opened (launch PID=$($proc.Id), window PID=$($windowProcess.Id))."
        Write-RuntimeSceneEvent `
            -Component "browser" `
            -Phase "window" `
            -EventCode "browser.window.opened" `
            -Message "Managed browser window opened." `
            -Outcome "succeeded" `
            -Fields @{
                executable = $BrowserExecutable
                launch_pid = $proc.Id
                window_pid = $windowProcess.Id
                launch_api = "gui_process_without_console"
                console_window_suppressed = $true
            }
    }

    return [pscustomobject]@{
        LaunchPid = $proc.Id
        WindowPid = $windowProcess.Id
    }
}

function Start-Supervisor {
    param([string]$ManagedSessionId)

    $powershellExe = Join-Path $PSHOME "powershell.exe"
    if (-not (Test-Path $powershellExe)) {
        throw "PowerShell executable was not found at $powershellExe"
    }

    $supervisorStdoutLog = if ($script:currentRuntimeSceneId) {
        Get-CurrentRuntimeSceneFilePath (Get-RuntimeSceneRelativePaths).Supervisor
    } else {
        Join-Path $launcherDir "supervisor.log"
    }
    $supervisorStderrLog = if ($script:currentRuntimeSceneId) {
        Get-CurrentRuntimeSceneFilePath (Get-RuntimeSceneRelativePaths).SupervisorStderr
    } else {
        Join-Path $launcherDir "supervisor.stderr.log"
    }

    $proc = Start-RedirectedBackgroundProcess `
        -CommandPath $powershellExe `
        -ArgumentList @("-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $PSCommandPath, "-Action", "supervise", "-SessionId", $ManagedSessionId) `
        -WorkingDirectory $projectDir `
        -StdoutPath $supervisorStdoutLog `
        -StderrPath $supervisorStderrLog

    if ($script:currentRuntimeSceneId) {
        Update-RuntimeSceneManifest @{ supervisor = @{ pid = $proc.Id; status = "running" } }
        Write-RuntimeSceneEvent `
            -Component "supervisor" `
            -Phase "session" `
            -EventCode "supervisor.started" `
            -Message "Supervisor process started." `
            -Outcome "started" `
            -Fields @{ pid = $proc.Id; managed_session_id = $ManagedSessionId }
    }

    return $proc.Id
}

function Get-SessionSnapshot {
    $state = Get-State
    $backendPids = @(Get-ManagedBackendCandidatePids)
    $browserPids = @(Get-ManagedBrowserPids)
    $browserWindowProcesses = @(Get-ManagedBrowserWindowProcesses)

    $backendPid = $null
    if ($state -and $state.backendPid -and (Test-ProcessAlive ([int]$state.backendPid))) {
        $backendPid = [int]$state.backendPid
    } elseif ($backendPids.Count -gt 0) {
        $backendPid = [int]$backendPids[0]
    }

    $supervisorPid = $null
    if ($state -and $state.supervisorPid -and (Test-ProcessAlive ([int]$state.supervisorPid))) {
        $supervisorPid = [int]$state.supervisorPid
    }

    return [pscustomobject]@{
        State = $state
        BackendPid = $backendPid
        BackendPids = $backendPids
        BackendHealthy = [bool]($backendPid) -and (Test-WebHealthy)
        BrowserPids = $browserPids
        BrowserWindowProcesses = $browserWindowProcesses
        BrowserWindowCount = $browserWindowProcesses.Count
        BrowserWindowPid = if ($browserWindowProcesses.Count -gt 0) { [int]$browserWindowProcesses[0].Id } else { $null }
        SupervisorPid = $supervisorPid
        SessionRunning = [bool]($backendPid) -and (Test-WebHealthy) -and ($browserWindowProcesses.Count -gt 0)
    }
}

function Save-SessionState {
    param(
        [string]$ManagedSessionId,
        [int]$BackendPid,
        [int]$BackendLaunchPid,
        [pscustomobject]$PythonRuntime,
        [string]$BrowserExecutable,
        [int]$BrowserLaunchPid,
        [int]$BrowserWindowPid,
        [int]$SupervisorPid,
        [bool]$BrowserManaged
)

    $rawPaths = Get-RuntimeSceneRelativePaths
    Save-State @{
        mode = $mode
        sessionId = $ManagedSessionId
        host = $bindHost
        port = $port
        url = $url
        backendPid = $BackendPid
        backendLaunchPid = $BackendLaunchPid
        backendStdout = if ($script:currentRuntimeSceneDir) { Get-CurrentRuntimeSceneFilePath $rawPaths.BackendStdout } else { $null }
        backendStderr = if ($script:currentRuntimeSceneDir) { Get-CurrentRuntimeSceneFilePath $rawPaths.BackendStderr } else { $null }
        pythonCommand = if ($PythonRuntime) { $PythonRuntime.FilePath } else { $null }
        pythonLabel = if ($PythonRuntime) { $PythonRuntime.Label } else { $null }
        browserManaged = $BrowserManaged
        browserExecutable = $BrowserExecutable
        browserProfileDir = $browserProfileDir
        browserLaunchPid = $BrowserLaunchPid
        browserWindowPid = $BrowserWindowPid
        supervisorPid = $SupervisorPid
        supervisorStdout = if ($script:currentRuntimeSceneDir) { Get-CurrentRuntimeSceneFilePath $rawPaths.Supervisor } else { $null }
        supervisorStderr = if ($script:currentRuntimeSceneDir) { Get-CurrentRuntimeSceneFilePath $rawPaths.SupervisorStderr } else { $null }
        runtimeSceneId = $script:currentRuntimeSceneId
        runtimeSceneDir = $script:currentRuntimeSceneDir
        startedAt = (Get-Date).ToString("o")
    }
}

function Get-SessionReferenceTime {
    param([pscustomobject]$Snapshot)

    if ($Snapshot -and $Snapshot.BackendPid) {
        try {
            $backendProcess = Get-Process -Id $Snapshot.BackendPid -ErrorAction Stop
            return $backendProcess.StartTime.ToUniversalTime()
        } catch {
        }
    }

    if ($Snapshot -and $Snapshot.State -and $Snapshot.State.startedAt) {
        $parsed = [datetime]::MinValue
        if ([datetime]::TryParse([string]$Snapshot.State.startedAt, [ref]$parsed)) {
            return $parsed.ToUniversalTime()
        }
    }

    return [datetime]::MinValue
}

function Get-SessionRestartReason {
    param([pscustomobject]$Snapshot)

    if (-not $Snapshot) {
        return $null
    }

    $referenceTime = Get-SessionReferenceTime -Snapshot $Snapshot
    if ($referenceTime -eq [datetime]::MinValue) {
        return $null
    }

    $backendInputTime = Get-BackendInputTimeUtc
    if ($backendInputTime -gt $referenceTime) {
        return "backend files changed"
    }

    $frontendDistTime = Get-WebDistTimeUtc
    if ($frontendDistTime -gt $referenceTime) {
        return "frontend bundle changed"
    }

    return $null
}

function Adopt-Or-FocusSession {
    param([pscustomobject]$Snapshot)

    if (-not $Snapshot.SessionRunning) {
        return $false
    }

    if (-not $Snapshot.State -or -not $Snapshot.SupervisorPid) {
        Write-Note "Adopting a live managed session and reattaching supervision."
        if ($Snapshot.State -and $Snapshot.State.runtimeSceneId -and $Snapshot.State.runtimeSceneDir) {
            Set-CurrentRuntimeSceneContext -SceneId ([string]$Snapshot.State.runtimeSceneId) -SceneDir ([string]$Snapshot.State.runtimeSceneDir)
        }
        $backendLaunchPid = if ($Snapshot.State -and $Snapshot.State.backendLaunchPid) {
            [int]$Snapshot.State.backendLaunchPid
        } else {
            [int]$Snapshot.BackendPid
        }
        $managedSessionId = [guid]::NewGuid().ToString()
        $supervisorPid = Start-Supervisor -ManagedSessionId $managedSessionId
        Save-SessionState `
            -ManagedSessionId $managedSessionId `
            -BackendPid $Snapshot.BackendPid `
            -BackendLaunchPid $backendLaunchPid `
            -PythonRuntime $null `
            -BrowserExecutable $null `
            -BrowserLaunchPid 0 `
            -BrowserWindowPid $Snapshot.BrowserWindowPid `
            -SupervisorPid $supervisorPid `
            -BrowserManaged $true
    }

    Write-Note "Vibelution is already running. Focusing the existing app window."
    if ($Snapshot.State -and $Snapshot.State.runtimeSceneId -and $Snapshot.State.runtimeSceneDir) {
        Set-CurrentRuntimeSceneContext -SceneId ([string]$Snapshot.State.runtimeSceneId) -SceneDir ([string]$Snapshot.State.runtimeSceneDir)
        $focusResult = [bool](Focus-ManagedBrowserWindow)
        Write-RuntimeSceneEvent `
            -Component "launcher" `
            -Phase "session" `
            -EventCode $(if ($focusResult) { "runtime.scene.focused" } else { "runtime.scene.focus.failed" }) `
            -Message $(if ($focusResult) { "Focused the existing managed session." } else { "Failed to focus the existing managed session." }) `
            -Level $(if ($focusResult) { "info" } else { "warning" }) `
            -Outcome $(if ($focusResult) { "succeeded" } else { "failed" })
    } else {
        [void](Focus-ManagedBrowserWindow)
        return $true
    }
    return $true
}

function Complete-HeadlessSessionWithBrowser {
    param([pscustomobject]$Snapshot)

    if (-not $Snapshot -or -not $Snapshot.BackendHealthy -or $Snapshot.BrowserWindowCount -gt 0) {
        return $false
    }

    Write-Note "A healthy backend is already running without a browser. Opening the managed app window."
    if ($Snapshot.State -and $Snapshot.State.runtimeSceneId -and $Snapshot.State.runtimeSceneDir) {
        Set-CurrentRuntimeSceneContext -SceneId ([string]$Snapshot.State.runtimeSceneId) -SceneDir ([string]$Snapshot.State.runtimeSceneDir)
    } else {
        Initialize-RuntimeScene -Trigger $Action -BrowserManaged $true
    }

    if ($script:currentRuntimeSceneId) {
        Write-RuntimeSceneEvent `
            -Component "launcher" `
            -Phase "session" `
            -EventCode "runtime.scene.headless_upgrade.started" `
            -Message "Upgrading a healthy headless backend into a managed browser session." `
            -Outcome "started" `
            -Fields @{ backend_pid = $Snapshot.BackendPid; url = $url }
    }

    $browserExecutable = Resolve-EdgeExecutable
    $browserInfo = Start-ManagedBrowser -BrowserExecutable $browserExecutable
    $managedSessionId = if ($Snapshot.State -and $Snapshot.State.sessionId) {
        [string]$Snapshot.State.sessionId
    } else {
        [guid]::NewGuid().ToString()
    }
    $backendLaunchPid = if ($Snapshot.State -and $Snapshot.State.backendLaunchPid) {
        [int]$Snapshot.State.backendLaunchPid
    } else {
        [int]$Snapshot.BackendPid
    }
    $supervisorPid = Start-Supervisor -ManagedSessionId $managedSessionId

    Save-SessionState `
        -ManagedSessionId $managedSessionId `
        -BackendPid $Snapshot.BackendPid `
        -BackendLaunchPid $backendLaunchPid `
        -PythonRuntime $null `
        -BrowserExecutable $browserExecutable `
        -BrowserLaunchPid $browserInfo.LaunchPid `
        -BrowserWindowPid $browserInfo.WindowPid `
        -SupervisorPid $supervisorPid `
        -BrowserManaged $true

    $focusResult = [bool](Focus-ManagedBrowserWindow)
    Write-RuntimeSceneEvent `
        -Component "launcher" `
        -Phase "session" `
        -EventCode "runtime.scene.headless_upgrade.succeeded" `
        -Message "Healthy headless backend is now attached to a managed browser window." `
        -Outcome "succeeded" `
        -Fields @{ url = $url; backend_pid = $Snapshot.BackendPid; browser_window_pid = $browserInfo.WindowPid; supervisor_pid = $supervisorPid; focus_requested = $focusResult }
    Write-Note "Vibelution is live in a managed Edge app window at $url"
    return $true
}

function Stop-ManagedBrowserProcesses {
    $windowProcesses = @(Get-ManagedBrowserWindowProcesses)
    foreach ($windowProcess in $windowProcesses) {
        try {
            $null = $windowProcess.CloseMainWindow()
        } catch {
        }
    }
    Start-Sleep -Milliseconds 600

    for ($attempt = 1; $attempt -le 4; $attempt++) {
        $browserPids = @(Get-ManagedBrowserPids)
        if ($browserPids.Count -eq 0) {
            return
        }

        if ($attempt -gt 1) {
            Write-LauncherControlLog `
                -Event "launcher.browser.stop.retry" `
                -Message "Managed browser processes were still alive after a stop attempt." `
                -Level "warning" `
                -Fields @{
                    attempt = $attempt
                    browser_pids = @($browserPids)
                    window_pids = @($windowProcesses | ForEach-Object { [int]$_.Id })
                }
        }

        Stop-ProcessesById $browserPids
        Start-Sleep -Milliseconds $(if ($attempt -eq 1) { 450 } else { 650 })
    }

    $remainingPids = @(Get-ManagedBrowserPids)
    if ($remainingPids.Count -gt 0) {
        Write-LauncherControlLog `
            -Event "launcher.browser.stop.incomplete" `
            -Message "Managed browser processes were still present after repeated stop attempts." `
            -Level "error" `
            -Fields @{
                browser_pids = @($remainingPids)
                window_pids = @($windowProcesses | ForEach-Object { [int]$_.Id })
            }
    }
}

function Stop-ManagedBackendProcesses {
    $candidatePids = @(Get-ManagedBackendCandidatePids)
    Write-LauncherControlLog `
        -Event "launcher.backend.stop.requested" `
        -Message "Stopping managed backend candidates." `
        -Fields @{
            candidate_pids = @($candidatePids)
            port = $port
        }
    Stop-ProcessesById $candidatePids
    $state = Get-State
    $remainingPortPid = Get-ListeningPid $port
    if (-not $remainingPortPid) {
        return [pscustomobject]@{
            CandidatePids = @($candidatePids)
            RemainingPortPid = $null
            RemainingLooksManaged = $false
            RemainingHealthy = $false
            PortOwnerStopped = $false
        }
    }

    $remainingProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $remainingPortPid" -ErrorAction SilentlyContinue
    $remainingHealthy = [bool](Test-WebHealthy)
    $remainingCommandLine = [string](Get-LauncherProcessPropertyValue -Process $remainingProcess -Name "CommandLine" -Default "")
    $remainingLooksManaged = Test-CommandLineLooksLikeManagedBackend -CommandLine $remainingCommandLine
    $remainingMentionsWorkbench = Test-CommandLineMentionsWorkbenchScript -CommandLine $remainingCommandLine
    $remainingLooksRepoWorkbench = Test-ProcessLooksLikeRepoWorkbenchBackend -Process $remainingProcess
    $cleanupResult = $null
    $cleanupReason = ""
    $portOwnerStopped = $false
    if ($remainingLooksManaged) {
        Stop-ProcessesById @([int]$remainingPortPid)
        $portOwnerStopped = $true
        $cleanupReason = "managed_backend_marker"
    } elseif ($remainingMentionsWorkbench) {
        $cleanupResult = Invoke-RepoResidualWorkbenchCleanup -ExcludePids $candidatePids
        $cleanupRequestedPids = @()
        if ($cleanupResult) {
            $rawCleanupPids = @($cleanupResult.requested) + @($cleanupResult.terminated)
            $cleanupRequestedPids = @($rawCleanupPids | ForEach-Object { [int]$_ })
        }
        if ($cleanupRequestedPids -contains [int]$remainingPortPid) {
            $portOwnerStopped = $true
            $cleanupReason = "repo_runtime_inventory"
        } elseif ($remainingLooksRepoWorkbench) {
            Stop-ProcessesById @([int]$remainingPortPid)
            $portOwnerStopped = $true
            $cleanupReason = "repo_workbench_ancestor"
        }
    }
    $finalPortPid = Get-ListeningPid $port
    $finalPortOwnerPid = if ($finalPortPid) { [int]$finalPortPid } else { $null }
    $cleanupResultForLog = if ($cleanupResult) { $cleanupResult } else { $null }
    Write-LauncherControlLog `
        -Event "launcher.backend.stop.port_owner_detected" `
        -Message "Backend port still had a listener after stopping tracked candidates." `
        -Level $(if ($portOwnerStopped) { "warning" } else { "error" }) `
        -Fields @{
            candidate_pids = @($candidatePids)
            port_owner_pid = [int]$remainingPortPid
            remaining_looks_managed = [bool]$remainingLooksManaged
            remaining_mentions_workbench = [bool]$remainingMentionsWorkbench
            remaining_looks_repo_workbench = [bool]$remainingLooksRepoWorkbench
            remaining_healthy = [bool]$remainingHealthy
            port_owner_stop_requested = [bool]$portOwnerStopped
            port_owner_cleanup_reason = $cleanupReason
            final_port_owner_pid = $finalPortOwnerPid
            cleanup_result = $cleanupResultForLog
            port = $port
        }
    return [pscustomobject]@{
        CandidatePids = @($candidatePids)
        RemainingPortPid = [int]$remainingPortPid
        RemainingLooksManaged = [bool]$remainingLooksManaged
        RemainingMentionsWorkbench = [bool]$remainingMentionsWorkbench
        RemainingLooksRepoWorkbench = [bool]$remainingLooksRepoWorkbench
        RemainingHealthy = [bool]$remainingHealthy
        PortOwnerStopped = [bool]$portOwnerStopped
        PortOwnerCleanupReason = $cleanupReason
        CleanupResult = $cleanupResult
        FinalPortPid = $finalPortOwnerPid
    }
}

function Get-ManagedSessionClosureSnapshot {
    $snapshot = Get-SessionSnapshot
    $workbench = Get-RuntimeManagerWorkbench
    $desiredState = [string](Get-ObjectPropertyValue -Object $workbench -Name "desiredState" -Default "")
    $observedState = [string](Get-ObjectPropertyValue -Object $workbench -Name "observedState" -Default "")
    $phase = [string](Get-ObjectPropertyValue -Object $workbench -Name "phase" -Default "")
    $failureMessage = [string](Get-ObjectPropertyValue -Object $workbench -Name "failureMessage" -Default "")
    $portOwnerPid = Get-ListeningPid $port
    $backendHealthy = [bool](Test-WebHealthy)
    $backendRunning = ($snapshot.BackendPids.Count -gt 0) -or [bool]$portOwnerPid -or $backendHealthy
    $browserRunning = ($snapshot.BrowserPids.Count -gt 0) -or ($snapshot.BrowserWindowCount -gt 0)
    $managerClosed = if ($workbench) {
        $desiredState -eq "closed" -and $observedState -eq "closed" -and $phase -eq "steady"
    } else {
        -not $backendRunning -and -not $browserRunning
    }

    return [pscustomobject]@{
        BackendStopped = -not $backendRunning
        BrowserStopped = -not $browserRunning
        ManagerClosed = [bool]$managerClosed
        BackendPids = @($snapshot.BackendPids)
        BackendHealthy = [bool]$backendHealthy
        BrowserPids = @($snapshot.BrowserPids)
        BrowserWindowCount = [int]$snapshot.BrowserWindowCount
        PortOwnerPid = $portOwnerPid
        DesiredState = $desiredState
        ObservedState = $observedState
        Phase = $phase
        FailureMessage = $failureMessage
    }
}

function Test-ManagedSessionClosureSucceeded {
    param(
        [pscustomobject]$Closure,
        [bool]$RequireManagerClosed = $true
    )

    return [bool](
        $Closure `
        -and $Closure.BackendStopped `
        -and $Closure.BrowserStopped `
        -and ((-not $RequireManagerClosed) -or $Closure.ManagerClosed)
    )
}

function Write-ManagedSessionClosureRecord {
    param(
        [pscustomobject]$Closure,
        [string]$Reason,
        [string]$Source,
        [bool]$Success
    )

    $fields = @{
        reason = $Reason
        source = $Source
        backend_stopped = [bool]$Closure.BackendStopped
        backend_healthy = [bool]$Closure.BackendHealthy
        browser_stopped = [bool]$Closure.BrowserStopped
        manager_closed = [bool]$Closure.ManagerClosed
        backend_pids = @($Closure.BackendPids)
        browser_pids = @($Closure.BrowserPids)
        browser_window_count = [int]$Closure.BrowserWindowCount
        port_owner_pid = $Closure.PortOwnerPid
        desired_state = [string]$Closure.DesiredState
        observed_state = [string]$Closure.ObservedState
        phase = [string]$Closure.Phase
        failure_message = [string]$Closure.FailureMessage
        control_log_path = $launcherControlLogPath
    }

    if ($script:currentRuntimeSceneId) {
        $existingManifest = Get-RuntimeSceneManifest
        $finalState = if ($Success) {
            Get-RuntimeSceneFinalState -Reason $Reason
        } else {
            @{ status = "failed"; result = "shutdown_failed" }
        }
        $manifestReason = $Reason
        $manifestResult = $finalState.result
        $existingStatus = ""
        if ($existingManifest -is [System.Collections.IDictionary]) {
            $existingStatus = [string]$existingManifest["status"]
        }
        if ($Success -and $finalState.status -eq "stopped" -and $existingStatus -eq "stopped") {
            $existingStopReason = [string]$existingManifest["stop_reason"]
            $existingResult = [string]$existingManifest["result"]
            if ($existingStopReason) {
                $manifestReason = $existingStopReason
            }
            if ($existingResult) {
                $manifestResult = $existingResult
            }
        }
        $manifestRuntimeManager = if ($Success -and $finalState.status -eq "stopped") {
            @{
                desired_state = "closed"
                observed_state = "closed"
                phase = "steady"
                failure_message = ""
            }
        } else {
            @{
                desired_state = [string]$Closure.DesiredState
                observed_state = [string]$Closure.ObservedState
                phase = [string]$Closure.Phase
                failure_message = [string]$Closure.FailureMessage
            }
        }
        $manifestChanges = @{
            status = $finalState.status
            result = $manifestResult
            stop_reason = $manifestReason
            ended_at = (Get-Date).ToUniversalTime().ToString("o")
            backend = @{
                health_status = if ($Closure.BackendStopped) { "stopped" } else { "failed_to_stop" }
                remaining_pids = @($Closure.BackendPids)
                healthy_after_stop = [bool]$Closure.BackendHealthy
                port_owner_pid = $Closure.PortOwnerPid
            }
            browser = @{
                status = if ($Closure.BrowserStopped) { "stopped" } else { "failed_to_stop" }
                remaining_pids = @($Closure.BrowserPids)
            }
            launcher = @{
                control_log_path = (Get-RuntimeSceneRelativePaths).LauncherControl
                visible_monitor = if ($Source -eq "desktop_monitor") { if ($Success) { "closed" } else { "failed" } } else { "observed" }
                last_shutdown_source = $Source
            }
            runtime_manager = $manifestRuntimeManager
        }
        if ($Success -and $finalState.status -eq "stopped") {
            $manifestChanges.supervisor = @{
                status = "stopped"
                pid = 0
            }
        }
        Update-RuntimeSceneManifest $manifestChanges
    }

    Write-LauncherControlLog `
        -Event $(if ($Success) { "launcher.shutdown.succeeded" } else { "launcher.shutdown.failed" }) `
        -Message $(if ($Success) { "Managed workbench shutdown completed." } else { "Managed workbench shutdown failed." }) `
        -Level $(if ($Success) { "info" } else { "error" }) `
        -Fields $fields
}

function Stop-ManagedSession {
    param([string]$Reason = "user requested stop")

    $snapshot = Get-SessionSnapshot
    if ($snapshot.BackendPids.Count -eq 0 -and $snapshot.BrowserPids.Count -eq 0 -and -not $snapshot.State) {
        Write-Note "No managed Vibelution session is running."
        return
    }

    $supervisorPid = $null
    if ($snapshot.State -and $snapshot.State.supervisorPid) {
        $supervisorPid = [int]$snapshot.State.supervisorPid
    }

    Write-Note "Stopping Vibelution session ($Reason)..."
    if ($snapshot.State -and $snapshot.State.runtimeSceneId -and $snapshot.State.runtimeSceneDir) {
        Set-CurrentRuntimeSceneContext -SceneId ([string]$snapshot.State.runtimeSceneId) -SceneDir ([string]$snapshot.State.runtimeSceneDir)
        Write-RuntimeSceneEvent `
            -Component "launcher" `
            -Phase "shutdown" `
            -EventCode "runtime.scene.stop.requested" `
            -Message "Stopping the managed session." `
            -Outcome "started" `
            -Fields @{ reason = $Reason }
        Update-RuntimeSceneManifest @{
            status = "stopping"
            stop_reason = $Reason
            browser = @{
                status = if ($snapshot.BrowserWindowCount -gt 0 -or $snapshot.BrowserPids.Count -gt 0) { "stopping" } else { "stopped" }
            }
            backend = @{
                health_status = if ($snapshot.BackendPid) { "stopping" } else { "stopped" }
            }
        }
    }
    $backendStopTrace = Stop-ManagedBackendProcesses
    $backendStopped = Wait-ForPortClosed -Port $port

    if ($supervisorPid -and $supervisorPid -ne $selfProcessId) {
        Stop-ProcessesById @($supervisorPid)
    }

    if (-not $backendStopped) {
        Write-LauncherControlLog `
            -Event "launcher.browser.stop.with_backend_unconfirmed" `
            -Message "Closing the managed browser even though backend shutdown was not fully confirmed." `
            -Level "warning" `
            -Fields @{
                reason = $Reason
                port = $port
                port_owner_pid = Get-ListeningPid $port
                backend_stop_trace = $backendStopTrace
            }
    }
    Stop-ManagedBrowserProcesses
    $browserStopped = Wait-ForBrowserStopped -TimeoutSeconds 20

    $closure = Get-ManagedSessionClosureSnapshot
    if ($script:currentRuntimeSceneId) {
        Write-RuntimeSceneEvent `
            -Component "launcher" `
            -Phase "shutdown" `
            -EventCode "runtime.scene.stopped" `
            -Message "Managed session shutdown completed." `
            -Level $(if (Test-ManagedSessionClosureSucceeded -Closure $closure -RequireManagerClosed $false) { "info" } else { "warning" }) `
            -Outcome $(if (Test-ManagedSessionClosureSucceeded -Closure $closure -RequireManagerClosed $false) { "succeeded" } else { "partial" }) `
            -Fields @{
                reason = $Reason
                backend_stopped = [bool]$closure.BackendStopped
                backend_healthy = [bool]$closure.BackendHealthy
                backend_stop_trace = $backendStopTrace
                backend_pids = @($closure.BackendPids)
                browser_stopped = [bool]$closure.BrowserStopped
                browser_pids = @($closure.BrowserPids)
                manager_closed = [bool]$closure.ManagerClosed
                port_owner_pid = $closure.PortOwnerPid
            }
    }
    Write-ManagedSessionClosureRecord -Closure $closure -Reason $Reason -Source "launcher_stop" -Success (Test-ManagedSessionClosureSucceeded -Closure $closure -RequireManagerClosed $false)

    if (Test-ManagedSessionClosureSucceeded -Closure $closure -RequireManagerClosed $false) {
        Remove-State
        Write-Note "Vibelution session stopped."
        return
    }

    if (-not $browserStopped) {
        Write-Note "Managed browser processes are still winding down."
    }
    if (-not $backendStopped) {
        $portPid = Get-ListeningPid $port
        if ($portPid) {
            Write-Note "Port $port is still owned by PID=$portPid."
        }
        Write-Note "The managed browser was closed; backend shutdown still needs attention."
    }

    $stopFailures = @()
    if (-not $backendStopped) {
        $stopFailures += "backend did not stop"
    }
    if (-not $browserStopped) {
        $stopFailures += "browser did not stop"
    }
    throw "Managed session did not stop cleanly: $($stopFailures -join '; ')."
}

function Show-Status {
    $snapshot = Get-SessionSnapshot
    $buildReason = Get-WebBuildReason
    $sessionRestartReason = Get-SessionRestartReason -Snapshot $snapshot

    Write-Host "Mode      : $mode"
    Write-Host "Project   : $projectDir"
    Write-Host "URL       : $url"

    if ($snapshot.BackendPid) {
        $backendHealth = if ($snapshot.BackendHealthy) { "healthy" } else { "starting or unhealthy" }
        Write-Host "Backend   : running (PID=$($snapshot.BackendPid), $backendHealth)"
    } else {
        Write-Host "Backend   : stopped"
    }

    if ($snapshot.BrowserWindowCount -gt 0) {
        Write-Host "Browser   : running (window PID=$($snapshot.BrowserWindowPid), managed windows=$($snapshot.BrowserWindowCount))"
    } elseif ($snapshot.BrowserPids.Count -gt 0) {
        Write-Host "Browser   : background only (PID(s)=$($snapshot.BrowserPids -join ', '))"
    } else {
        Write-Host "Browser   : stopped"
    }

    if ($snapshot.SupervisorPid) {
        Write-Host "Supervisor: running (PID=$($snapshot.SupervisorPid))"
    } else {
        Write-Host "Supervisor: stopped"
    }

    if ($snapshot.SessionRunning) {
        if ($sessionRestartReason) {
            Write-Host "Session   : stale ($sessionRestartReason)"
        } else {
            Write-Host "Session   : current"
        }
    } elseif ($snapshot.BackendPids.Count -gt 0 -or $snapshot.BrowserPids.Count -gt 0 -or $snapshot.State) {
        Write-Host "Session   : incomplete (cleanup required before next launch)"
    } else {
        Write-Host "Session   : stopped"
    }

    if ($buildReason) {
        Write-Host "Frontend  : stale ($buildReason)"
    } else {
        Write-Host "Frontend  : current"
    }

    if ($snapshot.State) {
        Write-Host "State     : $statePath"
        if ($snapshot.State.runtimeSceneId) {
            Write-Host "Scene     : $($snapshot.State.runtimeSceneId)"
        }
        if ($snapshot.State.backendStdout) {
            Write-Host "Logs      : $($snapshot.State.backendStdout)"
        }
        if ($snapshot.State.backendStderr) {
            Write-Host "Errors    : $($snapshot.State.backendStderr)"
        }
    } else {
        Write-Host "State     : not tracking a managed session"
    }
}

function Start-ManagedSession {
    Ensure-Directories

    $snapshot = Get-SessionSnapshot
    $restartReason = Get-SessionRestartReason -Snapshot $snapshot

    Write-LauncherControlLog `
        -Event "launcher.session.snapshot" `
        -Message "Launcher evaluated the managed session before starting." `
        -Fields @{
            action = $Action
            no_browser = [bool]$NoBrowser
            backend_pid = $snapshot.BackendPid
            backend_pids = @($snapshot.BackendPids)
            backend_healthy = [bool]$snapshot.BackendHealthy
            browser_pids = @($snapshot.BrowserPids)
            browser_window_count = [int]$snapshot.BrowserWindowCount
            browser_window_pid = $snapshot.BrowserWindowPid
            supervisor_pid = $snapshot.SupervisorPid
            session_running = [bool]$snapshot.SessionRunning
            state_present = [bool]$snapshot.State
            restart_reason = $restartReason
        }

    if ($snapshot.SessionRunning -and -not $restartReason) {
        if (Adopt-Or-FocusSession -Snapshot $snapshot) {
            return
        }
    } elseif ($snapshot.SessionRunning -and $restartReason) {
        Write-Note "Restarting the managed session because $restartReason."
        Stop-ManagedSession -Reason $restartReason
        $snapshot = Get-SessionSnapshot
    }

    if ((-not $NoBrowser) -and $snapshot.BackendHealthy -and $snapshot.BrowserWindowCount -eq 0) {
        if (Complete-HeadlessSessionWithBrowser -Snapshot $snapshot) {
            return
        }
    }

    if ($snapshot.BackendPids.Count -gt 0 -or $snapshot.BrowserPids.Count -gt 0 -or $snapshot.State) {
        Write-Note "Found an incomplete managed session. Cleaning it up before restart."
        Stop-ManagedSession -Reason "cleanup stale session"
    }

    $portPid = Get-ListeningPid $port
    if ($portPid) {
        Write-LauncherControlLog `
            -Event "launcher.backend.prestart_port_owner_detected" `
            -Message "Backend port had a listener before starting a new managed backend." `
            -Level "warning" `
            -Fields @{
                port = $port
                port_owner_pid = [int]$portPid
            }
        $prestartCleanupTrace = Stop-ManagedBackendProcesses
        if ($prestartCleanupTrace.PortOwnerStopped) {
            [void](Wait-ForPortClosed -Port $port -TimeoutSeconds 8)
        }
        $portPid = Get-ListeningPid $port
        $postCleanupPortOwnerPid = if ($portPid) { [int]$portPid } else { $null }
        Write-LauncherControlLog `
            -Event $(if ($portPid) { "launcher.backend.prestart_port_owner_remaining" } else { "launcher.backend.prestart_port_owner_cleared" }) `
            -Message $(if ($portPid) { "Backend port still had a listener after prestart cleanup." } else { "Backend port owner was cleared before managed startup." }) `
            -Level $(if ($portPid) { "error" } else { "info" }) `
            -Fields @{
                port = $port
                port_owner_pid = $postCleanupPortOwnerPid
                cleanup_trace = $prestartCleanupTrace
            }
        if ($portPid) {
            throw "Port $port is already in use by PID=$portPid. Stop that process first."
        }
    }

    Initialize-RuntimeScene -Trigger $Action -BrowserManaged (-not $NoBrowser)

    try {
        Ensure-WebBuild
        Ensure-ProjectPythonDependencies

        $pythonRuntime = Resolve-PythonRuntime
        $managedSessionId = [guid]::NewGuid().ToString()
        $backendProc = Start-ManagedBackend -PythonRuntime $pythonRuntime

        if ($NoBrowser) {
            Save-SessionState `
                -ManagedSessionId $managedSessionId `
                -BackendPid $backendProc.Id `
                -BackendLaunchPid $backendProc.LauncherPid `
                -PythonRuntime $pythonRuntime `
                -BrowserExecutable $null `
                -BrowserLaunchPid 0 `
                -BrowserWindowPid 0 `
                -SupervisorPid 0 `
                -BrowserManaged $false
            Write-RuntimeSceneEvent `
                -Component "launcher" `
                -Phase "session" `
                -EventCode "runtime.scene.backend_live" `
                -Message "Managed backend is live without a browser window." `
                -Outcome "succeeded" `
                -Fields @{ url = $url; backend_pid = $backendProc.Id }
            Write-Note "Vibelution backend is live at $url"
            return
        }

        $browserExecutable = Resolve-EdgeExecutable
        $browserInfo = Start-ManagedBrowser -BrowserExecutable $browserExecutable

        Save-SessionState `
            -ManagedSessionId $managedSessionId `
            -BackendPid $backendProc.Id `
            -BackendLaunchPid $backendProc.LauncherPid `
            -PythonRuntime $pythonRuntime `
            -BrowserExecutable $browserExecutable `
            -BrowserLaunchPid $browserInfo.LaunchPid `
            -BrowserWindowPid $browserInfo.WindowPid `
            -SupervisorPid 0 `
            -BrowserManaged $true

        $supervisorPid = Start-Supervisor -ManagedSessionId $managedSessionId

        Save-SessionState `
            -ManagedSessionId $managedSessionId `
            -BackendPid $backendProc.Id `
            -BackendLaunchPid $backendProc.LauncherPid `
            -PythonRuntime $pythonRuntime `
            -BrowserExecutable $browserExecutable `
            -BrowserLaunchPid $browserInfo.LaunchPid `
            -BrowserWindowPid $browserInfo.WindowPid `
            -SupervisorPid $supervisorPid `
            -BrowserManaged $true

        $focusResult = [bool](Focus-ManagedBrowserWindow)
        Write-RuntimeSceneEvent `
            -Component "launcher" `
            -Phase "session" `
            -EventCode "runtime.scene.ready" `
            -Message "Managed runtime scene is ready." `
            -Outcome "succeeded" `
            -Fields @{ url = $url; backend_pid = $backendProc.Id; browser_window_pid = $browserInfo.WindowPid; supervisor_pid = $supervisorPid; focus_requested = $focusResult }
        Write-Note "Vibelution is live in a managed Edge app window at $url"
    } catch {
        if ($script:currentRuntimeSceneId) {
            Write-RuntimeSceneEvent `
                -Component "launcher" `
                -Phase "session" `
                -EventCode "runtime.scene.startup.failed" `
                -Message "Managed runtime scene startup failed." `
                -Level "error" `
                -Outcome "failed" `
                -Fields @{ reason = $_.Exception.Message }
            Update-RuntimeSceneManifest @{
                status = "failed"
                result = "startup_failed"
                stop_reason = $_.Exception.Message
                ended_at = (Get-Date).ToUniversalTime().ToString("o")
            }
        }
        Stop-ManagedBrowserProcesses
        Stop-ManagedBackendProcesses
        Remove-State
        throw
    }
}

function Run-SupervisorLoop {
    param([string]$ManagedSessionId)

    if (-not $ManagedSessionId) {
        throw "Supervisor mode requires -SessionId."
    }

    $reportedBackendPidMismatch = $false

    while ($true) {
        $state = Get-State
        if (-not $state) {
            return
        }
        if ($state.sessionId -ne $ManagedSessionId) {
            return
        }

        $trackedBackendPid = 0
        if ($state.backendPid) {
            $trackedBackendPid = [int]$state.backendPid
        }
        $backendLiveness = Get-ManagedBackendLiveness -TrackedPid $trackedBackendPid
        $backendAlive = [bool]$backendLiveness.Alive
        if (
            $backendAlive `
            -and $trackedBackendPid -gt 0 `
            -and -not $backendLiveness.TrackedPidAlive `
            -and -not $reportedBackendPidMismatch
        ) {
            Write-LauncherControlLog `
                -Event "launcher.supervisor.backend_pid.reconciled" `
                -Message "Supervisor found a live backend even though the tracked backend PID is gone." `
                -Level "warning" `
                -Fields @{
                    tracked_pid = $trackedBackendPid
                    candidate_pids = @($backendLiveness.CandidatePids)
                    healthy = [bool]$backendLiveness.Healthy
                }
            $reportedBackendPidMismatch = $true
        }

        $browserWindowCount = @(Get-ManagedBrowserWindowProcesses).Count

        if (-not $backendAlive) {
            $workbench = Get-RuntimeManagerWorkbench
            $desiredState = [string](Get-ObjectPropertyValue -Object $workbench -Name "desiredState" -Default "")
            if ($desiredState -eq "closed") {
                $closureReason = Get-RuntimeManagerWorkbenchReason -Workbench $workbench -Fallback "workbench closed"
                Write-Note "Supervisor detected backend exit after shutdown was requested. Closing the managed app window."
                Stop-ManagedSession -Reason $closureReason
            } else {
                Write-Note "Supervisor detected backend exit. Closing the managed app window."
                Stop-ManagedSession -Reason "backend exited unexpectedly"
            }
            return
        }

        if ([bool]$state.browserManaged -and $browserWindowCount -eq 0) {
            Write-Note "Supervisor detected app window closure. Stopping the backend."
            Stop-ManagedSession -Reason "app window closed"
            return
        }

        Start-Sleep -Milliseconds 900
    }
}

function Invoke-DesktopLifecycleMonitor {
    param(
        [int]$OpenTimeoutSeconds = 60,
        [int]$CloseTimeoutSeconds = 120,
        [int]$SuccessExitDelaySeconds = 2
    )

    Ensure-Directories
    Sync-LauncherEndpointFromState
    [void](Restore-RuntimeSceneContextFromState)

    Write-Note "Launcher monitor attached. Close the workbench from the web UI or this window will report the final shutdown status."
    if ($script:currentRuntimeSceneId) {
        Update-RuntimeSceneManifest @{ launcher = @{ visible_monitor = "running"; control_log_path = (Get-RuntimeSceneRelativePaths).LauncherControl } }
    }
    Write-LauncherMonitorEvent `
        -EventCode "launcher.monitor.started" `
        -Message "Visible launcher monitor attached to the managed workbench lifecycle." `
        -Outcome "started" `
        -Fields @{ open_timeout_seconds = $OpenTimeoutSeconds; close_timeout_seconds = $CloseTimeoutSeconds; control_log_path = $launcherControlLogPath }

    $initialClosure = Get-ManagedSessionClosureSnapshot
    if (Test-ManagedSessionClosureSucceeded -Closure $initialClosure -RequireManagerClosed $true) {
        Write-LauncherMonitorEvent `
            -EventCode "launcher.monitor.already_closed" `
            -Message "Launcher monitor found the workbench already closed." `
            -Outcome "succeeded" `
            -Fields @{
                backend_stopped = [bool]$initialClosure.BackendStopped
                browser_stopped = [bool]$initialClosure.BrowserStopped
                manager_closed = [bool]$initialClosure.ManagerClosed
                port_owner_pid = $initialClosure.PortOwnerPid
            }
        return
    }

    $opened = Wait-ForRuntimeManagerWorkbenchOpen -TimeoutSeconds $OpenTimeoutSeconds
    if (-not $opened) {
        [void](Restore-RuntimeSceneContextFromState)
        $closure = Get-ManagedSessionClosureSnapshot
        if (Test-ManagedSessionClosureSucceeded -Closure $closure -RequireManagerClosed $true) {
            Write-LauncherMonitorEvent `
                -EventCode "launcher.monitor.closed_before_open" `
                -Message "Workbench closed before the launcher monitor observed an open steady state." `
                -Outcome "succeeded" `
                -Fields @{
                    backend_stopped = [bool]$closure.BackendStopped
                    browser_stopped = [bool]$closure.BrowserStopped
                    manager_closed = [bool]$closure.ManagerClosed
                    port_owner_pid = $closure.PortOwnerPid
                }
            return
        }
        $workbench = Get-RuntimeManagerWorkbench
        $message = "Workbench did not reach open/steady before launcher monitor timeout."
        $fields = @{
            desired_state = [string](Get-ObjectPropertyValue -Object $workbench -Name "desiredState" -Default "")
            observed_state = [string](Get-ObjectPropertyValue -Object $workbench -Name "observedState" -Default "")
            phase = [string](Get-ObjectPropertyValue -Object $workbench -Name "phase" -Default "")
            failure_message = [string](Get-ObjectPropertyValue -Object $workbench -Name "failureMessage" -Default "")
        }
        Write-LauncherMonitorEvent `
            -EventCode "launcher.monitor.open_timeout" `
            -Message $message `
            -Level "error" `
            -Outcome "failed" `
            -Fields $fields
        throw $message
    }

    [void](Restore-RuntimeSceneContextFromState)
    Write-Note "Workbench is running. Waiting for shutdown request ..."
    Write-LauncherMonitorEvent `
        -EventCode "launcher.monitor.workbench_open" `
        -Message "Workbench reached open/steady; waiting for lifecycle shutdown." `
        -Outcome "succeeded"

    $seenClosing = $false
    $closeDeadline = $null
    $lastPhase = ""
    while ($true) {
        [void](Restore-RuntimeSceneContextFromState)
        $workbench = Get-RuntimeManagerWorkbench
        $desiredState = [string](Get-ObjectPropertyValue -Object $workbench -Name "desiredState" -Default "")
        $observedState = [string](Get-ObjectPropertyValue -Object $workbench -Name "observedState" -Default "")
        $phase = [string](Get-ObjectPropertyValue -Object $workbench -Name "phase" -Default "")
        $failureMessage = [string](Get-ObjectPropertyValue -Object $workbench -Name "failureMessage" -Default "")

        if ($phase -and $phase -ne $lastPhase) {
            $lastPhase = $phase
            Write-LauncherControlLog `
                -Event "launcher.monitor.phase" `
                -Message "Runtime manager phase changed." `
                -Fields @{ desired_state = $desiredState; observed_state = $observedState; phase = $phase }
        }

        if ($phase -eq "failed") {
            $closure = Get-ManagedSessionClosureSnapshot
            $closureReason = Get-RuntimeManagerWorkbenchReason -Workbench $workbench -Fallback "runtime manager failure"
            $closureSource = Get-RuntimeManagerWorkbenchSource -Workbench $workbench -Fallback "desktop_monitor"
            Write-ManagedSessionClosureRecord -Closure $closure -Reason $closureReason -Source $closureSource -Success $false
            Write-LauncherMonitorEvent `
                -EventCode "launcher.monitor.failed" `
                -Message "Runtime manager reported a lifecycle failure." `
                -Level "error" `
                -Outcome "failed" `
                -Fields @{
                    desired_state = $desiredState
                    observed_state = $observedState
                    phase = $phase
                    failure_message = $failureMessage
                    backend_stopped = [bool]$closure.BackendStopped
                    browser_stopped = [bool]$closure.BrowserStopped
                    manager_closed = [bool]$closure.ManagerClosed
                    port_owner_pid = $closure.PortOwnerPid
                }
            throw "Workbench lifecycle failed: $failureMessage"
        }

        if (-not $seenClosing -and $desiredState -eq "closed") {
            $seenClosing = $true
            $closeDeadline = (Get-Date).AddSeconds($CloseTimeoutSeconds)
            Write-Note "Shutdown requested. Waiting for backend and browser to close ..."
            Write-LauncherMonitorEvent `
                -EventCode "launcher.monitor.shutdown_detected" `
                -Message "Launcher monitor detected a workbench shutdown request." `
                -Outcome "observed" `
                -Fields @{ desired_state = $desiredState; observed_state = $observedState; phase = $phase }
        }

        if ($seenClosing) {
            $closure = Get-ManagedSessionClosureSnapshot
            if (Test-ManagedSessionClosureSucceeded -Closure $closure -RequireManagerClosed $true) {
                $closureReason = Get-RuntimeManagerWorkbenchReason -Workbench $workbench -Fallback "workbench closed"
                $closureSource = Get-RuntimeManagerWorkbenchSource -Workbench $workbench -Fallback "desktop_monitor"
                Write-ManagedSessionClosureRecord -Closure $closure -Reason $closureReason -Source $closureSource -Success $true
                Write-LauncherMonitorEvent `
                    -EventCode "launcher.monitor.shutdown_confirmed" `
                    -Message "Backend, browser, and runtime manager all report closed." `
                    -Outcome "succeeded" `
                    -Fields @{
                        backend_stopped = [bool]$closure.BackendStopped
                        browser_stopped = [bool]$closure.BrowserStopped
                        manager_closed = [bool]$closure.ManagerClosed
                        port_owner_pid = $closure.PortOwnerPid
                    }
                Write-Note "Backend stopped."
                Write-Note "Browser stopped."
                Write-Note "Workbench closed cleanly."
                Write-Note "Launcher will close in $SuccessExitDelaySeconds seconds."
                Start-Sleep -Seconds $SuccessExitDelaySeconds
                return
            }

            if ($closeDeadline -and (Get-Date) -gt $closeDeadline) {
                Write-ManagedSessionClosureRecord -Closure $closure -Reason "desktop monitor shutdown timeout" -Source "desktop_monitor" -Success $false
                Write-LauncherMonitorEvent `
                    -EventCode "launcher.monitor.shutdown_timeout" `
                    -Message "Shutdown did not complete before launcher monitor timeout." `
                    -Level "error" `
                    -Outcome "failed" `
                    -Fields @{
                        backend_stopped = [bool]$closure.BackendStopped
                        browser_stopped = [bool]$closure.BrowserStopped
                        manager_closed = [bool]$closure.ManagerClosed
                        backend_pids = @($closure.BackendPids)
                        browser_pids = @($closure.BrowserPids)
                        port_owner_pid = $closure.PortOwnerPid
                        desired_state = [string]$closure.DesiredState
                        observed_state = [string]$closure.ObservedState
                        phase = [string]$closure.Phase
                    }
                throw "Workbench shutdown timed out. See $launcherControlLogPath for details."
            }
        }

        Start-Sleep -Milliseconds 750
    }
}

$runtimeManagerClientActions = @("toggle", "start", "stop", "restart", "status")
if ($runtimeManagerClientActions -contains $Action) {
    $clientExitCode = 0
    switch ($Action) {
        "toggle" {
            $clientExitCode = Invoke-RuntimeManagerClient -Mode "command" -CommandType "toggle_workbench" -Reason "launcher_toggle" -ForwardNoBrowser:$NoBrowser
        }
        "start" {
            $clientExitCode = Invoke-RuntimeManagerClient -Mode "command" -CommandType "open_workbench" -Reason "launcher_start" -ForwardNoBrowser:$NoBrowser
        }
        "stop" {
            $clientExitCode = Invoke-RuntimeManagerClient -Mode "command" -CommandType "close_workbench" -Reason "launcher_stop" -StopManager
        }
        "restart" {
            $clientExitCode = Invoke-RuntimeManagerClient -Mode "command" -CommandType "restart_workbench" -Reason "launcher_restart" -ForwardNoBrowser:$NoBrowser
        }
        "status" {
            $clientExitCode = Invoke-RuntimeManagerClient -Mode "status"
        }
    }
    if ($clientExitCode -ne 0) {
        exit $clientExitCode
    }
    return
}

Acquire-LauncherMutex
try {
    Sync-LauncherEndpointFromState
    switch ($Action) {
        "toggle" {
            $snapshot = Get-SessionSnapshot
            if ($snapshot.BackendPids.Count -gt 0 -or $snapshot.BrowserPids.Count -gt 0 -or $snapshot.State) {
                Stop-ManagedSession -Reason "toggle stop"
            } else {
                Start-ManagedSession
            }
        }
        "internal-start" {
            Start-ManagedSession
        }
        "start" {
            Start-ManagedSession
        }
        "internal-stop" {
            Stop-ManagedSession -Reason "runtime manager stop"
        }
        "stop" {
            Stop-ManagedSession -Reason "explicit stop"
        }
        "internal-restart" {
            Stop-ManagedSession -Reason "runtime manager restart"
            Start-ManagedSession
        }
        "monitor" {
            Invoke-DesktopLifecycleMonitor
        }
        "restart" {
            Stop-ManagedSession -Reason "restart"
            Start-ManagedSession
        }
        "internal-status" {
            Show-Status
        }
        "status" {
            Show-Status
        }
        "supervise" {
            Run-SupervisorLoop -ManagedSessionId $SessionId
        }
    }
} finally {
    Release-LauncherMutex
}
