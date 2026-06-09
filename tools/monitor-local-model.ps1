[CmdletBinding()]
param(
    [string]$ServerId = "",
    [string]$RegistryPath = "",
    [string]$ServerHost = "192.168.20.30",
    [string]$SshHost = "bossai-server",
    [int]$Port = 8081,
    [int]$IntervalSeconds = 5,
    [int]$HttpTimeoutSeconds = 5,
    [string]$LogFile = "/tmp/houmo-llama-server.log",
    [int]$LogLines = 160,
    [switch]$Once,
    [switch]$NoSsh,
    [switch]$NoClear,
    [switch]$Probe
)

$ErrorActionPreference = "Stop"

function Resolve-ServerRegistryPath {
    param([string]$Path)

    $candidates = New-Object System.Collections.Generic.List[string]
    if ($Path) { [void]$candidates.Add($Path) }
    if ($env:VIBELUTION_SERVER_REGISTRY) { [void]$candidates.Add($env:VIBELUTION_SERVER_REGISTRY) }

    $scriptPath = if ($PSCommandPath) { $PSCommandPath } else { $MyInvocation.MyCommand.Path }
    if ($scriptPath) {
        $scriptRoot = Split-Path -Parent $scriptPath
        $projectRoot = Split-Path -Parent $scriptRoot
        [void]$candidates.Add((Join-Path $projectRoot ".runtime\servers.json"))
        [void]$candidates.Add((Join-Path $projectRoot "config\servers.local.json"))
    }

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    if ($Path) { return $Path }
    return ""
}

if ($ServerId) {
    $resolvedRegistryPath = Resolve-ServerRegistryPath $RegistryPath
    if (-not $resolvedRegistryPath) {
        throw "ServerId requires a server registry. Pass -RegistryPath or set VIBELUTION_SERVER_REGISTRY."
    }
    if (-not (Test-Path -LiteralPath $resolvedRegistryPath)) {
        throw "Server registry not found: $resolvedRegistryPath"
    }

    $registry = Get-Content -LiteralPath $resolvedRegistryPath -Raw | ConvertFrom-Json
    if ($null -eq $registry.servers) {
        throw "Server registry is missing a 'servers' object: $resolvedRegistryPath"
    }
    $entryProperty = $registry.servers.PSObject.Properties[$ServerId]
    if ($null -eq $entryProperty) {
        $known = $registry.servers.PSObject.Properties.Name -join ", "
        throw "Unknown server '$ServerId'. Known servers: $known"
    }

    $entry = $entryProperty.Value
    if ($entry.PSObject.Properties["configured"] -and -not [bool]$entry.configured) {
        throw "Server '$ServerId' is not configured yet. Fill $resolvedRegistryPath first."
    }
    if ($entry.host) { $ServerHost = [string]$entry.host }
    if ($entry.sshAlias) { $SshHost = [string]$entry.sshAlias }
    if ($entry.ports -and $entry.ports.model) { $Port = [int]$entry.ports.model }
    if ($entry.model -and $entry.model.logFile) { $LogFile = [string]$entry.model.logFile }
}

$BaseUrl = "http://$ServerHost`:$Port"

function Get-Prop {
    param($Object, [string]$Name, $Default = $null)
    if ($null -eq $Object) { return $Default }
    if ($Object -is [System.Collections.IDictionary] -and $Object.Contains($Name)) {
        return $Object[$Name]
    }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $Default }
    return $property.Value
}

function Format-Short {
    param($Value, [int]$Max = 120)
    $text = if ($null -eq $Value) { "" } else { [string]$Value }
    $text = $text -replace "`r", " " -replace "`n", " "
    if ($text.Length -le $Max) { return $text }
    return $text.Substring(0, [Math]::Max(0, $Max - 3)) + "..."
}

