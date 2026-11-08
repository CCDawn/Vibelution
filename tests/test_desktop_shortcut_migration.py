"""Real shell-link migration in an isolated directory; no product lifecycle."""

import json
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "desktop_entry_catalog.ps1"
CATALOG = ROOT / "desktop" / "electron" / "desktop-entry-catalog.json"


@pytest.fixture
def powershell_harness(tmp_path):
    def run(source, **parameters):
        harness = tmp_path / "shortcut-harness.ps1"
        harness.write_text(source, encoding="utf-8")
        powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        command = [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                   "-File", str(harness), "-Helper", str(HELPER), "-Root", str(tmp_path)]
        for name, value in parameters.items():
            command.extend([f"-{name}", str(value)])
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
        assert result.returncode == 0, result.stderr or result.stdout
        return json.loads(result.stdout)
    return run


def write_catalog(project, catalog=None):
    path = project / "desktop" / "electron" / "desktop-entry-catalog.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(catalog or json.loads(CATALOG.read_text(encoding="utf-8"))), encoding="utf-8")


@pytest.mark.skipif(os.name != "nt", reason="Windows KnownFolder resolution")
def test_public_entry_uses_known_folder_after_checkout_moves(tmp_path, powershell_harness):
    original = tmp_path / "original project"
    moved = tmp_path / "moved project"
    write_catalog(original)
    original.rename(moved)
    outcome = powershell_harness(r'''
param([string]$Helper, [string]$Root, [string]$Project)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
. $Helper
$expected = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Vibelution\Launcher\VibelutionLauncher.exe'
$env:LOCALAPPDATA = Join-Path $Root 'untrusted-localappdata'
$env:APPDATA = Join-Path $Root 'untrusted-appdata'
Set-Location -LiteralPath $Project
$catalog = Assert-DesktopEntryCatalog -ProjectDir $Project
$entry = Resolve-DesktopPublicEntryPath -Catalog $catalog
$arguments = Resolve-DesktopPublicEntryArguments -Catalog $catalog
$artifact = Resolve-DesktopPackageEntryPath -Catalog $catalog -ProjectDir $Project
if ($entry -ne $expected -or $arguments -cne '--assistant') { throw 'Public entry depends on checkout/environment' }
if ($artifact -ne (Join-Path $Project 'dist/desktop/win-unpacked/Vibelution.exe')) { throw 'Artifact left project' }
[pscustomobject]@{ entry = $entry; arguments = $arguments; artifact = $artifact } | ConvertTo-Json -Compress
''', Project=moved)
    assert outcome["arguments"] == "--assistant"
    assert str(moved) not in outcome["entry"]
    assert str(moved) in outcome["artifact"]


@pytest.mark.skipif(os.name != "nt", reason="Windows catalog bridge")
@pytest.mark.parametrize(("field", "value"), [
    ("path", "../Launcher/VibelutionLauncher.exe"),
    ("path", "C:/untrusted/VibelutionLauncher.exe"),
    ("path", "dist/desktop/win-unpacked/Vibelution.exe"),
    ("pathBase", "project"),
    ("arguments", ["--assistant", "--workspace", "C:/other"]),
    ("arguments", ["--project", "C:/other", "start"]),
    ("arguments", ["--Assistant"]),
    ("arguments", "--assistant"),
    ("arguments", []),
])
def test_public_entry_rejects_noncanonical_catalog_without_prior_assertion(tmp_path, powershell_harness, field, value):
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    catalog["publicProductEntries"][0][field] = value
    project = tmp_path / "project"
    write_catalog(project, catalog)
    outcome = powershell_harness(r'''
param([string]$Helper, [string]$Root, [string]$Project)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. $Helper
$catalog = Read-DesktopEntryCatalog -ProjectDir $Project
$rejected = 0
try { $null = Assert-DesktopEntryCatalog -ProjectDir $Project } catch { $rejected++ }
try { $null = Resolve-DesktopPublicEntryPath -Catalog $catalog } catch { $rejected++ }
try { $null = Resolve-DesktopPublicEntryArguments -Catalog $catalog } catch { $rejected++ }
[pscustomobject]@{ rejected = $rejected } | ConvertTo-Json -Compress
''', Project=project)
    assert outcome["rejected"] == 3


