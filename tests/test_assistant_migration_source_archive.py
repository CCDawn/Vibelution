"""Custom data copies are immutable sources, never runnable or active state."""
import json

import pytest

from core.assistant_runtime.migration_io import MigrationIOError
from core.assistant_runtime.migration_paths import resolve_source_paths, source_snapshot
from core.assistant_runtime.migration_source_archive import import_source_snapshots as _import_source_snapshots


def import_source_snapshots(*args, **kwargs):
    kwargs.setdefault("authority_verify", lambda: None)
    return _import_source_snapshots(*args, **kwargs)


def source(tmp_path):
    project, workspace, external = tmp_path / "project", tmp_path / "project/workspace", tmp_path / "custom-memory"
    workspace.mkdir(parents=True)
    external.mkdir()
    (external / "original.jsonl").write_bytes(b'{"text":"PRIVATE_MEMORY"}\n')
    outbox = workspace / "agents/pa/outbox"
    outbox.mkdir(parents=True)
    (outbox / "queue.json").write_bytes(b'{"runnable":true}')
    row = {"agentId": "pa", "directSessionId": "direct", "roleKey": "personal_assistant", "status": "active",
           "metadata": {"personalAssistantProfile": "personal_assistant_v1"},
           "memoryPolicy": {"privateMemoryRoot": str(external)}}
    grants = {"schemaVersion": 1, "sourceScope": {"projectId": "p", "instanceId": "i", "agentId": "pa"},
              "grants": [{"category": "memory", "root": str(external), "revision": 1}]}
    resolved = resolve_source_paths(project_root=project, workspace=workspace, project_id="p", instance_id="i",
                                    agent_row=row, grants=grants)
    return project, workspace, external, source_snapshot(resolved)


def test_approved_custom_data_import_is_exact_idempotent_and_not_executable(tmp_path):
    project, workspace, external, snapshots = source(tmp_path)
    before = {p: p.read_bytes() for root in (project, external) for p in root.rglob("*") if p.is_file()}
    target = tmp_path / "target"
    first = import_source_snapshots(snapshots, target, "migration-1", source_roots=(project, workspace))
    assert first["published"] and not first["readyForCutover"]
    second = import_source_snapshots(snapshots, target, "migration-1", source_roots=(project, workspace))
    assert second["reused"]
    manifest_path = target / "history_sources/migrations/migration-1/manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    assert manifest["schemaVersion"] == 2
    assert (manifest_path.parent / ".confirmed").is_dir()
    assert manifest["activePluginStateImported"] is False
    assert {entry["category"] for entry in manifest["entries"]} == {"memory"}
    assert all("queue" not in p.name for p in target.rglob("*"))
    copied = manifest_path.parent / manifest["entries"][0]["path"]
    assert copied.read_bytes() == (external / "original.jsonl").read_bytes()
    assert before == {p: p.read_bytes() for root in (project, external) for p in root.rglob("*") if p.is_file()}
    assert not list(target.rglob("*.sqlite3"))


def test_custom_data_source_change_refuses_before_target_write(tmp_path):
    project, workspace, external, snapshots = source(tmp_path)
    (external / "original.jsonl").write_bytes(b"changed")
    target = tmp_path / "target"
    with pytest.raises(MigrationIOError):
        import_source_snapshots(snapshots, target, "migration-1", source_roots=(project, workspace))
    assert not target.exists()


def test_source_target_alias_cannot_write_into_source(tmp_path):
    project, workspace, _, snapshots = source(tmp_path)
    staging = project / "staging"
    staging.mkdir()
    before = set(project.rglob("*"))
    with pytest.raises(MigrationIOError):
        import_source_snapshots(snapshots, staging / ".." / "workspace", "migration-1",
                                source_roots=(project, workspace))
    assert set(project.rglob("*")) == before


@pytest.mark.parametrize("published", [False, True])
def test_unlisted_target_file_is_never_published_or_reused(tmp_path, published):
    project, workspace, _, snapshots = source(tmp_path)
    target = tmp_path / "target"
    if published:
        import_source_snapshots(snapshots, target, "migration-1", source_roots=(project, workspace))
    directory = target / "history_sources/migrations" / ("migration-1" if published else ".pending-migration-1")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "extra.bin").write_bytes(b"unlisted")
    with pytest.raises(MigrationIOError):
        import_source_snapshots(snapshots, target, "migration-1", source_roots=(project, workspace))
    if not published:
        assert not (directory.parent / "migration-1").exists()