function Invoke-ModelEndpoint {
    param([string]$Path, [string]$Method = "GET", $Body = $null)
    $uri = "$BaseUrl$Path"
    $started = Get-Date
    try {
        $request = @{
            Uri = $uri
            Method = $Method
            TimeoutSec = $HttpTimeoutSeconds
            UseBasicParsing = $true
        }
        if ($null -ne $Body) {
            $request.ContentType = "application/json"
            $request.Body = ($Body | ConvertTo-Json -Depth 8 -Compress)
        }
        $response = Invoke-WebRequest @request
        $elapsed = ((Get-Date) - $started).TotalSeconds
        $json = $null
        if ($response.Content) {
            try { $json = $response.Content | ConvertFrom-Json } catch { $json = $null }
        }
        [pscustomobject]@{
            Path = $Path
            Code = [int]$response.StatusCode
            Latency = "{0:N3}" -f $elapsed
            Json = $json
            Text = $response.Content
            Error = $null
        }
    } catch {
        $elapsed = ((Get-Date) - $started).TotalSeconds
        [pscustomobject]@{
            Path = $Path
            Code = "n/a"
            Latency = "{0:N3}" -f $elapsed
            Json = $null
            Text = ""
            Error = $_.Exception.Message
        }
    }
}

function Invoke-RemoteSnapshot {
    if ($NoSsh) {
        return @("ssh disabled; HTTP-only monitor")
    }

    $safeLogFile = $LogFile.Replace("'", "'\''")
    $modelPort = [string]$Port
    $remote = @'
set -u
MODEL_PORT='__MODEL_PORT__'
echo "[PROCESS]"
pid="$(pgrep -f "llama-server.*--port[ =]$MODEL_PORT" | head -1 || true)"
if [ -z "$pid" ]; then pid="$(pgrep -f 'llama-server' | head -1 || true)"; fi
if [ -z "$pid" ]; then
  echo "llama-server: not found"
else
  ps -p "$pid" -o pid=,ppid=,etime=,%cpu=,%mem=,rss=,vsz=,comm= 2>/dev/null | awk '{printf "pid=%s ppid=%s uptime=%s cpu=%s%% mem=%s%% rss=%.1fMiB vsz=%.1fMiB comm=%s\n", $1, $2, $3, $4, $5, $6/1024, $7/1024, $8}'
  printf "cwd="
  readlink -f "/proc/$pid/cwd" 2>/dev/null || true
fi

echo "[SYSTEM]"
awk '{print "loadavg: " $1 " " $2 " " $3 " running=" $4}' /proc/loadavg 2>/dev/null || true
free -h 2>/dev/null | awk '/^Mem|^内存/ {print "memory: used=" $3 " free=" $4 " avail=" $7} /^Swap|^交换/ {print "swap: used=" $3 " free=" $4}'
if command -v vmstat >/dev/null 2>&1; then
  vmstat 1 2 2>/dev/null | tail -1 | awk '{printf "cpu: user=%s%% system=%s%% idle=%s%% wait=%s%%\n", $13, $14, $15, $16}'
fi
ss -ltnp 2>/dev/null | awk -v model_port=":$MODEL_PORT" '/:3001/ {api="up"} /:5173/ {web="up"} /:7901/ {hlie="up"} index($0, model_port) {model="up"} END {printf "ports: api=%s web=%s model=%s hlie=%s\n", (api?api:"down"), (web?web:"down"), (model?model:"down"), (hlie?hlie:"down")}'

echo "[ACCELERATOR]"
houmo_monitor="/home/kylin/BossAI-dev/BossAI/tools/houmo-xh2-monitor"
if [ -x "$houmo_monitor" ]; then
  LD_LIBRARY_PATH=/usr/local/houmo-sdk/hal/lib:${LD_LIBRARY_PATH:-} timeout 3 "$houmo_monitor" 2>&1 | sed 's/\[/\n[/g' | sed '/^$/d' | head -8 | sed 's/^/houmo: /' || true
  printf '\n'
elif command -v nvidia-smi >/dev/null 2>&1; then
  timeout 3 nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw --format=csv,noheader,nounits 2>&1 | head -4 | sed 's/^/nvidia: /'
else
  echo "accelerator monitor: unavailable"
fi

echo "[RUNTIME LOG]"
LOG_FILE='__LOG_FILE__'
LOG_LINES=__LOG_LINES__
if [ ! -r "$LOG_FILE" ]; then
  echo "log: unavailable ($LOG_FILE)"
else
  echo "log_file: $LOG_FILE"
  perf="$(tail -n "$LOG_LINES" "$LOG_FILE" 2>/dev/null | grep -Ei 'context [0-9]+/[0-9]+|TTFT|TOPT|E2E|TPS|prompt eval|decoder eval|tokens per second' | tail -3 | tr '\n' ' ' | cut -c 1-220)"
  [ -n "$perf" ] && echo "perf: $perf" || echo "perf: none in tail"
  errors="$(tail -n "$LOG_LINES" "$LOG_FILE" 2>/dev/null | grep -Ei 'error|failed|exception|traceback| 4[0-9][0-9] | 5[0-9][0-9] |invalid|unavailable' || true)"
  count="$(printf '%s\n' "$errors" | sed '/^$/d' | wc -l | awk '{print $1}')"
  if [ "$count" = "0" ]; then
    echo "errors: 0"
  else
    last="$(printf '%s\n' "$errors" | tail -1 | tr '\n' ' ' | cut -c 1-180)"
    echo "errors_in_last_$LOG_LINES: $count | last=$last"
  fi
fi
'@
    $remote = $remote.Replace("__MODEL_PORT__", $modelPort).Replace("__LOG_FILE__", $safeLogFile).Replace("__LOG_LINES__", [string]$LogLines)

    try {
        $encoded = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($remote))
        $command = "printf '%s' '$encoded' | base64 -d | bash"
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $output = & ssh -o BatchMode=yes -o ConnectTimeout=5 $SshHost $command 2>&1
        $sshExitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousErrorActionPreference
        $output = @($output | Where-Object { ([string]$_).Trim() -ne "Kylin V10 SP1" })
        if ($sshExitCode -ne 0) {
            return @("ssh failed: exit=$sshExitCode", ($output | Select-Object -First 4))
        }
        return @($output)
    } catch {
        if ($null -ne $previousErrorActionPreference) {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        return @("ssh failed: $($_.Exception.Message)")
    }
}

