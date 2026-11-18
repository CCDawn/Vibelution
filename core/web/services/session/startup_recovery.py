"""Startup recovery sweep for interrupted session turns and queued turns.

Claim scope: after a backend restart, ordinary sessions can be left with an
open (never-settled) turn and/or undrained queued user turns, because the
in-memory running registry is empty and nobody re-triggers the queue drain.
This sweep runs once after the workbench lifespan is ready and:

- resumes an interrupted turn by resubmitting its original user prompt with
  ``turn_mode="hot_restart_resume"`` (the daemon hot-restart wake precedent:
  the kind keeps the message out of the real user-message channel), restoring
  the interrupted turn's persisted write intent and per-turn model selection
  from the journal so the recovery turn is authorized and modeled like the
  original, guarded by the operator ``session_recovery`` switch and a
  per-turn retry budget;
- appends one ``session_recovery_resumed`` status line to the conversation
  when a resume is accepted (the journal projection derives ``turnItems`` from
  the content, so the row survives the timeline visibility filter);
- schedules the queued-turn drain for sessions with pending queue rows.

Companion (virtual-human) sessions are skipped entirely — Companion chains
keep their own delivery path and must never be touched by this sweep. The
runtime's own 120s stale-turn reconciliation path is left exactly as it was;
this sweep covers turns whose chat_turn work-run snapshot is still active
(status queued/running/stopping/paused with no finishedAt) at startup, which
no live process can own right after a restart, plus — as an age-bounded
fallback — turns the runtime itself stamped ``turn_interrupted`` with
``reason=process_restarted``. A hard kill never reaches the graceful shutdown
hook that writes the marker, so without that fallback those turns waited for
the operator to press continue.

The sweep is best-effort: any failure is counted and logged, never raised, so
backend startup never blocks on recovery.
"""

from __future__ import annotations

import json

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

from core.chat.turn_journal import (
    EVENT_SESSION_RECOVERY_RESUMED,
    EVENT_TURN_INTERRUPTED,
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    latest_open_turn_id,
)
from core.chat.session_activity import activity_can_continue
from core.runtime_manager.work_run_status import work_run_has_execution
from core.session_recovery_flags import (
    is_session_recovery_enabled,
    session_recovery_max_auto_retries,
)
from core.web.services.session.limits import recovery_worker_limit

logger = logging.getLogger(__name__)

# Persisted per-conversation retry ledger (conversation state field). Keyed by
# the resume chain: ``originTurnId`` is the first interrupted turn of the
# chain, ``resumedTurnId`` the turn produced by the last accepted resume, so a
# re-interruption of a resumed turn keeps counting against the same budget.
RECOVERY_STATE_KEY = "session_recovery"

# Work-run snapshot statuses that mean "a live process owned this turn" —
# impossible right after a restart, so the snapshot marks the turn interrupted.

_TURN_LABEL_MAX_CHARS = 60

# Chat-turn leases that prove the interrupted turn ran with write intent. The
# submit path derives them from ``writeIntent``/content markers and persists
# the acquired leases on the journal ``turn_started`` payload, so a write
# lease is the durable journal fact of the original turn's authorization.
_WRITE_INTENT_CHAT_LEASES = frozenset({"worktree_write", "memory_write"})

# Re-entrancy guards: the sweep itself must be single-flight per process, and
# each (session, interrupted turn) pair is claimed before resubmitting so a
# multi-source startup window cannot double-fire the same resume.
_SWEEP_LOCK = threading.Lock()
_SWEEP_IN_FLIGHT = False
_RESUMED_TURN_KEYS_LOCK = threading.Lock()
_RESUMED_TURN_KEYS: set[str] = set()


# Bounded pool for the per-session candidate pass. Store reads are IO bound,
# and once the resume-window prefilter has narrowed the candidate set the
# ceiling stops mattering, so it stays small on purpose.
_SWEEP_MAX_WORKERS = 8

# Fixed gap between candidate submissions on the pool. Every resumed turn
# immediately starts appending to its turn_journal, and each append invalidates
# the session detail projection: parallel "all at once" recovery makes several
# sessions replay full journals concurrently on the GIL at the same moment the
# frontend starts polling, starving the asyncio loop's SSE heartbeats (client
# disconnect/reconnect storm = UI flicker). Rolling submissions keep automatic
# recovery fully intact while spreading the projection-rebuild load: N
# candidates come up across roughly (N-1) * this many seconds.
_RECOVERY_STAGGER_SECONDS = 7.0


def _service():
    from core.web.services import session_service

    return session_service


def _shutdown_requested(should_stop: Callable[[], bool] | None) -> bool:
    if should_stop is None:
        return False
    try:
        return bool(should_stop())
    except Exception:  # noqa: BLE001 - uncertainty must stop recovery writes
        logger.warning("Session startup recovery stop fence failed; aborting the sweep.")
        return True


def _new_summary() -> dict[str, Any]:
    return {
        "trigger": "backend_startup",
        "enabled": True,
        "scannedSessionCount": 0,
        "resumedCount": 0,
        "retryLimitSkipCount": 0,
        "companionSkipCount": 0,
        "noInterruptedTurnCount": 0,
        "noActiveTurnSkipCount": 0,
        "journalInterruptResumeCount": 0,
        "continuableResumeCount": 0,
        "phaseCompanionMs": 0,
        "phaseActiveMs": 0,
        "phasePrefilterMs": 0,
        "phaseCandidatesMs": 0,
        "alreadyResumedSkipCount": 0,
        "unreadableSessionSkipCount": 0,
        "queuedDrainScheduledCount": 0,
        "errorCount": 0,
        "sessionIndexCount": 0,
        "candidateCount": 0,
        "prefilterSkippedCount": 0,
        "tailSkippedCount": 0,
        "markerResumeCount": 0,
        "workerCount": 1,
        "watermarkApplied": False,
        "durationMs": 0,
    }


def _clear_restart_resume_pending(s: Any) -> None:
    """Drop the marker once a clean sweep has consumed it."""

    from .restart_resume_pending import clear_pending_restart_resume

    try:
        clear_pending_restart_resume(getattr(s, "_WORK_RUN_STORE", None))
    except Exception:  # noqa: BLE001 - a stale marker is retried next startup
        return


def _load_restart_resume_pending(s: Any) -> dict[str, set[str]]:
    """Turns a graceful restart interrupted, keyed by session id."""

    from .restart_resume_pending import load_pending_restart_resume

    try:
        pending = load_pending_restart_resume(getattr(s, "_WORK_RUN_STORE", None))
    except Exception:  # noqa: BLE001 - a bad marker must not break the sweep
        return {}
    return pending if isinstance(pending, dict) else {}


def _active_chat_turn_session_ids(s: Any) -> set[str] | None:
    """Session ids owning a still-active chat_turn work-run after a restart.

    Reading every session's journal is the expensive half of the sweep. A
    session with no active chat_turn snapshot cannot own a turn this process
    died inside, so it never needs that read.

    Returns ``None`` when the store cannot be read: narrowing on a failed
    query would silently drop recovery, so callers fall back to the full scan.
    """

    try:
        snapshots = s._WORK_RUN_STORE.load_active_snapshots("chat_turn")
    except Exception:  # noqa: BLE001 - unknown store failure must not narrow
        return None
    if not isinstance(snapshots, list):
        return None
    session_ids: set[str] = set()
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        session_id = str(snapshot.get("sessionId") or "").strip()
        if session_id:
            session_ids.add(session_id)
    return session_ids


