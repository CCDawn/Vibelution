from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.agent_plugins.virtual_human_life.mailbox import (
    cancel_mailbox_entry,
    cancel_unsent_followups,
    claim_next_mailbox_entry,
    complete_mailbox_entry,
    enqueue_mailbox_entry,
    normalize_mailbox,
    release_mailbox_entry,
)

UTC = timezone.utc


def _now(minute: int = 0) -> datetime:
    return datetime(2026, 8, 30, 0, minute, tzinfo=UTC)


def _enqueue(
    mailbox: dict,
    *,
    entry_id: str,
    source_kind: str,
    minute: int,
    generation: int = 0,
) -> tuple[dict, dict]:
    return enqueue_mailbox_entry(
        mailbox,
        entry_id=entry_id,
        session_id="session-a",
        source_kind=source_kind,
        command={"content": entry_id},
        generation=generation,
        now=_now(minute),
    )


def test_plugin_mailbox_is_idempotent_and_prioritizes_user_over_proactive() -> None:
    mailbox = normalize_mailbox(None)
    mailbox, proactive = _enqueue(
        mailbox,
        entry_id="proactive-a",
        source_kind="proactive",
        minute=0,
    )
    mailbox, user = _enqueue(
        mailbox,
        entry_id="user-a",
        source_kind="user",
        minute=1,
    )
    mailbox, retried = _enqueue(
        mailbox,
        entry_id="proactive-a",
        source_kind="proactive",
        minute=2,
    )

    assert proactive["arrivalSequence"] == 1
    assert user["arrivalSequence"] == 2
    assert retried["arrivalSequence"] == 1
    assert retried["enqueueOutcome"] == "reused"

    mailbox, first = claim_next_mailbox_entry(
        mailbox,
        session_id="session-a",
        lease_owner="dispatcher-a",
        now=_now(3),
        lease_seconds=30,
    )
    assert first is not None
    assert first["entryId"] == "user-a"
    assert first["command"] == {"content": "user-a"}

    mailbox, blocked = claim_next_mailbox_entry(
        mailbox,
        session_id="session-a",
        lease_owner="dispatcher-b",
        now=_now(3) + timedelta(seconds=1),
        lease_seconds=30,
    )
    assert blocked is None


def test_plugin_mailbox_rejects_reused_entry_id_with_conflicting_identity_or_command() -> None:
    mailbox, _ = enqueue_mailbox_entry(
        normalize_mailbox(None),
        entry_id="user:submission-a",
        session_id="session-a",
        source_kind="user",
        command={"content": "first", "clientSubmissionId": "submission-a"},
        generation=1,
        now=_now(),
    )

    for conflict in (
        {
            "session_id": "session-b",
            "source_kind": "user",
            "command": {"content": "first", "clientSubmissionId": "submission-a"},
        },
        {
            "session_id": "session-a",
            "source_kind": "followup",
            "command": {"content": "first", "clientSubmissionId": "submission-a"},
        },
        {
            "session_id": "session-a",
            "source_kind": "user",
            "command": {"content": "changed", "clientSubmissionId": "submission-a"},
        },
    ):
        with pytest.raises(ValueError, match="conflicts"):
            enqueue_mailbox_entry(
                mailbox,
                entry_id="user:submission-a",
                generation=1,
                now=_now(1),
                **conflict,
            )


def test_plugin_mailbox_matching_lease_completes_then_claims_next() -> None:
    mailbox, _ = _enqueue(
        normalize_mailbox(None),
        entry_id="user-a",
        source_kind="user",
        minute=0,
    )
    mailbox, _ = _enqueue(
        mailbox,
        entry_id="user-b",
        source_kind="user",
        minute=1,
    )
    mailbox, first = claim_next_mailbox_entry(
        mailbox,
        session_id="session-a",
        lease_owner="dispatcher-a",
        now=_now(2),
        lease_seconds=30,
    )
    assert first is not None

    with pytest.raises(ValueError, match="lease"):
        complete_mailbox_entry(
            mailbox,
            entry_id="user-a",
            lease_token="wrong",
            turn_id="turn-a",
            now=_now(3),
        )

    mailbox, completed = complete_mailbox_entry(
        mailbox,
        entry_id="user-a",
        lease_token=str(first["leaseToken"]),
        turn_id="turn-a",
        now=_now(3),
    )
    mailbox, second = claim_next_mailbox_entry(
        mailbox,
        session_id="session-a",
        lease_owner="dispatcher-a",
        now=_now(4),
        lease_seconds=30,
    )

    assert completed["state"] == "completed"
    assert completed["turnId"] == "turn-a"
    assert completed["command"] == {}
    assert len(completed["commandFingerprint"]) == 64
    assert second is not None
    assert second["entryId"] == "user-b"