function Get-SectionLines {
    param([string[]]$Lines, [string]$Section)
    $marker = "[$Section]"
    $capture = $false
    $result = New-Object System.Collections.Generic.List[string]
    foreach ($line in $Lines) {
        if ($line -eq $marker) {
            $capture = $true
            continue
        }
        if ($capture -and $line -match '^\[[A-Z ]+\]$') { break }
        if ($capture -and $line) { [void]$result.Add($line) }
    }
    return $result.ToArray()
}

function Get-LineOrDefault {
    param([string[]]$Lines, [int]$Index, [string]$Default = "")
    if ($null -eq $Lines) { return $Default }
    if ($Lines.Count -le $Index) { return $Default }
    return $Lines[$Index]
}

function Get-Snapshot {
    $health = Invoke-ModelEndpoint "/health"
    $models = Invoke-ModelEndpoint "/v1/models"
    $props = Invoke-ModelEndpoint "/props"
    $slots = Invoke-ModelEndpoint "/slots"
    $metrics = Invoke-ModelEndpoint "/metrics"

    $probeResult = $null
    if ($Probe) {
        $probeResult = Invoke-ModelEndpoint "/completion" "POST" @{
            prompt = "Reply with OK."
            n_predict = 4
            temperature = 0
        }
    }

    $remoteLines = Invoke-RemoteSnapshot
    [pscustomobject]@{
        Time = Get-Date
        Health = $health
        Models = $models
        Props = $props
        Slots = $slots
        Metrics = $metrics
        Probe = $probeResult
        RemoteLines = [string[]]$remoteLines
    }
}