def _companion_session_ids(s: Any) -> set[str] | None:
    """Direct Session ids bound to Companion-flagged agents (frontend parity).

    Returns ``None`` when the Agent Directory cannot be read: in that case the
    sweep cannot prove which sessions are Companion-scoped and stays silent
    (red line: never touch a Companion session by guesswork).
    """

    try:
        # Both Companion identity fields survive summary projection; full
        # hydration also repairs unrelated Agent assets and loads policies.
        agents = s.agent_directory_service.list_agents(include_archived=True, detail="summary")
    except Exception as exc:  # noqa: BLE001 - directory outage must not guess
        logger.warning(
            "Session startup recovery skipped: companion scoping unavailable (%s).",
            type(exc).__name__,
        )
        return None
    session_ids: set[str] = set()
    for agent in list(agents or []):
        if not isinstance(agent, dict):
            continue
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        if metadata.get("virtualHumanCompanion") is not True:
            continue
        direct_session_id = str(agent.get("directSessionId") or "").strip()
        if direct_session_id:
            session_ids.add(direct_session_id)
    return session_ids


# Restarts never reach the graceful shutdown hook, so neither the shutdown
# marker nor an active chat_turn snapshot survives them. The runtime still
# stamps the abandoned turn with ``turn_interrupted`` plus the stop reason it
# was given; that journal fact is the only durable evidence left, and this
# sweep falls back to it. Two reasons mean "a restart took this turn":
# ``process_restarted`` (runtime reconcile) and ``electron_user_restart``
# (the Electron lifecycle stop in control.py _RUNTIME_STOP_REASONS). Operator
# leave (``electron_user_close``) and full shutdown (``runtime_shutdown``)
# stay excluded so a deliberate stop is never auto-resumed. The age window
# keeps a stale interrupted turn from being replayed at every startup.
_RESTART_INTERRUPT_REASONS = frozenset({"process_restarted", "electron_user_restart"})

# Journal interrupt reasons map onto the shared Session activity contract so
# the sweep and the composer continue button judge "continuable" identically.
# A deliberate operator stop carries no mapping and therefore stays stopped.
_INTERRUPT_REASON_ACTIVITY_OUTCOME = {
    "process_restarted": "stopped",
    "electron_user_restart": "stopped",
    "stale_work_run_worker_gone": "stopped",
}
# Continuable as an outcome, but the operator closed the window or shut the
# runtime down on purpose: never auto-resume these.
_AUTO_RESUME_EXCLUDED_REASONS = frozenset({"electron_user_close", "runtime_shutdown"})


def _interrupt_reason_can_continue(reason: str) -> bool:
    """Whether a journal interrupt reason stays continuable under the contract."""

    normalized = str(reason or "").strip()
    if not normalized or normalized in _AUTO_RESUME_EXCLUDED_REASONS:
        return False
    outcome = _INTERRUPT_REASON_ACTIVITY_OUTCOME.get(normalized)
    if outcome is None:
        return False
    return activity_can_continue(outcome)
_RESTART_INTERRUPT_MAX_AGE_SECONDS = 30 * 60.0
_RESTART_INTERRUPT_MAX_AGE_ENV = "VIBELUTION_SESSION_RECOVERY_MAX_AGE_SECONDS"


def _resume_age_window_seconds() -> float:
    """Bounded age window for the journal-only restart-interrupt fallback."""

    raw = str(os.environ.get(_RESTART_INTERRUPT_MAX_AGE_ENV) or "").strip()
    if not raw:
        return _RESTART_INTERRUPT_MAX_AGE_SECONDS
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return _RESTART_INTERRUPT_MAX_AGE_SECONDS
    return value if value > 0 else _RESTART_INTERRUPT_MAX_AGE_SECONDS


def _within_resume_age_window(timestamp: str, *, now: float | None = None) -> bool:
    """Whether an interrupted turn is recent enough to resume automatically."""

    raw = str(timestamp or "").strip()
    if not raw:
        return False
    try:
        stamped = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if stamped.tzinfo is None:
        stamped = stamped.replace(tzinfo=timezone.utc)
    observed = time.time() if now is None else float(now)
    return (observed - stamped.timestamp()) <= _resume_age_window_seconds()


def _latest_restart_interrupted_turn(events: list[Any]) -> tuple[str, str]:
    """Latest turn the runtime stamped ``turn_interrupted`` because of a restart.

    Returns ``(turn_id, timestamp)`` or ``("", "")``. Only interruptions whose
    payload reason is a restart reason (``_RESTART_INTERRUPT_REASONS``)
    qualify: a turn the operator cancelled carries a different reason and must
    stay cancelled. Turns an
    earlier sweep already resumed are skipped so one crash is not replayed
    forever.
    """

    raw_events = list(events or [])
    started_turn_ids = {
        str(getattr(event, "turn_id", "") or "").strip()
        for event in raw_events
        if str(getattr(event, "event_type", "") or "").strip() == EVENT_TURN_STARTED
    }
    already_resumed: set[str] = set()
    for event in raw_events:
        if str(getattr(event, "event_type", "") or "").strip() != EVENT_SESSION_RECOVERY_RESUMED:
            continue
        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            continue
        # The runtime nests the ids under ``recovery`` (see the journal row
        # ``{recovery: {recoveredTurnId: ...}}``), so reading only the payload
        # top level silently disabled this guard and replayed one crash on
        # every startup. Read both shapes.
        sources = [payload]
        nested = payload.get("recovery")
        if isinstance(nested, dict):
            sources.append(nested)
        for source in sources:
            for key in ("recoveredTurnId", "originalTurnId", "openTurnId"):
                recovered = str(source.get(key) or "").strip()
                if recovered:
                    already_resumed.add(recovered)
    already_resumed_skips = 0
    for event in reversed(raw_events):
        if str(getattr(event, "event_type", "") or "").strip() != EVENT_TURN_INTERRUPTED:
            continue
        turn_id = str(getattr(event, "turn_id", "") or "").strip()
        if not turn_id or turn_id not in started_turn_ids:
            continue
        if turn_id in already_resumed:
            already_resumed_skips += 1
            continue
        payload = getattr(event, "payload", None)
        reason = str(payload.get("reason") or "").strip() if isinstance(payload, dict) else ""
        if reason not in _RESTART_INTERRUPT_REASONS:
            continue
        return turn_id, str(getattr(event, "timestamp", "") or "").strip(), already_resumed_skips
    return "", "", already_resumed_skips


def _latest_continuable_turn(events: list[Any]) -> tuple[str, str, int]:
    """Latest settled turn the shared activity contract still lets continue.

    Journal twin of the composer's continue button: the turn's terminal
    outcome must be continuable (``continuableOutcomes``) and no earlier sweep
    may already have resumed it. Interruptions the operator caused deliberately
    carry a reason outside ``_INTERRUPT_REASON_ACTIVITY_OUTCOME`` and stay
    stopped.
    """

    raw_events = list(events or [])
    started_turn_ids = {
        str(getattr(event, "turn_id", "") or "").strip()
        for event in raw_events
        if str(getattr(event, "event_type", "") or "").strip() == EVENT_TURN_STARTED
    }
    already_resumed: set[str] = set()
    for event in raw_events:
        if str(getattr(event, "event_type", "") or "").strip() != EVENT_SESSION_RECOVERY_RESUMED:
            continue
        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            continue
        sources = [payload]
        nested = payload.get("recovery")
        if isinstance(nested, dict):
            sources.append(nested)
        for source in sources:
            for key in ("recoveredTurnId", "originalTurnId", "openTurnId"):
                recovered = str(source.get(key) or "").strip()
                if recovered:
                    already_resumed.add(recovered)
    already_resumed_skips = 0
    for event in reversed(raw_events):
        if str(getattr(event, "event_type", "") or "").strip() != EVENT_TURN_INTERRUPTED:
            continue
        turn_id = str(getattr(event, "turn_id", "") or "").strip()
        if not turn_id or turn_id not in started_turn_ids:
            continue
        if turn_id in already_resumed:
            already_resumed_skips += 1
            continue
        payload = getattr(event, "payload", None)
        reason = str(payload.get("reason") or "").strip() if isinstance(payload, dict) else ""
        if not _interrupt_reason_can_continue(reason):
            continue
        return turn_id, str(getattr(event, "timestamp", "") or "").strip(), already_resumed_skips
    return "", "", already_resumed_skips


