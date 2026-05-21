"""Health diagnostics helpers for the web workbench."""

from __future__ import annotations

from typing import Any

from core.web.services.log_service import list_log_roots
from core.web.services.runtime_scene_service import list_runtime_scenes
from core.web.services.session_service import list_sessions


LOG_HELPER_DEFINITIONS = {
    "runtime_scenes": {
        "title": "运行现场日志",
        "description": "按一次工作台运行聚合前端、后端、浏览器和 API 事件。",
        "route": "/logs?root=runtime_scenes",
        "resetItemId": "stopped_runtime_scenes",
        "protected": True,
        "protectedReason": "运行中和当前现场由 Reset 固定保护；已停止现场可从 Reset 单独清理。",
    },
    "runtime_logs": {
        "title": "运行日志",
        "description": "后端、launcher 和运行器的即时输出。",
        "route": "/logs?root=runtime_logs",
        "resetItemId": "runtime_logs",
        "protected": False,
        "protectedReason": "",
    },
    "workspace_logs": {
        "title": "工作区日志",
        "description": "工作流转录、辅助脚本和工作区内生成的运行记录。",
        "route": "/logs?root=workspace_logs",
        "resetItemId": "",
        "protected": True,
        "protectedReason": "可能包含任务证据和工作流上下文，第一版只整理入口，不建议自动清理。",
    },
    "conversation_logs": {
        "title": "对话日志",
        "description": "agent 会话、工具调用、子 agent 输出和 debug 日志。",
        "route": "/logs?root=conversation_logs",
        "resetItemId": "conversation_logs",
        "protected": False,
        "protectedReason": "",
    },
}


def get_health_diagnostics() -> dict[str, Any]:
    """Return a read-only health diagnostics snapshot."""

    session_helpers = _build_session_helpers()
    log_helpers = _build_log_helpers()
    counts = _status_counts([*session_helpers, *log_helpers])
    overall_status = _overall_status(counts)
    findings = _build_findings(session_helpers, log_helpers)
    _attach_finding_ids([*session_helpers, *log_helpers], findings)
    quick_actions = _build_quick_actions(findings, session_helpers, log_helpers)
    return {
        "status": overall_status,
        "summary": _status_summary(overall_status, counts),
        "counts": counts,
        "findings": findings,
        "quickActions": quick_actions,
        "sessionHelpers": session_helpers,
        "logHelpers": log_helpers,
    }


def _build_session_helpers() -> list[dict[str, Any]]:
    sessions = _safe_sessions()
    total = len(sessions)
    active = next((item for item in sessions if _is_session_active(item)), sessions[0] if sessions else None)
    busy = [item for item in sessions if _session_status(item) in {"running", "thinking", "tooling", "answering", "planning", "reading", "editing", "verifying", "stopping"}]
    failed = [item for item in sessions if _session_status(item) in {"failed", "error"}]
    stale = [item for item in sessions if not str(item.get("updatedAt") or item.get("lastActive") or "").strip()]

    status = "ok"
    if failed:
        status = "blocked"
    elif busy or stale or not sessions:
        status = "warning"

    latest_signal = _session_latest_signal(active, total=total, busy_count=len(busy), failed_count=len(failed))
    return [
        {
            "id": "chat_sessions",
            "title": "会话 Helper",
            "description": "整理当前会话列表、活跃会话、运行中状态和最近对话信号。",
            "status": status,
            "statusLabel": _status_label(status),
            "sessionCount": total,
            "busyCount": len(busy),
            "failedCount": len(failed),
            "staleCount": len(stale),
            "activeSessionId": str(active.get("id") or "") if active else "",
            "activeTitle": str(active.get("title") or "") if active else "",
            "currentPhase": str(active.get("currentPhase") or active.get("status") or "") if active else "",
            "updatedAt": str(active.get("updatedAt") or active.get("lastActive") or "") if active else "",
            "latestSignal": latest_signal,
            "recommendedAction": _session_recommended_action(
                status,
                total=total,
                busy_count=len(busy),
                failed_count=len(failed),
            ),
            "route": f"/chat?session={str(active.get('id') or '')}" if active else "/chat",
            "protected": True,
            "protectedReason": "会话内容属于工作上下文，健康诊断只整理入口和状态，不在这里删除或修复。",
            "findingIds": [],
            "primaryFindingId": "",
        }
    ]