function Get-ModelSummary {
    param($Snapshot)
    $healthStatus = Get-Prop $Snapshot.Health.Json "status" "unavailable"
    $modelId = "unknown"
    $desc = ""
    $ctx = "unknown"
    $params = "unknown"
    $rows = @()
    $dataRows = Get-Prop $Snapshot.Models.Json "data" @()
    $modelRows = Get-Prop $Snapshot.Models.Json "models" @()
    if ($dataRows) { $rows += @($dataRows) }
    if ($modelRows) { $rows += @($modelRows) }
    foreach ($row in $rows) {
        if ($null -eq $row) { continue }
        $modelId = Get-Prop $row "id" (Get-Prop $row "name" (Get-Prop $row "model" $modelId))
        $meta = Get-Prop $row "meta" $null
        $details = Get-Prop $row "details" $null
        $desc = Get-Prop $meta "model_desc" (Get-Prop $row "description" (Get-Prop $details "family" ""))
        $ctx = Get-Prop $meta "n_ctx_length" $ctx
        $nParams = Get-Prop $meta "n_params" $null
        if ($nParams) { $params = "{0:N0}" -f [double]$nParams }
        break
    }

    $props = $Snapshot.Props.Json
    $settings = Get-Prop $props "default_generation_settings" $null
    $paramObj = Get-Prop $settings "params" $null
    $propCtx = Get-Prop $settings "n_ctx" (Get-Prop $paramObj "n_ctx" $ctx)
    $totalSlots = Get-Prop $props "total_slots" "unknown"
    $metricsEnabled = Get-Prop $props "endpoint_metrics" "unknown"
    $kv = "unknown"
    try {
        if ($propCtx -ne "unknown" -and $totalSlots -ne "unknown") {
            $kvBytes = [double]$propCtx * [double]$totalSlots * 98304
            $kv = "{0:N2} GiB" -f ($kvBytes / [Math]::Pow(1024, 3))
        }
    } catch {
        $kv = "unknown"
    }

    $slotLine = "slots: unavailable"
    if ($Snapshot.Slots.Json) {
        $slotArray = @($Snapshot.Slots.Json)
        $busy = 0
        $parts = New-Object System.Collections.Generic.List[string]
        foreach ($slot in $slotArray) {
            if (Get-Prop $slot "is_processing" $false) { $busy++ }
            $nextTokens = @(Get-Prop $slot "next_token" @())
            $next = if ($nextTokens.Count -gt 0) { $nextTokens[0] } else { $null }
            $state = if (Get-Prop $slot "is_processing" $false) { "busy" } else { "idle" }
            [void]$parts.Add(("#{0} {1} task={2} ctx={3} decoded={4} remain={5}" -f `
                (Get-Prop $slot "id" "?"), $state, (Get-Prop $slot "id_task" "?"), `
                (Get-Prop $slot "n_ctx" "?"), (Get-Prop $next "n_decoded" "?"), (Get-Prop $next "n_remain" "?")))
            if ($parts.Count -ge 2) { break }
        }
        $slotLine = "slots: total=$($slotArray.Count) busy=$busy " + ($parts -join " | ")
    }

    [pscustomobject]@{
        Line1 = "health: $healthStatus | endpoints: health $($Snapshot.Health.Code)($($Snapshot.Health.Latency)s) models $($Snapshot.Models.Code) props $($Snapshot.Props.Code) slots $($Snapshot.Slots.Code) metrics $($Snapshot.Metrics.Code)"
        Line2 = "model: $(Format-Short $modelId 110)"
        Line3 = "desc: $(Format-Short $desc 38) | ctx=$propCtx | slots=$totalSlots | kv~$kv | metrics=$metricsEnabled | params=$params"
        Line4 = Format-Short $slotLine 130
    }
}

function Write-At {
    param([int]$Row, [string]$Text)
    $width = try { [Console]::WindowWidth } catch { 120 }
    if ($width -lt 80) { $width = 80 }
    if ($width -gt 160) { $width = 160 }
    $line = Format-Short $Text ($width - 1)
    $padded = $line.PadRight($width - 1)
    try {
        [Console]::SetCursorPosition(0, [Math]::Max(0, $Row - 1))
        Write-Host $padded -NoNewline
    } catch {
        Write-Host $line
    }
}