_TAIL_READ_BYTES = 32 * 1024
_TAIL_READ_BYTES_MAX = 256 * 1024

_TAIL_TERMINAL_EVENT_TYPES = frozenset(
    {"turn_completed", "turn_failed", "turn_interrupted"}
)


def _tail_ledger_rows(
    s: Any, session_id: str, *, limit_bytes: int = _TAIL_READ_BYTES
) -> tuple[list[dict[str, Any]], bool, tuple[int, int] | None]:
    """Newest rows of the session ledger, without loading the whole journal.

    Startup recovery only needs the newest turn-level fact: a settled turn, a
    restart interruption, or a turn that is still open. Active agent sessions
    keep ledgers tens of megabytes long, and parsing them end to end dominated
    the sweep even after the candidate set had been narrowed.
    """

    from pathlib import Path

    from core.chat.turn_journal import turn_journal_path

    path = Path(turn_journal_path(s.PROJECT_ROOT, session_id))
    try:
        before = path.stat()
        size = before.st_size
        with path.open("rb") as handle:
            truncated = size > limit_bytes
            if truncated:
                handle.seek(size - limit_bytes)
            chunk = handle.read()
        after = path.stat()
    except OSError:
        return [], False, None
    signature = (
        (int(before.st_mtime_ns), int(before.st_size))
        if before.st_mtime_ns == after.st_mtime_ns
        and before.st_size == after.st_size
        else None
    )
    lines = chunk.split(b"\n")
    if truncated and lines:
        # The tail window cut the oldest row mid-record.
        lines = lines[1:]
    rows: list[dict[str, Any]] = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows, truncated, signature


def _tail_resumed_turn_ids(rows: list[dict[str, Any]]) -> set[str]:
    resumed: set[str] = set()
    for row in rows:
        if str(row.get("eventType") or "").strip() != "session_recovery_resumed":
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        sources: list[dict[str, Any]] = [payload]
        nested = payload.get("recovery")
        if isinstance(nested, dict):
            sources.append(nested)
        for source in sources:
            for key in ("recoveredTurnId", "originalTurnId", "openTurnId"):
                value = str(source.get(key) or "").strip()
                if value:
                    resumed.add(value)
    return resumed


def _hint_may_need_resume(s: Any, session_id: str) -> tuple[bool, int] | None:
    """Verdict from the journal sidecar hint, or ``None`` when it is stale.

    The journal append path writes the hint beside the file it describes, so a
    matching signature means the newest turn fact on disk is exactly what the
    hint says. Anything else (missing, damaged, foreign append) returns
    ``None`` and the caller falls back to reading the journal tail.
    """

    from pathlib import Path

    from core.chat.turn_journal import turn_journal_path
    from core.chat.turn_journal_hint import hint_matches_journal, read_journal_hint

    try:
        path = Path(turn_journal_path(s.PROJECT_ROOT, session_id))
    except Exception:  # noqa: BLE001 - unknown path means "must inspect"
        return None
    hint = read_journal_hint(path)
    if hint is None or not hint_matches_journal(path, hint):
        return None
    terminal_type = str(hint.get("terminalType") or "").strip()
    if terminal_type and terminal_type != EVENT_TURN_INTERRUPTED:
        # A completed or failed turn holds nothing to resume.
        return False, 0
    # An interrupted or open turn also needs the resumed-chain detail that
    # this hint deliberately does not carry, so the journal tail decides.
    return None


def _backfill_hint(
    s: Any,
    session_id: str,
    *,
    rows: list[dict[str, Any]],
    signature: tuple[int, int] | None,
) -> None:
    """Persist a settled tail verdict so later sweeps skip this journal.

    Only a settled verdict is backfilled: an open or restart-interrupted
    turn still needs the resumed-chain detail the hint does not carry, so
    it keeps using the tail. A missing signature means the journal moved
    while we read it, and then no hint is written at all.
    """

    if signature is None:
        return
    from pathlib import Path

    from core.chat.turn_journal import (
        TURN_STATE_OPEN,
        TURN_STATE_TERMINAL,
        turn_journal_path,
    )
    from core.chat.turn_journal_hint import write_journal_hint

    for row in reversed(rows):
        event_type = str(row.get("eventType") or "").strip()
        if (
            event_type not in _TAIL_TERMINAL_EVENT_TYPES
            and event_type != "turn_started"
        ):
            continue
        turn_id = str(row.get("turnId") or "").strip()
        if not turn_id:
            return
        try:
            sequence = int(row.get("sequence") or 0)
        except (TypeError, ValueError):
            sequence = 0
        terminal_type = (
            event_type if event_type in _TAIL_TERMINAL_EVENT_TYPES else ""
        )
        try:
            path = Path(turn_journal_path(s.PROJECT_ROOT, session_id))
        except Exception:  # noqa: BLE001 - no path means no hint
            return
        write_journal_hint(
            path,
            turn_id=turn_id,
            turn_state=TURN_STATE_TERMINAL if terminal_type else TURN_STATE_OPEN,
            terminal_type=terminal_type,
            event_type=event_type,
            sequence=sequence,
            expected_signature=signature,
        )
        return


def _tail_may_need_resume(s: Any, session_id: str) -> tuple[bool | None, int]:
    """``False`` when the ledger tail proves nothing is resumable.

    ``True`` and ``None`` both mean "load the full events": a turn is still
    open or was restart-interrupted, or the tail was too short to decide. Only
    ``False`` may skip the journal read, so an unusual tail can never hide a
    genuine recovery.
    """

    hinted = _hint_may_need_resume(s, session_id)
    if hinted is not None:
        return hinted
    rows, truncated, signature = _tail_ledger_rows(s, session_id)
    if not rows:
        return False, 0
    verdict, resumed_skips = _tail_verdict(rows)
    if verdict is None and truncated:
        # A narrow probe keeps every settled session cheap; only a tail
        # without a single turn-level row pays for the wide window.
        wide_rows, _wide_truncated, wide_signature = _tail_ledger_rows(
            s, session_id, limit_bytes=_TAIL_READ_BYTES_MAX
        )
        if wide_rows:
            rows, signature = wide_rows, wide_signature
            verdict, resumed_skips = _tail_verdict(wide_rows)
    if verdict is False:
        # Settled sessions are the bulk of every sweep; recording the
        # verdict here is what retires their journal tail from startup.
        _backfill_hint(s, session_id, rows=rows, signature=signature)
    return verdict, resumed_skips


def _tail_verdict(rows: list[dict[str, Any]]) -> tuple[bool | None, int]:
    """Decide from one ledger tail whether any turn may need a resume.

    ``False`` means settled, ``True`` an open turn, ``None`` cannot tell.
    """

    resumed_turn_ids = _tail_resumed_turn_ids(rows)
    for row in reversed(rows):
        event_type = str(row.get("eventType") or "").strip()
        turn_id = str(row.get("turnId") or "").strip()
        if event_type == "turn_interrupted" and turn_id:
            if turn_id in resumed_turn_ids:
                return False, 1
            payload = row.get("payload")
            reason = (
                str(payload.get("reason") or "").strip()
                if isinstance(payload, dict)
                else ""
            )
            return _interrupt_reason_can_continue(reason), 0
        if event_type in _TAIL_TERMINAL_EVENT_TYPES:
            return False, 0
        if event_type == "turn_started":
            return True, 0
    return None, 0


