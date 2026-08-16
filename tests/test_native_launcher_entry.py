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
    assert "RunPythonBridge(projectDir, \"bootstrap\", true, true)" in source
    assert "RunPythonBridge(projectDir, \"launcher\", false, false)" in source


def test_native_launcher_secondary_shortcut_launch_refreshes_stale_backend_and_opens_console():
    source = _source()

    assert "native_action.secondary_launch" in source
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


def test_native_launcher_tray_menu_exposes_lifecycle_controls():
    source = _source()

    for label in [
        "打开控制台",
        "启动",
        "停止",
        "重启 Launcher",
        "退出 Launcher",
        "停止全部",
    ]:
        assert label in source

    assert "\"/api/launcher/branch-instances/\" + operation" in source
    assert "\"/api/launcher/force-stop\"" in source
    assert "PostLauncher(\"/api/launcher/force-stop\")" in source
    assert "重启当前 main" not in source
    assert "重建并启动（最新）" not in source
    assert 'menu.Items.Add(MenuItem("状态"' not in source
    assert "RunPythonBridge(projectDir, \"stop-launcher\", true, false)" in source


def test_native_launcher_non_default_actions_use_console_free_control_api():
    source = _source()

    assert "RunNativeAction(projectDir, parsed.ForwardedArgs)" in source
    assert "RunPythonBridge(projectDir, \"bootstrap\", true, true)" in source
    assert '"/api/launcher/status"' in source
    assert '"/api/launcher/" + effectiveAction' in source
    assert '"/api/launcher/force-stop"' in source
    assert "vibelution_desktop_entry.vbs" not in source
    assert "wscript.exe" not in source
    assert "RunLegacyScriptAction" not in source


def test_native_launcher_forwards_lifecycle_to_packaged_electron():
    source = _source()

    # The shim forwards argv to the packaged Electron shell and never builds a
    # second Python :8765 control plane when the Electron binary exists.
    assert "ForwardOrLaunchElectron(projectDir, action, forwardedArgs)" in source
    assert 'Path.Combine(projectDir, "dist", "desktop", "win-unpacked", "Vibelution.exe")' in source
    assert "native_action.electron_forwarded" in source
    assert "CreateNoWindow = true" in source
    assert 'action != "force-stop"' in source
    assert 'action != "rebuild-and-start"' in source
    # Legacy Python bridge remains only for development checkouts without the packaged Electron.
    forward_index = source.index("private static bool ForwardOrLaunchElectron")
    native_action_index = source.index("private static int RunNativeAction")
    forward_block = source[native_action_index:forward_index]
    assert "// T8:" in forward_block
    assert "No packaged Electron (development checkout)" in forward_block


def test_native_launcher_python_bridge_uses_no_console_outer_runtime():
    source = _source()
    bridge_source = source.split("private static void RunPythonBridge", maxsplit=1)[1].split(
        "private static string ResolvePython", maxsplit=1
    )[0]

    assert "string pythonPath = ResolvePython(projectDir, useNoConsole: true);" in bridge_source
    assert 'Quote(ResolvePython(projectDir, useNoConsole: false))' in bridge_source
    assert 'useNoConsole ? "pythonw.exe" : "python.exe"' in source


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
