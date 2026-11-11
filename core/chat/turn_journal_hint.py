"""Sidecar hint that lets startup recovery judge a session without its journal.

Startup recovery only needs one fact per session: is the newest turn settled,
open, or restart-interrupted? Reading that from the journal tail costs a
32 KB+ parse per candidate, and active sessions keep multi-megabyte journals,
so the sweep spent most of its wall clock re-deriving a fact the writer
already knew at append time.

This module persists that fact next to the journal:

``<session-dir>/recovery-hint.json``

The hint is a pure derived cache. It carries the journal ``mtime``/``size``
it was written against, so any append that does not refresh it (crash, failed
write, foreign writer) simply makes it stale, and the reader falls back to the
journal tail. Losing a hint costs one tail read; it never changes a verdict.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

HINT_FILENAME = "recovery-hint.json"
HINT_SCHEMA_VERSION = 1


def journal_hint_path(journal_path: Path) -> Path:
    """Hint file sitting beside ``turn_journal.jsonl`` in the session dir."""

    return Path(journal_path).with_name(HINT_FILENAME)


def write_journal_hint(
    journal_path: Path,
    *,
    turn_id: str,
    turn_state: str,
    terminal_type: str,
    event_type: str,
    sequence: int = 0,
) -> None:
    """Record the newest turn fact plus the journal signature it describes.

    Must be called while the caller still holds the journal write lock and
    after the append landed, so ``stat`` reflects the post-append file.
    """

    path = Path(journal_path)
    try:
        stat = path.stat()
    except OSError:
        return
    payload = {
        "schemaVersion": HINT_SCHEMA_VERSION,
        "journalMtimeNs": int(stat.st_mtime_ns),
        "journalSize": int(stat.st_size),
        "turnId": str(turn_id or ""),
        "turnState": str(turn_state or ""),
        "terminalType": str(terminal_type or ""),
        "eventType": str(event_type or ""),
        "sequence": int(sequence or 0),
    }
    hint = journal_hint_path(path)
    try:
        temporary = hint.with_suffix(f"{hint.suffix}.tmp-{os.getpid()}")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, hint)
    except OSError:
        # A missing hint only costs the next sweep one journal tail read.
        return


def read_journal_hint(journal_path: Path) -> dict[str, Any] | None:
    """Parsed hint, or ``None`` when absent, damaged, or from another schema."""

    hint = journal_hint_path(journal_path)
    try:
        payload = json.loads(hint.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schemaVersion") != HINT_SCHEMA_VERSION:
        return None
    return payload


def hint_matches_journal(journal_path: Path, hint: dict[str, Any]) -> bool:
    """True when the hint still describes the current journal file state."""

    try:
        stat = Path(journal_path).stat()
    except OSError:
        return False
    try:
        return int(hint.get("journalMtimeNs") or 0) == int(stat.st_mtime_ns) and int(
            hint.get("journalSize") or 0
        ) == int(stat.st_size)
    except (TypeError, ValueError):
        return False
