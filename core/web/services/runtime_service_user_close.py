"""Give every existing task owner a save opportunity during explicit close.

The Electron owner may terminate this backend after its short close deadline.
Daemon workers share that deadline; a wedged owner must not prevent unrelated
owners from reaching their existing stop and persistence paths.
"""
from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable

from core.runtime_manager import work_run_store
from core.infrastructure import developer_sandbox

from . import runtime_service as runtime


USER_CLOSE_SAVE_WAIT_SECONDS = 1.2
_REASON = "Interrupted by an operator close."


def _parallel(jobs: dict[str, Callable[[], list[dict]]], deadline: float) -> dict[str, list[dict]]:
    """Start all owners before waiting, without executor shutdown joins."""
    pending = {}
    for kind, callback in jobs.items():
        done = threading.Event()
        result: list[list[dict]] = []

        def run(target=callback, signal=done, output=result, owner=kind):
            try:
                output.append(target())
            except Exception as exc:
                output.append([{"kind": owner, "status": "failed", "error": type(exc).__name__}])
            finally:
                signal.set()

        threading.Thread(target=run, name=f"runtime-user-close-{kind}", daemon=True).start()
        pending[kind] = (done, result)
    results = {}
    for kind, (done, result) in pending.items():
        if done.wait(max(0.0, deadline - time.monotonic())):
            results[kind] = result[0]
        else:
            results[kind] = [{"kind": kind, "status": "timeout", "error": "user_close_save_wait_timeout"}]
    return results


def _active(kind: str) -> list[dict]:
    # Indexed active snapshots only: no latest/history reads or reconciliation.
    # Match each owner's store identity, including its developer-mode behavior.
    store = (work_run_store.WorkRunStore() if kind == "formal_review"
             else work_run_store.WorkRunStore(root=work_run_store.WORK_RUNS_DIR))
    return [item for item in store.load_active_snapshots(kind)
            if runtime._active_work_payload_blocks_lifecycle(item)]


def _autonomous_store() -> work_run_store.WorkRunStore:
    root = developer_sandbox.formal_workspace_path(runtime.PROJECT_ROOT, "self_evolution", "autonomous_loops")
    return work_run_store.WorkRunStore(root=root / "work_runs")


def _active_autonomous() -> list[dict]:
    store = _autonomous_store()
    return [item for kind in ("self_evolution_autonomous_loop", "self_evolution_campaign")
            for item in store.load_active_snapshots(kind)
            if not (kind == "self_evolution_autonomous_loop" and item.get("status") == "awaiting_user_approval")
            if runtime._active_work_payload_blocks_lifecycle(item)]


def _stop_autonomous() -> list[dict]:
    name = "core.web.services.self_evolution_autonomous_loop_orchestrator"
    module = sys.modules.get(name)
    owner = getattr(module, "_DEFAULT_ORCHESTRATOR", None)
    # An unloaded module is not proof of no persisted work. Only build the
    # production owner when active persisted work actually needs its cleanup.
    if owner is None:
        if not _active_autonomous():
            return []
        from .self_evolution_autonomous_loop_orchestrator import default_orchestrator

        owner = default_orchestrator()
    return [{"kind": "self_evolution_autonomous_loop", **item}
            for item in owner.interrupt_active_for_restart(_REASON)]


def _stop_formal_review() -> list[dict]:
    from core.runtime_manager.formal_review_work import interrupt_active_for_restart

    return [{"kind": "formal_review", **item} for item in interrupt_active_for_restart(_REASON)]


def _stop_sources(deadline: float) -> list[dict]:
    items = _active("source_collection_run")
    jobs = {str(item["runId"]): lambda row=item: runtime._stop_active_source_collection_runs_before_shutdown(
        deadline=deadline, active_items=[row],
    ) for item in items}
    return [row for rows in _parallel(jobs, deadline).values() for row in rows]


