"""Stale "starting" queued-turn recovery (crash between claim and settle).

A queued turn claimed by ``_claim_next_queued_turn`` is parked in "starting"
until its turn settles. If the process dies in between, no drain ever picks
the row again because selection only takes "queued" rows. These tests lock
the recovery path: stale "starting" rows are reset to "queued" before
selection, fresh ones are never touched, and the reset is a no-op without
side effects when nothing is stale.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from core.infrastructure import developer_sandbox
from core.ui.chat_state import load_session_chat_state, save_chat_state
from core.web.services import session_service
from core.web.services.session import queued_turns

SESSION_ID = "session-a"


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)


@pytest.fixture
def published_sessions(tmp_path, monkeypatch) -> list[str]:
    monkeypatch.setattr(session_service, "PROJECT_ROOT", Path(tmp_path))
    monkeypatch.setattr(session_service, "_is_session_running", lambda session_id: False)
    published: list[str] = []
    monkeypatch.setattr(
        session_service,
        "_publish_session_detail_snapshot",
        lambda session_id, **_kwargs: published.append(str(session_id)),
    )
    return published


def _timestamp(age: timedelta | None) -> str:
    moment = datetime.now(timezone.utc) if age is None else datetime.now(timezone.utc) - age
    return moment.isoformat(timespec="seconds")


def _turn_row(turn_id: str, *, status: str = "queued", age: timedelta | None = None) -> dict[str, Any]:
    timestamp = _timestamp(age)
    return {
        "id": turn_id,
        "clientSubmissionId": f"sub-{turn_id}",
        "content": f"content-{turn_id}",
        "attachments": [],
        "references": [],
        "mentalModelEnabled": False,
        "runtimeStatusEnabled": False,
        "turnMode": "",
        "writeIntent": False,
        "status": status,
        "createdAt": timestamp,
        "updatedAt": timestamp,
    }


def _seed_conversation(tmp_path, rows: list[dict[str, Any]]) -> None:
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": SESSION_ID,
            "conversations": [
                {
                    "conversation_id": SESSION_ID,
                    "title": "Queue recovery",
                    "queued_turns": rows,
                }
            ],
        },
    )


def _persisted_rows(tmp_path) -> list[dict[str, Any]]:
    conversation = load_session_chat_state(tmp_path, SESSION_ID)
    return queued_turns.session_queued_turn_rows(conversation)


def test_reset_stale_starting_rows_resets_only_stale_rows(published_sessions):
    stale_age = timedelta(seconds=queued_turns.STARTING_CLAIM_STALE_SECONDS + 60)
    rows = [
        _turn_row("turn-stale", status="starting", age=stale_age),
        _turn_row("turn-fresh", status="starting", age=timedelta(minutes=1)),
        _turn_row("turn-queued", status="queued"),
    ]
    stale_timestamp = rows[0]["updatedAt"]
    fresh_timestamp = rows[1]["updatedAt"]

    changed = queued_turns._reset_stale_starting_rows(session_service, rows)

    assert changed is True
    assert [row["status"] for row in rows] == ["queued", "starting", "queued"]
    # The reset refreshes updatedAt so the next pass sees a fresh row.
    assert rows[0]["updatedAt"] != stale_timestamp
    # The fresh "starting" row keeps its original timestamp.
    assert rows[1]["updatedAt"] == fresh_timestamp


def test_stale_starting_row_is_reset_and_claimed_before_selection(tmp_path, published_sessions):
    _seed_conversation(
        tmp_path,
        [_turn_row("turn-stale", status="starting", age=timedelta(minutes=11))],
    )

    claimed = queued_turns._claim_next_queued_turn(SESSION_ID)

    # Selection only takes "queued" rows, so a claim proves the stale row was
    # reset to "queued" first; it is then re-claimed like any other turn.
    assert claimed is not None
    assert claimed["id"] == "turn-stale"
    rows = _persisted_rows(tmp_path)
    assert [(row["id"], row["status"]) for row in rows] == [("turn-stale", "starting")]
    assert published_sessions == [SESSION_ID]


def test_unparseable_starting_timestamp_is_treated_as_stale(tmp_path, published_sessions):
    row = _turn_row("turn-stale", status="starting")
    row["updatedAt"] = "not-a-timestamp"
    _seed_conversation(tmp_path, [row])

    claimed = queued_turns._claim_next_queued_turn(SESSION_ID)

    assert claimed is not None
    assert claimed["id"] == "turn-stale"


def test_fresh_starting_row_is_untouched_and_blocks_claim(tmp_path, published_sessions):
    _seed_conversation(
        tmp_path,
        [_turn_row("turn-live", status="starting", age=timedelta(minutes=1))],
    )
    seeded_timestamp = _persisted_rows(tmp_path)[0]["updatedAt"]

    claimed = queued_turns._claim_next_queued_turn(SESSION_ID)

    assert claimed is None
    rows = _persisted_rows(tmp_path)
    assert [(row["id"], row["status"]) for row in rows] == [("turn-live", "starting")]
    # Untouched: no reset write refreshed the row.
    assert rows[0]["updatedAt"] == seeded_timestamp
    assert published_sessions == []


def test_fresh_starting_row_does_not_block_next_queued_turn(tmp_path, published_sessions):
    _seed_conversation(
        tmp_path,
        [
            _turn_row("turn-live", status="starting", age=timedelta(minutes=1)),
            _turn_row("turn-next", status="queued"),
        ],
    )

    claimed = queued_turns._claim_next_queued_turn(SESSION_ID)

    assert claimed is not None
    assert claimed["id"] == "turn-next"
    rows = _persisted_rows(tmp_path)
    assert [(row["id"], row["status"]) for row in rows] == [
        ("turn-live", "starting"),
        ("turn-next", "starting"),
    ]
    # One publish covers the claim; the untouched fresh row adds no noise.
    assert published_sessions == [SESSION_ID]


def test_reset_is_noop_without_starting_rows(published_sessions):
    rows = [
        _turn_row("turn-queued", status="queued"),
        _turn_row("turn-blocked", status="blocked", age=timedelta(hours=1)),
    ]
    snapshot = [dict(row) for row in rows]

    changed = queued_turns._reset_stale_starting_rows(session_service, rows)

    assert changed is False
    assert rows == snapshot
    assert published_sessions == []


def test_claim_without_starting_rows_keeps_single_claim_publish(tmp_path, published_sessions):
    _seed_conversation(tmp_path, [_turn_row("turn-1", status="queued")])

    claimed = queued_turns._claim_next_queued_turn(SESSION_ID)

    assert claimed is not None
    assert claimed["id"] == "turn-1"
    assert published_sessions == [SESSION_ID]
