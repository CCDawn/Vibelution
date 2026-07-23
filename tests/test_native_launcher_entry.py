from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent
NATIVE_ENTRY_SOURCE = PROJECT_ROOT / "scripts" / "windows_launcher_entry" / "VibelutionLauncher.cs"
NATIVE_ENTRY_BUILD_SCRIPT = PROJECT_ROOT / "scripts" / "windows_launcher_entry" / "build_vibelution_launcher_entry.ps1"


def _source() -> str:
    return NATIVE_ENTRY_SOURCE.read_text(encoding="utf-8")


def test_native_launcher_default_action_runs_as_tray_app():
    source = _source()

    assert "NotifyIcon" in source
    assert "ContextMenuStrip" in source
    assert "Application.Run(new TrayApplicationContext(projectDir))" in source
    assert "Global\\\\Vibelution.Launcher.Tray" in source
    assert "RunPythonBridge(projectDir, \"bootstrap\", true, true)" in source
    assert "RunPythonBridge(projectDir, \"launcher\", false, false)" in source


def test_native_launcher_tray_menu_exposes_lifecycle_controls():
    source = _source()

    for label in [
        "打开控制台",
        "启动项目",
        "停止项目",
        "重启项目",
        "重建并启动（最新）",
        "状态",
        "退出 Launcher",
        "停止全部",
    ]:
        assert label in source

    assert "\"/api/launcher/start\"" in source
    assert "\"/api/launcher/stop\"" in source
    assert "\"/api/launcher/restart\"" in source
    assert "\"/api/launcher/rebuild-and-start\"" in source
    assert "\"/api/launcher/force-stop\"" in source
    assert "QueueRebuildAndStart" in source
    assert "RunPythonBridge(projectDir, \"stop-launcher\", true, false)" in source


def test_native_launcher_non_default_actions_use_console_free_control_api():
    source = _source()

    assert "RunNativeAction(projectDir, parsed.ForwardedArgs)" in source
    assert "RunPythonBridge(projectDir, \"bootstrap\", true, true)" in source
    assert '"/api/launcher/status"' in source
    assert '"/api/launcher/start"' in source
    assert '"/api/launcher/stop"' in source
    assert '"/api/launcher/restart"' in source
    assert "vibelution_desktop_entry.vbs" not in source
    assert "wscript.exe" not in source
    assert "RunLegacyScriptAction" not in source


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
