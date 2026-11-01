"""Real shell-link migration in an isolated directory; no product lifecycle."""

import json
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "desktop_entry_catalog.ps1"


@pytest.mark.skipif(os.name != "nt", reason="Windows shell-link migration")
@pytest.mark.parametrize("mode", ["owned", "same_entry", "other_program", "other_project", "project_prefix",
                                  "project_slot", "duplicate_workspace", "save_failure"])
def test_desktop_shortcut_migration_preserves_other_entries_and_is_repeatable(tmp_path, mode):
    harness = tmp_path / "shortcut-migration.ps1"
    harness.write_text(r'''
param([string]$Helper, [string]$Root, [string]$Mode)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
. $Helper
$desktop = New-Item -ItemType Directory -Path (Join-Path $Root 'desktop')
$programs = New-Item -ItemType Directory -Path (Join-Path $Root 'programs')
$project = New-Item -ItemType Directory -Path (Join-Path $Root 'project with spaces')
$target = Join-Path $project.FullName 'dist\desktop\win-unpacked\Vibelution.exe'
$arguments = '--workspace "' + $project.FullName + '"'
$shell = New-Object -ComObject WScript.Shell
$legacyPath = Join-Path $desktop.FullName 'Vibelution.lnk'
$legacy = $shell.CreateShortcut($legacyPath)
$legacy.TargetPath = $target
$legacy.Arguments = $arguments + ' "vibelution://launcher/focus"'
if ($Mode -eq 'same_entry') { $legacy.Arguments = $arguments }
if ($Mode -eq 'other_program') { $legacy.TargetPath = Join-Path $Root 'different.exe' }
if ($Mode -eq 'other_project') { $legacy.Arguments = '--workspace "C:\other-project"' }
if ($Mode -eq 'project_prefix') { $legacy.Arguments = '--workspace "' + $project.FullName + '-other"' }
if ($Mode -eq 'project_slot') { $legacy.Arguments = $arguments + ' --project "C:\other-project"' }
if ($Mode -eq 'duplicate_workspace') { $legacy.Arguments = $arguments + ' --workspace "C:\other-project"' }
$legacy.Save()
$legacyHash = [Convert]::ToBase64String([IO.File]::ReadAllBytes($legacyPath))
$startMenuPath = Join-Path $programs.FullName 'Vibelution.lnk'
Copy-Item -LiteralPath $legacyPath -Destination $startMenuPath
$canonicalPath = Join-Path $desktop.FullName 'Vibelution Launcher.lnk'
if ($Mode -eq 'save_failure') { $null = New-Item -ItemType Directory -Path $canonicalPath }
$options = @{ Shell = $shell; ProjectDir = $project.FullName; TargetPath = $target; Arguments = $arguments;
    IconPath = (Join-Path $Root 'icon.ico'); DesktopDirectory = $desktop.FullName }
$failed = $false
try {
    $first = Set-VibelutionDesktopLauncherShortcut @options
    $second = Set-VibelutionDesktopLauncherShortcut @options
} catch { $failed = $true; if ($Mode -ne 'save_failure') { throw } }
if ($Mode -eq 'save_failure') {
    if (-not $failed) { throw 'Expected save failure' }
} else {
    if ($first -ne $canonicalPath -or $second -ne $canonicalPath) { throw 'Canonical path changed' }
    $canonical = $shell.CreateShortcut($canonicalPath)
    if ($canonical.TargetPath -ne $target -or $canonical.Arguments -ne $arguments -or $canonical.WorkingDirectory -ne $project.FullName) { throw 'Launch semantics changed' }
}
if ([Convert]::ToBase64String([IO.File]::ReadAllBytes($startMenuPath)) -ne $legacyHash) { throw 'Start Menu entry changed' }
$legacyRetained = Test-Path -LiteralPath $legacyPath
if ($legacyRetained -and [Convert]::ToBase64String([IO.File]::ReadAllBytes($legacyPath)) -ne $legacyHash) { throw 'Unowned entry changed' }
[pscustomobject]@{ legacyRetained = $legacyRetained; failed = $failed;
    desktopNames = @(Get-ChildItem -LiteralPath $desktop.FullName | Select-Object -ExpandProperty Name) } | ConvertTo-Json -Compress
''', encoding="utf-8")
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run(
        [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(harness), "-Helper", str(HELPER), "-Root", str(tmp_path), "-Mode", mode],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW, timeout=15,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    outcome = json.loads(result.stdout)
    assert outcome["legacyRetained"] == (mode not in {"owned", "same_entry"})
    assert outcome["failed"] == (mode == "save_failure")
    if mode in {"owned", "same_entry"}:
        assert outcome["desktopNames"] == ["Vibelution Launcher.lnk"]