@pytest.mark.skipif(os.name != "nt", reason="Windows catalog bridge")
def test_package_artifact_resolver_rejects_path_traversal(tmp_path, powershell_harness):
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    artifact = next(entry for entry in catalog["operatorEntries"] if entry["id"] == "desktop-package-artifact")
    artifact["path"] = "../Vibelution.exe"
    project = tmp_path / "project"
    write_catalog(project, catalog)
    outcome = powershell_harness(r'''
param([string]$Helper, [string]$Root, [string]$Project)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. $Helper
$catalog = Read-DesktopEntryCatalog -ProjectDir $Project
$rejected = $false
try { $null = Resolve-DesktopPackageEntryPath -Catalog $catalog -ProjectDir $Project } catch { $rejected = $true }
[pscustomobject]@{ rejected = $rejected } | ConvertTo-Json -Compress
''', Project=project)
    assert outcome["rejected"]


@pytest.mark.skipif(os.name != "nt", reason="Windows shell-link migration")
@pytest.mark.parametrize("mode", ["owned", "same_entry", "other_program", "other_project", "project_prefix",
                                  "project_slot", "duplicate_workspace", "save_failure"])
def test_desktop_shortcut_migration_preserves_other_entries_and_is_repeatable(powershell_harness, mode):
    outcome = powershell_harness(r'''
param([string]$Helper, [string]$Root, [string]$Mode)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
. $Helper
$desktop = New-Item -ItemType Directory -Path (Join-Path $Root 'desktop')
$programs = New-Item -ItemType Directory -Path (Join-Path $Root 'programs')
$project = New-Item -ItemType Directory -Path (Join-Path $Root 'project with spaces')
$target = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Vibelution\Launcher\VibelutionLauncher.exe'
$arguments = '--assistant'
$oldTarget = Join-Path $project.FullName 'dist\desktop\win-unpacked\Vibelution.exe'
$oldArguments = '--workspace "' + $project.FullName + '"'
$shell = New-Object -ComObject WScript.Shell
$legacyPath = Join-Path $desktop.FullName 'Vibelution.lnk'
$legacy = $shell.CreateShortcut($legacyPath)
$legacy.TargetPath = $oldTarget
$legacy.Arguments = $oldArguments + ' "vibelution://launcher/focus"'
if ($Mode -eq 'same_entry') { $legacy.TargetPath = $target; $legacy.Arguments = $arguments }
if ($Mode -eq 'other_program') { $legacy.TargetPath = Join-Path $Root 'different.exe' }
if ($Mode -eq 'other_project') { $legacy.Arguments = '--workspace "C:\other-project"' }
if ($Mode -eq 'project_prefix') { $legacy.Arguments = '--workspace "' + $project.FullName + '-other"' }
if ($Mode -eq 'project_slot') { $legacy.Arguments = $oldArguments + ' --project "C:\other-project"' }
if ($Mode -eq 'duplicate_workspace') { $legacy.Arguments = $oldArguments + ' --workspace "C:\other-project"' }
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
    if ($canonical.TargetPath -ne $target -or $canonical.Arguments -ne $arguments -or $canonical.WorkingDirectory -ne (Split-Path -Parent $target)) { throw 'Launch semantics changed' }
}
if ([Convert]::ToBase64String([IO.File]::ReadAllBytes($startMenuPath)) -ne $legacyHash) { throw 'Start Menu entry changed' }
$legacyRetained = Test-Path -LiteralPath $legacyPath
if ($legacyRetained -and [Convert]::ToBase64String([IO.File]::ReadAllBytes($legacyPath)) -ne $legacyHash) { throw 'Unowned entry changed' }
[pscustomobject]@{ legacyRetained = $legacyRetained; failed = $failed;
    desktopNames = @(Get-ChildItem -LiteralPath $desktop.FullName | Select-Object -ExpandProperty Name) } | ConvertTo-Json -Compress
''', Mode=mode)
    assert outcome["legacyRetained"] == (mode not in {"owned", "same_entry"})
    assert outcome["failed"] == (mode == "save_failure")
    if mode in {"owned", "same_entry"}:
        assert outcome["desktopNames"] == ["Vibelution Launcher.lnk"]


