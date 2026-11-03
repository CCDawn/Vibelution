"""Metadata-only native inventory; every database in this file is disposable."""
from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from core.chat.conversation_store import ConversationStore
from core.web.services.session import directory_runtime
from core.web.services.session_turn_scheduler import SessionTurnScheduler


def scheduler():
    return SessionTurnScheduler(
        agent_key_for_context=lambda context: "agent:" + context["agent_id"],
        max_active_per_agent=1, now=lambda: 1.0,
        record_event=lambda *args: None, mark_queued=lambda *args: None,
        mark_dequeued=lambda *args: None, is_session_running=lambda sid: False,
        is_session_turn_current=lambda sid, tid: True,
    )


@pytest.fixture
def native(tmp_path, monkeypatch):
    from core.web.services.session import runtime_inventory

    monkeypatch.setenv("VIBELUTION_CONFIG_HOME", str(tmp_path / "config"))
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    store.open()
    fake = SimpleNamespace(
        PROJECT_ROOT=tmp_path, _RUNNING_SESSIONS_LOCK=threading.Lock(),
        _RUNNING_SESSION_IDS=set(), _SESSION_ACTIVE_TURN_IDS={},
        _SESSION_TURN_CONTROLS_LOCK=threading.Lock(), _SESSION_TURN_CONTROLS={},
        _SESSION_TURN_SCHEDULER=scheduler(),
    )
    monkeypatch.setattr(runtime_inventory, "_service", lambda: fake)
    monkeypatch.setattr(directory_runtime, "_STORE", store)
    monkeypatch.setattr(directory_runtime, "_PROJECT_ROOT", tmp_path.resolve())
    monkeypatch.setattr(directory_runtime, "_GENERATION", 12)
    yield SimpleNamespace(root=tmp_path, store=store, service=fake, inventory=runtime_inventory)
    store.close()


def seed(native, sid, rows, **metadata):
    native.store.repository.upsert_session_runtime_state(
        sid, {"conversation_id": sid, "agent_id": "agent-a", "queued_turns": rows,
              "title": "SECRET title", "messages": [{"content": "SECRET body"}], **metadata},
    ).result(timeout=3)


def row(qid="queue-a", **fields):
    return {"id": qid, "content": "SECRET queue body", "status": "queued", "kind": "user", **fields}


def coverage(result, source):
    return next(item for item in result["sourceCoverage"] if item["source"] == source)


def read(native, **kwargs):
    return native.inventory.read_session_runtime_inventory(native.root, **kwargs)


def test_inventory_discovers_more_than_forty_idle_hidden_archived_queues(native, monkeypatch):
    revision = native.store.repository.create_agent(
        agent_id="agent-a", display_name="SECRET", kind="assistant", config={}, source="test",
    ).result(timeout=3)["configRevisionId"]
    for number in range(47):
        native.store.repository.create_session(
            session_id=f"session-{number:02}", agent_id="agent-a", agent_config_revision_id=revision,
            title="SECRET", hidden_from_index=True, archived=bool(number % 2),
        ).result(timeout=3)
        seed(native, f"session-{number:02}", [row(f"queue-{number:02}")],
             status="archived" if number % 2 else "idle", hidden_from_index=True)
    monkeypatch.setattr(native.store.repository, "get_session_runtime_state", lambda *args: pytest.fail("body read"))
    monkeypatch.setattr(ConversationStore, "open", lambda *args, **kwargs: pytest.fail("initialization"))
    before = {path.name: path.read_bytes() for path in native.root.iterdir()
              if path.suffix == ".sqlite3" or path.name.endswith("-wal")}
    result = read(native)
    assert len(result["queues"]) == 47 and result["turns"] == []
    assert coverage(result, "persisted_queue")["complete"] is True
    assert result["complete"] is False and result["consistency"] == "non_atomic"
    assert coverage(result, "journal")["reason"] == "read_failed"
    assert "SECRET" not in json.dumps(result)
    assert before == {path.name: path.read_bytes() for path in native.root.iterdir()
                      if path.suffix == ".sqlite3" or path.name.endswith("-wal")}


def test_inventory_keeps_queue_kinds_status_hold_and_generation_metadata(native):
    kinds = ["user", "task_notification", "subagent_message", "control_notice"]
    statuses = ["queued", "starting", "paused", "blocked"]
    seed(native, "session-a", [row(f"queue-{number}", kind=kind, status=statuses[number],
         branchGeneration=2, sendNow=number == 0, held={"reason": "SECRET"} if number == 1 else None)
         for number, kind in enumerate(kinds)], branchGeneration=3,
         queued_turn_hold={"reason": "SECRET", "turnId": "turn-old"})
    result = read(native)
    assert [item["queueKind"] for item in result["queues"]] == kinds
    assert [item["status"] for item in result["queues"]] == statuses
    assert all(item["sessionHeld"] for item in result["queues"])
    assert [item["held"] for item in result["queues"]] == [False, True, False, False]
    assert all(item["branchGeneration"] == 2 and item["sessionBranchGeneration"] == 3 for item in result["queues"])
    assert result["queues"][0]["sendNow"] is True
    assert "turnId" not in result["queues"][0] and result["turns"] == []
    assert "SECRET" not in json.dumps(result)