def _open_turn_work_run_is_interrupted(
    s: Any,
    turn_id: str,
    pending_turn_ids: set[str] | None = None,
    *,
    journal_interrupt_evidence: bool = False,
) -> bool:
    """Whether the open turn's chat_turn work-run snapshot is still active.

    A finished or missing snapshot means the runtime's own reconcile path owns
    the turn; only a still-active snapshot right after a restart proves the
    process died mid-turn, which this sweep may recover without the runtime's
    120s grace window.
    """

    snapshot = s._WORK_RUN_STORE.load_active_snapshot_for_run("chat_turn", turn_id)
    if isinstance(snapshot, dict):
        return work_run_has_execution(snapshot)
    # A graceful restart writes the same terminal ``stopped`` state a manual
    # stop writes, so the snapshot cannot prove which one happened. The
    # shutdown marker is the evidence that a graceful restart interrupted this
    # turn instead of the operator cancelling it.
    if pending_turn_ids and turn_id in pending_turn_ids:
        return True
    # Hard kill: no marker was ever written. The journal's own
    # ``turn_interrupted`` stamp with ``reason=process_restarted`` is then the
    # only surviving evidence, and the caller already bounded it by age.
    return bool(journal_interrupt_evidence)


def _interrupted_turn_prompt(events: list[Any], turn_id: str) -> str:
    """The interrupted turn's original user prompt from the journal payload."""

    for event in reversed(list(events or [])):
        if str(getattr(event, "event_type", "") or "").strip() != EVENT_USER_MESSAGE:
            continue
        if str(getattr(event, "turn_id", "") or "").strip() != turn_id:
            continue
        payload = getattr(event, "payload", None)
        content = payload.get("content") if isinstance(payload, dict) else ""
        return str(content or "").strip()
    return ""


def _interrupted_turn_attachment_ids(events: list[Any], turn_id: str) -> list[str]:
    """The interrupted turn's attachment artifact ids from the journal payload.

    The journal stores attachment metadata only (artifactId/url, no bytes), so
    a faithful resume re-passes the ids and the submit path re-resolves the
    artifacts exactly like the original submission did.
    """

    for event in reversed(list(events or [])):
        if str(getattr(event, "event_type", "") or "").strip() != EVENT_USER_MESSAGE:
            continue
        if str(getattr(event, "turn_id", "") or "").strip() != turn_id:
            continue
        payload = getattr(event, "payload", None)
        attachments = payload.get("attachments") if isinstance(payload, dict) else None
        artifact_ids: list[str] = []
        for attachment in list(attachments or []):
            if not isinstance(attachment, dict):
                continue
            artifact_id = str(attachment.get("artifactId") or "").strip()
            if artifact_id and artifact_id not in artifact_ids:
                artifact_ids.append(artifact_id)
        return artifact_ids
    return []


def interrupted_turn_resume_intent(events: list[Any], *, turn_id: str) -> dict[str, Any]:
    """The interrupted turn's persisted write intent and model override.

    ``modelSelection`` rides the user-message metadata (submit persists the
    per-turn override there, including ``reasoningEffort`` when pinned). Write
    intent has no direct metadata field: an explicit ``metadata.writeIntent``
    wins when present, otherwise the write leases acquired on the journal
    ``turn_started`` payload are the durable fact of what the original turn
    was authorized to do. Anything unreadable degrades to the pre-existing
    defaults (``writeIntent=False`` / no override) instead of guessing.
    """

    normalized_turn_id = str(turn_id or "").strip()
    explicit_write_intent: bool | None = None
    model_selection: dict[str, Any] | None = None
    started_leases: list[str] = []
    for event in reversed(list(events or [])):
        if str(getattr(event, "turn_id", "") or "").strip() != normalized_turn_id:
            continue
        event_type = str(getattr(event, "event_type", "") or "").strip()
        if event_type != EVENT_USER_MESSAGE:
            continue
        payload = getattr(event, "payload", None)
        metadata = payload.get("metadata") if isinstance(payload, dict) else None
        if isinstance(metadata, dict):
            raw_write_intent = metadata.get("writeIntent")
            if isinstance(raw_write_intent, bool):
                explicit_write_intent = raw_write_intent
            raw_selection = metadata.get("modelSelection")
            if (
                isinstance(raw_selection, dict)
                and str(raw_selection.get("modelId") or raw_selection.get("modelRef") or "").strip()
            ):
                model_selection = dict(raw_selection)
        break
    for event in list(events or []):
        if str(getattr(event, "turn_id", "") or "").strip() != normalized_turn_id:
            continue
        if str(getattr(event, "event_type", "") or "").strip() != EVENT_TURN_STARTED:
            continue
        payload = getattr(event, "payload", None)
        leases = payload.get("leases") if isinstance(payload, dict) else None
        started_leases = [str(item or "").strip() for item in list(leases or [])]
    if explicit_write_intent is not None:
        write_intent = explicit_write_intent
    else:
        write_intent = any(lease in _WRITE_INTENT_CHAT_LEASES for lease in started_leases)
    return {"writeIntent": write_intent, "modelSelection": model_selection}


def session_resume_intent_snapshot(session_id: str) -> dict[str, Any]:
    """Resume intent of the session's open (interrupted) turn, daemon-safe.

    Used by the hot-restart wake, which must read the interrupted turn before
    stopping it (the stop settles the journal turn and the snapshot would be
    gone). Read failures and missing open turns degrade to the pre-existing
    defaults so the wake never blocks on recovery metadata.
    """

    defaults: dict[str, Any] = {"writeIntent": False, "modelSelection": None, "turnId": ""}
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return defaults
    try:
        s = _service()
        events = s._load_session_conversation_events_cached(normalized_session_id)
        open_turn_id = latest_open_turn_id(events)
        if not open_turn_id:
            return defaults
        intent = interrupted_turn_resume_intent(events, turn_id=open_turn_id)
        return {**intent, "turnId": open_turn_id}
    except Exception:  # noqa: BLE001 - intent metadata must never block the wake
        return defaults


def _recovery_turn_label(prompt: str) -> str:
    """A short, single-line label of the interrupted turn for the status row."""

    label = _first_nonempty_line(prompt)
    if len(label) > _TURN_LABEL_MAX_CHARS:
        label = label[:_TURN_LABEL_MAX_CHARS].rstrip()
    return label


def _first_nonempty_line(prompt: str) -> str:
    for line in str(prompt or "").splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _restart_interrupt_reason(events: list[Any], turn_id: str) -> str:
    """Reason recorded for the newest interruption of ``turn_id``."""

    wanted = str(turn_id or "").strip()
    if not wanted:
        return ""
    for event in reversed(list(events or [])):
        if str(getattr(event, "event_type", "") or "").strip() != EVENT_TURN_INTERRUPTED:
            continue
        if str(getattr(event, "turn_id", "") or "").strip() != wanted:
            continue
        payload = getattr(event, "payload", None)
        return str(payload.get("reason") or "").strip() if isinstance(payload, dict) else ""
    return ""


def _load_recovery_attempts(state: Any, open_turn_id: str) -> int:
    """Attempt budget used so far for the resume chain of ``open_turn_id``."""

    if not isinstance(state, dict):
        return 0
    chain_turn_ids = {
        str(state.get("originTurnId") or "").strip(),
        str(state.get("resumedTurnId") or "").strip(),
    }
    if open_turn_id not in chain_turn_ids:
        return 0
    try:
        return max(0, int(state.get("attempts") or 0))
    except (TypeError, ValueError):
        return 0


def _persist_recovery_state(
    s: Any,
    session_id: str,
    *,
    origin_turn_id: str,
    resumed_turn_id: str,
    attempts: int,
    should_stop: Callable[[], bool] | None = None,
) -> bool:
    """Persist the retry ledger on the conversation state (crash-safe count)."""

    if _shutdown_requested(should_stop):
        return False
    with s._CHAT_STATE_LOCK:
        if _shutdown_requested(should_stop):
            return False
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, session_id)
        if conversation is None:
            return False
        conversation[RECOVERY_STATE_KEY] = {
            "originTurnId": str(origin_turn_id or "").strip(),
            "resumedTurnId": str(resumed_turn_id or "").strip(),
            "attempts": max(0, int(attempts)),
            "updatedAt": s._now_timestamp(),
        }
        conversation["updated_at"] = s._now_timestamp()
        s.save_session_chat_state(s.PROJECT_ROOT, session_id, conversation)
        return True


