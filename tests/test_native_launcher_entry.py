import os
import json
import shutil
import time
import re
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
NATIVE_ENTRY_SOURCE = PROJECT_ROOT / "scripts" / "windows_launcher_entry" / "VibelutionLauncher.cs"
NATIVE_ENTRY_BUILD_SCRIPT = PROJECT_ROOT / "scripts" / "windows_launcher_entry" / "build_vibelution_launcher_entry.ps1"


def _source() -> str:
    return NATIVE_ENTRY_SOURCE.read_text(encoding="utf-8")


def test_native_launch_budget_covers_start_settlement_retry_and_spawn():
    from scripts.vibelution_desktop_entry import (
        DEFAULT_START_LIFECYCLE_SETTLE_TIMEOUT_SECONDS,
        LAUNCH_SETTLEMENT_RETRY_TIMEOUT_SECONDS,
    )

    block = _source().split("private static void LaunchCurrentElectronMain", 1)[1].split(
        "private static bool HasArgument", 1
    )[0]
    budget = re.search(r'int bridgeTimeoutMs = startup \? (\d+) : (\d+);', block)
    assert budget is not None
    outer_seconds = int(budget.group(1)) / 1000
    assert outer_seconds >= (
        DEFAULT_START_LIFECYCLE_SETTLE_TIMEOUT_SECONDS + LAUNCH_SETTLEMENT_RETRY_TIMEOUT_SECONDS + 60
    )
    assert int(budget.group(2)) == 240000
    for operation in ("start", "restart", "rebuild-and-start"):
        assert f'string.Equals(thenLifecycle, "{operation}", StringComparison.OrdinalIgnoreCase)' in block
    bridge_source = (PROJECT_ROOT / "desktop/electron/src/process/pythonJsonBridge.ts").read_text(encoding="utf-8")
    registry_source = (PROJECT_ROOT / "desktop/electron/src/lifecycle/instanceRegistryStore.ts").read_text(encoding="utf-8")
    build_budget = re.search(r'PYTHON_JSON_BRIDGE_MAINTENANCE_TIMEOUT_MS = ([\d_]+)', bridge_source)
    ready_budget = re.search(r'ISOLATED_START_TIMEOUT_SECONDS = (\d+)', registry_source)
    assert build_budget and ready_budget
    assert DEFAULT_START_LIFECYCLE_SETTLE_TIMEOUT_SECONDS >= (
        int(build_budget.group(1).replace("_", "")) / 1000 + int(ready_budget.group(1)) + 30
    )


def test_native_launcher_default_action_runs_as_tray_app():
    source = _source()

    assert "NotifyIcon" in source
    assert "ContextMenuStrip" in source
    assert "Application.Run(new TrayApplicationContext(projectDir, parsed.FromShortcut))" in source
    assert "Global\\\\Vibelution.Launcher.Tray" in source
    assert "HandleSecondaryTrayLaunch(projectDir)" in source
    assert "EnsureFreshLauncherBackend(projectDir)" in source
    # Tray default action still launches Electron open through the shared shim;
    # the trailing false is hiddenPresentation (opt-in e2e flag, user opens show).
    assert "LaunchCurrentElectronMain(projectDir, \"open\", false, false)" in source
    assert "TryLaunchElectronAndWaitForTrayOwner(projectDir)" in source
    assert "RunPythonBridge(projectDir, \"bootstrap\", true, true)" in source


def test_native_launcher_starts_electron_before_last_resort_winforms_tray():
    source = _source()
    default_block = source.split("Application.Run(new TrayApplicationContext", 1)[0]
    assert "TryLaunchElectronAndWaitForTrayOwner" in default_block
    assert "native_action.winforms_last_resort" in source
    assert "watcher.Renamed" in source
    assert "ownerPollTimer" in source
    assert "IsDesktopShellOwnerFileName" in source
    assert "ExecutablesMatch" in source
    owns = source.split("private static bool ElectronOwnsDesktopTray", 1)[1].split(
        "private static int HandleSecondaryTrayLaunch", 1
    )[0]
    assert "createTimeMatches || ExecutablesMatch" in owns
    assert "> 2.0" not in owns


