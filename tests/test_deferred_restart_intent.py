"""Deferred workbench restart intents are fulfilled from the idle branch."""

from __future__ import annotations

from core.runtime_manager import daemon as daemon_module


def _daemon_class():
    for value in vars(daemon_module).values():
        if isinstance(value, type) and hasattr(value, "_handle_command"):
            return value
    raise AssertionError("runtime manager daemon class not found")


def test_deferred_restart_intent_is_handed_off_and_completed(monkeypatch) -> None:
    claimed = [
        {
            "intentId": "intent_test_1",
            "target": "workbench_restart",
            "reason": "1 active work item(s) block lifecycle commands.",
            "requestedBy": "electron_main",
            "sourceCommandId": "cmd-42",
            "payload": {"action": "restart_workbench"},
        }
    ]
    completed: dict[str, object] = {}
    handled: list[dict[str, object]] = []

    monkeypatch.setattr(
        daemon_module,
        "claim_next_restart_intent",
        lambda **kwargs: claimed.pop(0) if claimed else None,
    )

    def fake_complete(intent_id: str, **kwargs: object) -> dict[str, object]:
        completed["intentId"] = intent_id
        completed.update(kwargs)
        return {}

    monkeypatch.setattr(daemon_module, "complete_restart_intent", fake_complete)

    instance = object.__new__(_daemon_class())

    def fake_handle(payload: dict[str, object]) -> dict[str, object]:
        handled.append(payload)
        return {"ok": True, "message": "handed off"}

    instance._handle_command = fake_handle  # type: ignore[method-assign]
    instance._process_deferred_restart_intent()

    assert handled, "deferred intent must be handed off through a lifecycle command"
    assert handled[0]["type"] == "restart_workbench"
    args = handled[0]["args"]
    assert isinstance(args, dict)
    assert args["deferredIntentId"] == "intent_test_1"
    assert completed["intentId"] == "intent_test_1"
    assert completed["status"] == "completed"


def test_unsupported_deferred_action_fails_closed(monkeypatch) -> None:
    claimed = [
        {
            "intentId": "intent_test_2",
            "target": "workbench_restart",
            "payload": {"action": "something_else"},
        }
    ]
    completed: dict[str, object] = {}
    monkeypatch.setattr(
        daemon_module,
        "claim_next_restart_intent",
        lambda **kwargs: claimed.pop(0) if claimed else None,
    )

    def fake_complete(intent_id: str, **kwargs: object) -> dict[str, object]:
        completed["intentId"] = intent_id
        completed.update(kwargs)
        return {}

    monkeypatch.setattr(daemon_module, "complete_restart_intent", fake_complete)
    instance = object.__new__(_daemon_class())
    instance._handle_command = lambda payload: (_ for _ in ()).throw(  # type: ignore[method-assign]
        AssertionError("unsupported actions must not reach the lifecycle command handler")
    )
    instance._process_deferred_restart_intent()

    assert completed["intentId"] == "intent_test_2"
    assert completed["status"] == "failed"