def _append_recovery_status_line(
    s: Any,
    session_id: str,
    *,
    original_turn_id: str,
    resumed_turn_id: str,
    attempt: int,
    turn_label: str,
) -> None:
    """Journal the ``session_recovery_resumed`` status line.

    Journaled against the synthetic turn id ``session-recovery:{original}``
    (the ``cli-lifecycle:{subject}`` precedent) so the post-terminal guard
    cannot trip and the row does not coalesce into a real turn's assistant
    bubble. The journal projection derives ``turnItems`` from the content, so
    the message survives the timeline ``hasVisibleTurnData`` filter exactly
    like every other assistant message.
    """

    lang = s.get_web_language()
    content = s.text_for(
        lang,
        zh="已从重启中恢复，继续执行",
        en="Recovered after restart and resumed",
    )
    s._append_session_conversation_event(
        session_id,
        f"session-recovery:{original_turn_id}",
        EVENT_SESSION_RECOVERY_RESUMED,
        status="resumed",
        payload={
            "recovery": {
                "content": content,
                "attempt": max(1, int(attempt)),
                "turnLabel": turn_label,
                "recoveredTurnId": original_turn_id,
                "resumedTurnId": resumed_turn_id,
            },
        },
        source="startup_recovery",
        visible_in_model=True,
        projection_kind=EVENT_SESSION_RECOVERY_RESUMED,
        source_kind="session_recovery",
    )


def _resume_interrupted_turn(
    s: Any,
    session_id: str,
    *,
    open_turn_id: str,
    events: list[Any],
    summary: dict[str, Any],
    should_stop: Callable[[], bool] | None = None,
    pending_turn_ids: set[str] | None = None,
    journal_interrupt_evidence: bool = False,
) -> None:
    if _shutdown_requested(should_stop):
        return
    conversation = s.load_session_chat_state(s.PROJECT_ROOT, session_id)
    if conversation is None or s._conversation_is_read_only(conversation):
        summary["noInterruptedTurnCount"] += 1
        return
    if not _open_turn_work_run_is_interrupted(
        s,
        open_turn_id,
        pending_turn_ids,
        journal_interrupt_evidence=journal_interrupt_evidence,
    ):
        summary["noInterruptedTurnCount"] += 1
        return
    prompt = _interrupted_turn_prompt(events, open_turn_id)
    attachment_ids = _interrupted_turn_attachment_ids(events, open_turn_id)
    if not prompt and not attachment_ids:
        # Nothing faithful to resubmit (no prompt and no attachments); the
        # interrupted presentation stays and the user can resend manually.
        summary["noInterruptedTurnCount"] += 1
        return
    # Restore the interrupted turn's authorization and per-turn model override
    # so the recovery turn runs like the original (same write leases, same
    # model, same reasoning effort) instead of silently downgrading both.
    resume_intent = interrupted_turn_resume_intent(events, turn_id=open_turn_id)

    max_retries = max(0, int(session_recovery_max_auto_retries()))
    previous_state = (
        conversation.get(RECOVERY_STATE_KEY)
        if isinstance(conversation.get(RECOVERY_STATE_KEY), dict)
        else {}
    )
    attempts = _load_recovery_attempts(previous_state, open_turn_id)
    # An operator-driven restart is not a poison object: it must not spend the
    # bounded auto-retry budget, or a couple of restarts would silence recovery
    # for this session until somebody types manually.
    if _restart_interrupt_reason(events, open_turn_id) in _RESTART_INTERRUPT_REASONS:
        attempts = 0
    if attempts >= max_retries:
        summary["retryLimitSkipCount"] += 1
        return
    # The chain origin survives across resumes: a re-interrupted resumed turn
    # keeps counting against the same budget instead of starting a new one.
    origin_turn_id = (
        str(previous_state.get("originTurnId") or "").strip() or open_turn_id
        if attempts
        else open_turn_id
    )

    turn_label = _recovery_turn_label(prompt)
    if not turn_label and attachment_ids:
        # Attachment-only turn: an empty text resubmit is valid (submit accepts
        # attachments without content), the label just needs something visible.
        turn_label = "[图片]"
    if _shutdown_requested(should_stop):
        return

    turn_key = f"{session_id}:{open_turn_id}"
    with _RESUMED_TURN_KEYS_LOCK:
        if _shutdown_requested(should_stop):
            return
        if turn_key in _RESUMED_TURN_KEYS:
            return
        _RESUMED_TURN_KEYS.add(turn_key)

    if _shutdown_requested(should_stop):
        with _RESUMED_TURN_KEYS_LOCK:
            _RESUMED_TURN_KEYS.discard(turn_key)
        return
    try:
        detail = s.submit_session_message(
            session_id,
            prompt,
            turn_mode="hot_restart_resume",
            write_intent=bool(resume_intent.get("writeIntent")),
            model_selection=resume_intent.get("modelSelection"),
            client_submission_id=f"resume:{open_turn_id}",
            attachment_ids=attachment_ids or None,
            message_metadata={
                "kind": "hot_restart_resume",
                "recoverySource": "startup_sweep",
                "recoveredTurnId": open_turn_id,
            },
            message_source="hot_restart_resume",
            include_started_turn_id=True,
            # Accept the turn at the scheduler instead of waiting for its worker
            # to start. The started-turn-id request made each resume block for
            # the whole worker handshake, and because a single agent runs its
            # turns serially five recoveries cost 43s of a restart. The light
            # response still returns the turn id assigned at admission.
            lightweight_response=True,
        )
    except Exception as exc:  # noqa: BLE001 - one bad resume must not stop the sweep
        summary["errorCount"] += 1
        # The attempt still burns budget so a poison turn converges to the
        # interrupted presentation instead of retrying forever across restarts.
        try:
            _persist_recovery_state(
                s,
                session_id,
                origin_turn_id=origin_turn_id,
                resumed_turn_id="",
                attempts=attempts + 1,
                should_stop=should_stop,
            )
        except Exception:  # noqa: BLE001 - ledger persistence is best effort
            pass
        logger.warning(
            "Session startup resume submit failed for %s turn %s: %s",
            session_id,
            open_turn_id,
            type(exc).__name__,
        )
        return

    if _shutdown_requested(should_stop):
        return
    resumed_turn_id = str((detail or {}).get("startedTurnId") or (detail or {}).get("turnId") or "").strip()
    if not _persist_recovery_state(
        s,
        session_id,
        origin_turn_id=origin_turn_id,
        resumed_turn_id=resumed_turn_id,
        attempts=attempts + 1,
        should_stop=should_stop,
    ):
        return
    if _shutdown_requested(should_stop):
        return
    _append_recovery_status_line(
        s,
        session_id,
        original_turn_id=open_turn_id,
        resumed_turn_id=resumed_turn_id,
        attempt=attempts + 1,
        turn_label=turn_label,
    )
    s._publish_session_detail_snapshot(session_id)
    summary["resumedCount"] += 1


def _latest_marker_turn_id(events: list[Any], marker_turn_ids: set[str]) -> str:
    """Newest marker turn the journal actually saw, else the marker's own id.

    The marker lists turns a restart stopped. The journal may already carry a
    stop fact for them or may lag the marker write, so prefer the newest
    journal-visible id and fall back to the marker id when the ledger has not
    caught up yet.
    """

    seen: list[str] = []
    for row in events or []:
        turn_id = str(getattr(row, "turn_id", "") or "").strip()
        if turn_id and turn_id in marker_turn_ids and turn_id not in seen:
            seen.append(turn_id)
    if seen:
        return seen[-1]
    ordered = sorted(marker_turn_ids)
    return ordered[-1] if ordered else ""