def test_native_launcher_secondary_shortcut_launch_refreshes_stale_backend_and_opens_console():
    source = _source()

    assert "native_action.secondary_launch" in source
    # Secondary shortcut still refreshes the backend via an Electron open launch
    # (HandleSecondaryTrayLaunch); trailing false = hiddenPresentation, user-initiated.
    assert "LaunchCurrentElectronMain(projectDir, \"open\", false, false)" in source
    assert "/api/launcher/freshness" in source
    assert "RunPythonBridge(projectDir, \"stop-launcher\", true, false)" in source
    assert "--from-shortcut" in source
    assert "parsed.FromShortcut" in source


def test_launch_vibelution_shortcut_script_builds_content_addressed_entry():
    source = (PROJECT_ROOT / "scripts" / "launch_vibelution_shortcut.ps1").read_text(encoding="utf-8")

    assert "entry-cache" in source
    assert "--from-shortcut" in source
    assert "build_vibelution_launcher_entry.ps1" in source
    assert "Start-Process" in source
    assert "WindowStyle Hidden" in source
    assert "Vibelution Launcher.lnk" in source
    assert "WScript.Shell" in source
    assert "WindowStyle = 7" in source
    assert "Repair-DesktopLauncherShortcut" in source


def test_native_launcher_last_resort_tray_defers_lifecycle_to_electron():
    source = _source()
    menu = source.split("private ContextMenuStrip BuildMenu", 1)[1].split(
        "private static ToolStripMenuItem DisabledMenuItem", 1
    )[0]

    assert 'menu.Items.Add(MenuItem("打开控制台"' in menu
    assert "Electron 控制面未接管" in menu
    assert 'menu.Items.Add(MenuItem("退出 Launcher"' in menu
    assert "BranchActionMenu" not in menu
    assert "QueueRestartLauncher" not in menu
    assert "QueueExitLauncher(true)" not in menu
    assert "/api/launcher/branch-instances" not in menu
    assert "/api/launcher/force-stop" not in menu
    assert "PostLauncher" not in menu
    assert "RunPythonBridge(projectDir, \"stop-launcher\", true, false)" in source


def test_native_launcher_last_resort_tray_bootstraps_electron_without_lifecycle_posts():
    source = _source()
    bootstrap_block = source.split("private void BootstrapLauncherBackend", 1)[1].split(
        "private void QueueOpenConsole", 1
    )[0]

    assert "ThreadPool.QueueUserWorkItem(delegate { BootstrapLauncherBackend(); });" in source
    # Last-resort tray bootstrap still launches Electron open (openWorkbench
    # false = no lifecycle post); trailing false = hiddenPresentation.
    assert 'LaunchCurrentElectronMain(projectDir, "open", false, false)' in bootstrap_block


def test_native_launcher_non_default_actions_use_console_free_control_api():
    source = _source()

    # Non-default actions still route through the native action dispatcher;
    # parsed.HiddenPresentation threads the opt-in e2e flag into it.
    assert "RunNativeAction(projectDir, parsed.ForwardedArgs, parsed.HiddenPresentation)" in source
    assert "RunPythonBridge(projectDir, \"bootstrap\", true, true)" in source
    assert '"/api/launcher/status"' in source
    assert 'PostLauncher("/api/launcher/force-stop")' not in source
    assert "launch-desktop-shell" in source
    assert "vibelution_desktop_entry.vbs" not in source
    assert "wscript.exe" not in source
    assert "RunLegacyScriptAction" not in source


def test_native_launcher_forwards_lifecycle_to_packaged_electron():
    source = _source()

    # The shim launches current checkout Electron main (packaged if current,
    # otherwise unpackaged) and never builds a Python :8765 control plane.
    # hiddenPresentation is the opt-in e2e flag threaded through the forward.
    assert "ForwardOrLaunchElectron(projectDir, action, forwardedArgs, hiddenPresentation)" in source
    assert "LaunchCurrentElectronMain" in source
    assert "launch-desktop-shell" in source
    assert "--open-workbench" in source
    assert "native_action.electron_forwarded" in source
    assert 'action != "force-stop"' in source
    assert 'action != "rebuild-and-start"' in source
    assert "No packaged Electron (development checkout)" not in source
    assert 'RunPythonBridge(projectDir, noBrowser ? "bootstrap" : "launcher"' not in source
    native_action_index = source.index("private static int RunNativeAction")
    forward_index = source.index("private static bool ForwardOrLaunchElectron")
    forward_block = source[native_action_index:forward_index]
    assert "Electron main owns lifecycle commands" in forward_block
    assert "native_action.bridge_failed" in forward_block


