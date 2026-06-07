import base64
import json

import pytest
from fastapi.testclient import TestClient

import scripts.computer_use_bridge as computer_use_bridge
from core.infrastructure.tool_executor import ToolExecutor
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import agent_directory_service
from core.web.services import computer_use_service
from core.web.services import tool_registry_service as registry
from tools.computer_use_tools import computer_use_session_tool, computer_use_task_tool


ORIGINAL_RECORD_EVENT = computer_use_service._record_event


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/l9Q9WQAAAABJRU5ErkJggg=="
)


@pytest.fixture()
def computer_use_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(computer_use_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(computer_use_service, "SESSION_ROOT", tmp_path / "workspace" / "computer_use_sessions")
    monkeypatch.setattr(computer_use_service, "_record_event", lambda *args, **kwargs: None)
    return tmp_path


def test_computer_use_tool_blocks_when_disabled(computer_use_tmp, monkeypatch):
    monkeypatch.delenv("VIBELUTION_COMPUTER_USE_ENABLED", raising=False)

    result = json.loads(
        computer_use_task_tool(
            task="Open example and take a screenshot",
            target_url="https://example.com",
            allowed_domains="example.com",
        )
    )

    assert result["status"] == "blocked"
    assert result["sessionId"].startswith("cu-")
    assert result["needsConfirmation"] is False
    assert "disabled" in result["summary"].lower()


def test_computer_use_service_requires_browser_mode(computer_use_tmp):
    with pytest.raises(computer_use_service.ComputerUseError):
        computer_use_service.start_computer_use_task(
            task="try desktop",
            target_url="https://example.com",
            allowed_domains="example.com",
            mode="desktop",
        )


def test_computer_use_service_derives_allowed_domain_and_saves_screenshot(computer_use_tmp, monkeypatch):
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_ENABLED", "1")
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_BASE_URL", "https://computer-use.invalid")

    def fake_call(request, *, session_id):
        assert request["allowedDomains"] == ["example.com"]
        return {
            "status": "completed",
            "summary": "Screenshot captured.",
            "steps": [{"action": "open", "summary": "Opened example.com", "status": "completed"}],
            "screenshot_b64": base64.b64encode(PNG_BYTES).decode("ascii"),
        }

    monkeypatch.setattr(computer_use_service, "_call_open_computer_use", fake_call)

    result = computer_use_service.start_computer_use_task(
        task="Open example and take a screenshot",
        target_url="https://example.com",
        allowed_domains="",
    )

    assert result["status"] == "completed"
    assert result["allowedDomains"] == ["example.com"]
    assert result["screenshotUrl"].startswith(f"/api/computer-use/sessions/{result['sessionId']}/screenshots/")
    screenshot_id = result["screenshotUrl"].rsplit("/", 1)[-1]
    assert computer_use_service.computer_use_screenshot_path(result["sessionId"], screenshot_id).read_bytes() == PNG_BYTES


def test_computer_use_service_forwards_actions_and_redacts_public_text(computer_use_tmp, monkeypatch):
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_ENABLED", "1")
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_BASE_URL", "https://computer-use.invalid")

    def fake_call(request, *, session_id):
        assert request["actions"] == [
            {"action": "fill", "selector": "#q", "text": "secret query"},
            {"action": "press", "key": "Enter"},
        ]
        return {
            "status": "completed",
            "summary": "Actions completed.",
            "steps": [{"action": "fill", "summary": "Filled search box", "status": "completed"}],
        }

    monkeypatch.setattr(computer_use_service, "_call_open_computer_use", fake_call)

    result = computer_use_service.start_computer_use_task(
        task="Search example",
        target_url="https://example.com",
        allowed_domains="example.com",
        actions='fill selector=#q text="secret query"\npress key=Enter',
    )

    assert result["status"] == "completed"
    assert result["actionCount"] == 2
    assert result["requestedActions"][0]["action"] == "fill"
    assert result["requestedActions"][0]["textLength"] == len("secret query")
    assert "secret query" not in json.dumps(result, ensure_ascii=False)


def test_computer_use_task_tool_forwards_timeout_seconds(computer_use_tmp, monkeypatch):
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_ENABLED", "1")
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_BASE_URL", "https://computer-use.invalid")

    calls = []

    def fake_call(request, *, session_id):
        calls.append(request)
        return {
            "status": "completed",
            "summary": "Opened page.",
            "steps": [{"action": "open", "summary": "Opened page", "status": "completed"}],
        }

    monkeypatch.setattr(computer_use_service, "_call_open_computer_use", fake_call)

    result = json.loads(
        computer_use_task_tool(
            task="Open example",
            target_url="https://example.com",
            allowed_domains="example.com",
            timeout_seconds=7,
        )
    )

    assert result["status"] == "completed"
    assert calls[0]["timeoutSeconds"] == 7


def test_computer_use_service_blocks_cross_domain_action(computer_use_tmp, monkeypatch):
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_ENABLED", "1")
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_BASE_URL", "https://computer-use.invalid")

    with pytest.raises(computer_use_service.ComputerUseError, match="outside allowed_domains"):
        computer_use_service.start_computer_use_task(
            task="Navigate elsewhere",
            target_url="https://example.com",
            allowed_domains="example.com",
            actions=[{"action": "navigate", "url": "https://not-example.com"}],
        )


def test_computer_use_service_blocks_local_and_private_targets(computer_use_tmp, monkeypatch):
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_ENABLED", "1")

    for url in (
        "http://127.0.0.1:8000/api/control-token",
        "http://localhost:8000/api/control-token",
        "http://10.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data",
    ):
        with pytest.raises(computer_use_service.ComputerUseError, match="public internet"):
            computer_use_service.start_computer_use_task(
                task="Open internal URL",
                target_url=url,
                allowed_domains="",
            )


def test_computer_use_service_blocks_local_and_private_allowed_domains(computer_use_tmp, monkeypatch):
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_ENABLED", "1")

    for domain in ("localhost", "localhost:8000", "127.0.0.1", "127.0.0.1:8000", "10.0.0.1", "10.0.0.1:443", "169.254.169.254", "*.example.com"):
        with pytest.raises(computer_use_service.ComputerUseError, match="allowed_domains"):
            computer_use_service.start_computer_use_task(
                task="Open example",
                target_url="https://example.com",
                allowed_domains=domain,
            )


def test_computer_use_service_sends_bridge_token_only_to_loopback_bridge(computer_use_tmp, monkeypatch):
    import requests

    token_path = computer_use_tmp / ".runtime" / "computer-use" / "bridge.token"
    token_path.parent.mkdir(parents=True)
    token_path.write_text("local-bridge-token", encoding="utf-8")
    monkeypatch.setattr(computer_use_service, "BRIDGE_TOKEN_PATH", token_path)
    monkeypatch.delenv("VIBELUTION_COMPUTER_USE_BRIDGE_TOKEN", raising=False)
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_BASE_URL", "http://127.0.0.1:8765")
    captured = {}

    class FakeResponse:
        status_code = 200
        text = "{}"

        def json(self):
            return {"status": "completed", "summary": "ok"}

    def fake_post(endpoint, *, headers, json, timeout):
        captured["endpoint"] = endpoint
        captured["headers"] = headers
        return FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)

    computer_use_service._call_open_computer_use(
        {
            "task": "Open example",
            "targetUrl": "https://example.com",
            "allowedDomains": ["example.com"],
            "actions": [],
            "mode": "browser",
            "maxSteps": 1,
            "requireConfirmation": True,
            "timeoutSeconds": 5,
        },
        session_id="cu-test",
    )

    assert captured["endpoint"] == "http://127.0.0.1:8765/v1/predict"
    assert captured["headers"][computer_use_service.BRIDGE_TOKEN_HEADER] == "local-bridge-token"


