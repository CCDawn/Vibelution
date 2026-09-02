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
``meeting_runtime.schedule_meeting_discussion`` (the dedup registry guarantees
at most one live driver per meeting, and an expired lease proves the holder is
wedged, so the sweep may evict the stale holder first) or submits one bounded
digest re-drive per meeting through the same executor (in-process digest job
set dedups).

Heartbeats are progress-gated (T1): the discussion driver stamps progress at
each step boundary and the heartbeat thread only renews the lease while that
progress is recent.  A driver wedged inside an unbounded blocking call stops
advancing its stamp, so the heartbeat stops renewing, fences the attempt as
``failed`` once, and hands the meeting back to recovery — a same-boot wedge
therefore has a real in-run exit instead of a permanently renewed lease.

Digest wedges have no heartbeat (the lease is a crash fence), so an in-process
watchdog (:func:`sweep_stuck_digest_works`, hosted by the production
maintenance tick) fences ``run_digest`` intents still ``running`` past their
lease or governed deadline and writes the meeting's structured
``summaryDraftError`` retry entry.  It never re-drives: re-running the LLM
stays the startup sweep's job, and a restarted backend re-drives the fenced
failed attempt through the existing ``_recover_one_digest`` path.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
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
# The digest draft LLM call is bounded by the review-runner timeout; the
# digest lease is a crash fence just beyond that budget, not a heartbeat
# window. A digest re-drive never waits longer than the meeting deadline.
# The lease derives from the review call timeout actually in effect
# (``review_llm_call_timeout_seconds`` in llm_review_runners — the env
# override accepts 300-600s, the persisted per-call budget fills the rest);
# ``DIGEST_INTENT_LEASE_MS`` stays as the historical 480s floor so a
# shorter derived budget can never under-cover a legitimate slow call.
DIGEST_INTENT_LEASE_MS = 480_000
DIGEST_LEASE_MARGIN_MS = 30_000
# Fallback when the review-runner authority is unavailable: the documented
# default review call budget (llm_review_runners.REVIEW_LLM_CALL_TIMEOUT_SECONDS).
DEFAULT_REVIEW_CALL_TIMEOUT_S = 450.0
# The discussion heartbeat is progress-gated: one driver "step" is one full
# discussion round of bounded participant LLM calls.  The stale-progress
# window must therefore cover a whole round of maximal bounded calls before
# declaring the driver wedged — a healthy bounded round can never trip it,
# while an unbounded wedge always eventually does.
DISCUSSION_STEP_ALLOWANCE_CALLS = 8
DISCUSSION_STEP_MARGIN_MS = 60_000
# Bounded problem marker stamped by the heartbeat when it fences a driver
# whose progress stamp went stale inside one step.
WEDGED_DRIVER_PROBLEM = "driver_lease_lapsed_no_progress"

_LOCK = threading.RLock()
_WORKER_BOOT_ID = uuid.uuid4().hex
# In-memory driver progress stamps: (teamId, meetingRoundId, actionKind) ->
# last progress epoch ms.  The heartbeat trusts these over the mere existence
# of the driver thread: a wedged thread never refreshes its stamp.
_PROGRESS_STAMPS: dict[tuple[str, str, str], int] = {}


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
        _PROGRESS_STAMPS.clear()
        return _WORKER_BOOT_ID


def effective_review_call_timeout_seconds() -> float:
    """The review-profile LLM call budget actually in effect, in seconds.

    Authority is ``review_llm_call_timeout_seconds`` in
    ``llm_review_runners`` (read-only reference: that surface is owned by
    another task).  The local fallback duplicates only its documented
    contract — an env override bounded to 300-600 seconds, else the default
    review call budget — so a broken import can never turn a lease back into
    a stale hardcoded constant.
    """

    try:
        from core.web.services.team_workflow.llm_review_runners import (
            review_llm_call_timeout_seconds,
        )

        value = float(review_llm_call_timeout_seconds())
        if value > 0:
            return value
    except Exception:  # noqa: BLE001 - lease derivation must never raise
        pass
    raw = str(
        os.environ.get("VIBELUTION_REVIEW_LLM_CALL_TIMEOUT_SECONDS") or ""
    ).strip()
    if raw:
        try:
            value = float(raw)
        except ValueError:
            return DEFAULT_REVIEW_CALL_TIMEOUT_S
        if 300.0 <= value <= 600.0:
            return value
    return DEFAULT_REVIEW_CALL_TIMEOUT_S