def test_native_launcher_forwards_bridge_exit_code_and_parent_console_message():
    source = _source()
    native_action_index = source.index("private static int RunNativeAction")
    forward_index = source.index("private static bool ForwardOrLaunchElectron")
    forward_block = source[native_action_index:forward_index]

    # The bridge settles lifecycle commands itself: rejection exits 3 with
    # lifecycleSettlement.message on stdout. The shim must forward that exit
    # code as its own process exit code (other non-zero codes collapse to 1)
    # instead of swallowing every failure into exit 1.
    assert "BridgeFailureException" in source
    assert "ExitCode" in source
    assert "throw new BridgeFailureException(" in source
    assert "BridgeFailureException" in forward_block
    assert "return 3" in forward_block
    assert "MapBridgeExitCode" in forward_block

    # Terminal-driven failures must explain themselves on the parent console:
    # attach the parent console (never create a new one), write the settlement
    # message, then detach.
    assert "AttachConsole(AttachParentProcess)" in source
    assert "GetStdHandle" in source
    assert "FreeConsole" in source
    assert "new UTF8Encoding(false)" in source
    assert "ExtractBridgeSettlementMessage" in source
    assert "lifecycleSettlement" in source
    # AllocConsole would pop a visible console window and violate the product
    # no-console red line.
    assert "AllocConsole" not in source


def test_native_launcher_failure_message_uses_codepage_independent_console_output():
    source = _source()

    # A chcp 936 (GBK) terminal renders UTF-8 bytes as mojibake, so the Chinese
    # settlement failure message must go through the wide-char console API
    # (WriteConsoleW), whose output the console renders regardless of the
    # active code page.
    assert "WriteConsoleW" in source
    assert "CharSet = System.Runtime.InteropServices.CharSet.Unicode" in source
    assert "TryWriteParentConsoleWideChar" in source
    assert "GetFileType" in source
    assert "FileTypeChar" in source

    report = source.split("private static void ReportBridgeFailureToParentConsole", 1)[1].split(
        "private static string ExtractBridgeSettlementMessage", 1
    )[0]
    # The attached-console path writes the failure message through the
    # wide-char helper first; the UTF-8 byte writer remains only as the
    # redirected-handle (file/pipe) fallback.
    assert "TryWriteParentConsoleWideChar(stdOutput," in report
    assert "请求未完成" in report
    assert report.index("TryWriteParentConsoleWideChar(stdOutput,") < report.index(
        "new UTF8Encoding(false)"
    )


def test_native_launcher_python_bridge_uses_no_console_outer_runtime():
    source = _source()
    bridge_source = source.split("private static void RunPythonBridge", maxsplit=1)[1].split(
        "private static string ResolvePython", maxsplit=1
    )[0]

    assert "string pythonPath = ResolvePython(shellRoot, useNoConsole: true);" in bridge_source
    assert 'Quote(ResolvePython(shellRoot, useNoConsole: false))' in bridge_source
    assert 'useNoConsole ? "pythonw.exe" : "python.exe"' in source
    assert 'string.Equals(action, "stop-launcher", StringComparison.OrdinalIgnoreCase)' in bridge_source
    assert 'string.Equals(action, "launch-desktop-shell", StringComparison.OrdinalIgnoreCase)' in bridge_source
    assert '--use-state-owned-backend-pid' in bridge_source
    assert 'arguments.Add("--workspace")' in bridge_source
    assert 'arguments.Add("--then-lifecycle")' in bridge_source
    assert 'arguments.Add("--open-workbench")' in bridge_source
    assert "? requestedRoot" in bridge_source
    assert ": shellRoot));" in bridge_source
    assert "WorkingDirectory = shellRoot" in bridge_source
    assert "Quote(projectDir)" not in bridge_source
    assert "process.StandardOutput.ReadToEnd()" not in bridge_source
    assert "process.BeginOutputReadLine();" in bridge_source
    assert "process.BeginErrorReadLine();" in bridge_source


