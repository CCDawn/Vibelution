"""PA dispatch-receipt ledger: schema hygiene, replay safety, envelope
extraction, change-driven harvest, and the ledger-first read model with
its JSONL fallback."""

import json
import sqlite3
import time
from pathlib import Path

import pytest

from core.web.services import agent_directory_service as directory
from core.web.services import personal_assistant_dispatch_ledger as ledger
from core.web.services import personal_assistant_dispatches_service as dispatches_service
from core.web.services import personal_assistant_service as service
from tests.test_personal_assistant_service import (
    finance_env as _finance_env,
)
from tests.test_personal_assistant_service import (
    personal_env as _personal_env,
)

finance_env = _finance_env
personal_env = _personal_env

ASSISTANT_ID = "assistant-agent"
TARGET_ID = "target-agent"
OTHER_ID = "other-agent"


@pytest.fixture(autouse=True)
def _reset_ledger_memo():
    ledger.reset_identity_memo()
    yield
    ledger.reset_identity_memo()


def _agent_row(agent_id: str, *, is_assistant: bool = False) -> dict:
    row = {
        "agentId": agent_id,
        "displayName": agent_id,
        "status": "active",
        "workspacePath": f"workspace/agents/{agent_id}",
        "metadata": {},
    }
    if is_assistant:
        row["roleKey"] = service.ROLE
        row["primaryMode"] = "general"
        row["metadata"] = {"personalAssistantProfile": service.PROFILE}
    return row


def _seed_agents(personal_env, rows) -> None:
    state = directory.load_state()
    state["agents"] = rows
    directory.save_state(state)


def _inbox_path(personal_env, agent_id: str) -> Path:
    return personal_env["root"] / "workspace" / "agents" / agent_id / "events" / "agent_inbox_messages.jsonl"


def _write_inbox(personal_env, agent_id: str, rows, *, raw_lines: list[str] | None = None) -> None:
    inbox = _inbox_path(personal_env, agent_id)
    inbox.parent.mkdir(parents=True, exist_ok=True)
    with open(inbox, "w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        for line in raw_lines or []:
            fh.write(line + "\n")


def _dispatch_row(message_id: str, *, kind: str = "agent_message", status: str = "pending",
                  created_at: str = "2026-10-20T10:00:00+00:00", target: str = TARGET_ID,
                  thread: str | None = None, metadata: dict | None = None) -> dict:
    return {
        "eventId": f"event-{message_id}",
        "messageId": message_id,
        "threadId": thread or f"thread-{message_id}",
        "kind": kind,
        "status": status,
        "sourceAgentId": ASSISTANT_ID,
        "sourceAgentName": "个人助理",
        "targetAgentId": target,
        "targetAgentName": target,
        "targetSessionId": "target-session",
        "summary": "dispatch summary",
        "createdAt": created_at,
        "metadata": metadata or {},
    }


def _receipt_row(message_id: str, *, reply_to: str = "", thread_id: str = "",
                 source_agent: str = TARGET_ID, created_at: str = "2026-10-20T11:00:00+00:00",
                 status: str = "pending", envelope: dict | None = None,
                 metadata: dict | None = None) -> dict:
    row_metadata = dict(metadata or {})
    if envelope is not None:
        row_metadata["agentToolMetadataJson"] = json.dumps(envelope, ensure_ascii=False)
    elif reply_to:
        row_metadata["replyToMessageId"] = reply_to
    return {
        "eventId": f"event-{message_id}",
        "messageId": message_id,
        "threadId": thread_id,
        "kind": "agent_inbox_message",
        "status": status,
        "sourceAgentId": source_agent,
        "sourceAgentName": source_agent,
        "targetAgentId": ASSISTANT_ID,
        "targetSessionId": "assistant-session",
        "summary": "receipt summary",
        "createdAt": created_at,
        "metadata": row_metadata,
    }


def _task_envelope(status: str, *, dispatch_id: str = "original") -> dict:
    return {
        "replyToMessageId": dispatch_id,
        "personalAssistantTask": {
            "schemaVersion": 1,
            "dispatchMessageId": dispatch_id,
            "status": status,
            "evidenceRefs": ["artifact:result-1"],
        },
    }


@pytest.fixture
def seeded(personal_env):
    _seed_agents(personal_env, [
        _agent_row(ASSISTANT_ID, is_assistant=True),
        _agent_row(TARGET_ID),
        _agent_row(OTHER_ID),
    ])
    return personal_env


# ---------------------------------------------------------------------------
# Schema hygiene
# ---------------------------------------------------------------------------


def test_ledger_creates_schema_and_reopens(seeded):
    assert ledger.ensure_harvested(ASSISTANT_ID) is True
    path = ledger.ledger_database_path()
    assert path.exists()
    connection = sqlite3.connect(str(path))
    try:
        assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == ledger.SCHEMA_VERSION
        names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")
        }
        assert {"ledger_meta", "dispatches", "receipts", "harvest_state"} <= names
        assert list(connection.execute("PRAGMA quick_check")) == [("ok",)]
    finally:
        connection.close()
    # Reopen: steady state is served without re-harvest failures.
    assert ledger.ensure_harvested(ASSISTANT_ID) is True