def test_computer_use_service_does_not_send_bridge_token_to_remote_provider(computer_use_tmp, monkeypatch):
    import requests

    token_path = computer_use_tmp / ".runtime" / "computer-use" / "bridge.token"
    token_path.parent.mkdir(parents=True)
    token_path.write_text("local-bridge-token", encoding="utf-8")
    monkeypatch.setattr(computer_use_service, "BRIDGE_TOKEN_PATH", token_path)
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_BRIDGE_TOKEN", "env-bridge-token")
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_BASE_URL", "https://computer-use.invalid")
    captured = {}

    class FakeResponse:
        status_code = 200
        text = "{}"

        def json(self):
            return {"status": "completed", "summary": "ok"}

    def fake_post(endpoint, *, headers, json, timeout):
        captured["headers"] = headers
        return FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)

    computer_use_service._call_open_computer_use(
        {
            "task": "Open example",
            "targetUrl": "https://example.com",
            "allowedDomains": ["example.com"],
            "actions": [],
            "mode": "browser",
            "maxSteps": 1,
            "requireConfirmation": True,
            "timeoutSeconds": 5,
        },
        session_id="cu-test",
    )

    assert computer_use_service.BRIDGE_TOKEN_HEADER not in captured["headers"]


def test_computer_use_service_pauses_high_risk_explicit_action_before_provider(computer_use_tmp, monkeypatch):
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_ENABLED", "1")
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_BASE_URL", "https://computer-use.invalid")

    called = False

    def fake_call(request, *, session_id):
        nonlocal called
        called = True
        return {"status": "completed", "summary": "Should not run."}

    monkeypatch.setattr(computer_use_service, "_call_open_computer_use", fake_call)

    result = computer_use_service.start_computer_use_task(
        task="Submit a form",
        target_url="https://example.com/form",
        allowed_domains="example.com",
        actions=[{"action": "click", "selector": "#submit"}],
    )

    assert called is False
    assert result["status"] == "need_confirmation"
    assert result["needsConfirmation"] is True
    assert result["steps"][0]["requiresConfirmation"] is True
    cancelled = computer_use_service.cancel_computer_use_session(result["sessionId"], reason="test_cancel")
    assert cancelled["status"] == "cancelled"
    assert "pendingExecution" not in computer_use_service._load_session(result["sessionId"])


