"""SQLite control-plane admission for journal-backed session submissions.

This module intentionally has no journal writer dependency.  Its caller must
reserve first, append the canonical journal event, and then acknowledge the
journal sequence.  This keeps SQLite from becoming a second conversation or
tool transcript while preserving retry-safe admission identity.
"""

from __future__ import annotations

from typing import Any

from core.chat.conversation_store.repository import ConversationRepository


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
