param(
    [int]$Port = 8765,
    [string]$HostName = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "python"
}

$logDir = Join-Path $projectRoot ".runtime\computer-use"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stdout = Join-Path $logDir "bridge.out.log"
$stderr = Join-Path $logDir "bridge.err.log"
$tokenFile = Join-Path $logDir "bridge.token"
if (Test-Path -LiteralPath $tokenFile) {
    $bridgeToken = (Get-Content -LiteralPath $tokenFile -Raw).Trim()
} else {
    $bridgeToken = [Convert]::ToBase64String([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
    Set-Content -LiteralPath $tokenFile -Value $bridgeToken -Encoding utf8
}
$env:VIBELUTION_COMPUTER_USE_BRIDGE_TOKEN = $bridgeToken

$existing = Get-NetTCPConnection -LocalAddress $HostName -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    try {
        $health = Invoke-RestMethod -Uri "http://${HostName}:$Port/health" -Method Get -TimeoutSec 2
    } catch {
        throw "Port $Port is already listening, but it is not a compatible Computer Use bridge. Stop that process or choose a different -Port."
    }
    if (-not $health.bridgeAuth) {
        throw "Computer Use bridge at http://${HostName}:$Port is an older process without token confirmation support. Stop it and rerun this script."
    }
    Write-Host "Computer Use bridge already listening at http://${HostName}:$Port"
} else {
    $script = Join-Path $projectRoot "scripts\computer_use_bridge.py"
    Start-Process -FilePath $python `
        -ArgumentList @($script, "--host", $HostName, "--port", "$Port") `
        -WorkingDirectory $projectRoot `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle Hidden
    Start-Sleep -Milliseconds 800
}

$env:VIBELUTION_COMPUTER_USE_ENABLED = "1"
$env:VIBELUTION_COMPUTER_USE_BASE_URL = "http://${HostName}:$Port"
Write-Host "Set current shell:"
Write-Host "`$env:VIBELUTION_COMPUTER_USE_ENABLED=`"1`""
Write-Host "`$env:VIBELUTION_COMPUTER_USE_BASE_URL=`"http://${HostName}:$Port`""
Write-Host "`$env:VIBELUTION_COMPUTER_USE_BRIDGE_TOKEN=`"$bridgeToken`""
Write-Host "Bridge logs: $logDir"