def test_native_launcher_resolves_desktop_shell_workspace_from_worktrees():
    source = _source()
    assert "private static string ResolveDesktopShellWorkspace(string projectDir)" in source
    resolver = source.split("private static string ResolveDesktopShellWorkspace", 1)[1].split(
        "private static void LaunchCurrentElectronMain", 1
    )[0]
    assert 'string.Equals(parts[index], ".worktrees", StringComparison.OrdinalIgnoreCase)' in resolver
    assert "return string.Join(Path.DirectorySeparatorChar.ToString(), parts, 0, index);" in resolver
    assert "string requestedRoot = Path.GetFullPath(projectDir);" in source
    assert "string shellRoot = ResolveDesktopShellWorkspace(requestedRoot);" in source
    assert "? requestedRoot" in source
    assert 'string.Equals(action, "launch-desktop-shell", StringComparison.OrdinalIgnoreCase)' in source
    assert 'string.Equals(action, "stop-launcher", StringComparison.OrdinalIgnoreCase)' in source


def test_native_launcher_build_references_windows_forms_and_icon():
    build_script = NATIVE_ENTRY_BUILD_SCRIPT.read_text(encoding="utf-8")

    assert "/target:winexe" in build_script
    assert "/reference:System.Windows.Forms.dll" in build_script
    assert "/reference:System.Drawing.dll" in build_script
    assert "/win32icon:" in build_script
    assert "assets\\icons\\vibelution.ico" in build_script