def _build_log_helpers() -> list[dict[str, Any]]:
    roots = list_log_roots()
    scenes = _safe_runtime_scenes()
    latest_scene = scenes[0] if scenes else None
    helpers: list[dict[str, Any]] = []

    for root in roots:
        root_id = str(root.get("id") or "")
        definition = LOG_HELPER_DEFINITIONS.get(root_id)
        if not definition:
            continue
        summary = root.get("summary") if isinstance(root.get("summary"), dict) else {}
        status = _log_helper_status(root, summary, root_id=root_id, latest_scene=latest_scene)
        latest_path = str(summary.get("latestPath") or "")
        helpers.append(
            {
                "id": root_id,
                "title": definition["title"],
                "description": definition["description"],
                "rootPath": str(root.get("path") or ""),
                "exists": bool(root.get("exists")),
                "status": status,
                "statusLabel": _status_label(status),
                "fileCount": int(summary.get("fileCount") or 0),
                "directoryCount": int(summary.get("directoryCount") or 0),
                "sizeBytes": int(summary.get("sizeBytes") or 0),
                "lastModifiedAt": str(summary.get("lastModifiedAt") or ""),
                "latestPath": latest_path,
                "latestSignal": _latest_signal(root_id, latest_path, latest_scene),
                "userGuide": str(summary.get("userGuide") or ""),
                "agentGuide": str(summary.get("agentGuide") or ""),
                "recommendedAction": _recommended_action(status, root_id, bool(root.get("exists")), latest_path, latest_scene),
                "route": definition["route"],
                "resetItemId": definition["resetItemId"],
                "protected": bool(definition["protected"]),
                "protectedReason": definition["protectedReason"],
                "findingIds": [],
                "primaryFindingId": "",
            }
        )
    return helpers


