"""Bind one optimization discussion to native project sessions and chat rounds.

Internal bridge only: the workflow caller owns model-budget admission and
terminal result collection. This module does not mark a hypothesis completed.
"""
from __future__ import annotations

import json

from core.research.workflow.contracts._canonical import sha256_hex
from core.research.workflow.contracts.discussion_scope import parse_discussion_scope
from core.web.services import chat_room_service, team_service

from ..research_project_agent_sessions import resolve_research_project_agent_session
from ..research_runtime.formal_write_runtime import get_write_store
from ..research_runtime.meeting_receipt_authority import (
    MeetingReceiptAuthorityError,
    build_meeting_receipt_authority,
)
from ..storage_durability import inter_process_lock
from .discussion import (
    DISCUSSION_MEETING_TYPE,
    DISCUSSION_SCOPE_AUTHORITY,
    discussion_input,
    save_discussion_hypothesis,
)
from .store import CampaignConflict, campaign_root, read_campaign


def open_discussion(team_id: str, run_id: str) -> dict:
    inputs = discussion_input(team_id, run_id)
    context = inputs["context"]
    project_id = context["researchProjectId"]
    campaign = read_campaign(team_id, project_id, context["optimizationCampaignId"])
    if not campaign.budget.authorized or not campaign.authorizedBy or campaign.budget.modelCostLimit <= 0:
        raise CampaignConflict("Discussion requires authorized model budget")
    run = get_write_store().get_run(run_id)
    snapshot = json.loads(run.input_snapshot_json)
    scope = parse_discussion_scope(inputs["discussionScope"])
    room_id = "room-operator-" + sha256_hex({"team": team_id, "run": run_id})[:24]
    lock = campaign_root(team_id, project_id) / "discussion" / room_id
    with inter_process_lock(lock):
        existing = chat_room_service.get_chat_room_detail(room_id)
        if existing is not None:
            config = existing.get("config") or {}
            if config.get("workflowRunId") != run_id or config.get("inputHash") != sha256_hex(inputs):
                raise CampaignConflict("Discussion room belongs to different frozen input")
            if existing.get("rounds"):
                return {"roomId": room_id, "roundId": existing["rounds"][0]["roundId"], "reused": True}
        # Use the native authority owner before creating sessions or turns.
        try:
            authority = build_meeting_receipt_authority(team_id=team_id,
                question_id=snapshot["questionId"], workflow_run_id=run_id,
                workflow_id=run.workflow_id, workflow_version_id=run.workflow_version_id,
                run_input=snapshot)
        except MeetingReceiptAuthorityError as exc:
            raise CampaignConflict(f"Operator discussion receipt authority is unavailable: {exc}") from exc
        if existing is None:
            members = team_service.get_team(team_id).get("members") or []
            # Use the team's existing research seats, retaining their order.
            participants = list({m["agentId"]: m for m in members if m.get("agentId")}.values())
            if len(participants) < 2:
                raise CampaignConflict("Team discussion requires at least two participants")
            sessions = []
            for member in participants:
                session = resolve_research_project_agent_session(team_id, research_project_id=project_id,
                    agent_id=member["agentId"], role_key=member.get("role") or "researcher",
                    role_label="算子优化讨论", created_from_task_id="operator-discussion:" + context["roundId"],
                    workflow_run_id=run_id, workflow_node_id="optimization_discussion", discussion_scope=scope)
                sessions.append(session["sessionId"])
            chat_room_service.create_chat_room(room_id=room_id, title="算子优化讨论",
                participant_session_ids=sessions, mode="round_robin", purpose="meeting",
                config={"teamId": team_id, "researchProjectId": project_id, "workflowRunId": run_id,
                    "inputHash": sha256_hex(inputs), "operatorRoundId": context["roundId"],
                    "scopeAuthority": DISCUSSION_SCOPE_AUTHORITY, "discussionScope": scope.to_dict(),
                    "scopeHash": scope.scope_hash,
                    "participantRoleSnapshot": [{"agentId": m["agentId"], "role": m.get("role", "researcher")} for m in participants],
                    "finalParticipantSessionId": sessions[-1]})
        topic = "进行一次算子优化讨论。最后一位参与者汇总一个主要假设，按 outputSchema 输出 JSON。\n" + json.dumps(inputs, ensure_ascii=False)
        result = chat_room_service.start_chat_room_round(room_id, topic, purpose="meeting",
            config={"teamId": team_id, "workflowRunId": run_id, "operatorRoundId": context["roundId"],
                "meetingType": DISCUSSION_MEETING_TYPE, "meetingRoundId": context["roundId"],
                "questionId": snapshot["questionId"]},
            background=True, lightweight_response=True, max_topic_lines=3,
            _model_invocation_receipt_authority=authority)
        return {"roomId": room_id, "roundId": result["roundId"], "reused": False}