def test_computer_use_service_forces_confirmation_even_when_opted_out(computer_use_tmp, monkeypatch):
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_ENABLED", "1")
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_BASE_URL", "https://computer-use.invalid")

    called = False

    def fake_call(request, *, session_id):
        nonlocal called
        called = True
        return {"status": "completed", "summary": "Should not run."}

    monkeypatch.setattr(computer_use_service, "_call_open_computer_use", fake_call)

    result = computer_use_service.start_computer_use_task(
        task="Submit a form",
        target_url="https://example.com/form",
        allowed_domains="example.com",
        actions=[{"action": "click", "selector": "#submit"}],
        require_confirmation=False,
    )

    assert called is False
    assert result["status"] == "need_confirmation"
    assert result["needsConfirmation"] is True


def test_computer_use_service_confirm_resumes_high_risk_explicit_action_and_redacts_text(computer_use_tmp, monkeypatch):
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_ENABLED", "1")
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_BASE_URL", "https://computer-use.invalid")

    calls = []

    def fake_call(request, *, session_id):
        calls.append(request)
        assert request["requireConfirmation"] is False
        assert request["actions"] == [
            {"action": "fill", "selector": "#login", "text": "secret password"},
            {"action": "click", "selector": "#submit"},
        ]
        return {
            "status": "completed",
            "summary": "Confirmed actions completed.",
            "steps": [{"action": "click", "summary": "Submitted login form", "status": "completed"}],
            "screenshot_b64": base64.b64encode(PNG_BYTES).decode("ascii"),
        }

    monkeypatch.setattr(computer_use_service, "_call_open_computer_use", fake_call)

    started = computer_use_service.start_computer_use_task(
        task="Login to example",
        target_url="https://example.com/login",
        allowed_domains="example.com",
        actions=[
            {"action": "fill", "selector": "#login", "text": "secret password"},
            {"action": "click", "selector": "#submit"},
        ],
    )

    assert calls == []
    assert started["status"] == "need_confirmation"
    assert started["requestedActions"][0]["textLength"] == len("secret password")
    assert "secret password" not in json.dumps(started, ensure_ascii=False)

    confirmed = computer_use_service.confirm_computer_use_session(started["sessionId"], confirmation="approved_by_test")

    assert len(calls) == 1
    assert confirmed["status"] == "completed"
    assert confirmed["needsConfirmation"] is False
    assert confirmed["screenshotUrl"].startswith(f"/api/computer-use/sessions/{started['sessionId']}/screenshots/")
    assert [step.get("status") for step in confirmed["steps"]][-1] == "completed"
    assert "secret password" not in json.dumps(confirmed, ensure_ascii=False)
    saved = computer_use_service._load_session(started["sessionId"])
    assert "pendingExecution" not in saved