def _stop_rooms(deadline: float) -> list[dict]:
    from .chat_room_service import load_chat_room_work_run_summary

    # Background rounds can be durable in the room store before their
    # WorkRun index is written. Discover them through the existing owner.
    summary = load_chat_room_work_run_summary()
    candidates = [*summary.get("activeItems", []), summary.get("active")]
    items = {}
    for row in candidates:
        if not isinstance(row, dict) or not runtime._active_work_payload_blocks_lifecycle(row):
            continue
        run_id = str(row.get("runId") or row.get("roundId") or "").strip()
        room_id = str(row.get("roomId") or "").strip()
        if run_id and room_id:
            items[run_id] = {**row, "runId": run_id, "roomId": room_id}
    # Dispatch the existing light stop flags before attempting the room lock.
    return runtime._stop_active_chat_room_rounds_before_shutdown(deadline=deadline, active_items=list(items.values()))


def _stop_chat_turns(deadline: float) -> list[dict]:
    items = runtime.list_active_session_work_runs(reconcile=False)
    jobs = {}
    for item in items:
        session_id = str(item.get("sessionId") or "")
        if not session_id or session_id in jobs:
            continue

        def stop(row=item, target=session_id):
            # This owner signals the turn and descendants with fast_ack before
            # sealing through the unchanged Session Journal interruption path.
            runtime._stop_and_persist_chat_turn_for_restart(target, stop_reason="electron_user_close")
            return [{"kind": "chat_turn", "sessionId": target,
                     "runId": str(row.get("runId") or ""), "status": "stopped"}]

        jobs[session_id] = stop
    return [row for rows in _parallel(jobs, deadline).values() for row in rows]


def _stopped_evolution(kind: str, stopper: Callable) -> list[dict]:
    return [{"kind": kind, **item} for item in stopper(_REASON)]


def _remaining_work(deadline: float) -> list[dict]:
    # Only the canonical guard can certify no remaining work. An active index
    # alone can miss restored snapshots or room rounds awaiting WorkRun writes.
    return _parallel({"active_work_readback": runtime._restart_guard_active_work_runs}, deadline)["active_work_readback"]


def retire_for_user_close(lang: str) -> dict[str, object]:
    deadline = time.monotonic() + USER_CLOSE_SAVE_WAIT_SECONDS
    # Producer owners are dispatched first; each applies its existing stop
    # controls before persistence. Chat saving never waits for their completion.
    jobs = {
        "autonomous": _stop_autonomous,
        "formal_review": _stop_formal_review,
        "self_evolution_run": lambda: _stopped_evolution("self_evolution_run", runtime._force_cancel_self_evolution_for_shutdown),
        "supervised_evolution_run": lambda: _stopped_evolution("supervised_evolution_run", runtime._force_cancel_supervised_evolution_for_shutdown),
        "supervised_worktree_evolution_run": lambda: _stopped_evolution("supervised_worktree_evolution_run", runtime._force_cancel_supervised_worktree_evolution_for_shutdown),
        "sources": lambda: _stop_sources(deadline),
        "rooms": lambda: _stop_rooms(deadline),
        "turns": lambda: _stop_chat_turns(deadline),
    }
    harvested = _parallel(jobs, deadline)
    results = [item for rows in harvested.values() for item in rows]
    failures = [item for item in results if item.get("error") or item.get("status") in {"failed", "timeout", "skipped"}]
    if not failures:
        failures.extend({**item, "error": "user_close_pause_not_settled"} for item in _remaining_work(deadline))
    runtime._record_shutdown_event(
        "runtime.shutdown.user_close_pause_failed" if failures else "runtime.shutdown.user_close_paused",
        message="Operator close task cleanup failed." if failures else "Operator close task cleanup settled.",
        outcome="failed" if failures else "accepted", level="error" if failures else "info",
        fields={"source": "electron_user_close", "taskCount": len(results), "failedCount": len(failures), "pauseResults": results},
    )
    if failures:
        raise runtime.RuntimeRestartPauseFailed(failures)
    response = runtime._electron_retire_local_shutdown(
        lang, source="electron_user_close", stopped_chat_turns=harvested["turns"],
        stopped_chat_room_rounds=harvested["rooms"], stopped_source_collection_runs=harvested["sources"],
        stopped_evolution_runs=[item for kind in ("self_evolution_run", "supervised_evolution_run", "supervised_worktree_evolution_run") for item in harvested[kind]],
    )
    response["otherWorkRuns"] = [*harvested["autonomous"], *harvested["formal_review"]]
    return response
