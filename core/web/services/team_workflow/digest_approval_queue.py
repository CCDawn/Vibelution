"""Batch queue for pending hypothesis-chain digest approvals.

Every hypothesis chain round parks in ``awaiting_approval`` until an
operator approves its digest, and today each approval is one meeting, one
screen, one click.  At multi-question scale that is the widest human gate in
the chain, so this module adds the two batch primitives on top of the
unchanged single-approve authority:

* :func:`list_pending_digest_approvals` — one team-wide, read-only view of
  every awaiting digest with the exact ``contentHash`` the approval must
  echo back (same CAS contract as ``approve-digest``);
* :func:`batch_approve_digests` — sequential per-item execution of
  :func:`~core.web.services.team_workflow.research_runtime.hypothesis_first_chain.approve_meeting_digest`
  with per-item isolation: one stale hash or already-approved meeting fails
  its own row and never blocks the rest.  Sequential on purpose — the chain
  applies generation/review side effects per approval, and those writes are
  not designed for concurrent execution.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Any


def list_pending_digest_approvals(team_id: str) -> dict[str, Any]:
    """Team-wide read-only queue of digests awaiting approval."""

    from core.web.services import team_service
    from core.web.services.team_workflow import meeting_rounds, meeting_runtime

    normalized_team_id = team_service.assert_team_exists(team_id)
    listing = meeting_rounds.list_meeting_rounds(
        normalized_team_id, status=("awaiting_approval",), read_only=True
    )
    now_ms = int(time.time() * 1000)
    items: list[dict[str, Any]] = []
    for meeting in listing.get("meetings") or []:
        if not isinstance(meeting, Mapping):
            continue
        draft = (
            meeting.get("digestDraft")
            if isinstance(meeting.get("digestDraft"), Mapping)
            else {}
        )
        content_hash = str(draft.get("contentHash") or "").strip()
        if not content_hash:
            # Without a hash there is nothing the batch approval could echo;
            # the per-meeting screen keeps handling these rare drafts.
            continue
        proposed = draft.get("proposedCandidates")
        risks = draft.get("risks")
        started_at = str(meeting.get("startedAt") or meeting.get("createdAt") or "")
        item: dict[str, Any] = {
            "meetingRoundId": str(meeting.get("meetingRoundId") or "").strip(),
            "meetingType": str(meeting.get("meetingType") or "").strip(),
            "questionId": str(meeting.get("question") or "").strip().upper(),
            "digestContentHash": content_hash,
            "digestSummary": str(draft.get("summary") or "").strip(),
            "proposedCandidateCount": len(proposed) if isinstance(proposed, list) else 0,
            "riskCount": len(risks) if isinstance(risks, list) else 0,
            "startedAt": started_at,
            "ageSeconds": max(0, int((now_ms - _epoch_ms(started_at)) / 1000)),
            "ttlOverdue": False,
            "ttlMessage": "",
        }
        try:
            mute = meeting_runtime.meeting_digest_ttl_mute_state(meeting)
        except Exception:  # noqa: BLE001 - TTL signals are advisory only
            mute = None
        if mute:
            item["ttlOverdue"] = True
            item["ttlMessage"] = str(mute.get("message") or "")
        items.append(item)
    items.sort(key=lambda row: (-row.get("ageSeconds", 0), row.get("meetingRoundId", "")))
    return {
        "items": items,
        "count": len(items),
        "fetchedAtMs": now_ms,
    }


def batch_approve_digests(
    team_id: str,
    items: Sequence[Mapping[str, Any]],
    *,
    closed_by: str,
    runtime: Any = None,
) -> dict[str, Any]:
    """Approve a batch of awaiting digests sequentially, one result per row.

    Per-item failures (stale hash, meeting no longer awaiting, unknown id)
    come back as ``failed`` rows with the domain error name and message; the
    loop never aborts.  An empty ``closedBy`` or empty item list fails the
    whole request exactly like the single-approve endpoint would.
    """

    from core.web.services.team_workflow.research_runtime import hypothesis_first_chain

    normalized_closed_by = str(closed_by or "").strip()
    if not normalized_closed_by:
        raise hypothesis_first_chain.HypothesisFirstChainError("closedBy is required.")
    rows: list[dict[str, Any]] = []
    approved = 0
    failed = 0
    for raw in list(items or []):
        if not isinstance(raw, Mapping):
            continue
        meeting_round_id = str(raw.get("meetingRoundId") or "").strip()
        expected_hash = str(raw.get("expectedDigestContentHash") or "").strip()
        if not meeting_round_id or not expected_hash:
            rows.append(
                {
                    "meetingRoundId": meeting_round_id,
                    "status": "failed",
                    "errorType": "invalid_request",
                    "error": "meetingRoundId and expectedDigestContentHash are required.",
                }
            )
            failed += 1
            continue
        try:
            hypothesis_first_chain.approve_meeting_digest(
                team_id,
                meeting_round_id,
                closed_by=normalized_closed_by,
                expected_digest_content_hash=expected_hash,
                runtime=runtime,
            )
        except Exception as exc:  # noqa: BLE001 - one bad row never stops the batch
            rows.append(
                {
                    "meetingRoundId": meeting_round_id,
                    "status": "failed",
                    "errorType": type(exc).__name__,
                    "error": str(exc) or type(exc).__name__,
                }
            )
            failed += 1
            continue
        rows.append({"meetingRoundId": meeting_round_id, "status": "approved"})
        approved += 1
    return {
        "results": rows,
        "approvedCount": approved,
        "failedCount": failed,
        "closedBy": normalized_closed_by,
    }


def _epoch_ms(iso_value: str) -> int:
    from datetime import datetime

    try:
        parsed = datetime.fromisoformat(str(iso_value).replace("Z", "+00:00"))
        return int(parsed.timestamp() * 1000)
    except (TypeError, ValueError):
        return 0


__all__ = ["batch_approve_digests", "list_pending_digest_approvals"]
