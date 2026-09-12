from dataclasses import replace
import json

from core.web.services.team_workflow.research_runtime.completion_dependency import (
    CompletionDependencyPending, bind_completion_resume, defer_completion,
    receipt_delivery_state, wake_receipt_completion,
    wake_meeting_completion,
)
from core.web.services.team_workflow.research_runtime.domain_ports import AgentTaskHandle
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS
from tests.test_research_workflow_agent_anchor import _agent_action, _seed, _leased_outbox, _outbox_row
from tests.test_completion_dependency_recovery import _delivery


def test_each_meeting_speaker_delivery_can_resume_original_completion(tmp_path):
    h = CommandHarness(tmp_path / "ledger.sqlite")
    try:
        h.seed_run(status="running")
        action = _agent_action()
        _seed(h, action, action.node_id)
        h.store.submit(lambda u: u.repository.update_attempt_status(
            action.node_run_id, "running", FIXED_NOW_MS), force_flush=True).result()
        participants = tuple({"sessionId": f"session-{i}", "participantId": str(i),
            "turnId": f"chat-room:meeting-1:{i}", "taskId": f"task-{i}"} for i in (1, 2))
        handle = AgentTaskHandle("session-2", 1, "task-2", "chat-room:meeting-1:2",
            meeting_room_id="room-1", meeting_round_id="meeting-1", meeting_participants=participants)
        receipts = []
        for i, participant in enumerate(participants):
            row, receipt = _delivery(action, "pending")
            receipt["scope"].update(participant)
            row = replace(row, action_id=f"delivery-{i}", idempotency_key=f"receipt-{i}",
                payload_json=json.dumps({"kind": "challenge_model_invocation_receipt_persist", "receipt": receipt}))
            h.store.submit(lambda u, row=row: u.repository.insert_outbox(row), force_flush=True).result()
            receipts.append(receipt)
        statuses, _ = h.store.submit(lambda u: receipt_delivery_state(u, action, handle)).result()
        assert statuses == {"pending"}
        outbox = _leased_outbox(h, action, attempt_count=1)
        error = CompletionDependencyPending("meeting receipts pending", snapshot={"terminalStatus": "completed"})
        bind_completion_resume(error, action, handle, {"reservationId": "res-1"})
        defer_completion(h.store, outbox=outbox, action=action, error=error,
            owner="adapter-worker", now_ms=FIXED_NOW_MS + 1)
        for receipt in receipts:
            h.store.submit(lambda u, receipt=receipt: wake_receipt_completion(
                u, receipt=receipt, now_ms=FIXED_NOW_MS + 2), force_flush=True).result()
            assert _outbox_row(h, outbox.action_id).available_at_ms == FIXED_NOW_MS + 2
    finally:
        h.close()


def test_running_meeting_waits_without_receipts_and_exact_terminal_notification_wakes(tmp_path):
    h = CommandHarness(tmp_path / "meeting.sqlite")
    try:
        h.seed_run(status="running")
        action = _agent_action()
        _seed(h, action, action.node_id)
        h.store.submit(lambda u: u.repository.update_attempt_status(
            action.node_run_id, "running", FIXED_NOW_MS), force_flush=True).result()
        participants = tuple({"sessionId": f"s{i}", "participantId": str(i),
            "turnId": f"chat-room:r1:{i}", "taskId": f"task{i}"} for i in (1, 2))
        handle = AgentTaskHandle("s2", 1, "task2", "chat-room:r1:2",
            meeting_room_id="room1", meeting_round_id="r1", meeting_participants=participants)
        outbox = _leased_outbox(h, action, attempt_count=1)
        error = CompletionDependencyPending("speakers running",
            snapshot={"terminalStatus": "running", "meetingRunning": True})
        bind_completion_resume(error, action, handle, {"reservationId": "res1"})
        defer_completion(h.store, outbox=outbox, action=action, error=error,
            owner="adapter-worker", now_ms=FIXED_NOW_MS)
        assert _outbox_row(h, outbox.action_id).status == "pending"
        assert _outbox_row(h, outbox.action_id).available_at_ms == FIXED_NOW_MS + 5000
        for room_id in ("wrong-room", "room1", "room1"):
            h.store.submit(lambda u: wake_meeting_completion(u,
                run_id=action.run_id, node_run_id=action.node_run_id, room_id=room_id,
                round_id="r1", now_ms=FIXED_NOW_MS + 1), force_flush=True).result()
            assert _outbox_row(h, outbox.action_id).available_at_ms == FIXED_NOW_MS + (5000 if room_id == "wrong-room" else 1)
    finally:
        h.close()