def test_foreign_v0_database_is_rejected_and_read_model_falls_back(seeded):
    path = ledger.ledger_database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    foreign = sqlite3.connect(str(path))
    foreign.execute("CREATE TABLE impostor (id TEXT PRIMARY KEY)")
    foreign.commit()
    foreign.close()

    assert ledger.ensure_harvested(ASSISTANT_ID) is False

    _write_inbox(seeded, TARGET_ID, [_dispatch_row("dispatch-1")])
    payload = dispatches_service.list_personal_assistant_dispatches(limit=10)
    assert [row["messageId"] for row in payload["dispatches"]] == ["dispatch-1"]


# ---------------------------------------------------------------------------
# Recording: replay safety and monotonic status merge
# ---------------------------------------------------------------------------


def test_record_replay_is_idempotent_and_status_merge_is_monotonic(seeded):
    row = _dispatch_row("dispatch-1", status="pending")

    ledger.record_inbox_message(row)
    ledger.record_inbox_message(dict(row))
    ledger.record_inbox_status_change(TARGET_ID, ["dispatch-1"], "consumed")
    # A replayed pending row must never downgrade a consumed ledger row.
    ledger.record_inbox_message(dict(row))

    connection = sqlite3.connect(str(ledger.ledger_database_path()))
    try:
        rows = list(connection.execute(
            "SELECT message_id, row_kind, status FROM dispatches"
        ))
        instances = list(connection.execute(
            "SELECT message_id FROM dispatch_instances"
        ))
    finally:
        connection.close()
    assert rows == [("dispatch-1", "dispatch", "consumed")]
    # Hook-recorded rows are not JSONL rows; the instance ledger only grows
    # from harvest, so a pure replay adds no instance either.
    assert instances == []


def test_receipt_replay_keeps_reply_to_and_task_columns(seeded):
    envelope = _task_envelope("running")
    row = _receipt_row("receipt-1", reply_to="original", envelope=envelope)

    ledger.record_inbox_message(row)
    replayed = dict(row)
    replayed["metadata"] = {}  # a degenerate replay must not erase pairing
    ledger.record_inbox_message(replayed)

    connection = sqlite3.connect(str(ledger.ledger_database_path()))
    try:
        stored = list(connection.execute(
            "SELECT reply_to_message_id, personal_assistant_task, digested_at FROM receipts"
        ))
    finally:
        connection.close()
    assert len(stored) == 1
    reply_to, task_json, digested_at = stored[0]
    assert reply_to == "original"
    assert json.loads(task_json)["status"] == "running"
    assert digested_at is None


# ---------------------------------------------------------------------------
# Oversized envelope: the whole point of the explicit columns
# ---------------------------------------------------------------------------


