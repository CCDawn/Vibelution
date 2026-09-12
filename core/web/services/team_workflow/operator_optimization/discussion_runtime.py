"""Native room bridge for one authority-bound operator discussion round."""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from core.research.workflow.contracts._canonical import sha256_hex
from core.research.workflow.contracts.discussion_scope import parse_discussion_scope
from core.web.services import chat_room_service

from ..research_project_agent_sessions import resolve_research_project_agent_session
from ..research_runtime import model_invocation_receipt_registry
from ..research_runtime.formal_write_runtime import get_write_store
from ..storage_durability import inter_process_lock
from . import discussion_authority
from .discussion import (
    DISCUSSION_MEETING_TYPE,
    DISCUSSION_SCOPE_AUTHORITY,
    discussion_input,
    read_discussion_result,
    save_discussion_result,
)
from .discussion_output import OperatorDiscussionOutputError, validated_result
from .store import CampaignConflict, campaign_root, read_campaign


# Keep a patchable module-level seam for domain tests and for the main Agent's
# authority implementation.  This is the only source of operator authority;
# this module never constructs a receipt binding itself.
build_operator_meeting_authority = discussion_authority.build_operator_meeting_authority
validate_operator_authority = discussion_authority.validate_operator_authority


def _authority_for_open(
    team_id: str,
    run_id: str,
    *,
    node_run_id: str,
    inputs: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        authority = build_operator_meeting_authority(
            team_id,
            run_id,
            node_run_id=node_run_id,
        )
    except Exception as exc:  # noqa: BLE001 - authority is a fail-closed boundary
        raise CampaignConflict(
            f"Operator discussion receipt authority is unavailable: {exc}"
        ) from exc
    if not isinstance(authority, Mapping):
        raise CampaignConflict("Operator discussion receipt authority is unavailable")
    authority = dict(authority)
    if authority.get("authorityKind") not in {None, "operator_discussion"}:
        raise CampaignConflict("Operator discussion authority kind differs")
    for key, expected in (
        ("teamId", team_id),
        ("workflowRunId", run_id),
        ("workflowId", "operator-optimization"),
    ):
        actual = str(authority.get(key) or "").strip()
        if actual and actual != expected:
            raise CampaignConflict(f"Operator discussion authority {key} differs")
    actual_node_run_id = str(authority.get("nodeRunId") or "").strip()
    if actual_node_run_id and actual_node_run_id != node_run_id:
        raise CampaignConflict("Operator discussion authority node run differs")
    expected_hash = sha256_hex(dict(inputs))
    authority_input_hash = str(authority.get("inputHash") or "").strip()
    if authority_input_hash and authority_input_hash != expected_hash:
        raise CampaignConflict("Operator discussion authority input differs")
    participants = authority.get("participants")
    if not isinstance(participants, list):
        raise CampaignConflict("Operator discussion authority has no frozen participants")
    seats: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in participants:
        if not isinstance(item, Mapping):
            raise CampaignConflict("Operator discussion authority participant is invalid")
        agent_id = str(item.get("agentId") or "").strip()
        if not agent_id or agent_id in seen:
            raise CampaignConflict("Operator discussion authority participants are not unique")
        seen.add(agent_id)
        seats.append(dict(item))
    if len(seats) < 2:
        raise CampaignConflict("Operator discussion requires at least two frozen participants")
    final_agent_id = str(authority.get("finalAgentId") or "").strip()
    if not final_agent_id or final_agent_id not in seen:
        raise CampaignConflict("Operator discussion requires a frozen final experiment_planner seat")
    authority["participants"] = seats
    authority["finalAgentId"] = final_agent_id
    return authority


def _session_id(value: Mapping[str, Any]) -> str:
    return str(value.get("sessionId") or value.get("id") or "").strip()


def _room_participants_by_agent(room: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in room.get("participants") or []:
        if not isinstance(item, Mapping):
            continue
        agent_id = str(item.get("agentId") or "").strip()
        if not agent_id or agent_id in result:
            raise CampaignConflict("Discussion room participants are not uniquely bound")
        result[agent_id] = dict(item)
    return result


def open_discussion(
    team_id: str,
    run_id: str,
    *,
    node_run_id: str = "",
) -> dict[str, Any]:
    """Open or reuse one room and one round for the real node attempt."""

    normalized_node_run_id = str(node_run_id or "").strip()
    if not normalized_node_run_id:
        raise CampaignConflict("node_run_id is required for operator discussion")
    inputs = discussion_input(team_id, run_id)
    context = inputs["context"]
    project_id = context["researchProjectId"]
    campaign = read_campaign(team_id, project_id, context["optimizationCampaignId"])
    if (
        not campaign.budget.authorized
        or not campaign.authorizedBy
        or campaign.budget.modelCostLimit <= 0
    ):
        raise CampaignConflict("Discussion requires authorized model budget")
    run = get_write_store().get_run(run_id)
    if run is None:
        raise CampaignConflict("Optimization discussion run is unavailable")
    try:
        snapshot = json.loads(run.input_snapshot_json)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CampaignConflict("Optimization discussion run input is invalid") from exc
    if not isinstance(snapshot, dict):
        raise CampaignConflict("Optimization discussion run input is invalid")
    scope = parse_discussion_scope(inputs["discussionScope"])
    authority = _authority_for_open(
        team_id,
        run_id,
        node_run_id=normalized_node_run_id,
        inputs=inputs,
    )
    room_id = "room-operator-" + sha256_hex({"team": team_id, "run": run_id})[:24]
    input_hash = sha256_hex(inputs)
    lock = campaign_root(team_id, project_id) / "discussion" / room_id
    with inter_process_lock(lock):
        existing = chat_room_service.get_chat_room_detail(room_id)
        if existing is not None:
            config = existing.get("config") if isinstance(existing.get("config"), Mapping) else {}
            if (
                config.get("workflowRunId") != run_id
                or config.get("inputHash") != input_hash
            ):
                raise CampaignConflict("Discussion room belongs to different frozen input")
            configured_node_run_id = str(config.get("nodeRunId") or "").strip()
            if configured_node_run_id and configured_node_run_id != normalized_node_run_id:
                raise CampaignConflict("Discussion room belongs to a different node attempt")
            rounds = list(existing.get("rounds") or [])
            if len(rounds) > 1:
                raise CampaignConflict("Optimization discussion requires exactly one chat round")
            if rounds:
                return {
                    "roomId": room_id,
                    "roundId": rounds[0]["roundId"],
                    "reused": True,
                }

        if existing is None:
            seats = authority["participants"]
            sessions: list[str] = []
            for seat in seats:
                agent_id = str(seat["agentId"]).strip()
                session = resolve_research_project_agent_session(
                    team_id,
                    research_project_id=project_id,
                    agent_id=agent_id,
                    role_key=str(seat.get("role") or "researcher"),
                    role_label="算子优化讨论",
                    created_from_task_id="operator-discussion:" + context["roundId"],
                    workflow_run_id=run_id,
                    workflow_node_id="optimization_discussion",
                    discussion_scope=scope,
                )
                resolved_session_id = _session_id(session)
                if not resolved_session_id:
                    raise CampaignConflict("Operator discussion participant session is unavailable")
                sessions.append(resolved_session_id)
            final_agent_id = authority["finalAgentId"]
            final_index = next(
                index
                for index, seat in enumerate(seats)
                if str(seat["agentId"]).strip() == final_agent_id
            )
            room_config = {
                "teamId": team_id,
                "researchProjectId": project_id,
                "workflowRunId": run_id,
                "workflowVersionId": authority.get("workflowVersionId") or run.workflow_version_id,
                "nodeRunId": normalized_node_run_id,
                "nodeAttempt": authority.get("nodeAttempt") or 1,
                "inputHash": input_hash,
                "operatorRoundId": context["roundId"],
                "scopeAuthority": DISCUSSION_SCOPE_AUTHORITY,
                "discussionScope": scope.to_dict(),
                "scopeHash": scope.scope_hash,
                "discussionScopeHash": scope.scope_hash,
                "operatorDiscussionAuthority": authority,
                "participantRoleSnapshot": [
                    {
                        "agentId": str(seat["agentId"]),
                        "role": str(seat.get("role") or "researcher"),
                    }
                    for seat in seats
                ],
                "finalParticipantAgentId": final_agent_id,
                "finalParticipantSessionId": sessions[final_index],
                "outputSchemaName": inputs["outputSchemaName"],
                "outputSchema": inputs["outputSchema"],
            }
            chat_room_service.create_chat_room(
                room_id=room_id,
                title="算子优化讨论",
                participant_session_ids=sessions,
                mode="round_robin",
                purpose="meeting",
                config=room_config,
            )
        else:
            room_config = existing.get("config") if isinstance(existing.get("config"), Mapping) else {}
            participants_by_agent = _room_participants_by_agent(existing)
            sessions = []
            for seat in authority["participants"]:
                participant = participants_by_agent.get(str(seat["agentId"]).strip())
                if participant is None or not _session_id(participant):
                    raise CampaignConflict("Existing operator discussion room has incomplete frozen participants")
                sessions.append(_session_id(participant))

        topic = (
            "进行一次算子优化讨论。按专属结构化输出合同返回 JSON；"
            "experiment_planner 最后发言并汇总一个主要结果。\n"
            + json.dumps(inputs, ensure_ascii=False)
        )
        round_config = {
            "speakerBatchMode": "serial",
            "speakerFenceRetry": False,
            "teamId": team_id,
            "researchProjectId": project_id,
            "workflowRunId": run_id,
            "workflowVersionId": authority.get("workflowVersionId") or run.workflow_version_id,
            "nodeRunId": normalized_node_run_id,
            "nodeAttempt": authority.get("nodeAttempt") or 1,
            "operatorRoundId": context["roundId"],
            "meetingType": DISCUSSION_MEETING_TYPE,
            "participantAgentIds": [str(seat["agentId"]) for seat in authority["participants"]],
            "question": snapshot.get("questionId") or "",
            "questionId": snapshot.get("questionId") or "",
            "outputSchemaName": inputs["outputSchemaName"],
            "outputSchema": inputs["outputSchema"],
            "operatorDiscussionAuthority": authority,
        }
        result = chat_room_service.start_chat_room_round(
            room_id,
            topic,
            purpose="meeting",
            config=round_config,
            background=True,
            lightweight_response=True,
            max_topic_lines=3,
            _model_invocation_receipt_authority=authority,
        )
        return {"roomId": room_id, "roundId": result["roundId"], "reused": False}


def _receipt_rows(
    team_id: str,
    *,
    question_id: str,
    run_id: str,
    session_id: str,
    turn_id: str,
) -> list[dict[str, Any]]:
    rows = model_invocation_receipt_registry.question_model_invocation_receipts(
        team_id,
        question_id=question_id,
        workflow_run_id=run_id,
        session_id=session_id,
        turn_id=turn_id,
    )
    exact: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        scope = row.get("scope") if isinstance(row.get("scope"), Mapping) else {}
        if (
            str(scope.get("sessionId") or "").strip() == session_id
            and str(scope.get("turnId") or "").strip() == turn_id
        ):
            exact.append(dict(row))
    return exact


def collect_discussion(
    team_id: str,
    run_id: str,
    *,
    node_run_id: str = "",
    budget_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Collect exact speaker receipts and publish the validated final result."""

    try:
        inputs = discussion_input(team_id, run_id)
    except CampaignConflict:
        # A no-viable result pauses the campaign.  Recollection must replay its
        # persisted source rather than reopening a room or fabricating a new
        # result from stale visible text.
        existing = read_discussion_result(team_id, run_id)
        if existing is not None and existing.get("status") == "no_viable_hypothesis":
            return existing
        raise
    input_hash = sha256_hex(inputs)
    room_id = "room-operator-" + sha256_hex({"team": team_id, "run": run_id})[:24]
    room = chat_room_service.get_chat_room_detail(room_id)
    config = room.get("config") if isinstance(room, Mapping) and isinstance(room.get("config"), Mapping) else {}
    if room is None or config.get("inputHash") != input_hash:
        raise CampaignConflict("Discussion room cannot be verified")
    authority = config.get("operatorDiscussionAuthority")
    if not isinstance(authority, Mapping):
        raise CampaignConflict("Operator discussion authority is missing from the room")
    try:
        authority = validate_operator_authority(dict(authority))
    except CampaignConflict:
        raise
    except Exception as exc:  # noqa: BLE001 - persisted authority is a fail-closed boundary
        raise CampaignConflict("Operator discussion authority cannot be verified") from exc
    if not isinstance(authority, Mapping):
        raise CampaignConflict("Operator discussion authority cannot be verified")
    authority = dict(authority)
    stored_node_run_id = str(authority.get("nodeRunId") or config.get("nodeRunId") or "").strip()
    if not stored_node_run_id:
        raise CampaignConflict("Operator discussion node run identity is missing")
    if node_run_id and str(node_run_id).strip() != stored_node_run_id:
        raise CampaignConflict("Operator discussion node run identity differs")
    rounds = list(room.get("rounds") or [])
    if len(rounds) != 1:
        raise CampaignConflict("Optimization discussion requires exactly one chat round")
    record = rounds[0]
    if str(record.get("status") or "").strip().lower() != "completed":
        raise CampaignConflict("All discussion participants must complete before result collection")

    seats = authority.get("participants")
    final_agent_id = str(authority.get("finalAgentId") or config.get("finalParticipantAgentId") or "").strip()
    if not isinstance(seats, list) or len(seats) < 2 or not final_agent_id:
        raise CampaignConflict("Operator discussion authority has incomplete frozen seats")
    room_participants = _room_participants_by_agent(room)
    if set(room_participants) != {
        str(item.get("agentId") or "").strip()
        for item in seats
        if isinstance(item, Mapping)
    }:
        raise CampaignConflict("Discussion room participants differ from the frozen authority")
    messages = [item for item in record.get("messages") or [] if isinstance(item, Mapping)]
    expected_sessions = {
        _session_id(room_participants[str(item["agentId"]).strip()])
        for item in seats
        if isinstance(item, Mapping) and str(item.get("agentId") or "").strip()
    }
    if len(messages) != len(expected_sessions):
        raise CampaignConflict("Discussion requires exactly one completed Turn per participant")
    if any(_session_id(item) not in expected_sessions for item in messages):
        raise CampaignConflict("Discussion contains a message outside the frozen participants")

    snapshot = json.loads(get_write_store().get_run(run_id).input_snapshot_json)
    question_id = str(snapshot.get("questionId") or "").strip()
    expected_by_agent = {str(item["agentId"]).strip(): dict(item) for item in seats if isinstance(item, Mapping)}
    message_refs: list[dict[str, Any]] = []
    receipt_refs: list[dict[str, Any]] = []
    receipt_ids: dict[str, str] = {}
    final_message = None
    final_result = None
    for agent_id, seat in expected_by_agent.items():
        participant = room_participants[agent_id]
        session_id = _session_id(participant)
        participant_id = str(participant.get("participantId") or "").strip()
        if not participant_id:
            raise CampaignConflict("Discussion participant has no stable participantId")
        matching = [
            item
            for item in messages
            if _session_id(item) == session_id
            and str(item.get("participantId") or "").strip() == participant_id
        ]
        if len(matching) != 1:
            raise CampaignConflict("Discussion requires exactly one message for each participant")
        message = dict(matching[0])
        if str(message.get("status") or "").strip().lower() != "completed":
            raise CampaignConflict("All discussion participants must complete before result collection")
        turn_id = f"chat-room:{record['roundId']}:{participant_id}"
        stored_turn_id = str(message.get("turnId") or message.get("turn_id") or "").strip()
        if stored_turn_id and stored_turn_id != turn_id:
            raise CampaignConflict("Discussion message Turn identity differs")
        receipts = _receipt_rows(
            team_id,
            question_id=question_id,
            run_id=run_id,
            session_id=session_id,
            turn_id=turn_id,
        )
        successful = [
            row
            for row in receipts
            if str(row.get("status") or "").strip().lower() in {"succeeded", "retried"}
        ]
        if not successful:
            raise CampaignConflict("Discussion lacks provider receipts for an exact participant Turn")
        try:
            structured = validated_result(message)
        except OperatorDiscussionOutputError as exc:
            raise CampaignConflict(f"Discussion structured output is invalid: {exc}") from exc
        if agent_id == final_agent_id:
            if structured.result is None:
                raise CampaignConflict("Final experiment_planner Turn must contain a discussion result")
            final_message = message
            final_result = structured.result
        elif structured.result is not None:
            raise CampaignConflict("Only the final experiment_planner seat may publish a discussion result")
        payload = structured.model_dump(mode="json")
        message_refs.append(
            {
                "messageId": str(message.get("messageId") or "").strip(),
                "agentId": agent_id,
                "sessionId": session_id,
                "participantId": participant_id,
                "turnId": turn_id,
                "payloadHash": sha256_hex(payload),
            }
        )
        for receipt in successful:
            receipt_id = str(receipt.get("receiptId") or "").strip()
            if not receipt_id:
                raise CampaignConflict("Discussion provider receipt has no stable receiptId")
            receipt_scope_key = f"{session_id}:{turn_id}"
            prior_scope = receipt_ids.get(receipt_id)
            if prior_scope is not None and prior_scope != receipt_scope_key:
                raise CampaignConflict("Discussion receipt identity is reused by another participant Turn")
            receipt_ids[receipt_id] = receipt_scope_key
            receipt_refs.append(
                {
                    "receiptId": receipt_id,
                    "sha256": sha256_hex(receipt),
                    "sessionId": session_id,
                    "turnId": turn_id,
                    "status": str(receipt.get("status") or "").strip().lower(),
                }
            )

    if final_message is None or final_result is None:
        raise CampaignConflict("Final experiment_planner output is unavailable")
    provenance = {
        "roomId": room_id,
        "chatRoundId": record["roundId"],
        "workflowRunId": run_id,
        "nodeRunId": stored_node_run_id,
        "nodeAttempt": authority.get("nodeAttempt") or config.get("nodeAttempt") or 1,
        "inputHash": input_hash,
        "discussionScope": config.get("discussionScope"),
        "discussionScopeHash": config.get("discussionScopeHash"),
        "participants": [
            {
                "agentId": agent_id,
                "role": str(seat.get("role") or "researcher"),
                "sessionId": _session_id(room_participants[agent_id]),
                "participantId": str(room_participants[agent_id].get("participantId") or ""),
            }
            for agent_id, seat in expected_by_agent.items()
        ],
        "finalParticipantAgentId": final_agent_id,
        "finalParticipantSessionId": _session_id(room_participants[final_agent_id]),
        "messageRefs": message_refs,
        "modelReceiptRefs": receipt_refs,
        "costStatus": (budget_receipt or {}).get("costStatus", "unsettled"),
        "budgetReceipt": {key: str(budget_receipt[key]) for key in (
            "receiptId", "reservationId", "currency", "knownAmount", "actualAmount", "costStatus")
            if budget_receipt and key in budget_receipt},
        "costBasis": "Provider token usage multiplied by the frozen price policy",
    }
    return save_discussion_result(
        team_id,
        run_id,
        final_result,
        provenance=provenance,
    )


__all__ = [
    "build_operator_meeting_authority",
    "collect_discussion",
    "open_discussion",
    "validate_operator_authority",
]