def test_scheduler_metadata_does_not_promote_reservations_or_pending_admission(native):
    owner = native.service._SESSION_TURN_SCHEDULER
    owner.schedule({"session_id": "active", "turn_id": "turn-active", "agent_id": "agent-a"},
                   submit=lambda context: None, release=lambda context: None)
    owner.schedule({"session_id": "waiting", "turn_id": "turn-waiting", "agent_id": "agent-a",
                    "raw_user_message": "SECRET"}, submit=lambda context: None, release=lambda context: None)
    owner.schedule({"session_id": "proactive", "turn_id": "turn-pending", "agent_id": "agent-a",
                    "_scheduler_deferred_session_admission": True},
                   submit=lambda context: None, release=lambda context: None)
    with owner._condition:
        owner._queues["agent:agent-a"].append({"session_id": "external", "turn_id": "external-run",
            "agent_id": "agent-a", "_scheduler_external": True})
    result = read(native)
    assert [item["turnId"] for item in result["turns"]] == ["turn-waiting"]
    assert result["turns"][0]["status"] == "queued"
    assert result["turns"][0]["liveControl"] is False
    assert coverage(result, "scheduler")["pendingAdmissionCount"] == 1
    assert coverage(result, "scheduler")["externalReservationCount"] == 1
    assert coverage(result, "scheduler")["complete"] is False
    assert "SECRET" not in json.dumps(result)


class Control:
    def __init__(self, tid, *, stopped=False, released=False):
        self.turn_id = tid
        self.stopped, self.released = stopped, released

    def snapshot(self):
        return {"turnId": self.turn_id, "stopRequested": self.stopped,
                "releasedToUser": self.released, "stopReason": "SECRET"}


def test_running_turn_requires_matching_current_control_and_revalidates_identity(native):
    owner = native.service
    owner._RUNNING_SESSION_IDS.update({"live", "mismatch", "orphan", "released"})
    owner._SESSION_ACTIVE_TURN_IDS.update({"live": "turn-a", "mismatch": "turn-b",
        "orphan": "turn-c", "released": "turn-d"})
    owner._SESSION_TURN_CONTROLS.update({"live": Control("turn-a", stopped=True),
        "mismatch": Control("another"), "released": Control("turn-d", released=True)})
    result = read(native)
    assert [(item["sessionId"], item["status"]) for item in result["turns"]] == [("live", "stopping")]
    assert result["turns"][0]["liveControl"] is True
    assert coverage(result, "running_controller")["complete"] is False

    control = owner._SESSION_TURN_CONTROLS["live"]
    original = control.snapshot
    def replace():
        owner._SESSION_TURN_CONTROLS["live"] = Control("turn-new")
        return original()
    control.snapshot = replace
    result = read(native)
    assert result["turns"] == []
    assert coverage(result, "running_controller")["reason"] == "source_changed"


def test_new_running_identity_during_sampling_marks_source_changed(native):
    owner = native.service
    control = Control("turn-a")
    owner._RUNNING_SESSION_IDS.add("first")
    owner._SESSION_ACTIVE_TURN_IDS["first"] = "turn-a"
    owner._SESSION_TURN_CONTROLS["first"] = control
    original = control.snapshot
    def add_session():
        owner._RUNNING_SESSION_IDS.add("second")
        owner._SESSION_ACTIVE_TURN_IDS["second"] = "turn-b"
        owner._SESSION_TURN_CONTROLS["second"] = Control("turn-b")
        return original()
    control.snapshot = add_session
    result = read(native)
    assert [item["turnId"] for item in result["turns"]] == ["turn-a"]
    assert coverage(result, "running_controller")["reason"] == "source_changed"
    assert coverage(result, "running_controller")["complete"] is False


@pytest.mark.parametrize("condition", ["missing", "project_mismatch", "generation_changed", "closed"])
def test_store_binding_failures_never_initialize_or_report_empty_complete(native, monkeypatch, condition):
    if condition == "missing":
        monkeypatch.setattr(directory_runtime, "_STORE", None)
    elif condition == "project_mismatch":
        monkeypatch.setattr(directory_runtime, "_PROJECT_ROOT", native.root / "other")
    elif condition == "closed":
        native.store.close()
    else:
        original = native.store.repository.read_session_queue_metadata_snapshot
        def changed(**kwargs):
            result = original(**kwargs)
            monkeypatch.setattr(directory_runtime, "_GENERATION", 13)
            return result
        monkeypatch.setattr(native.store.repository, "read_session_queue_metadata_snapshot", changed)
    monkeypatch.setattr(ConversationStore, "open", lambda *args, **kwargs: pytest.fail("initialization"))
    result = read(native)
    assert result["queues"] == [] and result["complete"] is False
    assert coverage(result, "persisted_queue")["state"] == "unavailable"