def _lease_ms_for_action(action_kind: str) -> int:
    """Crash-fence lease for one action kind, derived from live timeouts."""

    if action_kind != ACTION_RUN_DIGEST:
        return DEFAULT_INTENT_LEASE_MS
    per_call_ms = int(effective_review_call_timeout_seconds() * 1000)
    derived = per_call_ms + DIGEST_LEASE_MARGIN_MS
    # Never below the historical floor: a slower configured timeout widens
    # the fence, a faster one keeps the old coverage.
    return max(DIGEST_INTENT_LEASE_MS, derived)


def discussion_step_window_ms() -> int:
    """Stale-progress window for the discussion heartbeat (T1).

    One driver step is one full discussion round of bounded participant
    calls, so the window covers ``DISCUSSION_STEP_ALLOWANCE_CALLS`` maximal
    review-timeout calls plus scheduling slack, floored at the digest
    crash-fence lease.  A driver that stops advancing its progress stamp for
    longer than this is wedged beyond any legitimate bounded step.
    """

    per_call_ms = int(effective_review_call_timeout_seconds() * 1000)
    derived = (
        per_call_ms * DISCUSSION_STEP_ALLOWANCE_CALLS + DISCUSSION_STEP_MARGIN_MS
    )
    return max(DIGEST_INTENT_LEASE_MS, derived)


def mark_driver_progress(
    team_id: str,
    meeting_round_id: str,
    *,
    action_kind: str = ACTION_RUN_DISCUSSION,
) -> None:
    """Stamp driver progress; heartbeat renewal requires a recent stamp."""

    key = (
        str(team_id or "").strip(),
        str(meeting_round_id or "").strip(),
        str(action_kind or "").strip(),
    )
    if not key[0] or not key[1]:
        return
    with _LOCK:
        _PROGRESS_STAMPS[key] = int(time.time() * 1000)


def progress_age_ms(
    team_id: str,
    meeting_round_id: str,
    *,
    action_kind: str = ACTION_RUN_DISCUSSION,
) -> int | None:
    """Age of the last progress stamp, or ``None`` when never stamped."""

    key = (
        str(team_id or "").strip(),
        str(meeting_round_id or "").strip(),
        str(action_kind or "").strip(),
    )
    with _LOCK:
        stamp = _PROGRESS_STAMPS.get(key)
    if stamp is None:
        return None
    return max(0, int(time.time() * 1000) - stamp)


def _clear_driver_progress(
    team_id: str,
    meeting_round_id: str,
    *,
    action_kind: str = ACTION_RUN_DISCUSSION,
) -> None:
    key = (
        str(team_id or "").strip(),
        str(meeting_round_id or "").strip(),
        str(action_kind or "").strip(),
    )
    with _LOCK:
        _PROGRESS_STAMPS.pop(key, None)


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
            lease_ms = _lease_ms_for_action(normalized_action_kind)
            lease_expires_at_ms = now_ms + lease_ms
            # A re-drive must never outlive the governed meeting deadline.
            if normalized_deadline and lease_expires_at_ms > normalized_deadline:
                lease_expires_at_ms = normalized_deadline
        else:
            lease_expires_at_ms = 0
            _clear_driver_progress(
                normalized_team_id,
                normalized_round_id,
                action_kind=normalized_action_kind,
            )
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
    must never adopt someone else's driver.  The renewal is clamped to the
    intent's governed meeting ``deadlineAtMs`` like every fresh lease, so a
    lapsed deadline always reads as a stale lease.
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
        lease_expires_at_ms = now_ms + int(lease_ms)
        try:
            deadline = int(previous.get("deadlineAtMs") or 0)
        except (TypeError, ValueError):
            deadline = 0
        if isinstance(previous.get("deadlineAtMs"), bool) or deadline <= 0:
            deadline = 0
        if deadline and lease_expires_at_ms > deadline:
            lease_expires_at_ms = deadline
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
            "leaseExpiresAtMs": lease_expires_at_ms,
            "deadlineAtMs": deadline,
            "lastProblem": str(previous.get("lastProblem") or "").strip()[
                :_MAX_LAST_PROBLEM_LENGTH
            ],
        }
        from core.web.services.team_workflow.storage_durability import append_jsonl_locked

        append_jsonl_locked(work_path(normalized_team_id), record)
        return record