def test_oversized_envelope_pairing_survives_in_ledger_and_legacy_drops(seeded):
    dispatch = _dispatch_row("original", status="consumed")
    dispatch["metadata"] = {"sourceSessionId": "assistant-session"}
    _write_inbox(seeded, TARGET_ID, [dispatch])
    # A >8192-char envelope: the JSONL read path drops these keys wholesale.
    envelope = _task_envelope("completed")
    envelope["padding"] = "x" * 9000
    receipt = _receipt_row(
        "receipt-big",
        envelope=envelope,
        metadata={"sourceSessionId": "target-session"},
    )
    _write_inbox(seeded, ASSISTANT_ID, [receipt])

    legacy_metadata = dispatches_service._metadata(receipt)
    assert "replyToMessageId" not in legacy_metadata
    assert "personalAssistantTask" not in legacy_metadata

    payload = dispatches_service.list_personal_assistant_dispatches(limit=10)
    dispatch_view = payload["dispatches"][0]
    assert dispatch_view["taskStatus"] == "completed"
    assert dispatch_view["receipts"][0]["taskStatus"] == "completed"
    assert payload["unmatchedReceipts"] == []


# ---------------------------------------------------------------------------
# Harvest: change-driven, idempotent, truth-repairing
# ---------------------------------------------------------------------------


def test_harvest_is_idempotent_and_repeats_repair_status(seeded):
    original = _dispatch_row("dispatch-1", status="pending")
    _write_inbox(seeded, TARGET_ID, [original])
    _write_inbox(seeded, ASSISTANT_ID, [
        _receipt_row("receipt-1", reply_to="dispatch-1"),
    ])

    assert ledger.ensure_harvested(ASSISTANT_ID) is True
    path = ledger.ledger_database_path()
    first_stat = path.stat()
    connection = sqlite3.connect(str(path))
    try:
        count_one = int(connection.execute("SELECT COUNT(*) FROM dispatches").fetchone()[0])
    finally:
        connection.close()

    assert ledger.ensure_harvested(ASSISTANT_ID) is True
    connection = sqlite3.connect(str(path))
    try:
        count_two = int(connection.execute("SELECT COUNT(*) FROM dispatches").fetchone()[0])
    finally:
        connection.close()
    assert count_one == count_two == 1
    # Signature unchanged: no rewrite happened on the steady-state path.
    assert path.stat().st_mtime_ns == first_stat.st_mtime_ns

    # JSONL is the truth: mutate the row and touch the file; the next
    # harvest repairs the ledger status.
    original["status"] = "revoked"
    _write_inbox(seeded, TARGET_ID, [original])
    assert ledger.ensure_harvested(ASSISTANT_ID) is True
    connection = sqlite3.connect(str(path))
    try:
        status = connection.execute(
            "SELECT status FROM dispatches WHERE message_id='dispatch-1'"
        ).fetchone()[0]
    finally:
        connection.close()
    assert status == "revoked"


def test_new_inbox_row_is_harvested_on_signature_change(seeded):
    _write_inbox(seeded, TARGET_ID, [_dispatch_row("dispatch-1")])
    assert ledger.ensure_harvested(ASSISTANT_ID) is True

    _write_inbox(seeded, TARGET_ID, [
        _dispatch_row("dispatch-1"),
        _dispatch_row("dispatch-2", created_at="2026-10-20T10:05:00+00:00"),
    ])
    assert ledger.ensure_harvested(ASSISTANT_ID) is True
    view = ledger.read_dispatch_view(ASSISTANT_ID, window=10, receipt_window=20)
    assert view is not None
    assert [row["messageId"] for row in view["dispatches"]] == ["dispatch-2", "dispatch-1"]


