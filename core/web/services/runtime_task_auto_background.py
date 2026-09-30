"""Auto-background sweeper for long-running runtime tasks.

Foreground subtasks in this project are notification-driven (the CLI task
broker returns ``task_sent`` immediately and the child-session creator never
blocks), so the ZCode-style "foreground race, then detach" shape does not
exist here. The equivalent failure mode is a parent turn that sits idle or
keeps polling while a task runs far past a reasonable wait. This module makes
the wait explicit instead:

- A daemon sweeper (started lazily by ``RuntimeTaskStore.register_task``) walks
  only index-listed active tasks.
- A task whose elapsed time passes the configured threshold is stamped once
  (``RuntimeTaskStore.request_background``) and keeps running unchanged; its
  stopInitiator, terminal status and completion notification chain stay with
  the registry.
- ``cli_agent`` and ``child_session`` tasks immediately deliver a
  ``task_notification`` notice to their source session through the existing
  queued-turn channel, stamped with the task's ``branchGeneration`` so a
  forked/rewound session drops it exactly like completion notices.
- ``research_task`` rows are stamp-only: their orchestrator owns the polling
  loop and has no parent turn waiting on them.

Threshold: ``VIBELUTION_RUNTIME_TASK_AUTO_BACKGROUND_SECONDS`` (float).
Unset, non-numeric, or non-positive disables the sweeper entirely (default
off); values are clamped to a 5-second floor so a typo cannot turn the sweep
into a busy loop.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

from . import runtime_task_registry as task_registry

AUTO_BACKGROUND_ENV_VAR = "VIBELUTION_RUNTIME_TASK_AUTO_BACKGROUND_SECONDS"
MIN_THRESHOLD_SECONDS = 5.0
SWEEP_INTERVAL_SECONDS = 1.0
_RECONCILE_EVERY_TICKS = 60
# Kinds whose source session actually waits on the task and therefore gets
# the "still running in the background" notice. Research tasks are polled by
# their own orchestrator store instead.
NOTICE_KINDS = frozenset({task_registry.KIND_CLI_AGENT, task_registry.KIND_CHILD_SESSION})

_SWEPPER_LOCK = threading.Lock()
_SWEEPER_THREAD: threading.Thread | None = None


def resolve_threshold_seconds(env: Any = None) -> float | None:
    """Parse the auto-background threshold; None means the feature is off."""

    source = os.environ if env is None else env
    raw = str(source.get(AUTO_BACKGROUND_ENV_VAR) or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return max(MIN_THRESHOLD_SECONDS, value)


def ensure_auto_background_sweeper() -> bool:
    """Start the daemon sweep loop when a threshold is configured (idempotent).

    Returns True when the sweeper is running afterwards. Called lazily from
    ``RuntimeTaskStore.register_task`` so every task kind is covered without
    each registration site having to remember.
    """

    if resolve_threshold_seconds() is None:
        return False
    global _SWEEPER_THREAD
    with _SWEPPER_LOCK:
        if _SWEEPER_THREAD is not None and _SWEEPER_THREAD.is_alive():
            return True
        thread = threading.Thread(
            target=_sweep_loop, name="runtime-task-auto-background", daemon=True
        )
        _SWEEPER_THREAD = thread
        thread.start()
        return True


def sweep_runtime_tasks_once(
    store: task_registry.RuntimeTaskStore | None = None,
    *,
    deliver_notice: Any = None,
    record_event: Any = None,
    now: Any = None,
) -> list[dict[str, Any]]:
    """Run one synchronous sweep pass; returns one row per handled task.

    Test seam: ``deliver_notice`` replaces the queued-turn enqueue, ``record_event``
    replaces the runtime scene record, and ``now`` freezes the clock. Tasks
    younger than the threshold are untouched; the stamp makes the whole pass
    idempotent.
    """

    threshold = resolve_threshold_seconds()
    if threshold is None:
        return []
    active_store = store or task_registry.default_store()
    deliver = deliver_notice if deliver_notice is not None else _deliver_background_notice
    record = record_event if record_event is not None else _record_sweep_event
    current_time = _utcnow() if now is None else now
    handled: list[dict[str, Any]] = []
    for state in active_store.active_task_states():
        task_id = str(state.get("taskId") or "").strip()
        if not task_id:
            continue
        started = _parse_iso_epoch(str(state.get("startedAt") or state.get("createdAt") or ""))
        if started is None or current_time - started < threshold:
            continue
        outcome = active_store.request_background(task_id)
        row = {"taskId": task_id, "kind": str(state.get("kind") or ""), "outcome": outcome}
        if outcome == task_registry.BACKGROUND_OUTCOME_BACKGROUNDED:
            row["noticeStatus"] = _deliver_backgrounded_notice(
                active_store, active_store.load_state(task_id) or state, deliver=deliver
            )
            record(
                "runtime_task.backgrounded",
                outcome="backgrounded",
                fields={
                    "taskId": task_id,
                    "kind": row["kind"],
                    "thresholdSeconds": threshold,
                    "noticeStatus": row["noticeStatus"],
                    "branchGeneration": state.get("branchGeneration"),
                },
            )
        elif str(outcome).startswith("refused:"):
            row["refusalReason"] = str(outcome).split(":", 1)[1]
            record(
                "runtime_task.background_refused",
                outcome="refused",
                fields={"taskId": task_id, "kind": row["kind"], "reason": row["refusalReason"]},
            )
        handled.append(row)
    return handled


def _sweep_loop() -> None:
    tick = 0
    while True:
        try:
            threshold = resolve_threshold_seconds()
            if threshold is None:
                return
            active_store = task_registry.default_store()
            if tick % _RECONCILE_EVERY_TICKS == 0:
                active_store.reconcile_index()
            sweep_runtime_tasks_once(active_store)
        except Exception:  # noqa: BLE001 - the sweeper must never die loudly
            pass
        tick += 1
        time.sleep(SWEEP_INTERVAL_SECONDS)


def _deliver_backgrounded_notice(
    store: task_registry.RuntimeTaskStore,
    state: dict[str, Any],
    *,
    deliver: Any,
) -> str:
    """Queue the "already backgrounded" notice; returns a status string."""

    kind = str(state.get("kind") or "").strip().lower()
    task_id = str(state.get("taskId") or "").strip()
    if kind not in NOTICE_KINDS:
        return "skipped:orchestrator_owned"
    target = str(state.get("sourceSessionId") or state.get("parentSessionId") or "").strip()
    if not target:
        return "skipped:no_target_session"
    threshold = resolve_threshold_seconds()
    label = str(state.get("label") or "").strip() or task_id
    kind_label = "子会话" if kind == task_registry.KIND_CHILD_SESSION else "后台任务"
    lines = [
        f"{kind_label}已转后台：{label}",
        (
            f"任务已运行超过 {threshold:g} 秒仍未完成，已在后台继续执行；"
            "完成或失败后会另行通知，本轮无需继续等待，也不要重复启动同一个任务。"
        ),
        f"taskId: {task_id}",
    ]
    stamped = state.get("branchGeneration")
    branch_generation = None if stamped in (None, "") else max(0, int(stamped))
    try:
        queued = deliver(
            target,
            kind="task_notification",
            content="\n".join(lines),
            source_id=f"runtime-task-backgrounded:{task_id}",
            branch_generation=branch_generation,
            task_id=task_id,
            tool_name="runtime_task_auto_background",
        )
    except Exception as exc:  # noqa: BLE001 - notice failure never breaks the stamp
        _write_notice_audit(store, task_id, f"failed:{type(exc).__name__}")
        return f"failed:{type(exc).__name__}"
    dropped = str((queued or {}).get("dropped") or "")
    if dropped:
        status = f"dropped:{dropped}"
    else:
        status = "queued"
    _write_notice_audit(store, task_id, status, target=target)
    return status


def _write_notice_audit(
    store: task_registry.RuntimeTaskStore,
    task_id: str,
    status: str,
    *,
    target: str = "",
) -> None:
    def _mutate(state: dict[str, Any]) -> dict[str, Any] | None:
        if str(state.get("backgroundedNoticeStatus") or "") == status and (
            not target or str(state.get("backgroundedNoticeTarget") or "") == target
        ):
            return None
        state["backgroundedNoticeStatus"] = status
        if target:
            state["backgroundedNoticeTarget"] = target
        state["updatedAt"] = _utcnow_iso()
        return state

    try:
        store.update_task(task_id, _mutate)
    except Exception:  # noqa: BLE001 - audit is best effort
        return


def _deliver_background_notice(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Late-bound queued-turn enqueue keeps monkeypatches stable."""

    from .session_service import enqueue_session_runtime_notice

    return enqueue_session_runtime_notice(*args, **kwargs)


def _record_sweep_event(event_code: str, *, outcome: str, fields: dict[str, Any]) -> None:
    try:
        from .runtime_scene_service import record_runtime_scene_event_quietly

        record_runtime_scene_event_quietly(
            "runtime_tasks",
            "auto_background",
            event_code,
            message=event_code,
            outcome=outcome,
            fields=fields,
            lifecycle=True,
        )
    except Exception:  # noqa: BLE001 - diagnostics are best effort
        return


def _parse_iso_epoch(value: str) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _utcnow() -> float:
    return datetime.now(timezone.utc).timestamp()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
