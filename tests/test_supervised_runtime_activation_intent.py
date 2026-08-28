from core.launcher import lifecycle_action_dispatcher
from core.web.services import supervised_worktree_evolution_service as supervised_service


def test_supervised_activation_uses_approval_session_as_trusted_restart_requester(
    monkeypatch,
):
    captured: dict = {}

    def fake_submit(payload: dict, *, actor_context: dict) -> dict:
        captured["payload"] = payload
        captured["actorContext"] = actor_context
        return {
            "status": "accepted",
            "intentId": "intent-activation",
            "commandId": "command-activation",
        }

    monkeypatch.setattr(
        supervised_service.launcher_service,
        "submit_lifecycle_intent",
        fake_submit,
    )

    activation = supervised_service._queue_runtime_activation(
        {
            "runId": "swte-activation",
            "approvalConversationSessionId": "session-approval",
            "merge": {"commitSha": "a" * 40},
            "candidateWorktree": {"path": "C:/candidate"},
            "approvalDecision": {
                "decidedBy": {"actorId": "agent-auditor"},
            },
        }
    )

    assert activation["status"] == "activating"
    assert captured["actorContext"]["sourceSessionId"] == "session-approval"
    assert captured["actorContext"]["sourceRunId"] == "swte-activation"


def test_runtime_effect_dispatch_forwards_trusted_restart_requester(monkeypatch):
    captured: dict = {}

    def fake_submit(command_type: str, *, requested_by: str, args: dict) -> dict:
        captured["commandType"] = command_type
        captured["requestedBy"] = requested_by
        captured["args"] = args
        return {"commandId": "command-activation", "accepted": True}

    monkeypatch.setattr(
        lifecycle_action_dispatcher.command_queue,
        "submit_command",
        fake_submit,
    )

    result = lifecycle_action_dispatcher.dispatch_runtime_effect_intent(
        {
            "action": "restart_after_apply",
            "actorType": "supervised_approval_agent",
            "reason": "activate candidate",
            "sourceRunId": "swte-activation",
            "sourceSessionId": "session-approval",
            "sourceTaskId": "",
            "sourceWorktree": "C:/candidate",
            "intentId": "intent-activation",
        }
    )

    assert result["dispatched"] is True
    assert captured["commandType"] == "hot_restart_workbench"
    assert captured["args"]["allowActiveSessionId"] == "session-approval"
    assert captured["args"]["allowActiveRunId"] == "swte-activation"


def test_runtime_effect_dispatch_without_session_falls_back_to_plain_restart(monkeypatch):
    """Empty/blank sourceSessionId must not enqueue a doomed hot restart."""

    captured: dict = {}

    def fake_submit(command_type: str, *, requested_by: str, args: dict) -> dict:
        captured["commandType"] = command_type
        captured["args"] = args
        return {"commandId": "command-fallback", "accepted": True}

    monkeypatch.setattr(
        lifecycle_action_dispatcher.command_queue,
        "submit_command",
        fake_submit,
    )

    base_intent = {
        "action": "restart_after_apply",
        "actorType": "supervised_approval_agent",
        "reason": "activate candidate",
        "sourceRunId": "swte-activation",
        "sourceTaskId": "",
        "sourceWorktree": "C:/candidate",
        "intentId": "intent-activation",
    }

    result = lifecycle_action_dispatcher.dispatch_runtime_effect_intent(
        {**base_intent, "sourceSessionId": ""}
    )

    assert result["dispatched"] is True
    assert captured["commandType"] == "restart_workbench"

    result = lifecycle_action_dispatcher.dispatch_runtime_effect_intent(
        {**base_intent, "sourceSessionId": "   "}
    )

    assert result["dispatched"] is True
    assert captured["commandType"] == "restart_workbench"