def test_pa_identity_change_wipes_previous_rows(seeded):
    _write_inbox(seeded, TARGET_ID, [_dispatch_row("dispatch-1")])
    assert ledger.ensure_harvested(ASSISTANT_ID) is True

    _seed_agents(seeded, [
        _agent_row("new-assistant", is_assistant=True),
        _agent_row(TARGET_ID),
    ])
    ledger.reset_identity_memo()
    assert ledger.ensure_harvested("new-assistant") is True
    connection = sqlite3.connect(str(ledger.ledger_database_path()))
    try:
        assert int(connection.execute("SELECT COUNT(*) FROM dispatches").fetchone()[0]) == 0
        marker = connection.execute("SELECT pa_agent_id FROM ledger_meta").fetchone()[0]
    finally:
        connection.close()
    assert marker == "new-assistant"


def test_degraded_harvest_blocks_thread_pairing(seeded):
    _write_inbox(seeded, TARGET_ID, [
        _dispatch_row("dispatch-partial"),
    ], raw_lines=["{malformed"])
    _write_inbox(seeded, ASSISTANT_ID, [
        _receipt_row("receipt-partial", thread_id=_dispatch_row("dispatch-partial")["threadId"]),
    ])
    payload = dispatches_service.list_personal_assistant_dispatches(limit=10)
    assert payload["dispatches"][0]["receipts"] == []
    assert [row["messageId"] for row in payload["unmatchedReceipts"]] == ["receipt-partial"]


def test_duplicate_visible_rows_pair_single_instance_reject_two(seeded):
    # Legacy window semantics count instances: with one instance visible the
    # unique thread dispatch pairs; with both duplicate instances visible the
    # ambiguity refuses the pairing (mirrors the JSONL path exactly).
    first = _dispatch_row("dispatch-duplicate", created_at="2026-10-20T10:00:00+00:00")
    second = dict(first, created_at="2026-10-20T10:01:00+00:00")
    _write_inbox(seeded, TARGET_ID, [first, second])
    _write_inbox(seeded, ASSISTANT_ID, [
        _receipt_row("receipt-dup", thread_id=first["threadId"]),
    ])

    one_visible = dispatches_service.list_personal_assistant_dispatches(limit=1)
    assert [row["messageId"] for row in one_visible["dispatches"]] == ["dispatch-duplicate"]
    assert [row["messageId"] for row in one_visible["dispatches"][0]["receipts"]] == [
        "receipt-dup",
    ]

    both_visible = dispatches_service.list_personal_assistant_dispatches(limit=2)
    assert [row["messageId"] for row in both_visible["dispatches"]] == [
        "dispatch-duplicate", "dispatch-duplicate",
    ]
    assert all(view["receipts"] == [] for view in both_visible["dispatches"])
    assert [row["messageId"] for row in both_visible["unmatchedReceipts"]] == ["receipt-dup"]


def test_chase_reply_pairs_to_origin_only_from_authoritative_inbox(seeded):
    original = _dispatch_row("original")
    followup = dict(
        _dispatch_row("followup", kind="pa_followup", thread=original["threadId"]),
        metadata={"paFollowupOfMessageId": "original"},
    )
    _write_inbox(seeded, TARGET_ID, [original, followup])
    _write_inbox(seeded, ASSISTANT_ID, [
        _receipt_row("receipt", reply_to="followup"),
    ])
    payload = dispatches_service.list_personal_assistant_dispatches(limit=10)
    assert [row["messageId"] for row in payload["dispatches"][0]["receipts"]] == ["receipt"]

    # The same chase planted in a foreign inbox loses its authority.
    _write_inbox(seeded, TARGET_ID, [original])
    _write_inbox(seeded, OTHER_ID, [followup])
    payload = dispatches_service.list_personal_assistant_dispatches(limit=10)
    assert payload["dispatches"][0]["receipts"] == []
    assert [row["messageId"] for row in payload["unmatchedReceipts"]] == ["receipt"]


def test_chase_with_mismatched_thread_stays_unmatched(seeded):
    original = _dispatch_row("original")
    followup = dict(
        _dispatch_row("followup", kind="pa_followup", thread="unrelated-thread"),
        metadata={"paFollowupOfMessageId": "original"},
    )
    _write_inbox(seeded, TARGET_ID, [original, followup])
    _write_inbox(seeded, ASSISTANT_ID, [
        _receipt_row("receipt", reply_to="followup"),
    ])
    payload = dispatches_service.list_personal_assistant_dispatches(limit=10)
    assert payload["dispatches"][0]["receipts"] == []
    assert [row["messageId"] for row in payload["unmatchedReceipts"]] == ["receipt"]


