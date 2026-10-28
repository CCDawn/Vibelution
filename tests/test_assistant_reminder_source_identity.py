import json
import hashlib
import shutil
from datetime import datetime, timezone

import pytest

from core.assistant_runtime.migration_io import MigrationIOError
from core.assistant_runtime.history_preview import HistoryPreview
from core.assistant_runtime.reminder_source_identity import observe_reminder_source, compare_reminder_sources
from tests.test_assistant_history_preview import setup_preview  # noqa: F401


def prepare(dispatch, workspace):
    registry = workspace / "agents/agents.json"
    data = json.loads(registry.read_text(encoding="utf-8"))
    data["agents"][0]["primaryMode"] = "general"
    registry.write_text(json.dumps(data), encoding="utf-8")
    root = dispatch._admitted_projects()["registered:1"]
    ledger = root / "agents/agent-pa/plugins/personal-affairs/affairs/items.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("", encoding="utf-8")
    return registry, ledger


def test_registered_identity_is_read_only_and_rechecks_source(setup_preview):
    dispatch, workspace, _ = setup_preview
    registry, ledger = prepare(dispatch, workspace)
    before = {p: p.read_bytes() for p in (registry, ledger)}
    with observe_reminder_source(dispatch, dispatch.history_preview, "registered:1", 1) as first:
        with observe_reminder_source(dispatch, dispatch.history_preview, "registered:1", 1) as second:
            assert compare_reminder_sources(first, second) == "same"
            assert first.agent_id == "agent-pa"
            assert first.ready_for_cutover is False
            assert {p: p.read_bytes() for p in (registry, ledger)} == before
            ledger.write_text('{"change":true}\n', encoding="utf-8")
            with pytest.raises(MigrationIOError):
                compare_reminder_sources(first, second)
    assert not dispatch.history_preview._previews


def test_large_native_ledger_observation_and_mutex_share_identity(setup_preview):
    from core.agent_plugins.personal_affairs.service import AFFAIR_LEDGER_LIMIT, PersonalAffairsService
    from core.assistant_runtime.initial_migration_binding import _digest, _directory
    from core.infrastructure.reminder_source_mutex import trusted_reminder_source_mutex_key, try_acquire_reminder_source_mutex

    dispatch, workspace, _ = setup_preview
    _, ledger = prepare(dispatch, workspace)
    root = dispatch._admitted_projects()["registered:1"]
    now = datetime(2026, 10, 28, 1, 2, 3, 123456, tzinfo=timezone.utc)
    service = PersonalAffairsService(root, now_provider=lambda: now)
    # U+0001 is valid in these native string fields and exercises JSON's
    # six-byte escape expansion. Construct rows from the actual service output
    # and persist with its native writer rather than using oversized junk data.
    template = service.add_item("agent-pa", kind="todo", title="item-0000:" + "\x01" * 150,
                                note="\x01" * 600, source_turn_id="\x01" * 200,
                                due_at="2026-10-28T12:34:56.123456Z")
    rows = []
    for index in range(AFFAIR_LEDGER_LIMIT):
        title = f"item-{index:04d}:" + "\x01" * 150
        digest = hashlib.sha256(f"agent-pa:todo:{title}:{now.isoformat()}".encode("utf-8")).hexdigest()[:16]
        rows.append({**template, "title": title, "itemId": f"affair-{digest}"})
    service._write_rows("agent-pa", rows)
    size = ledger.stat().st_size
    assert 4 * 1024 * 1024 < size <= AFFAIR_LEDGER_LIMIT * (6 * (160 + 600 + 200) + 512) < 16 * 1024 * 1024
    assert len(service.list_items("agent-pa")["items"]) == AFFAIR_LEDGER_LIMIT
    with observe_reminder_source(dispatch, dispatch.history_preview, "registered:1", 1) as observation:
        key = trusted_reminder_source_mutex_key(observation)
        assert key == _digest({"path": str(ledger).casefold(), "parent": _directory(ledger.parent), "agentId": "agent-pa"})
        lease = try_acquire_reminder_source_mutex(observation)
        assert lease is not None
        try:
            lease.check()
            with ledger.open("ab") as stream:
                stream.write(b"\n")
            with pytest.raises(MigrationIOError, match="reminder_source_observation_changed"):
                trusted_reminder_source_mutex_key(observation)
        finally:
            lease.release()
    assert not dispatch.history_preview._previews


