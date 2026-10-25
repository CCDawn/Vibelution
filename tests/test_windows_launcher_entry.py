"""Native managed assistant admission; no real install, project or model."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from tests.test_managed_desktop_package import package as managed_source_package, package_fixture

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "scripts/windows_launcher_entry/VibelutionLauncher.cs"
HELPER = ENTRY.with_name("ManagedDesktopAssistant.cs")


@pytest.fixture(scope="module")
def managed_native_harness(tmp_path_factory):
    if os.name != "nt":
        pytest.skip("Windows native Launcher")
    work = tmp_path_factory.mktemp("managed-native")
    harness = work / "Harness.cs"
    harness.write_text(r'''
using System;
using System.Diagnostics;
using System.Reflection;
using System.Web.Script.Serialization;
internal static class ManagedHarness {
 public static int Main(string[] args) {
  Console.OutputEncoding=new System.Text.UTF8Encoding(false);
  var type=typeof(VibelutionLauncher).Assembly.GetType("ManagedDesktopAssistant");
  if(type==null){Console.WriteLine("missing");return 9;}
  try {
   if(args.Length>1 && args[1]=="public-spelling") {
    var spelling=type.GetMethod("PublicPathSpelling",BindingFlags.Static|BindingFlags.NonPublic);
    Console.WriteLine(spelling.Invoke(null,new object[]{args[0]})); return 0;
   }
   if(args.Length>2 && args[1]=="public-open") {
    var open=type.GetMethod("OpenCore",BindingFlags.Static|BindingFlags.NonPublic);
    using(var file=(System.IO.Stream)open.Invoke(null,new object[]{args[0],true,args[2]})){}
    return 0;
   }
   if(args.Length>1 && args[1]=="redirect-open") {
    var open=type.GetMethod("Open",BindingFlags.Static|BindingFlags.NonPublic);
    using(var file=(System.IO.Stream)open.Invoke(null,new object[]{"\\\\?\\"+args[0],true})){}
    return 0;
   }
   if(args.Length>1 && args[1]=="hold") {
    var prepare=type.GetMethod("PrepareStart",BindingFlags.Static|BindingFlags.NonPublic);
    var lease=(IDisposable)prepare.Invoke(null,new object[]{new string[]{"--assistant"},args[0]});
    var info=(ProcessStartInfo)lease.GetType().GetField("Info",BindingFlags.Instance|BindingFlags.NonPublic).GetValue(lease);
    string fileName=info.FileName.StartsWith("\\\\?\\")?info.FileName.Substring(4):info.FileName;
    string working=info.WorkingDirectory.StartsWith("\\\\?\\")?info.WorkingDirectory.Substring(4):info.WorkingDirectory;
    bool writeBlocked=false, renameBlocked=false, newMemberBlocked=false, recheckRejected=false;
    try { using(var f=System.IO.File.Open(fileName,System.IO.FileMode.Open,System.IO.FileAccess.Write)){} }
    catch(System.IO.IOException){writeBlocked=true;}
    try { System.IO.Directory.Move(working,working+"-moved"); }
    catch(System.IO.IOException){renameBlocked=true;}
    var extra=working+"\\unlisted.dll";
    try { System.IO.File.WriteAllText(extra,"new member"); }
    catch(System.IO.IOException){newMemberBlocked=true;}
    try { lease.GetType().GetMethod("CheckMembers",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(lease,null); }
    catch(TargetInvocationException){recheckRejected=true;}
    lease.Dispose();
    using(var f=System.IO.File.Open(fileName,System.IO.FileMode.Open,System.IO.FileAccess.Write)){}
    Console.WriteLine(new JavaScriptSerializer().Serialize(new {writeBlocked,renameBlocked,newMemberBlocked,recheckRejected,released=true}));
    return 0;
   }
   var argv=new string[args.Length-1]; Array.Copy(args,1,argv,0,argv.Length);
   var method=type.GetMethod("ResolveStartInfo",BindingFlags.Static|BindingFlags.NonPublic|BindingFlags.Public);
   var p=(ProcessStartInfo)method.Invoke(null,new object[]{argv,args[0]});
   Console.WriteLine(new JavaScriptSerializer().Serialize(new { file=p.FileName, cwd=p.WorkingDirectory,
    args=p.Arguments, shell=p.UseShellExecute, noConsole=p.CreateNoWindow,
    project=p.EnvironmentVariables["VIBELUTION_WORKSPACE_ROOT"], python=p.EnvironmentVariables["PYTHON"] }));
   return 0;
  } catch(Exception e) { Console.WriteLine(e.InnerException==null?e.Message:e.InnerException.Message);return 1; }
 }
}
''', encoding="utf-8")
    compiler = Path(os.environ["SystemRoot"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    output = work / "Harness.exe"
    sources = [ENTRY, harness, *([HELPER] if HELPER.exists() else [])]
    result = subprocess.run([str(compiler), "/nologo", "/target:exe", "/main:ManagedHarness",
        "/reference:System.Windows.Forms.dll", "/reference:System.Drawing.dll",
        "/reference:System.Web.Extensions.dll", f"/out:{output}", *map(str, sources)],
        capture_output=True, text=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, result.stdout + result.stderr
    return output


def seed(root, *, extra_catalog=None, extra_active=None, duplicate_active=False):
    files = {"Vibelution.exe": b"MZ private test, never executed",
        "resources/app.asar": b"sealed-main",
        "resources/app.asar.unpacked/package-provenance.json": b'{"schemaVersion":1}',
        "resources/launcher-assistant/manifest.json": b'{"schemaVersion":1}',
        "resources/web-dist/ordinary asset.js": b"native fixture"}
    catalog = {"schemaVersion": 1, "files": [{"path": p, "size": len(b),
        "sha256": hashlib.sha256(b).hexdigest()} for p, b in sorted(files.items())]}
    if extra_catalog:
        extra_catalog(catalog)
    raw = json.dumps(catalog, ensure_ascii=False, separators=(",", ":")).encode()
    pid = hashlib.sha256(raw).hexdigest()
    package = root / "packages" / pid
    package.mkdir(parents=True)
    for path, value in files.items():
        target = package / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value)
    (package / "managed-package-catalog.json").write_bytes(raw)
    active = {"schemaVersion": 1, "protocolVersion": 1, "packageId": pid,
        "exeSha256": hashlib.sha256(files["Vibelution.exe"]).hexdigest(),
        "provenanceSha256": hashlib.sha256(files["resources/app.asar.unpacked/package-provenance.json"]).hexdigest()}
    active.update(extra_active or {})
    text = json.dumps(active)
    if duplicate_active:
        text = text.replace('{', '{"packageId":"' + "0" * 64 + '",', 1)
    (root / "active.json").write_text(text, encoding="utf-8")
    return package


def invoke(executable, root, *args):
    return subprocess.run([str(executable), str(root), *(args or ("--assistant",))],
        capture_output=True, text=True, encoding="utf-8", timeout=12,
        env={**os.environ, "VIBELUTION_WORKSPACE_ROOT": "poison-project", "PYTHON": "poison-python"},
        creationflags=subprocess.CREATE_NO_WINDOW)


def test_assistant_main_branch_precedes_any_project_parse():
    source = ENTRY.read_text(encoding="utf-8")
    assert source.index("ManagedDesktopAssistant.IsRequested(args)") < source.index("ParseArgs(args)")


def test_native_managed_start_requires_no_project_or_python(managed_native_harness, tmp_path):
    package = seed(tmp_path)
    result = invoke(managed_native_harness, tmp_path, "--assistant", "--hidden")
    assert result.returncode == 0, result.stdout
    info = json.loads(result.stdout)
    assert not info["file"].startswith("\\\\?\\")
    assert not info["cwd"].startswith("\\\\?\\")
    assert Path(info["file"]) == package / "Vibelution.exe"
    assert Path(info["cwd"]) == package
    assert info["args"] == "--assistant --hidden-presentation"
    assert info["shell"] is False and info["noConsole"] is True
    assert info["project"] is None and info["python"] is None


@pytest.mark.parametrize(("source", "public"), [
    (r"\\?\C:\installed\Vibelution.exe", r"C:\installed\Vibelution.exe"),
    (r"\\?\UNC\server\share\package", r"\\server\share\package"),
])
def test_startup_spelling_converts_only_validated_drive_or_unc(managed_native_harness, source, public):
    result = invoke(managed_native_harness, source, "public-spelling")
    assert result.returncode == 0, result.stdout
    assert result.stdout.strip() == public


@pytest.mark.parametrize("source", [r"C:\unverified", r"\\?\GLOBALROOT\Device\HarddiskVolume1", r"\\.\pipe\test", r"\\?\UNC\server"])
def test_startup_spelling_has_no_other_namespace_fallback(managed_native_harness, source):
    result = invoke(managed_native_harness, source, "public-spelling")
    assert result.returncode == 1 and "ASSISTANT_PACKAGE_UNAVAILABLE" in result.stdout


def test_public_spelling_reopen_cannot_accept_win32_trimming_alias(managed_native_harness, tmp_path):
    original = tmp_path / "ordinary"
    original.mkdir()
    alias = str(original) + ". "
    # Public Win32 spelling can trim this suffix and reach the ordinary folder;
    # it is not the exact canonical namespace object that was admitted.
    result = invoke(managed_native_harness, alias, "public-open", "\\\\?\\" + alias)
    assert result.returncode == 1 and "ASSISTANT_PACKAGE_UNAVAILABLE" in result.stdout


def test_native_managed_handles_long_payload_paths(managed_native_harness, tmp_path):
    relative = "resources/launcher-assistant/source/" + "/".join(["native-path-" + "a" * 35] * 6) + "/module.py"
    def add(c):
        c["files"].append({"path": relative, "size": 4, "sha256": hashlib.sha256(b"code").hexdigest()})
    package = seed(tmp_path, extra_catalog=add)
    target = package / relative
    extended = Path("\\\\?\\" + str(target))
    extended.parent.mkdir(parents=True)
    extended.write_bytes(b"code")
    result = invoke(managed_native_harness, tmp_path)
    assert result.returncode == 0, result.stdout


def test_python_publication_is_accepted_by_native_including_long_paths(managed_native_harness, managed_source_package, tmp_path):
    from core.launcher.managed_desktop_package import install_managed_desktop_package
    relative = "resources/web-dist/" + "/".join(["contract-" + "a" * 90] * 22) + "/asset.js"
    assert 2048 < len(relative) < 4096
    extended = Path("\\\\?\\" + str(managed_source_package / relative))
    extended.parent.mkdir(parents=True)
    extended.write_bytes(b"contract asset")
    managed = tmp_path / "native-install"
    active = install_managed_desktop_package(managed_source_package, managed_root=managed)
    result = invoke(managed_native_harness, managed)
    assert result.returncode == 0, result.stdout
    info = json.loads(result.stdout)
    assert active["packageId"] in info["file"] and info["args"] == "--assistant"


def test_python_does_not_activate_paths_native_counts_as_oversize(managed_native_harness, managed_source_package, tmp_path):
    from core.launcher.managed_desktop_package import install_managed_desktop_package
    managed = tmp_path / "native-install"
    install_managed_desktop_package(managed_source_package, managed_root=managed)
    before = (managed / "active.json").read_bytes()
    relative = "resources/web-dist/" + "/".join(["😀" * 100] * 23) + "/asset.js"
    assert len(relative) < 4096 < len(relative.encode("utf-16-le")) // 2
    extended = Path("\\\\?\\" + str(managed_source_package / relative))
    extended.parent.mkdir(parents=True)
    extended.write_bytes(b"not native portable")
    with pytest.raises(ValueError):
        install_managed_desktop_package(managed_source_package, managed_root=managed)
    assert (managed / "active.json").read_bytes() == before
    assert invoke(managed_native_harness, managed).returncode == 0


def test_final_native_open_rejects_ancestor_redirect_even_after_attribute_check(managed_native_harness, tmp_path):
    outside = tmp_path / "outside"
    (outside / "managed-desktop").mkdir(parents=True)
    link = tmp_path / "alias"
    setup = tmp_path / "junction.ps1"
    setup.write_text('param([string]$Link,[string]$Target)\nNew-Item -ItemType Junction -Path $Link -Target $Target -ErrorAction Stop | Out-Null\n', encoding="utf-8")
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-File", str(setup), str(link), str(outside)],
        capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW,
        env={**os.environ, "PSModulePath": str(powershell.parent / "Modules")})
    assert result.returncode == 0, result.stderr
    # Simulate the final Open after a prior attribute check has already passed:
    # final component is ordinary, only an ancestor now points outside.
    opened = invoke(managed_native_harness, link / "managed-desktop", "redirect-open")
    assert opened.returncode == 1 and "ASSISTANT_PACKAGE_UNAVAILABLE" in opened.stdout
    opened = invoke(managed_native_harness, link / "managed-desktop", "public-open", "\\\\?\\" + str(link / "managed-desktop"))
    assert opened.returncode == 1 and "ASSISTANT_PACKAGE_UNAVAILABLE" in opened.stdout


def test_verified_code_and_namespace_remain_guarded_until_handoff(managed_native_harness, tmp_path):
    seed(tmp_path)
    result = invoke(managed_native_harness, tmp_path, "hold")
    assert result.returncode == 0, result.stdout
    info = json.loads(result.stdout)
    assert info["writeBlocked"] and info["renameBlocked"] and info["released"]
    assert info["newMemberBlocked"] or info["recheckRejected"]


@pytest.mark.parametrize("path", ["CONIN$", "COM¹.txt", "a/../b", "a:b", "a\\b", "a\x7fb", "/root"])
def test_native_managed_rejects_windows_aliases_and_controls(managed_native_harness, tmp_path, path):
    package = seed(tmp_path, extra_catalog=lambda c: c["files"][0].update(path=path))
    result = invoke(managed_native_harness, tmp_path)
    assert result.returncode == 1 and "ASSISTANT_PACKAGE_UNAVAILABLE" in result.stdout


@pytest.mark.parametrize("flags", [("--assistant", "--project", "unrelated"),
    ("--assistant", "restart"), ("--assistant", "vibelution://open"),
    ("--assistant=true",), ("--assistant", "--assistant"), ("--assistant", "--config", "file")])
def test_native_assistant_rejects_mixed_arguments_before_file_reads(managed_native_harness, tmp_path, flags):
    result = invoke(managed_native_harness, tmp_path / "missing", *flags)
    assert result.returncode == 1 and "ASSISTANT_MODE_CONFLICT" in result.stdout


@pytest.mark.parametrize("fault", ["missing", "unknown", "protocol", "duplicate", "oversize",
    "catalog_hash", "file_hash", "extra_file", "missing_file", "path", "case_duplicate", "number", "active_path"])
def test_native_managed_admission_fails_closed(managed_native_harness, tmp_path, fault):
    catalog_change = None
    if fault == "path":
        catalog_change = lambda c: c["files"][0].update(path="../outside")
    if fault == "case_duplicate":
        catalog_change = lambda c: c["files"].append({**c["files"][0], "path": c["files"][0]["path"].upper()})
    if fault == "number":
        catalog_change = lambda c: c["files"][0].update(size=True)
    active = {"unknown": True} if fault == "unknown" else {"protocolVersion": 2} if fault == "protocol" else {"packageId": "../outside"} if fault == "active_path" else None
    package = seed(tmp_path, extra_catalog=catalog_change, extra_active=active, duplicate_active=fault == "duplicate")
    if fault == "missing": (tmp_path / "active.json").unlink()
    if fault == "oversize": (tmp_path / "active.json").write_bytes(b" " * (16 * 1024 + 1))
    if fault == "catalog_hash": (package / "managed-package-catalog.json").write_bytes(b"{}")
    if fault == "file_hash": (package / "resources/app.asar").write_bytes(b"changed")
    if fault == "extra_file": (package / "unlisted.dll").write_bytes(b"unlisted")
    if fault == "missing_file": (package / "resources/app.asar").unlink()
    result = invoke(managed_native_harness, tmp_path)
    assert result.returncode == 1 and "ASSISTANT_PACKAGE_UNAVAILABLE" in result.stdout


@pytest.mark.parametrize("changed_input", ["assistant", "build", "icon"])
def test_shortcut_cache_key_hashes_every_native_build_input(tmp_path, changed_input):
    if os.name != "nt":
        pytest.skip("Windows PowerShell cache function")
    source = (ROOT / "scripts/launch_vibelution_shortcut.ps1").read_text(encoding="utf-8")
    function = source.split("function Get-NativeEntryCacheKey {", 1)[1].split("$localAppData =", 1)[0]
    paths = {name: tmp_path / f"{name}.input" for name in ("source", "assistant", "build", "icon")}
    for name, path in paths.items():
        path.write_text(f"original {name}", encoding="utf-8")
    source_bytes = paths["source"].read_bytes()
    call = "Get-NativeEntryCacheKey " + " ".join(
        f"-{parameter} '{str(paths[name]).replace(chr(39), chr(39) * 2)}'"
        for parameter, name in (("SourcePath", "source"), ("AssistantSourcePath", "assistant"),
                                ("BuildScriptPath", "build"), ("IconPath", "icon"))
    )
    script = tmp_path / "cache-only.ps1"
    script.write_text('Set-StrictMode -Version Latest\n$ErrorActionPreference = "Stop"\n'
                      + "function Get-NativeEntryCacheKey {" + function + "\n" + call, encoding="utf-8")
    private = tmp_path / "private"
    private.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("VIBELUTION_")}
    env.update(USERPROFILE=str(private), HOME=str(private), LOCALAPPDATA=str(private))
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    env["PSModulePath"] = str(powershell.parent / "Modules")

    def key():
        result = subprocess.run([str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive",
                                 "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                                capture_output=True, text=True, timeout=15, env=env,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout.strip()

    before = key()
    paths[changed_input].write_text(f"changed {changed_input}", encoding="utf-8")
    after = key()
    assert before != after, f"{changed_input} must invalidate the native entry cache"
    combined = "|".join(hashlib.sha256(paths[name].read_bytes()).hexdigest().upper()
                        for name in ("source", "assistant", "build", "icon"))
    assert after == hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]
    assert key() == after
    assert paths["source"].read_bytes() == source_bytes
