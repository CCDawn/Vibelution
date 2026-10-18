from __future__ import annotations

import copy
import threading
import time

import pytest

from core.web.services import personal_assistant_computer_service as service

OWNER = ("assistant", "session", "turn")


@pytest.fixture
def computer(monkeypatch):
    monkeypatch.setattr(service, "_grant", None)
    monkeypatch.setattr(service, "_pending", None)
    monkeypatch.setattr(service, "_active", None)
    monkeypatch.setattr(service, "_quarantine", None)
    monkeypatch.setattr(service, "_epoch", 0)
    monkeypatch.setattr(service, "_status", "idle")
    monkeypatch.setattr(service, "_selection", {})
    monkeypatch.setattr(service, "_observations", {})
    monkeypatch.setattr(service, "_event", lambda *args: None)
    monkeypatch.setattr(service, "_canonical", lambda: {"agentId": OWNER[0], "directSessionId": OWNER[1]})
    monkeypatch.setattr(service, "_configuration", lambda _: (1, "config"))
    monkeypatch.setattr(service, "_window_alive", lambda window: True)
    monkeypatch.setattr(service.adapter, "driver_binary", lambda: "pinned-driver")
    monkeypatch.setattr(service.adapter, "process_identity", lambda pid: (123.0, r"C:\Apps\notepad.exe"))
    tick = [1]
    monkeypatch.setattr(service.adapter, "last_input_tick", lambda: tick[0])
    from core.web.services import personal_assistant_computer_vision
    monkeypatch.setattr(personal_assistant_computer_vision, "describe_window", lambda *args: "窗口中有文本编辑器。")
    calls = []
    snapshot = {"fingerprint": "before", "incomplete": False, "images": [{"type": "image"}],
                "elements": [{"role": "Edit", "label": "内容", "value": "", "actions": ["set_value"],
                              "element_token": "current-token"}]}

    class Connection:
        def __init__(self, checker):
            self.checker = checker

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def windows(self):
            return [{"pid": 10, "window_id": 20, "title": "Test", "app_name": "Notepad"}]

        def snapshot(self, window, **kwargs):
            return copy.deepcopy(snapshot)

        def act(self, window, action, element, text):
            assert not self.checker()
            calls.append((action, text, element))
            if action == "set_value":
                snapshot["elements"][0]["value"] = text
                snapshot["fingerprint"] = "after"
                return text

    monkeypatch.setattr(service.adapter, "Connection", Connection)
    windows = service.list_windows()["windows"]
    state = service.grant_window(windows[0]["selectionId"], True)
    return state["grantId"], snapshot, calls, tick


def observe():
    result = service.execute(OWNER, cancel_checker=lambda: "")
    assert result["ok"] and result["modality"] == "window_screenshot_and_uia"
    return result["observationId"]


def pending_action(token, text="hello", **kwargs):
    result = []
    worker = threading.Thread(target=lambda: result.append(service.execute(
        OWNER, action="set_value", observation_id=token, element_id="0", text=text, cancel_checker=lambda: "", **kwargs)))
    worker.start()
    deadline = time.monotonic() + 2
    while service.get_state()["pending"] is None:
        assert worker.is_alive() and time.monotonic() < deadline
        time.sleep(.005)
    return worker, result, service.get_state()["pending"]["id"]


@pytest.mark.parametrize("text", ["hello", ""])
def test_every_action_waits_for_operator_and_one_shot_confirm(computer, text):
    grant_id, _, calls, _ = computer
    token = observe()
    worker, result, confirmation = pending_action(token, text=text)
    assert calls == []
    assert "内容" in service.get_state()["pending"]["targetLabel"]
    pending_text = service.get_state()["pending"]["text"]
    service.confirm(grant_id, confirmation, True)
    worker.join(2)
    assert not worker.is_alive()
    # Clearing a field is a text operation too, not a missing text parameter.
    assert pending_text == text
    assert result[0]["verified"] is True
    assert calls[0][:2] == ("set_value", text)
    with pytest.raises(ValueError):
        service.confirm(grant_id, confirmation, True)
    assert not service.execute(OWNER, action="set_value", observation_id=token, element_id="0", text="again", cancel_checker=lambda: "")["ok"]
    assert len(calls) == 1


@pytest.mark.parametrize("control", ["pause", "takeover", "end"])
def test_pause_takeover_end_cancel_pending_without_input(computer, control):
    grant_id, _, calls, _ = computer
    worker, result, confirmation = pending_action(observe())
    service.control(grant_id, control)
    worker.join(2)
    assert not worker.is_alive() and result[0]["status"] == "cancelled"
    assert calls == []
    with pytest.raises(ValueError):
        service.confirm(grant_id, confirmation, True)


def test_cancel_and_timeout_never_send_input(computer, monkeypatch):
    grant_id, _, calls, _ = computer
    worker, result, confirmation = pending_action(observe())
    service.confirm(grant_id, confirmation, False)
    worker.join(2)
    assert result[0]["status"] == "blocked" and not calls
    service.control(grant_id, "resume")
    monkeypatch.setattr(service, "CONFIRM_SECONDS", .01)
    result = service.execute(OWNER, action="click", observation_id=observe(), element_id="0", cancel_checker=lambda: "")
    assert result["status"] == "blocked" and not calls