def test_missing_ledger_or_untrusted_request_is_not_an_identity(setup_preview):
    dispatch, workspace, _ = setup_preview
    _, ledger = prepare(dispatch, workspace)
    ledger.unlink()
    with pytest.raises(MigrationIOError):
        observe_reminder_source(dispatch, dispatch.history_preview, "registered:1", 1)
    with pytest.raises(MigrationIOError):
        observe_reminder_source(dispatch, dispatch.history_preview, str(ledger), 1)
    assert not dispatch.history_preview._previews


def test_oversized_non_native_ledger_stays_unavailable(setup_preview):
    dispatch, workspace, _ = setup_preview
    _, ledger = prepare(dispatch, workspace)
    with ledger.open("wb") as stream:
        stream.truncate(16 * 1024 * 1024 + 1)
    with pytest.raises(MigrationIOError, match="file_byte_limit"):
        observe_reminder_source(dispatch, dispatch.history_preview, "registered:1", 1)
    assert not dispatch.history_preview._previews


def test_registry_and_routing_changes_revoke_observation(setup_preview):
    dispatch, workspace, _ = setup_preview
    registry, _ = prepare(dispatch, workspace)
    with observe_reminder_source(dispatch, dispatch.history_preview, "registered:1", 1) as source:
        registry.write_text(registry.read_text(encoding="utf-8") + " ", encoding="utf-8")
        with pytest.raises(MigrationIOError):
            compare_reminder_sources(source, source)


def test_shared_ledger_with_separate_data_home_is_unknown(setup_preview, tmp_path):
    dispatch, workspace, _ = setup_preview
    prepare(dispatch, workspace)
    home = tmp_path / "another-data-home"
    shutil.copytree(workspace, home / "workspace")
    config = tmp_path / "other-config.toml"
    config.write_text(f'[storage]\ndata_home = "{home.as_posix()}"\n', encoding="utf-8")
    second_preview = HistoryPreview(dispatch, config)
    with observe_reminder_source(dispatch, dispatch.history_preview, "registered:1", 1) as first:
        with observe_reminder_source(dispatch, second_preview, "registered:1", 1) as second:
            assert compare_reminder_sources(first, second) == "unknown"


def test_profile_identity_change_cannot_revive_old_observation(setup_preview):
    dispatch, workspace, _ = setup_preview
    registry, ledger = prepare(dispatch, workspace)
    with observe_reminder_source(dispatch, dispatch.history_preview, "registered:1", 1) as old:
        data = json.loads(registry.read_text(encoding="utf-8"))
        data["agents"][0]["agentId"] = "agent-new"
        registry.write_text(json.dumps(data), encoding="utf-8")
        other = ledger.parents[4] / "agent-new/plugins/personal-affairs/affairs/items.jsonl"
        other.parent.mkdir(parents=True)
        other.write_text("", encoding="utf-8")
        with observe_reminder_source(dispatch, dispatch.history_preview, "registered:1", 1) as new:
            with pytest.raises(MigrationIOError):
                compare_reminder_sources(old, new)


def test_different_registered_projects_have_distinct_ledgers(setup_preview, tmp_path):
    from vibelution_storage import resolve_active_project_storage_paths

    dispatch, workspace, _ = setup_preview
    prepare(dispatch, workspace)
    root = dispatch._admitted_projects()["registered:1"]
    other = tmp_path / "other-project"
    shutil.copytree(root, other)
    project_file = other / ".vibelution/project.json"
    project_file.write_text('{"schemaVersion": 1, "projectId": "another-project"}', encoding="utf-8")
    other_workspace = resolve_active_project_storage_paths(other, config_path=dispatch.history_preview._config).data / "workspace"
    shutil.copytree(workspace, other_workspace)
    dispatch.replace_projects({"schemaVersion": 1, "revision": 2,
                               "projects": {"registered:1": str(root), "registered:2": str(other)}})
    with observe_reminder_source(dispatch, dispatch.history_preview, "registered:1", 2) as first:
        with observe_reminder_source(dispatch, dispatch.history_preview, "registered:2", 2) as second:
            assert compare_reminder_sources(first, second) == "different"
