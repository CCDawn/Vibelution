"""Agent-scoped tools for the trusted virtual-human-life plugin.

The current Agent identity always comes from the server-owned runtime context.
No tool accepts an arbitrary target Agent id.
"""

from __future__ import annotations

import json
from typing import Any

from core.chat.chat_task_types import trim_lines


def _runtime_agent_id() -> str:
    from core.web.services import agent_directory_service

    return str(agent_directory_service.current_agent_runtime().get("agentId") or "").strip()


def _service():
    from core.web.services.virtual_human_life_service import (
        get_virtual_human_life_service,
    )

    return get_virtual_human_life_service()


def _result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _blocked(message: str, *, error: str) -> str:
    return _result({"ok": False, "status": "blocked", "error": error, "message": message})


def _invoke(operation) -> str:
    agent_id = _runtime_agent_id()
    if not agent_id:
        return _blocked("当前工具需要在已绑定 Agent 的运行时中调用。", error="agent_runtime_missing")
    try:
        binding = _service().binding_for(agent_id)
        if not binding or not bool(binding.get("enabled")):
            return _blocked("当前 Agent 未启用虚拟人生活插件。", error="plugin_binding_disabled")
        return _result({"ok": True, "agentId": agent_id, **operation(agent_id)})
    except Exception as exc:  # noqa: BLE001 - tool boundary returns structured failure
        return _result(
            {
                "ok": False,
                "status": "failed",
                "error": type(exc).__name__,
                "message": trim_lines(str(exc), max_lines=2),
            }
        )


def virtual_human_status_tool() -> str:
    """查询当前虚拟人的心情、体力、当前活动和插件运行状态。"""

    return _invoke(lambda agent_id: {"status": "ready", "snapshot": _service().snapshot(agent_id)})


def virtual_human_schedule_tool(
    local_date: str = "",
    action: str = "view",
    expected_version: int = 0,
    title: str = "",
    start_at: str = "",
    end_at: str = "",
    required_tool_names: list[str] | None = None,
    idempotency_key: str = "",
) -> str:
    """查询日程，或提出一个受当前 Agent ToolPolicy 约束的工具型活动。

    action: view | propose_tool_activity。提出活动只登记计划；到达时间后仍通过
    原生 proactive turn 和实际工具授权执行，不能因为计划存在就宣称完成。
    """

    def operation(agent_id: str) -> dict[str, Any]:
        normalized_action = str(action or "view").strip().lower()
        if normalized_action == "propose_tool_activity":
            key = str(idempotency_key or "").strip()
            if not key:
                return {
                    "status": "blocked",
                    "error": "idempotency_key_required",
                    "message": "提出工具型活动需要 idempotency_key。",
                }
            return {
                "status": "applied",
                "commandResult": _service().execute_command(
                    agent_id,
                    command="proposeToolActivity",
                    expected_version=expected_version,
                    idempotency_key=key,
                    arguments={
                        "localDate": str(local_date or "").strip(),
                        "title": str(title or "").strip(),
                        "startAt": str(start_at or "").strip(),
                        "endAt": str(end_at or "").strip(),
                        "requiredToolNames": list(required_tool_names or []),
                    },
                ),
            }
        if normalized_action != "view":
            return {
                "status": "blocked",
                "error": "invalid_action",
                "message": "action 必须是 view 或 propose_tool_activity。",
            }
        if local_date:
            return {"status": "ready", "schedule": _service().schedule_for(agent_id, local_date)}
        snapshot = _service().snapshot(agent_id)
        return {
            "status": "ready",
            "today": snapshot.get("todaySchedule"),
            "tomorrow": snapshot.get("tomorrowSchedule"),
        }

    return _invoke(operation)


def virtual_human_activity_tool(
    action: str,
    expected_version: int,
    activity_id: str = "",
    local_date: str = "",
    reason: str = "",
    outcome_summary: str = "",
    salience_score: int = 0,
    movement_id: str = "",
    destination: str = "",
    travel_minutes: int = 15,
    fact_key: str = "",
    fact_value: str = "",
    source_kind: str = "",
    source_ref: str = "",
    confidence: int = 80,
    idempotency_key: str = "",
) -> str:
    """维护生活活动、授权环境事实和有耗时的位置移动。

    action: start | complete | fail | cancel | skip | replan |
    record_environment | start_move | complete_move。
    complete 接收 outcome_summary 记录实际结果；计划文本不会被视为完成结果。
    """

    command_by_action = {
        "start": "startActivity",
        "complete": "completeActivity",
        "fail": "failActivity",
        "cancel": "cancelActivity",
        "skip": "skipActivity",
        "replan": "replan",
        "record_environment": "recordEnvironmentFact",
        "start_move": "startLocationMove",
        "complete_move": "completeLocationMove",
    }
    command = command_by_action.get(str(action or "").strip().lower(), "")
    if not command:
        return _blocked(
            "action 必须是 start/complete/fail/cancel/skip/replan/record_environment/start_move/complete_move。",
            error="invalid_action",
        )
    key = str(idempotency_key or "").strip()
    if not key:
        return _blocked("修改生活活动需要 idempotency_key。", error="idempotency_key_required")
    arguments: dict[str, Any] = {
        "activityId": str(activity_id or "").strip(),
        "localDate": str(local_date or "").strip(),
        "reason": str(reason or "").strip(),
    }
    if command == "completeActivity":
        arguments["outcome"] = {
            "status": "succeeded",
            "summary": str(outcome_summary or "").strip(),
            "salienceScore": int(salience_score or 0),
        }
    elif command == "recordEnvironmentFact":
        arguments.update(
            {
                "factKey": str(fact_key or "").strip(),
                "value": str(fact_value or "").strip(),
                "sourceKind": str(source_kind or "tool").strip(),
                "sourceRef": str(source_ref or "").strip(),
                "confidence": int(confidence or 80),
            }
        )
    elif command == "startLocationMove":
        arguments.update(
            {
                "movementId": str(movement_id or "").strip(),
                "destination": str(destination or "").strip(),
                "travelMinutes": int(travel_minutes or 15),
                "sourceKind": str(source_kind or "schedule_outcome").strip(),
                "sourceRef": str(source_ref or "").strip(),
            }
        )
    elif command == "completeLocationMove":
        arguments["movementId"] = str(movement_id or "").strip()
    return _invoke(
        lambda agent_id: {
            "status": "applied",
            "commandResult": _service().execute_command(
                agent_id,
                command=command,
                expected_version=expected_version,
                idempotency_key=key,
                arguments=arguments,
            ),
        }
    )


