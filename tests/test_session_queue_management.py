"""Native queue cancellation uses disposable stores, never operator data."""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from core.chat.conversation_store import ConversationStore
from core.chat.conversation_store.repository import (
    ChatStateRevisionConflictError,
    SessionQueueControlConflictError,
    WorkspaceChatStateDao,
)
from core.ui import chat_state
from core.web.services.session import directory_runtime, queued_turns


class Busy(RuntimeError):
    pass


@pytest.fixture
def native(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_CONFIG_HOME", str(tmp_path / "config"))
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    store.open()
    monkeypatch.setattr(directory_runtime, "_STORE", store)
    monkeypatch.setattr(directory_runtime, "_PROJECT_ROOT", tmp_path.resolve())
    monkeypatch.setattr(directory_runtime, "_GENERATION", 91)
    monkeypatch.setattr(chat_state, "_conversation_store_signature", lambda root: ((1, 1),))
    chat_state.clear_session_chat_state_cache()
    notices = []
    monkeypatch.setattr(chat_state, "notify_session_catalog_dirty", lambda *args: notices.append(args))

    def mutable(sid, *, conversation):
        assert sid == "session-a"
        if conversation is None or conversation.get("read_only"):
            raise Busy("Session is unavailable or read-only")
        return conversation

    service = SimpleNamespace(
        PROJECT_ROOT=tmp_path, _CHAT_STATE_LOCK=threading.RLock(),
        load_session_chat_state=chat_state.load_session_chat_state,
        _ensure_session_mutable=mutable, _now_timestamp=lambda: "2026-11-03T00:00:00Z",
        SessionBusyError=Busy,
        _publish_session_detail_snapshot=lambda *args: pytest.fail("body projection"),
        _schedule_session_queued_turn_drain=lambda *args: pytest.fail("queue drain"),
    )
    monkeypatch.setattr(queued_turns, "_service", lambda: service)
    yield SimpleNamespace(store=store, repo=store.repository, root=tmp_path,
                          service=service, notices=notices)
    chat_state.clear_session_chat_state_cache()
    store.close()


def seed(native, sid="session-a", *, status="queued", **changes):
    value = {"conversation_id": sid, "agent_id": "agent-a", "branchGeneration": 2,
             "queued_turn_hold": {"reason": "SECRET", "turnId": "turn-live"},
             "queued_turns": [
                 {"id": "queue-a", "kind": "user", "status": status,
                  "content": "SECRET target body", "branchGeneration": 2},
                 {"id": "queue-b", "kind": "task_notification", "status": "queued",
                  "content": "SECRET sibling body", "held": {"reason": "SECRET"}},
             ], **changes}
    native.repo.upsert_session_runtime_state(sid, value).result(timeout=3)
    return native.repo.get_session_runtime_state(sid)


def observation(native):
    snapshot = native.repo.read_session_queue_metadata_snapshot()
    return snapshot["stateRevision"], next(
        row for row in snapshot["rows"] if row["sessionId"] == "session-a" and row["queueId"] == "queue-a")


def cancel(native, revision, fact):
    return queued_turns.cancel_session_queued_turn(
        "session-a", "queue-a", expected_state_revision=revision, expected_metadata=fact)


@pytest.mark.parametrize("status", ["queued", "blocked", "paused"])
def test_cancel_removes_only_observed_item_and_preserves_hold_and_siblings(native, status, monkeypatch):
    before = seed(native, status=status)
    unrelated = seed(native, "session-other")
    revision, fact = observation(native)
    original_read = native.repo.get_session_runtime_state
    monkeypatch.setattr(native.repo, "get_chat_state", lambda: pytest.fail("all Sessions hydrated"))
    monkeypatch.setattr(native.repo, "get_session_runtime_state", lambda sid: (
        original_read(sid) if sid == "session-a" else pytest.fail("unrelated Session hydrated")))
    ack = cancel(native, revision, fact)
    assert ack == {"sessionId": "session-a", "queueId": "queue-a", "agentId": "agent-a",
                   "status": "cancelled", "stateRevision": revision + 1, "queueMetadata": fact}
    after = original_read("session-a")
    assert after["queued_turns"] == before["queued_turns"][1:]
    assert after["queued_turn_hold"] == before["queued_turn_hold"]
    assert original_read("session-other") == unrelated
    assert "SECRET" not in json.dumps(ack) and "turnId" not in ack
    assert native.notices == [(native.root, "session-a", f"state:{revision + 1}")]


def test_starting_is_rejected_without_writes_or_cache_notifications(native):
    before = seed(native, status="starting")
    revision, fact = observation(native)
    with pytest.raises(Busy, match="queue_starting"):
        cancel(native, revision, fact)
    assert observation(native) == (revision, fact)
    assert native.repo.get_session_runtime_state("session-a") == before
    assert native.notices == []


@pytest.mark.parametrize("change", ["content", "global_revision"])
def test_native_revision_fences_same_metadata_content_changes_and_unrelated_writes(native, change):
    before = seed(native)
    revision, fact = observation(native)
    if change == "content":
        before["queued_turns"][0]["content"] = "changed body"
        native.repo.upsert_session_runtime_state("session-a", before).result(timeout=3)
    else:
        seed(native, "session-other")
    assert observation(native)[1] == fact
    with pytest.raises(Busy, match="revision conflict"):
        cancel(native, revision, fact)
    assert len(native.repo.get_session_runtime_state("session-a")["queued_turns"]) == 2
    assert native.notices == []


@pytest.mark.parametrize("field,value", [
    ("agentId", "agent-other"), ("position", 2), ("queueKind", "control_notice"),
    ("status", "paused"), ("branchGeneration", 99), ("sessionBranchGeneration", 99),
    ("sessionHeld", False), ("held", True), ("sendNow", True),
])
def test_metadata_fact_is_exactly_bound(native, field, value):
    before = seed(native)
    revision, fact = observation(native)
    with pytest.raises(Busy, match="queue_metadata_changed"):
        cancel(native, revision, {**fact, field: value})
    assert native.repo.get_session_runtime_state("session-a") == before


def test_identity_mismatch_rejected_before_submission(native):
    seed(native)
    revision, fact = observation(native)
    with pytest.raises(ValueError, match="identity mismatch"):
        cancel(native, revision, {**fact, "queueId": "queue-b"})
    assert observation(native) == (revision, fact)


def test_cas_is_checked_at_writer_execution_after_a_queued_competing_write(native):
    value = seed(native)
    revision, fact = observation(native)
    entered, release = threading.Event(), threading.Event()

    def hold_writer(unit):
        entered.set()
        assert release.wait(3)

    blocker = native.repo._writer.submit(hold_writer, force_flush=True)
    assert entered.wait(3)
    value["queued_turns"][0]["content"] = "racing change"
    change = native.repo.upsert_session_runtime_state("session-a", value)
    removal = native.repo.cancel_session_queued_turn_metadata(
        session_id="session-a", queue_id="queue-a", expected_state_revision=revision,
        expected_metadata=fact, updated_at="now")
    release.set()
    blocker.result(timeout=3)
    change.result(timeout=3)
    with pytest.raises(ChatStateRevisionConflictError):
        removal.result(timeout=3)
    assert native.repo.get_session_runtime_state("session-a")["queued_turns"][0]["content"] == "racing change"


def test_cancellation_transaction_rolls_back_if_revision_commit_fails(native, monkeypatch):
    before = seed(native)
    revision, fact = observation(native)

    def fail(self, **kwargs):
        raise RuntimeError("injected revision failure")

    monkeypatch.setattr(WorkspaceChatStateDao, "_bump_workspace_revision", fail)
    with pytest.raises(RuntimeError, match="injected"):
        cancel(native, revision, fact)
    assert native.repo.get_session_runtime_state("session-a") == before
    assert observation(native) == (revision, fact)


def test_native_cache_epoch_prevents_subsequent_save_resurrecting_removed_item(native):
    seed(native)
    cached = chat_state.load_session_chat_state(native.root, "session-a")
    assert len(cached["queued_turns"]) == 2
    revision, fact = observation(native)
    cancel(native, revision, fact)
    # The signature is held constant by this fixture, proving epoch invalidation.
    with native.service._CHAT_STATE_LOCK:
        current = chat_state.load_session_chat_state(native.root, "session-a")
        assert [row["id"] for row in current["queued_turns"]] == ["queue-b"]
        current["title"] = "edited later"
        chat_state.save_session_chat_state(native.root, "session-a", current)
    assert [row["id"] for row in native.repo.get_session_runtime_state("session-a")["queued_turns"]] == ["queue-b"]


def test_delayed_writer_settles_before_a_later_locked_load_save(native, monkeypatch):
    seed(native)
    chat_state.load_session_chat_state(native.root, "session-a")
    revision, fact = observation(native)
    entered, release, awaiting_commit, saved = (threading.Event() for _ in range(4))
    def hold_writer(unit):
        entered.set()
        assert release.wait(3)
    blocker = native.repo._writer.submit(hold_writer, force_flush=True)
    assert entered.wait(3)
    original = native.repo.cancel_session_queued_turn_metadata
    def observed_submission(**kwargs):
        future = original(**kwargs)
        class PendingCommit:
            def result(self, timeout=None):
                assert timeout is None, "a timeout leaves an uncancelled mutation outside the CHAT lock"
                awaiting_commit.set()
                return future.result()
        return PendingCommit()
    monkeypatch.setattr(native.repo, "cancel_session_queued_turn_metadata", observed_submission)
    def later_save():
        with native.service._CHAT_STATE_LOCK:
            current = chat_state.load_session_chat_state(native.root, "session-a")
            current["title"] = "after withdrawal"
            chat_state.save_session_chat_state(native.root, "session-a", current)
            saved.set()
    with ThreadPoolExecutor(max_workers=2) as threads:
        removal = threads.submit(cancel, native, revision, fact)
        try:
            assert awaiting_commit.wait(2)
            subsequent = threads.submit(later_save)
            assert not saved.wait(.05)
        finally:
            release.set()
        blocker.result(timeout=3)
        assert removal.result(timeout=3)["status"] == "cancelled"
        subsequent.result(timeout=3)
    assert saved.is_set()
    assert [row["id"] for row in native.repo.get_session_runtime_state("session-a")["queued_turns"]] == ["queue-b"]


def test_missing_store_and_read_only_session_fail_without_initialization(native, monkeypatch):
    seed(native, read_only=True)
    revision, fact = observation(native)
    with pytest.raises(Busy, match="read-only"):
        cancel(native, revision, fact)
    monkeypatch.setattr(directory_runtime, "_STORE", None)
    monkeypatch.setattr(ConversationStore, "open", lambda *args: pytest.fail("store initialization"))
    with pytest.raises(Busy, match="unavailable"):
        cancel(native, revision, fact)


def test_repository_cancellation_never_decodes_runtime_bodies(native, monkeypatch):
    seed(native)
    revision, fact = observation(native)
    monkeypatch.setattr(json, "loads", lambda *args, **kwargs: pytest.fail("runtime body decoded"))
    ack = native.repo.cancel_session_queued_turn_metadata(
        session_id="session-a", queue_id="queue-a", expected_state_revision=revision,
        expected_metadata=fact, updated_at="now").result(timeout=3)
    assert ack["status"] == "cancelled"


def test_duplicate_native_queue_ids_are_not_ambiguously_removed(native):
    seed(native, queued_turns=[{"id": "queue-a"}, {"id": "queue-a"}])
    with pytest.raises(SessionQueueControlConflictError, match="unavailable"):
        native.repo.cancel_session_queued_turn_metadata(
            session_id="session-a", queue_id="queue-a", expected_state_revision=1,
            expected_metadata={"sessionId": "session-a", "queueId": "queue-a"},
            updated_at="now").result(timeout=3)
