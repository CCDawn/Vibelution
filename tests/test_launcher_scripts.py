import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parent.parent
LAUNCHER_SCRIPT = PROJECT_ROOT / "scripts" / "vibelution_launcher.ps1"
DESKTOP_ENTRY_SCRIPT = PROJECT_ROOT / "scripts" / "vibelution_desktop_entry.ps1"
DESKTOP_ENTRY_VBS = PROJECT_ROOT / "scripts" / "vibelution_desktop_entry.vbs"


def test_web_workbench_access_log_filter_suppresses_polling_noise_only():
    from scripts.web_workbench import WorkbenchAccessLogFilter

    log_filter = WorkbenchAccessLogFilter()

    def access_record(message: str) -> logging.LogRecord:
        return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, message, (), None)

    suppressed_messages = [
        '127.0.0.1:51112 - "GET /api/health HTTP/1.1" 200 OK',
        '127.0.0.1:51113 - "GET /api/runtime/summary HTTP/1.1" 200 OK',
        '127.0.0.1:51114 - "GET /api/git/status HTTP/1.1" 200 OK',
        '127.0.0.1:51115 - "GET /api/evolution/active-run HTTP/1.1" 200 OK',
        '127.0.0.1:51116 - "GET /api/evolution/runs HTTP/1.1" 200 OK',
        '127.0.0.1:51117 - "POST /api/runtime/browser-telemetry HTTP/1.1" 202 Accepted',
    ]
    kept_messages = [
        '127.0.0.1:51118 - "POST /api/evolution/runs HTTP/1.1" 202 Accepted',
        '127.0.0.1:51119 - "POST /api/evolution/proposals/delete HTTP/1.1" 200 OK',
        '127.0.0.1:51120 - "GET /supervised-evolution HTTP/1.1" 200 OK',
        '127.0.0.1:51121 - "GET /assets/index.js HTTP/1.1" 200 OK',
        'application startup complete',
    ]

    assert all(log_filter.filter(access_record(message)) is False for message in suppressed_messages)
    assert all(log_filter.filter(access_record(message)) is True for message in kept_messages)


def test_web_workbench_access_log_filter_installs_once(monkeypatch):
    from scripts.web_workbench import WorkbenchAccessLogFilter, install_access_log_filters

    logger = logging.getLogger("uvicorn.access")
    original_filters = list(logger.filters)
    logger.filters = []
    try:
        install_access_log_filters()
        install_access_log_filters()

        assert sum(isinstance(item, WorkbenchAccessLogFilter) for item in logger.filters) == 1
    finally:
        logger.filters = original_filters


def _powershell_exe() -> str:
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        pytest.skip("PowerShell is required for launcher script tests")
    return exe


def _cscript_exe() -> str:
    exe = shutil.which("cscript")
    if not exe:
        pytest.skip("cscript is required for VBS desktop entry tests")
    return exe


def _resolve_launcher_backend_port(
    tmp_path: Path,
    *,
    config_text: str,
    env_overrides: dict[str, str] | None = None,
) -> int:
    config_path = tmp_path / "config.toml"
    config_path.write_text(config_text, encoding="utf-8")

    harness_path = tmp_path / "resolve-launcher-port.ps1"
    harness_path.write_text(
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath,
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Resolve-ConfiguredWorkbenchPort"
}, $true)
if ($null -eq $functionAst) {
    throw "Resolve-ConfiguredWorkbenchPort was not found."
}