def _recover_session_on_startup(
    s: Any,
    session_id: str,
    *,
    companion_session_ids: set[str],
    summary: dict[str, Any],
    should_stop: Callable[[], bool] | None = None,
    active_turn_session_ids: set[str] | None = None,
    pending_turn_ids: set[str] | None = None,
    pending_session_turn_ids: dict[str, set[str]] | None = None,
) -> None:
    if _shutdown_requested(should_stop):
        return
    if session_id in companion_session_ids:
        summary["companionSkipCount"] += 1
        return
    summary["scannedSessionCount"] += 1
    conversation = s.load_session_chat_state(s.PROJECT_ROOT, session_id)
    if conversation is None:
        # session_runtime_state rows outlive their sessions row (archived,
        # deleted, or a stale instance workspace). Counting them keeps
        # scannedSessionCount explainable against the visible session list.
        summary["unreadableSessionSkipCount"] += 1
        return
    if _shutdown_requested(should_stop):
        return
    from core.web.services.external_agent.approval_binding import is_external_session
    if is_external_session(conversation):
        # External task authority and its approval bindings are process-local.
        # Never drain or resume this Session as an ordinary chat after restart.
        summary["externalTaskSkipCount"] = summary.get("externalTaskSkipCount", 0) + 1
        return
    queued_rows = s._session_queued_turn_rows(conversation)
    if any(str(row.get("status") or "") in {"queued", "starting"} for row in queued_rows):
        if _shutdown_requested(should_stop):
            return
        # The idle gate and stale-"starting" reset are built into the drain;
        # after a restart nothing else re-triggers it.
        s._schedule_session_queued_turn_drain(session_id)
        summary["queuedDrainScheduledCount"] += 1
        for row in queued_rows:
            if str(row.get("status") or "") == "starting":
                s._schedule_session_queued_turn_stale_retry(
                    session_id,
                    updated_at=str(row.get("updatedAt") or ""),
                )
    if s._is_session_running(session_id):
        return
    if _shutdown_requested(should_stop):
        return
    journal_interrupt_evidence = False
    if active_turn_session_ids is not None and session_id not in active_turn_session_ids:
        # A hard kill leaves neither an active chat_turn snapshot nor a shutdown
        # marker, so this branch used to skip the session without reading its
        # journal at all and the turn waited for the operator to press continue.
        # Fall back to the journal's own restart-interrupt stamp, bounded by age
        # so a stale turn is never replayed at every startup.
        tail_decision, tail_resumed_skips = _tail_may_need_resume(s, session_id)
        summary["alreadyResumedSkipCount"] += tail_resumed_skips
        if tail_decision is False:
            summary["tailSkippedCount"] += 1
            summary["noInterruptedTurnCount"] += 1
            summary["noActiveTurnSkipCount"] += 1
            return
        events = s._load_session_conversation_events_cached(session_id)
        open_turn_id = latest_open_turn_id(events)
        if not open_turn_id:
            (
                candidate_turn_id,
                interrupted_at,
                already_resumed_skips,
            ) = _latest_restart_interrupted_turn(events)
            summary["alreadyResumedSkipCount"] += already_resumed_skips
            if candidate_turn_id and _within_resume_age_window(interrupted_at):
                open_turn_id = candidate_turn_id
                journal_interrupt_evidence = True
                summary["journalInterruptResumeCount"] += 1
        if not open_turn_id:
            (
                continuable_turn_id,
                continuable_at,
                continuable_skips,
            ) = _latest_continuable_turn(events)
            summary["alreadyResumedSkipCount"] += continuable_skips
            if continuable_turn_id and _within_resume_age_window(continuable_at):
                open_turn_id = continuable_turn_id
                journal_interrupt_evidence = True
                summary["continuableResumeCount"] += 1
        if not open_turn_id:
            summary["noInterruptedTurnCount"] += 1
            summary["noActiveTurnSkipCount"] += 1
            return
    else:
        marker_turn_ids = set((pending_session_turn_ids or {}).get(session_id) or ())
        if marker_turn_ids:
            # The restart marker is the authoritative record that a restart
            # interrupted this turn. A stop writes its own terminal fact and a
            # hint can be backfilled as terminal, so the tail alone would skip
            # exactly the turns the operator expects back.
            events = s._load_session_conversation_events_cached(session_id)
            open_turn_id = _latest_marker_turn_id(events, marker_turn_ids)
            if not open_turn_id:
                summary["noInterruptedTurnCount"] += 1
                return
            summary["markerResumeCount"] += 1
        else:
            tail_decision, tail_resumed_skips = _tail_may_need_resume(s, session_id)
            summary["alreadyResumedSkipCount"] += tail_resumed_skips
            if tail_decision is False:
                summary["tailSkippedCount"] += 1
                return
            events = s._load_session_conversation_events_cached(session_id)
            open_turn_id = latest_open_turn_id(events)
            if not open_turn_id:
                (
                    continuable_turn_id,
                    continuable_at,
                    continuable_skips,
                ) = _latest_continuable_turn(events)
                summary["alreadyResumedSkipCount"] += continuable_skips
                if continuable_turn_id and _within_resume_age_window(continuable_at):
                    open_turn_id = continuable_turn_id
                    journal_interrupt_evidence = True
                    summary["continuableResumeCount"] += 1
                else:
                    return
    _resume_interrupted_turn(
        s,
        session_id,
        open_turn_id=open_turn_id,
        events=events,
        summary=summary,
        should_stop=should_stop,
        pending_turn_ids=pending_turn_ids,
        journal_interrupt_evidence=journal_interrupt_evidence,
    )


_SWEEP_COUNTER_FIELDS = (
    "scannedSessionCount",
    "resumedCount",
    "retryLimitSkipCount",
    "companionSkipCount",
    "noInterruptedTurnCount",
    "noActiveTurnSkipCount",
    "journalInterruptResumeCount",
    "continuableResumeCount",
    "alreadyResumedSkipCount",
    "unreadableSessionSkipCount",
    "queuedDrainScheduledCount",
    "externalTaskSkipCount",
    "errorCount",
    "tailSkippedCount",
    "markerResumeCount",
)


def _resume_window_start_ns(*, now_ns: int | None = None) -> int:
    """Lower bound (epoch ns) of the age window this sweep may resume."""

    observed = time.time_ns() if now_ns is None else int(now_ns)
    return observed - int(_resume_age_window_seconds() * 1_000_000_000)


def _session_workspace_root(s: Any) -> Any:
    """Resolve the shared sessions workspace once per prefilter pass.

    ``turn_journal_path`` re-resolves the project identity and ensures the
    sandbox state on every call, so asking it once per session spent seconds of
    config and state reads before a single candidate was inspected. The same
    authority is still used; the result is only reused for the pass.
    """

    from pathlib import Path

    from core.chat.turn_journal import turn_journal_workspace_root

    try:
        return turn_journal_workspace_root(Path(s.PROJECT_ROOT))
    except Exception:  # noqa: BLE001 - unknown root means "resolve per session"
        return None


def _ledger_modified_ns(
    s: Any, session_id: str, *, workspace_root: Any = None
) -> int:
    """Ledger mtime used to prefilter a session without reading its events.

    ``-1`` means "unknown"; the caller must then inspect the session instead of
    trusting a missing timestamp.

    Only the modification time is needed here. Asking the journal bridge for
    its signature also computed ``latest_ledger_sequence`` for every session,
    which turned the 362-session prefilter into a cold-cache journal scan: it
    spent 20.9s of a 21s sweep before a single candidate was inspected.
    """

    from pathlib import Path

    from core.chat.turn_journal import turn_journal_path

    try:
        path = turn_journal_path(
            Path(s.PROJECT_ROOT), session_id, journal_workspace_root=workspace_root
        )
        return int(path.stat().st_mtime_ns)
    except OSError:
        return -1
    except Exception:  # noqa: BLE001 - unknown mtime means "must inspect"
        return -1