def _build_findings(
    session_helpers: list[dict[str, Any]],
    log_helpers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for helper in session_helpers:
        findings.extend(_session_findings(helper))
    for helper in log_helpers:
        findings.extend(_log_findings(helper))
    findings.extend(_reset_boundary_findings(log_helpers))
    findings.sort(key=_finding_sort_key)
    return findings


def _session_findings(helper: dict[str, Any]) -> list[dict[str, Any]]:
    total = int(helper.get("sessionCount") or 0)
    busy_count = int(helper.get("busyCount") or 0)
    failed_count = int(helper.get("failedCount") or 0)
    stale_count = int(helper.get("staleCount") or 0)
    route = str(helper.get("route") or "/chat")
    common_evidence = [
        _evidence("会话数", total),
        _evidence("运行中", busy_count),
        _evidence("失败", failed_count),
        _evidence("当前会话", helper.get("activeSessionId") or "未记录"),
        _evidence("阶段", helper.get("currentPhase") or "未记录"),
    ]
    if failed_count > 0:
        return [
            _finding(
                "session_failed",
                severity="blocked",
                source="session",
                helper_id=str(helper.get("id") or ""),
                title="会话失败需要先看",
                summary=f"{failed_count} 个会话处于失败状态，先从最近回答、工具调用和错误日志确认失败点。",
                evidence=common_evidence,
                recommended_action=str(helper.get("recommendedAction") or ""),
                route=route,
                protected=True,
            )
        ]
    if busy_count > 0:
        return [
            _finding(
                "session_busy",
                severity="warning",
                source="session",
                helper_id=str(helper.get("id") or ""),
                title="仍有会话在运行",
                summary=f"{busy_count} 个会话仍在推进或停止中，先确认它们不是卡住的旧任务。",
                evidence=common_evidence,
                recommended_action=str(helper.get("recommendedAction") or ""),
                route=route,
                protected=True,
            )
        ]
    if total <= 0:
        return [
            _finding(
                "session_empty",
                severity="warning",
                source="session",
                helper_id=str(helper.get("id") or ""),
                title="没有可诊断会话",
                summary="当前没有可整理的会话记录；诊断入口只能显示日志侧证据。",
                evidence=common_evidence,
                recommended_action=str(helper.get("recommendedAction") or ""),
                route=route,
                protected=True,
            )
        ]
    if stale_count > 0:
        return [
            _finding(
                "session_stale",
                severity="warning",
                source="session",
                helper_id=str(helper.get("id") or ""),
                title="会话缺少更新时间",
                summary=f"{stale_count} 个会话缺少更新时间，排序和最近信号可能不可靠。",
                evidence=[*common_evidence, _evidence("缺少更新时间", stale_count)],
                recommended_action=str(helper.get("recommendedAction") or ""),
                route=route,
                protected=True,
            )
        ]
    return []


def _log_findings(helper: dict[str, Any]) -> list[dict[str, Any]]:
    helper_id = str(helper.get("id") or "")
    exists = bool(helper.get("exists"))
    status = str(helper.get("status") or "")
    file_count = int(helper.get("fileCount") or 0)
    directory_count = int(helper.get("directoryCount") or 0)
    latest_signal = str(helper.get("latestSignal") or helper.get("latestPath") or "")
    route = str(helper.get("route") or "/logs")
    common_evidence = [
        _evidence("根目录", helper.get("rootPath") or helper_id),
        _evidence("文件", file_count),
        _evidence("目录", directory_count),
        _evidence("最近信号", latest_signal or "暂无"),
    ]
    if not exists:
        return [
            _finding(
                f"{helper_id}_missing",
                severity="warning",
                source="logs",
                helper_id=helper_id,
                title=f"{helper.get('title') or helper_id} 不存在",
                summary="这个日志根目录尚未生成，相关诊断证据暂时缺失。",
                evidence=common_evidence,
                recommended_action=str(helper.get("recommendedAction") or ""),
                route=route,
                reset_item_id=str(helper.get("resetItemId") or ""),
                protected=bool(helper.get("protected")),
            )
        ]
    if helper_id == "runtime_scenes" and status == "blocked":
        return [
            _finding(
                "runtime_scene_failed",
                severity="blocked",
                source="logs",
                helper_id=helper_id,
                title="最近运行现场失败",
                summary="最新 runtime scene 已标记失败，应该先读 timeline，再追 raw logs。",
                evidence=common_evidence,
                recommended_action=str(helper.get("recommendedAction") or ""),
                route=route,
                reset_item_id=str(helper.get("resetItemId") or ""),
                protected=bool(helper.get("protected")),
            )
        ]
    if file_count == 0 and directory_count == 0:
        return [
            _finding(
                f"{helper_id}_empty",
                severity="warning",
                source="logs",
                helper_id=helper_id,
                title=f"{helper.get('title') or helper_id} 为空",
                summary="这个日志入口存在但没有可读文件；如果刚完成一轮操作，需要确认日志是否写入正确位置。",
                evidence=common_evidence,
                recommended_action=str(helper.get("recommendedAction") or ""),
                route=route,
                reset_item_id=str(helper.get("resetItemId") or ""),
                protected=bool(helper.get("protected")),
            )
        ]
    return []


def _reset_boundary_findings(log_helpers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for helper in log_helpers:
        helper_id = str(helper.get("id") or "")
        if helper_id not in {"runtime_scenes", "workspace_logs"}:
            continue
        if not bool(helper.get("protected")):
            continue
        findings.append(
            _finding(
                f"{helper_id}_protected_boundary",
                severity="info",
                source="reset",
                helper_id=helper_id,
                title=f"{helper.get('title') or helper_id} 受保护",
                summary=str(helper.get("protectedReason") or "这个入口只整理证据，不在健康诊断里执行清理。"),
                evidence=[
                    _evidence("根目录", helper.get("rootPath") or helper_id),
                    _evidence("Reset 项", helper.get("resetItemId") or "无"),
                    _evidence("最近信号", helper.get("latestSignal") or "暂无"),
                ],
                recommended_action="需要清理时进入 Reset 页面手动选择；运行中、当前现场和工作流证据仍保持保护。",
                route=str(helper.get("route") or "/logs"),
                reset_item_id=str(helper.get("resetItemId") or ""),
                protected=True,
            )
        )
    return findings


def _attach_finding_ids(helpers: list[dict[str, Any]], findings: list[dict[str, Any]]) -> None:
    ids_by_helper: dict[str, list[str]] = {}
    for finding in findings:
        helper_id = str(finding.get("helperId") or "")
        finding_id = str(finding.get("id") or "")
        if not helper_id or not finding_id:
            continue
        ids_by_helper.setdefault(helper_id, []).append(finding_id)
    for helper in helpers:
        ids = ids_by_helper.get(str(helper.get("id") or ""), [])
        helper["findingIds"] = ids
        helper["primaryFindingId"] = ids[0] if ids else ""


def _build_quick_actions(
    findings: list[dict[str, Any]],
    session_helpers: list[dict[str, Any]],
    log_helpers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    seen_routes: set[str] = set()

    for finding in findings:
        if str(finding.get("severity") or "") not in {"blocked", "warning"}:
            continue
        route = str(finding.get("route") or "")
        if not route or route in seen_routes:
            continue
        seen_routes.add(route)
        actions.append(
            {
                "id": f"open_{finding['id']}",
                "title": _quick_action_title(finding),
                "description": str(finding.get("recommendedAction") or finding.get("summary") or ""),
                "route": route,
                "source": str(finding.get("source") or ""),
                "severity": str(finding.get("severity") or "info"),
                "findingId": str(finding.get("id") or ""),
                "resetItemId": str(finding.get("resetItemId") or ""),
                "protected": bool(finding.get("protected")),
            }
        )
        if len(actions) >= 4:
            break

    for helper in log_helpers:
        reset_item_id = str(helper.get("resetItemId") or "")
        if not reset_item_id:
            continue
        route = f"/reset?item={reset_item_id}"
        if route in seen_routes:
            continue
        seen_routes.add(route)
        actions.append(
            {
                "id": f"reset_{helper.get('id') or reset_item_id}",
                "title": _reset_action_title(str(helper.get("id") or "")),
                "description": f"{helper.get('title') or reset_item_id} 可在 Reset 中预览后确认清理。",
                "route": route,
                "source": "reset",
                "severity": "info",
                "findingId": str(helper.get("primaryFindingId") or ""),
                "resetItemId": reset_item_id,
                "protected": bool(helper.get("protected")),
            }
        )
        if len(actions) >= 6:
            break

    if not actions:
        for helper in [*session_helpers, *log_helpers]:
            route = str(helper.get("route") or "")
            if not route:
                continue
            actions.append(
                {
                    "id": f"open_{helper.get('id') or 'health'}",
                    "title": f"打开{helper.get('title') or '诊断入口'}",
                    "description": str(helper.get("latestSignal") or helper.get("description") or ""),
                    "route": route,
                    "source": "health",
                    "severity": "info",
                    "findingId": "",
                    "resetItemId": str(helper.get("resetItemId") or ""),
                    "protected": bool(helper.get("protected")),
                }
            )
            break
    return actions


def _finding(
    finding_id: str,
    *,
    severity: str,
    source: str,
    helper_id: str,
    title: str,
    summary: str,
    evidence: list[dict[str, str]],
    recommended_action: str,
    route: str,
    reset_item_id: str = "",
    protected: bool = False,
) -> dict[str, Any]:
    return {
        "id": finding_id,
        "severity": severity,
        "source": source,
        "helperId": helper_id,
        "title": title,
        "summary": summary,
        "evidence": [item for item in evidence if item.get("value")],
        "recommendedAction": recommended_action,
        "route": route,
        "resetItemId": reset_item_id,
        "protected": protected,
    }


def _evidence(label: str, value: Any) -> dict[str, str]:
    return {"label": label, "value": str(value)}


def _finding_sort_key(finding: dict[str, Any]) -> tuple[int, str]:
    severity_order = {"blocked": 0, "warning": 1, "info": 2}
    return (severity_order.get(str(finding.get("severity") or ""), 3), str(finding.get("id") or ""))


def _quick_action_title(finding: dict[str, Any]) -> str:
    source = str(finding.get("source") or "")
    if source == "session":
        return "打开相关会话"
    if source == "logs":
        return "打开相关日志"
    if source == "reset":
        return "查看保护边界"
    return f"处理：{finding.get('title') or '诊断项'}"


def _reset_action_title(helper_id: str) -> str:
    if helper_id == "runtime_scenes":
        return "清理已停止现场"
    if helper_id == "runtime_logs":
        return "清理运行日志"
    if helper_id == "conversation_logs":
        return "清理对话日志"
    return "打开 Reset 清理"


def _safe_sessions() -> list[dict[str, Any]]:
    try:
        return list_sessions()
    except Exception:
        return []


def _safe_runtime_scenes() -> list[dict[str, Any]]:
    try:
        return list_runtime_scenes(limit=5)
    except Exception:
        return []


def _is_session_active(session: dict[str, Any]) -> bool:
    return str(session.get("id") or "").strip() == str(session.get("activeSessionId") or "").strip()


def _session_status(session: dict[str, Any]) -> str:
    return str(session.get("currentPhase") or session.get("status") or "").strip().lower()


def _session_latest_signal(
    active: dict[str, Any] | None,
    *,
    total: int,
    busy_count: int,
    failed_count: int,
) -> str:
    if not active:
        return "暂无会话"
    title = str(active.get("title") or active.get("id") or "当前会话").strip()
    phase = str(active.get("currentPhase") or active.get("status") or "unknown").strip()
    parts = [title, phase, f"{total} 个会话"]
    if busy_count:
        parts.append(f"{busy_count} 个运行中")
    if failed_count:
        parts.append(f"{failed_count} 个失败")
    return " · ".join(parts)


def _session_recommended_action(status: str, *, total: int, busy_count: int, failed_count: int) -> str:
    if total <= 0:
        return "还没有可整理的会话；进入对话页创建或恢复一个会话。"
    if status == "blocked":
        return f"打开对话页，优先查看 {failed_count} 个失败会话的最近回答和工具调用。"
    if busy_count:
        return f"打开对话页，先确认 {busy_count} 个运行中会话是否仍在推进或需要停止。"
    return "打开对话页，从当前活跃会话和最近更新时间开始检查。"


def _log_helper_status(
    root: dict[str, Any],
    summary: dict[str, Any],
    *,
    root_id: str,
    latest_scene: dict[str, Any] | None,
) -> str:
    if not root.get("exists"):
        return "warning"
    if root_id == "runtime_scenes" and latest_scene:
        scene_status = str(latest_scene.get("status") or "").lower()
        scene_result = str(latest_scene.get("result") or "").lower()
        if scene_status == "failed" or "failed" in scene_result:
            return "blocked"
    health = str(summary.get("health") or "")
    if health in {"missing"}:
        return "warning"
    return "ok"


def _latest_signal(root_id: str, latest_path: str, latest_scene: dict[str, Any] | None) -> str:
    if root_id == "runtime_scenes" and latest_scene:
        status = str(latest_scene.get("status") or "unknown")
        display_name = str(latest_scene.get("displayName") or latest_scene.get("runtimeSceneId") or "")
        if display_name:
            return f"{display_name} · {status}"
        return status
    if latest_path:
        return latest_path
    return "暂无日志文件"


def _recommended_action(
    status: str,
    root_id: str,
    exists: bool,
    latest_path: str,
    latest_scene: dict[str, Any] | None,
) -> str:
    if not exists:
        return "目录不存在；先启动一次工作台或运行相关流程，让系统生成日志。"
    if root_id == "runtime_scenes" and latest_scene:
        if status == "blocked":
            return "打开运行现场，优先查看最近 failed scene 的 timeline 和 raw logs。"
        return "打开运行现场，按最近一次工作台运行查看统一时间线。"
    if latest_path:
        return "打开日志页，从最近文件开始查看诊断摘要。"
    return "当前目录为空；如刚完成一轮操作，重新运行诊断确认日志是否写入。"


def _status_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"ok": 0, "warning": 0, "blocked": 0}
    for item in items:
        status = str(item.get("status") or "warning")
        if status not in counts:
            status = "warning"
        counts[status] += 1
    return counts


def _overall_status(counts: dict[str, int]) -> str:
    if counts.get("blocked", 0) > 0:
        return "blocked"
    if counts.get("warning", 0) > 0:
        return "warning"
    return "ok"


def _status_summary(status: str, counts: dict[str, int]) -> str:
    if status == "blocked":
        return f"健康诊断发现 {counts.get('blocked', 0)} 个阻塞项，需要先查看对应会话或日志。"
    if status == "warning":
        return f"健康诊断有 {counts.get('warning', 0)} 个注意项，其余入口可正常使用。"
    return "会话与日志 Helper 入口正常，可以从最近信号开始诊断。"


def _status_label(status: str) -> str:
    if status == "blocked":
        return "阻塞"
    if status == "warning":
        return "注意"
    return "正常"
