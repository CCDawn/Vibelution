"""Repair registered research-task projections outside read-only request paths."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from . import runtime_task_registry, session_service
from .team_workflow import research_project_agent_tasks as tasks
from .team_workflow.research_runtime.archive_mode import challenge_archive_mode_enabled

logger = logging.getLogger(__name__)


def reconcile_registered_research_tasks_once(
    *, should_stop: Callable[[], bool] = lambda: False, rebuild_index: bool = False,
) -> dict[str, int]:
    """Use the active index, exact task identity, Journal and existing business verdict.

    Legacy registry rows recover their project pointer from the bound Session's
    experiment binding. No title matching, guessed success or Session mutation.
    """
    store = runtime_task_registry.default_store()
    # Archive mode forbids automatic workflow-state writes, including recovery.
    if challenge_archive_mode_enabled():
        return {"checked": 0, "repaired": 0, "unresolved": 0}
    if should_stop():
        return {"checked": 0, "repaired": 0, "unresolved": 0}
    if rebuild_index:
        store.reconcile_index()
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    unresolved = 0
    for snapshot in store.active_task_states():
        if should_stop():
            break
        if snapshot.get("kind") != runtime_task_registry.KIND_RESEARCH_TASK:
            continue
        team_id = str(snapshot.get("teamId") or "")
        project_id = str(snapshot.get("researchProjectId") or "")
        try:
            if not (team_id and project_id):
                row = session_service.load_session_chat_state(
                    session_service.PROJECT_ROOT, str(snapshot.get("sourceSessionId") or ""),
                ) or {}
                binding = row.get("experiment_binding") or row.get("experimentBinding") or {}
                team_id = str(binding.get("teamId") or "")
                project_id = str(binding.get("researchProjectId") or "")
            if not (team_id and project_id):
                unresolved += 1
                continue
            groups.setdefault((team_id, project_id), []).append(snapshot)
        except Exception:
            unresolved += 1

    checked = repaired = 0
    for (team_id, project_id), snapshots in groups.items():
        if should_stop():
            break
        try:
            # Verify pointers against the business store before any reconcile.
            with tasks._TASK_LOCK:
                if should_stop():
                    break
                domain = tasks._read_store(team_id, project_id)
                matched = [task for task in domain["tasks"] if any(
                    task.get("taskId") == row.get("taskId")
                    and task.get("sessionId") == row.get("sourceSessionId")
                    and (not row.get("sourceTurnId")
                         or row["sourceTurnId"] == (task.get("turn") or {}).get("turnId"))
                    for row in snapshots
                )]
                unresolved += len(snapshots) - len(matched)
                if not matched:
                    continue
                checked += len(matched)
                if should_stop():
                    break
                tasks.reconcile_research_project_agent_task_statuses(
                    team_id, project_id, should_stop=should_stop,
                )
                latest = tasks._read_store(team_id, project_id)
                matched_ids = {task["taskId"] for task in matched}
                for task in latest["tasks"]:
                    if should_stop():
                        break
                    if task.get("taskId") in matched_ids:
                        # Also repairs a crash after business commit but before
                        # registry publication, including already terminal tasks.
                        tasks._publish_runtime_task_status(team_id, project_id, task)
                group_repaired = sum(
                    (store.get_task(row["taskId"]) or {}).get("status") != row.get("status")
                    for row in snapshots if row.get("taskId") in matched_ids
                )
                repaired += group_repaired
            if group_repaired:
                tasks._service()._record_workflow_event(
                    "research_project_agent_task_registry_recovered", team_id,
                    fields={"researchProjectId": project_id, "checked": len(matched)},
                    outcome="accepted",
                )
        except Exception as exc:
            unresolved += len(snapshots)
            logger.warning("Research task recovery deferred (%s).", type(exc).__name__)
    return {"checked": checked, "repaired": repaired, "unresolved": unresolved}


async def run_research_task_recovery(
    *, startup_jobs: Any, session_recovery: Any, interval_seconds: float = 30.0,
) -> None:
    """Lifespan-owned startup repair and periodic compensation; no subprocesses."""
    await asyncio.shield(session_recovery)
    iteration = 0
    while not startup_jobs.should_stop():
        try:
            iteration += 1
            await startup_jobs.run_sync(
                f"research-task-reconcile-{iteration}",
                reconcile_registered_research_tasks_once,
                should_stop=startup_jobs.should_stop,
                rebuild_index=iteration % 10 == 1,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Research task recovery will retry (%s).", type(exc).__name__)
        await asyncio.sleep(max(0.01, interval_seconds))
