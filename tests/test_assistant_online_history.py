import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext

import pytest

from core.assistant_runtime import migration_history as history
from core.assistant_runtime.online_history import AuthorizedHistorySource, OnlineHistoryOwner
from tests.test_assistant_migration_history import AGENT, source

REGISTRATION = "project-1:123e4567-e89b-42d3-a456-426614174000"


class GenerationFence:
    def __init__(self):
        self.lock = threading.RLock()
        self.active = "generation-1"

    @contextmanager
    def guard(self, generation):
        with self.lock:
            if self.active != generation:
                raise history.MigrationIOError("generation_changed")
            yield


def owner(tmp_path):
    workspace = source(tmp_path)
    profile = tmp_path / "profile"
    profile.mkdir()
    binding = AuthorizedHistorySource(workspace.parent, workspace, "instance-1", AGENT,
                                      "canonical-project", nullcontext)
    fence = GenerationFence()
    service = OnlineHistoryOwner(profile_root=profile, generation="generation-1",
                                 sources={REGISTRATION: binding}, generation_guard=fence.guard)
    return service, profile, binding, fence


def test_registered_id_selects_canonical_source_scope_and_never_accepts_paths(tmp_path):
    service, profile, binding, _ = owner(tmp_path)
    assert service.import_history(REGISTRATION, "migration-1")["published"]
    archived = history.list_history(profile)
    assert archived[0]["sourceScope"]["projectId"] == "canonical-project"
    assert archived[0]["sourceScope"]["projectId"] != REGISTRATION
    with pytest.raises(history.MigrationIOError, match="history_authority_revoked"):
        service.import_history("project-1:123e4567-e89b-42d3-a456-426614174001", "other")
    for invalid in ("C:/path", "C:\\path", "file:project", "../project", "x/y"):
        with pytest.raises(ValueError, match="history_request_invalid"):
            service.import_history(invalid, "other")
        with pytest.raises(ValueError, match="history_sources_invalid"):
            service.replace_sources({invalid: binding})
    with pytest.raises(ValueError, match="history_request_invalid"):
        service.import_history(REGISTRATION, "migration:invalid")
    bad = AuthorizedHistorySource(binding.project_root, binding.workspace, binding.instance_id,
                                  binding.assistant_agent_id, REGISTRATION, nullcontext)
    with pytest.raises(ValueError, match="history_sources_invalid"):
        service.replace_sources({REGISTRATION: bad})


def test_concurrent_id_is_reserved_once_and_not_replayed_after_restart(tmp_path):
    service, profile, binding, fence = owner(tmp_path)
    barrier = threading.Barrier(2)

    def run():
        barrier.wait()
        try:
            return service.import_history(REGISTRATION, "migration-1")
        except history.MigrationIOError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert sum(isinstance(result, dict) and result["published"] for result in results) == 1
    assert "history_outcome_unknown" in results
    fence.active = "generation-2"
    restarted = OnlineHistoryOwner(profile_root=profile, generation="generation-2",
                                   sources={REGISTRATION: binding}, generation_guard=fence.guard)
    with pytest.raises(history.MigrationIOError, match="history_outcome_unknown"):
        restarted.import_history(REGISTRATION, "migration-1")
    assert len(history.list_history(profile)) == 1


@pytest.mark.parametrize("action", ["close", "revoke", "replace", "source", "generation"])
def test_authority_change_after_copy_prevents_publication(tmp_path, monkeypatch, action):
    service, profile, binding, fence = owner(tmp_path)
    source_valid = [True]
    source_lock = threading.RLock()

    @contextmanager
    def check_source():
        with source_lock:
            if not source_valid[0]:
                raise history.MigrationIOError("source_changed")
            yield

    if action == "source":
        binding = AuthorizedHistorySource(binding.project_root, binding.workspace, binding.instance_id,
                                          binding.assistant_agent_id, binding.project_id, check_source)
        service.replace_sources({REGISTRATION: binding})
    reached, proceed = threading.Event(), threading.Event()
    original = history._load_archive

    def pause(directory, **kwargs):
        result = original(directory, **kwargs)
        if directory.name == ".migration-1.pending":
            reached.set()
            assert proceed.wait(10)
        return result

    monkeypatch.setattr(history, "_load_archive", pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.import_history, REGISTRATION, "migration-1")
        assert reached.wait(10)
        if action == "close":
            service.close()
        elif action == "revoke":
            service.suspend()
        elif action == "replace":
            service.replace_sources({REGISTRATION: binding})
        elif action == "source":
            with source_lock:
                source_valid[0] = False
        else:
            with fence.lock:
                fence.active = "generation-2"
        proceed.set()
        expected = {"source": "source_changed", "generation": "generation_changed"}.get(action, "history_authority_revoked")
        with pytest.raises(history.MigrationIOError, match=expected):
            future.result(timeout=10)
    assert not (profile / "history_archive/migrations/migration-1").exists()
    assert (profile / "history_online_reservations/migration-1").exists()


def test_overlapping_profile_never_reserves(tmp_path):
    workspace = source(tmp_path)
    binding = AuthorizedHistorySource(workspace.parent, workspace, "instance-1", AGENT,
                                      "canonical-project", nullcontext)
    fence = GenerationFence()
    service = OnlineHistoryOwner(profile_root=workspace, generation="generation-1",
                                 sources={REGISTRATION: binding}, generation_guard=fence.guard)
    with pytest.raises(history.MigrationIOError, match="history_target_overlaps_source"):
        service.import_history(REGISTRATION, "migration-1")
    assert not (workspace / "history_online_reservations").exists()


@pytest.mark.parametrize("authority", ["generation", "source"])
def test_authority_change_cannot_overtake_publication(tmp_path, monkeypatch, authority):
    service, profile, binding, fence = owner(tmp_path)
    source_lock = threading.RLock()
    binding = AuthorizedHistorySource(binding.project_root, binding.workspace, binding.instance_id,
                                      binding.assistant_agent_id, binding.project_id, lambda: source_lock)
    service.replace_sources({REGISTRATION: binding})
    entered, proceed, changed = threading.Event(), threading.Event(), threading.Event()
    original = history.publish_directory

    def pause(*args):
        entered.set()
        assert proceed.wait(10)
        return original(*args)

    def change():
        lock = fence.lock if authority == "generation" else source_lock
        with lock:
            if authority == "generation":
                fence.active = "generation-2"
            changed.set()

    monkeypatch.setattr(history, "publish_directory", pause)
    with ThreadPoolExecutor(max_workers=2) as pool:
        write = pool.submit(service.import_history, REGISTRATION, "migration-1")
        assert entered.wait(10)
        mutation = pool.submit(change)
        try:
            assert not changed.wait(0.2)
        finally:
            proceed.set()
        mutation.result(timeout=10)
        # If the generation changed immediately after publication, the final
        # check may report unknown; either outcome preserves the published ID.
        try:
            write.result(timeout=10)
        except history.MigrationIOError as exc:
            assert authority == "generation" and str(exc) == "generation_changed"
    assert changed.is_set()
    assert (profile / "history_archive/migrations/migration-1").is_dir()
