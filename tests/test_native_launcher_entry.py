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
        "状态",
        "退出 Launcher",
        "停止全部",
    ]:
        assert label in source

    assert "\"/api/launcher/start\"" in source
    assert "\"/api/launcher/stop\"" in source
    assert "\"/api/launcher/restart\"" in source
    assert "\"/api/launcher/force-stop\"" in source
    assert "RunPythonBridge(projectDir, \"stop-launcher\", true, false)" in source


def test_native_launcher_non_default_actions_keep_hidden_vbs_fallback():
    source = _source()

    assert "RunLegacyScriptAction(projectDir, parsed.ForwardedArgs)" in source
    assert "wscript.exe" in source
    assert "vibelution_desktop_entry.vbs" in source
    assert "UseShellExecute = false" in source
    assert "CreateNoWindow = true" in source
    assert "WindowStyle = ProcessWindowStyle.Hidden" in source


def test_native_launcher_build_references_windows_forms_and_icon():
    build_script = NATIVE_ENTRY_BUILD_SCRIPT.read_text(encoding="utf-8")

    assert "/target:winexe" in build_script
    assert "/reference:System.Windows.Forms.dll" in build_script
    assert "/reference:System.Drawing.dll" in build_script
    assert "/win32icon:" in build_script
    assert "assets\\icons\\vibelution.ico" in build_script