# ---------------------------------------------------------------------------
# Read model: ledger-first with JSONL fallback, and late visibility
# ---------------------------------------------------------------------------


def test_read_model_ledger_view_matches_legacy_path(seeded):
    original = _dispatch_row("original", status="consumed")
    original["metadata"] = {"sourceSessionId": "assistant-session"}
    _write_inbox(seeded, TARGET_ID, [original])
    _write_inbox(seeded, ASSISTANT_ID, [
        _receipt_row("receipt-thread", thread_id=original["threadId"]),
        _receipt_row("receipt-explicit", reply_to="original",
                     created_at="2026-10-20T11:30:00+00:00"),
        _receipt_row("receipt-foreign", source_agent=OTHER_ID),
    ])

    ledger_view = dispatches_service.list_personal_assistant_dispatches(limit=10)

    original_fallback = ledger.ensure_harvested
    try:
        ledger.ensure_harvested = lambda *_a, **_k: False
        legacy_view = dispatches_service.list_personal_assistant_dispatches(limit=10)
    finally:
        ledger.ensure_harvested = original_fallback

    assert ledger_view["dispatches"] == legacy_view["dispatches"]
    assert ledger_view["unmatchedReceipts"] == legacy_view["unmatchedReceipts"]
    assert [row["messageId"] for row in legacy_view["dispatches"]] == ["original"]
    assert [row["messageId"] for row in legacy_view["dispatches"][0]["receipts"]] == [
        "receipt-thread", "receipt-explicit",
    ]


def test_late_receipt_outside_window_still_pairs_and_terminal_survives(seeded):
    original = _dispatch_row("original", status="consumed")
    original["metadata"] = {"sourceSessionId": "assistant-session"}
    _write_inbox(seeded, TARGET_ID, [original])
    # Push the completed receipt far outside the legacy receipt window:
    # 150 newer unrelated rows in the assistant inbox.
    filler = [
        _receipt_row(f"noise-{index:03d}", source_agent=OTHER_ID,
                     created_at=f"2026-10-20T12:{index // 60:02d}:{index % 60:02d}+00:00")
        for index in range(150)
    ]
    _write_inbox(seeded, ASSISTANT_ID, [
        _receipt_row(
            "receipt-completed",
            envelope=_task_envelope("completed"),
            metadata={"sourceSessionId": "target-session"},
        ),
        *filler,
    ])

    payload = dispatches_service.list_personal_assistant_dispatches(limit=50)
    dispatch_view = payload["dispatches"][0]
    assert dispatch_view["taskStatus"] == "completed"
    assert [row["messageId"] for row in dispatch_view["receipts"]] == ["receipt-completed"]

    try:
        original_harvest = ledger.ensure_harvested
        ledger.ensure_harvested = lambda *_a, **_k: False
        legacy_payload = dispatches_service.list_personal_assistant_dispatches(limit=50)
    finally:
        ledger.ensure_harvested = original_harvest
    assert legacy_payload["dispatches"][0]["taskStatus"] in {"running", "awaiting_result"}


