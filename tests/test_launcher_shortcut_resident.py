"""Exercise shortcut construction without creating real shell shortcuts."""
import json
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "vibelution_launcher.ps1"


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell shortcut construction")
@pytest.mark.parametrize("mode", ["packaged", "fallback"])
def test_shortcut_arguments_use_the_resident_entry_without_focus_or_workbench(tmp_path, mode):
    harness = tmp_path / "shortcut-contract.ps1"
    harness.write_text(r'''
param([string]$LauncherPath, [string]$Mode)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($LauncherPath, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw $errors[0] }
$fn = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq "Repair-LauncherShortcut" }, $true)
if (-not $fn) { throw "missing shortcut owner" }
Invoke-Expression $fn.Extent.Text
$script:mode = $Mode
$script:calls = @()
$projectDir = 'C:\fixture\Project With Spaces'
$launcherIconPath = 'C:\fixture\icon.ico'
$launcherShortcutName = 'Vibelution.lnk'
$launcherDesktopShortcutName = 'Vibelution Launcher.lnk'
function Test-Path { param($LiteralPath) return $true }
function Resolve-PackagedElectronDesktopEntryPath {
    if ($script:mode -eq 'fallback') { throw 'fixture unavailable' }
    return 'C:\fixture\Vibelution.exe'
}
function New-Object { param($ComObject) return 'fixture-shell' }
function Set-LauncherShellShortcut {
    param($Shell, $ShortcutPath, $TargetPath, $Arguments, $IconPath)
    $script:calls += [pscustomobject]@{ target = $TargetPath; arguments = $Arguments }
}
function Write-LauncherControlLog { param($Event, $Message, $Fields) }
$null = Repair-LauncherShortcut
if ($script:calls.Count -lt 1) { throw 'no shortcuts captured' }
ConvertTo-Json -InputObject @($script:calls) -Compress
''', encoding="utf-8")
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run([str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", str(harness), "-LauncherPath", str(LAUNCHER), "-Mode", mode], capture_output=True,
        text=True, encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
    assert result.returncode == 0, result.stderr or result.stdout
    calls = json.loads(result.stdout)
    assert calls and all(row == calls[0] for row in calls)
    args = calls[0]["arguments"]
    assert "vibelution://" not in args and "--open-workbench" not in args
    if mode == "packaged":
        assert calls[0]["target"] == r"C:\fixture\Vibelution.exe"
        assert args == '--workspace "C:\\fixture\\Project With Spaces"'
    else:
        assert calls[0]["target"].lower().endswith(r"powershell\v1.0\powershell.exe")
        assert "launch_vibelution_shortcut.ps1" in args and '-ProjectDir "C:\\fixture\\Project With Spaces"' in args


def test_fallback_wrapper_selects_default_resident_action():
    wrapper = (ROOT / "scripts" / "launch_vibelution_shortcut.ps1").read_text(encoding="utf-8")
    args = wrapper.split("$startArgs = @(", 1)[1].split(")", 1)[0]
    assert '"--action"' in args and '"launcher"' in args
    assert '"open"' not in args and "vibelution://" not in args
