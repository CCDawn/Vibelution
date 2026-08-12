from __future__ import annotations

import os
from pathlib import Path

from core.launcher.desktop_shell_owner import (
    OWNER_RELATIVE_PATH,
    clear_desktop_shell_owner,
    electron_owns_desktop_tray,
    should_show_winforms_tray,
    write_desktop_shell_owner,
)


def test_electron_owner_hides_winforms_tray(tmp_path: Path) -> None:
    write_desktop_shell_owner(tmp_path, owner="electron", pid=os.getpid())
    assert electron_owns_desktop_tray(tmp_path) is True
    assert should_show_winforms_tray(tmp_path) is False
    assert (tmp_path / OWNER_RELATIVE_PATH).is_file()


def test_dead_electron_pid_does_not_hide_winforms_tray(tmp_path: Path) -> None:
    write_desktop_shell_owner(tmp_path, owner="electron", pid=1_000_000_001)
    assert electron_owns_desktop_tray(tmp_path) is False
    assert should_show_winforms_tray(tmp_path) is True


def test_clear_only_removes_matching_owner(tmp_path: Path) -> None:
    write_desktop_shell_owner(tmp_path, owner="electron", pid=os.getpid())
    clear_desktop_shell_owner(tmp_path, owner="electron", pid=999)
    assert (tmp_path / OWNER_RELATIVE_PATH).is_file()
    clear_desktop_shell_owner(tmp_path, owner="electron", pid=os.getpid())
    assert not (tmp_path / OWNER_RELATIVE_PATH).exists()


def test_winforms_and_electron_sources_share_owner_file_name() -> None:
    cs = Path("scripts/windows_launcher_entry/VibelutionLauncher.cs").read_text(encoding="utf-8")
    ts = Path("desktop/electron/src/tray/desktopShellOwner.ts").read_text(encoding="utf-8")
    main = Path("desktop/electron/src/main.ts").read_text(encoding="utf-8")
    assert "desktop_shell_owner.json" in cs
    assert "ElectronOwnsDesktopTray" in cs
    assert "desktop_shell_owner.json" in ts
    assert "claimElectronDesktopShellOwner" in main
    assert "releaseElectronDesktopShellOwner" in main
