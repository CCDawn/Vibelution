"""System Team bootstrap control plane.

Claim scope: bounded background discovery/repair orchestration for system Teams.
Does not own ensure_* agent materialization bodies, canvas normalize, or list CRUD.
Late-binds ``team_service`` for locks/state globals, missing checks, and ensure entrypoints.
"""

from __future__ import annotations

import threading
from typing import Any


def _service():
    """Late-bound facade module (avoids import cycles at package import time)."""

    from core.web.services import team_service

    return team_service


def request_system_team_bootstrap(*, reason: str = "team_list", allow_sync_check: bool = True) -> dict[str, Any]:
    """Start a bounded background repair for missing system Teams.

    Team list reads must stay fast. This helper only performs lightweight
    missing checks inline, then lets the expensive Team/Agent/ChatRoom writes
    happen outside the request path. Callers on a latency-sensitive read path
    can request the last ready snapshot without refreshing those checks inline.
    """

    s = _service()
    normalized_reason = s._safe_token(reason or "team_list", default="team_list", max_length=80)
    now = s._perf_counter()
    with s._TEAM_SYSTEM_BOOTSTRAP_LOCK:
        if s._TEAM_SYSTEM_BOOTSTRAP_THREAD and s._TEAM_SYSTEM_BOOTSTRAP_THREAD.is_alive():
            return _system_team_bootstrap_state_snapshot_locked()
        ready_snapshot = (
            str(s._TEAM_SYSTEM_BOOTSTRAP_STATE.get("status") or "") == "ready"
            and not list(s._TEAM_SYSTEM_BOOTSTRAP_STATE.get("requiredSteps") or [])
        )
        checked_at = 0.0
        if ready_snapshot:
            try:
                checked_at = float(s._TEAM_SYSTEM_BOOTSTRAP_STATE.get("checkedAtMonotonic") or 0.0)
            except (TypeError, ValueError):
                checked_at = 0.0
            if checked_at > 0 and now - checked_at <= s.TEAM_SYSTEM_BOOTSTRAP_READY_CACHE_TTL_SECONDS:
                return _system_team_bootstrap_state_snapshot_locked()
        if not allow_sync_check:
            attempt = int(s._TEAM_SYSTEM_BOOTSTRAP_STATE.get("attempt") or 0) + 1
            request_id = f"system-team-bootstrap-{attempt}"
            if ready_snapshot:
                s._TEAM_SYSTEM_BOOTSTRAP_STATE["attempt"] = attempt
                snapshot = _system_team_bootstrap_state_snapshot_locked()
            else:
                s._TEAM_SYSTEM_BOOTSTRAP_STATE.update(
                    {
                        "status": "running",
                        "requiredSteps": [],
                        "reason": normalized_reason,
                        "startedAt": s.utc_now_iso(),
                        "finishedAt": "",
                        "lastError": "",
                        "elapsedMs": 0,
                        "attempt": attempt,
                        "requestId": request_id,
                    }
                )
                snapshot = _system_team_bootstrap_state_snapshot_locked()
            s._TEAM_SYSTEM_BOOTSTRAP_THREAD = threading.Thread(
                target=_run_system_team_bootstrap_discovery,
                args=(request_id, normalized_reason),
                name="vibelution-team-system-bootstrap",
                daemon=True,
            )
            thread = s._TEAM_SYSTEM_BOOTSTRAP_THREAD
            thread.start()
            return snapshot
    team_lock_acquired = s._try_acquire_team_lock()
    if not team_lock_acquired:
        with s._TEAM_SYSTEM_BOOTSTRAP_LOCK:
            s._TEAM_SYSTEM_BOOTSTRAP_STATE.update(
                {
                    "status": "deferred",
                    "requiredSteps": [],
                    "reason": normalized_reason,
                    "finishedAt": "",
                    "lastError": "team_lock_busy",
                    "elapsedMs": 0,
                }
            )
            snapshot = _system_team_bootstrap_state_snapshot_locked()
        _record_system_team_bootstrap_event(
            "team.system_bootstrap.deferred_lock_busy",
            outcome="deferred",
            fields={"reason": normalized_reason},
        )
        return snapshot
    try:
        required_steps = _system_team_bootstrap_required_steps()
    except Exception as exc:
        with s._TEAM_SYSTEM_BOOTSTRAP_LOCK:
            s._TEAM_SYSTEM_BOOTSTRAP_STATE.update(
                {
                    "status": "failed",
                    "requiredSteps": [],
                    "reason": normalized_reason,
                    "finishedAt": s.utc_now_iso(),
                    "lastError": f"{type(exc).__name__}: {exc}",
                    "elapsedMs": 0,
                }
            )
            snapshot = _system_team_bootstrap_state_snapshot_locked()
        _record_system_team_bootstrap_event(
            "team.system_bootstrap.check_failed",
            outcome="failed",
            fields={"reason": normalized_reason, "errorType": type(exc).__name__},
        )
        return snapshot
    finally:
        s._release_team_lock_if_acquired(team_lock_acquired)
    if not required_steps:
        with s._TEAM_SYSTEM_BOOTSTRAP_LOCK:
            s._TEAM_SYSTEM_BOOTSTRAP_STATE.update(
                {
                    "status": "ready",
                    "requiredSteps": [],
                    "reason": normalized_reason,
                    "finishedAt": s.utc_now_iso(),
                    "lastError": "",
                    "elapsedMs": 0,
                    "checkedAtMonotonic": now,
                }
            )
            return _system_team_bootstrap_state_snapshot_locked()

    with s._TEAM_SYSTEM_BOOTSTRAP_LOCK:
        if s._TEAM_SYSTEM_BOOTSTRAP_THREAD and s._TEAM_SYSTEM_BOOTSTRAP_THREAD.is_alive():
            return _system_team_bootstrap_state_snapshot_locked()
        attempt = int(s._TEAM_SYSTEM_BOOTSTRAP_STATE.get("attempt") or 0) + 1
        request_id = f"system-team-bootstrap-{attempt}"
        started_at = s.utc_now_iso()
        s._TEAM_SYSTEM_BOOTSTRAP_STATE.update(
            {
                "status": "running",
                "requiredSteps": list(required_steps),
                "reason": normalized_reason,
                "startedAt": started_at,
                "finishedAt": "",
                "lastError": "",
                "elapsedMs": 0,
                "attempt": attempt,
                "requestId": request_id,
            }
        )
        s._TEAM_SYSTEM_BOOTSTRAP_THREAD = threading.Thread(
            target=_run_system_team_bootstrap,
            args=(request_id, list(required_steps), normalized_reason),
            name="vibelution-team-system-bootstrap",
            daemon=True,
        )
        thread = s._TEAM_SYSTEM_BOOTSTRAP_THREAD
        snapshot = _system_team_bootstrap_state_snapshot_locked()
    thread.start()
    return snapshot


