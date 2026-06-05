import base64
import json

import pytest
from fastapi.testclient import TestClient

from core.infrastructure.tool_executor import ToolExecutor
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import agent_directory_service
from core.web.services import computer_use_service
from core.web.services import tool_registry_service as registry
from tools.computer_use_tools import computer_use_task_tool


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
    confirmed = computer_use_service.confirm_computer_use_session(result["sessionId"])

    assert result["status"] == "need_confirmation"
    assert result["needsConfirmation"] is True
    assert confirmed["status"] == "completed"
    assert confirmed["needsConfirmation"] is False


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
        json={"task": "Open example", "targetUrl": "https://example.com", "allowedDomains": []},
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


def test_tool_registry_marks_computer_use_as_high_risk_explicit_allow(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")

    payload = registry.get_tool_registry()
    tool = next(item for item in payload["tools"] if item["name"] == "computer_use_task_tool")
    operations = next(item for item in payload["toolBundles"] if item["bundleId"] == "operations")

    assert tool["category"] == "task_runtime"
    assert tool["permissionTier"] == "high"
    assert {"computer_control", "network_access", "external_automation"}.issubset(set(tool["riskTags"]))
    assert tool["permissionPolicy"]["requiresExplicitAllow"] is True
    assert "computer_use_task_tool" in operations["toolNames"]
