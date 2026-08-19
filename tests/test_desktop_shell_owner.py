from __future__ import annotations

import json
import os
from pathlib import Path

from vibelution_storage import resolve_project_storage_paths

from core.launcher.desktop_shell_owner import (
    OWNER_RELATIVE_PATH,
    canonical_desktop_shell_owner_path,
    clear_desktop_shell_owner,
    electron_owns_desktop_tray,
    read_desktop_shell_owner,
    should_show_winforms_tray,
    write_desktop_shell_owner,
)


def _seed_project(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "checkout"
    root.mkdir()
    identity = root / ".vibelution" / "project.json"
    identity.parent.mkdir()
    identity.write_text(
        json.dumps({"schemaVersion": 1, "projectId": "test-vibelution"}) + "\n",
        encoding="utf-8",
    )
    projects = tmp_path / "projects"
    monkeypatch.setenv("VIBELUTION_PROJECTS_HOME", str(projects))
    return root


def test_electron_owner_hides_winforms_tray(tmp_path: Path, monkeypatch) -> None:
    root = _seed_project(tmp_path, monkeypatch)
    record = write_desktop_shell_owner(root, owner="electron", pid=os.getpid())
    assert record is not None
    assert record["owner"] == "electron"
    assert "createTime" in record
    assert "updatedAt" in record
    assert electron_owns_desktop_tray(root) is True
    assert should_show_winforms_tray(root) is False
    canonical = canonical_desktop_shell_owner_path(root)
    assert canonical is not None
    assert canonical.is_file()
    assert not (root / OWNER_RELATIVE_PATH).exists()
    assert canonical == resolve_project_storage_paths(root).runtime / "launcher" / "desktop_shell_owner.json"


def test_dead_electron_pid_does_not_hide_winforms_tray(tmp_path: Path, monkeypatch) -> None:
    root = _seed_project(tmp_path, monkeypatch)
    write_desktop_shell_owner(root, owner="electron", pid=1_000_000_001)
    assert electron_owns_desktop_tray(root) is False
    assert should_show_winforms_tray(root) is True


def test_clear_only_removes_matching_full_identity(tmp_path: Path, monkeypatch) -> None:
    root = _seed_project(tmp_path, monkeypatch)
    write_desktop_shell_owner(root, owner="electron", pid=os.getpid())
    canonical = canonical_desktop_shell_owner_path(root)
    assert canonical is not None and canonical.is_file()
    clear_desktop_shell_owner(root, owner="electron", pid=999)
    assert canonical.is_file()
    clear_desktop_shell_owner(root, owner="electron", pid=os.getpid())
    assert not canonical.exists()


def test_checkout_owner_is_compat_read_only(tmp_path: Path, monkeypatch) -> None:
    root = _seed_project(tmp_path, monkeypatch)
    checkout = root / OWNER_RELATIVE_PATH
    checkout.parent.mkdir(parents=True)
    checkout.write_text(
        json.dumps({"schemaVersion": 1, "owner": "electron", "pid": os.getpid()}) + "\n",
        encoding="utf-8",
    )
    current = read_desktop_shell_owner(root)
    assert current is not None
    assert current["pid"] == os.getpid()
    written = write_desktop_shell_owner(root, owner="electron", pid=os.getpid())
    assert written is not None
    canonical = canonical_desktop_shell_owner_path(root)
    assert canonical is not None and canonical.is_file()
    assert checkout.is_file()
    assert json.loads(canonical.read_text(encoding="utf-8"))["pid"] == os.getpid()
    assert json.loads(canonical.read_text(encoding="utf-8")).get("updatedAt")


def test_winforms_and_electron_sources_share_one_resolver() -> None:
    cs = Path("scripts/windows_launcher_entry/VibelutionLauncher.cs").read_text(encoding="utf-8")
    ts = Path("desktop/electron/src/tray/desktopShellOwner.ts").read_text(encoding="utf-8")
    paths = Path("desktop/electron/src/lifecycle/projectStoragePaths.ts").read_text(encoding="utf-8")
    main = Path("desktop/electron/src/main.ts").read_text(encoding="utf-8")
    assert "desktop_shell_owner.json" in cs
    assert "ResolveCanonicalDesktopShellOwnerPath" in cs
    assert ".runtime" in cs
    assert "createTime" in cs
    assert "ElectronOwnsDesktopTray" in cs
    assert "resolveDesktopShellOwnerPaths" in ts
    assert "resolveDesktopShellOwnerPaths" in paths
    assert "claimElectronDesktopShellOwner" in main
    assert "releaseElectronDesktopShellOwner" in main
    assert 'File.WriteAllText(canonical' not in cs
