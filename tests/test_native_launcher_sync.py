import json
import os
import subprocess
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent
SYNC_SCRIPT = PROJECT_ROOT / "scripts" / "windows_launcher_entry" / "sync_vibelution_launcher_entry.ps1"
POST_MERGE_HOOK = PROJECT_ROOT / ".githooks" / "post-merge"


def _powershell_exe() -> str:
    return str(Path(os.environ.get("SystemRoot", r"C:\\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")


def _write_fake_project(project_root: Path) -> Path:
    entry_dir = project_root / "scripts" / "windows_launcher_entry"
    entry_dir.mkdir(parents=True)
    (project_root / "assets" / "icons").mkdir(parents=True)
    (entry_dir / "VibelutionLauncher.cs").write_text("source", encoding="utf-8")
    (project_root / "assets" / "icons" / "vibelution.ico").write_text("icon", encoding="utf-8")
    (entry_dir / "build_vibelution_launcher_entry.ps1").write_text(
        """
param([string]$ProjectDir, [string]$OutputPath)
$directory = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Path $directory -Force | Out-Null
Set-Content -LiteralPath $OutputPath -Value (Get-Date).ToUniversalTime().ToString("o") -Encoding utf8
""".strip(),
        encoding="utf-8",
    )
    return entry_dir / "VibelutionLauncher.cs"


def _sync(project_root: Path, output_path: Path) -> dict[str, object]:
    result = subprocess.run(
        [
            _powershell_exe(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SYNC_SCRIPT),
            "-ProjectDir",
            str(project_root),
            "-OutputPath",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


def test_native_launcher_sync_rebuilds_only_when_inputs_are_newer(tmp_path: Path):
    project_root = tmp_path / "project"
    source_path = _write_fake_project(project_root)
    output_path = tmp_path / "installed" / "VibelutionLauncher.exe"

    first = _sync(project_root, output_path)
    assert first["status"] == "rebuilt"
    assert first["rebuilt"] is True
    assert output_path.exists()

    second = _sync(project_root, output_path)
    assert second == {"outputPath": str(output_path), "status": "current", "rebuilt": False}

    time.sleep(1.1)
    source_path.write_text("source updated", encoding="utf-8")
    third = _sync(project_root, output_path)
    assert third["status"] == "rebuilt"
    assert third["rebuilt"] is True

    sync_events = [
        json.loads(line)
        for line in (project_root / ".runtime" / "launcher" / "native-entry-sync.log").read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    assert [event["event"] for event in sync_events] == ["native_launcher.sync.rebuilt", "native_launcher.sync.rebuilt"]


def test_post_merge_hook_syncs_only_local_main_without_user_visible_host():
    source = POST_MERGE_HOOK.read_text(encoding="utf-8")

    assert 'git branch --show-current' in source
    assert '!= "main"' in source
    assert "sync_vibelution_launcher_entry.ps1" in source
    assert "-WindowStyle Hidden" in source
    assert "-Quiet" in source