def test_computer_use_service_rejects_duplicate_confirmation_while_resuming(computer_use_tmp, monkeypatch):
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_ENABLED", "1")
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_BASE_URL", "https://computer-use.invalid")

    nested_error = None

    def fake_call(request, *, session_id):
        nonlocal nested_error
        if nested_error is None:
            with pytest.raises(computer_use_service.ComputerUseError) as exc_info:
                computer_use_service.confirm_computer_use_session(session_id, confirmation="duplicate_confirm")
            nested_error = str(exc_info.value)
        return {
            "status": "completed",
            "summary": "Confirmed actions completed.",
            "steps": [{"action": "click", "summary": "Clicked submit", "status": "completed"}],
        }

    monkeypatch.setattr(computer_use_service, "_call_open_computer_use", fake_call)

    started = computer_use_service.start_computer_use_task(
        task="Submit example",
        target_url="https://example.com/form",
        allowed_domains="example.com",
        actions=[{"action": "click", "selector": "#submit"}],
    )
    confirmed = computer_use_service.confirm_computer_use_session(started["sessionId"])

    assert confirmed["status"] == "completed"
    assert "already resuming" in str(nested_error)


def test_computer_use_service_rejects_confirmation_when_lock_exists(computer_use_tmp, monkeypatch):
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_ENABLED", "1")
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_BASE_URL", "https://computer-use.invalid")
    monkeypatch.setattr(
        computer_use_service,
        "_call_open_computer_use",
        lambda request, *, session_id: {
            "status": "completed",
            "summary": "Confirmed actions completed.",
            "steps": [{"action": "click", "summary": "Clicked submit", "status": "completed"}],
        },
    )

    started = computer_use_service.start_computer_use_task(
        task="Submit example",
        target_url="https://example.com/form",
        allowed_domains="example.com",
        actions=[{"action": "click", "selector": "#submit"}],
    )
    lock_path = computer_use_service._session_lock_path(started["sessionId"])
    lock_path.write_text("locked", encoding="utf-8")

    with pytest.raises(computer_use_service.ComputerUseError, match="already resuming"):
        computer_use_service.confirm_computer_use_session(started["sessionId"])


def test_computer_use_service_recovers_stale_resuming_session(computer_use_tmp, monkeypatch):
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_ENABLED", "1")
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_BASE_URL", "https://computer-use.invalid")

    calls = []

    def fake_call(request, *, session_id):
        calls.append(request)
        return {
            "status": "completed",
            "summary": "Confirmed actions completed.",
            "steps": [{"action": "click", "summary": "Clicked submit", "status": "completed"}],
        }

    monkeypatch.setattr(computer_use_service, "_call_open_computer_use", fake_call)

    started = computer_use_service.start_computer_use_task(
        task="Submit example",
        target_url="https://example.com/form",
        allowed_domains="example.com",
        actions=[{"action": "click", "selector": "#submit"}],
    )
    payload = computer_use_service._load_session(started["sessionId"])
    payload["status"] = "resuming"
    payload["needsConfirmation"] = False
    payload["resumingStartedAt"] = "2000-01-01T00:00:00+00:00"
    computer_use_service._save_session(payload)

    confirmed = computer_use_service.confirm_computer_use_session(started["sessionId"])

    assert confirmed["status"] == "completed"
    assert len(calls) == 1


def test_computer_use_session_tool_reads_confirms_and_cancels_sessions(computer_use_tmp, monkeypatch):
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_ENABLED", "1")
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_BASE_URL", "https://computer-use.invalid")

    calls = []

    def fake_call(request, *, session_id):
        calls.append(request)
        if request.get("actions") == [{"action": "wait", "ms": 10}]:
            return {
                "status": "running",
                "summary": "Session tool task is still running.",
                "steps": [{"action": "wait", "summary": "Waiting", "status": "running"}],
            }
        return {
            "status": "completed",
            "summary": "Session tool confirmed actions.",
            "steps": [{"action": "click", "summary": "Clicked submit", "status": "completed"}],
        }

    monkeypatch.setattr(computer_use_service, "_call_open_computer_use", fake_call)

    pending = computer_use_service.start_computer_use_task(
        task="Submit from session tool",
        target_url="https://example.com/form",
        allowed_domains="example.com",
        actions=[{"action": "click", "selector": "#submit"}],
    )
    read_result = json.loads(computer_use_session_tool(session_id=pending["sessionId"], action="get"))
    confirmed = json.loads(
        computer_use_session_tool(
            session_id=pending["sessionId"],
            action="confirm",
            confirmation="approved_by_session_tool",
        )
    )
    running = computer_use_service.start_computer_use_task(
        task="Open example and wait",
        target_url="https://example.com",
        allowed_domains="example.com",
        actions=[{"action": "wait", "ms": 10}],
    )
    cancelled = json.loads(
        computer_use_session_tool(
            session_id=running["sessionId"],
            action="cancel",
            reason="cancelled_by_session_tool_test",
        )
    )

    assert read_result["status"] == "need_confirmation"
    assert confirmed["status"] == "completed"
    assert calls and calls[0]["requireConfirmation"] is False
    assert cancelled["status"] == "cancelled"