. ([scriptblock]::Create($functionAst.Extent.Text))
Set-Variable -Name configPath -Value $ConfigPath -Scope Script
Write-Output ([string](Resolve-ConfiguredWorkbenchPort))
""".strip(),
        encoding="utf-8",
    )

    command = [_powershell_exe(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness_path)]
    command += ["-LauncherPath", str(LAUNCHER_SCRIPT), "-ConfigPath", str(config_path)]
    env = os.environ.copy()
    env.pop("VIBELUTION_PORT", None)
    env.pop("AGENT_WORKBENCH_BACKEND_PORT", None)
    if env_overrides:
        env.update(env_overrides)

    result = subprocess.run(command, capture_output=True, text=True, env=env, check=False, timeout=20)
    assert result.returncode == 0, result.stderr or result.stdout
    return int(result.stdout.strip().splitlines()[-1])


def _run_desktop_entry_with_fake_launcher(
    tmp_path: Path,
    *,
    action: str,
    no_browser: bool = False,
) -> list[dict[str, object]]:
    project_dir = tmp_path / "project"
    scripts_dir = project_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    shutil.copyfile(DESKTOP_ENTRY_SCRIPT, scripts_dir / "vibelution_desktop_entry.ps1")
    (scripts_dir / "vibelution_launcher.ps1").write_text(
        """
param(
    [string]$Action = "",
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$projectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$logDir = Join-Path $projectDir ".runtime\\launcher"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}
$payload = @{
    action = $Action
    noBrowser = [bool]$NoBrowser
    argv = @($args)
} | ConvertTo-Json -Depth 8 -Compress
Add-Content -LiteralPath (Join-Path $logDir "fake-launcher-calls.jsonl") -Value $payload -Encoding utf8
""".strip(),
        encoding="utf-8",
    )

    command = [
        _powershell_exe(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(scripts_dir / "vibelution_desktop_entry.ps1"),
        "-Action",
        action,
    ]
    if no_browser:
        command.append("-NoBrowser")

    result = subprocess.run(command, capture_output=True, text=True, cwd=project_dir, check=False, timeout=30)
    assert result.returncode == 0, result.stderr or result.stdout

    calls_path = project_dir / ".runtime" / "launcher" / "fake-launcher-calls.jsonl"
    assert calls_path.exists()
    return [json.loads(line) for line in calls_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def _run_vbs_desktop_entry_with_fake_powershell_entry(
    tmp_path: Path,
    args: list[str],
) -> list[dict[str, object]]:
    project_dir = tmp_path / "project"
    scripts_dir = project_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    shutil.copyfile(DESKTOP_ENTRY_VBS, scripts_dir / "vibelution_desktop_entry.vbs")
    (scripts_dir / "vibelution_desktop_entry.ps1").write_text(
        """