def fence_wedged_driver(
    team_id: str,
    meeting_round_id: str,
    *,
    action_kind: str = ACTION_RUN_DISCUSSION,
    problem: str = WEDGED_DRIVER_PROBLEM,
) -> dict[str, Any] | None:
    """Terminalize a running intent whose driver stopped making progress.

    The heartbeat thread is the only observer that stays alive while the
    driver thread is wedged inside an unbounded blocking call, so it owns
    this transition: once the driver's progress stamp goes stale past the
    step window, the attempt is fenced as ``failed`` (attemptCount preserved
    so the shared auto-reschedule cap still bounds recovery) instead of the
    heartbeat silently renewing a dead driver forever.  Returns ``None``
    when there is no same-boot running intent to fence.
    """

    normalized_team_id = _require_id(team_id, "teamId")
    normalized_round_id = _require_id(meeting_round_id, "meetingRoundId")
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
    return record_intent(
        normalized_team_id,
        normalized_round_id,
        status=STATUS_FAILED,
        action_kind=action_kind,
        last_problem=problem,
    )


def start_lease_heartbeat(
    team_id: str,
    meeting_round_id: str,
    *,
    stop_event: threading.Event,
    interval_ms: int = HEARTBEAT_INTERVAL_MS,
    progress_window_ms: int | None = None,
    on_lapse: Callable[[], None] | None = None,
) -> threading.Thread:
    """Refresh the running intent lease until ``stop_event`` is set.

    Heartbeat failures are swallowed: the worst outcome is that the lease
    lapses and the recovery sweep re-drives the meeting, which is exactly
    the contract this lease exists to provide.

    When ``progress_window_ms`` is set, renewal additionally requires the
    driver's progress stamp to be younger than the window.  A wedged driver
    stops advancing its stamp, so the heartbeat stops renewing (the lease
    lapses), fences the attempt once via :func:`fence_wedged_driver`, and
    invokes ``on_lapse`` exactly once so the runtime can re-drive the meeting
    in-run.  After the lapse this heartbeat exits: its own attempt is fenced
    and any successor drives with its own progress-gated heartbeat — renewing
    here would silently adopt the successor's lease (same worker boot) and
    mask a successor wedge from the same-boot exit.  Callers that pass no
    window keep the legacy unconditional renewal.
    """

    interval_s = max(int(interval_ms), 10) / 1000.0
    heartbeat_state = {"lapsed": False}

    def _loop() -> None:
        while not stop_event.wait(interval_s):
            try:
                if progress_window_ms is not None and not heartbeat_state["lapsed"]:
                    age = progress_age_ms(team_id, meeting_round_id)
                    if age is not None and age > int(progress_window_ms):
                        # The driver thread has not advanced within one
                        # maximal bounded step: stop renewing its lease and
                        # hand the meeting to recovery exactly once.
                        heartbeat_state["lapsed"] = True
                        fenced = fence_wedged_driver(team_id, meeting_round_id)
                        if fenced is not None and on_lapse is not None:
                            try:
                                on_lapse()
                            except Exception:  # noqa: BLE001
                                pass
                        return
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
    backfilled meetings now carry a future deadline, and rescheduled ones
    are protected by the in-process dedup registry — except that a running
    intent with an expired lease proves its in-process holder is wedged, so
    the stale holder is evicted and the re-drive proceeds.  Never raises;
    every team/meeting failure is isolated into ``skipped``.
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

    if status == STATUS_RUNNING and lease_expired:
        # An expired lease proves the in-process holder (if any) stopped
        # progressing past its heartbeat window: a live, healthy driver
        # never lets its lease lapse.  Evict the stale dedup holder so the
        # re-drive is not silently swallowed by "already_scheduled" — this
        # is the same-boot exit for a wedged driver thread.
        meeting_runtime.force_release_wedged_discussion_job(
            team_id, meeting_round_id
        )
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


