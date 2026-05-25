import json
import logging
import os
import shutil
import subprocess
import sys
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


def test_web_workbench_accepts_managed_launcher_marker():
    from scripts import web_workbench

    args = web_workbench.parse_args(
        [
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--no-browser",
            "--managed-by-launcher",
        ]
    )

    assert args.managed_by_launcher is True


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


def _loads_json_line_allowing_control_chars(line: str) -> dict[str, object]:
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        sanitized = "".join(char for char in line if char >= " " or char in "\t\r\n")
        return json.loads(sanitized)


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
    venv_scripts_dir = project_dir / ".venv" / "Scripts"
    venv_scripts_dir.mkdir(parents=True)
    (venv_scripts_dir / "python.exe").write_text("console python", encoding="utf-8")
    (venv_scripts_dir / "python.exe").write_text("console python", encoding="utf-8")
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
    pythonExe = $env:VIBELUTION_PYTHON_EXE
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

    env = os.environ.copy()
    env["VIBELUTION_DESKTOP_ENTRY_SUPPRESS_FEEDBACK"] = "1"
    env["VIBELUTION_DESKTOP_ENTRY_START_MUTEX_NAME"] = f"Local\\Vibelution.Tests.{tmp_path.name}.{action}"
    result = subprocess.run(command, capture_output=True, text=True, cwd=project_dir, env=env, check=False, timeout=30)
    assert result.returncode == 0, result.stderr or result.stdout

    calls_path = project_dir / ".runtime" / "launcher" / "fake-launcher-calls.jsonl"
    assert calls_path.exists()
    return [json.loads(line) for line in calls_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def _run_vbs_desktop_entry_with_fake_powershell_entry(
    tmp_path: Path,
    args: list[str],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    project_dir = tmp_path / "project"
    scripts_dir = project_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    venv_scripts_dir = project_dir / ".venv" / "Scripts"
    venv_scripts_dir.mkdir(parents=True)
    (venv_scripts_dir / "python.exe").write_text("console python", encoding="utf-8")
    (venv_scripts_dir / "python.exe").write_text("console python", encoding="utf-8")
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
    pythonExe = $env:VIBELUTION_PYTHON_EXE
} | ConvertTo-Json -Depth 8 -Compress
Add-Content -LiteralPath (Join-Path $logDir "fake-vbs-entry-calls.jsonl") -Value $payload -Encoding utf8
""".strip(),
        encoding="utf-8",
    )

    command = [_cscript_exe(), "//NoLogo", str(scripts_dir / "vibelution_desktop_entry.vbs"), *args]
    env = os.environ.copy()
    env["VIBELUTION_DESKTOP_ENTRY_SUPPRESS_FEEDBACK"] = "1"
    env["VIBELUTION_DESKTOP_ENTRY_START_MUTEX_NAME"] = f"Local\\Vibelution.Tests.{tmp_path.name}.failure.{time.time_ns()}"
    result = subprocess.run(command, capture_output=True, text=True, cwd=project_dir, env=env, check=False, timeout=30)
    assert result.returncode == 0, result.stderr or result.stdout

    calls_path = project_dir / ".runtime" / "launcher" / "fake-vbs-entry-calls.jsonl"
    deadline = time.time() + 5
    while time.time() < deadline and not calls_path.exists():
        time.sleep(0.05)
    assert calls_path.exists()
    calls = [json.loads(line) for line in calls_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    log_path = project_dir / ".runtime" / "launcher" / "desktop-entry-vbs.log"
    events = [
        _loads_json_line_allowing_control_chars(line)
        for line in log_path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    return calls, events


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


def _run_desktop_entry_ast_harness(tmp_path: Path, harness_source: str) -> subprocess.CompletedProcess[str]:
    harness_path = tmp_path / "desktop-entry-ast-harness.ps1"
    harness_path.write_text(harness_source.strip(), encoding="utf-8")
    command = [
        _powershell_exe(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(harness_path),
        "-DesktopEntryPath",
        str(DESKTOP_ENTRY_SCRIPT),
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


def test_launcher_native_commands_are_hidden_and_python_checks_use_helper(tmp_path):
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

$nativeCommandAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Invoke-NativeCommand"
}, $true)
if ($null -eq $nativeCommandAst) {
    throw "Invoke-NativeCommand was not found."
}
$hiddenProcessAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Invoke-HiddenProcessCapture"
}, $true)
if ($null -eq $hiddenProcessAst) {
    throw "Invoke-HiddenProcessCapture was not found."
}
$hiddenProcessText = $hiddenProcessAst.Extent.Text
if ($hiddenProcessText -notmatch 'CreateNoWindow\\s*=\\s*\\$true') {
    throw "Invoke-HiddenProcessCapture does not force CreateNoWindow."
}
if ($hiddenProcessText -notmatch 'UseShellExecute\\s*=\\s*\\$false') {
    throw "Invoke-HiddenProcessCapture does not avoid shell execution."
}
if ($hiddenProcessText -notmatch 'ProcessWindowStyle\\]::Hidden') {
    throw "Invoke-HiddenProcessCapture does not set hidden window style."
}
if ($hiddenProcessText -notmatch "RedirectStandardOutput" -or $hiddenProcessText -notmatch "RedirectStandardError") {
    throw "Invoke-HiddenProcessCapture does not capture native output."
}
$nativeCommandText = $nativeCommandAst.Extent.Text
if ($nativeCommandText -notmatch "Invoke-HiddenProcessCapture") {
    throw "Invoke-NativeCommand does not use the no-window process helper."
}

$testPythonAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Test-PythonRuntime"
}, $true)
if ($null -eq $testPythonAst) {
    throw "Test-PythonRuntime was not found."
}
$testPythonText = $testPythonAst.Extent.Text
if ($testPythonText -match '&\\s+\\$CommandPath') {
    throw "Test-PythonRuntime still invokes python directly."
}
if ($testPythonText -notmatch "Invoke-NativeCommand" -or $testPythonText -notmatch "SuppressOutput") {
    throw "Test-PythonRuntime does not use the hidden native helper."
}

$depsAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Ensure-ProjectPythonDependencies"
}, $true)
if ($null -eq $depsAst) {
    throw "Ensure-ProjectPythonDependencies was not found."
}
$depsText = $depsAst.Extent.Text
if ($depsText -match '&\\s+\\$installTarget\\.FilePath') {
    throw "Python dependency install still invokes pip directly."
}
if ($depsText -notmatch "Invoke-NativeCommand") {
    throw "Python dependency install does not use the hidden native helper."
}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_frontend_npm_invocation_avoids_cmd_wrapper(tmp_path):
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

$resolveAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Resolve-NpmInvocation"
}, $true)
if ($null -eq $resolveAst) {
    throw "Resolve-NpmInvocation was not found."
}
$resolveText = $resolveAst.Extent.Text
if ($source -match "function\\s+Resolve-NpmCommand") {
    throw "Legacy Resolve-NpmCommand still exists."
}
if ($resolveText -notmatch "node_modules\\\\npm\\\\bin\\\\npm-cli\\.js") {
    throw "npm invocation does not resolve npm-cli.js."
}
if ($resolveText -notmatch 'LaunchStrategy\\s*=\\s*"node_npm_cli"') {
    throw "npm invocation does not record the node npm-cli launch strategy."
}

foreach ($functionName in @("Ensure-FrontendDependencies", "Ensure-WebBuild")) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    $text = $functionAst.Extent.Text
    if ($text -match "Resolve-NpmCommand" -or $text -match '\\$npmCommand') {
        throw "$functionName still uses the legacy npm command wrapper."
    }
    if ($text -notmatch "Resolve-NpmInvocation") {
        throw "$functionName does not resolve a shell-free npm invocation."
    }
    if ($text -notmatch '\\$npmInvocation\\.CommandPath') {
        throw "$functionName does not launch npm through the invocation command path."
    }
    if ($text -notmatch '\\$npmInvocation\\.PrefixArgs') {
        throw "$functionName does not pass npm-cli.js as prefix args."
    }
    if ($text -notmatch "npm_launch_strategy") {
        throw "$functionName does not log the npm launch strategy."
    }
}

$nativeCommandAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Invoke-NativeCommand"
}, $true)
$nativeCommandText = $nativeCommandAst.Extent.Text
if ($nativeCommandText -notmatch "launcher.native_command.started" -or
    $nativeCommandText -notmatch "launcher.native_command.completed" -or
    $nativeCommandText -notmatch "console_window_suppressed") {
    throw "hidden native command lifecycle logging is incomplete."
}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_background_processes_are_started_without_windows(tmp_path):
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

$hiddenBackgroundAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Start-HiddenBackgroundProcess"
}, $true)
if ($null -eq $hiddenBackgroundAst) {
    throw "Start-HiddenBackgroundProcess was not found."
}
$hiddenBackgroundText = $hiddenBackgroundAst.Extent.Text
if ($hiddenBackgroundText -notmatch 'CreateNoWindow\\s*=\\s*\\$true') {
    throw "Start-HiddenBackgroundProcess does not force CreateNoWindow."
}
if ($hiddenBackgroundText -notmatch 'UseShellExecute\\s*=\\s*\\$false') {
    throw "Start-HiddenBackgroundProcess does not avoid shell execution."
}
if ($hiddenBackgroundText -notmatch 'ProcessWindowStyle\\]::Hidden') {
    throw "Start-HiddenBackgroundProcess does not set hidden window style."
}

$guiProcessAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Start-GuiProcessWithoutConsole"
}, $true)
if ($null -eq $guiProcessAst) {
    throw "Start-GuiProcessWithoutConsole was not found."
}
$guiProcessText = $guiProcessAst.Extent.Text
if ($guiProcessText -match "Start-Process") {
    throw "GUI process helper still uses Start-Process."
}
if ($guiProcessText -notmatch 'CreateNoWindow\\s*=\\s*\\$true') {
    throw "GUI process helper does not force CreateNoWindow."
}
if ($guiProcessText -notmatch 'UseShellExecute\\s*=\\s*\\$false') {
    throw "GUI process helper does not avoid shell execution."
}
if ($guiProcessText -notmatch 'ProcessWindowStyle\\]::Normal') {
    throw "GUI process helper should keep GUI windows visible while suppressing console windows."
}

$redirectedAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Start-RedirectedBackgroundProcess"
}, $true)
if ($null -eq $redirectedAst) {
    throw "Start-RedirectedBackgroundProcess was not found."
}
$redirectedText = $redirectedAst.Extent.Text
if ($redirectedText -match "cmd.exe" -or $redirectedText -match "ComSpec" -or $redirectedText -match "/c") {
    throw "Redirected background process still shells out through cmd."
}
if ($redirectedText -match "Start-Process") {
    throw "Redirected background process still uses Start-Process."
}
if ($redirectedText -notmatch 'StartHiddenRedirected') {
    throw "Redirected background process does not use the Win32 no-window redirected starter."
}
if ($redirectedText -notmatch 'ConvertTo-ProcessArgumentString') {
    throw "Redirected background process does not construct an explicit command line."
}
if ($source -notmatch 'CREATE_NO_WINDOW' -or $source -notmatch 'STARTF_USESTDHANDLES') {
    throw "Redirected background process does not force no-window inherited file handles."
}
if ($redirectedText -notmatch 'distinct stdout and stderr log paths') {
    throw "Redirected background process does not guard against same-file stdout/stderr redirection."
}

foreach ($functionName in @("Start-ManagedBackend", "Start-Supervisor")) {
$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq $functionName
}, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    $functionText = $functionAst.Extent.Text
    if ($functionText -match "Start-Process") {
        throw "$functionName still uses Start-Process."
    }
    if ($functionText -notmatch "Start-RedirectedBackgroundProcess") {
        throw "$functionName does not use the redirected no-window helper."
    }
}

$managedBackendAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Start-ManagedBackend"
}, $true)
$managedBackendText = $managedBackendAst.Extent.Text
if ($managedBackendText -notmatch '--managed-by-launcher') {
    if ($managedBackendText -notmatch 'managedBackendMarkerArg' -or $managedBackendText -notmatch 'managed_marker') {
        throw "Start-ManagedBackend does not tag backend processes as launcher-managed."
    }
}
if ($managedBackendText -notmatch 'managed_marker') {
    throw "Start-ManagedBackend does not log the managed backend marker."
}
if ($managedBackendText -notmatch 'Resolve-ManagedBackendPythonRuntime') {
    throw "Start-ManagedBackend does not resolve a backend-specific no-console Python runtime."
}
if ($managedBackendText -notmatch 'console_host_avoidance') {
    throw "Start-ManagedBackend does not log the console host avoidance strategy."
}

$browserAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Start-ManagedBrowser"
}, $true)
if ($null -eq $browserAst) {
    throw "Start-ManagedBrowser was not found."
}
$browserText = $browserAst.Extent.Text
if ($browserText -match "Start-Process") {
    throw "Start-ManagedBrowser still uses Start-Process."
}
if ($browserText -notmatch "Start-GuiProcessWithoutConsole") {
    throw "Start-ManagedBrowser does not use the no-console GUI helper."
}
if ($browserText -notmatch "gui_process_without_console" -or $browserText -notmatch "console_window_suppressed") {
    throw "Start-ManagedBrowser does not log the no-console launch strategy."
}

$saveStateAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Save-SessionState"
}, $true)
if ($null -eq $saveStateAst) {
    throw "Save-SessionState was not found."
}
$saveStateText = $saveStateAst.Extent.Text
if ($saveStateText -notmatch 'backendLaunchPid\\s*=\\s*\\$BackendLaunchPid') {
    throw "Save-SessionState does not persist backendLaunchPid."
}
if ($saveStateText -notmatch 'supervisorStderr\\s*=\\s*if \\(\\$script:currentRuntimeSceneDir\\)') {
    throw "Save-SessionState does not persist supervisorStderr."
}
$managedSessionText = ($ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Start-ManagedSession"
}, $true)).Extent.Text
if ($managedSessionText -notmatch 'BackendLaunchPid\\s+\\$backendProc\\.LauncherPid') {
    throw "Start-ManagedSession does not save the backend launcher PID."
}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_upgrades_headless_backend_before_cleanup(tmp_path):
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

$completeAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Complete-HeadlessSessionWithBrowser"
}, $true)
if ($null -eq $completeAst) {
    throw "Complete-HeadlessSessionWithBrowser was not found."
}
$completeText = $completeAst.Extent.Text
foreach ($required in @(
    "runtime.scene.headless_upgrade.started",
    "Start-ManagedBrowser",
    "Start-Supervisor",
    "Save-SessionState",
    "runtime.scene.headless_upgrade.succeeded"
)) {
    if ($completeText -notmatch [regex]::Escape($required)) {
        throw "Headless upgrade is missing '$required'."
    }
}

$managedAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Start-ManagedSession"
}, $true)
if ($null -eq $managedAst) {
    throw "Start-ManagedSession was not found."
}
$managedText = $managedAst.Extent.Text
$upgradeIndex = $managedText.IndexOf("Complete-HeadlessSessionWithBrowser")
$cleanupIndex = $managedText.IndexOf("Found an incomplete managed session")
if ($upgradeIndex -lt 0) {
    throw "Start-ManagedSession does not attempt a headless backend upgrade."
}
if ($cleanupIndex -lt 0) {
    throw "Start-ManagedSession cleanup branch was not found."
}
    if ($upgradeIndex -gt $cleanupIndex) {
        throw "Headless backend upgrade must run before stale cleanup."
    }
    foreach ($required in @(
        "launcher.session.snapshot",
        "backend_healthy",
        "browser_window_count",
        "state_present",
        "restart_reason"
    )) {
        if ($managedText -notmatch [regex]::Escape($required)) {
            throw "Start-ManagedSession snapshot log is missing '$required'."
        }
    }
    Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_runtime_scene_initialization_persists_active_sidecar(tmp_path):
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

foreach ($functionName in @("Save-ActiveRuntimeSceneReference", "Initialize-RuntimeScene")) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    if ($functionName -eq "Initialize-RuntimeScene" -and $functionAst.Extent.Text -notmatch "Save-ActiveRuntimeSceneReference") {
        throw "Initialize-RuntimeScene does not persist the active runtime scene sidecar."
    }
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_frontend_build_failure_summary_includes_typescript_error(tmp_path):
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

foreach ($functionName in @("Get-RuntimeSceneRelativePaths", "Get-LogTail", "Get-FrontendBuildFailureSummary")) {{
    $functionAst = $ast.Find({{
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }}, $true)
    if ($null -eq $functionAst) {{
        throw "$functionName was not found."
    }}
    . ([scriptblock]::Create($functionAst.Extent.Text))
}}

$script:currentRuntimeSceneDir = {json.dumps(str(scene_dir))}
function Get-CurrentRuntimeSceneFilePath {{
    param([string]$RelativePath)
    return Join-Path $script:currentRuntimeSceneDir $RelativePath
}}
New-Item -ItemType Directory -Path (Join-Path $script:currentRuntimeSceneDir "raw") -Force | Out-Null
Set-Content -LiteralPath (Join-Path $script:currentRuntimeSceneDir "raw\\frontend.build.log") -Encoding utf8 -Value @(
    "vite v6.0.0 building",
    "web/src/routes/ToolsRoute.tsx(476,49): error TS2322: Type mismatch.",
    "At scripts/vibelution_launcher.ps1:2616 char:13"
)

$summary = Get-FrontendBuildFailureSummary -ExitCode 2
if ($summary -notmatch "npm run build failed with exit code 2") {{
    throw "Build failure summary does not include the npm exit code."
}}
if ($summary -notmatch "frontend\\.build\\.failed") {{
    throw "Build failure summary does not include the build failure event code."
}}
if ($summary -notmatch "ToolsRoute\\.tsx\\(476,49\\): error TS2322") {{
    throw "Build failure summary does not include the first TypeScript error."
}}
if ($summary -match "At scripts") {{
    throw "Build failure summary should prefer TypeScript errors over PowerShell stack noise."
}}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_python_candidates_prefer_python_runtime(tmp_path):
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
        $node.Name -eq "Get-ProjectPythonCandidates"
}, $true)
if ($null -eq $functionAst) {
    throw "Get-ProjectPythonCandidates was not found."
}
. ([scriptblock]::Create($functionAst.Extent.Text))

$projectDir = Join-Path $env:TEMP ("vibelution-python-candidates-" + [guid]::NewGuid().ToString("N"))
$scriptsDir = Join-Path $projectDir ".venv\\Scripts"
New-Item -ItemType Directory -Path $scriptsDir -Force | Out-Null
$pythonPath = Join-Path $scriptsDir "python.exe"
Set-Content -LiteralPath $pythonPath -Value "" -Encoding ascii
Set-Variable -Name preferredPythonExe -Value $pythonPath -Scope Script
Set-Variable -Name launcherPythonOverride -Value $pythonPath -Scope Script

$candidates = @(Get-ProjectPythonCandidates)
if ($candidates.Count -ne 1) {
    throw "Expected one deduplicated Python candidate, got $($candidates.Count)."
}
if ($candidates[0].FilePath -ne (Resolve-Path -LiteralPath $pythonPath).Path) {
    throw "Launcher did not prefer python.exe."
}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_backend_service_runtime_prefers_pythonw_without_changing_dependency_runtime(tmp_path):
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
        $node.Name -eq "Resolve-ManagedBackendPythonRuntime"
}, $true)
if ($null -eq $functionAst) {
    throw "Resolve-ManagedBackendPythonRuntime was not found."
}
. ([scriptblock]::Create($functionAst.Extent.Text))

$projectDir = Join-Path $env:TEMP ("vibelution-backend-runtime-" + [guid]::NewGuid().ToString("N"))
$scriptsDir = Join-Path $projectDir ".venv\\Scripts"
New-Item -ItemType Directory -Path $scriptsDir -Force | Out-Null
$pythonPath = Join-Path $scriptsDir "python.exe"
$pythonwPath = Join-Path $scriptsDir "pythonw.exe"
Set-Content -LiteralPath $pythonPath -Value "" -Encoding ascii
Set-Content -LiteralPath $pythonwPath -Value "" -Encoding ascii

$dependencyRuntime = [pscustomobject]@{
    FilePath = (Resolve-Path -LiteralPath $pythonPath).Path
    PrefixArgs = @()
    Label = "project venv"
}
$serviceRuntime = Resolve-ManagedBackendPythonRuntime -PythonRuntime $dependencyRuntime

if ($dependencyRuntime.FilePath -ne (Resolve-Path -LiteralPath $pythonPath).Path) {
    throw "Dependency runtime was mutated."
}
if ($serviceRuntime.FilePath -ne (Resolve-Path -LiteralPath $pythonwPath).Path) {
    throw "Backend service runtime did not switch to sibling pythonw.exe."
}
if ($serviceRuntime.BaseFilePath -ne (Resolve-Path -LiteralPath $pythonPath).Path) {
    throw "Backend service runtime did not preserve the dependency runtime path."
}
if ($serviceRuntime.ConsoleHostAvoidance -ne "pythonw_service_runtime") {
    throw "Backend service runtime did not record the console-host avoidance strategy."
}
if (@($serviceRuntime.PrefixArgs).Count -ne 0) {
    throw "Backend service runtime unexpectedly changed prefix args."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_bootstrap_creates_project_venv_before_python_dependency_repair(tmp_path):
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

$bootstrapAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Ensure-ProjectVirtualEnvironment"
}, $true)
if ($null -eq $bootstrapAst) {
    throw "Ensure-ProjectVirtualEnvironment was not found."
}

$depsAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Ensure-ProjectPythonDependencies"
}, $true)
if ($null -eq $depsAst) {
    throw "Ensure-ProjectPythonDependencies was not found."
}

$bootstrapText = $bootstrapAst.Extent.Text
$depsText = $depsAst.Extent.Text
if ($bootstrapText -notmatch 'Get-Command\\s+python') {
    throw "Virtual environment bootstrap does not discover Python from PATH."
}
if ($bootstrapText -notmatch '"-m",\\s*"venv"') {
    throw "Virtual environment bootstrap does not create the project venv with python -m venv."
}
if ($bootstrapText -notmatch 'bootstrap.virtualenv.create.started') {
    throw "Virtual environment bootstrap start event is not logged."
}
if ($bootstrapText -notmatch 'bootstrap.virtualenv.create.succeeded') {
    throw "Virtual environment bootstrap success event is not logged."
}
if ($bootstrapText -notmatch 'bootstrap.virtualenv.create.failed') {
    throw "Virtual environment bootstrap failure event is not logged."
}
if ($depsText -notmatch 'Ensure-ProjectVirtualEnvironment') {
    throw "Python dependency repair does not bootstrap the project venv first."
}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_virtualenv_bootstrap_is_idempotent(tmp_path):
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

$names = @("Ensure-ProjectVirtualEnvironment", "Get-ProjectPythonCandidates")
foreach ($name in $names) {
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

$script:commands = @()
$script:controlEvents = @()
$script:runtimeEvents = @()
$script:currentRuntimeSceneId = "test-scene"
$projectDir = Join-Path $env:TEMP ("vibelution-bootstrap-" + [guid]::NewGuid().ToString("N"))
$projectVenvDir = Join-Path $projectDir ".venv"
$preferredPythonExe = Join-Path $projectVenvDir "Scripts\\python.exe"
$launcherPythonOverride = ""
New-Item -ItemType Directory -Path $projectDir -Force | Out-Null

function Write-Note {
    param([string]$Message)
}
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:controlEvents += ,@{ event = $Event; level = $Level; fields = $Fields }
}
function Write-RuntimeSceneEvent {
    param(
        [string]$Component,
        [string]$Phase,
        [string]$EventCode,
        [string]$Message,
        [string]$Level = "info",
        [string]$Outcome = "observed",
        [hashtable]$Fields = @{}
    )
    $script:runtimeEvents += ,@{ component = $Component; phase = $Phase; eventCode = $EventCode; outcome = $Outcome; level = $Level }
}
function Invoke-NativeCommand {
    param([string]$CommandPath, [string[]]$ArgumentList = @())
    $script:commands += ,@{ commandPath = $CommandPath; argumentList = @($ArgumentList) }
    if ($ArgumentList.Count -ge 3 -and $ArgumentList[0] -eq "-m" -and $ArgumentList[1] -eq "venv") {
        $scriptsDir = Join-Path $ArgumentList[2] "Scripts"
        New-Item -ItemType Directory -Path $scriptsDir -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $scriptsDir "python.exe") -Value "" -Encoding ascii
    }
    return 0
}

Ensure-ProjectVirtualEnvironment
Ensure-ProjectVirtualEnvironment

if ($script:commands.Count -ne 1) {
    throw "Expected virtualenv bootstrap to run once, got $($script:commands.Count)."
}
$args = @($script:commands[0].argumentList)
if ($args[0] -ne "-m" -or $args[1] -ne "venv" -or $args[2] -ne $projectVenvDir) {
    throw "Virtualenv bootstrap did not invoke python -m venv for the project venv."
}
if (-not (Test-Path -LiteralPath $preferredPythonExe)) {
    throw "Virtualenv bootstrap did not create the project python path."
}
$candidate = @(Get-ProjectPythonCandidates)[0]
if ($candidate.FilePath -ne (Resolve-Path -LiteralPath $preferredPythonExe).Path) {
    throw "Project venv was not returned as the preferred Python candidate."
}
if (@($script:controlEvents | Where-Object { $_.event -eq "bootstrap.virtualenv.create.succeeded" }).Count -ne 1) {
    throw "Virtualenv bootstrap success was not logged once."
}
if (@($script:runtimeEvents | Where-Object { $_.eventCode -eq "bootstrap.virtualenv.create.succeeded" }).Count -ne 1) {
    throw "Virtualenv bootstrap success was not written to runtime scene once."
}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_runtime_scene_lifecycle_event_classifier_indexes_operational_phases(tmp_path):
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
        $node.Name -eq "Test-RuntimeSceneLifecycleEvent"
}, $true)
if ($null -eq $functionAst) {
    throw "Test-RuntimeSceneLifecycleEvent was not found."
}
. ([scriptblock]::Create($functionAst.Extent.Text))

foreach ($phase in @(
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
)) {
    $payload = @{
        component = "probe"
        phase = $phase
        event_code = "probe.$phase"
    }
    if (-not (Test-RuntimeSceneLifecycleEvent -Payload $payload)) {
        throw "Lifecycle classifier did not index phase '$phase'."
    }
}

if (-not (Test-RuntimeSceneLifecycleEvent -Payload @{ component = "runtime"; phase = "misc"; event_code = "runtime.scene.ready" })) {
    throw "Lifecycle classifier did not index runtime.scene events."
}
if (Test-RuntimeSceneLifecycleEvent -Payload @{ component = "browser_page"; phase = "focus"; event_code = "browser.focus.changed" }) {
    throw "Lifecycle classifier indexes browser focus noise."
}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_focus_lifecycle_events_are_traceable(tmp_path):
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

function Get-LauncherFunctionText {
    param([string]$Name)

    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $Name
    }, $true)
    if ($null -eq $functionAst) {
        throw "$Name was not found."
    }
    return $functionAst.Extent.Text
}

$focusText = Get-LauncherFunctionText -Name "Focus-ManagedBrowserWindow"
foreach ($required in @(
    "launcher.browser.focus.succeeded",
    "launcher.browser.focus.failed",
    "window_not_found",
    "browser_pids",
    "show_window",
    "set_foreground",
    "app_activate"
)) {
    if ($focusText -notmatch [regex]::Escape($required)) {
        throw "Focus-ManagedBrowserWindow is missing trace field '$required'."
    }
}

$adoptText = Get-LauncherFunctionText -Name "Adopt-Or-FocusSession"
foreach ($required in @(
    "runtime.scene.focused",
    "runtime.scene.focus.failed",
    "Focus-ManagedBrowserWindow",
    "backendLaunchPid",
    "BackendLaunchPid `$backendLaunchPid"
)) {
    if ($adoptText -notmatch [regex]::Escape($required)) {
        throw "Adopt-Or-FocusSession is missing trace field '$required'."
    }
}

$startText = Get-LauncherFunctionText -Name "Start-ManagedSession"
foreach ($required in @(
    "runtime.scene.ready",
    "focus_requested",
    "Focus-ManagedBrowserWindow"
)) {
    if ($startText -notmatch [regex]::Escape($required)) {
        throw "Start-ManagedSession is missing trace field '$required'."
    }
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_redirected_background_process_runs_without_visible_shell_wrapper(tmp_path):
    stdout_path = tmp_path / "redirected.out.log"
    stderr_path = tmp_path / "redirected.err.log"
    powershell_exe = _powershell_exe()
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
    "ConvertTo-ProcessArgument",
    "ConvertTo-ProcessArgumentString",
    "Ensure-HiddenRedirectedProcessApi",
    "Start-RedirectedBackgroundProcess"
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

Set-Variable -Name projectDir -Value {json.dumps(str(tmp_path))} -Scope Script
$proc = Start-RedirectedBackgroundProcess `
    -CommandPath {json.dumps(powershell_exe)} `
    -ArgumentList @(
        "-NoProfile",
        "-Command",
        "[Console]::Out.WriteLine('stdout-ok'); [Console]::Error.WriteLine('stderr-ok'); Start-Sleep -Milliseconds 300"
    ) `
    -WorkingDirectory {json.dumps(str(tmp_path))} `
    -StdoutPath {json.dumps(str(stdout_path))} `
    -StderrPath {json.dumps(str(stderr_path))}
$proc.WaitForExit(10000) | Out-Null
if (-not $proc.HasExited) {{
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    throw "Redirected process did not exit."
}}
if ($proc.ProcessName -match "cmd") {{
    throw "Redirected process returned a cmd wrapper PID."
}}
$stdout = Get-Content -Raw -LiteralPath {json.dumps(str(stdout_path))}
$stderr = Get-Content -Raw -LiteralPath {json.dumps(str(stderr_path))}
if ($stdout -notmatch "stdout-ok") {{
    throw "Redirected stdout log was not written."
}}
if ($stderr -notmatch "stderr-ok") {{
    throw "Redirected stderr log was not written."
}}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_redirected_background_process_preserves_python_arguments(tmp_path):
    stdout_path = tmp_path / "python-redirected.out.log"
    stderr_path = tmp_path / "python-redirected.err.log"
    python_exe = str(Path(sys.executable))
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
    "ConvertTo-ProcessArgument",
    "ConvertTo-ProcessArgumentString",
    "Ensure-HiddenRedirectedProcessApi",
    "Start-RedirectedBackgroundProcess"
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

Set-Variable -Name projectDir -Value {json.dumps(str(tmp_path))} -Scope Script
$proc = Start-RedirectedBackgroundProcess `
    -CommandPath {json.dumps(python_exe)} `
    -ArgumentList @(
        "-c",
        "import sys; print('args-ok:' + '|'.join(sys.argv[1:]))",
        "alpha",
        "beta value"
    ) `
    -WorkingDirectory {json.dumps(str(tmp_path))} `
    -StdoutPath {json.dumps(str(stdout_path))} `
    -StderrPath {json.dumps(str(stderr_path))}
$proc.WaitForExit(10000) | Out-Null
if (-not $proc.HasExited) {{
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    throw "Redirected Python process did not exit."
}}
$stdout = Get-Content -Raw -LiteralPath {json.dumps(str(stdout_path))}
if ($stdout -notmatch "args-ok:alpha\\|beta value") {{
    throw "Redirected Python arguments were not preserved: $stdout"
}}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_desktop_entry_launcher_actions_are_no_window_and_monitor_is_skipped(tmp_path):
    result = _run_desktop_entry_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$DesktopEntryPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $DesktopEntryPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Desktop entry script parse failed: $($parseErrors[0].Message)"
}

$launcherActionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Invoke-HiddenLauncherAction"
}, $true)
if ($null -eq $launcherActionAst) {
    throw "Invoke-HiddenLauncherAction was not found."
}
$launcherActionText = $launcherActionAst.Extent.Text
if ($launcherActionText -match "Start-Process") {
    throw "Desktop entry still uses Start-Process for launcher actions."
}
if ($launcherActionText -notmatch 'CreateNoWindow\\s*=\\s*\\$true') {
    throw "Desktop entry launcher action does not force CreateNoWindow."
}
if ($launcherActionText -notmatch 'UseShellExecute\\s*=\\s*\\$false') {
    throw "Desktop entry launcher action does not avoid shell execution."
}
if ($launcherActionText -notmatch "RedirectStandardOutput" -or $launcherActionText -notmatch "RedirectStandardError") {
    throw "Desktop entry launcher action does not capture output."
}
if ($source -match 'Invoke-HiddenLauncherAction\\s+-LauncherAction\\s+"monitor"') {
    throw "Desktop entry still attaches the launcher monitor automatically."
}
if ($source -notmatch "desktop_entry.monitor.skipped") {
    throw "Desktop entry does not log skipped monitor behavior."
}
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
$script:dependencyCalls = 0
function Ensure-ProjectPythonDependencies {
    $script:dependencyCalls += 1
}
function Resolve-PythonRuntime {
    if ($script:dependencyCalls -le 0) {
        throw "Resolve-PythonRuntime was called before dependency repair."
    }
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
if ($script:dependencyCalls -ne 3) { throw "runtime manager client did not repair dependencies before each command." }
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_runtime_manager_client_failure_exits_launcher(tmp_path):
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

$scriptText = $ast.EndBlock.Extent.Text
    if ($scriptText -notmatch '\\$clientExitCode\\s*=\\s*Invoke-RuntimeManagerClient') {
        throw "Runtime-manager client action return code is not captured."
    }
    if ($scriptText -notmatch 'if\\s*\\(\\s*\\$clientExitCode\\s+-ne\\s+0\\s*\\)') {
        throw "Runtime-manager client non-zero return code is not checked."
    }
    if ($scriptText -notmatch 'exit\\s+\\$clientExitCode') {
        throw "Runtime-manager client non-zero return code is not propagated."
    }
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
    "Get-RuntimeSceneEffectiveStatus",
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
if ($index.display_name -notmatch "工作台启动" -or $index.display_name -notmatch "手动停止") {
    throw "display_name is not user-readable Chinese."
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
    "Get-RuntimeSceneEffectiveStatus",
    "Get-RuntimeSceneTriggerDisplayLabel",
    "Get-RuntimeScenePackageIndex",
    "Get-RuntimeScenePackageSummary",
    "Get-RuntimeSceneJsonlEventCount",
    "Get-RuntimeSceneSeverityCounts",
    "Get-RuntimeSceneEventSeverity",
    "Get-RuntimeSceneChildFileCount",
    "Get-HashtableStringValue",
    "ConvertTo-PlainHashtable",
    "Write-RuntimeSceneJsonFile",
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
$script:runtimeSceneWriteMaxAttempts = 2
$script:runtimeSceneWriteRetryDelayMilliseconds = 1
function Ensure-CurrentRuntimeSceneSubdirs {{
    New-Item -ItemType Directory -Path $script:currentRuntimeSceneDir -Force | Out-Null
}}
function Get-CurrentRuntimeSceneFilePath {{
    param([string]$RelativePath)
    return Join-Path $script:currentRuntimeSceneDir $RelativePath
}}
New-Item -ItemType Directory -Path (Join-Path $script:currentRuntimeSceneDir "agent/supervised_runs") -Force | Out-Null
Set-Content -Path (Join-Path $script:currentRuntimeSceneDir "agent/supervised_runs/run-a.jsonl") -Value '{{}}' -Encoding UTF8
New-Item -ItemType Directory -Path (Join-Path $script:currentRuntimeSceneDir "agent/self_evolution_runs") -Force | Out-Null
Set-Content -Path (Join-Path $script:currentRuntimeSceneDir "agent/self_evolution_runs/run-b.jsonl") -Value '{{}}' -Encoding UTF8
Set-Content -Path (Join-Path $script:currentRuntimeSceneDir "timeline.jsonl") -Value @(
    '{{"level":"info","outcome":"observed","fields":{{}}}}',
    '{{"level":"warning","outcome":"degraded","fields":{{}}}}',
    '{{"level":"warning","outcome":"retrying","fields":{{"errorType":"network_error","error":"temporary transport failure"}}}}',
    '{{"level":"error","outcome":"failed","fields":{{"errorType":"RuntimeError"}}}}'
) -Encoding UTF8
Set-Content -Path (Join-Path $script:currentRuntimeSceneDir "lifecycle.jsonl") -Value @(
    '{{"phase":"startup","level":"info","outcome":"observed","fields":{{}}}}',
    '{{"phase":"shutdown","level":"info","outcome":"succeeded","fields":{{}}}}'
) -Encoding UTF8

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
$summary = Get-Content -LiteralPath (Join-Path $script:currentRuntimeSceneDir "summary.json") -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.package.package_index_path -ne "package_index.json") {{
    throw "manifest package does not point to package_index.json."
}}
if ($manifest.package.summary_path -ne "summary.json") {{
    throw "manifest package does not point to summary.json."
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
if ($summary.package_id -ne "scene-a") {{
    throw "summary package_id did not round-trip."
}}
if ($summary.primary_files.package_index -ne "package_index.json") {{
    throw "summary does not point to package_index.json."
}}
if ($summary.primary_files.timeline -ne "timeline.jsonl" -or $summary.primary_files.lifecycle -ne "lifecycle.jsonl") {{
    throw "summary does not point to lifecycle entry files."
}}
if ($summary.primary_files.startup -ne "raw/desktop-entry.log") {{
    throw "summary does not point to startup entry file."
}}
if ($summary.sections.startup.path -ne "raw/desktop-entry.log") {{
    throw "summary missing startup section."
}}
if ($summary.sections.startup.launcher_path -ne "raw/launcher-control.log") {{
    throw "summary startup section does not include launcher control log."
}}
if ($summary.sections.supervised_evolution.path -ne "agent/supervised_runs") {{
    throw "summary missing supervised evolution section."
}}
if ($summary.sections.supervised_evolution.worktree_path -ne "agent/supervised_worktree_runs") {{
    throw "summary missing supervised worktree evolution section."
}}
if ($summary.sections.self_evolution.path -ne "agent/self_evolution_runs") {{
    throw "summary missing self evolution section."
}}
if ($summary.event_counts.supervised_evolution_logs -ne 1) {{
    throw "summary supervised evolution log count is wrong."
}}
if ($summary.event_counts.self_evolution_logs -ne 1) {{
    throw "summary self evolution log count is wrong."
}}
if ($summary.event_counts.timeline_events -ne 4) {{
    throw "summary timeline event count should count jsonl rows."
}}
if ($summary.event_counts.lifecycle_events -ne 2) {{
    throw "summary lifecycle event count should count jsonl rows."
}}
if ($summary.event_counts.errors -ne 1) {{
    throw "summary error count should reflect timeline event severity."
}}
if ($summary.event_counts.warnings -ne 2) {{
    throw "summary warning count should preserve explicit warning level before error markers."
}}
if ($summary.diagnostic_entrypoint.recommended_order[0] -ne "summary.json") {{
    throw "summary diagnostic order does not start from summary.json."
}}
if ($summary.diagnostic_entrypoint.recommended_order[2] -ne "raw/desktop-entry-vbs.log") {{
    throw "summary diagnostic order should inspect startup logs before timeline."
}}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_runtime_scene_manifest_treats_active_unknown_package_as_running(tmp_path):
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
    "Get-RuntimeSceneEffectiveStatus",
    "Get-RuntimeSceneTriggerDisplayLabel",
    "Get-RuntimeScenePackageIndex",
    "Get-RuntimeScenePackageSummary",
    "Get-RuntimeSceneJsonlEventCount",
    "Get-RuntimeSceneSeverityCounts",
    "Get-RuntimeSceneEventSeverity",
    "Get-RuntimeSceneChildFileCount",
    "Get-HashtableStringValue",
    "ConvertTo-PlainHashtable",
    "Write-RuntimeSceneJsonFile",
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
$script:runtimeSceneWriteMaxAttempts = 2
$script:runtimeSceneWriteRetryDelayMilliseconds = 1
function Ensure-CurrentRuntimeSceneSubdirs {{
    New-Item -ItemType Directory -Path $script:currentRuntimeSceneDir -Force | Out-Null
}}
function Get-CurrentRuntimeSceneFilePath {{
    param([string]$RelativePath)
    return Join-Path $script:currentRuntimeSceneDir $RelativePath
}}

Save-RuntimeSceneManifest -Manifest @{{
    schema_version = 2
    runtime_scene_id = "scene-active"
    started_at = "2026-05-24T12:00:01Z"
    ended_at = ""
    status = "unknown"
    trigger = "internal-start"
}}

$manifest = Get-Content -LiteralPath (Join-Path $script:currentRuntimeSceneDir "manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$packageIndex = Get-Content -LiteralPath (Join-Path $script:currentRuntimeSceneDir "package_index.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$summary = Get-Content -LiteralPath (Join-Path $script:currentRuntimeSceneDir "summary.json") -Raw -Encoding UTF8 | ConvertFrom-Json
if ($packageIndex.index_key -notmatch "_running$") {{
    throw "active unknown package index should end with running."
}}
if ($packageIndex.display_name -notmatch "运行中") {{
    throw "active unknown package display name should be user-readable running."
}}
if ($summary.status -ne "running") {{
    throw "active unknown package summary should report running."
}}
if ($manifest.package.index_key -ne $packageIndex.index_key) {{
    throw "manifest package index should match package_index."
}}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_runtime_scene_json_write_is_nonfatal_when_manifest_locked(tmp_path):
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
        $node.Name -eq "Write-RuntimeSceneJsonFile"
}, $true)
if ($null -eq $functionAst) {
    throw "Write-RuntimeSceneJsonFile was not found."
}

. ([scriptblock]::Create($functionAst.Extent.Text))

$script:runtimeSceneWriteMaxAttempts = 1
$script:runtimeSceneWriteRetryDelayMilliseconds = 1
$script:logEvents = @()
function Write-LauncherControlLog {
    param(
        [string]$Event,
        [string]$Message,
        [string]$Level = "info",
        [hashtable]$Fields = @{}
    )
    $script:logEvents += ,@{
        event = $Event
        message = $Message
        level = $Level
        fields = $Fields
    }
}

$targetDir = Join-Path ([System.IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
$manifestPath = Join-Path $targetDir "manifest.json"
[System.IO.File]::WriteAllText($manifestPath, "{}")
$lock = [System.IO.File]::Open($manifestPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
try {
    $ok = Write-RuntimeSceneJsonFile -Path $manifestPath -Value @{ status = "running" } -Depth 4
} finally {
    $lock.Dispose()
}

if ($ok) {
    throw "Runtime scene JSON write unexpectedly succeeded while the target file was locked."
}
if ($script:logEvents.Count -ne 1) {
    throw "Runtime scene JSON write failure was not logged exactly once."
}
if ($script:logEvents[0].event -ne "launcher.runtime_scene.write.failed") {
    throw "Unexpected log event: $($script:logEvents[0].event)"
}
if ($script:logEvents[0].level -ne "warning") {
    throw "Runtime scene JSON write failure should be a warning, not a fatal error."
}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_runtime_scene_event_append_is_nonfatal_when_lifecycle_locked(tmp_path):
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
    "Write-RuntimeSceneTextLine",
    "Test-RuntimeSceneLifecycleEvent",
    "Write-RuntimeSceneEvent"
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

$script:currentRuntimeSceneId = "scene-locked"
$script:currentRuntimeSceneDir = {json.dumps(str(scene_dir))}
$script:sceneEventSequence = @{{}}
$script:runtimeSceneWriteMaxAttempts = 1
$script:runtimeSceneWriteRetryDelayMilliseconds = 1
$sceneSchemaVersion = 2
$script:logEvents = @()
function Ensure-CurrentRuntimeSceneSubdirs {{
    New-Item -ItemType Directory -Path $script:currentRuntimeSceneDir -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $script:currentRuntimeSceneDir "events") -Force | Out-Null
}}
function Get-CurrentRuntimeSceneFilePath {{
    param([string]$RelativePath)
    return Join-Path $script:currentRuntimeSceneDir $RelativePath
}}
function Write-LauncherControlLog {{
    param(
        [string]$Event,
        [string]$Message,
        [string]$Level = "info",
        [hashtable]$Fields = @{{}}
    )
    $script:logEvents += ,@{{
        event = $Event
        message = $Message
        level = $Level
        fields = $Fields
    }}
}}

Ensure-CurrentRuntimeSceneSubdirs
$lifecyclePath = Join-Path $script:currentRuntimeSceneDir "lifecycle.jsonl"
[System.IO.File]::WriteAllText($lifecyclePath, "")
$lock = [System.IO.File]::Open($lifecyclePath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
try {{
    Write-RuntimeSceneEvent `
        -Component "launcher" `
        -Phase "session" `
        -EventCode "runtime.scene.ready" `
        -Message "ready" `
        -Outcome "succeeded"
}} finally {{
    $lock.Dispose()
}}

$eventPath = Join-Path $script:currentRuntimeSceneDir "events/launcher.jsonl"
$timelinePath = Join-Path $script:currentRuntimeSceneDir "timeline.jsonl"
if (-not (Test-Path -LiteralPath $eventPath)) {{
    throw "Component event file was not written."
}}
if (-not (Test-Path -LiteralPath $timelinePath)) {{
    throw "Timeline file was not written."
}}
if ($script:logEvents.Count -ne 1) {{
    throw "Expected exactly one append failure log, got $($script:logEvents.Count)."
}}
if ($script:logEvents[0].event -ne "launcher.runtime_scene.append.failed") {{
    throw "Unexpected log event: $($script:logEvents[0].event)"
}}
if ($script:logEvents[0].level -ne "warning") {{
    throw "Runtime scene append failure should be a warning."
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
    BackendHealthy = $false
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
    controlLogBackendHealthy = $script:controlFields[0].backend_healthy
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
    assert payload["controlLogBackendHealthy"] is False
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


def test_launcher_backend_candidates_include_tracked_launch_and_listener_pids(tmp_path):
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
    "ConvertTo-LauncherComparableText",
    "Test-CommandLineMentionsWorkbenchScript",
    "Test-CommandLineLooksLikeManagedBackend",
    "Get-ManagedBackendCandidatePids"
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

$script:port = 8000
$script:healthy = $true
function Get-State {
    return [pscustomobject]@{
        backendPid = 6544
        backendLaunchPid = 6544
        port = 8000
    }
}
function Test-ProcessAlive {
    param([int]$ProcessId)
    return $ProcessId -eq 6544
}
function Get-ListeningPid {
    param([int]$Port)
    if ($Port -eq 8000) {
        return 14916
    }
    return $null
}
function Get-CimInstance {
    param([string]$ClassName, [string]$Filter, [string]$ErrorAction)
    if ($Filter -match "ProcessId = 14916") {
        return [pscustomobject]@{
            ProcessId = 14916
            CommandLine = "`"C:\\Python312\\python.exe`" scripts/web_workbench.py --host 127.0.0.1 --port 8000 --no-browser --managed-by-launcher"
        }
    }
    return @()
}
function Test-WebHealthy { return [bool]$script:healthy }

$pids = @(Get-ManagedBackendCandidatePids)
if (($pids -join ",") -ne "6544,14916") {
    throw "Expected tracked launch and listener PIDs, got $($pids -join ',')."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_backend_candidates_do_not_adopt_unmarked_manual_listener(tmp_path):
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
    "ConvertTo-LauncherComparableText",
    "Test-CommandLineMentionsWorkbenchScript",
    "Test-CommandLineLooksLikeManagedBackend",
    "Get-ManagedBackendCandidatePids"
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

$script:port = 8000
function Get-State {
    return [pscustomobject]@{
        backendPid = 0
        backendLaunchPid = 0
        port = 8000
    }
}
function Test-ProcessAlive { param([int]$ProcessId) return $false }
function Get-ListeningPid {
    param([int]$Port)
    if ($Port -eq 8000) {
        return 14916
    }
    return $null
}
function Get-CimInstance {
    param([string]$ClassName, [string]$Filter, [string]$ErrorAction)
    if ($Filter -match "ProcessId = 14916") {
        return [pscustomobject]@{
            ProcessId = 14916
            CommandLine = "`"C:\\Python312\\python.exe`" scripts/web_workbench.py --host 127.0.0.1 --port 8000 --no-browser"
        }
    }
    return @()
}
function Test-WebHealthy { return $true }

$pids = @(Get-ManagedBackendCandidatePids)
if ($pids.Count -ne 0) {
    throw "Expected unmarked manual backend listener to stay unadopted, got $($pids -join ',')."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_browser_candidates_include_tracked_launch_window_and_profile_pids(tmp_path):
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
        $node.Name -eq "Get-ManagedBrowserCandidatePids"
}, $true)
if ($null -eq $functionAst) {
    throw "Get-ManagedBrowserCandidatePids was not found."
}
. ([scriptblock]::Create($functionAst.Extent.Text))

$script:browserProfileDir = "C:\\Users\\17533\\Desktop\\Vibelution\\.runtime\\launcher\\edge-app-profile"
function Ensure-Directories { }
function Get-State {
    return [pscustomobject]@{
        browserWindowPid = 40736
        browserLaunchPid = 40736
    }
}
function Test-ProcessAlive {
    param([int]$ProcessId)
    return $ProcessId -in @(40736, 36192)
}
function Get-CimInstance {
    param([string]$ClassName, [string]$Filter, [string]$ErrorAction)
    return @(
        [pscustomobject]@{
            ProcessId = 40736
            Name = "msedge.exe"
            CommandLine = "`"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe`" --user-data-dir=C:\\Users\\17533\\Desktop\\Vibelution\\.runtime\\launcher\\edge-app-profile --app=http://127.0.0.1:8000"
        },
        [pscustomobject]@{
            ProcessId = 36192
            Name = "msedge.exe"
            CommandLine = "`"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe`" --type=renderer --user-data-dir=C:\\Users\\17533\\Desktop\\Vibelution\\.runtime\\launcher\\edge-app-profile"
        }
    )
}

$pids = @(Get-ManagedBrowserCandidatePids)
if (($pids -join ",") -ne "36192,40736") {
    throw "Expected tracked browser and profile PIDs, got $($pids -join ',')."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_stop_backend_kills_remaining_managed_port_owner(tmp_path):
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

foreach ($functionName in @(
    "ConvertTo-LauncherComparableText",
    "Test-NormalizedTextContainsPathSegment",
    "Test-TextReferencesProjectPath",
    "Test-CommandLineMentionsWorkbenchScript",
    "Test-CommandLineUsesRelativeWorkbenchScript",
    "Get-LauncherProcessPropertyValue",
    "Test-CommandLineLooksLikeRepoWorkbenchBackend",
    "Test-ProcessLooksLikeRepoWorkbenchBackend",
    "Test-CommandLineLooksLikeManagedBackend",
    "Stop-ManagedBackendProcesses"
)) {
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

$script:port = 8000
$script:projectDir = "C:\\Users\\17533\\Desktop\\Vibelution"
$script:stopCalls = @()
$script:listenerCalls = 0
function Get-ManagedBackendCandidatePids { return @(6544) }
function Stop-ProcessesById {
    param([int[]]$ProcessIds)
    $script:stopCalls += ,@($ProcessIds)
}
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
}
function Get-State {
    return [pscustomobject]@{
        port = 8000
        backendPid = 14916
        backendLaunchPid = 6544
    }
}
function Get-ListeningPid {
    param([int]$Port)
    $script:listenerCalls += 1
    if ($script:listenerCalls -eq 1) {
        return 14916
    }
    return $null
}
function Get-CimInstance {
    param([string]$ClassName, [string]$Filter, [string]$ErrorAction)
    if ($Filter -match "ProcessId = 14916") {
        return [pscustomobject]@{
            ProcessId = 14916
            CommandLine = "`"C:\\Python312\\python.exe`" scripts/web_workbench.py --host 127.0.0.1 --port 8000 --no-browser --managed-by-launcher"
        }
    }
    return @()
}
function Test-WebHealthy { return $true }

Stop-ManagedBackendProcesses

$payload = @{
    calls = @($script:stopCalls | ForEach-Object { @($_) })
} | ConvertTo-Json -Depth 8 -Compress
Write-Output $payload
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["calls"] == [6544, 14916]


def test_launcher_stop_browser_processes_retry_until_profile_processes_exit(tmp_path):
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
        $node.Name -eq "Stop-ManagedBrowserProcesses"
}, $true)
if ($null -eq $functionAst) {
    throw "Stop-ManagedBrowserProcesses was not found."
}
. ([scriptblock]::Create($functionAst.Extent.Text))

$script:browserPids = @(40736, 36192)
$script:stopCalls = @()
$script:closeCalls = 0
$script:logEvents = @()

$windowProcess = [pscustomobject]@{
    Id = 40736
    MainWindowHandle = 2821910
}
$windowProcess | Add-Member -MemberType ScriptMethod -Name CloseMainWindow -Value {
    $script:closeCalls += 1
    return $true
}

function Get-ManagedBrowserWindowProcesses {
    return @($windowProcess)
}
function Get-ManagedBrowserPids {
    return @($script:browserPids)
}
function Stop-ProcessesById {
    param([int[]]$ProcessIds)
    $script:stopCalls += ,(($ProcessIds -join ","))
    if ($script:stopCalls.Count -eq 1) {
        $script:browserPids = @($script:browserPids | Where-Object { $_ -ne 40736 })
    } else {
        $script:browserPids = @()
    }
}
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:logEvents += $Event
}
function Start-Sleep { param([int]$Milliseconds, [int]$Seconds) }

Stop-ManagedBrowserProcesses

$payload = @{
    closeCalls = $script:closeCalls
    stopCalls = @($script:stopCalls)
    logEvents = @($script:logEvents)
    remaining = @($script:browserPids)
} | ConvertTo-Json -Depth 8 -Compress
Write-Output $payload
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["closeCalls"] == 1
    assert payload["stopCalls"] == ["40736,36192", "36192"]
    assert "launcher.browser.stop.retry" in payload["logEvents"]
    assert "launcher.browser.stop.incomplete" not in payload["logEvents"]
    assert payload["remaining"] == []


def test_launcher_stop_session_closes_browser_when_backend_stop_is_unconfirmed(tmp_path):
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
        $node.Name -eq "Stop-ManagedSession"
}, $true)
if ($null -eq $functionAst) {
    throw "Stop-ManagedSession was not found."
}
. ([scriptblock]::Create($functionAst.Extent.Text))

$script:port = 8000
$script:selfProcessId = 123
$script:currentRuntimeSceneId = ""
$script:browserStopCalls = 0
$script:browserWaitCalls = 0
$script:removedState = $false
$script:notes = @()
$script:controlEvents = @()

function Get-SessionSnapshot {
    return [pscustomobject]@{
        BackendPids = @(6544)
        BackendPid = 6544
        BrowserPids = @(40736)
        BrowserWindowCount = 1
        State = [pscustomobject]@{
            supervisorPid = 7777
            runtimeSceneId = ""
            runtimeSceneDir = ""
        }
    }
}
function Stop-ManagedBackendProcesses {
    return [pscustomobject]@{
        CandidatePids = @(6544)
        RemainingPortPid = 14916
        RemainingLooksManaged = $false
        RemainingHealthy = $false
        PortOwnerStopped = $false
    }
}
function Wait-ForPortClosed {
    param([int]$Port)
    return $false
}
function Stop-ProcessesById { param([int[]]$ProcessIds) }
function Stop-ManagedBrowserProcesses {
    $script:browserStopCalls += 1
}
function Wait-ForBrowserStopped {
    param([int]$TimeoutSeconds)
    $script:browserWaitCalls += 1
    return $true
}
function Get-ManagedSessionClosureSnapshot {
    return [pscustomobject]@{
        BackendStopped = $false
        BrowserStopped = $true
        ManagerClosed = $false
        BackendPids = @(6544)
        BackendHealthy = $false
        BrowserPids = @()
        BrowserWindowCount = 0
        PortOwnerPid = 14916
        DesiredState = "closed"
        ObservedState = "open"
        Phase = "closing"
        FailureMessage = ""
    }
}
function Test-ManagedSessionClosureSucceeded {
    param([pscustomobject]$Closure, [bool]$RequireManagerClosed = $true)
    return $false
}
function Write-ManagedSessionClosureRecord {
    param([pscustomobject]$Closure, [string]$Reason, [string]$Source, [bool]$Success)
}
function Remove-State { $script:removedState = $true }
function Get-ListeningPid { param([int]$Port) return 14916 }
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:controlEvents += ,@{ event = $Event; level = $Level; fields = $Fields }
}
function Write-Note {
    param([string]$Message)
    $script:notes += $Message
}

$errorMessage = ""
try {
    Stop-ManagedSession -Reason "web_close_button"
} catch {
    $errorMessage = $_.Exception.Message
}

$payload = @{
    browserStopCalls = $script:browserStopCalls
    browserWaitCalls = $script:browserWaitCalls
    removedState = $script:removedState
    notes = @($script:notes)
    controlEvents = @($script:controlEvents)
    errorMessage = $errorMessage
} | ConvertTo-Json -Depth 10 -Compress
Write-Output $payload
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["browserStopCalls"] == 1
    assert payload["browserWaitCalls"] == 1
    assert payload["removedState"] is False
    assert "backend did not stop" in payload["errorMessage"]
    assert "browser did not stop" not in payload["errorMessage"]
    assert "launcher.browser.stop.with_backend_unconfirmed" in [item["event"] for item in payload["controlEvents"]]
    assert any("browser was closed" in note for note in payload["notes"])


def test_launcher_stop_backend_logs_traceable_candidates_and_port_owner(tmp_path):
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

foreach ($functionName in @(
    "ConvertTo-LauncherComparableText",
    "Test-NormalizedTextContainsPathSegment",
    "Test-TextReferencesProjectPath",
    "Test-CommandLineMentionsWorkbenchScript",
    "Test-CommandLineUsesRelativeWorkbenchScript",
    "Get-LauncherProcessPropertyValue",
    "Test-CommandLineLooksLikeRepoWorkbenchBackend",
    "Test-ProcessLooksLikeRepoWorkbenchBackend",
    "Test-CommandLineLooksLikeManagedBackend",
    "Stop-ManagedBackendProcesses"
)) {
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

$script:port = 8000
$script:projectDir = "C:\\Users\\17533\\Desktop\\Vibelution"
$script:controlEvents = @()
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:controlEvents += ,@{ event = $Event; level = $Level; fields = $Fields }
}
function Get-ManagedBackendCandidatePids { return @(6544) }
function Stop-ProcessesById { param([int[]]$ProcessIds) }
function Get-State { return [pscustomobject]@{ port = 8000 } }
function Get-ListeningPid { param([int]$Port) return 14916 }
function Get-CimInstance {
    param([string]$ClassName, [string]$Filter, [string]$ErrorAction)
    return [pscustomobject]@{
        ProcessId = 14916
        CommandLine = "`"C:\\Python312\\python.exe`" scripts/web_workbench.py --host 127.0.0.1 --port 8000 --no-browser --managed-by-launcher"
    }
}
function Test-WebHealthy { return $true }

$trace = Stop-ManagedBackendProcesses
$payload = @{
    trace = $trace
    events = @($script:controlEvents)
} | ConvertTo-Json -Depth 8 -Compress
Write-Output $payload
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["trace"]["CandidatePids"] == [6544]
    assert payload["trace"]["RemainingPortPid"] == 14916
    assert payload["trace"]["RemainingLooksManaged"] is True
    assert payload["trace"]["RemainingHealthy"] is True
    assert [item["event"] for item in payload["events"]] == [
        "launcher.backend.stop.requested",
        "launcher.backend.stop.port_owner_detected",
    ]
    assert payload["events"][1]["level"] == "warning"


def test_launcher_stop_backend_cleans_repo_local_unmarked_residual_port_owner(tmp_path):
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

foreach ($functionName in @(
    "ConvertTo-LauncherComparableText",
    "Test-NormalizedTextContainsPathSegment",
    "Test-TextReferencesProjectPath",
    "Test-CommandLineMentionsWorkbenchScript",
    "Test-CommandLineUsesRelativeWorkbenchScript",
    "Get-LauncherProcessPropertyValue",
    "Test-CommandLineLooksLikeRepoWorkbenchBackend",
    "Test-ProcessLooksLikeRepoWorkbenchBackend",
    "Test-CommandLineLooksLikeManagedBackend",
    "Stop-ManagedBackendProcesses"
)) {
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

$script:port = 8000
$script:projectDir = "C:\\Users\\17533\\Desktop\\Vibelution"
$script:controlEvents = @()
$script:stopCalls = @()
$script:listenerCalls = 0
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:controlEvents += ,@{ event = $Event; level = $Level; fields = $Fields }
}
function Get-ManagedBackendCandidatePids { return @() }
function Stop-ProcessesById {
    param([int[]]$ProcessIds)
    $script:stopCalls += ,@($ProcessIds)
}
function Get-State { return [pscustomobject]@{ port = 8000 } }
function Get-ListeningPid {
    param([int]$Port)
    $script:listenerCalls += 1
    if ($script:listenerCalls -eq 1) {
        return 31832
    }
    return $null
}
function Get-CimInstance {
    param([string]$ClassName, [string]$Filter, [string]$ErrorAction)
    if ($Filter -match "ProcessId = 31832") {
        return [pscustomobject]@{
            ProcessId = 31832
            ParentProcessId = 50404
            CommandLine = "`"C:\\Users\\17533\\AppData\\Local\\Programs\\Python\\Python312\\python.exe`" scripts\\web_workbench.py --no-browser"
            ExecutablePath = "C:\\Users\\17533\\AppData\\Local\\Programs\\Python\\Python312\\python.exe"
        }
    }
    if ($Filter -match "ProcessId = 50404") {
        return [pscustomobject]@{
            ProcessId = 50404
            ParentProcessId = 1
            CommandLine = "`"C:\\Users\\17533\\Desktop\\Vibelution\\.venv\\Scripts\\python.exe`" scripts\\web_workbench.py --no-browser"
            ExecutablePath = "C:\\Users\\17533\\Desktop\\Vibelution\\.venv\\Scripts\\python.exe"
        }
    }
    return @()
}
function Test-WebHealthy { return $true }
function Invoke-RepoResidualWorkbenchCleanup {
    param([int[]]$ExcludePids = @())
    return [pscustomobject]@{
        supported = $true
        requested = @()
        terminated = @()
        remaining = @()
    }
}

$trace = Stop-ManagedBackendProcesses
$payload = @{
    trace = $trace
    stopCalls = @($script:stopCalls | ForEach-Object { @($_) })
    events = @($script:controlEvents)
} | ConvertTo-Json -Depth 10 -Compress
Write-Output $payload
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["trace"]["RemainingLooksManaged"] is False
    assert payload["trace"]["RemainingLooksRepoWorkbench"] is True
    assert payload["trace"]["PortOwnerStopped"] is True
    assert payload["trace"]["PortOwnerCleanupReason"] == "repo_workbench_ancestor"
    assert payload["stopCalls"] == [31832]
    assert payload["events"][1]["fields"]["remaining_looks_repo_workbench"] is True
    assert payload["events"][1]["fields"]["port_owner_cleanup_reason"] == "repo_workbench_ancestor"


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


def test_launcher_supervisor_preserves_requested_shutdown_reason_on_backend_exit(tmp_path):
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

foreach ($functionName in @(
    "ConvertTo-PlainHashtable",
    "Get-ObjectPropertyValue",
    "Get-RuntimeManagerWorkbenchReason",
    "Run-SupervisorLoop"
)) {
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

$script:getStateCalls = 0
$script:stops = @()
$script:notes = @()
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
        Alive = $false
        Healthy = $false
        TrackedPid = $TrackedPid
        TrackedPidAlive = $false
        CandidatePids = @()
    }
}
function Get-RuntimeManagerWorkbench {
    return [pscustomobject]@{
        desiredState = "closed"
        observedState = "open"
        phase = "closing"
        lastReason = "web_close_button"
        lastSource = "web_ui"
    }
}
function Get-ManagedBrowserWindowProcesses {
    return @([pscustomobject]@{ Id = 3333; MainWindowHandle = 1 })
}
function Stop-ManagedSession {
    param([string]$Reason = "")
    $script:stops += $Reason
}
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
}
function Write-Note {
    param([string]$Message)
    $script:notes += $Message
}
function Start-Sleep { param([int]$Milliseconds, [int]$Seconds) }

Run-SupervisorLoop -ManagedSessionId "session-1"

$payload = @{
    stops = @($script:stops)
    notes = @($script:notes)
    getStateCalls = $script:getStateCalls
} | ConvertTo-Json -Depth 8 -Compress
Write-Output $payload
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["stops"] == ["web_close_button"]
    assert "backend exited unexpectedly" not in json.dumps(payload, ensure_ascii=False)
    assert payload["getStateCalls"] == 1


def test_desktop_entry_maps_open_to_start_without_monitor(tmp_path):
    calls = _run_desktop_entry_with_fake_launcher(tmp_path, action="open")

    assert calls == [
        {
            "action": "start",
            "argv": [],
            "noBrowser": False,
            "pythonExe": str(tmp_path / "project" / ".venv" / "Scripts" / "python.exe"),
        }
    ]


def test_desktop_entry_failure_is_logged_without_blocking_popup(tmp_path):
    project_dir = tmp_path / "project"
    scripts_dir = project_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    venv_scripts_dir = project_dir / ".venv" / "Scripts"
    venv_scripts_dir.mkdir(parents=True)
    (venv_scripts_dir / "python.exe").write_text("console python", encoding="utf-8")
    (venv_scripts_dir / "python.exe").write_text("console python", encoding="utf-8")
    shutil.copyfile(DESKTOP_ENTRY_SCRIPT, scripts_dir / "vibelution_desktop_entry.ps1")
    (scripts_dir / "vibelution_launcher.ps1").write_text(
        """
param(
    [string]$Action = "",
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
throw "synthetic launcher failure"
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
        "open",
    ]
    env = os.environ.copy()
    env["VIBELUTION_DESKTOP_ENTRY_SUPPRESS_FEEDBACK"] = "1"
    result = subprocess.run(command, capture_output=True, text=True, cwd=project_dir, env=env, check=False, timeout=30)

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == ""
    log_path = project_dir / ".runtime" / "launcher" / "desktop-entry.log"
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    assert [event["event"] for event in events[-3:]] == [
        "desktop_entry.failed",
        "desktop_entry.failure.notice.requested",
        "desktop_entry.feedback.suppressed",
    ]
    assert "synthetic launcher failure" in events[-2]["fields"]["error"]


def test_desktop_entry_syncs_logs_from_active_runtime_scene_sidecar(tmp_path):
    scene_dir = tmp_path / "scene"
    launcher_dir = tmp_path / "launcher"
    result = _run_desktop_entry_ast_harness(
        tmp_path,
        f"""
param(
    [Parameter(Mandatory = $true)]
    [string]$DesktopEntryPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $DesktopEntryPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {{
    throw "Desktop entry script parse failed: $($parseErrors[0].Message)"
}}

foreach ($functionName in @(
    "Sync-DesktopEntryLogsIntoRuntimeScene",
    "Get-DesktopEntryRuntimeSceneDir",
    "Get-JsonPayloadField",
    "Sync-DesktopEntryLogFile"
)) {{
    $functionAst = $ast.Find({{
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }}, $true)
    if ($null -eq $functionAst) {{
        throw "$functionName was not found."
    }}
    . ([scriptblock]::Create($functionAst.Extent.Text))
}}

$launcherDir = {json.dumps(str(launcher_dir))}
$entryLogPath = Join-Path $launcherDir "desktop-entry.log"
$script:desktopEntryRunId = "entry-run"
$env:VIBELUTION_DESKTOP_ENTRY_VBS_RUN_ID = "vbs-run"
New-Item -ItemType Directory -Path $launcherDir -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path {json.dumps(str(scene_dir))} "raw") -Force | Out-Null
@{{
    runtimeSceneId = "scene-a"
    runtimeSceneDir = {json.dumps(str(scene_dir))}
}} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $launcherDir "active-runtime-scene.json") -Encoding utf8

Set-Content -LiteralPath $entryLogPath -Encoding utf8 -Value @(
    '{{"event":"desktop_entry.started","fields":{{"run_id":"entry-run"}}}}',
    '{{"event":"desktop_entry.started","fields":{{"run_id":"other-run"}}}}'
)
Set-Content -LiteralPath (Join-Path $launcherDir "desktop-entry-vbs.log") -Encoding utf8 -Value @(
    '{{"event":"desktop_entry_vbs.started","details":"run_id=vbs-run action=start"}}',
    '{{"event":"desktop_entry_vbs.started","details":"run_id=other-vbs action=start"}}'
)

Sync-DesktopEntryLogsIntoRuntimeScene

$entryTarget = Get-Content -LiteralPath (Join-Path {json.dumps(str(scene_dir))} "raw\\desktop-entry.log") -Raw -Encoding utf8
$vbsTarget = Get-Content -LiteralPath (Join-Path {json.dumps(str(scene_dir))} "raw\\desktop-entry-vbs.log") -Raw -Encoding utf8
if ($entryTarget -notmatch "entry-run" -or $entryTarget -match "other-run") {{
    throw "Desktop entry log was not filtered by run id through the sidecar scene reference."
}}
if ($vbsTarget -notmatch "vbs-run" -or $vbsTarget -match "other-vbs") {{
    throw "Desktop entry VBS log was not filtered by VBS run id through the sidecar scene reference."
}}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_desktop_entry_success_feedback_is_quiet_by_default(tmp_path):
    result = _run_desktop_entry_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$DesktopEntryPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $DesktopEntryPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Desktop entry script parse failed: $($parseErrors[0].Message)"
}

foreach ($functionName in @("Show-DesktopEntryFeedback", "Test-DesktopEntryFeedbackSuppressed", "Test-DesktopEntryFeedbackEnabled")) {
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

$script:feedbackEvents = @()
function Write-DesktopEntryLog {
    param(
        [string]$Event,
        [string]$Message,
        [string]$Level = "info",
        [hashtable]$Fields = @{}
    )
    $script:feedbackEvents += ,@{ event = $Event; fields = $Fields }
}

$env:VIBELUTION_DESKTOP_ENTRY_SUPPRESS_FEEDBACK = ""
$env:VIBELUTION_DESKTOP_ENTRY_SHOW_FEEDBACK = ""
Show-DesktopEntryFeedback -Title "title" -Message "message" -Seconds 1 -Kind "info"
if ($script:feedbackEvents.Count -ne 1 -or $script:feedbackEvents[0].event -ne "desktop_entry.feedback.suppressed") {
    throw "Success feedback should be quiet by default."
}
if ($script:feedbackEvents[0].fields.reason -ne "default_quiet") {
    throw "Default quiet feedback should log reason=default_quiet."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_desktop_entry_has_nonblocking_start_gate(tmp_path):
    result = _run_desktop_entry_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$DesktopEntryPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $DesktopEntryPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Desktop entry script parse failed: $($parseErrors[0].Message)"
}

foreach ($functionName in @("Enter-DesktopEntryStartGate", "Exit-DesktopEntryStartGate", "Test-DesktopEntryStartAction", "Show-DesktopEntryFeedback", "Test-DesktopEntryFeedbackSuppressed", "Test-DesktopEntryFeedbackEnabled")) {
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

$gateAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Enter-DesktopEntryStartGate"
}, $true)
$gateText = $gateAst.Extent.Text
if ($gateText -notmatch "WaitOne\\(0\\)") {
    throw "Start gate should use nonblocking mutex acquisition."
}
if ($gateText -notmatch "desktop_entry.start.skipped_in_progress") {
    throw "Start gate should log duplicate start suppression."
}
if ($gateText -notmatch "Show-DesktopEntryFeedback") {
    throw "Start gate should request visible feedback when a duplicate start is skipped."
}
if ($gateText -notmatch 'return\\s+\\$false') {
    throw "Start gate should skip duplicate starts."
}

if (-not (Test-DesktopEntryStartAction -LauncherAction "start")) {
    throw "start should be gated."
}
if (Test-DesktopEntryStartAction -LauncherAction "stop") {
    throw "stop should not be gated."
}
if (Test-DesktopEntryStartAction -LauncherAction "status") {
    throw "status should not be gated."
}

$env:VIBELUTION_DESKTOP_ENTRY_SUPPRESS_FEEDBACK = "1"
$script:feedbackEvents = @()
function Write-DesktopEntryLog {
    param(
        [string]$Event,
        [string]$Message,
        [string]$Level = "info",
        [hashtable]$Fields = @{}
    )
    $script:feedbackEvents += ,@{ event = $Event; fields = $Fields }
}
Show-DesktopEntryFeedback -Title "title" -Message "message" -Seconds 1 -Kind "info"
if ($script:feedbackEvents.Count -ne 1 -or $script:feedbackEvents[0].event -ne "desktop_entry.feedback.suppressed") {
    throw "Feedback suppression should be logged."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_desktop_entry_maps_close_to_stop_without_monitor(tmp_path):
    calls = _run_desktop_entry_with_fake_launcher(tmp_path, action="close")

    assert calls == [
        {
            "action": "stop",
            "argv": [],
            "noBrowser": False,
            "pythonExe": str(tmp_path / "project" / ".venv" / "Scripts" / "python.exe"),
        }
    ]


def test_desktop_entry_runs_restart_without_monitor(tmp_path):
    calls = _run_desktop_entry_with_fake_launcher(tmp_path, action="restart")

    assert calls == [
        {
            "action": "restart",
            "argv": [],
            "noBrowser": False,
            "pythonExe": str(tmp_path / "project" / ".venv" / "Scripts" / "python.exe"),
        }
    ]


def test_desktop_entry_status_does_not_attach_monitor(tmp_path):
    calls = _run_desktop_entry_with_fake_launcher(tmp_path, action="status")

    assert calls == [
        {
            "action": "status",
            "argv": [],
            "noBrowser": False,
            "pythonExe": str(tmp_path / "project" / ".venv" / "Scripts" / "python.exe"),
        }
    ]


def test_desktop_entry_forwards_no_browser_and_skips_monitor(tmp_path):
    calls = _run_desktop_entry_with_fake_launcher(tmp_path, action="open", no_browser=True)

    assert calls == [
        {
            "action": "start",
            "argv": [],
            "noBrowser": True,
            "pythonExe": str(tmp_path / "project" / ".venv" / "Scripts" / "python.exe"),
        }
    ]


def test_vbs_desktop_entry_accepts_named_action_arguments(tmp_path):
    calls, _events = _run_vbs_desktop_entry_with_fake_powershell_entry(tmp_path, ["-Action", "close"])

    assert calls == [
        {
            "action": "close",
            "argv": [],
            "noBrowser": False,
            "pythonExe": str(tmp_path / "project" / ".venv" / "Scripts" / "python.exe"),
        }
    ]


def test_vbs_desktop_entry_accepts_powershell_style_no_browser_switch(tmp_path):
    calls, events = _run_vbs_desktop_entry_with_fake_powershell_entry(tmp_path, ["open", "-NoBrowser"])

    assert calls == [
        {
            "action": "open",
            "argv": [],
            "noBrowser": True,
            "pythonExe": str(tmp_path / "project" / ".venv" / "Scripts" / "python.exe"),
        }
    ]
    assert events[-1]["event"] == "desktop_entry_vbs.feedback.suppressed"


def test_vbs_desktop_entry_accepts_colon_action_argument(tmp_path):
    calls, _events = _run_vbs_desktop_entry_with_fake_powershell_entry(tmp_path, ["-Action:status"])

    assert calls == [
        {
            "action": "status",
            "argv": [],
            "noBrowser": False,
            "pythonExe": str(tmp_path / "project" / ".venv" / "Scripts" / "python.exe"),
        }
    ]


def test_vbs_desktop_entry_accepts_equals_action_argument(tmp_path):
    calls, _events = _run_vbs_desktop_entry_with_fake_powershell_entry(tmp_path, ["--action=restart", "--no-browser"])

    assert calls == [
        {
            "action": "restart",
            "argv": [],
            "noBrowser": True,
            "pythonExe": str(tmp_path / "project" / ".venv" / "Scripts" / "python.exe"),
        }
    ]
