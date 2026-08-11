"""SQLite control-plane admission for journal-backed session submissions.

This module intentionally has no journal writer dependency.  Its caller must
reserve first, append the canonical journal event, and then acknowledge the
journal sequence.  This keeps SQLite from becoming a second conversation or
tool transcript while preserving retry-safe admission identity.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from core.chat.conversation_store.repository import ConversationRepository


@dataclass
class _AdmissionLockEntry:
    lock: threading.Lock
    users: int = 0


_ADMISSION_LOCKS_GUARD = threading.Lock()
_ADMISSION_LOCKS: dict[tuple[str, str], _AdmissionLockEntry] = {}


@contextmanager
def _admission_lock(session_id: str, client_submission_id: str) -> Iterator[None]:
    """Serialize the non-transactional journal bridge without retaining locks."""

    key = (session_id, client_submission_id)
    with _ADMISSION_LOCKS_GUARD:
        entry = _ADMISSION_LOCKS.get(key)
        if entry is None:
            entry = _AdmissionLockEntry(lock=threading.Lock())
            _ADMISSION_LOCKS[key] = entry
        entry.users += 1
    entry.lock.acquire()
    try:
        yield
    finally:
        entry.lock.release()
        with _ADMISSION_LOCKS_GUARD:
            entry.users -= 1
            if entry.users == 0 and _ADMISSION_LOCKS.get(key) is entry:
                _ADMISSION_LOCKS.pop(key, None)


class SessionSubmissionAdmissionService:
    """Small orchestration façade for the T3 control-plane contract."""

    def __init__(self, repository: ConversationRepository) -> None:
        self._repository = repository

    def reserve(
        self,
        *,
        session_id: str,
        agent_id: str,
        agent_config_revision_id: str,
        client_submission_id: str,
        turn_id: str,
        expires_at_ms: int | None = None,
    ) -> dict[str, Any]:
        return self._repository.reserve_submission_admission(
            session_id=session_id,
            agent_id=agent_id,
            agent_config_revision_id=agent_config_revision_id,
            client_submission_id=client_submission_id,
            turn_id=turn_id,
            expires_at_ms=expires_at_ms,
        ).result(timeout=3)

    def mark_journaled(
        self,
        *,
        session_id: str,
        client_submission_id: str,
        journal_sequence: int,
        journal_event_id: str,
    ) -> dict[str, Any]:
        return self._repository.mark_submission_journaled(
            session_id=session_id,
            client_submission_id=client_submission_id,
            journal_sequence=journal_sequence,
            journal_event_id=journal_event_id,
        ).result(timeout=3)

    def mark_projected(
        self,
        *,
        session_id: str,
        client_submission_id: str,
        journal_sequence: int,
    ) -> dict[str, Any]:
        return self._repository.mark_submission_projected(
            session_id=session_id,
            client_submission_id=client_submission_id,
            journal_sequence=journal_sequence,
        ).result(timeout=3)

    def admit_to_journal(
        self,
        *,
        session_id: str,
        agent_id: str,
        agent_config_revision_id: str,
        client_submission_id: str,
        turn_id: str,
        journal_lookup: Callable[[dict[str, Any]], Mapping[str, Any] | None],
        journal_append: Callable[[dict[str, Any]], Mapping[str, Any]],
        expires_at_ms: int | None = None,
    ) -> dict[str, Any]:
        """Reserve once, append/recover one journal acknowledgment, then mark it.

        The callback boundary is deliberate: it keeps journal authoritative and
        allows the future live submit path to reuse its existing append logic
        rather than duplicating any message, tool, or terminal persistence here.
        """

        reserved = self.reserve(
            session_id=session_id,
            agent_id=agent_id,
            agent_config_revision_id=agent_config_revision_id,
            client_submission_id=client_submission_id,
            turn_id=turn_id,
            expires_at_ms=expires_at_ms,
        )
        normalized_submission_id = str(reserved["clientSubmissionId"])
        normalized_session_id = str(reserved["sessionId"])
        with _admission_lock(normalized_session_id, normalized_submission_id):
            current = self._repository.get_submission_admission(
                session_id=normalized_session_id,
                client_submission_id=normalized_submission_id,
            )
            if current is None:
                raise RuntimeError("Submission admission disappeared before journal append.")
            if current["state"] != "reserved":
                return {**current, "journalDisposition": "already_journaled"}

            receipt = journal_lookup(current)
            disposition = "recovered"
            if receipt is None:
                receipt = journal_append(current)
                disposition = "appended"
            journal_sequence, journal_event_id = _journal_receipt(receipt)
            journaled = self.mark_journaled(
                session_id=normalized_session_id,
                client_submission_id=normalized_submission_id,
                journal_sequence=journal_sequence,
                journal_event_id=journal_event_id,
            )
            return {**journaled, "journalDisposition": disposition}


def _journal_receipt(receipt: Mapping[str, Any]) -> tuple[int, str]:
    journal_sequence = int(receipt.get("journalSequence") or 0)
    journal_event_id = str(receipt.get("journalEventId") or "").strip()
    if journal_sequence < 1 or not journal_event_id:
        raise ValueError("Journal append must return a positive sequence and event id.")
    return journal_sequence, journal_event_id
