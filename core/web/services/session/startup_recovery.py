"""Startup recovery sweep for interrupted session turns and queued turns.

Claim scope: after a backend restart, ordinary sessions can be left with an
open (never-settled) turn and/or undrained queued user turns, because the
in-memory running registry is empty and nobody re-triggers the queue drain.
This sweep runs once after the workbench lifespan is ready and:

- resumes an interrupted turn by resubmitting its original user prompt with
  ``turn_mode="hot_restart_resume"`` (the daemon hot-restart wake precedent:
  the kind keeps the message out of the real user-message channel), guarded by
  the operator ``session_recovery`` switch and a per-turn retry budget;
- appends one ``session_recovery_resumed`` status line to the conversation
  when a resume is accepted (the journal projection derives ``turnItems`` from
  the content, so the row survives the timeline visibility filter);
- schedules the queued-turn drain for sessions with pending queue rows.

Companion (virtual-human) sessions are skipped entirely — Companion chains
keep their own delivery path and must never be touched by this sweep. The
runtime's own 120s stale-turn reconciliation path is left exactly as it was;
this sweep only covers turns whose chat_turn work-run snapshot is still
active (status queued/running/stopping/paused with no finishedAt) at startup,
which no live process can own right after a restart.

The sweep is best-effort: any failure is counted and logged, never raised, so
backend startup never blocks on recovery.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from core.chat.turn_journal import (
    EVENT_SESSION_RECOVERY_RESUMED,
    EVENT_USER_MESSAGE,
    latest_open_turn_id,
)
from core.session_recovery_flags import (
    is_session_recovery_enabled,
    session_recovery_max_auto_retries,
)

logger = logging.getLogger(__name__)

# Persisted per-conversation retry ledger (conversation state field). Keyed by
# the resume chain: ``originTurnId`` is the first interrupted turn of the
# chain, ``resumedTurnId`` the turn produced by the last accepted resume, so a
# re-interruption of a resumed turn keeps counting against the same budget.
RECOVERY_STATE_KEY = "session_recovery"

# Work-run snapshot statuses that mean "a live process owned this turn" —
# impossible right after a restart, so the snapshot marks the turn interrupted.
_RECOVERY_BUSY_WORK_RUN_STATUSES = {"queued", "running", "stopping", "paused"}

_TURN_LABEL_MAX_CHARS = 60

# Re-entrancy guards: the sweep itself must be single-flight per process, and
# each (session, interrupted turn) pair is claimed before resubmitting so a
# multi-source startup window cannot double-fire the same resume.
_SWEEP_LOCK = threading.Lock()
_SWEEP_IN_FLIGHT = False
_RESUMED_TURN_KEYS_LOCK = threading.Lock()
_RESUMED_TURN_KEYS: set[str] = set()


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
        "queuedDrainScheduledCount": 0,
        "errorCount": 0,
        "durationMs": 0,
    }


def _companion_session_ids(s: Any) -> set[str] | None:
    """Direct Session ids bound to Companion-flagged agents (frontend parity).

    Returns ``None`` when the Agent Directory cannot be read: in that case the
    sweep cannot prove which sessions are Companion-scoped and stays silent
    (red line: never touch a Companion session by guesswork).
    """

    try:
        agents = s.agent_directory_service.list_agents(include_archived=True)
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


def _open_turn_work_run_is_interrupted(s: Any, turn_id: str) -> bool:
    """Whether the open turn's chat_turn work-run snapshot is still active.

    A finished or missing snapshot means the runtime's own reconcile path owns
    the turn; only a still-active snapshot right after a restart proves the
    process died mid-turn, which this sweep may recover without the runtime's
    120s grace window.
    """

    snapshot = s._WORK_RUN_STORE.load_active_snapshot_for_run("chat_turn", turn_id)
    if not isinstance(snapshot, dict):
        return False
    status = str(snapshot.get("status") or "").strip().lower()
    if status not in _RECOVERY_BUSY_WORK_RUN_STATUSES:
        return False
    return not str(snapshot.get("finishedAt") or "").strip()


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
) -> None:
    if _shutdown_requested(should_stop):
        return
    conversation = s.load_session_chat_state(s.PROJECT_ROOT, session_id)
    if conversation is None or s._conversation_is_read_only(conversation):
        summary["noInterruptedTurnCount"] += 1
        return
    if not _open_turn_work_run_is_interrupted(s, open_turn_id):
        summary["noInterruptedTurnCount"] += 1
        return
    prompt = _interrupted_turn_prompt(events, open_turn_id)
    attachment_ids = _interrupted_turn_attachment_ids(events, open_turn_id)
    if not prompt and not attachment_ids:
        # Nothing faithful to resubmit (no prompt and no attachments); the
        # interrupted presentation stays and the user can resend manually.
        summary["noInterruptedTurnCount"] += 1
        return

    max_retries = max(0, int(session_recovery_max_auto_retries()))
    previous_state = (
        conversation.get(RECOVERY_STATE_KEY)
        if isinstance(conversation.get(RECOVERY_STATE_KEY), dict)
        else {}
    )
    attempts = _load_recovery_attempts(previous_state, open_turn_id)
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
            write_intent=False,
            client_submission_id=f"resume:{open_turn_id}",
            attachment_ids=attachment_ids or None,
            message_metadata={
                "kind": "hot_restart_resume",
                "recoverySource": "startup_sweep",
                "recoveredTurnId": open_turn_id,
            },
            message_source="hot_restart_resume",
            include_started_turn_id=True,
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


def _recover_session_on_startup(
    s: Any,
    session_id: str,
    *,
    companion_session_ids: set[str],
    summary: dict[str, Any],
    should_stop: Callable[[], bool] | None = None,
) -> None:
    if _shutdown_requested(should_stop):
        return
    if session_id in companion_session_ids:
        summary["companionSkipCount"] += 1
        return
    summary["scannedSessionCount"] += 1
    conversation = s.load_session_chat_state(s.PROJECT_ROOT, session_id)
    if conversation is None or _shutdown_requested(should_stop):
        return
    queued_rows = s._session_queued_turn_rows(conversation)
    if any(str(row.get("status") or "") in {"queued", "starting"} for row in queued_rows):
        if _shutdown_requested(should_stop):
            return
        # The idle gate and stale-"starting" reset are built into the drain;
        # after a restart nothing else re-triggers it.
        s._schedule_session_queued_turn_drain(session_id)
        summary["queuedDrainScheduledCount"] += 1
    if s._is_session_running(session_id):
        return
    if _shutdown_requested(should_stop):
        return
    events = s._load_session_conversation_events_cached(session_id)
    open_turn_id = latest_open_turn_id(events)
    if not open_turn_id:
        return
    _resume_interrupted_turn(
        s,
        session_id,
        open_turn_id=open_turn_id,
        events=events,
        summary=summary,
        should_stop=should_stop,
    )


def recover_interrupted_session_turns_on_startup(
    *, should_stop: Callable[[], bool] | None = None
) -> dict[str, Any]:
    """Sweep every session once after startup: resume + queue drain.

    Never raises. The operator switch gates the whole sweep: disabled means
    exactly the pre-sweep status quo (interrupted turns stay interrupted,
    queues wait for the next natural trigger).
    """

    global _SWEEP_IN_FLIGHT

    summary = _new_summary()
    s = _service()
    started_at = s._perf_counter()
    with _SWEEP_LOCK:
        if _SWEEP_IN_FLIGHT:
            return {"trigger": "backend_startup", "skipped": "sweep_in_flight"}
        _SWEEP_IN_FLIGHT = True
    try:
        if not is_session_recovery_enabled():
            summary["enabled"] = False
            return summary
        companion_session_ids = _companion_session_ids(s)
        if companion_session_ids is None:
            summary["skipped"] = "companion_scope_unavailable"
            return summary
        if _shutdown_requested(should_stop):
            summary["stopped"] = True
            return summary
        for session_id in list(s.list_session_runtime_ids(s.PROJECT_ROOT) or []):
            if _shutdown_requested(should_stop):
                summary["stopped"] = True
                break
            normalized = str(session_id or "").strip()
            if not normalized:
                continue
            try:
                _recover_session_on_startup(
                    s,
                    normalized,
                    companion_session_ids=companion_session_ids,
                    summary=summary,
                    should_stop=should_stop,
                )
            except Exception as exc:  # noqa: BLE001 - one bad session never blocks startup
                summary["errorCount"] += 1
                logger.warning(
                    "Session startup recovery failed for %s: %s",
                    normalized,
                    type(exc).__name__,
                )
    finally:
        summary["durationMs"] = s._elapsed_ms(started_at)
        if not _shutdown_requested(should_stop):
            _record_sweep_scene_event(s, summary)
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
                "queuedDrainScheduledCount": max(
                    0, int(summary.get("queuedDrainScheduledCount") or 0)
                ),
                "errorCount": max(0, int(summary.get("errorCount") or 0)),
                "durationMs": max(0, int(summary.get("durationMs") or 0)),
            },
            lifecycle=True,
        )
    except Exception:  # noqa: BLE001 - diagnostics are best effort
        return
