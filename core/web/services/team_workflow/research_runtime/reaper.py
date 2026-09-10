"""Awaiting-approval reaper: bounded escalation and auto-rejection.

A digest-carrying meeting whose digest FAILED the auto-approve quality gate
(``hypothesis_first_chain._digest_auto_approval_block_reason`` — the same
predicate the auto-approve sweep uses) can never auto-advance: it waits for
a human forever while nothing tells the operator.  The reaper gives that
wait a bounded shape:

- ``awaiting_approval`` longer than :data:`REAPER_ESCALATION_AFTER_MS`
  (48 h) with a failed-gate digest → ONE anomaly-inbox escalation: the pure
  ``build_anomaly_inbox`` projector turns a ``digest_ttl_overdues`` entry
  into the canonical ``needs_human_gate`` item, which is persisted on a
  durable reaper-decision marker in the chain ledger (same emission pattern
  as the collection auto-retry exhaustion) plus a scene event;
- ``awaiting_approval`` longer than :data:`REAPER_REJECT_AFTER_MS` (7 d) →
  auto-reject through the EXISTING manual reject domain path
  (``meeting_rounds.reject_meeting_digest_draft`` — the same code the UI
  reject button reaches) with ``decidedBy/draftRejectedBy =
  "system:reaper"`` and an idempotency key derived from the meeting's
  closure digest content hash, so replay is a no-op.  The popped draft is
  re-drafted by the existing missing-digest sweep, exactly like a human
  rejection.

Meetings whose digest PASSED the gate stay owned by the auto-approve sweep
and are never touched; non-awaiting states and non-digest meeting types are
never touched.  The whole sweep is env-gated
(``VIBELUTION_AWAITING_APPROVAL_REAPER``, default on; ``0``/``false``/``off``
restores the purely manual contract, same pattern as
``VIBELUTION_AUTO_BUDGET_RECOVERY``) and self-throttled.  Best-effort like
every resident sweep: one broken team or meeting is isolated and counted,
nothing raises, and append-only rows are never deleted.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

#: Config gate for the reaper (default ON).  Set to ``0`` / ``false`` /
#: ``off`` to restore the purely manual rejection contract.
REAPER_KILL_SWITCH_ENV = "VIBELUTION_AWAITING_APPROVAL_REAPER"

#: Escalation threshold: an awaiting_approval meeting whose failed-gate
#: digest waited longer than this gets exactly one anomaly-inbox item.
REAPER_ESCALATION_AFTER_MS = 48 * 60 * 60 * 1000

#: Auto-rejection threshold: past this the meeting is rejected through the
#: existing manual reject domain path with ``decidedBy="system:reaper"``.
REAPER_REJECT_AFTER_MS = 7 * 24 * 60 * 60 * 1000

#: Additive chain-ledger record kind for reaper decisions (escalate/reject
#: markers).  Append-only like every other record; the idempotency key is
#: bound to the meeting's closure digest so a replay never double-fires.
REAPER_DECISION_KIND = "hypothesis_first_reaper_decision"

#: Sweep cadence: the recovery tick runs far more often than a 48 h/7 d
#: horizon needs (same self-throttle pattern as the auto-advance sweep).
REAPER_SWEEP_INTERVAL_MS = 10 * 60 * 1000

REAPER_ACTOR = "system:reaper"
REAPER_TAXONOMY_SOURCE = "reaper"

_LAST_REAPER_SWEEP_MS: int | None = None
_REAPER_SWEEP_LOCK = threading.Lock()


def reaper_enabled() -> bool:
    """Configured ON/OFF kill switch for the awaiting-approval reaper."""

    raw = str(os.environ.get(REAPER_KILL_SWITCH_ENV) or "").strip().lower()
    return raw not in {"0", "false", "off"}


def reset_reaper_throttle_for_tests() -> None:
    """Test seam: forget the last sweep run so the next tick executes."""

    global _LAST_REAPER_SWEEP_MS
    with _REAPER_SWEEP_LOCK:
        _LAST_REAPER_SWEEP_MS = None


def _reaper_sweep_due(now_ms: int) -> bool:
    global _LAST_REAPER_SWEEP_MS
    with _REAPER_SWEEP_LOCK:
        last = _LAST_REAPER_SWEEP_MS
        if last is not None and now_ms - last < REAPER_SWEEP_INTERVAL_MS:
            return False
        _LAST_REAPER_SWEEP_MS = now_ms
        return True


def _latest_reaper_decision(
    team_id: str, *, idempotency_key: str
) -> dict[str, Any] | None:
    """Existing reaper-decision marker for one idempotency key, if any."""

    from . import hypothesis_first_chain as chain

    with chain._LOCK:
        records = chain._read_jsonl(chain._storage_path(team_id))
        return next(
            (
                dict(item)
                for item in reversed(records)
                if item.get("recordKind") == REAPER_DECISION_KIND
                and str(item.get("idempotencyKey") or "") == idempotency_key
            ),
            None,
        )


def _append_reaper_decision(
    team_id: str,
    *,
    action: str,
    meeting: Mapping[str, Any],
    digest_hash: str,
    age_ms: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Append ONE durable reaper-decision marker (check-before-append)."""

    from . import hypothesis_first_chain as chain

    meeting_round_id = str(meeting.get("meetingRoundId") or "").strip()
    idempotency_key = (
        f"hf2:reaper:{action}:{team_id}:{meeting_round_id}:{digest_hash}"
    )
    with chain._LOCK:
        records = chain._read_jsonl(chain._storage_path(team_id))
        existing = next(
            (
                dict(item)
                for item in records
                if item.get("recordKind") == REAPER_DECISION_KIND
                and str(item.get("idempotencyKey") or "") == idempotency_key
            ),
            None,
        )
        if existing is not None:
            return existing
        now = chain._utc_now()
        record = {
            "schemaVersion": chain.SCHEMA_VERSION,
            "recordKind": REAPER_DECISION_KIND,
            "decisionId": f"hf-reaper-{chain._stable_hash({'key': idempotency_key})[:16]}",
            "idempotencyKey": idempotency_key,
            "action": action,
            "teamId": team_id,
            "questionId": str(meeting.get("question") or "").strip(),
            "meetingRoundId": meeting_round_id,
            "meetingType": str(meeting.get("meetingType") or "").strip(),
            "digestContentHash": digest_hash,
            "awaitingAgeMs": int(age_ms),
            "decidedBy": REAPER_ACTOR,
            "createdAt": now,
            "updatedAt": now,
            **payload,
        }
        chain._append_jsonl(chain._storage_path(team_id), record)
    return record