# Bounded problem marker stamped by the in-process digest watchdog.
STUCK_DIGEST_PROBLEM = "digest_draft_stuck_past_bounded_window"
# In-process watchdog cadence: the production maintenance tick calls
# ``sweep_stuck_digest_works`` far more often than the scan needs to run.
DIGEST_STUCK_SWEEP_INTERVAL_MS = 30_000
DIGEST_STUCK_SWEEP_INTERVAL_ENV = "VIBELUTION_DIGEST_STUCK_SWEEP_INTERVAL_MS"
# Structured summaryDraftError written for a fenced stuck digest so the
# meeting projection exposes a working retry entry without a restart.
_STUCK_SUMMARY_DRAFT_ERROR = {
    "code": "summary_draft_stuck",
    "message": "纪要生成超时未完成，已结束本次尝试；请重试生成纪要。",
    "remediationLabel": "重试生成纪要",
}
# Throttle stamp for the watchdog; touched only under _LOCK.
_LAST_DIGEST_STUCK_SWEEP_MS: int | None = None


def _digest_stuck_sweep_interval_ms() -> int:
    raw = str(os.environ.get(DIGEST_STUCK_SWEEP_INTERVAL_ENV) or "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError:
            return DIGEST_STUCK_SWEEP_INTERVAL_MS
        if value > 0:
            return max(value, 1000)
    return DIGEST_STUCK_SWEEP_INTERVAL_MS


def _digest_stuck_sweep_due(now_ms: int) -> bool:
    global _LAST_DIGEST_STUCK_SWEEP_MS
    interval = _digest_stuck_sweep_interval_ms()
    with _LOCK:
        last = _LAST_DIGEST_STUCK_SWEEP_MS
        if last is not None and now_ms - last < interval:
            return False
        _LAST_DIGEST_STUCK_SWEEP_MS = now_ms
        return True


def reset_digest_stuck_sweep_throttle_for_tests() -> None:
    """Test seam: forget the last watchdog run so the next sweep executes."""

    global _LAST_DIGEST_STUCK_SWEEP_MS
    with _LOCK:
        _LAST_DIGEST_STUCK_SWEEP_MS = None


# --- Queued-driver activity sweep ------------------------------------------
#
# The discussion driver executor is process-wide with four workers and an
# unbounded submission queue.  Under multi-question x multi-candidate fan-out
# a freshly scheduled driver can legitimately wait far longer than the
# 15-minute execution-heartbeat window the V2 projection uses to flag zombie
# meetings and expose the ``reopen_review`` recovery.  A queued driver writes
# no meeting or WorkRun activity by design — its running intent, progress
# stamps, and lease heartbeat all start only when the executor picks the job
# up — so queue depth used to read exactly like a dead executor.
#
# The sweep below renews those meetings' last-activity stamp instead.  It is
# deliberately narrow: only a meeting whose latest ``run_discussion`` intent
# is still ``pending`` (scheduled, executor has not started it) is touched,
# so a genuinely wedged RUNNING driver keeps going stale and its existing
# progress-gated heartbeat fence stays the sole wedge authority.  It lives on
# the resident maintenance tick (same minimal-intrusion host as
# :func:`sweep_stuck_digest_works`) — no second scheduler.
QUEUE_SWEEP_INTERVAL_MS = 30_000
QUEUE_SWEEP_INTERVAL_ENV = "VIBELUTION_MEETING_QUEUE_SWEEP_INTERVAL_MS"
# Renew strictly inside the projection's 15-minute stale window with slack
# for missed sweeps: a queued meeting whose last activity is older than this
# gets exactly one bounded activity stamp per window, bounding record churn.
QUEUE_ACTIVITY_RENEW_AFTER_MS = 7 * 60_000
# Bounded scan per tick: live scheduled jobs are realistically far below
# this; the jobs registry preserves insertion order, so the oldest (longest
# queued) meetings are scanned first.
QUEUE_SWEEP_SCAN_LIMIT = 256
# Throttle stamp for the sweep; touched only under _LOCK.
_LAST_QUEUE_SWEEP_MS: int | None = None


def _queue_sweep_interval_ms() -> int:
    raw = str(os.environ.get(QUEUE_SWEEP_INTERVAL_ENV) or "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError:
            return QUEUE_SWEEP_INTERVAL_MS
        if value > 0:
            return max(value, 1000)
    return QUEUE_SWEEP_INTERVAL_MS


def _queue_sweep_due(now_ms: int) -> bool:
    global _LAST_QUEUE_SWEEP_MS
    interval = _queue_sweep_interval_ms()
    with _LOCK:
        last = _LAST_QUEUE_SWEEP_MS
        if last is not None and now_ms - last < interval:
            return False
        _LAST_QUEUE_SWEEP_MS = now_ms
        return True


def reset_queue_sweep_throttle_for_tests() -> None:
    """Test seam: forget the last queue sweep run so the next sweep executes."""

    global _LAST_QUEUE_SWEEP_MS
    with _LOCK:
        _LAST_QUEUE_SWEEP_MS = None


def _parse_iso_epoch_ms(value: Any) -> int | None:
    """Tolerant ISO-8601 to epoch-ms parse; ``None`` when unreadable."""

    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def _queued_discussion_job_keys() -> list[tuple[str, str]]:
    """Live scheduled jobs whose latest ``run_discussion`` intent is pending.

    A key present in the runtime's dedup registry is scheduled; only the
    durable ``pending`` intent proves the executor has not started it yet
    (starting flips the intent to ``running`` before any driver step).  Keys
    whose intent is missing, unreadable, or already running are skipped:
    staleness must be provable from durable facts, never guessed.
    """

    from core.web.services.team_workflow import meeting_runtime

    with meeting_runtime._MEETING_DISCUSSION_JOBS_LOCK:
        scheduled = list(meeting_runtime._MEETING_DISCUSSION_JOBS.keys())[
            :QUEUE_SWEEP_SCAN_LIMIT
        ]
    queued: list[tuple[str, str]] = []
    for team_id, meeting_round_id in scheduled:
        try:
            intent = latest_intent(
                str(team_id), str(meeting_round_id), action_kind=ACTION_RUN_DISCUSSION
            )
        except Exception:  # noqa: BLE001 - one broken read must not stop the sweep
            continue
        if intent is None:
            continue
        if str(intent.get("status") or "").strip().lower() != STATUS_PENDING:
            continue
        queued.append((str(team_id), str(meeting_round_id)))
    return queued


def refresh_queued_meeting_activity(
    *,
    now_ms: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Renew last-activity stamps of meetings whose driver is still queued.

    Queued discussion drivers legitimately stay silent, so without this sweep
    the V2 projection would expose ``review_heartbeat_stale`` (and the
    ``reopen_review`` recovery) for healthy meetings whose drivers are merely
    waiting for one of the four executor workers.  For every scheduled
    meeting whose latest ``run_discussion`` intent is still ``pending`` and
    whose meeting record has been quiet past
    ``QUEUE_ACTIVITY_RENEW_AFTER_MS``, one bounded
    ``meeting_rounds.record_meeting_queue_activity`` stamp is appended.  A
    running (or terminal) intent is never touched — a real wedge keeps going
    stale and the progress-gated heartbeat fence stays authoritative.  The
    sweep is self-throttled, hosted by the resident maintenance tick, never
    re-drives, and never raises: one broken meeting is isolated into
    ``skipped``.
    """

    current_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    summary: dict[str, Any] = {
        "scanned": 0,
        "queued": 0,
        "renewed": 0,
        "skipped": 0,
    }
    if not force and not _queue_sweep_due(current_ms):
        summary["throttled"] = True
        return summary
    try:
        queued_keys = _queued_discussion_job_keys()
    except Exception:  # noqa: BLE001 - the sweep must never break its host
        _record_queue_sweep_event(summary)
        return summary
    from core.web.services.team_workflow import meeting_rounds

    for team_id, meeting_round_id in queued_keys:
        summary["scanned"] += 1
        try:
            meeting = meeting_rounds.get_meeting_round(team_id, meeting_round_id)[
                "meetingRound"
            ]
        except Exception:  # noqa: BLE001 - one broken meeting cannot stop the sweep
            summary["skipped"] += 1
            continue
        summary["queued"] += 1
        last_activity_ms = _parse_iso_epoch_ms(
            meeting.get("updatedAt") or meeting.get("createdAt")
        )
        if last_activity_ms is None:
            summary["skipped"] += 1
            continue
        if current_ms - last_activity_ms <= QUEUE_ACTIVITY_RENEW_AFTER_MS:
            summary["skipped"] += 1
            continue
        try:
            updated = meeting_rounds.record_meeting_queue_activity(
                team_id, meeting_round_id
            )
        except Exception:  # noqa: BLE001 - one broken meeting cannot stop the sweep
            summary["skipped"] += 1
            continue
        if updated is None:
            summary["skipped"] += 1
        else:
            summary["renewed"] += 1
    if summary["renewed"]:
        _record_queue_sweep_event(summary)
    return summary


def _record_queue_sweep_event(summary: Mapping[str, Any]) -> None:
    """Bounded queue-sweep evidence, following the digest watchdog pattern."""

    try:
        from core.web.services.runtime_scene_service import (
            record_runtime_scene_event_quietly,
        )

        record_runtime_scene_event_quietly(
            "team_workflow",
            "meeting_discussion_queue",
            "meeting_discussion.queue_activity_renewed",
            message="Queued discussion driver meeting activity renewed.",
            level="info",
            outcome="completed",
            fields={
                "scanned": int(summary.get("scanned") or 0),
                "queued": int(summary.get("queued") or 0),
                "renewed": int(summary.get("renewed") or 0),
                "skipped": int(summary.get("skipped") or 0),
            },
            lifecycle=True,
        )
    except Exception:
        # A diagnostic outage must not alter the sweep outcome.
        return


def _digest_work_stuck(work: Mapping[str, Any], now_ms: int) -> bool:
    """A running digest intent whose fence has passed proves a wedged holder.

    The digest lease derives from the bounded review-call budget actually in
    effect and is clamped to the meeting deadline, so a lease that expired
    in-process cannot belong to a healthy call; deadline-only records (no
    lease) go stale exactly when their governed deadline passes.
    """

    if str(work.get("status") or "").strip().lower() != STATUS_RUNNING:
        return False
    if _lease_expired(work, now_ms):
        return True
    deadline_at_ms = work.get("deadlineAtMs")
    return (
        isinstance(deadline_at_ms, int)
        and not isinstance(deadline_at_ms, bool)
        and deadline_at_ms > 0
        and now_ms >= deadline_at_ms
    )


def sweep_stuck_digest_works(
    *,
    now_ms: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """In-process watchdog: fail ``run_digest`` intents stuck past their fence.

    The 2026-09 ghost-lock incident left digest drafts waiting on the module
    lock forever while their durable intent stayed ``running``; only a
    restart-time sweep could recover them.  This sweep is hosted by the
    resident maintenance tick (no second scheduler): for every meeting whose
    latest ``run_digest`` intent is ``running`` past its lease or governed
    deadline it fences the attempt ``failed`` and writes a structured
    ``summaryDraftError`` (``summary_draft_stuck``, retry label) so the
    projection offers a working retry entry.  It never re-drives — re-running
    the LLM stays the startup sweep's job — and it never raises: one broken
    team or meeting is isolated into ``skipped``.  Self-throttled; pass
    ``force=True`` (tests) to bypass the throttle.
    """

    summary: dict[str, Any] = {
        "teams": 0,
        "scanned": 0,
        "fenced": 0,
        "summaryErrors": 0,
        "skipped": 0,
    }
    current_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if not force and not _digest_stuck_sweep_due(current_ms):
        summary["throttled"] = True
        return summary
    try:
        team_ids = _team_ids_with_meeting_rounds()
    except Exception:  # noqa: BLE001 - the watchdog must never break its host
        _record_digest_stuck_sweep_event(summary)
        return summary
    for team_id in team_ids:
        summary["teams"] += 1
        try:
            _sweep_team_stuck_digest_works(team_id, summary, current_ms)
        except Exception:  # noqa: BLE001 - one broken team cannot stop the sweep
            summary["skipped"] += 1
    _record_digest_stuck_sweep_event(summary)
    return summary


def _sweep_team_stuck_digest_works(
    team_id: str,
    summary: dict[str, Any],
    now_ms: int,
) -> None:
    latest: dict[str, Mapping[str, Any]] = {}
    for record in _read_records(work_path(team_id)):
        if str(record.get("actionKind") or "") != ACTION_RUN_DIGEST:
            continue
        meeting_round_id = str(record.get("meetingRoundId") or "")
        if meeting_round_id:
            latest[meeting_round_id] = record
    meeting_rounds = _meeting_rounds()
    for meeting_round_id, work in latest.items():
        summary["scanned"] += 1
        if not _digest_work_stuck(work, now_ms):
            summary["skipped"] += 1
            continue
        work_id = str(work.get("workId") or "")
        overdue_ms = _stuck_overdue_ms(work, now_ms)
        record_intent(
            team_id,
            meeting_round_id,
            status=STATUS_FAILED,
            action_kind=ACTION_RUN_DIGEST,
            last_problem=STUCK_DIGEST_PROBLEM,
        )
        summary["fenced"] += 1
        summary_error_written = False
        try:
            meeting = meeting_rounds.get_meeting_round(team_id, meeting_round_id)[
                "meetingRound"
            ]
        except Exception:  # noqa: BLE001 - meeting read failure skips the error write
            meeting = None
        if meeting is not None and (
            str(meeting.get("status") or "").strip().lower() == "summarizing"
        ):
            try:
                meeting_rounds.record_meeting_summary_draft_error(
                    team_id,
                    meeting_round_id,
                    dict(_STUCK_SUMMARY_DRAFT_ERROR),
                )
                summary_error_written = True
                summary["summaryErrors"] += 1
            except Exception:  # noqa: BLE001 - retry entry is best-effort; the fenced work stays failed
                summary_error_written = False
        _record_digest_stuck_event(
            team_id,
            meeting_round_id,
            work_id=work_id,
            overdue_ms=overdue_ms,
            summary_error_written=summary_error_written,
        )


def _stuck_overdue_ms(work: Mapping[str, Any], now_ms: int) -> int:
    """How far past its fence the stuck intent was when fenced."""

    expires_at_ms = work.get("leaseExpiresAtMs")
    if isinstance(expires_at_ms, int) and not isinstance(expires_at_ms, bool) and expires_at_ms > 0:
        return max(0, now_ms - expires_at_ms)
    deadline_at_ms = work.get("deadlineAtMs")
    if isinstance(deadline_at_ms, int) and not isinstance(deadline_at_ms, bool) and deadline_at_ms > 0:
        return max(0, now_ms - deadline_at_ms)
    return 0


def _record_digest_stuck_event(
    team_id: str,
    meeting_round_id: str,
    *,
    work_id: str,
    overdue_ms: int,
    summary_error_written: bool,
) -> None:
    """Bounded ghost-lock triage evidence for one fenced digest attempt."""

    try:
        from core.web.services.runtime_scene_service import (
            record_runtime_scene_event_quietly,
        )

        record_runtime_scene_event_quietly(
            "team_workflow",
            "meeting_digest_stuck",
            "meeting_digest.stuck_fenced",
            message="Running digest intent fenced after its bounded fence passed.",
            level="warning",
            outcome="failed",
            fields={
                "teamId": str(team_id),
                "meetingRoundId": str(meeting_round_id),
                "workId": str(work_id),
                "overdueMs": max(0, int(overdue_ms)),
                "summaryDraftErrorWritten": bool(summary_error_written),
            },
            lifecycle=True,
        )
    except Exception:  # noqa: BLE001 - diagnostics must never alter recovery
        return


def _record_digest_stuck_sweep_event(summary: Mapping[str, Any]) -> None:
    """Bounded watchdog evidence, following the startup sweep quiet pattern."""

    try:
        from core.web.services.runtime_scene_service import (
            record_runtime_scene_event_quietly,
        )

        record_runtime_scene_event_quietly(
            "team_workflow",
            "meeting_digest_stuck",
            "meeting_digest.stuck_sweep_completed",
            message="Stuck digest work watchdog sweep finished.",
            level="info",
            outcome="completed",
            fields={
                "teams": int(summary.get("teams") or 0),
                "scanned": int(summary.get("scanned") or 0),
                "fenced": int(summary.get("fenced") or 0),
                "summaryErrors": int(summary.get("summaryErrors") or 0),
                "skipped": int(summary.get("skipped") or 0),
            },
            lifecycle=True,
        )
    except Exception:
        # A diagnostic outage must not alter the watchdog outcome.
        return


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