def test_computer_use_service_confirm_resumes_provider_confirmation_token(computer_use_tmp, monkeypatch):
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_ENABLED", "1")
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_BASE_URL", "https://computer-use.invalid")

    calls = []

    def fake_call(request, *, session_id):
        calls.append(request)
        if len(calls) == 1:
            return {
                "status": "need_confirmation",
                "summary": "Provider paused before checkout.",
                "steps": [{"action": "pay", "summary": "Review checkout", "status": "ready"}],
                "continuation_token": "resume-token-1",
                "provider_state": {"cursor": "checkout"},
            }
        assert request["requireConfirmation"] is False
        assert request["confirmation"] == "approved_provider_resume"
        assert request["providerContinuation"]["continuationToken"] == "resume-token-1"
        assert request["providerContinuation"]["providerState"] == {"cursor": "checkout"}
        return {
            "status": "completed",
            "summary": "Provider resumed after confirmation.",
            "steps": [{"action": "pay", "summary": "Checkout confirmed", "status": "completed"}],
            "screenshot_b64": base64.b64encode(PNG_BYTES).decode("ascii"),
        }

    monkeypatch.setattr(computer_use_service, "_call_open_computer_use", fake_call)

    result = computer_use_service.start_computer_use_task(
        task="Checkout on example",
        target_url="https://example.com/cart",
        allowed_domains="example.com",
    )
    stored = computer_use_service._load_session(result["sessionId"])
    confirmed = computer_use_service.confirm_computer_use_session(
        result["sessionId"],
        confirmation="approved_provider_resume",
    )

    assert result["status"] == "need_confirmation"
    assert stored["pendingExecution"]["kind"] == "provider_confirmation"
    assert "resume-token-1" not in json.dumps(result, ensure_ascii=False)
    assert len(calls) == 2
    assert confirmed["status"] == "completed"
    assert confirmed["needsConfirmation"] is False
    assert confirmed["summary"] == "Provider resumed after confirmation."
    assert confirmed["screenshotUrl"].startswith(f"/api/computer-use/sessions/{result['sessionId']}/screenshots/")
    assert "pendingExecution" not in computer_use_service._load_session(result["sessionId"])


def test_computer_use_service_provider_confirmation_can_pause_more_than_once(computer_use_tmp, monkeypatch):
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_ENABLED", "1")
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_BASE_URL", "https://computer-use.invalid")

    calls = []

    def fake_call(request, *, session_id):
        calls.append(request)
        if len(calls) == 1:
            return {
                "status": "need_confirmation",
                "summary": "Provider paused before checkout.",
                "steps": [{"action": "pay", "summary": "Review checkout", "status": "ready"}],
                "continuation_token": "resume-token-1",
            }
        if len(calls) == 2:
            assert request["confirmation"] == "approved_first_resume"
            assert request["providerContinuation"]["continuationToken"] == "resume-token-1"
            return {
                "status": "need_confirmation",
                "summary": "Provider paused for final review.",
                "steps": [{"action": "pay", "summary": "Final review required", "status": "ready"}],
                "continuation_token": "resume-token-2",
            }
        assert request["confirmation"] == "approved_second_resume"
        assert request["providerContinuation"]["continuationToken"] == "resume-token-2"
        return {
            "status": "completed",
            "summary": "Provider completed after second confirmation.",
            "steps": [{"action": "pay", "summary": "Checkout confirmed", "status": "completed"}],
        }

    monkeypatch.setattr(computer_use_service, "_call_open_computer_use", fake_call)

    result = computer_use_service.start_computer_use_task(
        task="Checkout on example",
        target_url="https://example.com/cart",
        allowed_domains="example.com",
    )
    first_confirm = computer_use_service.confirm_computer_use_session(
        result["sessionId"],
        confirmation="approved_first_resume",
    )
    stored_after_first_confirm = computer_use_service._load_session(result["sessionId"])
    second_confirm = computer_use_service.confirm_computer_use_session(
        result["sessionId"],
        confirmation="approved_second_resume",
    )

    assert result["status"] == "need_confirmation"
    assert first_confirm["status"] == "need_confirmation"
    assert first_confirm["needsConfirmation"] is True
    assert stored_after_first_confirm["pendingExecution"]["kind"] == "provider_confirmation"
    assert stored_after_first_confirm["pendingExecution"]["continuation"]["continuationToken"] == "resume-token-2"
    assert "resume-token-1" not in json.dumps(first_confirm, ensure_ascii=False)
    assert "resume-token-2" not in json.dumps(first_confirm, ensure_ascii=False)
    assert len(calls) == 3
    assert second_confirm["status"] == "completed"
    assert second_confirm["needsConfirmation"] is False
    assert "pendingExecution" not in computer_use_service._load_session(result["sessionId"])