param(
    [string]$Action = "",
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$projectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$logDir = Join-Path $projectDir ".runtime\\launcher"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}
$payload = @{
    action = $Action
    noBrowser = [bool]$NoBrowser
    argv = @($args)
} | ConvertTo-Json -Depth 8 -Compress
Add-Content -LiteralPath (Join-Path $logDir "fake-vbs-entry-calls.jsonl") -Value $payload -Encoding utf8
""".strip(),
        encoding="utf-8",
    )

    command = [_cscript_exe(), "//NoLogo", str(scripts_dir / "vibelution_desktop_entry.vbs"), *args]
    result = subprocess.run(command, capture_output=True, text=True, cwd=project_dir, check=False, timeout=30)
    assert result.returncode == 0, result.stderr or result.stdout

    calls_path = project_dir / ".runtime" / "launcher" / "fake-vbs-entry-calls.jsonl"
    deadline = time.time() + 5
    while time.time() < deadline and not calls_path.exists():
        time.sleep(0.05)
    assert calls_path.exists()
    return [json.loads(line) for line in calls_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def _run_launcher_ast_harness(tmp_path: Path, harness_source: str) -> subprocess.CompletedProcess[str]:
    harness_path = tmp_path / "launcher-ast-harness.ps1"
    harness_path.write_text(harness_source.strip(), encoding="utf-8")
    command = [
        _powershell_exe(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(harness_path),
        "-LauncherPath",
        str(LAUNCHER_SCRIPT),
    ]
    return subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)


def test_launcher_backend_port_accepts_agent_env_alias(tmp_path):
    resolved = _resolve_launcher_backend_port(
        tmp_path,
        config_text="[workbench]\nbackend_port = 9101\n",
        env_overrides={"AGENT_WORKBENCH_BACKEND_PORT": "9401"},
    )

    assert resolved == 9401


def test_launcher_backend_port_prefers_vibelution_env_over_agent_alias(tmp_path):
    resolved = _resolve_launcher_backend_port(
        tmp_path,
        config_text="[workbench]\nbackend_port = 9101\n",
        env_overrides={
            "VIBELUTION_PORT": "9301",
            "AGENT_WORKBENCH_BACKEND_PORT": "9401",
        },
    )

    assert resolved == 9301


def test_launcher_backend_port_ignores_invalid_config_token(tmp_path):
    resolved = _resolve_launcher_backend_port(
        tmp_path,
        config_text="[workbench]\nbackend_port = 9101oops\n",
    )

    assert resolved == 8000


def test_launcher_state_save_uses_retrying_atomic_writer(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$saveStateAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Save-State"
}, $true)
if ($null -eq $saveStateAst) {
    throw "Save-State was not found."
}

$writeStateAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Write-LauncherStateFile"
}, $true)
if ($null -eq $writeStateAst) {
    throw "Write-LauncherStateFile was not found."
}

$saveStateText = $saveStateAst.Extent.Text
$writeStateText = $writeStateAst.Extent.Text
if ($saveStateText -notmatch "Write-LauncherStateFile") {
    throw "Save-State does not use Write-LauncherStateFile."
}
if ($saveStateText -match "Set-Content") {
    throw "Save-State still writes state with Set-Content."
}
if ($writeStateText -notmatch "Move-Item") {
    throw "Write-LauncherStateFile does not atomically move a temp file into place."
}
if ($writeStateText -notmatch "Start-Sleep") {
    throw "Write-LauncherStateFile does not retry after a failed write."
}
if ($writeStateText -notmatch "launcher.state.write.failed") {
    throw "Write-LauncherStateFile does not log final write failure."
}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_state_writer_outputs_utf8_json_without_bom(tmp_path):
    state_path = tmp_path / "state.json"
    result = _run_launcher_ast_harness(
        tmp_path,
        f"""
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {{
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}}

$functionAst = $ast.Find({{
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Write-LauncherStateFile"
}}, $true)
if ($null -eq $functionAst) {{
    throw "Write-LauncherStateFile was not found."
}}

. ([scriptblock]::Create($functionAst.Extent.Text))
$script:launcherStateWriteMaxAttempts = 2
$script:launcherStateWriteRetryDelayMilliseconds = 1
function Write-LauncherControlLog {{
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{{}})
}}

Write-LauncherStateFile -Path {json.dumps(str(state_path))} -Value '{{"status":"ok","text":"中文"}}'
$bytes = [System.IO.File]::ReadAllBytes({json.dumps(str(state_path))})
if ($bytes.Length -ge 3 -and $bytes[0] -eq 239 -and $bytes[1] -eq 187 -and $bytes[2] -eq 191) {{
    throw "state file has UTF-8 BOM."
}}
$payload = Get-Content -LiteralPath {json.dumps(str(state_path))} -Raw -Encoding UTF8 | ConvertFrom-Json
if ($payload.status -ne "ok" -or $payload.text -ne "中文") {{
    throw "state JSON did not round-trip."
}}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_runtime_manager_client_forwards_expected_command_flags(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Invoke-RuntimeManagerClient"
}, $true)
if ($null -eq $functionAst) {
    throw "Invoke-RuntimeManagerClient was not found."
}

. ([scriptblock]::Create($functionAst.Extent.Text))

$script:calls = @()
function Resolve-PythonRuntime {
    return [pscustomobject]@{ FilePath = "python-test"; PrefixArgs = @() }
}
function Invoke-HiddenNativeCommand {
    param([string]$CommandPath, [string[]]$ArgumentList = @())
    $script:calls += ,@{
        commandPath = $CommandPath
        argumentList = @($ArgumentList)
    }
    return 0
}
function Set-LauncherWindowTitle {}

