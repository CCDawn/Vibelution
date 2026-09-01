"""Agent-scoped tools for the trusted virtual-human-life plugin.

The current Agent identity always comes from the server-owned runtime context.
No tool accepts an arbitrary target Agent id.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from core.chat.chat_task_types import trim_lines


def _runtime_context() -> dict[str, Any]:
    from core.web.services import agent_directory_service

    runtime = agent_directory_service.current_agent_runtime()
    return dict(runtime) if isinstance(runtime, dict) else {}


def _service():
    from core.web.services.virtual_human_life_service import (
        get_virtual_human_life_service,
    )

    return get_virtual_human_life_service()


def _result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _blocked(message: str, *, error: str) -> str:
    return _result({"ok": False, "status": "blocked", "error": error, "message": message})


def _invoke(operation, *, require_steward: bool = False) -> str:
    runtime = _runtime_context()
    runtime_agent_id = str(runtime.get("agentId") or "").strip()
    if not runtime_agent_id:
        return _blocked("当前工具需要在已绑定 Agent 的运行时中调用。", error="agent_runtime_missing")
    try:
        from core.web.services.virtual_human_life_service import (
            resolve_virtual_human_runtime_target,
        )

        resolved = resolve_virtual_human_runtime_target(
            runtime_agent_id,
            session_id=str(runtime.get("sessionId") or ""),
            runtime_agent=(runtime.get("agent") if isinstance(runtime.get("agent"), dict) else None),
        )
        if require_steward and not bool(resolved.get("steward")):
            return _blocked(
                "结构化生活世界只能由已配对的生活管家修改。",
                error="life_steward_required",
            )
        target_agent_id = str(resolved.get("targetAgentId") or "").strip()
        payload = {
            "ok": True,
            "agentId": target_agent_id,
            **operation(target_agent_id),
        }
        if target_agent_id != runtime_agent_id:
            payload["runtimeAgentId"] = runtime_agent_id
        return _result(payload)
    except Exception as exc:  # noqa: BLE001 - tool boundary returns structured failure
        if str(exc).strip() == "Virtual-human plugin binding is disabled for this Agent.":
            return _blocked(
                "当前 Agent 未启用虚拟人生活插件。",
                error="plugin_binding_disabled",
            )
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
    event_id: str = "",
    calendar_kind: str = "one_off",
    recurrence: dict[str, Any] | None = None,
    occurrence_date: str = "",
    replacement_title: str = "",
    replacement_start_at: str = "",
    replacement_end_at: str = "",
    source_kind: str = "agent",
    source_ref: str = "",
    reason: str = "",
    idempotency_key: str = "",
) -> str:
    """查询日程、维护长期日历，或提出受 ToolPolicy 约束的工具型活动。

    action: view | propose_tool_activity | upsert_calendar | cancel_calendar |
    set_calendar_exception。日历只负责长期约定和重复安排，活动执行仍由每日
    schedule 与原生 proactive turn 负责，不能因为日历存在就宣称完成。
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
        calendar_commands = {
            "upsert_calendar": "upsertCalendarEvent",
            "cancel_calendar": "cancelCalendarEvent",
            "set_calendar_exception": "setCalendarException",
        }
        calendar_command = calendar_commands.get(normalized_action, "")
        if calendar_command:
            key = str(idempotency_key or "").strip()
            if not key:
                return {
                    "status": "blocked",
                    "error": "idempotency_key_required",
                    "message": "修改长期日历需要 idempotency_key。",
                }
            arguments: dict[str, Any] = {
                "eventId": str(event_id or "").strip(),
                "localDate": str(local_date or "").strip(),
                "reason": str(reason or "").strip(),
            }
            if calendar_command == "upsertCalendarEvent":
                arguments.update(
                    {
                        "title": str(title or "").strip(),
                        "kind": str(calendar_kind or "one_off").strip(),
                        "startAt": str(start_at or "").strip(),
                        "endAt": str(end_at or "").strip(),
                        "recurrence": dict(recurrence or {}),
                        "sourceKind": str(source_kind or "agent").strip(),
                        "sourceRef": str(source_ref or "").strip(),
                    }
                )
            elif calendar_command == "setCalendarException":
                replacement = {
                    "title": str(replacement_title or "").strip(),
                    "startAt": str(replacement_start_at or "").strip(),
                    "endAt": str(replacement_end_at or "").strip(),
                }
                arguments.update(
                    {
                        "occurrenceDate": str(occurrence_date or local_date or "").strip(),
                        **(
                            {"replacement": replacement}
                            if replacement["startAt"] and replacement["endAt"]
                            else {}
                        ),
                    }
                )
            return {
                "status": "applied",
                "commandResult": _service().execute_command(
                    agent_id,
                    command=calendar_command,
                    expected_version=expected_version,
                    idempotency_key=key,
                    arguments=arguments,
                ),
            }
        if normalized_action != "view":
            return {
                "status": "blocked",
                "error": "invalid_action",
                "message": "action 必须是 view/propose_tool_activity/upsert_calendar/cancel_calendar/set_calendar_exception。",
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
    expected_world_revision: int = 0,
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
    place_id: str = "",
    place_label: str = "",
    route_from: str = "",
    route_minutes: int = 0,
    living_space: bool = False,
    item_id: str = "",
    item_label: str = "",
    significance: str = "",
    artifact_id: str = "",
    artifact_kind: str = "artifact",
    artifact_title: str = "",
    artifact_summary: str = "",
    source_event_ids: list[str] | None = None,
    local_ref: str = "",
    account_id: str = "",
    amount_minor: int = 0,
    currency: str = "",
    category: str = "",
    description: str = "",
    occurred_at: str = "",
    item_category: str = "",
    item_name: str = "",
    item_brand: str = "",
    item_model: str = "",
    item_status: str = "active",
    item_location: str = "",
    acquired_at: str = "",
    idempotency_key: str = "",
) -> str:
    """维护生活活动、环境/位置，以及由真实结果支撑的世界和作品记录。

    action: start | complete | fail | cancel | skip | replan |
    record_environment | start_move | complete_move | record_place_visit |
    record_important_item | record_artifact_receipt | record_transaction |
    upsert_life_item。
    complete 接收 outcome_summary 记录实际结果；计划文本不会被视为完成结果。
    """

    normalized_action = str(action or "").strip().lower()
    if normalized_action in {"record_transaction", "upsert_life_item"}:
        key = str(idempotency_key or "").strip()
        if not key:
            return _blocked(
                "修改结构化生活世界需要 idempotency_key。",
                error="idempotency_key_required",
            )
        if int(expected_world_revision or 0) <= 0:
            return _blocked(
                "修改结构化生活世界需要有效的 expected_world_revision。",
                error="expected_world_revision_required",
            )
        if normalized_action == "record_transaction":
            return _invoke(
                lambda agent_id: {
                    "status": "applied",
                    "lifeWorldResult": _service().record_life_world_transaction(
                        agent_id,
                        account_id=str(account_id or "").strip(),
                        amount_minor=int(amount_minor),
                        currency=str(currency or "").strip(),
                        category=str(category or "").strip(),
                        description=str(description or "").strip(),
                        occurred_at=str(occurred_at or "").strip(),
                        idempotency_key=key,
                        expected_world_revision=int(expected_world_revision),
                    ),
                },
                require_steward=True,
            )
        return _invoke(
            lambda agent_id: {
                "status": "applied",
                "lifeWorldResult": _service().upsert_life_world_item(
                    agent_id,
                    item_id=str(item_id or "").strip(),
                    category=str(item_category or "").strip(),
                    name=str(item_name or "").strip(),
                    brand=str(item_brand or "").strip(),
                    model=str(item_model or "").strip(),
                    status=str(item_status or "active").strip(),
                    current_location=str(item_location or "").strip(),
                    acquired_at=str(acquired_at or "").strip(),
                    idempotency_key=key,
                    expected_world_revision=int(expected_world_revision),
                ),
            },
            require_steward=True,
        )

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
        "record_place_visit": "recordPlaceVisit",
        "record_important_item": "recordImportantItem",
        "record_artifact_receipt": "recordArtifactReceipt",
    }
    command = command_by_action.get(normalized_action, "")
    if not command:
        return _blocked(
            "action 必须是 start/complete/fail/cancel/skip/replan/record_environment/start_move/complete_move/record_place_visit/record_important_item/record_artifact_receipt/record_transaction/upsert_life_item。",
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
            "kind": "verified_tool_outcome",
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
    elif command == "recordPlaceVisit":
        arguments.update(
            {
                "placeId": str(place_id or "").strip(),
                "label": str(place_label or "").strip(),
                "sourceEventId": str(source_ref or "").strip(),
                "routeFrom": str(route_from or "").strip(),
                "routeMinutes": int(route_minutes or 0),
                "livingSpace": bool(living_space),
            }
        )
    elif command == "recordImportantItem":
        arguments.update(
            {
                "itemId": str(item_id or "").strip(),
                "label": str(item_label or "").strip(),
                "placeId": str(place_id or "").strip(),
                "sourceKind": str(source_kind or "activity_outcome").strip(),
                "sourceRef": str(source_ref or "").strip(),
                "significance": str(significance or "").strip(),
            }
        )
    elif command == "recordArtifactReceipt":
        arguments.update(
            {
                "artifactId": str(artifact_id or "").strip(),
                "kind": str(artifact_kind or "artifact").strip(),
                "title": str(artifact_title or "").strip(),
                "summary": str(artifact_summary or "").strip(),
                "status": "succeeded",
                "sourceEventIds": list(source_event_ids or []),
                "localRef": str(local_ref or "").strip(),
            }
        )
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
    action: str = "interact",
    target_id: str = "",
    interaction_kind: str = "",
    note: str = "",
    intimacy_delta: int = 0,
    trust_delta: int = 0,
    npc_id: str = "",
    display_name: str = "",
    role: str = "",
    traits: list[str] | None = None,
    source_kind: str = "lived_event",
    source_ref: str = "",
    expected_version: int = 0,
    idempotency_key: str = "",
) -> str:
    """查询关系，记录有界互动，或维护人物生活里的轻量 NPC 档案。

    action: list | interact | upsert_npc。NPC 不是 Agent，不拥有 Session、工具或权限。
    """

    normalized_action = str(action or "interact").strip().lower()
    if normalized_action not in {"list", "interact", "upsert_npc"}:
        return _blocked("action 必须是 list/interact/upsert_npc。", error="invalid_action")
    key = str(idempotency_key or "").strip()
    is_read = normalized_action == "list" or (
        normalized_action == "interact" and not str(target_id or "").strip()
    )
    if not is_read and not key:
        return _blocked("记录关系互动需要 idempotency_key。", error="idempotency_key_required")

    def operation(agent_id: str) -> dict[str, Any]:
        if is_read:
            return {"status": "ready", "relationships": _service().list_relationships(agent_id)}
        if normalized_action == "upsert_npc":
            return {
                "status": "recorded",
                "commandResult": _service().execute_command(
                    agent_id,
                    command="upsertNpc",
                    expected_version=expected_version,
                    idempotency_key=key,
                    arguments={
                        "npcId": str(npc_id or "").strip(),
                        "displayName": str(display_name or "").strip(),
                        "role": str(role or "").strip(),
                        "traits": list(traits or []),
                        "sourceKind": str(source_kind or "lived_event").strip(),
                        "sourceRef": str(source_ref or "").strip(),
                    },
                ),
            }
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