def test_computer_use_service_requires_confirmation_for_high_risk_step(computer_use_tmp, monkeypatch):
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_ENABLED", "1")
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_BASE_URL", "https://computer-use.invalid")

    monkeypatch.setattr(
        computer_use_service,
        "_call_open_computer_use",
        lambda request, *, session_id: {
            "status": "completed",
            "summary": "Ready to submit.",
            "steps": [{"action": "submit", "summary": "Submit contact form", "status": "ready"}],
        },
    )

    result = computer_use_service.start_computer_use_task(
        task="Fill contact form but wait before submit",
        target_url="https://example.com/contact",
        allowed_domains="example.com",
    )

    assert result["status"] == "need_confirmation"
    assert result["needsConfirmation"] is True
    with pytest.raises(computer_use_service.ComputerUseError, match="cannot resume"):
        computer_use_service.confirm_computer_use_session(result["sessionId"])
    stored = computer_use_service._load_session(result["sessionId"])
    assert stored["status"] == "blocked"
    assert stored["needsConfirmation"] is False


def test_computer_use_public_payload_and_events_redact_target_url_query(computer_use_tmp, monkeypatch):
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_ENABLED", "1")
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_BASE_URL", "https://computer-use.invalid")

    events = []

    from core.web.services import runtime_scene_service

    monkeypatch.setattr(
        runtime_scene_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append(kwargs.get("fields") or {}),
    )
    monkeypatch.setattr(computer_use_service, "_record_event", ORIGINAL_RECORD_EVENT)
    monkeypatch.setattr(
        computer_use_service,
        "_call_open_computer_use",
        lambda request, *, session_id: {
            "status": "completed",
            "summary": "Opened page.",
            "steps": [{"action": "open", "summary": "Opened page", "status": "completed"}],
        },
    )

    result = computer_use_service.start_computer_use_task(
        task="Open tokenized URL",
        target_url="https://example.com/path?token=secret#frag",
        allowed_domains="example.com",
    )

    assert result["targetUrl"] == "https://example.com/path"
    assert "secret" not in json.dumps(result, ensure_ascii=False)
    assert events
    assert all("secret" not in json.dumps(event, ensure_ascii=False) for event in events)


def test_computer_use_routes_confirm_resumes_pending_actions(computer_use_tmp, monkeypatch):
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_ENABLED", "1")
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_BASE_URL", "https://computer-use.invalid")

    calls = []

    def fake_call(request, *, session_id):
        calls.append(request)
        return {
            "status": "completed",
            "summary": "Confirmed route action completed.",
            "steps": [{"action": "click", "summary": "Clicked submit", "status": "completed"}],
            "screenshot_b64": base64.b64encode(PNG_BYTES).decode("ascii"),
        }

    monkeypatch.setattr(computer_use_service, "_call_open_computer_use", fake_call)
    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

    create_response = client.post(
        "/api/computer-use/tasks",
        json={
            "task": "Submit example form",
            "targetUrl": "https://example.com/form",
            "allowedDomains": ["example.com"],
            "actions": [{"action": "click", "selector": "#submit"}],
        },
    )
    assert create_response.status_code == 200, create_response.text
    created = create_response.json()

    confirm_response = client.post(
        f"/api/computer-use/sessions/{created['sessionId']}/confirm",
        json={"confirmation": "approved_from_route_test"},
    )
    confirmed = confirm_response.json()

    assert calls and calls[0]["requireConfirmation"] is False
    assert confirm_response.status_code == 200, confirm_response.text
    assert confirmed["status"] == "completed"
    assert confirmed["needsConfirmation"] is False
    assert confirmed["summary"] == "Confirmed route action completed."
    assert confirmed["screenshotUrl"].startswith(f"/api/computer-use/sessions/{created['sessionId']}/screenshots/")