def _run_system_team_bootstrap_discovery(request_id: str, reason: str) -> None:
    s = _service()
    try:
        required_steps = _system_team_bootstrap_required_steps()
    except Exception as exc:
        with s._TEAM_SYSTEM_BOOTSTRAP_LOCK:
            s._TEAM_SYSTEM_BOOTSTRAP_STATE.update(
                {
                    "status": "failed",
                    "requiredSteps": [],
                    "reason": reason,
                    "finishedAt": s.utc_now_iso(),
                    "lastError": f"{type(exc).__name__}: {exc}",
                    "elapsedMs": 0,
                    "requestId": request_id,
                }
            )
        _record_system_team_bootstrap_event(
            "team.system_bootstrap.check_failed",
            outcome="failed",
            fields={"reason": reason, "requestId": request_id, "errorType": type(exc).__name__},
        )
        return
    if not required_steps:
        with s._TEAM_SYSTEM_BOOTSTRAP_LOCK:
            s._TEAM_SYSTEM_BOOTSTRAP_STATE.update(
                {
                    "status": "ready",
                    "requiredSteps": [],
                    "reason": reason,
                    "finishedAt": s.utc_now_iso(),
                    "lastError": "",
                    "elapsedMs": 0,
                    "requestId": request_id,
                    "checkedAtMonotonic": s._perf_counter(),
                }
            )
        return
    _run_system_team_bootstrap(request_id, list(required_steps), reason)


def _system_team_bootstrap_required_steps() -> list[str]:
    s = _service()
    required_steps: list[str] = []
    if s.evolution_system_teams_missing():
        required_steps.append("evolution_system_teams")
    if s.ai_search_system_team_missing():
        required_steps.append("ai_search_system_team")
    if s.challenge_cup_research_team_missing():
        required_steps.append("challenge_cup_research_team")
    if s.knowledge_expansion_team_agents_need_repair():
        required_steps.append("knowledge_expansion_team_agents")
    return required_steps