def test_plugin_mailbox_reclaims_expired_dispatch_after_restart() -> None:
    mailbox, _ = _enqueue(
        normalize_mailbox(None),
        entry_id="user-a",
        source_kind="user",
        minute=0,
    )
    mailbox, first = claim_next_mailbox_entry(
        mailbox,
        session_id="session-a",
        lease_owner="old-process",
        now=_now(1),
        lease_seconds=30,
    )
    assert first is not None

    mailbox = normalize_mailbox(mailbox)
    mailbox, before_expiry = claim_next_mailbox_entry(
        mailbox,
        session_id="session-a",
        lease_owner="new-process",
        now=_now(1) + timedelta(seconds=29),
        lease_seconds=30,
    )
    mailbox, reclaimed = claim_next_mailbox_entry(
        mailbox,
        session_id="session-a",
        lease_owner="new-process",
        now=_now(1) + timedelta(seconds=31),
        lease_seconds=30,
    )

    assert before_expiry is None
    assert reclaimed is not None
    assert reclaimed["entryId"] == "user-a"
    assert reclaimed["leaseToken"] != first["leaseToken"]
    assert reclaimed["leaseAttempt"] == 2


def test_busy_native_session_releases_entry_without_changing_fifo_sequence() -> None:
    mailbox, _ = _enqueue(
        normalize_mailbox(None),
        entry_id="user-a",
        source_kind="user",
        minute=0,
    )
    mailbox, claimed = claim_next_mailbox_entry(
        mailbox,
        session_id="session-a",
        lease_owner="dispatcher-a",
        now=_now(1),
        lease_seconds=30,
    )
    assert claimed is not None

    mailbox, released = release_mailbox_entry(
        mailbox,
        entry_id="user-a",
        lease_token=str(claimed["leaseToken"]),
        reason="native_session_busy",
        now=_now(2),
    )
    mailbox, retried = claim_next_mailbox_entry(
        mailbox,
        session_id="session-a",
        lease_owner="dispatcher-b",
        now=_now(3),
        lease_seconds=30,
    )

    assert released["state"] == "queued"
    assert released["arrivalSequence"] == 1
    assert retried is not None
    assert retried["arrivalSequence"] == 1
    assert retried["leaseAttempt"] == 2


def test_new_user_generation_cancels_only_unsent_followup_bubbles() -> None:
    mailbox, _ = _enqueue(
        normalize_mailbox(None),
        entry_id="followup-old",
        source_kind="followup",
        minute=0,
        generation=1,
    )
    mailbox, _ = _enqueue(
        mailbox,
        entry_id="proactive-real-message",
        source_kind="proactive",
        minute=1,
        generation=1,
    )
    mailbox, _ = _enqueue(
        mailbox,
        entry_id="followup-current",
        source_kind="followup",
        minute=2,
        generation=2,
    )

    mailbox, cancelled = cancel_unsent_followups(
        mailbox,
        session_id="session-a",
        before_generation=2,
        reason="user_interjected",
        now=_now(3),
    )
    by_id = {entry["entryId"]: entry for entry in mailbox["entries"]}

    assert cancelled == ["followup-old"]
    assert by_id["followup-old"]["state"] == "cancelled"
    assert by_id["proactive-real-message"]["state"] == "queued"
    assert by_id["followup-current"]["state"] == "queued"


def test_user_generation_cancels_claimed_followup_before_native_admission() -> None:
    mailbox, _ = _enqueue(
        normalize_mailbox(None),
        entry_id="followup-claimed",
        source_kind="followup",
        minute=0,
        generation=1,
    )
    mailbox, claimed = claim_next_mailbox_entry(
        mailbox,
        session_id="session-a",
        lease_owner="dispatcher-a",
        now=_now(1),
        lease_seconds=30,
    )
    assert claimed is not None

    mailbox, cancelled = cancel_unsent_followups(
        mailbox,
        session_id="session-a",
        before_generation=2,
        reason="user_interjected",
        now=_now(2),
    )

    assert cancelled == ["followup-claimed"]
    assert mailbox["entries"][0]["state"] == "cancelled"
    assert mailbox["entries"][0]["leaseToken"] == ""


def test_plugin_mailbox_rejects_transcript_or_tool_payload_fields() -> None:
    with pytest.raises(ValueError, match="command"):
        enqueue_mailbox_entry(
            normalize_mailbox(None),
            entry_id="user-a",
            session_id="session-a",
            source_kind="user",
            command={"content": "hello", "turnItems": [{"kind": "tool_call"}]},
            generation=0,
            now=_now(),
        )


def test_plugin_mailbox_cancels_a_stale_claim_without_completing_a_turn() -> None:
    mailbox, _ = _enqueue(
        normalize_mailbox(None),
        entry_id="proactive-stale",
        source_kind="proactive",
        minute=0,
    )
    mailbox, claimed = claim_next_mailbox_entry(
        mailbox,
        session_id="session-a",
        lease_owner="dispatcher-a",
        now=_now(1),
        lease_seconds=30,
    )
    assert claimed is not None

    mailbox, cancelled = cancel_mailbox_entry(
        mailbox,
        entry_id="proactive-stale",
        lease_token=str(claimed["leaseToken"]),
        reason="binding_revision_changed",
        now=_now(2),
    )

    assert cancelled["state"] == "cancelled"
    assert cancelled["command"] == {}
    assert cancelled["turnId"] == ""
    assert cancelled["cancelReason"] == "binding_revision_changed"