def _prefilter_session_ids(
    s: Any,
    session_ids: list[str],
    *,
    forced_session_ids: set[str],
    lower_bound_ns: int,
) -> tuple[list[str], int]:
    """Split sessions into "must inspect" and "cannot own a resumable turn".

    A session qualifies for inspection when the runtime or the restart marker
    already names it, or when its ledger changed inside ``lower_bound_ns``.
    Everything else only holds settled history: skipping its journal read is
    what removes hundreds of full event loads from startup.
    """

    candidates: list[str] = []
    skipped = 0
    workspace_root = _session_workspace_root(s)
    for session_id in session_ids:
        if session_id in forced_session_ids:
            candidates.append(session_id)
            continue
        modified_ns = _ledger_modified_ns(
            s, session_id, workspace_root=workspace_root
        )
        if modified_ns < 0 or modified_ns >= lower_bound_ns:
            candidates.append(session_id)
            continue
        skipped += 1
    return candidates, skipped


def _sweep_watermark_dirty_ids(s: Any) -> set[str]:
    """Sessions the previous pass saw move under it; always re-inspected."""

    from .recovery_sweep_state import load_watermark_dirty_session_ids

    try:
        return set(
            load_watermark_dirty_session_ids(getattr(s, "_WORK_RUN_STORE", None))
        )
    except Exception:  # noqa: BLE001 - a damaged watermark costs one extra pass
        return set()


def _sweep_dirty_session_ids(
    s: Any, candidates: list[str], *, started_wall_ns: int
) -> list[str]:
    """Candidates whose ledger moved while this pass was still running."""

    dirty: list[str] = []
    workspace_root = _session_workspace_root(s)
    for session_id in candidates:
        modified_ns = _ledger_modified_ns(
            s, session_id, workspace_root=workspace_root
        )
        if modified_ns >= started_wall_ns:
            dirty.append(session_id)
    return dirty


def _sweep_watermark_ns(s: Any) -> int:
    from .recovery_sweep_state import load_sweep_watermark_ns

    try:
        return load_sweep_watermark_ns(getattr(s, "_WORK_RUN_STORE", None))
    except Exception:  # noqa: BLE001 - a bad watermark only costs one full scan
        return 0


def _record_sweep_watermark(
    s: Any,
    *,
    started_wall_ns: int,
    summary: dict[str, Any],
    dirty_session_ids: list[str] | None = None,
) -> None:
    from .recovery_sweep_state import record_sweep_watermark

    try:
        record_sweep_watermark(
            getattr(s, "_WORK_RUN_STORE", None),
            started_at_ns=started_wall_ns,
            completed_at_ns=time.time_ns(),
            dirty_session_ids=dirty_session_ids or (),
            scanned_session_count=int(summary.get("scannedSessionCount") or 0),
            resumed_count=int(summary.get("resumedCount") or 0),
        )
    except Exception:  # noqa: BLE001 - bookkeeping never fails startup
        return


def _run_session_candidates(
    s: Any,
    session_ids: list[str],
    *,
    worker_count: int,
    companion_session_ids: set[str],
    should_stop: Callable[[], bool] | None,
    active_turn_session_ids: set[str] | None,
    pending_turn_ids: set[str],
    priority_session_ids: set[str] | None = None,
    pending_session_turn_ids: dict[str, set[str]] | None = None,
) -> list[dict[str, Any]]:
    """Run one candidate per session, serially or on a staggered pool.

    Each call gets a private summary so no counter is shared between threads;
    the caller merges them afterwards into the same shape a serial sweep
    produced. Sessions named by the restart marker or by an active turn are
    submitted first and without the stagger: they are the work a restart
    actually interrupted, so waiting behind idle history would turn a resume
    into a multi-minute silence. The remaining candidates keep the rolling
    stagger that protects journal projection rebuilds.
    """

    def run_one(session_id: str) -> dict[str, Any]:
        local = _new_summary()
        try:
            _recover_session_on_startup(
                s,
                session_id,
                companion_session_ids=companion_session_ids,
                summary=local,
                should_stop=should_stop,
                active_turn_session_ids=active_turn_session_ids,
                pending_turn_ids=pending_turn_ids,
                pending_session_turn_ids=pending_session_turn_ids,
            )
        except Exception as exc:  # noqa: BLE001 - one bad session never blocks startup
            local["errorCount"] += 1
            logger.warning(
                "Session startup recovery failed for %s: %s",
                session_id,
                type(exc).__name__,
            )
        return local

    if worker_count <= 1 or len(session_ids) <= 1:
        return [run_one(session_id) for session_id in session_ids]
    from concurrent.futures import ThreadPoolExecutor

    priority = set(priority_session_ids or ())
    ordered = [session_id for session_id in session_ids if session_id in priority]
    ordered.extend(
        session_id for session_id in session_ids if session_id not in priority
    )
    with ThreadPoolExecutor(
        max_workers=worker_count, thread_name_prefix="session-recovery"
    ) as pool:
        futures = []
        previous_was_regular = False
        for session_id in ordered:
            is_priority = session_id in priority
            if previous_was_regular and not _shutdown_requested(should_stop):
                # 恢复错峰：重启后 N 个候选若同时拉起，N 个会话立刻并行追加
                # turn_journal，每个进行中会话的 detail 投影全量重建在 GIL 上
                # 互踩（35MB journal 单次 1.5-4.5s，并发劣化 2-3 倍），SSE 心跳
                # 被饿死导致前端断连重连风暴。滚动提交让恢复约每
                # _RECOVERY_STAGGER_SECONDS 拉起一个会话，投影重建压力随之摊开；
                # 自动恢复语义不变，只是不再齐发。被重启中断的候选已在队首
                # 提交完毕，这里只摊开空闲历史。
                _stagger_sleep(_RECOVERY_STAGGER_SECONDS)
            previous_was_regular = not is_priority
            futures.append(pool.submit(run_one, session_id))
        return [future.result() for future in futures]


def _stagger_sleep(seconds: float) -> None:
    """Submit-gap between recovery candidates; module-level for testability."""

    time.sleep(seconds)


def _merge_recovery_summaries(target: dict[str, Any], parts: list[dict[str, Any]]) -> None:
    for part in parts:
        for field in _SWEEP_COUNTER_FIELDS:
            target[field] = int(target.get(field) or 0) + int(part.get(field) or 0)
        if part.get("stopped"):
            target["stopped"] = True