def _system_team_bootstrap_state_snapshot_locked() -> dict[str, Any]:
    s = _service()
    state = s._TEAM_SYSTEM_BOOTSTRAP_STATE
    return {
        "schemaVersion": int(s.SCHEMA_VERSION),
        "status": str(state.get("status") or "idle"),
        "requiredSteps": list(state.get("requiredSteps") or []),
        "reason": str(state.get("reason") or ""),
        "startedAt": str(state.get("startedAt") or ""),
        "finishedAt": str(state.get("finishedAt") or ""),
        "lastError": str(state.get("lastError") or ""),
        "elapsedMs": int(state.get("elapsedMs") or 0),
        "attempt": int(state.get("attempt") or 0),
        "requestId": str(state.get("requestId") or ""),
    }


def _run_system_team_bootstrap(request_id: str, required_steps: list[str], reason: str) -> None:
    s = _service()
    started_at = s._perf_counter()
    _record_system_team_bootstrap_event(
        "team.system_bootstrap.started",
        outcome="started",
        fields={"requestId": request_id, "requiredSteps": list(required_steps), "reason": reason},
    )
    try:
        if "challenge_cup_research_team" in required_steps:
            s.bootstrap_challenge_cup_research_team()
        if "ai_search_system_team" in required_steps:
            s.ensure_ai_search_system_team()
        if "knowledge_expansion_team_agents" in required_steps:
            s.ensure_knowledge_expansion_team_agents(purge_stale=True)
        if "evolution_system_teams" in required_steps:
            s.ensure_evolution_system_teams()
        remaining_steps = _system_team_bootstrap_required_steps()
        elapsed_ms = s._elapsed_ms(started_at)
        status = "ready" if not remaining_steps else "needs_retry"
        outcome = "succeeded" if not remaining_steps else "blocked"
        with s._TEAM_SYSTEM_BOOTSTRAP_LOCK:
            s._TEAM_SYSTEM_BOOTSTRAP_STATE.update(
                {
                    "status": status,
                    "requiredSteps": list(remaining_steps),
                    "reason": reason,
                    "finishedAt": s.utc_now_iso(),
                    "lastError": "",
                    "elapsedMs": elapsed_ms,
                    "requestId": request_id,
                    "checkedAtMonotonic": s._perf_counter() if status == "ready" else 0.0,
                }
            )
        _record_system_team_bootstrap_event(
            "team.system_bootstrap.finished",
            outcome=outcome,
            fields={
                "requestId": request_id,
                "requiredSteps": list(required_steps),
                "remainingSteps": list(remaining_steps),
                "reason": reason,
                "elapsedMs": elapsed_ms,
            },
        )
    except Exception as exc:
        elapsed_ms = s._elapsed_ms(started_at)
        with s._TEAM_SYSTEM_BOOTSTRAP_LOCK:
            s._TEAM_SYSTEM_BOOTSTRAP_STATE.update(
                {
                    "status": "failed",
                    "requiredSteps": list(required_steps),
                    "reason": reason,
                    "finishedAt": s.utc_now_iso(),
                    "lastError": f"{type(exc).__name__}: {exc}",
                    "elapsedMs": elapsed_ms,
                    "requestId": request_id,
                }
            )
        _record_system_team_bootstrap_event(
            "team.system_bootstrap.failed",
            outcome="failed",
            fields={
                "requestId": request_id,
                "requiredSteps": list(required_steps),
                "reason": reason,
                "elapsedMs": elapsed_ms,
                "errorType": type(exc).__name__,
            },
        )


def _record_system_team_bootstrap_event(
    event_code: str,
    *,
    outcome: str,
    fields: dict[str, Any] | None = None,
) -> None:
    from core.logging import debug as _debug_logger
    from core.web.services.runtime_scene_service import record_runtime_scene_event

    try:
        record_runtime_scene_event(
            "team_service",
            "system_bootstrap",
            event_code,
            message=event_code,
            outcome=outcome,
            fields=fields or {},
        )
    except Exception as exc:
        _debug_logger.warning(f"Failed to emit system Team bootstrap event. error={exc}")
