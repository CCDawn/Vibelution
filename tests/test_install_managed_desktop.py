"""Explicit install entry contract; no real build, product or production root."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from types import ModuleType

import pytest

from core.launcher import managed_desktop_package as owner
from scripts import install_managed_desktop as cli
from tests.test_managed_desktop_package import package, package_fixture


ROOT = Path(__file__).resolve().parents[1]


def test_project_prepare_is_rejected_before_build_import(tmp_path, capsys):
    assert cli.main(["--project", str(tmp_path)], managed_root=tmp_path / "managed") == 1
    assert '"MANAGED_INSTALL_FAILED"' in capsys.readouterr().out
    assert not (tmp_path / "managed").exists()


def test_source_default_prepare_is_readonly_without_config_or_build_import(package, tmp_path):
    runner = r'''
import os, runpy, sys
sys.dont_write_bytecode = True
class ForbiddenImport:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "config" or fullname.startswith("config.") or fullname == "core.launcher.desktop_shell":
            raise RuntimeError("forbidden bootstrap import")
sys.meta_path.insert(0, ForbiddenImport())
def audit(event, args):
    if event == "open":
        path, mode, flags = args
        writing = (flags or 0) & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND)
        writing = writing or (isinstance(mode, str) and any(c in mode for c in "wax+"))
        if writing and path != os.devnull:
            raise RuntimeError("prepare attempted a write")
    elif event in {"os.mkdir", "os.rename", "os.remove", "os.rmdir", "os.utime", "os.chmod"}:
        raise RuntimeError("prepare attempted a mutation")
sys.addaudithook(audit)
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
'''
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("VIBELUTION_")}
    env.update(USERPROFILE=str(tmp_path / "profile"), HOME=str(tmp_path / "profile"),
               LOCALAPPDATA=str(tmp_path / "local"), VIBELUTION_MANAGED_DESKTOP_ROOT=str(tmp_path / "poison"))
    result = subprocess.run([sys.executable, "-I", "-B", "-c", runner,
                             str(ROOT / "scripts/install_managed_desktop.py"), "--source-package", str(package)],
                            capture_output=True, text=True, timeout=25, env=env,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert result.returncode == 0, result.stdout + result.stderr
    value = json.loads(result.stdout)
    prepared = owner.prepare_managed_desktop_package(package)
    assert value == {"schemaVersion": 1, "status": "prepared", "fileCount": len(prepared.files),
                     "bytes": sum(r["size"] for r in prepared.files), "packageId": prepared.active["packageId"]}
    assert len(result.stdout) < 300
    assert not (tmp_path / "profile").exists() and not (tmp_path / "poison").exists()
    assert not (package / owner.CATALOG_NAME).exists()


def test_source_apply_uses_existing_sealed_publisher_in_temp(package, tmp_path, capsys):
    managed = tmp_path / "managed"
    assert cli.main(["--source-package", str(package), "--apply"], managed_root=managed) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt == {"schemaVersion": 1, "status": "installed",
                       "packageId": owner.inspect_active_managed_desktop_package(managed_root=managed)["packageId"]}


@pytest.mark.parametrize("flags", [[], ["--source-package", "relative"], ["--project", "relative", "--apply"],
    ["--source-package", ".", "--project", "."], ["--source-package", ".", "--root", "elsewhere"],
    ["--source-package", ".", "--managed-root", "elsewhere"], ["--source", "."]])
def test_closed_cli_rejects_relative_conflicting_and_free_root_arguments(tmp_path, capsys, flags):
    assert cli.main(flags, managed_root=tmp_path / "managed") == 1
    assert json.loads(capsys.readouterr().out) == {
        "schemaVersion": 1, "status": "failed", "error": "MANAGED_INSTALL_FAILED"}
    assert not (tmp_path / "managed").exists()


@pytest.mark.parametrize("fault", ["missing", "corrupt"])
def test_bad_source_keeps_existing_pointer(package, tmp_path, capsys, fault):
    managed = tmp_path / "managed"
    owner.install_managed_desktop_package(package, managed_root=managed)
    previous = (managed / "active.json").read_bytes()
    if fault == "missing":
        source = tmp_path / "missing"
    else:
        source = package
        (package / "resources/launcher-assistant/manifest.json").write_text("{}", encoding="utf-8")
    assert cli.main(["--source-package", str(source), "--apply"], managed_root=managed) == 1
    assert "MANAGED_INSTALL_FAILED" in capsys.readouterr().out
    assert (managed / "active.json").read_bytes() == previous


def _fake_build(monkeypatch, result):
    calls = []
    module = ModuleType("core.launcher.desktop_shell")
    def build(project, *, mode):
        calls.append((project, mode))
        print("owner diagnostic must not enter the receipt")
        if isinstance(result, Exception):
            raise result
        return result
    module.build_desktop_shell_package = build
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return calls


@pytest.mark.parametrize("result", [None, {}, {"built": False, "mode": "dir"},
    {"built": 1, "mode": "dir"}, {"built": True, "mode": "staging"},
    RuntimeError("private build diagnostic"), {"built": True, "mode": "dir"}])
def test_bad_build_result_or_missing_package_never_publishes(tmp_path, monkeypatch, capsys, result):
    calls = _fake_build(monkeypatch, result)
    managed = tmp_path / "managed"
    managed.mkdir()
    pointer = managed / "active.json"
    pointer.write_bytes(b"previous active bytes")
    monkeypatch.setattr(owner, "install_managed_desktop_package", lambda *a, **k: pytest.fail("must not publish"))
    assert cli.main(["--project", str(tmp_path), "--apply"], managed_root=managed) == 1
    assert calls == [(tmp_path, "dir")]
    assert pointer.read_bytes() == b"previous active bytes"
    assert json.loads(capsys.readouterr().out)["error"] == "MANAGED_INSTALL_FAILED"


def test_project_apply_only_publishes_canonical_producer_output(tmp_path, monkeypatch, capsys):
    expected = tmp_path / "dist/desktop/win-unpacked"
    expected.mkdir(parents=True)
    calls = _fake_build(monkeypatch, {"built": True, "mode": "dir", "output": str(tmp_path / "untrusted-output")})
    installed = []
    def install(source, **kwargs):
        installed.append((source, kwargs))
        return {"packageId": "a" * 64}
    monkeypatch.setattr(owner, "install_managed_desktop_package", install)
    assert cli.main(["--project", str(tmp_path), "--apply"], managed_root=tmp_path / "managed") == 0
    assert calls == [(tmp_path, "dir")]
    assert installed == [(expected, {"managed_root": tmp_path / "managed"})]
    assert json.loads(capsys.readouterr().out)["status"] == "installed"


def test_production_apply_leaves_knownfolder_root_selection_to_owner(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VIBELUTION_MANAGED_DESKTOP_ROOT", str(tmp_path / "poison"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "poison"))
    installed = []
    def install(source, **kwargs):
        installed.append((source, kwargs))
        return {"packageId": "b" * 64}
    monkeypatch.setattr(owner, "install_managed_desktop_package", install)
    assert cli.main(["--source-package", str(tmp_path), "--apply"]) == 0
    assert installed == [(tmp_path, {})]
    assert json.loads(capsys.readouterr().out)["packageId"] == "b" * 64
    assert not (tmp_path / "poison").exists()


def test_install_windows_binds_explicit_project_apply_after_native_sync():
    source = (ROOT / "scripts/install_windows.ps1").read_text(encoding="utf-8")
    hook = source.index('$ManagedDesktopInstaller = Join-Path $ProjectDir "scripts\\install_managed_desktop.py"')
    assert source.index('Write-Step "Sync and verify required native Launcher entry') < hook < source.index('Write-Host "Install finished.')
    assert '-FilePath $VenvPython `' in source[hook:hook + 400]
    assert '-ArgumentList @($ManagedDesktopInstaller, "--project", $ProjectDir, "--apply")' in source[hook:hook + 400]
    assert 'Independent assistant: $NativeLauncher --assistant' in source
    assert '-ArgumentList @("--project", $ProjectDir, "start")' in source


def test_install_windows_prepares_electron_dependencies_before_producer():
    source = (ROOT / "scripts/install_windows.ps1").read_text(encoding="utf-8")
    prepare = source.index("Ensure-DesktopElectronDependencies -DesktopDir $DesktopElectronDir")
    assert prepare < source.index('$ManagedDesktopInstaller =')
    assert '"ci", "--include=dev", "--prefix", $DesktopDir' in source


def test_install_windows_requires_confirmed_native_sync_before_publish():
    source = (ROOT / "scripts/install_windows.ps1").read_text(encoding="utf-8")
    gate = source.index("Sync-NativeLauncherForManagedInstall -SyncScript $SyncLauncher")
    assert gate < source.index('$ManagedDesktopInstaller =')
    assert '-ProjectRoot $ProjectDir -OutputPath $NativeLauncher' in source[gate:gate + 220]
    assert '"current", "rebuilt"' in source
    assert '"-ProjectDir", $ProjectRoot' in source


def _ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def _run_install_function(tmp_path, name, body):
    if os.name != "nt":
        pytest.skip("Windows PowerShell installer functions")
    source = (ROOT / "scripts/install_windows.ps1").read_text(encoding="utf-8")
    function = re.search(r"(?ms)^function " + re.escape(name) + r" \{.*?^\}", source)
    assert function is not None
    script = tmp_path / "function-only.ps1"
    script.write_text('Set-StrictMode -Version Latest\n$ErrorActionPreference = "Stop"\n'
                      '$OutputEncoding = [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)\n'
                      + function.group() + "\n" + body, encoding="utf-8-sig")
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("VIBELUTION_")}
    env.update(USERPROFILE=str(tmp_path / "private"), HOME=str(tmp_path / "private"),
               LOCALAPPDATA=str(tmp_path / "private"), PSModulePath=str(powershell.parent / "Modules"))
    result = subprocess.run([str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                             "-ExecutionPolicy", "Bypass", "-File", str(script)],
                            env=env, capture_output=True, text=True, encoding="utf-8", timeout=15,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.splitlines()[-1])


@pytest.mark.parametrize("mode,expected", [("reuse", ["ls"]), ("stale", ["ls", "ci"]), ("missing", ["ci"])])
def test_electron_dependencies_validate_reuse_or_explicit_ci(tmp_path, mode, expected):
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    if mode != "missing":
        (desktop / "node_modules").mkdir()
    body = r'''
$script:calls = @()
function Invoke-Native {
    param($FilePath, [string[]]$ArgumentList, $Label)
    $script:calls += ,@{ file=$FilePath; args=$ArgumentList }
    if ($ArgumentList[0] -eq 'ls' -and MODE -eq 'stale') { throw 'mock dependency mismatch' }
}
Ensure-DesktopElectronDependencies -DesktopDir DESKTOP
@{calls=$script:calls} | ConvertTo-Json -Depth 6 -Compress
'''.replace("MODE", _ps_quote(mode)).replace("DESKTOP", _ps_quote(desktop))
    result = _run_install_function(tmp_path, "Ensure-DesktopElectronDependencies", body)
    assert [c["args"][0] for c in result["calls"]] == expected
    assert all(c["file"] == "npm" and c["args"][-2:] == ["--prefix", str(desktop)]
               and "--include=dev" in c["args"] for c in result["calls"])


@pytest.mark.parametrize("status,exists,wrong_path,native_error,accepted", [
    ("current", True, False, False, True), ("rebuilt", True, False, False, True),
    ("deferred", True, False, False, False), ("unknown", True, False, False, False),
    ("current", False, False, False, False), ("current", True, True, False, False),
    ("current", True, False, True, False), ("bad-json", True, False, False, False),
])
def test_native_sync_gate_never_reaches_publish_without_confirmed_exe(
        tmp_path, status, exists, wrong_path, native_error, accepted):
    sync = tmp_path / "sync.ps1"
    sync.write_text("# mock; never executed", encoding="utf-8")
    exe = tmp_path / "launcher.exe"
    if exists:
        exe.write_bytes(b"MZ mock; never executed")
    response = "not-json" if status == "bad-json" else json.dumps({
        "status": status, "outputPath": str(tmp_path / "wrong.exe" if wrong_path else exe)})
    body = r'''
$script:syncArgs = @()
function Invoke-Native {
    param($FilePath, [string[]]$ArgumentList, $Label)
    $script:syncArgs = $ArgumentList
    if (NATIVEERROR) { throw 'mock sync process failed' }
    return RESPONSE
}
$reachedPublish = $false
try {
    Sync-NativeLauncherForManagedInstall -SyncScript SYNC -ProjectRoot PROJECT -OutputPath OUTPUT
    $reachedPublish = $true
} catch { }
@{publish=$reachedPublish; args=$script:syncArgs} | ConvertTo-Json -Depth 6 -Compress
'''.replace("NATIVEERROR", "$true" if native_error else "$false").replace("RESPONSE", _ps_quote(response))
    body = body.replace("SYNC", _ps_quote(sync)).replace("PROJECT", _ps_quote(tmp_path)).replace("OUTPUT", _ps_quote(exe))
    result = _run_install_function(tmp_path, "Sync-NativeLauncherForManagedInstall", body)
    assert result["publish"] is accepted
    assert result["args"][-4:] == ["-ProjectDir", str(tmp_path), "-OutputPath", str(exe)]
    assert result["args"][result["args"].index("-WindowStyle") + 1] == "Hidden"