def _digest_hash_for(meeting: Mapping[str, Any]) -> str:
    draft = (
        dict(meeting.get("digestDraft"))
        if isinstance(meeting.get("digestDraft"), Mapping)
        else {}
    )
    return str(draft.get("contentHash") or "").strip() or "no-digest"


def _escalate_meeting(
    team_id: str,
    meeting: Mapping[str, Any],
    *,
    block_reason: str,
    age_ms: int,
    now_iso: str,
) -> dict[str, Any]:
    """Emit the ONE anomaly-inbox escalation for one stalled digest."""

    from .anomaly_inbox_service import build_anomaly_inbox

    meeting_round_id = str(meeting.get("meetingRoundId") or "").strip()
    digest_hash = _digest_hash_for(meeting)
    items: list[dict[str, Any]] = []
    try:
        inbox = build_anomaly_inbox(
            {
                "teamId": team_id,
                "questionId": str(meeting.get("question") or "").strip(),
            },
            digest_ttl_overdues=[
                {
                    "meetingRoundId": meeting_round_id,
                    "overdueMs": max(age_ms - REAPER_ESCALATION_AFTER_MS, 0),
                    "ttlMs": REAPER_ESCALATION_AFTER_MS,
                    "digestAt": str(meeting.get("updatedAt") or "") or now_iso,
                    "digestAtSource": "meeting_updated_at",
                }
            ],
            generated_at=now_iso,
        )
        items = [item.to_dict() for item in inbox.items]
    except Exception:  # noqa: BLE001 - escalation must not depend on the projector
        items = []
    record = _append_reaper_decision(
        team_id,
        action="escalate",
        meeting=meeting,
        digest_hash=digest_hash,
        age_ms=age_ms,
        payload={
            "digestGateReason": block_reason,
            "escalation": {
                "status": "emitted" if items else "unavailable",
                "items": items,
            },
        },
    )
    from . import hypothesis_first_chain as chain

    chain._record_scene_event(
        "hypothesis_first.reaper_escalated",
        outcome="escalated" if items else "projector_unavailable",
        level="warning",
        fields={
            "teamId": team_id,
            "questionId": str(meeting.get("question") or "").strip(),
            "meetingRoundId": meeting_round_id,
            "digestGateReason": block_reason,
            "awaitingAgeMs": int(age_ms),
            "anomalyItemCount": len(items),
            "decisionId": str(record.get("decisionId") or ""),
        },
    )
    return {"status": "escalated", "decision": record}


