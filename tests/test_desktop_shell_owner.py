from __future__ import annotations

import json
import os
import pytest
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


@pytest.mark.parametrize("same_file,age_delta,expected", [(True, 0.2, "match"), (False, 0.2, "mismatch"), (True, 20.0, "mismatch")])
def test_owner_alias_requires_same_file_and_process_creation(tmp_path, monkeypatch, same_file, age_delta, expected):
    from core.launcher.desktop_shell_owner import _identity_status
    import core.runtime_manager.process_identity as identity
    actual = tmp_path / "electron.exe"
    actual.write_bytes(b"executable")
    alias = tmp_path / "linked-electron.exe"
    if same_file:
        alias.hardlink_to(actual)
    else:
        alias.write_bytes(b"different executable")
    record = {"pid": 123, "createTime": 100.0, "executable": str(alias)}
    monkeypatch.setattr(identity, "inspect_process_identity", lambda _: {"status": "mismatch", "reason": "executable_mismatch"})
    monkeypatch.setattr(identity, "capture_process_identity", lambda _: {"pid": 123, "createTime": 100.0 + age_delta, "executable": str(actual)})
    assert _identity_status(record) == expected


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
    assert not checkout.exists()
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
    # The tray factory lives in a function defined earlier; check runtime order
    # at each admission site instead of comparing unrelated source offsets.
    startup = main.split("if (runPrimaryWhenReady) {", 1)[1]
    assert startup.index("claimElectronDesktopShellOwner(paths.workspaceRoot)") < startup.index(
        "await ensureProjectControlPlane(workspaceRoot)"
    )
    admission = main.split("async function ensureProjectControlPlane", 1)[1].split(
        "async function bootstrapProjectControlPlane", 1
    )[0]
    assert admission.index("claimElectronDesktopShellOwner(deferredWorkspace)") < admission.index(
        "await bootstrapProjectControlPlane(paths"
    )
    assert 'File.WriteAllText(canonical' not in cs
