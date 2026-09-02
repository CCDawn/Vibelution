import os
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
NATIVE_ENTRY_SOURCE = PROJECT_ROOT / "scripts" / "windows_launcher_entry" / "VibelutionLauncher.cs"
NATIVE_ENTRY_BUILD_SCRIPT = PROJECT_ROOT / "scripts" / "windows_launcher_entry" / "build_vibelution_launcher_entry.ps1"


def _source() -> str:
    return NATIVE_ENTRY_SOURCE.read_text(encoding="utf-8")


def test_native_launcher_default_action_runs_as_tray_app():
    source = _source()

    assert "NotifyIcon" in source
    assert "ContextMenuStrip" in source
    assert "Application.Run(new TrayApplicationContext(projectDir, parsed.FromShortcut))" in source
    assert "Global\\\\Vibelution.Launcher.Tray" in source
    assert "HandleSecondaryTrayLaunch(projectDir)" in source
    assert "EnsureFreshLauncherBackend(projectDir)" in source
    assert "LaunchCurrentElectronMain(projectDir, \"open\", false)" in source
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
    assert "LaunchCurrentElectronMain(projectDir, \"open\", false)" in source
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
    assert 'LaunchCurrentElectronMain(projectDir, "open", false)' in bootstrap_block


def test_native_launcher_non_default_actions_use_console_free_control_api():
    source = _source()

    assert "RunNativeAction(projectDir, parsed.ForwardedArgs)" in source
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
    assert "ForwardOrLaunchElectron(projectDir, action, forwardedArgs)" in source
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