def virtual_human_diary_tool(
    local_date: str = "",
    review: bool = False,
    expected_version: int = 0,
    idempotency_key: str = "",
) -> str:
    """查询日记；review=true 时只从已完成且有 outcome 的生活事件生成日记。"""

    key = str(idempotency_key or "").strip()
    if review and not key:
        return _blocked("生成日记需要 idempotency_key。", error="idempotency_key_required")

    def operation(agent_id: str) -> dict[str, Any]:
        if not review:
            return {
                "status": "ready",
                "entries": _service().list_diary(agent_id, local_date=local_date),
            }
        return {
            "status": "reviewed",
            "commandResult": _service().execute_command(
                agent_id,
                command="triggerDiaryReview",
                expected_version=expected_version,
                idempotency_key=key,
                arguments={"localDate": local_date},
            ),
        }

    return _invoke(operation)


def virtual_human_relationship_tool(
    target_id: str = "",
    interaction_kind: str = "",
    note: str = "",
    intimacy_delta: int = 0,
    trust_delta: int = 0,
    expected_version: int = 0,
    idempotency_key: str = "",
) -> str:
    """查询关系；提供 target_id 时记录一次有界关系互动并更新数值投影。"""

    key = str(idempotency_key or "").strip()
    if str(target_id or "").strip() and not key:
        return _blocked("记录关系互动需要 idempotency_key。", error="idempotency_key_required")

    def operation(agent_id: str) -> dict[str, Any]:
        if not str(target_id or "").strip():
            return {"status": "ready", "relationships": _service().list_relationships(agent_id)}
        return {
            "status": "recorded",
            "commandResult": _service().execute_command(
                agent_id,
                command="recordRelationshipInteraction",
                expected_version=expected_version,
                idempotency_key=key,
                arguments={
                    "targetId": target_id,
                    "kind": interaction_kind,
                    "note": note,
                    "intimacyDelta": intimacy_delta,
                    "trustDelta": trust_delta,
                },
            ),
        }

    return _invoke(operation)


def virtual_human_proactive_message_tool(
    reason: str = "",
    source_event_id: str = "",
    valid_for_minutes: int = 30,
    action: str = "request",
    expected_version: int = 0,
    idempotency_key: str = "",
    topic_key: str = "",
    loop_kind: str = "topic",
    summary: str = "",
    source_turn_id: str = "",
    expires_in_minutes: int = 10_080,
    resolution: str = "",
) -> str:
    """申请主动消息，或维护未完话题、承诺和回应状态。

    action: request | record_open_loop | resolve_open_loop | record_reply。
    request 仍受候选价值、额度、间隔、免打扰和 binding revision 约束；
    其他动作只更新 Agent 私有的连续性账本，不直接创建会话 Turn。
    """

    normalized_action = str(action or "request").strip().lower()
    if normalized_action == "request":
        return _invoke(
            lambda agent_id: {
                "status": "requested",
                "attempt": _service().request_proactive_message(
                    agent_id,
                    reason=reason,
                    source_event_id=source_event_id,
                    valid_for_minutes=valid_for_minutes,
                ),
            }
        )

    command_by_action = {
        "record_open_loop": "recordOpenLoop",
        "resolve_open_loop": "resolveOpenLoop",
        "record_reply": "recordConversationReply",
    }
    command = command_by_action.get(normalized_action, "")
    if not command:
        return _blocked(
            "action 必须是 request/record_open_loop/resolve_open_loop/record_reply。",
            error="invalid_action",
        )
    key = str(idempotency_key or "").strip()
    if not key:
        return _blocked(
            "维护会话连续性需要 idempotency_key。",
            error="idempotency_key_required",
        )
    arguments = {
        "topicKey": str(topic_key or "").strip(),
        "kind": str(loop_kind or "topic").strip(),
        "summary": str(summary or "").strip(),
        "sourceTurnId": str(source_turn_id or "").strip(),
        "sourceEventId": str(source_event_id or "").strip(),
        "expiresInMinutes": int(expires_in_minutes or 10_080),
        "resolution": str(resolution or "").strip(),
    }

    return _invoke(
        lambda agent_id: {
            "status": "recorded",
            "commandResult": _service().execute_command(
                agent_id,
                command=command,
                expected_version=expected_version,
                idempotency_key=key,
                arguments=arguments,
            ),
        }
    )


__all__ = [
    "virtual_human_activity_tool",
    "virtual_human_diary_tool",
    "virtual_human_proactive_message_tool",
    "virtual_human_relationship_tool",
    "virtual_human_schedule_tool",
    "virtual_human_status_tool",
]
