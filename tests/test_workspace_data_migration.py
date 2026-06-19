from pathlib import Path

from scripts import migrate_workspace_to_user_data as migration


def test_workspace_migration_dry_run_reports_source_and_target(tmp_path, monkeypatch):
    project = tmp_path / "project"
    source_workspace = project / "workspace"
    data_home = tmp_path / "operator-data"
    (source_workspace / "agents").mkdir(parents=True)
    (source_workspace / "agents" / "agents.json").write_text('{"agents":[]}\n', encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))

    report = migration.build_report(
        action="dry-run",
        source_workspace=source_workspace,
        target_workspace=data_home / "workspace",
        excludes=set(),
    )

    assert report["deletesProjectWorkspace"] is False
    assert report["totals"]["itemCount"] == 1
    assert report["items"][0]["relativePath"] == "agents"
    assert report["items"][0]["source"]["fileCount"] == 1
    assert report["items"][0]["targetExists"] is False


def test_workspace_migration_apply_copies_files_and_backs_up_target_conflicts(tmp_path, monkeypatch):
    project = tmp_path / "project"
    source_workspace = project / "workspace"
    data_home = tmp_path / "operator-data"
    target_workspace = data_home / "workspace"
    (source_workspace / "agents").mkdir(parents=True)
    (source_workspace / "agents" / "agents.json").write_text('{"agents":["new"]}\n', encoding="utf-8")
    (target_workspace / "agents").mkdir(parents=True)
    (target_workspace / "agents" / "agents.json").write_text('{"agents":["old"]}\n', encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))

    report = migration.build_report(
        action="apply",
        source_workspace=source_workspace,
        target_workspace=target_workspace,
        excludes=set(),
    )
    migration.apply_migration(report, data_home=str(data_home))
    verified = migration.verify_migration(report)

    assert verified["ok"] is True
    assert (target_workspace / "agents" / "agents.json").read_text(encoding="utf-8") == '{"agents":["new"]}\n'
    backup_files = list((data_home / "backups").glob("workspace-migration-*/workspace/agents/agents.json"))
    assert backup_files
    assert backup_files[0].read_text(encoding="utf-8") == '{"agents":["old"]}\n'


def test_workspace_migration_cli_apply_writes_manifest(tmp_path, monkeypatch):
    project = tmp_path / "project"
    source_workspace = project / "workspace"
    data_home = tmp_path / "operator-data"
    (source_workspace / "memory").mkdir(parents=True)
    (source_workspace / "memory" / "tasks.json").write_text('{"tasks":[1]}\n', encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))

    exit_code = migration.main(["apply", "--project-root", str(project), "--data-home", str(data_home)])

    assert exit_code == 0
    assert (data_home / "workspace" / "memory" / "tasks.json").exists()
    assert (data_home / "workspace" / "workspace_manifest.json").exists()


def test_workspace_migration_cli_finalize_target_writes_manifest_without_source_copy(tmp_path, monkeypatch):
    project = tmp_path / "project"
    source_workspace = project / "workspace"
    data_home = tmp_path / "operator-data"
    target_workspace = data_home / "workspace"
    (source_workspace / "agents").mkdir(parents=True)
    (source_workspace / "agents" / "agents.json").write_text('{"legacy":true}\n', encoding="utf-8")
    (target_workspace / "memory").mkdir(parents=True)
    (target_workspace / "memory" / "memory.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))

    exit_code = migration.main(["finalize-target", "--project-root", str(project), "--data-home", str(data_home)])

    assert exit_code == 0
    assert (target_workspace / "workspace_manifest.json").exists()
    assert not (target_workspace / "agents" / "agents.json").exists()


def test_workspace_migration_verify_reports_mismatch(tmp_path):
    source_workspace = tmp_path / "project" / "workspace"
    target_workspace = tmp_path / "operator-data" / "workspace"
    (source_workspace / "memory").mkdir(parents=True)
    (target_workspace / "memory").mkdir(parents=True)
    (source_workspace / "memory" / "tasks.json").write_text('{"tasks":[1]}\n', encoding="utf-8")
    (target_workspace / "memory" / "tasks.json").write_text('{"tasks":[]}\n', encoding="utf-8")
    report = migration.build_report(
        action="verify",
        source_workspace=source_workspace,
        target_workspace=target_workspace,
        excludes=set(),
    )

    verified = migration.verify_migration(report)

    assert verified["ok"] is False
    assert verified["mismatchCount"] == 1
    assert verified["mismatches"][0]["relativePath"] == "memory"