function Write-Rule {
    param([int]$Row)
    $width = try { [Console]::WindowWidth } catch { 120 }
    if ($width -lt 80) { $width = 80 }
    if ($width -gt 160) { $width = 160 }
    Write-At $Row ("-" * ($width - 1))
}

function Render-Dashboard {
    param($Snapshot)
    $summary = Get-ModelSummary $Snapshot
    $process = Get-SectionLines $Snapshot.RemoteLines "PROCESS"
    $system = Get-SectionLines $Snapshot.RemoteLines "SYSTEM"
    $accelerator = Get-SectionLines $Snapshot.RemoteLines "ACCELERATOR"
    $logs = Get-SectionLines $Snapshot.RemoteLines "RUNTIME LOG"

    Write-At 1 ("Vibelution Local Model Monitor | {0} | refresh={1}s | base={2}" -f $Snapshot.Time.ToString("yyyy-MM-dd HH:mm:ss"), $IntervalSeconds, $BaseUrl)
    Write-Rule 2
    Write-At 3 "[MODEL]"
    Write-At 4 $summary.Line1
    Write-At 5 $summary.Line2
    Write-At 6 $summary.Line3
    Write-At 7 $summary.Line4
    Write-Rule 8
    Write-At 9 "[REMOTE PROCESS]"
    Write-At 10 (Get-LineOrDefault $process 0 "no process data")
    Write-At 11 (Get-LineOrDefault $process 1 "")
    Write-At 12 "[REMOTE SYSTEM]"
    Write-At 13 (Get-LineOrDefault $system 0 "no system data")
    Write-At 14 (Get-LineOrDefault $system 1 "")
    Write-At 15 (Get-LineOrDefault $system 2 "")
    Write-At 16 (Get-LineOrDefault $system 3 "")
    Write-At 17 (Get-LineOrDefault $system 4 "")
    Write-Rule 18
    Write-At 19 "[ACCELERATOR]"
    Write-At 20 (Get-LineOrDefault $accelerator 0 "no accelerator data")
    Write-At 21 (Get-LineOrDefault $accelerator 1 "")
    Write-At 22 (Get-LineOrDefault $accelerator 2 "")
    Write-At 23 (Get-LineOrDefault $accelerator 3 "")
    Write-Rule 24
    Write-At 25 "[RUNTIME LOG]"
    Write-At 26 (Get-LineOrDefault $logs 0 "no log data")
    Write-At 27 (Get-LineOrDefault $logs 1 "")
    Write-At 28 (Get-LineOrDefault $logs 2 "")
    if ($Probe -and $Snapshot.Probe) {
        Write-At 29 ("probe: code=$($Snapshot.Probe.Code) latency=$($Snapshot.Probe.Latency)s error=$(Format-Short $Snapshot.Probe.Error 80)")
    } else {
        Write-At 29 "probe: off"
    }
    Write-At 30 "Press Ctrl+C to stop. Options: -Once -IntervalSeconds 1 -NoSsh -Probe"
}

function Write-Snapshot {
    param($Snapshot)
    $summary = Get-ModelSummary $Snapshot
    Write-Host "Vibelution local model monitor"
    Write-Host "time: $($Snapshot.Time.ToString("yyyy-MM-dd HH:mm:ss"))"
    Write-Host "base_url: $BaseUrl"
    Write-Host ""
    Write-Host "[MODEL]"
    Write-Host $summary.Line1
    Write-Host $summary.Line2
    Write-Host $summary.Line3
    Write-Host $summary.Line4
    Write-Host ""
    $Snapshot.RemoteLines | ForEach-Object { Write-Host $_ }
}

if ($IntervalSeconds -lt 1) {
    throw "IntervalSeconds must be >= 1."
}

if ($Once) {
    Write-Snapshot (Get-Snapshot)
    return
}

if (-not $NoClear) {
    [Console]::Clear()
}

try {
    [Console]::CursorVisible = $false
    while ($true) {
        Render-Dashboard (Get-Snapshot)
        Start-Sleep -Seconds $IntervalSeconds
    }
} finally {
    try { [Console]::CursorVisible = $true } catch {}
    Write-Host ""
}