def test_native_launcher_source_compiles_as_windows_executable(tmp_path: Path):
    if os.name != "nt":
        pytest.skip("The native Launcher is compiled only on Windows.")

    powershell = Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    output_path = tmp_path / "VibelutionLauncher.exe"
    result = subprocess.run(
        [
            str(powershell),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(NATIVE_ENTRY_BUILD_SCRIPT),
            "-ProjectDir",
            str(PROJECT_ROOT),
            "-OutputPath",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert output_path.is_file()


@pytest.fixture(scope="module")
def native_start_harness(tmp_path_factory):
    if os.name != "nt":
        pytest.skip("Windows native pipe admission and server identity")
    directory = tmp_path_factory.mktemp("native-start-harness")
    harness = directory / "Harness.cs"
    harness.write_text(r'''
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
internal static class NativeStartHarness {
 public static int Main(string[] args) {
  string root=args[0], mode=args[1];
  if (mode=="client-only") {
   try {
    var call=typeof(VibelutionLauncher).GetMethod("TryNativeStart",BindingFlags.NonPublic|BindingFlags.Static);
    Console.WriteLine((bool)call.Invoke(null,new object[]{root,5000})?"completed":"fallback");
   } catch(TargetInvocationException) {Console.WriteLine("rejected");}
   return 0;
  }
  if (!mode.StartsWith("pipe-")) {
   var target=VibelutionLauncher.ReadNativeStartTarget(root);
   if (target==null) { Console.WriteLine("fallback"); return 0; }
   var identity=new VibelutionLauncher.NativeProcessIdentity {CreateTime=mode=="pid-reused"?103:100,
    Executable=mode=="same-basename"?Path.Combine(root,"other","Vibelution.exe"):target.Executable};
   Console.WriteLine(VibelutionLauncher.NativeIdentityMatches(target,mode=="wrong-server"?99:42,identity)?"eligible":"fallback");
   return 0;
  }
  string metadata=args[2], pipeName="vibelution-native-start-"+Process.GetCurrentProcess().Id+"-"+Guid.NewGuid().ToString("N");
  var json=new JavaScriptSerializer();
  using (var self=Process.GetCurrentProcess())
  using (var server=new NamedPipeServerStream(pipeName,PipeDirection.InOut,1,PipeTransmissionMode.Byte,PipeOptions.Asynchronous)) {
   File.WriteAllText(metadata,json.Serialize(new Dictionary<string,object> {
    {"schemaVersion",1},{"protocolVersion",1},{"workspaceRoot",root},{"pipeName",pipeName},{"token",new string('a',64)},
    {"pid",self.Id},{"createTime",(self.StartTime.ToUniversalTime()-new DateTime(1970,1,1,0,0,0,DateTimeKind.Utc)).TotalSeconds},
    {"executable",self.MainModule.FileName}
   }));
   int received=0;
   var worker=new Thread(()=> {
    try {
     server.WaitForConnection();
     using (var reader=new StreamReader(server,new UTF8Encoding(false),false,1024,true))
     using (var writer=new StreamWriter(server,new UTF8Encoding(false),1024,true)) {
      var request=json.Deserialize<Dictionary<string,object>>(reader.ReadLine());
      Interlocked.Increment(ref received);
      if (mode=="pipe-disconnect") return;
      if (mode=="pipe-timeout") {Thread.Sleep(300);return;}
      var reply=new Dictionary<string,object> {
       {"schemaVersion",1},{"protocolVersion",1},{"workspaceRoot",root},
       {"requestId",mode=="pipe-wrong-request"?"launch_other":request["requestId"]},
       {"accepted",mode!="pipe-reject"&&mode!="pipe-explicit-fallback"},
       {"commandId",mode=="pipe-explicit-fallback"?"":"cmd_owned_request"},
       {"code",mode=="pipe-explicit-fallback"?"native_requires_legacy_launch":"started"},
       {"message","测试启动结算"},{"notDispatched",mode=="pipe-explicit-fallback"}
      };
      writer.WriteLine(json.Serialize(reply));writer.Flush();server.WaitForPipeDrain();
     }
    } catch(IOException) {} catch(ObjectDisposedException) {}
    finally {try {server.Disconnect();} catch {} }
   });
   worker.IsBackground=true;worker.Start();
   string verdict;
   try {
    var method=typeof(VibelutionLauncher).GetMethod("TryNativeStart",BindingFlags.NonPublic|BindingFlags.Static);
    verdict=(bool)method.Invoke(null,new object[]{root,mode=="pipe-timeout"?75:5000})?"completed":"fallback";
   } catch(TargetInvocationException error) {
    var field=error.InnerException.GetType().GetField("ExitCode");
    verdict="rejected:"+(field==null?"unknown":field.GetValue(error.InnerException).ToString());
   }
   worker.Join(1000);
   Console.WriteLine(verdict+"|received="+received);
  }
  return 0;
 }
}
''', encoding="utf-8")
    compiler = Path(os.environ["SystemRoot"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    executable = directory / "Harness.exe"
    result = subprocess.run(
        [str(compiler), "/nologo", "/target:exe", "/main:NativeStartHarness", "/reference:System.Windows.Forms.dll",
         "/reference:System.Drawing.dll", "/reference:System.Web.Extensions.dll", f"/out:{executable}",
         str(NATIVE_ENTRY_SOURCE), str(harness)], capture_output=True, text=True, timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return executable


def _seed_native_start(root, projects):
    digest = 2166136261
    for byte in str(root).lower().encode("utf-8"):
        digest = ((digest ^ byte) * 16777619) & 0xffffffff
    instance = f"{digest:08x}"

    def put(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value) if isinstance(value, dict) else value, encoding="utf-8")

    put(root / ".git/HEAD", "ref: refs/heads/main")
    put(root / ".vibelution/project.json", {"projectId": "test-project"})
    home = projects / "test-project/instances" / instance
    put(home / "storage-migration.json", {"schemaVersion": 1, "status": "completed", "projectId": "test-project", "instanceId": instance})
    metadata = home / "runtime/launcher/native-start-transport.json"
    record = {"schemaVersion": 1, "protocolVersion": 1, "workspaceRoot": str(root), "pid": 42, "createTime": 100,
              "executable": str(root / "dist/desktop/win-unpacked/Vibelution.exe"),
              "pipeName": "vibelution-native-start-42-" + "b" * 32, "token": "a" * 64}
    put(metadata, record)
    return metadata, record, put


@pytest.mark.parametrize("mode", [
    "eligible", "pid-reused", "wrong-server", "same-basename", "wrong-root", "unknown-protocol",
    "missing-identity", "unsafe-pipe", "missing-token", "old-shell", "malformed", "branch", "worktree",
    "wrong-migration", "oversized",
])
def test_native_start_metadata_and_connected_identity_fail_closed(native_start_harness, tmp_path, mode):
    root, projects = tmp_path / "project with spaces", tmp_path / "projects"
    metadata, record, put = _seed_native_start(root, projects)
    if mode == "wrong-root": record["workspaceRoot"] = str(tmp_path / "other")
    if mode == "unknown-protocol": record["protocolVersion"] = 2
    if mode == "missing-identity": record.pop("createTime")
    if mode == "unsafe-pipe": record["pipeName"] = r"\\remote\pipe\start"
    if mode == "missing-token": record.pop("token")
    put(metadata, "{" if mode == "malformed" else (" " * 8193 if mode == "oversized" else record))
    if mode == "old-shell": metadata.unlink()
    if mode == "branch": put(root / ".git/HEAD", "ref: refs/heads/codex/task")
    if mode == "worktree":
        (root / ".git/HEAD").unlink(); (root / ".git").rmdir(); put(root / ".git", "gitdir: elsewhere")
    if mode == "wrong-migration": put(metadata.parents[2] / "storage-migration.json", {"schemaVersion": 1, "status": "pending"})
    result = subprocess.run(
        [str(native_start_harness), str(root), mode], env={**os.environ, "VIBELUTION_PROJECTS_HOME": str(projects)},
        capture_output=True, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ("eligible" if mode == "eligible" else "fallback")


@pytest.mark.parametrize("mode,expected", [
    ("pipe-success", "completed"), ("pipe-reject", "rejected:3"), ("pipe-disconnect", "rejected:3"),
    ("pipe-timeout", "rejected:3"), ("pipe-wrong-request", "rejected:3"), ("pipe-explicit-fallback", "fallback"),
])
def test_native_start_uses_real_local_pipe_and_never_retries_unknown_outcomes(native_start_harness, tmp_path, mode, expected):
    root, projects = tmp_path / "project", tmp_path / "projects"
    metadata, _, _ = _seed_native_start(root, projects)
    executable = root / "dist/desktop/win-unpacked/Vibelution.exe"
    executable.parent.mkdir(parents=True)
    shutil.copy2(native_start_harness, executable)
    result = subprocess.run(
        [str(executable), str(root), mode, str(metadata)],
        env={**os.environ, "VIBELUTION_PROJECTS_HOME": str(projects)},
        capture_output=True, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"{expected}|received=1"


def test_native_start_marks_possible_delivery_before_writing_and_keeps_legacy_bridge():
    source = _source()
    forward = source.split("private static bool TryNativeStart", 1)[1].split("internal static int ValidateNativeStartResult", 1)[0]
    assert forward.index("mayHaveSent = true") < forward.index("pipe.BeginWrite")
    assert "if (!mayHaveSent) return false" in forward
    assert "GetNamedPipeServerProcessId" in forward
    assert '"launch-desktop-shell"' not in forward
    assert 'RunPythonBridge(projectDir, "launch-desktop-shell"' in source


def test_native_client_interoperates_with_the_real_node_transport(native_start_harness, tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node runtime unavailable")
    root, projects = tmp_path / "project", tmp_path / "projects"
    metadata, _, _ = _seed_native_start(root, projects)
    metadata.unlink()
    executable = root / "dist/desktop/win-unpacked/Vibelution.exe"
    executable.parent.mkdir(parents=True)
    try:
        os.link(node, executable)
    except OSError:
        shutil.copy2(node, executable)
    module = PROJECT_ROOT / "desktop/electron/src/process/nativeLauncherStart.ts"
    server_source = tmp_path / "server.mjs"
    calls_path = tmp_path / "calls.json"
    server_source.write_text(
        f"import {{startNativeLauncherStartTransport}} from {json.dumps(module.as_uri())};\n"
        "import {writeFileSync} from 'node:fs';\n"
        "let calls=0; const [root,runtime,callsPath]=process.argv.slice(2);\n"
        "const transport=await startNativeLauncherStartTransport({workspaceRoot:root,runtimeDir:runtime,"
        "identity:{pid:process.pid,createTime:Date.now()/1000-process.uptime(),executable:process.execPath},"
        "onStart:async()=>{writeFileSync(callsPath,JSON.stringify(++calls));"
        "return {schemaVersion:1,accepted:true,operation:'start',commandId:'cmd_node_interop',code:'started'};}});\n"
        "process.stdin.once('data',async()=>{await transport.close();process.exit(0);});\n",
        encoding="utf-8",
    )
    env = {**os.environ, "VIBELUTION_PROJECTS_HOME": str(projects)}
    server = subprocess.Popen(
        [str(executable), "--experimental-strip-types", str(server_source), str(root), str(metadata.parent), str(calls_path)],
        env=env, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        deadline = time.monotonic() + 10
        while not metadata.exists() and server.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        if not metadata.exists():
            if server.poll() is None:
                raise AssertionError("Native Node test transport did not publish")
            raise AssertionError(server.stderr.read().decode(errors="replace")[-2000:])
        result = subprocess.run(
            [str(native_start_harness), str(root), "client-only"], env=env,
            capture_output=True, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "completed"
        assert json.loads(calls_path.read_text()) == 1
    finally:
        if server.poll() is None:
            try:
                server.communicate(b"close\n", timeout=5)
            except subprocess.TimeoutExpired:
                server.terminate()
                server.communicate(timeout=5)
        server.wait(timeout=5)
    assert not metadata.exists()