def virtual_human_reflection_tool(
    action: str = "list",
    proposal_id: str = "",
    source_kind: str = "lived_event",
    target_kind: str = "self_narrative",
    text: str = "",
    source_event_ids: list[str] | None = None,
    source_fact_ids: list[str] | None = None,
    supersedes_episode_id: str = "",
    supersedes_proposal_id: str = "",
    expected_version: int = 0,
    idempotency_key: str = "",
) -> str:
    """列出或提出自我反思；本工具不能批准、拒绝或替换审核结果。

    action: list | propose。propose 只生成 pending 提案，审核前不会进入 Prompt、
    Persona 或原生 episodic memory。
    """

    normalized_action = str(action or "list").strip().lower()
    if normalized_action == "list":
        return _invoke(
            lambda agent_id: {
                "status": "ready",
                "proposals": _service().list_reflection_proposals(agent_id, limit=50),
            }
        )
    if normalized_action != "propose":
        return _blocked(
            "action 必须是 list 或 propose；审核不开放给 Agent 工具。",
            error="invalid_action",
        )
    key = str(idempotency_key or "").strip()
    if not key:
        return _blocked("提出反思需要 idempotency_key。", error="idempotency_key_required")
    return _invoke(
        lambda agent_id: {
            "status": "proposed",
            "commandResult": _service().execute_command(
                agent_id,
                command="recordReflectionProposal",
                expected_version=expected_version,
                idempotency_key=key,
                arguments={
                    "proposalId": str(proposal_id or "").strip(),
                    "sourceKind": str(source_kind or "lived_event").strip(),
                    "targetKind": str(target_kind or "self_narrative").strip(),
                    "text": str(text or "").strip(),
                    "sourceEventIds": list(source_event_ids or []),
                    "sourceFactIds": list(source_fact_ids or []),
                    "supersedesEpisodeId": str(supersedes_episode_id or "").strip(),
                    "supersedesProposalId": str(supersedes_proposal_id or "").strip(),
                },
            ),
        }
    )


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