def test_status_hooks_flow_through_directory_writes(seeded):
    dispatch_message = directory.write_agent_inbox_message(
        TARGET_ID,
        content="dispatch body",
        source_agent_id=ASSISTANT_ID,
        source_session_id="assistant-session",
        kind="agent_message",
        summary="dispatch summary",
        target_session_id="target-session",
        metadata={"sourceSessionId": "assistant-session"},
    )
    dispatch_message_id = dispatch_message["messageId"]
    assert dispatch_message_id

    # Oversized envelope through the real hook: the explicit columns must
    # capture what the JSONL read path would drop.
    envelope = _task_envelope("running", dispatch_id=dispatch_message_id)
    envelope["padding"] = "x" * 9000
    directory.write_agent_inbox_message(
        ASSISTANT_ID,
        content="receipt body",
        source_agent_id=TARGET_ID,
        kind="agent_inbox_message",
        summary="receipt summary",
        metadata={
            "sourceSessionId": "target-session",
            "targetSessionId": "assistant-session",
            "agentToolMetadataJson": json.dumps(envelope),
        },
    )

    payload = dispatches_service.list_personal_assistant_dispatches(limit=10)
    dispatch_view = payload["dispatches"][0]
    assert dispatch_view["messageId"] == dispatch_message_id
    assert dispatch_view["taskStatus"] == "running"
    assert dispatch_view["receipts"][0]["taskStatus"] == "running"

    directory.consume_agent_inbox_message(TARGET_ID, dispatch_message_id)
    payload = dispatches_service.list_personal_assistant_dispatches(limit=10)
    assert payload["dispatches"][0]["deliveryStatus"] == "consumed"

    directory.revoke_agent_inbox_message(TARGET_ID, dispatch_message_id, reason="done")
    payload = dispatches_service.list_personal_assistant_dispatches(limit=10)
    assert payload["dispatches"][0]["deliveryStatus"] == "revoked"
    assert payload["dispatches"][0]["taskStatus"] == "cancelled"


# ---------------------------------------------------------------------------
# 批三 patrol: wake reservation state machine, digest marking, pairing queries
# ---------------------------------------------------------------------------


def _seed_live_dispatch(seeded, *, status: str = "pending") -> dict:
    dispatch = _dispatch_row("dispatch-live", status=status)
    _write_inbox(seeded, TARGET_ID, [dispatch])
    assert ledger.ensure_harvested(ASSISTANT_ID)
    return dispatch


def test_v1_database_migrates_to_v2_wake_attempts(seeded):
    _seed_live_dispatch(seeded)
    path = ledger.ledger_database_path()
    connection = sqlite3.connect(str(path))
    try:
        connection.execute("DROP TABLE wake_attempts")
        connection.execute("PRAGMA user_version=1")
        connection.commit()
    finally:
        connection.close()

    # The next writable open migrates in place; rows survive.
    assert ledger.ensure_harvested(ASSISTANT_ID) is True
    connection = sqlite3.connect(str(path))
    try:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table'"
            )
        }
    finally:
        connection.close()
    assert version == ledger.SCHEMA_VERSION == 2
    assert "wake_attempts" in names


def test_wake_attempt_state_machine_drives_throttle_and_coverage(seeded):
    _seed_live_dispatch(seeded)
    reserved_ms = int(time.time() * 1000) - 1000
    token = ledger.reserve_wake(
        ["receipt-1"], reserved_at="2026-11-01T00:00:00+00:00", reserved_at_ms=reserved_ms
    )
    # Reserved intent blocks re-wake before any submission happened.
    assert ledger.wake_covered_receipt_ids() == {"receipt-1": "reserved"}
    assert ledger.recent_wake_submissions(
        window_ms=3_600_000, now_ms=reserved_ms + 500
    ) == []

    # Provably not submitted: retryable, no quota.
    assert ledger.complete_wake(
        token, state="cancelled_pre_admission", reason="skipped_busy"
    ) is True
    assert ledger.wake_covered_receipt_ids() == {}
    assert ledger.recent_wake_submissions(
        window_ms=3_600_000, now_ms=reserved_ms + 500
    ) == []

    # Retry, then a real submission: quota stamped, coverage non-retryable.
    token2 = ledger.reserve_wake(
        ["receipt-1"], reserved_at="2026-11-01T00:00:01+00:00", reserved_at_ms=reserved_ms + 1000
    )
    assert ledger.complete_wake(
        token2, state="accepted", submitted_at_ms=reserved_ms + 1500
    ) is True
    assert ledger.recent_wake_submissions(
        window_ms=3_600_000, now_ms=reserved_ms + 2000
    ) == [reserved_ms + 1500]
    assert ledger.wake_covered_receipt_ids() == {"receipt-1": "accepted"}

    # A settled attempt can never be downgraded by a late completion.
    assert ledger.complete_wake(token2, state="cancelled_pre_admission") is False
    connection = sqlite3.connect(str(ledger.ledger_database_path()))
    try:
        state = connection.execute(
            "SELECT state FROM wake_attempts WHERE attempt_id=?", (token2,)
        ).fetchone()[0]
    finally:
        connection.close()
    assert state == "accepted"