def test_leaf_mutation_at_publish_never_returns_success(tmp_path, monkeypatch):
    from core.assistant_runtime import migration_source_archive as owner
    original = owner.publish_directory
    project, workspace, _, snapshots = source(tmp_path)
    def tamper(pending, final, identity):
        next(pending.rglob("original.jsonl")).write_bytes(b"tampered")
        original(pending, final, identity)
    monkeypatch.setattr(owner, "publish_directory", tamper)
    with pytest.raises(MigrationIOError):
        import_source_snapshots(snapshots, tmp_path / "target", "migration-1", source_roots=(project, workspace))


def test_reused_archive_rechecks_source_after_reading_target(tmp_path, monkeypatch):
    from core.assistant_runtime import migration_source_archive as owner
    project, workspace, external, snapshots = source(tmp_path)
    target = tmp_path / "target"
    import_source_snapshots(snapshots, target, "migration-1", source_roots=(project, workspace))
    original = owner.read_stable_file
    def changed(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if path.name == "manifest.json":
            (external / "original.jsonl").write_bytes(b"source changed while reading target")
        return result
    monkeypatch.setattr(owner, "read_stable_file", changed)
    with pytest.raises(MigrationIOError):
        import_source_snapshots(snapshots, target, "migration-1", source_roots=(project, workspace))


def test_failed_post_publication_authority_check_keeps_archive_unconfirmed_until_verified_retry(tmp_path):
    project, workspace, _, snapshots = source(tmp_path)
    target = tmp_path / "target"
    checks = 0

    def revoked_after_publication():
        nonlocal checks
        checks += 1
        if checks == 3:
            raise MigrationIOError("source_authority_changed")

    with pytest.raises(MigrationIOError, match="source_authority_changed"):
        import_source_snapshots(snapshots, target, "migration-1", source_roots=(project, workspace),
                                authority_verify=revoked_after_publication)
    archive = target / "history_sources/migrations/migration-1"
    assert archive.is_dir() and not (archive / ".confirmed").exists()
    result = import_source_snapshots(snapshots, target, "migration-1", source_roots=(project, workspace),
                                     authority_verify=lambda: None)
    assert result["reused"] and (archive / ".confirmed").is_dir()


def test_old_archive_is_confirmed_only_after_matching_source_is_reverified(tmp_path):
    project, workspace, _, snapshots = source(tmp_path)
    target = tmp_path / "target"
    import_source_snapshots(snapshots, target, "migration-1", source_roots=(project, workspace))
    archive = target / "history_sources/migrations/migration-1"
    (archive / ".confirmed").rmdir()
    manifest = json.loads((archive / "manifest.json").read_bytes())
    manifest["schemaVersion"] = 1
    manifest["sourceComplete"] = manifest.pop("snapshotCompleteAtScan")
    (archive / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")), encoding="utf-8")
    result = import_source_snapshots(snapshots, target, "migration-1", source_roots=(project, workspace))
    assert result["reused"] and (archive / ".confirmed").is_dir()


def test_unverified_source_never_creates_a_confirmed_archive(tmp_path):
    project, workspace, _, snapshots = source(tmp_path)
    target = tmp_path / "target"
    with pytest.raises(MigrationIOError, match="source_authority_required"):
        _import_source_snapshots(snapshots, target, "migration-1", source_roots=(project, workspace))
    assert not target.exists()


def test_source_file_remains_locked_during_confirmation(tmp_path, monkeypatch):
    from core.assistant_runtime import migration_source_archive as owner
    project, workspace, external, snapshots = source(tmp_path)
    original = owner._confirm_archive
    denied = []

    def attempt_change(directory, guard):
        try:
            (external / "original.jsonl").write_bytes(b"changed")
        except PermissionError:
            denied.append(True)
        return original(directory, guard)

    monkeypatch.setattr(owner, "_confirm_archive", attempt_change)
    result = import_source_snapshots(snapshots, tmp_path / "target", "migration-1", source_roots=(project, workspace))
    assert result["published"] and denied == [True]


def test_source_guard_preserves_callers_busy_error(tmp_path):
    from core.assistant_runtime.migration_io import pinned_source_files, read_stable_file
    path = tmp_path / "source.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(TimeoutError, match="target busy"):
        with pinned_source_files([read_stable_file(path, 100)]):
            raise TimeoutError("target busy")