def test_queue_invalid_duplicate_and_budget_data_is_explicitly_partial(native):
    seed(native, "session-a", [row("duplicate"), row("duplicate"), row("good"),
                              row("bad/path"), row("unknown", status="SECRET status"), None])
    result = read(native)
    assert {item["queueId"] for item in result["queues"]} == {"good", "unknown"}
    assert next(item for item in result["queues"] if item["queueId"] == "unknown")["status"] == "unknown"
    assert coverage(result, "persisted_queue")["invalidCount"] >= 4
    assert coverage(result, "persisted_queue")["complete"] is False
    assert "SECRET" not in json.dumps(result)
    limited = read(native, max_rows=2)
    assert coverage(limited, "persisted_queue")["truncated"] is True
    assert limited["complete"] is False


def test_queue_document_byte_budget_does_not_parse_or_return_oversized_json(native, monkeypatch):
    from core.chat.conversation_store import repository
    seed(native, "session-a", [row("first")])
    seed(native, "session-b", [row("second")])
    monkeypatch.setattr(repository, "QUEUE_METADATA_MAX_BYTES", 1)
    result = read(native)
    assert result["queues"] == []
    assert coverage(result, "persisted_queue")["truncated"] is True
    assert coverage(result, "persisted_queue")["reason"] == "budget_exceeded"


@pytest.mark.parametrize("fields", [{"sendNow": "SECRET"}, {"branchGeneration": -1},
                                    {"branchGeneration": 2**80}, {"kind": "SECRET"}])
def test_invalid_control_metadata_cannot_claim_complete(native, fields):
    seed(native, "session-a", [row(**fields)])
    result = read(native)
    assert coverage(result, "persisted_queue")["complete"] is False
    assert "SECRET" not in json.dumps(result)


@pytest.mark.parametrize("raw", ['{"queued_turns":{}}', '{broken', '{"queued_turns":[1,"body",true]}'])
def test_malformed_queue_documents_are_not_silently_an_empty_source(native, raw):
    seed(native, "session-a", [])
    writer = native.store.database.open_writer()
    try:
        writer.execute("UPDATE session_runtime_state SET payload_json=? WHERE session_id='session-a'", (raw,))
    finally:
        writer.close()
    result = read(native)
    assert result["queues"] == []
    assert coverage(result, "persisted_queue")["invalidCount"] > 0
    assert coverage(result, "persisted_queue")["complete"] is False


def test_sql_metadata_projection_has_one_read_transaction_and_no_body_columns(native, monkeypatch):
    seed(native, "session-a", [row("before")])
    original = native.store.database.reader
    statements, updated = [], False
    @contextmanager
    def reader():
        with original() as connection:
            class Traced:
                def execute(self, sql, parameters=()):
                    nonlocal updated
                    statements.append(sql)
                    result = connection.execute(sql, parameters)
                    if "COUNT(*)" in sql and not updated:
                        updated = True
                        seed(native, "session-a", [row("after")])
                    return result
            yield Traced()
    monkeypatch.setattr(native.store.database, "reader", reader)
    snapshot = native.store.repository.read_session_queue_metadata_snapshot()
    assert [item["queueId"] for item in snapshot["rows"]] == ["before"]
    assert statements[0] == "BEGIN" and statements[-1] == "ROLLBACK"
    assert all("SELECT payload_json" not in sql and "SELECT *" not in sql for sql in statements)
    assert all("session_debug_snapshots" not in sql and "turn_items" not in sql for sql in statements)


def test_native_sources_fail_independently_without_using_body_or_repair(native, monkeypatch):
    seed(native, "session-a", [row()])
    monkeypatch.setattr(native.service._SESSION_TURN_SCHEDULER, "snapshot_queued_turn_metadata",
                        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("SECRET")))
    result = read(native)
    assert len(result["queues"]) == 1
    assert coverage(result, "scheduler")["state"] == "unavailable"
    assert coverage(result, "persisted_queue")["complete"] is True
    assert "SECRET" not in json.dumps(result)


@pytest.mark.parametrize("max_rows", [0, -1, 10001, True, "3"])
def test_inventory_rejects_invalid_read_budgets(native, max_rows):
    with pytest.raises(ValueError, match="inventory limit"):
        read(native, max_rows=max_rows)


def test_runtime_root_mismatch_is_not_an_available_idle_source(native):
    native.service.PROJECT_ROOT = native.root / "other"
    result = read(native)
    assert result["turns"] == [] and result["complete"] is False
    for source in ("running_controller", "scheduler"):
        assert coverage(result, source)["state"] == "unavailable"
        assert coverage(result, source)["reason"] == "project_binding_mismatch"


def test_conflicting_directory_owner_is_not_promoted_to_queue_authority(native):
    revision = native.store.repository.create_agent(
        agent_id="directory-agent", display_name="SECRET", kind="assistant", config={}, source="test",
    ).result(timeout=3)["configRevisionId"]
    native.store.repository.create_session(
        session_id="session-a", agent_id="directory-agent", agent_config_revision_id=revision, title="SECRET",
    ).result(timeout=3)
    seed(native, "session-a", [row()], agent_id="payload-agent")
    result = read(native)
    assert len(result["queues"]) == 1 and result["queues"][0]["agentId"] == ""
    assert coverage(result, "persisted_queue")["complete"] is False