def test_reserved_rows_survive_restart_and_unknown_consumes_quota(seeded):
    _seed_live_dispatch(seeded)
    reserved_ms = int(time.time() * 1000) - 1000
    token = ledger.reserve_wake(
        ["receipt-1"], reserved_at="2026-11-01T00:00:00+00:00", reserved_at_ms=reserved_ms
    )
    # Crash before completion: the reservation still blocks re-wake ...
    assert ledger.wake_covered_receipt_ids() == {"receipt-1": "reserved"}
    # ... and settling it as unknown stamps the throttle quota.
    assert ledger.complete_wake(
        token, state="unknown", reason="RuntimeError", submitted_at_ms=reserved_ms
    ) is True
    assert ledger.recent_wake_submissions(
        window_ms=3_600_000, now_ms=reserved_ms + 1
    ) == [reserved_ms]
    assert ledger.wake_covered_receipt_ids() == {"receipt-1": "unknown"}


def test_reserve_prunes_old_cancelled_rows(seeded):
    _seed_live_dispatch(seeded)
    now_ms = int(time.time() * 1000)
    token = ledger.reserve_wake(
        ["receipt-1"], reserved_at="2026-11-01T00:00:00+00:00", reserved_at_ms=now_ms
    )
    assert ledger.complete_wake(token, state="cancelled_pre_admission") is True
    connection = sqlite3.connect(str(ledger.ledger_database_path()))
    try:
        connection.execute(
            "UPDATE wake_attempts SET updated_at_ms=? WHERE attempt_id=?",
            (now_ms - 2 * 3600 * 1000, token),
        )
        connection.commit()
    finally:
        connection.close()
    ledger.reserve_wake(
        ["receipt-2"], reserved_at="2026-11-01T00:00:01+00:00", reserved_at_ms=now_ms + 1000
    )
    connection = sqlite3.connect(str(ledger.ledger_database_path()))
    try:
        states = [row[0] for row in connection.execute("SELECT state FROM wake_attempts")]
    finally:
        connection.close()
    assert states == ["reserved"]  # the stale cancelled row was pruned


def test_mark_receipts_digested_is_all_rows_never_regresses(seeded):
    _seed_live_dispatch(seeded)
    _write_inbox(seeded, ASSISTANT_ID, [
        _receipt_row("receipt-1", reply_to="dispatch-live"),
        _receipt_row("receipt-2", reply_to="dispatch-live"),
    ])
    assert ledger.ensure_harvested(ASSISTANT_ID)

    stamp = "2026-11-01T00:00:00+00:00"
    assert ledger.mark_receipts_digested(
        ["receipt-1", "receipt-2", "ghost"], digested_at=stamp
    ) == 2
    # Replay: digested_at never regresses, nothing double-stamps.
    assert ledger.mark_receipts_digested(
        ["receipt-1", "receipt-2"], digested_at="2026-11-02T00:00:00+00:00"
    ) == 0
    connection = sqlite3.connect(str(ledger.ledger_database_path()))
    try:
        rows = dict(connection.execute(
            "SELECT message_id, digested_at FROM receipts"
        ))
    finally:
        connection.close()
    assert rows == {"receipt-1": stamp, "receipt-2": stamp}