def virtual_human_dialogue_decision_v2_tool(
    act: str,
    reasonCode: str,
    topicKey: str,
    expectsUserReply: bool,
    referencedSourceKeys: list[str] | None = None,
) -> str:
    """记录当前人物消息的自然延续决策，不生成或保存下一条消息文本。

    act: continue_dialogue | ask_user | stop。身份、会话、Turn 与调用标识
    全部由当前 Agent 运行时绑定，模型不可指定。
    """

    runtime = _runtime_context()
    agent_id = str(runtime.get("agentId") or "").strip()
    session_id = str(runtime.get("sessionId") or "").strip()
    turn_id = str(runtime.get("turnId") or runtime.get("runId") or "").strip()
    if not agent_id or not session_id or not turn_id:
        return _blocked(
            "当前对话决策需要已绑定的人物 Agent、Session 与 Turn。",
            error="companion_turn_runtime_missing",
        )
    model_decision = {
        "act": str(act or "").strip(),
        "reasonCode": str(reasonCode or "").strip(),
        "topicKey": str(topicKey or "").strip(),
        "expectsUserReply": bool(expectsUserReply),
        "referencedSourceKeys": [
            str(item).strip()
            for item in list(referencedSourceKeys or [])
            if str(item).strip()
        ],
    }
    canonical = json.dumps(
        model_decision,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    tool_call_id = "dialogue-v2:" + hashlib.sha256(
        f"{turn_id}\x1f{canonical}".encode()
    ).hexdigest()[:24]
    try:
        plan = _service().record_dialogue_decision_v2(
            agent_id,
            session_id=session_id,
            turn_id=turn_id,
            model_decision=model_decision,
            tool_call_id=tool_call_id,
        )
        return _result(
            {
                "ok": True,
                "status": str(plan.get("decisionDraftStatus") or "recorded"),
                "act": str((plan.get("decisionDraft") or {}).get("act") or "stop"),
            }
        )
    except Exception as exc:  # noqa: BLE001 - tool boundary returns structured failure
        return _result(
            {
                "ok": False,
                "status": "failed",
                "error": type(exc).__name__,
                "message": trim_lines(str(exc), max_lines=2),
            }
        )


__all__ = [
    "virtual_human_activity_tool",
    "virtual_human_dialogue_decision_v2_tool",
    "virtual_human_diary_tool",
    "virtual_human_proactive_message_tool",
    "virtual_human_reflection_tool",
    "virtual_human_relationship_tool",
    "virtual_human_schedule_tool",
    "virtual_human_status_tool",
]