def _reject_meeting(
    team_id: str,
    meeting: Mapping[str, Any],
    *,
    block_reason: str,
    age_ms: int,
) -> dict[str, Any]:
    """Auto-reject one stalled digest via the manual reject domain path."""

    from core.web.services.team_workflow import meeting_rounds

    from . import hypothesis_first_chain as chain

    meeting_round_id = str(meeting.get("meetingRoundId") or "").strip()
    digest_hash = _digest_hash_for(meeting)
    reason = (
        "reaper: awaiting_approval waited "
        f"{age_ms // (60 * 60 * 1000)}h with a digest that failed the "
        f"auto-approve quality gate ({block_reason})"
    )
    try:
        meeting_rounds.reject_meeting_digest_draft(
            team_id,
            meeting_round_id,
            actor=REAPER_ACTOR,
            reason=reason,
        )
    except Exception as exc:  # noqa: BLE001 - one meeting stays isolated
        # A domain rejection (status moved on, digest regenerated between
        # the read and the reject) is a structured skip, never an error.
        chain._record_scene_event(
            "hypothesis_first.reaper_rejected",
            outcome="skipped",
            level="warning",
            fields={
                "teamId": team_id,
                "meetingRoundId": meeting_round_id,
                "reason": type(exc).__name__,
                "error": str(exc)[:200],
            },
        )
        return {"status": "skipped", "reason": type(exc).__name__}
    record = _append_reaper_decision(
        team_id,
        action="reject",
        meeting=meeting,
        digest_hash=digest_hash,
        age_ms=age_ms,
        payload={
            "digestGateReason": block_reason,
            "rejectReason": reason,
        },
    )
    chain._record_scene_event(
        "hypothesis_first.reaper_rejected",
        outcome="rejected",
        level="warning",
        fields={
            "teamId": team_id,
            "questionId": str(meeting.get("question") or "").strip(),
            "meetingRoundId": meeting_round_id,
            "digestGateReason": block_reason,
            "awaitingAgeMs": int(age_ms),
            "decidedBy": REAPER_ACTOR,
            "decisionId": str(record.get("decisionId") or ""),
        },
    )
    return {"status": "rejected", "decision": record}