def test_undigested_wake_receipts_pairing_matrix(seeded):
    live = _dispatch_row("dispatch-live", status="pending")
    revoked = _dispatch_row("dispatch-revoked", status="revoked")
    followup = dict(
        _dispatch_row("followup-1", kind="pa_followup", thread=live["threadId"]),
        metadata={"paFollowupOfMessageId": "dispatch-live"},
    )
    _write_inbox(seeded, TARGET_ID, [live, revoked, followup])
    _write_inbox(seeded, ASSISTANT_ID, [
        _receipt_row("receipt-direct", reply_to="dispatch-live"),
        _receipt_row("receipt-chase", reply_to="followup-1"),
        _receipt_row("receipt-thread", thread_id=live["threadId"]),
        # Revoked dispatch reply: not a live dispatch, never wakes.
        _receipt_row("receipt-revoked", reply_to="dispatch-revoked"),
        # Unpaired chatter: digest material at most, never a wake.
        _receipt_row("receipt-orphan"),
        # Already consumed upstream: not undigested.
        _receipt_row("receipt-consumed", reply_to="dispatch-live", status="consumed"),
    ])
    assert ledger.ensure_harvested(ASSISTANT_ID)

    paired = {
        row["messageId"] for row in ledger.undigested_wake_receipts(ASSISTANT_ID)
    }
    assert paired == {"receipt-direct", "receipt-chase", "receipt-thread"}

    # Digestion removes a receipt from the wake set without touching status.
    assert ledger.mark_receipts_digested(
        ["receipt-direct"], digested_at="2026-11-01T00:00:00+00:00"
    ) == 1
    paired = {
        row["messageId"] for row in ledger.undigested_wake_receipts(ASSISTANT_ID)
    }
    assert paired == {"receipt-chase", "receipt-thread"}


def test_undigested_wake_receipts_thread_pairing_excludes_revoked(seeded):
    live = _dispatch_row("dispatch-live", status="revoked")
    _write_inbox(seeded, TARGET_ID, [live])
    _write_inbox(seeded, ASSISTANT_ID, [
        _receipt_row("receipt-thread", thread_id=live["threadId"]),
    ])
    assert ledger.ensure_harvested(ASSISTANT_ID)
    assert ledger.undigested_wake_receipts(ASSISTANT_ID) == []


def test_dispatch_envelope_verdict_replaces_strict_scan(seeded):
    dispatch = _dispatch_row("dispatch-1", metadata={"sourceSessionId": "assistant-session"})
    # Unknown id before anything is recorded: the ledger cannot answer.
    assert ledger.dispatch_envelope_is_current(
        "dispatch-1", source_agent_id=ASSISTANT_ID, target_agent_id=TARGET_ID,
        target_session_id="target-session", source_session_id="assistant-session",
        thread_id=dispatch["threadId"],
    ) is None

    _write_inbox(seeded, TARGET_ID, [dispatch])
    assert ledger.ensure_harvested(ASSISTANT_ID)

    def verdict(**changes):
        fields = {
            "source_agent_id": ASSISTANT_ID,
            "target_agent_id": TARGET_ID,
            "target_session_id": "target-session",
            "source_session_id": "assistant-session",
            "thread_id": dispatch["threadId"],
        }
        fields.update(changes)
        return ledger.dispatch_envelope_is_current("dispatch-1", **fields)

    assert verdict() is True
    assert verdict(source_session_id="other-session") is False
    assert verdict(thread_id="other-thread") is False
    assert verdict(target_session_id="other-session") is False

    # Revocation lands in the ledger (JSONL truth) → not current anymore.
    _write_inbox(seeded, TARGET_ID, [_dispatch_row("dispatch-1", status="revoked",
                                                   metadata={"sourceSessionId": "assistant-session"})])
    assert ledger.ensure_harvested(ASSISTANT_ID)
    assert verdict() is False

    # Unknown id: the ledger cannot answer → caller falls back to JSONL.
    assert ledger.dispatch_envelope_is_current(
        "missing", source_agent_id=ASSISTANT_ID, target_agent_id=TARGET_ID,
        target_session_id="target-session", source_session_id="assistant-session",
        thread_id=dispatch["threadId"],
    ) is None
