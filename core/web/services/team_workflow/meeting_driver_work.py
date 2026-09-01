"""Durable intent store and startup recovery for challenge meeting drivers.

The in-process meeting discussion driver
(``meeting_runtime._MEETING_DISCUSSION_EXECUTOR`` plus its dedup set) is the
only scheduler; a backend restart used to orphan every open challenge meeting
because the pending driver existed only in memory.  This module persists one
append-only intent record per ``(teamId, meetingRoundId, actionKind)`` next to
``meeting_rounds.jsonl`` so a startup sweep can fence deadline-expired
meetings, re-drive interrupted discussions, re-drive interrupted digest
drafts, backfill the governed deadline for challenge-identity meetings whose
policy was never persisted, and close identity-less legacy orphans that can
never receive a governed deadline.

Two action kinds are durable: ``run_discussion`` (the round driver) and
``run_digest`` (the Coordinator digest draft).  Digest intents additionally
carry the ``sourceHash`` of the bound room messages they draft from and the
meeting's governed ``deadlineAtMs``; the digest LLM call itself is bounded
(review-runner timeout), so the digest lease is a crash fence rather than a
heartbeat window: a running digest intent is stale when the boot id is foreign
or the lease has expired.  The lease is clamped to the meeting deadline, so a
lapsed deadline always reads as a stale lease.

Reads are latest-wins by ``(teamId, meetingRoundId, actionKind)``, mirroring
the append + latest read contract of ``meeting_rounds``.  No second scheduler
lives here: the recovery sweep only re-enters
``meeting_runtime.schedule_meeting_discussion`` (dedup set guarantees at most
one live driver per meeting) or submits one bounded digest re-drive per
meeting through the same executor (in-process digest job set dedups).
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
ACTION_RUN_DISCUSSION = "run_discussion"
ACTION_RUN_DIGEST = "run_digest"
_ACTION_KINDS = frozenset({ACTION_RUN_DISCUSSION, ACTION_RUN_DIGEST})
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_SUPERSEDED = "superseded"
_VALID_STATUSES = frozenset(
    {
        STATUS_PENDING,
        STATUS_RUNNING,
        STATUS_COMPLETED,
        STATUS_FAILED,
        STATUS_SUPERSEDED,
    }
)
# Same terminal vocabulary meeting_runtime uses when the discussion runner
# observes an expired ``challengeDeadlineAtMs`` (stop_reason ``challenge_deadline``).
_FENCE_REASON_DEADLINE = "challenge_deadline"
# Legacy meetings predate the challenge identity contract (no scope authority,
# no receipt authority), so no governed deadline can ever be derived for them.
# The sweep closes such orphans through the existing terminal path instead of
# leaving a permanent ``open``/``summarizing`` hang with no possible closer.
_FENCE_REASON_LEGACY_ORPHAN = "legacy_orphan_closeout"
MAX_AUTO_RESCHEDULE_ATTEMPTS = 3
_MAX_LAST_PROBLEM_LENGTH = 240
# A running intent is only authoritative for this long without a heartbeat;
# the recovery sweep re-drives a same-boot driver that let its lease lapse.
DEFAULT_INTENT_LEASE_MS = 90_000
HEARTBEAT_INTERVAL_MS = DEFAULT_INTENT_LEASE_MS // 3
# The digest draft LLM call is bounded by the review-runner timeout (450s);
# the digest lease is a crash fence just beyond that budget, not a heartbeat
# window. A digest re-drive never waits longer than the meeting deadline.
DIGEST_INTENT_LEASE_MS = 480_000
_LEASE_MS_BY_ACTION = {
    ACTION_RUN_DISCUSSION: DEFAULT_INTENT_LEASE_MS,
    ACTION_RUN_DIGEST: DIGEST_INTENT_LEASE_MS,
}

_LOCK = threading.RLock()
_WORKER_BOOT_ID = uuid.uuid4().hex


class MeetingDriverWorkError(RuntimeError):
    """Base error for the durable meeting driver intent store."""


def worker_boot_id() -> str:
    """Process-level boot id stamped onto intents this process touches."""

    with _LOCK:
        return _WORKER_BOOT_ID


def reset_for_tests() -> str:
    """Test seam: drop in-memory state and rotate the boot id (new process)."""

    global _WORKER_BOOT_ID
    with _LOCK:
        _WORKER_BOOT_ID = uuid.uuid4().hex
        return _WORKER_BOOT_ID


def format_problem(error: BaseException) -> str:
    """Bounded problem text: exception type plus message, never a traceback."""

    return f"{type(error).__name__}: {error}"[:_MAX_LAST_PROBLEM_LENGTH]


def _meeting_rounds():
    from core.web.services.team_workflow import meeting_rounds

    return meeting_rounds


def _require_id(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise MeetingDriverWorkError(f"{field} is required")
    return normalized


def work_path(team_id: str) -> Path:
    """Store path sharing the meeting_rounds team workspace resolution."""

    meeting_rounds = _meeting_rounds()
    rounds_path = meeting_rounds._rounds_path(_require_id(team_id, "teamId"))
    return rounds_path.with_name("meeting_driver_work.jsonl")


def _read_records(path: Path) -> list[dict[str, Any]]:
    from core.web.services.team_workflow.storage_durability import read_jsonl_tolerant

    return read_jsonl_tolerant(path)


def _attempt_count(record: Mapping[str, Any] | None) -> int:
    if not isinstance(record, Mapping):
        return 0
    value = record.get("attemptCount")
    if isinstance(value, bool):
        return 0
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return 0
    return normalized if normalized > 0 else 0


def latest_intent(
    team_id: str,
    meeting_round_id: str,
    *,
    action_kind: str = ACTION_RUN_DISCUSSION,
) -> dict[str, Any] | None:
    """Latest-wins intent for one meeting, mirroring meeting_rounds reads."""

    normalized_team_id = _require_id(team_id, "teamId")
    normalized_round_id = _require_id(meeting_round_id, "meetingRoundId")
    with _LOCK:
        records = _read_records(work_path(normalized_team_id))
    for record in reversed(records):
        if (
            str(record.get("teamId") or "") == normalized_team_id
            and str(record.get("meetingRoundId") or "") == normalized_round_id
            and str(record.get("actionKind") or "") == action_kind
        ):
            return record
    return None


def record_intent(
    team_id: str,
    meeting_round_id: str,
    *,
    status: str,
    last_problem: str | None = None,
    action_kind: str = ACTION_RUN_DISCUSSION,
    source_hash: str = "",
    deadline_at_ms: int = 0,
) -> dict[str, Any]:
    """Append one durable intent record for a meeting driver action."""

    normalized_team_id = _require_id(team_id, "teamId")
    normalized_round_id = _require_id(meeting_round_id, "meetingRoundId")
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in _VALID_STATUSES:
        raise MeetingDriverWorkError(f"unsupported driver work status: {status!r}")
    normalized_action_kind = str(action_kind or "").strip()
    if normalized_action_kind not in _ACTION_KINDS:
        raise MeetingDriverWorkError(f"unsupported driver work actionKind: {action_kind!r}")
    try:
        normalized_deadline = int(deadline_at_ms)
    except (TypeError, ValueError):
        normalized_deadline = 0
    if isinstance(deadline_at_ms, bool) or normalized_deadline <= 0:
        normalized_deadline = 0
    normalized_source_hash = str(source_hash or "").strip()
    now_ms = int(time.time() * 1000)
    with _LOCK:
        previous = latest_intent(
            normalized_team_id, normalized_round_id, action_kind=normalized_action_kind
        )
        previous_attempts = _attempt_count(previous)
        # Terminal records inherit the identity of the work they close out.
        if not normalized_source_hash and isinstance(previous, Mapping):
            normalized_source_hash = str(previous.get("sourceHash") or "").strip()
        if not normalized_deadline and isinstance(previous, Mapping):
            try:
                inherited_deadline = int(previous.get("deadlineAtMs") or 0)
            except (TypeError, ValueError):
                inherited_deadline = 0
            if inherited_deadline > 0:
                normalized_deadline = inherited_deadline
        if normalized_status in {STATUS_PENDING, STATUS_RUNNING}:
            boot_id = worker_boot_id()
        else:
            boot_id = (
                str((previous or {}).get("workerBootId") or "").strip()
                or worker_boot_id()
            )
        if normalized_status == STATUS_RUNNING:
            lease_ms = _LEASE_MS_BY_ACTION[normalized_action_kind]
            lease_expires_at_ms = now_ms + lease_ms
            # A re-drive must never outlive the governed meeting deadline.
            if normalized_deadline and lease_expires_at_ms > normalized_deadline:
                lease_expires_at_ms = normalized_deadline
        else:
            lease_expires_at_ms = 0
        record = {
            "schemaVersion": SCHEMA_VERSION,
            "workId": uuid.uuid4().hex,
            "teamId": normalized_team_id,
            "meetingRoundId": normalized_round_id,
            "actionKind": normalized_action_kind,
            "status": normalized_status,
            "attemptCount": previous_attempts + (1 if normalized_status == STATUS_RUNNING else 0),
            "workerBootId": boot_id,
            "createdAtMs": now_ms,
            "updatedAtMs": now_ms,
            "leaseExpiresAtMs": lease_expires_at_ms,
            "sourceHash": normalized_source_hash,
            "deadlineAtMs": normalized_deadline,
            "lastProblem": str(last_problem or "").strip()[:_MAX_LAST_PROBLEM_LENGTH],
        }
        from core.web.services.team_workflow.storage_durability import append_jsonl_locked

        append_jsonl_locked(work_path(normalized_team_id), record)
        return record


def _lease_expired(work: Mapping[str, Any], now_ms: int) -> bool:
    expires_at_ms = work.get("leaseExpiresAtMs")
    if isinstance(expires_at_ms, bool) or not isinstance(expires_at_ms, int):
        # Pre-lease records keep the legacy same-boot trust: only a foreign
        # boot id marks them stale.
        return False
    return expires_at_ms > 0 and now_ms >= expires_at_ms


def refresh_intent_lease(
    team_id: str,
    meeting_round_id: str,
    *,
    action_kind: str = ACTION_RUN_DISCUSSION,
    lease_ms: int = DEFAULT_INTENT_LEASE_MS,
) -> dict[str, Any] | None:
    """Heartbeat: extend the lease of a running intent owned by this boot.

    Appends a running record that preserves ``attemptCount`` so recovery
    accounting stays accurate.  Returns ``None`` without writing when the
    latest intent is not running or belongs to a foreign boot: a heartbeat
    must never adopt someone else's driver.
    """

    normalized_team_id = _require_id(team_id, "teamId")
    normalized_round_id = _require_id(meeting_round_id, "meetingRoundId")
    now_ms = int(time.time() * 1000)
    with _LOCK:
        previous = latest_intent(
            normalized_team_id, normalized_round_id, action_kind=action_kind
        )
        if previous is None:
            return None
        if str(previous.get("status") or "").strip().lower() != STATUS_RUNNING:
            return None
        if str(previous.get("workerBootId") or "").strip() != worker_boot_id():
            return None
        record = {
            "schemaVersion": SCHEMA_VERSION,
            "workId": uuid.uuid4().hex,
            "teamId": normalized_team_id,
            "meetingRoundId": normalized_round_id,
            "actionKind": action_kind,
            "status": STATUS_RUNNING,
            "attemptCount": _attempt_count(previous),
            "heartbeat": True,
            "workerBootId": worker_boot_id(),
            "createdAtMs": now_ms,
            "updatedAtMs": now_ms,
            "leaseExpiresAtMs": now_ms + int(lease_ms),
            "lastProblem": str(previous.get("lastProblem") or "").strip()[
                :_MAX_LAST_PROBLEM_LENGTH
            ],
        }
        from core.web.services.team_workflow.storage_durability import append_jsonl_locked

        append_jsonl_locked(work_path(normalized_team_id), record)
        return record


def start_lease_heartbeat(
    team_id: str,
    meeting_round_id: str,
    *,
    stop_event: threading.Event,
    interval_ms: int = HEARTBEAT_INTERVAL_MS,
) -> threading.Thread:
    """Refresh the running intent lease until ``stop_event`` is set.

    Heartbeat failures are swallowed: the worst outcome is that the lease
    lapses and the recovery sweep re-drives the meeting, which is exactly
    the contract this lease exists to provide.
    """

    interval_s = max(int(interval_ms), 10) / 1000.0

    def _loop() -> None:
        while not stop_event.wait(interval_s):
            try:
                refresh_intent_lease(team_id, meeting_round_id)
            except Exception:  # noqa: BLE001 - a missed beat must not kill the driver
                continue

    thread = threading.Thread(
        target=_loop,
        name=f"meeting-driver-lease:{meeting_round_id}",
        daemon=True,
    )
    thread.start()
    return thread


def _teams_workspace_root() -> Path:
    """Parent of every team workspace, resolved exactly like meeting_rounds."""

    meeting_rounds = _meeting_rounds()
    # Any team id resolves to <teams-root>/<team-id>/research_workflow/...;
    # a probe id inherits the sandbox/formal resolution without duplicating it.
    return meeting_rounds._team_workspace_root("driver-recovery-probe").parent


def _team_ids_with_meeting_rounds() -> list[str]:
    root = _teams_workspace_root()
    if not root.exists():
        return []
    team_ids: list[str] = []
    for rounds_path in sorted(root.glob("*/research_workflow/meeting_rounds.jsonl")):
        parts = rounds_path.parts
        if len(parts) >= 3 and parts[-3]:
            team_ids.append(parts[-3])
    return team_ids


def recover_challenge_meeting_drivers() -> dict[str, Any]:
    """Startup sweep for orphaned challenge meeting drivers.

    For every open/summarizing meeting: fence it through the existing
    terminal path when its ``challengeDeadlineAtMs`` has passed, re-enter
    ``schedule_meeting_discussion`` (open) or ``schedule_meeting_digest_redrive``
    (summarizing) when its durable intent shows an interrupted run (foreign
    boot id or an expired lease), backfill the
    governed deadline for challenge-identity meetings whose deadline was
    never persisted, and fence identity-less legacy orphans through the
    terminal path.  Idempotent: a second
    consecutive run is a no-op because fenced meetings are closed,
    backfilled meetings now carry a future deadline, and rescheduled ones are
    protected by the in-process dedup set.  Never raises; every team/meeting
    failure is isolated into ``skipped``.
    """

    summary: dict[str, Any] = {
        "teams": 0,
        "meetingsScanned": 0,
        "fenced": 0,
        "backfilled": 0,
        "rescheduled": 0,
        "skipped": 0,
    }
    try:
        team_ids = _team_ids_with_meeting_rounds()
    except Exception:  # noqa: BLE001 - startup sweep must never block boot
        _record_recovery_scene_event(summary)
        return summary
    for team_id in team_ids:
        summary["teams"] += 1
        try:
            _recover_team_drivers(team_id, summary)
        except Exception:  # noqa: BLE001 - one broken team cannot stop the sweep
            summary["skipped"] += 1
    _record_recovery_scene_event(summary)
    return summary


def _recover_team_drivers(team_id: str, summary: dict[str, Any]) -> None:
    meeting_rounds = _meeting_rounds()
    meetings = meeting_rounds.list_meeting_rounds(
        team_id, status=("open", "summarizing")
    )["meetings"]
    now_ms = int(time.time() * 1000)
    for meeting in meetings:
        summary["meetingsScanned"] += 1
        meeting_round_id = str(meeting.get("meetingRoundId") or "").strip()
        if not meeting_round_id:
            summary["skipped"] += 1
            continue
        try:
            outcome = _recover_one_meeting(
                team_id, meeting_round_id, dict(meeting), now_ms
            )
        except Exception:  # noqa: BLE001 - one broken meeting cannot stop the sweep
            summary["skipped"] += 1
            continue
        if outcome == "fenced":
            summary["fenced"] += 1
        elif outcome == "backfilled":
            summary["backfilled"] += 1
        elif outcome == "rescheduled":
            summary["rescheduled"] += 1
        else:
            summary["skipped"] += 1


def _recover_one_meeting(
    team_id: str,
    meeting_round_id: str,
    meeting: Mapping[str, Any],
    now_ms: int,
) -> str:
    deadline_at_ms = meeting.get("challengeDeadlineAtMs")
    has_deadline = (
        isinstance(deadline_at_ms, int)
        and not isinstance(deadline_at_ms, bool)
        and deadline_at_ms > 0
    )
    deadline_passed = has_deadline and now_ms >= deadline_at_ms
    if deadline_passed:
        # terminate_meeting_execution closes without promoting a partial digest.
        _meeting_rounds().terminate_meeting_execution(
            team_id,
            meeting_round_id,
            reason=_FENCE_REASON_DEADLINE,
        )
        return "fenced"
    if str(meeting.get("status") or "").strip().lower() == "summarizing":
        digest_work = latest_intent(
            team_id, meeting_round_id, action_kind=ACTION_RUN_DIGEST
        )
        if digest_work is not None:
            return _recover_one_digest(team_id, meeting_round_id, digest_work, now_ms)
        if not has_deadline:
            # Legacy summarizing hang with no durable digest work: keep the
            # identity-gap closeout (backfill or legacy-orphan fence).
            return _close_or_backfill_identity_gap(team_id, meeting_round_id, meeting)
        return "skipped"
    work = latest_intent(team_id, meeting_round_id)
    if work is None:
        if has_deadline:
            # A future deadline without durable work may legitimately await an
            # explicit schedule command; leave the meeting untouched.
            return "skipped"
        return _close_or_backfill_identity_gap(team_id, meeting_round_id, meeting)
    status = str(work.get("status") or "").strip().lower()
    stale_boot = str(work.get("workerBootId") or "") != worker_boot_id()
    lease_expired = _lease_expired(work, now_ms)
    should_reschedule = (
        status == STATUS_PENDING
        or (status == STATUS_RUNNING and (stale_boot or lease_expired))
        or (status == STATUS_FAILED and _attempt_count(work) < MAX_AUTO_RESCHEDULE_ATTEMPTS)
    )
    if not should_reschedule:
        return "skipped"
    from core.web.services.team_workflow import meeting_runtime

    result = meeting_runtime.schedule_meeting_discussion(team_id, meeting_round_id)
    return "rescheduled" if str(result.get("status") or "") == "scheduled" else "skipped"


def _recover_one_digest(
    team_id: str,
    meeting_round_id: str,
    work: Mapping[str, Any],
    now_ms: int,
) -> str:
    """Re-drive an interrupted digest draft for a summarizing meeting.

    Same decision table as the discussion path: pending or interrupted
    (foreign boot / expired lease — the lease is clamped to the meeting
    deadline, so a lapsed deadline reads as stale) work is re-driven once
    through the bounded digest re-drive entry point; failed work stops at
    the shared attempt cap and stays auditable for the ordinary UI retry.
    """

    status = str(work.get("status") or "").strip().lower()
    stale_boot = str(work.get("workerBootId") or "") != worker_boot_id()
    should_reschedule = (
        status == STATUS_PENDING
        or (status == STATUS_RUNNING and (stale_boot or _lease_expired(work, now_ms)))
        or (status == STATUS_FAILED and _attempt_count(work) < MAX_AUTO_RESCHEDULE_ATTEMPTS)
    )
    if not should_reschedule:
        return "skipped"
    from core.web.services.team_workflow import meeting_runtime

    result = meeting_runtime.schedule_meeting_digest_redrive(team_id, meeting_round_id)
    return "rescheduled" if str(result.get("status") or "") == "scheduled" else "skipped"


def _close_or_backfill_identity_gap(
    team_id: str,
    meeting_round_id: str,
    meeting: Mapping[str, Any],
) -> str:
    """Close the no-deadline, no-intent gap left by pre-policy meetings.

    Challenge-identity meetings whose deadline was never persisted get the
    governed deadline backfilled through the existing persist primitive, so a
    later sweep can fence them on expiry.  Meetings without any challenge
    identity (legacy records created before the scope/receipt authority
    contract) can never receive a governed deadline and have no driver that
    could advance them; the sweep fences them through the existing terminal
    path with an auditable reason instead of skipping them forever.
    """

    from core.web.services.team_workflow.challenge_deadline_policy import (
        is_challenge_meeting,
    )

    if is_challenge_meeting(meeting):
        updated = _meeting_rounds().persist_challenge_meeting_deadline_policy(
            team_id, meeting_round_id
        )
        backfilled_deadline = updated.get("challengeDeadlineAtMs")
        if (
            isinstance(backfilled_deadline, int)
            and not isinstance(backfilled_deadline, bool)
            and backfilled_deadline > 0
        ):
            return "backfilled"
        return "skipped"
    from core.web.services.team_workflow import meeting_runtime

    key = (str(team_id or "").strip(), meeting_round_id)
    with meeting_runtime._MEETING_DISCUSSION_JOBS_LOCK:
        has_live_driver = key in meeting_runtime._MEETING_DISCUSSION_JOBS
    if has_live_driver:
        return "skipped"
    _meeting_rounds().terminate_meeting_execution(
        team_id,
        meeting_round_id,
        reason=_FENCE_REASON_LEGACY_ORPHAN,
    )
    return "fenced"


def _record_recovery_scene_event(summary: Mapping[str, Any]) -> None:
    """Bounded sweep evidence, following the meeting_runtime quiet pattern."""

    try:
        from core.web.services.runtime_scene_service import (
            record_runtime_scene_event_quietly,
        )

        record_runtime_scene_event_quietly(
            "team_workflow",
            "meeting_discussion_recovery",
            "meeting_discussion.recovery.sweep_completed",
            message="Challenge meeting driver recovery sweep finished.",
            level="info",
            outcome="completed",
            fields={
                "teams": int(summary.get("teams") or 0),
                "meetingsScanned": int(summary.get("meetingsScanned") or 0),
                "fenced": int(summary.get("fenced") or 0),
                "backfilled": int(summary.get("backfilled") or 0),
                "rescheduled": int(summary.get("rescheduled") or 0),
                "skipped": int(summary.get("skipped") or 0),
            },
            lifecycle=True,
        )
    except Exception:
        # A diagnostic outage must not alter the recovery outcome.
        return
