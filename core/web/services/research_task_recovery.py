"""Repair registered research-task projections outside read-only request paths."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.infrastructure import developer_sandbox
from . import runtime_task_registry, session_service
from .team_workflow import research_project_agent_tasks as tasks
from .team_workflow.research_runtime.archive_mode import challenge_archive_mode_enabled

logger = logging.getLogger(__name__)

# 反查不到账本依据的注册表行超过该年龄后按 stale 收口；环境变量可覆盖，
# 解析失败或非正值回退默认（镜像 work_run_store.STALE_SNAPSHOT_GRACE 的常量风格）。
STALE_GRACE_ENV_VAR = "VIBELUTION_RUNTIME_TASK_STALE_GRACE_HOURS"
DEFAULT_STALE_GRACE_HOURS = 24.0


def _stale_grace_hours() -> float:
    raw = str(os.environ.get(STALE_GRACE_ENV_VAR) or "").strip()
    if raw:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return value
    return DEFAULT_STALE_GRACE_HOURS


def _parse_iso_utc(raw: str) -> datetime | None:
    normalized = str(raw or "").strip().replace("Z", "+00:00")
    if not normalized:
        return None
    try:
        stamp = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def _row_exceeds_stale_grace(snapshot: dict[str, Any]) -> bool:
    """行龄 = now -（updatedAt，缺失时依次回退 startedAt / createdAt）。

    时间戳全部无法解析时保守视为未超龄：没有年龄证据就不收口。
    """

    deadline = datetime.now(timezone.utc) - timedelta(hours=_stale_grace_hours())
    for key in ("updatedAt", "startedAt", "createdAt"):
        stamp = _parse_iso_utc(str(snapshot.get(key) or ""))
        if stamp is not None:
            return stamp < deadline
    return False


def _research_task_store_scan_root() -> Path:
    """兜底扫描的 teams 根，与 research_project_agent_tasks._store_path 同一布局。"""

    return developer_sandbox.formal_workspace_path(session_service.PROJECT_ROOT, "teams")


def _scan_research_task_store_for_task(task_id: str) -> dict[str, Any] | None:
    """绑定缺失时按 taskId 精确扫描各团队账本文件（纯读，不新造路径逻辑）。

    布局镜像 ``research_projects.resolve_research_project_workspace_root``：
    ``teams/<team>/research_projects/<project>/workspace/<store>``，legacy
    默认项目直接落在 ``teams/<team>/<store>``。
    """

    normalized = str(task_id or "").strip()
    if not normalized:
        return None
    try:
        base = _research_task_store_scan_root()
        if not base.is_dir():
            return None
        file_name = tasks.TASK_STORE_FILE_NAME
        for path in sorted(
            base.glob(f"*/research_projects/*/workspace/{file_name}")
        ) + sorted(base.glob(f"*/{file_name}")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            for item in list(payload.get("tasks") or []):
                if not isinstance(item, dict):
                    continue
                if str(item.get("taskId") or "").strip() != normalized:
                    continue
                from core.web.services.team_workflow.research_projects import (
                    LEGACY_PROJECT_ID,
                )

                parts = path.relative_to(base).parts
                return {
                    "teamId": parts[0],
                    "researchProjectId": (
                        parts[2] if len(parts) >= 4 else LEGACY_PROJECT_ID
                    ),
                    "task": tasks._normalize_task(item),
                }
    except Exception:
        return None
    return None


def _find_business_task_for_row(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    """按 taskId 反查业务账本，返回 {"teamId","researchProjectId","task"} 或 None。

    优先沿用注册表行自带的 teamId/researchProjectId，其次取绑定 Session 的
    experiment_binding，最后兜底扫描各团队账本文件。
    """

    task_id = str(snapshot.get("taskId") or "").strip()
    if not task_id:
        return None
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
        if team_id and project_id:
            with tasks._TASK_LOCK:
                domain = tasks._read_store(team_id, project_id)
            matched = next(
                (
                    item
                    for item in domain["tasks"]
                    if str(item.get("taskId") or "").strip() == task_id
                ),
                None,
            )
            if matched is not None:
                return {
                    "teamId": team_id,
                    "researchProjectId": project_id,
                    "task": matched,
                }
    except Exception:
        pass
    return _scan_research_task_store_for_task(task_id)


def _closeout_registered_research_task_rows(
    store: runtime_task_registry.RuntimeTaskStore,
    *,
    should_stop: Callable[[], bool],
    unresolved_reasons: dict[str, str],
    row_snapshots: dict[str, dict[str, Any]],
) -> tuple[int, int]:
    """先收口扫描：账本已终态且不再需要 session reconcile 的行立即落终态。

    只处理 kind=research_task 的 active 行，其他 kind 一律不动。账本仍在
    跑、或仍可能被 session 真相升级裁决（incomplete / turn 未终态）的行保
    留给既有实验绑定对账；反查不到依据或身份对不上的行记入
    unresolved_reasons，由调用方按行龄统一决定是否标记 stale。
    """

    checked = repaired = 0
    for snapshot in store.active_task_states():
        if should_stop():
            break
        if snapshot.get("kind") != runtime_task_registry.KIND_RESEARCH_TASK:
            continue
        task_id = str(snapshot.get("taskId") or "").strip()
        if not task_id:
            continue
        row_snapshots[task_id] = snapshot
        located = _find_business_task_for_row(snapshot)
        if located is None:
            unresolved_reasons[task_id] = "ledger_not_found"
            continue
        business = located["task"]
        business_status = str(business.get("status") or "")
        if not runtime_task_registry.is_terminal_status(business_status):
            continue  # 账本仍在跑，交给既有对账流程。
        if tasks._task_needs_session_reconciliation(business):
            continue  # 仍可能被 session 真相升级，保留给 reconcile。
        if runtime_task_registry.is_terminal_status(str(snapshot.get("status") or "")):
            continue
        if not tasks._registry_row_accepts_business_terminal(
            snapshot, str(business.get("sessionId") or "")
        ):
            unresolved_reasons[task_id] = "identity_mismatch"
            continue
        try:
            with tasks._TASK_LOCK:
                if should_stop():
                    break
                tasks._publish_runtime_task_status(
                    located["teamId"], located["researchProjectId"], business,
                )
                landed = store.get_task(task_id) or {}
                if landed and not runtime_task_registry.is_terminal_status(
                    str(landed.get("status") or "")
                ):
                    # _publish_runtime_task_status 内部已兜底一次；这里再核对，
                    # 仍非终态则直写业务终态。
                    tasks._backstop_registry_row_terminal(
                        store, located["teamId"], located["researchProjectId"],
                        business, landed,
                    )
        except Exception:
            unresolved_reasons[task_id] = "closeout_error"
            continue
        final_row = store.get_task(task_id) or {}
        if final_row and runtime_task_registry.is_terminal_status(
            str(final_row.get("status") or "")
        ):
            checked += 1
            repaired += 1
            tasks._service()._record_workflow_event(
                "research_project_agent_task_registry_recovered",
                located["teamId"],
                fields={"researchProjectId": located["researchProjectId"],
                        "checked": 1, "closeout": True},
                outcome="accepted",
            )
    return checked, repaired


def _mark_stale_unresolved_rows(
    store: runtime_task_registry.RuntimeTaskStore,
    *,
    unresolved_reasons: dict[str, str],
    row_snapshots: dict[str, dict[str, Any]],
    should_stop: Callable[[], bool],
) -> int:
    """反查不到依据且超过宽限期的僵尸行按 stale 收口；年轻行保持不动。"""

    staled = 0
    for task_id, reason in sorted(unresolved_reasons.items()):
        if should_stop():
            break
        snapshot = row_snapshots.get(task_id)
        if snapshot is None or not _row_exceeds_stale_grace(snapshot):
            continue
        current = store.get_task(task_id) or {}
        if not current or runtime_task_registry.is_terminal_status(
            str(current.get("status") or "")
        ):
            continue  # 行已被其他路径收口，不得用 stale 覆盖既有终态。
        try:
            landed = store.mark_task_terminal(
                task_id, status="stale", reason="registry_stale_reconcile",
            )
        except Exception as exc:
            logger.warning(
                "Runtime research task stale close-out failed (taskId=%s, %s).",
                task_id, type(exc).__name__,
            )
            continue
        if landed:
            staled += 1
            logger.warning(
                "Runtime research task row closed as stale (taskId=%s, "
                "unresolved=%s, graceHours=%s).",
                task_id, reason, _stale_grace_hours(),
            )
    return staled


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
    unresolved_reasons: dict[str, str] = {}
    row_snapshots: dict[str, dict[str, Any]] = {}
    # 先收口：账本已终态的存量僵尸行立即落终态，不依赖实验绑定对账
    # 是否把它们纳入 reconcile 目标集。
    checked, repaired = _closeout_registered_research_task_rows(
        store, should_stop=should_stop,
        unresolved_reasons=unresolved_reasons, row_snapshots=row_snapshots,
    )
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for snapshot in store.active_task_states():
        if should_stop():
            break
        if snapshot.get("kind") != runtime_task_registry.KIND_RESEARCH_TASK:
            continue
        task_id = str(snapshot.get("taskId") or "").strip()
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
                unresolved_reasons[task_id] = "binding_missing"
                continue
            groups.setdefault((team_id, project_id), []).append(snapshot)
        except Exception:
            unresolved_reasons[task_id] = "binding_error"

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
                matched_task_ids = {task.get("taskId") for task in matched}
                for row in snapshots:
                    if row.get("taskId") not in matched_task_ids:
                        unresolved_reasons[str(row.get("taskId") or "").strip()] = (
                            "business_identity_mismatch"
                        )
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
            for row in snapshots:
                unresolved_reasons[str(row.get("taskId") or "").strip()] = "group_error"
            logger.warning("Research task recovery deferred (%s).", type(exc).__name__)
    repaired += _mark_stale_unresolved_rows(
        store, unresolved_reasons=unresolved_reasons,
        row_snapshots=row_snapshots, should_stop=should_stop,
    )
    # 反查不到账本依据的行不再无声吞掉：带 taskId 与原因留一条 warning。
    if unresolved_reasons:
        logger.warning(
            "Research task reconciliation left %d registry row(s) unresolved: %s",
            len(unresolved_reasons),
            "; ".join(
                f"{task_id or '(anonymous)'}={reason}"
                for task_id, reason in sorted(unresolved_reasons.items())
            ),
        )
    return {"checked": checked, "repaired": repaired, "unresolved": len(unresolved_reasons)}


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
