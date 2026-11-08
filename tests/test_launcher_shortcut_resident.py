"""Exercise public shortcut repair and its legacy bootstrap without desktop effects."""
import json
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "vibelution_launcher.ps1"
WRAPPER = ROOT / "scripts" / "launch_vibelution_shortcut.ps1"


@pytest.fixture
def shortcut_project(tmp_path):
    project = tmp_path / "Project With Spaces"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "desktop_entry_catalog.ps1").write_bytes((ROOT / "scripts" / "desktop_entry_catalog.ps1").read_bytes())
    catalog_path = project / "desktop" / "electron" / "desktop-entry-catalog.json"
    catalog_path.parent.mkdir(parents=True)
    catalog_path.write_bytes((ROOT / "desktop" / "electron" / "desktop-entry-catalog.json").read_bytes())
    return project


@pytest.fixture
def shortcut_harness(tmp_path, shortcut_project):
    project = shortcut_project
    catalog_path = project / "desktop" / "electron" / "desktop-entry-catalog.json"

    def run(owner, mode):
        if mode == "invalid_catalog":
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            catalog["publicProductEntries"][0]["arguments"] = ["--assistant", "--project", "C:/other"]
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
        harness = tmp_path / "shortcut-contract.ps1"
        harness.write_text(r'''
param([string]$LauncherPath, [string]$WrapperPath, [string]$Project, [string]$Owner, [string]$Mode)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$global:shortcutTestCalls = @()
$global:shortcutTestLaunches = @()
$expected = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Vibelution\Launcher\VibelutionLauncher.exe'
$programs = [Environment]::GetFolderPath('Programs')
function Test-Path {
    param([string]$LiteralPath, [string]$PathType)
    if ($LiteralPath -eq $expected) { return $Mode -ne 'missing' }
    if ($LiteralPath -eq $programs) { return $true }
    if ([IO.Path]::GetExtension($LiteralPath) -eq '.lnk') { return $false }
    return Microsoft.PowerShell.Management\Test-Path @PSBoundParameters
}
$global:shortcutTestShell = [pscustomobject]@{}
$global:shortcutTestShell | Add-Member ScriptMethod CreateShortcut {
    param($path)
    $link = [pscustomobject]@{ TargetPath = ''; Arguments = ''; WorkingDirectory = ''; IconLocation = ''; Description = ''; WindowStyle = 0; Path = $path }
    $link | Add-Member ScriptMethod Save {
        if ($Mode -eq 'shortcut_failure') { throw 'fixture shortcut save failed' }
        $global:shortcutTestCalls += [pscustomobject]@{
            target = $this.TargetPath; arguments = $this.Arguments; workingDirectory = $this.WorkingDirectory
            icon = $this.IconLocation; path = $this.Path
        }
    }
    return $link
}
function New-Object { param($ComObject) return $global:shortcutTestShell }
function Start-Process {
    param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle)
    $global:shortcutTestLaunches += [pscustomobject]@{
        target = $FilePath; arguments = @($ArgumentList); workingDirectory = $WorkingDirectory; windowStyle = $WindowStyle
    }
}
function Write-LauncherControlLog { param($Event, $Message, $Fields) }
$message = ''
try {
    if ($Owner -eq 'wrapper') {
        & $WrapperPath -ProjectDir $Project
    } else {
        $projectDir = $Project
        $desktopEntryCatalogScriptPath = Join-Path $Project 'scripts\desktop_entry_catalog.ps1'
        $tokens = $null; $errors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile($LauncherPath, [ref]$tokens, [ref]$errors)
        if ($errors.Count) { throw $errors[0] }
        foreach ($fn in $ast.FindAll({ param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -in @('Repair-LauncherShortcut', 'Resolve-ManagedDesktopPublicEntryPath')
        }, $false)) { Invoke-Expression $fn.Extent.Text }
        $null = Repair-LauncherShortcut
    }
} catch { $message = $_.Exception.Message }
[pscustomobject]@{ calls = @($global:shortcutTestCalls); launches = @($global:shortcutTestLaunches); message = $message; expected = $expected;
    workingDirectory = (Split-Path -Parent $expected) } | ConvertTo-Json -Depth 5 -Compress
''', encoding="utf-8")
        powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        result = subprocess.run([
            str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(harness), "-LauncherPath", str(LAUNCHER), "-WrapperPath", str(WRAPPER),
            "-Project", str(project), "-Owner", owner, "-Mode", mode,
        ], capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
        assert result.returncode == 0, result.stderr or result.stdout
        return json.loads(result.stdout)
    return run


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell shortcut construction")
@pytest.mark.parametrize("owner", ["repair", "wrapper"])
@pytest.mark.parametrize("mode", ["installed", "missing", "invalid_catalog", "shortcut_failure"])
def test_public_shortcut_owners_use_only_the_managed_assistant(shortcut_harness, owner, mode):
    outcome = shortcut_harness(owner, mode)
    if mode != "installed":
        assert outcome["message"]
        assert outcome["calls"] == [] and outcome["launches"] == []
        if mode == "missing":
            assert "Managed native Launcher entry is missing:" in outcome["message"]
            assert "install_windows.ps1" in outcome["message"]
        return
    assert outcome["message"] == ""
    calls = outcome["calls"]
    assert len(calls) == 2
    assert {Path(row["path"]).name for row in calls} == {"Vibelution.lnk", "Vibelution Launcher.lnk"}
    for row in calls:
        assert row["target"] == outcome["expected"]
        assert row["arguments"] == "--assistant"
        assert row["workingDirectory"] == outcome["workingDirectory"]
        assert row["icon"] == outcome["expected"] + ",0"
    if owner == "wrapper":
        assert outcome["launches"] == [{
            "target": outcome["expected"], "arguments": ["--assistant"],
            "workingDirectory": outcome["workingDirectory"], "windowStyle": "Hidden",
        }]
    else:
        assert outcome["launches"] == []


def test_legacy_bootstrap_cannot_rebuild_or_rewrite_a_second_public_entry():
    wrapper = WRAPPER.read_text(encoding="utf-8")
    assert "Resolve-DesktopPublicEntryPath -Catalog $catalog" in wrapper
    assert "Resolve-DesktopPublicEntryArguments -Catalog $catalog" in wrapper
    assert "Set-VibelutionDesktopLauncherShortcut" in wrapper
    assert "Set-VibelutionStartMenuLauncherShortcut" in wrapper
    for forbidden in ("entry-cache", "Get-NativeEntryCacheKey", "build_vibelution_launcher_entry.ps1", "powershell.exe",
                      "--from-shortcut", "--workspace", "--project", "--action", "vibelution://", "catch"):
        assert forbidden not in wrapper
