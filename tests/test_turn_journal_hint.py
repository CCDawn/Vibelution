"""Tests for the recovery sidecar hint written beside a turn journal."""

from __future__ import annotations

import json
from pathlib import Path

from core.chat.turn_journal_hint import (
    HINT_FILENAME,
    HINT_SCHEMA_VERSION,
    hint_matches_journal,
    journal_hint_path,
    read_journal_hint,
    write_journal_hint,
)


def _journal(tmp_path: Path, payload: str = '{"a":1}\n') -> Path:
    path = tmp_path / "session-a" / "turn_journal.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    return path


def test_hint_lives_beside_the_journal(tmp_path: Path) -> None:
    journal = _journal(tmp_path)

    assert journal_hint_path(journal) == journal.parent / HINT_FILENAME


def test_hint_records_the_journal_signature_it_describes(tmp_path: Path) -> None:
    journal = _journal(tmp_path)

    write_journal_hint(
        journal,
        turn_id="turn-1",
        turn_state="terminal",
        terminal_type="turn_completed",
        event_type="turn_completed",
        sequence=7,
    )

    hint = read_journal_hint(journal)
    assert hint is not None
    assert hint["schemaVersion"] == HINT_SCHEMA_VERSION
    assert hint["turnId"] == "turn-1"
    assert hint["turnState"] == "terminal"
    assert hint["terminalType"] == "turn_completed"
    assert hint["sequence"] == 7
    assert hint_matches_journal(journal, hint) is True


def test_appending_the_journal_makes_the_hint_stale(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    write_journal_hint(
        journal,
        turn_id="turn-1",
        turn_state="terminal",
        terminal_type="turn_completed",
        event_type="turn_completed",
    )
    hint = read_journal_hint(journal)
    assert hint is not None

    with journal.open("a", encoding="utf-8") as handle:
        handle.write('{"b":2}\n')

    assert hint_matches_journal(journal, hint) is False


def test_missing_or_damaged_hint_reads_as_none(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    assert read_journal_hint(journal) is None

    journal_hint_path(journal).write_text("{not json", encoding="utf-8")
    assert read_journal_hint(journal) is None

    journal_hint_path(journal).write_text(
        json.dumps({"schemaVersion": 99}), encoding="utf-8"
    )
    assert read_journal_hint(journal) is None


def test_hint_write_survives_a_missing_journal(tmp_path: Path) -> None:
    journal = tmp_path / "session-a" / "turn_journal.jsonl"

    write_journal_hint(
        journal,
        turn_id="turn-1",
        turn_state="open",
        terminal_type="",
        event_type="turn_started",
    )

    assert not journal_hint_path(journal).exists()


def test_hint_write_refuses_a_journal_that_moved(tmp_path: Path) -> None:
    journal = tmp_path / "session-moved" / "turn_journal.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text("{}\n", encoding="utf-8")
    stat = journal.stat()
    signature = (int(stat.st_mtime_ns), int(stat.st_size))

    write_journal_hint(
        journal,
        turn_id="turn-1",
        turn_state="terminal",
        terminal_type="turn_completed",
        event_type="turn_completed",
        sequence=1,
        expected_signature=(signature[0], signature[1] + 1),
    )
    assert not journal_hint_path(journal).exists()

    write_journal_hint(
        journal,
        turn_id="turn-1",
        turn_state="terminal",
        terminal_type="turn_completed",
        event_type="turn_completed",
        sequence=1,
        expected_signature=signature,
    )
    hint = read_journal_hint(journal)
    assert hint is not None
    assert hint["terminalType"] == "turn_completed"