def _handle_meeting(
    team_id: str,
    meeting: Mapping[str, Any],
    *,
    now_ms: int,
    now_iso: str,
) -> dict[str, Any]:
    """One meeting, fully isolated: never raises, always a counted outcome."""

    from . import hypothesis_first_chain as chain

    meeting_round_id = str(meeting.get("meetingRoundId") or "").strip()
    if not meeting_round_id:
        return {"status": "skipped", "reason": "missing_meeting_round_id"}
    if (
        str(meeting.get("status") or "").strip().lower()
        != "awaiting_approval"
    ):
        # Never touch non-awaiting states.
        return {"status": "skipped", "reason": "not_awaiting_approval"}
    meeting_type = str(meeting.get("meetingType") or "").strip().lower()
    if meeting_type not in chain.AUTO_APPROVE_DIGEST_MEETING_TYPES:
        # Only the digest-carrying round types own the digest approval gate.
        return {"status": "skipped", "reason": "not_digest_meeting_type"}
    block_reason = chain._digest_auto_approval_block_reason(meeting)
    if not block_reason:
        # A digest that PASSES the gate follows the existing auto-approve
        # path; the reaper never auto-rejects it.
        return {"status": "skipped", "reason": "digest_gate_passed"}
    updated_at_ms = chain._iso_timestamp_ms(meeting.get("updatedAt"))
    if updated_at_ms is None:
        return {"status": "skipped", "reason": "unreadable_updated_at"}
    age_ms = max(now_ms - updated_at_ms, 0)
    if age_ms < REAPER_ESCALATION_AFTER_MS:
        return {"status": "skipped", "reason": "within_escalation_window"}
    digest_hash = _digest_hash_for(meeting)
    if age_ms >= REAPER_REJECT_AFTER_MS:
        if (
            _latest_reaper_decision(
                team_id,
                idempotency_key=(
                    f"hf2:reaper:reject:{team_id}:{meeting_round_id}:{digest_hash}"
                ),
            )
            is not None
        ):
            return {"status": "skipped", "reason": "reject_already_recorded"}
        return _reject_meeting(
            team_id, meeting, block_reason=block_reason, age_ms=age_ms
        )
    if (
        _latest_reaper_decision(
            team_id,
            idempotency_key=(
                f"hf2:reaper:escalate:{team_id}:{meeting_round_id}:{digest_hash}"
            ),
        )
        is not None
    ):
        return {"status": "skipped", "reason": "escalation_already_recorded"}
    return _escalate_meeting(
        team_id,
        meeting,
        block_reason=block_reason,
        age_ms=age_ms,
        now_iso=now_iso,
    )


def reap_awaiting_approval_meetings(
    *, now_ms: int | None = None, respect_throttle: bool = True
) -> dict[str, Any]:
    """Sweep every team's stalled awaiting_approval digest meetings.

    Returns a summary dict; never raises.  ``now_ms`` is the injectable
    clock (tests); ``respect_throttle=False`` bypasses the self-throttle
    for tests and explicit operator runs.
    """

    from . import hypothesis_first_chain as chain

    summary: dict[str, Any] = {
        "teams": 0,
        "meetings": 0,
        "escalated": 0,
        "rejected": 0,
        "skipped": 0,
        "failed": 0,
        "status": "ok",
        "reason": "",
    }
    if not reaper_enabled():
        summary["status"] = "skipped"
        summary["reason"] = "kill_switch_off"
        return summary
    now_value = int(now_ms if now_ms is not None else time.time() * 1000)
    if respect_throttle and not _reaper_sweep_due(now_value):
        summary["status"] = "skipped"
        summary["reason"] = "throttled"
        return summary
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_value / 1000.0))
    try:
        team_ids = chain._team_ids_with_chain_storage()
    except Exception:  # noqa: BLE001 - the sweep must never break its host
        summary["status"] = "failed"
        summary["reason"] = "team_enumeration_failed"
        return summary
    from core.web.services.team_workflow import meeting_rounds

    for team_id in team_ids:
        try:
            meetings = list(
                meeting_rounds.list_meeting_rounds(
                    team_id, status="awaiting_approval", read_only=True
                )["meetings"]
            )
        except Exception:  # noqa: BLE001 - one broken team stays isolated
            summary["failed"] += 1
            continue
        summary["teams"] += 1
        for meeting in meetings:
            if not isinstance(meeting, Mapping):
                continue
            summary["meetings"] += 1
            try:
                outcome = _handle_meeting(
                    team_id,
                    meeting,
                    now_ms=now_value,
                    now_iso=now_iso,
                )
            except Exception as exc:  # noqa: BLE001 - per-question isolation
                summary["failed"] += 1
                chain._record_scene_event(
                    "hypothesis_first.reaper_escalated",
                    outcome="failed",
                    level="warning",
                    fields={
                        "teamId": team_id,
                        "meetingRoundId": str(
                            meeting.get("meetingRoundId") or ""
                        ),
                        "reason": type(exc).__name__,
                        "error": str(exc)[:200],
                    },
                )
                continue
            status = str(outcome.get("status") or "skipped")
            if status == "escalated":
                summary["escalated"] += 1
            elif status == "rejected":
                summary["rejected"] += 1
            elif status == "failed":
                summary["failed"] += 1
            else:
                summary["skipped"] += 1
    return summary
