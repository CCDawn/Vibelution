import json
from pathlib import Path

from core.runtime_manager import hot_restart_backup as backup


def test_stable_backup_prunes_to_three(monkeypatch, tmp_path: Path):
    project_root = tmp_path
    runtime_dir = tmp_path / ".runtime" / "runtime-manager"
    (project_root / "core").mkdir()
    (project_root / "core" / "demo.py").write_text("value = 1\n", encoding="utf-8")

    monkeypatch.setattr(backup, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(backup, "RUNTIME_MANAGER_DIR", runtime_dir)
    monkeypatch.setattr(backup, "HOT_RESTART_DIR", runtime_dir / "hot-restart")
    monkeypatch.setattr(backup, "STABLE_BACKUPS_DIR", runtime_dir / "hot-restart" / "stable-backups")
    monkeypatch.setattr(backup, "FAILURE_PACKAGES_DIR", runtime_dir / "hot-restart" / "failure-packages")
    monkeypatch.setattr(backup, "BACKUP_TARGETS", ("core",))
    monkeypatch.setattr(backup, "_run_git", lambda *_args, **_kwargs: "")

    ids = [backup.create_stable_backup(reason=f"r-{index}")["backupId"] for index in range(4)]
    backups = backup.list_stable_backups()

    assert len(backups) == 3
    assert ids[0] not in {item["backupId"] for item in backups}


def test_restore_stable_backup_preserves_runtime_data(monkeypatch, tmp_path: Path):
    project_root = tmp_path
    runtime_dir = tmp_path / ".runtime" / "runtime-manager"
    core_file = project_root / "core" / "demo.py"
    runtime_file = project_root / "workspace" / "chat" / "chat_state.json"
    core_file.parent.mkdir(parents=True)
    runtime_file.parent.mkdir(parents=True)
    core_file.write_text("value = 1\n", encoding="utf-8")
    runtime_file.write_text('{"conversation":"keep"}', encoding="utf-8")

    monkeypatch.setattr(backup, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(backup, "RUNTIME_MANAGER_DIR", runtime_dir)
    monkeypatch.setattr(backup, "HOT_RESTART_DIR", runtime_dir / "hot-restart")
    monkeypatch.setattr(backup, "STABLE_BACKUPS_DIR", runtime_dir / "hot-restart" / "stable-backups")
    monkeypatch.setattr(backup, "FAILURE_PACKAGES_DIR", runtime_dir / "hot-restart" / "failure-packages")
    monkeypatch.setattr(backup, "BACKUP_TARGETS", ("core",))
    monkeypatch.setattr(backup, "_run_git", lambda *_args, **_kwargs: "")

    stable = backup.create_stable_backup(reason="stable")
    core_file.write_text("value = 2\n", encoding="utf-8")
    runtime_file.write_text('{"conversation":"still-current"}', encoding="utf-8")

    restored = backup.restore_stable_backup(stable)

    assert restored["backupId"] == stable["backupId"]
    assert core_file.read_text(encoding="utf-8") == "value = 1\n"
    assert runtime_file.read_text(encoding="utf-8") == '{"conversation":"still-current"}'


def test_failure_package_records_manifest_and_diff(monkeypatch, tmp_path: Path):
    project_root = tmp_path
    runtime_dir = tmp_path / ".runtime" / "runtime-manager"
    changed_file = project_root / "core" / "demo.py"
    changed_file.parent.mkdir(parents=True)
    changed_file.write_text("broken = True\n", encoding="utf-8")

    monkeypatch.setattr(backup, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(backup, "RUNTIME_MANAGER_DIR", runtime_dir)
    monkeypatch.setattr(backup, "HOT_RESTART_DIR", runtime_dir / "hot-restart")
    monkeypatch.setattr(backup, "STABLE_BACKUPS_DIR", runtime_dir / "hot-restart" / "stable-backups")
    monkeypatch.setattr(backup, "FAILURE_PACKAGES_DIR", runtime_dir / "hot-restart" / "failure-packages")

    def fake_git(args, **_kwargs):
        if args == ["status", "--short"]:
            return " M core/demo.py"
        if args == ["diff", "--binary"]:
            return "diff --git a/core/demo.py b/core/demo.py\n+api_key = secret\n"
        return ""

    monkeypatch.setattr(backup, "_run_git", fake_git)

    package = backup.create_failure_package(
        reason="failed",
        command_id="cmd-1",
        session_id="session-a",
        run_id="turn-a",
        failure_stage="restart",
        error_type="Boom",
        error_message="startup failed",
    )

    manifest = json.loads(Path(package["gitStatusPath"]).with_name("manifest.json").read_text(encoding="utf-8"))
    assert manifest["sessionId"] == "session-a"
    assert manifest["changedFiles"] == ["core/demo.py"]
    assert Path(package["gitDiffPath"]).read_text(encoding="utf-8").startswith("diff --git")
    assert "api_key" not in Path(package["gitDiffPath"]).read_text(encoding="utf-8")
    assert "[REDACTED sensitive line]" in Path(package["gitDiffPath"]).read_text(encoding="utf-8")