def test_computer_use_routes_forward_timeout_seconds(computer_use_tmp, monkeypatch):
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_ENABLED", "1")
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_BASE_URL", "https://computer-use.invalid")

    calls = []

    def fake_call(request, *, session_id):
        calls.append(request)
        return {
            "status": "completed",
            "summary": "Opened page.",
            "steps": [{"action": "open", "summary": "Opened page", "status": "completed"}],
        }

    monkeypatch.setattr(computer_use_service, "_call_open_computer_use", fake_call)
    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

    response = client.post(
        "/api/computer-use/tasks",
        json={
            "task": "Open example",
            "targetUrl": "https://example.com",
            "allowedDomains": ["example.com"],
            "timeoutSeconds": 9,
        },
    )

    assert response.status_code == 200, response.text
    assert calls[0]["timeoutSeconds"] == 9


def test_computer_use_routes_create_read_cancel_and_screenshot(computer_use_tmp, monkeypatch):
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_ENABLED", "1")
    monkeypatch.setenv("VIBELUTION_COMPUTER_USE_BASE_URL", "https://computer-use.invalid")
    monkeypatch.setattr(
        computer_use_service,
        "_call_open_computer_use",
        lambda request, *, session_id: {
            "status": "running",
            "summary": "Task is running.",
            "steps": [{"action": "open", "summary": "Opened page"}],
            "screenshot_b64": base64.b64encode(PNG_BYTES).decode("ascii"),
        },
    )
    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

    create_response = client.post(
        "/api/computer-use/tasks",
        json={
            "task": "Open example",
            "targetUrl": "https://example.com",
            "allowedDomains": [],
            "actions": [{"action": "wait", "ms": 10}],
        },
    )
    assert create_response.status_code == 200, create_response.text
    created = create_response.json()

    read_response = client.get(f"/api/computer-use/sessions/{created['sessionId']}")
    cancel_response = client.post(f"/api/computer-use/sessions/{created['sessionId']}/cancel", json={"reason": "test"})
    image_response = client.get(created["screenshotUrl"])

    assert read_response.status_code == 200
    assert read_response.json()["status"] == "running"
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"
    assert image_response.status_code == 200
    assert image_response.content == PNG_BYTES
    assert created["actionCount"] == 1
    assert created["requestedActions"][0]["action"] == "wait"


def test_computer_use_bridge_blocks_unsupported_action_without_launching_edge():
    result = computer_use_bridge.run_browser_task(
        {
            "task": "Do unsupported action",
            "target_url": "https://example.com",
            "allowed_domains": ["example.com"],
            "actions": [{"action": "drag"}],
        },
        edge=computer_use_bridge.Path("C:/missing/msedge.exe"),
        timeout=1,
    )

    assert result["status"] == "blocked"
    assert "Unsupported browser action" in result["summary"]


def test_computer_use_bridge_blocks_malformed_action_without_launching_edge():
    result = computer_use_bridge.run_browser_task(
        {
            "task": "Malformed click",
            "target_url": "https://example.com",
            "allowed_domains": ["example.com"],
            "actions": [{"action": "click"}],
        },
        edge=computer_use_bridge.Path("C:/missing/msedge.exe"),
        timeout=1,
    )

    assert result["status"] == "blocked"
    assert "requires selector" in result["summary"]


def test_computer_use_bridge_forces_high_risk_confirmation_when_opted_out():
    result = computer_use_bridge.run_browser_task(
        {
            "task": "Submit example form",
            "target_url": "https://example.com/form",
            "allowed_domains": ["example.com"],
            "actions": [{"action": "click", "selector": "#submit"}],
            "require_confirmation": False,
        },
        edge=computer_use_bridge.Path("C:/missing/msedge.exe"),
        timeout=1,
    )

    assert result["status"] == "need_confirmation"
    assert result["needsConfirmation"] is True