def recover_interrupted_session_turns_on_startup(
    *, should_stop: Callable[[], bool] | None = None
) -> dict[str, Any]:
    """Sweep only the sessions that may own a resumable turn.

    Never raises. The operator switch gates the whole sweep: disabled means
    exactly the pre-sweep status quo (interrupted turns stay interrupted,
    queues wait for the next natural trigger).

    Two filters keep startup bounded on a large install:

    - the resume-window / last-clean-sweep watermark bound which ledgers are
      even opened (a settled ledger cannot hold a turn this restart resumes);
    - the surviving candidates run on a bounded pool instead of one serial
      loop.

    Recovery semantics are unchanged: the same per-session decision function
    runs for every inspected session, and a failing session is still counted
    and logged rather than aborting the sweep.
    """

    global _SWEEP_IN_FLIGHT
    summary = _new_summary()
    candidates: list[str] = []
    s = _service()
    started_at = s._perf_counter()
    started_wall_ns = time.time_ns()
    with _SWEEP_LOCK:
        if _SWEEP_IN_FLIGHT:
            return {"trigger": "backend_startup", "skipped": "sweep_in_flight"}
        _SWEEP_IN_FLIGHT = True
    try:
        if not is_session_recovery_enabled():
            summary["enabled"] = False
            return summary
        _phase_start = time.perf_counter()
        companion_session_ids = _companion_session_ids(s)
        summary["phaseCompanionMs"] = int((time.perf_counter() - _phase_start) * 1000)
        if companion_session_ids is None:
            summary["skipped"] = "companion_scope_unavailable"
            return summary
        if _shutdown_requested(should_stop):
            summary["stopped"] = True
            return summary
        restart_pending_map = _load_restart_resume_pending(s)
        restart_pending_session_ids = set(restart_pending_map)
        restart_pending_turn_ids = {
            turn_id
            for turn_ids in restart_pending_map.values()
            for turn_id in turn_ids
        }
        _phase_start = time.perf_counter()
        active_turn_session_ids = _active_chat_turn_session_ids(s)
        summary["phaseActiveMs"] = int((time.perf_counter() - _phase_start) * 1000)
        if active_turn_session_ids is not None and restart_pending_session_ids:
            active_turn_session_ids = (
                set(active_turn_session_ids) | restart_pending_session_ids
            )
        summary["activeTurnCandidateCount"] = (
            len(active_turn_session_ids) if active_turn_session_ids is not None else -1
        )
        forced_session_ids = set(restart_pending_session_ids)
        if active_turn_session_ids:
            forced_session_ids |= set(active_turn_session_ids)
            forced_session_ids |= _sweep_watermark_dirty_ids(s)
        lower_bound_ns = _resume_window_start_ns(now_ns=started_wall_ns)
        watermark_ns = _sweep_watermark_ns(s)
        if watermark_ns > lower_bound_ns:
            lower_bound_ns = watermark_ns
            summary["watermarkApplied"] = True
        session_ids = [
            str(session_id or "").strip()
            for session_id in (s.list_session_runtime_ids(s.PROJECT_ROOT) or [])
        ]
        session_ids = [session_id for session_id in session_ids if session_id]
        summary["sessionIndexCount"] = len(session_ids)
        _phase_start = time.perf_counter()
        candidates, prefiltered = _prefilter_session_ids(
            s,
            session_ids,
            forced_session_ids=forced_session_ids,
            lower_bound_ns=lower_bound_ns,
        )
        summary["prefilterSkippedCount"] = prefiltered
        summary["phasePrefilterMs"] = int((time.perf_counter() - _phase_start) * 1000)
        summary["candidateCount"] = len(candidates)
        cpu_count = os.cpu_count() or 4
        # 恢复是后台补偿：池子再大也不能吃光调度槽位，否则用户新发的
        # 消息只能排在恢复出来的旧 turn 后面（见 limits.recovery_worker_limit）。
        worker_count = (
            1
            if len(candidates) <= 1
            else recovery_worker_limit(
                min(_SWEEP_MAX_WORKERS, max(2, cpu_count), len(candidates))
            )
        )
        summary["workerCount"] = worker_count
        _phase_start = time.perf_counter()
        resume_priority_session_ids = set(restart_pending_session_ids)
        if active_turn_session_ids:
            resume_priority_session_ids |= set(active_turn_session_ids)
        results = _run_session_candidates(
            s,
            candidates,
            worker_count=worker_count,
            companion_session_ids=companion_session_ids,
            should_stop=should_stop,
            active_turn_session_ids=active_turn_session_ids,
            pending_turn_ids=restart_pending_turn_ids,
            priority_session_ids=resume_priority_session_ids,
            pending_session_turn_ids=restart_pending_map,
        )
        summary["phaseCandidatesMs"] = int((time.perf_counter() - _phase_start) * 1000)
        _merge_recovery_summaries(summary, results)
    except Exception as exc:  # noqa: BLE001 - the sweep must never fail startup
        summary["errorCount"] = int(summary.get("errorCount") or 0) + 1
        logger.warning(
            "Session startup recovery sweep aborted: %s", type(exc).__name__
        )
    finally:
        summary["durationMs"] = s._elapsed_ms(started_at)
        try:
            if not _shutdown_requested(should_stop):
                _record_sweep_scene_event(s, summary)
                # Only a clean sweep may retire the marker or advance the
                # watermark: an interrupted or failing sweep must be retried by
                # the next startup.
                if not summary.get("errorCount") and not summary.get("stopped"):
                    _clear_restart_resume_pending(s)
                    _record_sweep_watermark(
                        s,
                        started_wall_ns=started_wall_ns,
                        dirty_session_ids=_sweep_dirty_session_ids(
                            s, candidates, started_wall_ns=started_wall_ns
                        ),
                        summary=summary,
                    )
        finally:
            with _SWEEP_LOCK:
                _SWEEP_IN_FLIGHT = False
    return summary


def _record_sweep_scene_event(s: Any, summary: dict[str, Any]) -> None:
    """Bounded startup evidence (ids/counts only, never prompt content)."""

    try:
        s.record_runtime_scene_event(
            "conversation",
            "startup_recovery",
            "conversation.startup_recovery.sweep",
            outcome="completed" if not summary.get("errorCount") else "degraded",
            message="Session startup recovery sweep completed.",
            fields={
                "enabled": bool(summary.get("enabled")),
                "scannedSessionCount": max(0, int(summary.get("scannedSessionCount") or 0)),
                "resumedCount": max(0, int(summary.get("resumedCount") or 0)),
                "retryLimitSkipCount": max(0, int(summary.get("retryLimitSkipCount") or 0)),
                "companionSkipCount": max(0, int(summary.get("companionSkipCount") or 0)),
                "noInterruptedTurnCount": max(
                    0, int(summary.get("noInterruptedTurnCount") or 0)
                ),
                "journalInterruptResumeCount": max(
                    0, int(summary.get("journalInterruptResumeCount") or 0)
                ),
                "continuableResumeCount": max(
                    0, int(summary.get("continuableResumeCount") or 0)
                ),
                "phaseCompanionMs": max(0, int(summary.get("phaseCompanionMs") or 0)),
                "phaseActiveMs": max(0, int(summary.get("phaseActiveMs") or 0)),
                "phasePrefilterMs": max(0, int(summary.get("phasePrefilterMs") or 0)),
                "phaseCandidatesMs": max(0, int(summary.get("phaseCandidatesMs") or 0)),
                "alreadyResumedSkipCount": max(
                    0, int(summary.get("alreadyResumedSkipCount") or 0)
                ),
                "unreadableSessionSkipCount": max(
                    0, int(summary.get("unreadableSessionSkipCount") or 0)
                ),
                "queuedDrainScheduledCount": max(
                    0, int(summary.get("queuedDrainScheduledCount") or 0)
                ),
                "noActiveTurnSkipCount": max(
                    0, int(summary.get("noActiveTurnSkipCount") or 0)
                ),
                "externalTaskSkipCount": max(
                    0, int(summary.get("externalTaskSkipCount") or 0)
                ),
                "activeTurnCandidateCount": (
                    -1
                    if summary.get("activeTurnCandidateCount") is None
                    else int(summary["activeTurnCandidateCount"])
                ),
                "sessionIndexCount": max(
                    0, int(summary.get("sessionIndexCount") or 0)
                ),
                "candidateCount": max(0, int(summary.get("candidateCount") or 0)),
                "prefilterSkippedCount": max(
                    0, int(summary.get("prefilterSkippedCount") or 0)
                ),
                "tailSkippedCount": max(
                    0, int(summary.get("tailSkippedCount") or 0)
                ),
                "workerCount": max(1, int(summary.get("workerCount") or 1)),
                "watermarkApplied": bool(summary.get("watermarkApplied")),
                "errorCount": max(0, int(summary.get("errorCount") or 0)),
                "durationMs": max(0, int(summary.get("durationMs") or 0)),
            },
            lifecycle=True,
        )
    except Exception:  # noqa: BLE001 - diagnostics are best effort
        return