def collect_discussion(team_id: str, run_id: str) -> dict:
    from ..research_runtime.model_invocation_receipt_registry import (
        question_model_invocation_receipts,
    )
    inputs = discussion_input(team_id, run_id)
    room_id = "room-operator-" + sha256_hex({"team": team_id, "run": run_id})[:24]
    room = chat_room_service.get_chat_room_detail(room_id)
    if room is None or (room.get("config") or {}).get("inputHash") != sha256_hex(inputs):
        raise CampaignConflict("Discussion room cannot be verified")
    if len(room.get("rounds") or []) != 1:
        raise CampaignConflict("Optimization discussion requires exactly one chat round")
    record = room["rounds"][0]
    messages = record.get("messages") or []
    expected = {p["sessionId"] for p in room.get("participants", [])}
    if (record.get("status") != "completed" or not messages or len(expected) < 2
        or {m.get("sessionId") for m in messages} != expected
        or any(m.get("status") != "completed" for m in messages)):
        raise CampaignConflict("All discussion participants must complete before result collection")
    snapshot = json.loads(get_write_store().get_run(run_id).input_snapshot_json)
    participants = {p["sessionId"]: p["participantId"] for p in room["participants"]}
    receipts, message_refs = [], []
    for message in messages:
        participant_id = participants[message["sessionId"]]
        if message.get("participantId") != participant_id:
            raise CampaignConflict("Discussion message differs from its frozen participant")
        turn_id = f"chat-room:{record['roundId']}:{participant_id}"
        scoped = question_model_invocation_receipts(team_id, question_id=snapshot["questionId"],
            workflow_run_id=run_id, session_id=message["sessionId"], turn_id=turn_id)
        scoped = [r for r in scoped if r.get("scope", {}).get("sessionId") == message["sessionId"]
            and r.get("scope", {}).get("turnId") == turn_id]
        if not any(r.get("status") == "succeeded" for r in scoped):
            raise CampaignConflict("Discussion lacks provider receipts for an exact participant Turn")
        receipts.extend(scoped)
        message_refs.append({"messageId": message["messageId"], "sessionId": message["sessionId"],
            "turnId": turn_id, "contentHash": sha256_hex(message["content"])})
    final_session = room["config"]["finalParticipantSessionId"]
    final_messages = [m for m in messages if m["sessionId"] == final_session]
    if len(final_messages) != 1:
        raise CampaignConflict("Discussion must contain exactly one final participant output")
    content = str(final_messages[0].get("content") or "").strip()
    if content.startswith("```json\n") and content.endswith("```"):
        content = content[8:-3].strip()
    hypothesis = json.loads(content)
    provenance = {"roomId": room_id, "chatRoundId": record["roundId"], "workflowRunId": run_id,
        "messageRefs": message_refs, "finalParticipantSessionId": final_session,
        "modelReceiptRefs": [{"receiptId": r["receiptId"], "sha256": sha256_hex(r)} for r in receipts],
        "costStatus": "unsettled", "costReason": "Provider estimates do not establish a currency-aware actual charge"}
    ref = save_discussion_hypothesis(team_id, run_id, hypothesis, provenance=provenance)
    return {"hypothesisRef": ref.model_dump(mode="json"), "discussion": provenance}
