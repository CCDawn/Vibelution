import logging
import os
import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parent.parent
LAUNCHER_SCRIPT = PROJECT_ROOT / "scripts" / "vibelution_launcher.ps1"


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