@pytest.mark.skipif(os.name != "nt", reason="Windows shell links")
def test_public_shortcuts_use_managed_entry_for_desktop_and_start_menu(tmp_path, powershell_harness):
    project = tmp_path / "project"
    write_catalog(project)
    outcome = powershell_harness(r'''
param([string]$Helper, [string]$Root, [string]$Project)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
. $Helper
$catalog = Assert-DesktopEntryCatalog -ProjectDir $Project
$target = Resolve-DesktopPublicEntryPath -Catalog $catalog
$arguments = Resolve-DesktopPublicEntryArguments -Catalog $catalog
$desktop = New-Item -ItemType Directory -Path (Join-Path $Root 'desktop')
$programs = Join-Path $Root 'start-menu\Programs'
$shell = New-Object -ComObject WScript.Shell
$options = @{ Shell = $shell; TargetPath = $target; Arguments = $arguments; IconPath = $target }
$paths = @(
    Set-VibelutionDesktopLauncherShortcut @options -ProjectDir $Project -DesktopDirectory $desktop.FullName
    Set-VibelutionStartMenuLauncherShortcut @options -ProgramsDirectory $programs
)
$null = Set-VibelutionStartMenuLauncherShortcut @options -ProgramsDirectory $programs
foreach ($path in $paths) {
    $shortcut = $shell.CreateShortcut($path)
    if ($shortcut.TargetPath -ne $target -or $shortcut.Arguments -cne '--assistant' -or
        $shortcut.WorkingDirectory -ne (Split-Path -Parent $target) -or $shortcut.IconLocation -ne ($target + ',0')) {
        throw 'Public shortcut depends on the project'
    }
}
[pscustomobject]@{ paths = $paths } | ConvertTo-Json -Compress
''', Project=project)
    assert len(outcome["paths"]) == 2
    assert all(str(tmp_path) in path for path in outcome["paths"])


@pytest.mark.skipif(os.name != "nt", reason="Windows shortcut repair")
def test_repair_rejects_missing_managed_entry_before_writing_shortcuts(tmp_path, powershell_harness):
    project = tmp_path / "project"
    write_catalog(project)
    outcome = powershell_harness(r'''
param([string]$Helper, [string]$Root, [string]$Project, [string]$LauncherScript)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$desktopEntryCatalogScriptPath = $Helper
$projectDir = $Project
$missingEntry = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Vibelution\Launcher\VibelutionLauncher.exe'
# Load only these functions; the script's lifecycle dispatcher must never run.
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($LauncherScript, [ref]$tokens, [ref]$errors)
foreach ($function in $ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -in @('Resolve-ManagedDesktopPublicEntryPath', 'Repair-LauncherShortcut')
}, $false)) { Invoke-Expression $function.Extent.Text }
function Test-Path {
    param([string]$LiteralPath, [string]$PathType)
    if ($LiteralPath -eq $missingEntry) { return $false }
    return Microsoft.PowerShell.Management\Test-Path @PSBoundParameters
}
function New-Object { throw 'Shortcut shell must not be created after entry failure' }
$message = ''
try { $null = Repair-LauncherShortcut } catch { $message = $_.Exception.Message }
if (-not $message.Contains('Managed native Launcher entry is missing:') -or
    -not $message.Contains('install_windows.ps1 before repairing the shortcut.')) {
    throw "Unexpected failure: $message"
}
[pscustomobject]@{ rejected = $true } | ConvertTo-Json -Compress
''', Project=project, LauncherScript=ROOT / "scripts" / "vibelution_launcher.ps1")
    assert outcome["rejected"]
