"""Launcher/PowerShell/desktop-entry source contract tests (parallel-safe)."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
LAUNCHER_SCRIPT = PROJECT_ROOT / "scripts" / "vibelution_launcher.ps1"
DESKTOP_ENTRY_SCRIPT = PROJECT_ROOT / "scripts" / "vibelution_desktop_entry.ps1"
DESKTOP_ENTRY_VBS = PROJECT_ROOT / "scripts" / "vibelution_desktop_entry.vbs"
DESKTOP_ENTRY_PY = PROJECT_ROOT / "scripts" / "vibelution_desktop_entry.py"
NATIVE_ENTRY_SOURCE = PROJECT_ROOT / "scripts" / "windows_launcher_entry" / "VibelutionLauncher.cs"
NATIVE_ENTRY_BUILD_SCRIPT = PROJECT_ROOT / "scripts" / "windows_launcher_entry" / "build_vibelution_launcher_entry.ps1"
PYTHON_LAUNCHER_SCRIPT = PROJECT_ROOT / "scripts" / "vibelution_launcher.py"
WORKBENCH_CLOSE_CANARY_SCRIPT = PROJECT_ROOT / "scripts" / "verify_desktop_workbench_close.ps1"

def test_launcher_script_repairs_start_menu_shortcut_entry():
    source = LAUNCHER_SCRIPT.read_text(encoding="utf-8")

    assert '"repair-shortcut"' in source
    assert "function Repair-LauncherShortcut" in source
    assert "function Resolve-PackagedElectronDesktopEntryPath" in source
    assert "function Set-LauncherShellShortcut" in source
    assert "launch_vibelution_shortcut.ps1" in source
    assert "Vibelution.lnk" in source
    assert "Vibelution Launcher.lnk" in source
    assert "scripts\\desktop_entry_catalog.ps1" in source
    assert "Resolve-DesktopPublicEntryPath" in source
    assert "Run scripts\\build_desktop_package.ps1" in source
    assert "assets\\icons\\vibelution.ico" in source
    assert "CreateShortcut" in source
    assert "$shortcut.TargetPath = $TargetPath" in source
    assert '$shortcutArguments = (\'--workspace "{0}"\' -f $projectDir)' in source
    assert '$shortcutMode = "electron_package"' in source
    assert '$shortcutMode = "native_shortcut_bootstrap"' in source
    assert "$shortcut.IconLocation" in source

    repair_start = source.index("function Repair-LauncherShortcut")
    repair_end = source.index("function Repair-StaleLauncherControlState")
    repair_source = source[repair_start:repair_end]
    assert "Resolve-PackagedElectronDesktopEntryPath" in repair_source
    assert "launch_vibelution_shortcut.ps1" in repair_source
    assert "native_shortcut_bootstrap" in repair_source
    assert "Ensure-NativeLauncherEntryExecutable" not in repair_source
    assert "vibelution_desktop_entry.vbs" not in repair_source

    launcher_action_start = source.rindex('        "launcher" {')
    launcher_action_end = source.index('        "toggle" {', launcher_action_start)
    launcher_action = source[launcher_action_start:launcher_action_end]
    assert "Repair-LauncherShortcut" not in launcher_action

def test_workbench_close_canary_quiesces_managed_workbench_before_packaged_run():
    source = WORKBENCH_CLOSE_CANARY_SCRIPT.read_text(encoding="utf-8")

    assert "function Close-ManagedWorkbenchForCanary" in source
    assert '"stop"' in source
    assert 'overallState -eq "closed"' in source
    assert 'observedState -eq "closed"' in source
    assert "$RecoveryRequired.Value = $true" in source

    active_work_check_index = source.index("$activeWorkCountBeforeCanary = Assert-NoActiveWorkbenchWork")
    quiesce_index = source.index("$managedWorkbenchState = Close-ManagedWorkbenchForCanary -RecoveryRequired")
    package_verify_index = source.index("if (-not $SkipPackageVerification)")
    package_start_index = source.index("Start-Process -FilePath $desktopExe")
    assert active_work_check_index < package_verify_index < quiesce_index < package_start_index

def test_workbench_close_canary_normalizes_empty_owned_process_cleanup_collection():
    source = WORKBENCH_CLOSE_CANARY_SCRIPT.read_text(encoding="utf-8")
    cleanup_block = source[source.index("} finally {") :]

    assert "$remainingOwnedProcessIds = @(\n        @(\n" in cleanup_block
    assert "if ($remainingOwnedProcessIds.Count -gt 0)" in cleanup_block

def test_workbench_close_canary_uses_unique_foreground_window_when_titles_collide():
    source = WORKBENCH_CLOSE_CANARY_SCRIPT.read_text(encoding="utf-8")

    assert "GetForegroundWindow" in source
    assert "$foregroundWindowHandle = [Vibelution.DesktopCanary.NativeWindowApi]::GetForegroundWindow()" in source
    assert "IsForeground = ($Handle -eq $foregroundWindowHandle)" in source
    assert "$foregroundMatches = @($matches | Where-Object { $_.IsForeground })" in source
    assert "if ($foregroundMatches.Count -eq 1)" in source
    assert "return $foregroundMatches[0]" in source

def test_workbench_close_canary_bootstraps_control_after_package_smoke_shutdown():
    source = WORKBENCH_CLOSE_CANARY_SCRIPT.read_text(encoding="utf-8")

    assert "function Ensure-LauncherControlForCanary" in source
    assert '"open", "--no-browser"' in source
    assert "$launcherBootstrapProcess = Start-Process" in source
    assert "$null = Ensure-LauncherControlForCanary" in source

    active_work_check_index = source.index("$activeWorkCountBeforeCanary = Assert-NoActiveWorkbenchWork")
    package_verify_index = source.index("if (-not $SkipPackageVerification)")
    control_bootstrap_index = source.rindex("$null = Ensure-LauncherControlForCanary")
    quiesce_index = source.index("$managedWorkbenchState = Close-ManagedWorkbenchForCanary -RecoveryRequired")
    assert active_work_check_index < package_verify_index < control_bootstrap_index < quiesce_index

def test_workbench_close_canary_uses_bounded_launcher_status_polling():
    source = WORKBENCH_CLOSE_CANARY_SCRIPT.read_text(encoding="utf-8")

    assert "-PassThru -Wait" not in source
    assert "$launcherBootstrapProcess = Start-Process" in source
    assert "$launcherProcess = Start-Process" in source
    assert "if ($launcherBootstrapProcess.HasExited -and $launcherBootstrapProcess.ExitCode -ne 0)" in source
    assert "if ($launcherProcess.HasExited -and $launcherProcess.ExitCode -ne 0)" in source
    assert 'throw "Managed Workbench did not close before the packaged Workbench-close canary. Last failure: $lastFailure"' in source
    assert 'throw "Workbench-close canary did not restore the managed Workbench. Last failure: $lastFailure"' in source

def test_workbench_close_canary_repolls_state_without_restarting_during_stop():
    source = WORKBENCH_CLOSE_CANARY_SCRIPT.read_text(encoding="utf-8")
    close_function = source[
        source.index("function Close-ManagedWorkbenchForCanary") : source.index(
            "function Wait-ForDesktopRootProcess"
        )
    ]

    assert "$latestLauncherState = Get-Content -LiteralPath $launcherStatePath -Raw | ConvertFrom-Json" in close_function
    assert "$latestLauncherOrigin = ([uri]$latestLauncherControlUrl).GetLeftPart([System.UriPartial]::Authority)" in close_function
    assert "Ensure-LauncherControlForCanary" not in close_function
    assert "$deadline = (Get-Date).AddSeconds($StartTimeoutSeconds)" in close_function

def test_workbench_close_canary_restores_control_before_active_work_gate():
    source = WORKBENCH_CLOSE_CANARY_SCRIPT.read_text(encoding="utf-8")
    active_work_function = source[
        source.index("function Assert-NoActiveWorkbenchWork") : source.index(
            "function Ensure-LauncherControlForCanary"
        )
    ]

    assert "$null = Ensure-LauncherControlForCanary" in active_work_function
    assert active_work_function.index("$null = Ensure-LauncherControlForCanary") < active_work_function.index(
        "Invoke-RestMethod -Uri \"$launcherOrigin/api/launcher/status\""
    )

def test_launcher_script_is_utf8_with_bom_for_windows_powershell_compatibility():
    assert LAUNCHER_SCRIPT.read_bytes().startswith(b"\xef\xbb\xbf")

def test_launcher_ci_verifies_package_lock_stays_in_sync():
    source = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "Verify package lock is in sync" in source
    assert "npm --silent install --package-lock-only --ignore-scripts --no-audit --no-fund" in source
    assert "git diff --exit-code -- package-lock.json" in source

def test_launcher_native_entry_source_and_build_contract():
    source = NATIVE_ENTRY_SOURCE.read_text(encoding="utf-8")
    build_script = NATIVE_ENTRY_BUILD_SCRIPT.read_text(encoding="utf-8")

    assert "ProcessStartInfo" in source
    assert "UseShellExecute = false" in source
    assert "CreateNoWindow = true" in source
    assert "WindowStyle = ProcessWindowStyle.Hidden" in source
    assert "RunNativeAction(projectDir, parsed.ForwardedArgs)" in source
    assert '"X-Vibelution-Launcher-Trigger"' in source
    assert "wscript.exe" not in source
    assert "vibelution_desktop_entry.vbs" not in source
    assert "--project" in source
    assert "native-launcher-entry.log" in source

    assert "/target:winexe" in build_script
    assert "/win32icon:" in build_script
    assert "VibelutionLauncher.exe" in build_script
    assert "assets\\icons\\vibelution.ico" in build_script
    assert "Microsoft.NET\\Framework64\\v4.0.30319\\csc.exe" in build_script

def test_managed_edge_windows_apply_vibelution_app_identity():
    source = LAUNCHER_SCRIPT.read_text(encoding="utf-8")

    assert "SHGetPropertyStoreForWindow" in source
    assert "SetWindowAppUserModelIdentity" in source
    assert "SetWindowIcon" in source
    assert "WM_SETICON" in source
    assert "function Set-ManagedBrowserWindowAppIdentity" in source
    assert "Set-ManagedBrowserWindowAppIdentity -WindowProcess $windowProcess -WindowPurpose $WindowPurpose" in source
    assert "Vibelution.Launcher" in source
    assert "Vibelution.Workbench" in source
    assert "assets\\icons\\vibelution.ico" in source
    assert "launcher.browser.window_app_identity.succeeded" in source
    assert "app_identity_applied" in source
    assert "window_icon_applied" in source

def test_ps_launcher_python_deps_stamp_aligns_with_content_hash():
    """PS and Python must share python-deps.stamp format to avoid pip on every restart."""
    ps_source = (PROJECT_ROOT / "scripts" / "vibelution_launcher.ps1").read_text(encoding="utf-8")
    py_source = (PROJECT_ROOT / "scripts" / "vibelution_launcher.py").read_text(encoding="utf-8")

    assert "function Get-RequirementsContentFingerprint" in ps_source
    assert "function Test-PythonDepsStampCurrent" in ps_source
    assert "Content-only SHA256 of requirements.txt" in ps_source
    assert "must match Python" in ps_source
    assert "_requirements_fingerprint" in py_source
    assert "_runtime_core_imports_available" in py_source
    assert "stamp already matches" in py_source
    assert "workbench.open.timings" in py_source

def test_python_launcher_workbench_window_applies_vibelution_app_identity():
    source = (PROJECT_ROOT / "scripts" / "vibelution_launcher.py").read_text(encoding="utf-8")

    assert "SHGetPropertyStoreForWindow" in source
    assert "PKEY_APPUSERMODEL_ID" in source
    assert "Vibelution.Workbench" in source
    assert "LAUNCHER_ICON_PATH" in source
    assert "WM_SETICON" in source
    assert "_apply_window_icon(int(hwnd), LAUNCHER_ICON_PATH)" in source
    assert "_apply_managed_browser_app_identity(" in source
    assert "start_named_workbench_browser" in source
    assert "display_name=display_name" in source
    assert "browserAppIdentityApplied" in source
    assert "browserWindowIconApplied" in source

def test_python_launcher_icon_binding_requires_exact_browser_process_window():
    launcher_source = (PROJECT_ROOT / "scripts" / "vibelution_launcher.py").read_text(encoding="utf-8")
    desktop_source = DESKTOP_ENTRY_PY.read_text(encoding="utf-8")

    for source in (launcher_source, desktop_source):
        assert "_visible_windows_for_process(int(browser_pid))" in source
        assert "_visible_vibelution_windows" not in source
        assert "or _visible_vibelution_windows()" not in source

def test_desktop_entry_launcher_window_applies_vibelution_app_identity():
    source = DESKTOP_ENTRY_PY.read_text(encoding="utf-8")

    assert "SHGetPropertyStoreForWindow" in source
    assert "PKEY_APPUSERMODEL_ID" in source
    assert "Vibelution.Launcher" in source
    assert "LAUNCHER_ICON_PATH" in source
    assert "WM_SETICON" in source
    assert "_apply_window_icon(hwnd, LAUNCHER_ICON_PATH)" in source
    assert "_apply_managed_browser_app_identity(int(process.pid), \"launcher\")" in source
    assert "launcher.browser.window_app_identity.succeeded" in source

def test_launcher_script_reconciles_stale_control_state_before_lifecycle_actions():
    source = LAUNCHER_SCRIPT.read_text(encoding="utf-8")

    assert "function Repair-StaleLauncherControlState" in source
    assert source.count("[void](Repair-StaleLauncherControlState)") >= 2
    assert "launcher.control_state.stale_reconciled" in source
    assert '$payload["launcherBackendPid"] = 0' in source
    assert '$payload["launcherBackendLaunchPid"] = 0' in source
    assert '$payload["launcherBrowserWindowPid"] = 0' in source
    assert '$payload["lastReason"] = "stale_launcher_control_reconciled"' in source
    assert "Remove-State" in source
    assert "Test-LauncherControlHealthy" in source

def test_launcher_reads_optional_supervisor_pid_with_strict_safe_helper():
    source = LAUNCHER_SCRIPT.read_text(encoding="utf-8")

    assert '$stateSupervisorPid = [int](Get-ObjectPropertyValue -Object $state -Name "supervisorPid" -Default 0)' in source
    assert '$snapshotSupervisorPid = [int](Get-ObjectPropertyValue -Object $snapshot.State -Name "supervisorPid" -Default 0)' in source
    assert "$state.supervisorPid" not in source
    assert "$snapshot.State.supervisorPid" not in source

def test_launcher_reads_optional_runtime_scene_status_fields_with_strict_safe_helper():
    source = LAUNCHER_SCRIPT.read_text(encoding="utf-8")

    assert "function Set-RuntimeSceneContextFromStateObject" in source
    assert '$sceneId = [string](Get-ObjectPropertyValue -Object $snapshot.State -Name "runtimeSceneId" -Default "")' in source
    assert '$backendStdout = [string](Get-ObjectPropertyValue -Object $snapshot.State -Name "backendStdout" -Default "")' in source
    assert '$backendStderr = [string](Get-ObjectPropertyValue -Object $snapshot.State -Name "backendStderr" -Default "")' in source
    assert "$state.runtimeSceneId" not in source
    assert "$payload.runtimeSceneId" not in source
    assert "$snapshot.State.runtimeSceneId" not in source
    assert "$Snapshot.State.runtimeSceneId" not in source
    assert "$snapshot.State.backendStdout" not in source
    assert "$snapshot.State.backendStderr" not in source

def test_desktop_entry_python_bridge_does_not_shell_out_to_powershell():
    source = DESKTOP_ENTRY_PY.read_text(encoding="utf-8").lower()

    assert "powershell.exe" not in source
    assert "vibelution_launcher.ps1" not in source
    assert '"core/launcher/developer_mode.py"' in source

def test_vbs_desktop_entry_uses_wmi_hidden_process_creation():
    source = DESKTOP_ENTRY_VBS.read_text(encoding="utf-8")

    assert "Win32_ProcessStartup" in source
    assert "startup.ShowWindow = 0" in source
    assert "startup.CreateFlags = 134218240" in source
    assert "BuildPowerShellEntryCommand()" in source
    assert "BuildPythonLauncherBridgeCommand()" in source
    assert "IsLauncherOnlyAction(action)" in source
    assert "VIBELUTION_DESKTOP_ENTRY_VBS_RUN_ID" in source
    assert "VIBELUTION_PYTHON_EXE" in source
    assert "processClass.Create(commandLine, workingDirectory, startup, createdPid)" in source
    assert "shell.Run(command, 0, False)" not in source