Invoke-RuntimeManagerClient -Mode "command" -CommandType "open_workbench" -Reason "launcher_start" -ForwardNoBrowser
Invoke-RuntimeManagerClient -Mode "command" -CommandType "close_workbench" -Reason "launcher_stop" -StopManager
Invoke-RuntimeManagerClient -Mode "status"

$openArgs = @($script:calls[0].argumentList)
$closeArgs = @($script:calls[1].argumentList)
$statusArgs = @($script:calls[2].argumentList)

if ($openArgs -notcontains "--no-browser") { throw "open_workbench did not forward --no-browser." }
if ($openArgs -contains "--stop-manager") { throw "open_workbench forwarded --stop-manager unexpectedly." }
if ($closeArgs -notcontains "--stop-manager") { throw "close_workbench did not forward --stop-manager." }
if ($closeArgs -contains "--no-browser") { throw "close_workbench forwarded --no-browser unexpectedly." }
if ($statusArgs -contains "command") { throw "status used command mode unexpectedly." }
if ($statusArgs -notcontains "status") { throw "status did not invoke runtime manager status." }
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_runtime_scene_package_search_text_expands_tags(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($name in @(
    "ConvertTo-RuntimeSceneIndexToken",
    "Get-RuntimeSceneTriggerIndexToken",
    "Get-RuntimeSceneStatusIndexToken",
    "Get-RuntimeSceneStatusDisplayLabel",
    "Get-RuntimeSceneTriggerDisplayLabel",
    "Get-RuntimeScenePackageIndex"
)) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)
    if ($null -eq $functionAst) {
        throw "$name was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$index = Get-RuntimeScenePackageIndex `
    -SceneId "scene-a" `
    -StartedAt ([datetime]"2026-05-18T12:00:00Z") `
    -Trigger "internal-start" `
    -Status "stopped" `
    -Result "explicit_stop" `
    -StopReason "manual stop" `
    -EndedAt "2026-05-18T12:03:00Z"

if ($index.search_text -match "System\\.Object\\[\\]") {
    throw "search_text contains a stringified tag array."
}
foreach ($tag in @("runtime-scene", "workbench-lifecycle", "workbench-start", "manual-stop", "managed")) {
    if ($index.search_text -notmatch [regex]::Escape($tag)) {
        throw "search_text is missing tag $tag."
    }
}
if (@($index.tags) -contains "System.Object[]") {
    throw "tags contains a stringified array."
}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_runtime_scene_manifest_writes_package_index_file(tmp_path):
    scene_dir = tmp_path / "scene"
    result = _run_launcher_ast_harness(
        tmp_path,
        f"""
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {{
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}}

foreach ($name in @(
    "ConvertTo-RuntimeSceneIndexToken",
    "Get-RuntimeSceneTriggerIndexToken",
    "Get-RuntimeSceneStatusIndexToken",
    "Get-RuntimeSceneStatusDisplayLabel",
    "Get-RuntimeSceneTriggerDisplayLabel",
    "Get-RuntimeScenePackageIndex",
    "ConvertTo-PlainHashtable",
    "Save-RuntimeSceneManifest"
)) {{
    $functionAst = $ast.Find({{
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }}, $true)
    if ($null -eq $functionAst) {{
        throw "$name was not found."
    }}
    . ([scriptblock]::Create($functionAst.Extent.Text))
}}

$script:currentRuntimeSceneDir = {json.dumps(str(scene_dir))}
function Ensure-CurrentRuntimeSceneSubdirs {{
    New-Item -ItemType Directory -Path $script:currentRuntimeSceneDir -Force | Out-Null
}}
function Get-CurrentRuntimeSceneFilePath {{
    param([string]$RelativePath)
    return Join-Path $script:currentRuntimeSceneDir $RelativePath
}}

Save-RuntimeSceneManifest -Manifest @{{
    schema_version = 2
    runtime_scene_id = "scene-a"
    started_at = "2026-05-18T12:00:00Z"
    ended_at = "2026-05-18T12:03:00Z"
    status = "stopped"
    result = "explicit_stop"
    stop_reason = "manual stop"
    trigger = "internal-start"
}}

$manifest = Get-Content -LiteralPath (Join-Path $script:currentRuntimeSceneDir "manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$packageIndex = Get-Content -LiteralPath (Join-Path $script:currentRuntimeSceneDir "package_index.json") -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.package.package_index_path -ne "package_index.json") {{
    throw "manifest package does not point to package_index.json."
}}
if ($packageIndex.package_id -ne "scene-a") {{
    throw "package_index package_id did not round-trip."
}}
if ($packageIndex.index_key -ne $manifest.package.index_key) {{
    throw "package_index and manifest package index_key diverged."
}}
if ($packageIndex.search_text -match "System\\.Object\\[\\]") {{
    throw "package_index search_text contains a stringified tag array."
}}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_closure_record_normalizes_successful_manifest_runtime_manager(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Write-ManagedSessionClosureRecord"
}, $true)
if ($null -eq $functionAst) {
    throw "Write-ManagedSessionClosureRecord was not found."
}
. ([scriptblock]::Create($functionAst.Extent.Text))

$script:currentRuntimeSceneId = "scene-1"
$launcherControlLogPath = "control.log"
$script:manifestUpdates = @()
$script:manifestState = @{}
$script:controlFields = @()
function Get-RuntimeSceneFinalState {
    param([string]$Reason)
    if ($Reason -match "startup failure") {
        return @{ status = "failed"; result = "startup_failed" }
    }
    return @{ status = "stopped"; result = "runtime_manager_stop" }
}
function Get-RuntimeSceneRelativePaths {
    return [pscustomobject]@{ LauncherControl = "raw/launcher-control.log" }
}
function Get-RuntimeSceneManifest {
    return $script:manifestState
}
function Update-RuntimeSceneManifest {
    param([hashtable]$Changes)
    $script:manifestUpdates += ,$Changes
    foreach ($key in $Changes.Keys) {
        $script:manifestState[$key] = $Changes[$key]
    }
}
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:controlFields += ,$Fields
}

$closingSnapshot = [pscustomobject]@{
    BackendStopped = $true
    BrowserStopped = $true
    ManagerClosed = $false
    BackendPids = @()
    BrowserPids = @()
    BrowserWindowCount = 0
    PortOwnerPid = $null
    DesiredState = "closed"
    ObservedState = "open"
    Phase = "closing"
    FailureMessage = ""
}

Write-ManagedSessionClosureRecord -Closure $closingSnapshot -Reason "runtime manager stop" -Source "launcher_stop" -Success $true
Write-ManagedSessionClosureRecord -Closure $closingSnapshot -Reason "launcher_start" -Source "desktop_monitor" -Success $true
Write-ManagedSessionClosureRecord -Closure $closingSnapshot -Reason "desktop monitor shutdown timeout" -Source "desktop_monitor" -Success $false
Write-ManagedSessionClosureRecord -Closure $closingSnapshot -Reason "startup failure" -Source "launcher_stop" -Success $true

$successRuntimeManager = $script:manifestUpdates[0].runtime_manager
$monitorRuntimeManager = $script:manifestUpdates[1].runtime_manager
$failedRuntimeManager = $script:manifestUpdates[2].runtime_manager
$startupFailureRuntimeManager = $script:manifestUpdates[3].runtime_manager
$payload = @{
    success = $successRuntimeManager
    successSupervisor = $script:manifestUpdates[0].supervisor
    monitor = @{
        result = $script:manifestUpdates[1].result
        stopReason = $script:manifestUpdates[1].stop_reason
        runtimeManager = $monitorRuntimeManager
        supervisor = $script:manifestUpdates[1].supervisor
    }
    failed = $failedRuntimeManager
    failedHasSupervisor = $script:manifestUpdates[2].ContainsKey("supervisor")
    startupFailure = $startupFailureRuntimeManager
    startupFailureHasSupervisor = $script:manifestUpdates[3].ContainsKey("supervisor")
    controlLogPhase = $script:controlFields[0].phase
    controlLogObservedState = $script:controlFields[0].observed_state
} | ConvertTo-Json -Depth 8 -Compress
Write-Output $payload
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["success"] == {
        "desired_state": "closed",
        "failure_message": "",
        "observed_state": "closed",
        "phase": "steady",
    }
    assert payload["successSupervisor"] == {"pid": 0, "status": "stopped"}
    assert payload["monitor"]["result"] == "runtime_manager_stop"
    assert payload["monitor"]["stopReason"] == "runtime manager stop"
    assert payload["monitor"]["runtimeManager"]["observed_state"] == "closed"
    assert payload["monitor"]["runtimeManager"]["phase"] == "steady"
    assert payload["monitor"]["supervisor"] == {"pid": 0, "status": "stopped"}
    assert payload["failed"]["observed_state"] == "open"
    assert payload["failed"]["phase"] == "closing"
    assert payload["failedHasSupervisor"] is False
    assert payload["startupFailure"]["observed_state"] == "open"
    assert payload["startupFailure"]["phase"] == "closing"
    assert payload["startupFailureHasSupervisor"] is False
    assert payload["controlLogObservedState"] == "open"
    assert payload["controlLogPhase"] == "closing"


def test_launcher_backend_liveness_accepts_reconciled_backend(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($functionName in @("Get-ManagedBackendLiveness", "Test-ManagedBackendAlive")) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:candidatePids = @(2222)
$script:webHealthy = $false
function Get-ManagedBackendCandidatePids { return @($script:candidatePids) }
function Test-ProcessAlive { param([int]$ProcessId) return $false }
function Test-WebHealthy { return [bool]$script:webHealthy }

$candidateOnly = Get-ManagedBackendLiveness -TrackedPid 1111
if (-not $candidateOnly.Alive -or $candidateOnly.TrackedPidAlive -or $candidateOnly.CandidatePids[0] -ne 2222) {
    throw "candidate backend was not accepted as alive."
}
if (-not (Test-ManagedBackendAlive -TrackedPid 1111)) {
    throw "Test-ManagedBackendAlive rejected a candidate backend."
}

$script:candidatePids = @()
$script:webHealthy = $true
$healthyOnly = Get-ManagedBackendLiveness -TrackedPid 1111
if (-not $healthyOnly.Alive -or -not $healthyOnly.Healthy) {
    throw "healthy backend was not accepted as alive."
}

$script:webHealthy = $false
$dead = Get-ManagedBackendLiveness -TrackedPid 1111
if ($dead.Alive) {
    throw "dead backend was accepted as alive."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_wait_for_backend_healthy_does_not_abort_on_wrapper_pid_exit(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Wait-ForBackendHealthy"
}, $true)
if ($null -eq $functionAst) {
    throw "Wait-ForBackendHealthy was not found."
}
. ([scriptblock]::Create($functionAst.Extent.Text))

$script:livenessCalls = 0
function Get-ManagedBackendLiveness {
    param([int]$TrackedPid = 0)
    $script:livenessCalls += 1
    return [pscustomobject]@{
        Alive = $false
        Healthy = ($script:livenessCalls -ge 2)
        TrackedPid = $TrackedPid
        TrackedPidAlive = $false
        CandidatePids = @()
    }
}
function Start-Sleep { param([int]$Milliseconds, [int]$Seconds) }

$healthy = Wait-ForBackendHealthy -ProcessId 1111 -TimeoutSeconds 5
if (-not $healthy) {
    throw "Wait-ForBackendHealthy aborted before the delayed healthy probe."
}
if ($script:livenessCalls -ne 2) {
    throw "Expected two liveness probes, got $script:livenessCalls."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_supervisor_does_not_stop_when_backend_pid_is_reconciled(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Run-SupervisorLoop"
}, $true)
if ($null -eq $functionAst) {
    throw "Run-SupervisorLoop was not found."
}
. ([scriptblock]::Create($functionAst.Extent.Text))

$script:getStateCalls = 0
$script:stops = @()
$script:controlEvents = @()
function Get-State {
    $script:getStateCalls += 1
    if ($script:getStateCalls -gt 1) {
        return $null
    }
    return [pscustomobject]@{
        sessionId = "session-1"
        backendPid = 1111
        browserManaged = $true
    }
}
function Get-ManagedBackendLiveness {
    param([int]$TrackedPid = 0)
    return [pscustomobject]@{
        Alive = $true
        Healthy = $true
        TrackedPid = $TrackedPid
        TrackedPidAlive = $false
        CandidatePids = @(2222)
    }
}
function Get-ManagedBrowserWindowProcesses {
    return @([pscustomobject]@{ Id = 3333; MainWindowHandle = 1 })
}
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:controlEvents += $Event
}
function Stop-ManagedSession {
    param([string]$Reason = "")
    $script:stops += $Reason
}
function Write-Note { param([string]$Message) }
function Start-Sleep { param([int]$Milliseconds, [int]$Seconds) }

Run-SupervisorLoop -ManagedSessionId "session-1"

$payload = @{
    stops = @($script:stops)
    controlEvents = @($script:controlEvents)
    getStateCalls = $script:getStateCalls
} | ConvertTo-Json -Depth 8 -Compress
Write-Output $payload
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["stops"] == []
    assert payload["getStateCalls"] == 2
    assert "launcher.supervisor.backend_pid.reconciled" in payload["controlEvents"]


def test_desktop_entry_maps_open_to_start_then_monitor(tmp_path):
    calls = _run_desktop_entry_with_fake_launcher(tmp_path, action="open")

    assert [call["action"] for call in calls] == ["start", "monitor"]
    assert [call["noBrowser"] for call in calls] == [False, False]


def test_desktop_entry_maps_close_to_stop_without_monitor(tmp_path):
    calls = _run_desktop_entry_with_fake_launcher(tmp_path, action="close")

    assert calls == [{"action": "stop", "argv": [], "noBrowser": False}]


def test_desktop_entry_runs_restart_then_monitor(tmp_path):
    calls = _run_desktop_entry_with_fake_launcher(tmp_path, action="restart")

    assert [call["action"] for call in calls] == ["restart", "monitor"]
    assert [call["noBrowser"] for call in calls] == [False, False]


def test_desktop_entry_status_does_not_attach_monitor(tmp_path):
    calls = _run_desktop_entry_with_fake_launcher(tmp_path, action="status")

    assert calls == [{"action": "status", "argv": [], "noBrowser": False}]


def test_desktop_entry_forwards_no_browser_and_skips_monitor(tmp_path):
    calls = _run_desktop_entry_with_fake_launcher(tmp_path, action="open", no_browser=True)

    assert calls == [{"action": "start", "argv": [], "noBrowser": True}]


def test_vbs_desktop_entry_accepts_named_action_arguments(tmp_path):
    calls = _run_vbs_desktop_entry_with_fake_powershell_entry(tmp_path, ["-Action", "close"])

    assert calls == [{"action": "close", "argv": [], "noBrowser": False}]


def test_vbs_desktop_entry_accepts_powershell_style_no_browser_switch(tmp_path):
    calls = _run_vbs_desktop_entry_with_fake_powershell_entry(tmp_path, ["open", "-NoBrowser"])

    assert calls == [{"action": "open", "argv": [], "noBrowser": True}]


def test_vbs_desktop_entry_accepts_colon_action_argument(tmp_path):
    calls = _run_vbs_desktop_entry_with_fake_powershell_entry(tmp_path, ["-Action:status"])

    assert calls == [{"action": "status", "argv": [], "noBrowser": False}]


def test_vbs_desktop_entry_accepts_equals_action_argument(tmp_path):
    calls = _run_vbs_desktop_entry_with_fake_powershell_entry(tmp_path, ["--action=restart", "--no-browser"])

    assert calls == [{"action": "restart", "argv": [], "noBrowser": True}]
