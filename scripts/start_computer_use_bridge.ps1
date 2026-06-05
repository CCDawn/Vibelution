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

$existing = Get-NetTCPConnection -LocalAddress $HostName -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
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
Write-Host "Bridge logs: $logDir"