def test_computer_use_bridge_blocks_local_and_private_targets():
    for url in (
        "http://127.0.0.1:8000/api/control-token",
        "http://localhost:8000/api/control-token",
        "http://10.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data",
    ):
        result = computer_use_bridge.run_browser_task(
            {
                "task": "Open internal URL",
                "target_url": url,
                "allowed_domains": [],
            },
            edge=computer_use_bridge.Path("C:/missing/msedge.exe"),
            timeout=1,
        )
        assert result["status"] == "blocked"
        assert result["error"] == "NETWORK_BOUNDARY_BLOCKED"


def test_computer_use_bridge_blocks_local_and_wildcard_allowed_domains():
    for domain in ("localhost:8000", "127.0.0.1:8000", "10.0.0.1:443", "*.example.com"):
        result = computer_use_bridge.run_browser_task(
            {
                "task": "Open example",
                "target_url": "https://example.com",
                "allowed_domains": [domain],
            },
            edge=computer_use_bridge.Path("C:/missing/msedge.exe"),
            timeout=1,
        )
        assert result["status"] == "blocked"
        assert result["error"] == "NETWORK_BOUNDARY_BLOCKED"


def test_computer_use_bridge_health_reports_auth_support(monkeypatch):
    captured = {}
    handler = computer_use_bridge.Handler.__new__(computer_use_bridge.Handler)
    handler.path = "/health"
    handler.edge_path = computer_use_bridge.Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe")
    monkeypatch.setattr(handler, "_json", lambda payload, status=200: captured.update({"payload": payload, "status": status}))

    handler.do_GET()

    assert captured["status"] == 200
    assert captured["payload"]["status"] == "ok"
    assert captured["payload"]["bridgeAuth"] is True


def test_computer_use_bridge_cleanup_retries_locked_temp_dir(monkeypatch, tmp_path):
    calls = []

    def fake_rmtree(path, ignore_errors=False):
        calls.append((path, ignore_errors))
        if len(calls) == 1:
            raise PermissionError("locked")

    monkeypatch.setattr(computer_use_bridge.shutil, "rmtree", fake_rmtree)
    monkeypatch.setattr(computer_use_bridge.time, "sleep", lambda seconds: None)

    computer_use_bridge.cleanup_temp_dir(tmp_path)

    assert calls == [(tmp_path, False), (tmp_path, False)]


def test_computer_use_tool_requires_explicit_tool_policy(computer_use_tmp, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", computer_use_tmp)
    monkeypatch.setattr(agent_directory_service, "record_runtime_scene_event", lambda *args, **kwargs: None)
    agent = agent_directory_service.create_agent_instance(
        display_name="Computer Use Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
    )

    with agent_directory_service.active_agent_runtime(agent["agentId"]):
        result, _ = ToolExecutor().execute(
            "computer_use_task_tool",
            {"task": "Open example", "target_url": "https://example.com", "allowed_domains": "example.com"},
        )

    assert "ToolPolicy.allowedTools" in result


def test_computer_use_session_tool_requires_explicit_tool_policy(computer_use_tmp, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", computer_use_tmp)
    monkeypatch.setattr(agent_directory_service, "record_runtime_scene_event", lambda *args, **kwargs: None)
    agent = agent_directory_service.create_agent_instance(
        display_name="Computer Use Session Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
    )

    with agent_directory_service.active_agent_runtime(agent["agentId"]):
        result, _ = ToolExecutor().execute(
            "computer_use_session_tool",
            {"session_id": "cu-test", "action": "get"},
        )

    assert "ToolPolicy.allowedTools" in result


def test_tool_registry_marks_computer_use_as_high_risk_explicit_allow(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")

    payload = registry.get_tool_registry()
    tool = next(item for item in payload["tools"] if item["name"] == "computer_use_task_tool")
    session_tool = next(item for item in payload["tools"] if item["name"] == "computer_use_session_tool")
    operations = next(item for item in payload["toolBundles"] if item["bundleId"] == "operations")

    assert tool["category"] == "task_runtime"
    assert tool["permissionTier"] == "high"
    assert {"computer_control", "network_access", "external_automation"}.issubset(set(tool["riskTags"]))
    assert tool["permissionPolicy"]["requiresExplicitAllow"] is True
    assert session_tool["category"] == "task_runtime"
    assert session_tool["permissionTier"] == "high"
    assert {"computer_control", "external_automation", "session_state_write"}.issubset(set(session_tool["riskTags"]))
    assert session_tool["permissionPolicy"]["requiresExplicitAllow"] is True
    assert "computer_use_task_tool" in operations["toolNames"]
    assert "computer_use_session_tool" in operations["toolNames"]
