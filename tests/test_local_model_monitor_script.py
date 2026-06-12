import json
import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parent.parent
MONITOR_SCRIPT = PROJECT_ROOT / "tools" / "monitor-local-model.ps1"

pytestmark = pytest.mark.slow


def _powershell_exe() -> str:
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        pytest.skip("PowerShell is required for local model monitor script tests")
    return exe


def test_local_model_monitor_script_has_no_personal_registry_default():
    text = MONITOR_SCRIPT.read_text(encoding="utf-8")

    assert "BossAI开发" not in text
    assert "C:\\Users\\17533" not in text
    assert "VIBELUTION_SERVER_REGISTRY" in text


def test_local_model_monitor_script_parses_as_powershell():
    ps = _powershell_exe()
    command = (
        "$tokens=$null; $errors=$null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{MONITOR_SCRIPT}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count) { $errors | ForEach-Object { $_.Message }; exit 1 }"
    )

    result = subprocess.run([ps, "-NoProfile", "-Command", command], text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr or result.stdout


def test_local_model_monitor_server_id_uses_registry_port(tmp_path):
    ps = _powershell_exe()
    registry_path = tmp_path / "servers.json"
    registry_path.write_text(
        json.dumps(
            {
                "servers": {
                    "test-local": {
                        "configured": True,
                        "host": "127.0.0.1",
                        "sshAlias": "unused",
                        "ports": {"model": 65534},
                        "model": {"logFile": "/tmp/test.log"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            ps,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(MONITOR_SCRIPT),
            "-ServerId",
            "test-local",
            "-RegistryPath",
            str(registry_path),
            "-Once",
            "-NoSsh",
            "-HttpTimeoutSeconds",
            "1",
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "base_url: http://127.0.0.1:65534" in result.stdout
    assert "ssh disabled; HTTP-only monitor" in result.stdout