def test_changed_window_after_confirmation_is_rejected(computer):
    grant_id, snapshot, calls, _ = computer
    token = observe()
    worker, result, confirmation = pending_action(token)
    snapshot["fingerprint"] = "human-changed"
    service.confirm(grant_id, confirmation, True)
    worker.join(2)
    assert result[0]["status"] == "blocked" and not calls


@pytest.mark.parametrize("owner", [("foreign", "session", "turn"), ("assistant", "foreign", "turn"), ("assistant", "session", ""), ()])
def test_noncanonical_identity_cannot_observe(computer, owner):
    assert not service.execute(owner, cancel_checker=lambda: "")["ok"]


def test_resume_requires_fresh_observation(computer):
    grant_id, _, calls, _ = computer
    old = observe()
    service.control(grant_id, "takeover")
    service.control(grant_id, "return")
    assert not service.execute(OWNER, action="click", observation_id=old, element_id="0", cancel_checker=lambda: "")["ok"]
    assert not calls
    observe()


def test_window_identity_change_ends_grant(computer, monkeypatch):
    monkeypatch.setattr(service, "_window_alive", lambda _: False)
    state = service.get_state()
    assert state["status"] == "ended" and state["grantId"] is None
    assert not service.execute(OWNER, cancel_checker=lambda: "")["ok"]


def test_assistant_policy_or_model_change_revokes_existing_grant(computer, monkeypatch):
    monkeypatch.setattr(service, "_configuration", lambda _: (2, "new-config"))
    assert service.get_state()["grantId"] is None
    assert not service.execute(OWNER, cancel_checker=lambda: "")["ok"]


def test_detected_human_input_retires_old_observation(computer):
    _, _, _, tick = computer
    token = observe()
    check = service._checker(OWNER, service._epoch, lambda: "", tick[0])
    tick[0] += 1
    assert check()
    assert service.get_state()["status"] == "manual"
    assert token not in service._observations


@pytest.mark.parametrize("arguments", [
    {"action": "press_key", "text": "ctrl+s"}, {"action": "scroll", "text": "invalid"},
    {"action": "launch"}, {"action": "type_text", "text": "x" * 2001},
])
def test_unsupported_action_input_is_refused_before_pending(computer, arguments):
    result = service.execute(OWNER, observation_id=observe(), element_id="0", cancel_checker=lambda: "", **arguments)
    assert not result["ok"] and service.get_state()["pending"] is None


def test_operator_cannot_bind_unlisted_or_replaced_window(computer, monkeypatch):
    with pytest.raises(ValueError):
        service.grant_window("model-invented-window", True)
    row = service.list_windows()["windows"][0]
    with pytest.raises(ValueError):
        service.grant_window(row["selectionId"], False)
    monkeypatch.setattr(service, "_window_alive", lambda _: False)
    with pytest.raises(ValueError):
        service.grant_window(row["selectionId"], True)


def test_incomplete_snapshot_cannot_act(computer):
    grant_id, snapshot, calls, _ = computer
    snapshot["incomplete"] = True
    worker, result, confirmation = pending_action(observe())
    service.confirm(grant_id, confirmation, True)
    worker.join(2)
    assert not result[0]["ok"] and not calls


def test_cancel_decision_cannot_be_changed_before_worker_consumes(computer):
    grant_id, _, calls, _ = computer
    worker, result, confirmation = pending_action(observe())
    # Hold the same control lock so the worker cannot consume the first event.
    with service._lock:
        service.confirm(grant_id, confirmation, False)
        with pytest.raises(ValueError):
            service.confirm(grant_id, confirmation, True)
    worker.join(2)
    assert not calls and not result[0]["ok"]


def test_failed_end_retains_cleanup_handle_and_blocks_new_grant(computer, monkeypatch):
    grant_id, _, _, _ = computer

    class Unretired:
        def __exit__(self, *args):
            raise OSError("still live")

    monkeypatch.setattr(service, "_active", Unretired())
    state = service.control(grant_id, "end")
    assert state["grantId"] == grant_id and state["status"] == "error"
    assert not service.execute(OWNER, cancel_checker=lambda: "")["ok"]
    service._quarantine.__class__.__exit__ = lambda *args: None
    monkeypatch.setattr(service, "_active", None)
    assert service.control(grant_id, "end")["grantId"] is None


def test_runtime_evidence_never_records_content(monkeypatch):
    from core.web.services import runtime_scene_service
    calls = []
    monkeypatch.setattr(runtime_scene_service, "record_runtime_scene_event_quietly", lambda *args, **kwargs: calls.append((args, kwargs)))
    service._event("grant", "accepted")
    assert calls[0][0] == ("personal_assistant", "computer", "computer.grant")
    assert calls[0][1]["fields"] == {"action": "grant", "scope": "single_window"}
