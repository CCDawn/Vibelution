"""SQLite control-plane admission for journal-backed session submissions.

This module intentionally has no journal writer dependency.  Its caller must
reserve first, append the canonical journal event, and then acknowledge the
journal sequence.  This keeps SQLite from becoming a second conversation or
tool transcript while preserving retry-safe admission identity.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.chat.conversation_store import ConversationStore
from core.chat.conversation_store.repository import ConversationRepository

DEVELOPMENT_SUBMISSION_ADMISSION_ROOT_ENV = "VIBELUTION_SESSION_SQLITE_ADMISSION_ROOT"
_DEVELOPMENT_RUNTIME_LOCK = threading.Lock()
_DEVELOPMENT_RUNTIMES: dict[str, DevelopmentSubmissionAdmissionRuntime] = {}


class DevelopmentSubmissionAdmissionConfigurationError(ValueError):
    """The explicit development-only admission store configuration is unsafe."""


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


class DevelopmentSubmissionAdmissionRuntime:
    """Opt-in development data-root bridge for journal-backed submissions.

    This is intentionally not an operator configuration or a production
    default.  It exists so one isolated runtime can exercise the real submit
    bridge without opening a SQLite file under the formal project data root.
    """

    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root).resolve()
        self.store = ConversationStore(
            self.data_root / "conversation-control" / "session_admission.sqlite3"
        )
        self.store.open()
        self.admission = SessionSubmissionAdmissionService(self.store.repository)

    def close(self) -> None:
        self.store.close()

    def existing(
        self,
        *,
        session_id: str,
        client_submission_id: str,
    ) -> dict[str, Any] | None:
        return self.store.repository.get_submission_admission(
            session_id=str(session_id).strip(),
            client_submission_id=str(client_submission_id).strip(),
        )

    def admit(
        self,
        *,
        session_id: str,
        agent: Mapping[str, Any],
        conversation: Mapping[str, Any],
        client_submission_id: str,
        turn_id: str,
        journal_lookup: Callable[[dict[str, Any]], Mapping[str, Any] | None],
        journal_append: Callable[[dict[str, Any]], Mapping[str, Any]],
    ) -> dict[str, Any]:
        agent_id = str(agent.get("agentId") or agent.get("agent_id") or "").strip()
        if not agent_id:
            raise ValueError("Development submission admission requires an Agent id.")
        control = self.store.repository.ensure_session_control_plane(
            agent_id=agent_id,
            display_name=str(agent.get("displayName") or agent.get("display_name") or agent_id),
            kind=str(agent.get("kind") or agent.get("type") or "assistant"),
            status=str(agent.get("status") or "active"),
            config=_admission_agent_config(agent),
            source="development_session_submission",
            session_id=str(session_id).strip(),
            title=str(conversation.get("title") or conversation.get("name") or ""),
        ).result(timeout=3)
        return self.admission.admit_to_journal(
            session_id=str(control["sessionId"]),
            agent_id=str(control["agentId"]),
            agent_config_revision_id=str(control["agentConfigRevisionId"]),
            client_submission_id=str(client_submission_id).strip(),
            turn_id=str(turn_id).strip(),
            journal_lookup=journal_lookup,
            journal_append=journal_append,
        )


def get_development_submission_admission_runtime(
    project_root: Path,
) -> DevelopmentSubmissionAdmissionRuntime | None:
    """Return the explicitly configured development-only control store.

    The gate is off unless its data root is supplied.  Pointing it at the
    project root is rejected to prevent a test bridge from silently becoming
    formal runtime storage.
    """

    raw_root = str(os.environ.get(DEVELOPMENT_SUBMISSION_ADMISSION_ROOT_ENV) or "").strip()
    if not raw_root:
        return None
    data_root = Path(raw_root).expanduser().resolve()
    formal_root = Path(project_root).resolve()
    if data_root == formal_root:
        raise DevelopmentSubmissionAdmissionConfigurationError(
            "Development SQLite admission data root must differ from the formal project root."
        )
    key = str(data_root)
    with _DEVELOPMENT_RUNTIME_LOCK:
        runtime = _DEVELOPMENT_RUNTIMES.get(key)
        if runtime is None:
            runtime = DevelopmentSubmissionAdmissionRuntime(data_root)
            _DEVELOPMENT_RUNTIMES[key] = runtime
        return runtime


def close_development_submission_admission_runtimes() -> None:
    """Close test/development stores without touching journal or chat data."""

    with _DEVELOPMENT_RUNTIME_LOCK:
        runtimes = list(_DEVELOPMENT_RUNTIMES.values())
        _DEVELOPMENT_RUNTIMES.clear()
    for runtime in runtimes:
        runtime.close()


def _admission_agent_config(agent: Mapping[str, Any]) -> dict[str, Any]:
    """Persist only non-secret, admission-relevant Agent identity fields."""

    return {
        key: agent[key]
        for key in (
            "agentId",
            "agent_id",
            "configRevision",
            "configHash",
            "dialogueModelId",
            "modelId",
            "profileId",
            "primaryMode",
            "roleKey",
        )
        if key in agent and agent[key] not in (None, "")
    }
