"""Native meeting task adapter for the independent operator workflow."""
from __future__ import annotations

from core.web.services import chat_room_service
from ..research_runtime.artifact_readback_registry import build_canonical_ref
from ..research_runtime.completion_dependency import CompletionDependencyPending, _receipt_handles
from ..research_runtime.domain_ports import AgentTaskHandle, AgentTurnResult
from .discussion_runtime import open_discussion, collect_discussion, _receipt_rows
from .model_budget import settle_model_budget
from .store import CampaignConflict


def create_discussion_task(store, action) -> AgentTaskHandle:
    run = store.get_run(action.run_id)
    opened = open_discussion(run.team_id, action.run_id, node_run_id=action.node_run_id)
    room = chat_room_service.get_chat_room_detail(opened["roomId"])
    authority = room["config"]["operatorDiscussionAuthority"]
    seats = {p["agentId"]: p for p in room["participants"]}
    participants = tuple({
        "sessionId": seats[s["agentId"]]["sessionId"],
        "participantId": seats[s["agentId"]]["participantId"],
        "taskId": f"operator-speaker:{opened['roundId']}:{seats[s['agentId']]['participantId']}",
        "turnId": f"chat-room:{opened['roundId']}:{seats[s['agentId']]['participantId']}",
    } for s in authority["participants"])
    final = participants[-1]
    handle = AgentTaskHandle(final["sessionId"], authority["nodeAttempt"],
        final["taskId"], final["turnId"], meeting_room_id=opened["roomId"],
        meeting_round_id=opened["roundId"], meeting_participants=participants)
    _receipt_handles(handle)
    return handle


def execute_discussion_task(store, action, handle) -> AgentTurnResult:
    participants = _receipt_handles(handle)
    room = chat_room_service.get_chat_room_detail(handle.meeting_room_id)
    if room is None:
        raise CampaignConflict("Operator discussion room is unavailable")
    authority = room["config"]["operatorDiscussionAuthority"]
    if authority["workflowRunId"] != action.run_id or authority["nodeRunId"] != action.node_run_id:
        raise CampaignConflict("Operator discussion task belongs to another attempt")
    rounds = [r for r in room["rounds"] if r["roundId"] == handle.meeting_round_id]
    if len(rounds) != 1:
        raise CampaignConflict("Operator discussion task round is unavailable")
    status = rounds[0]["status"]
    if status in chat_room_service.RUNNING_ROUND_STATUSES:
        raise CompletionDependencyPending("Operator discussion speakers are still executing",
            snapshot={"terminalStatus": status, "meetingRunning": True}, handle=handle)
    reservation = {"reservationId": "reservation-" + action.node_run_id,
        "runId": action.run_id, "nodeRunId": action.node_run_id}
    if status != "completed":
        settle_model_budget(store, reservation=reservation)
        raise CampaignConflict(f"Operator discussion ended with status {status}")
    for participant in participants:
        receipts = _receipt_rows(authority["teamId"], question_id=authority["questionId"],
            run_id=action.run_id, session_id=participant["sessionId"], turn_id=participant["turnId"])
        if not any(r.get("status") in {"succeeded", "retried"} for r in receipts):
            raise CompletionDependencyPending("Operator discussion speaker receipts are not delivered",
                snapshot={"terminalStatus": status}, handle=handle)
    budget = settle_model_budget(store, reservation=reservation)
    result = collect_discussion(authority["teamId"], action.run_id,
        node_run_id=action.node_run_id, budget_receipt=budget)
    refs = tuple({"kind": ref["kind"], "sha256": ref["sha256"], "canonicalRef": build_canonical_ref(
        kind=ref["kind"], team_id=authority["teamId"], authority_run_id=action.run_id,
        content_hash=ref["sha256"])}
        for ref in (result["discussionRef"], result["hypothesisRef"]) if ref is not None)
    return AgentTurnResult(refs, handle, usage={"discussionStatus": result["status"],
        "costStatus": budget["costStatus"]})
