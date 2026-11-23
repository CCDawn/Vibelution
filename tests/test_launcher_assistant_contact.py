"""Closed contact receipts and exact native Session landing, without a model."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from core.web.services.local_assistant.contact import TaskContacts, owned_task, deliver_reply, valid_tool_call
from core.assistant_runtime.contact_observer import AssistantTaskContacts


@pytest.fixture
def task():
    return {"taskId": "task-1", "agentId": "agent-1", "sessionId": "session-1", "localAuthorityFingerprint": "fingerprint"}


def test_discovery_is_read_only_and_never_infers_online(tmp_path):
    store = TaskContacts(tmp_path / "contacts")
    assert store.describe("t")["availability"] == "offline_or_unobserved"
    assert not store.root.exists()


def test_stable_request_identity_and_explicit_delivery(tmp_path, task):
    store = TaskContacts(tmp_path)
    assert store.send(task, "r1", "hello")["state"] == "undelivered"
    assert store.send(task, "r1", "hello")["state"] == "undelivered"
    with pytest.raises(ValueError, match="conflict"):
        store.send(task, "r1", "different")
    with pytest.raises(ValueError, match="identity"):
        store.receipt({**task, "sessionId": "foreign"}, "r1")
    assert store.pending(task)["contacts"][0]["sourceSessionId"] == "session-1"
    assert store.describe("task-1")["availability"] == "observed_online"
    assert store.delivery(task, "r1", "delivery_unknown")["changed"] is True
    assert store.delivery(task, "r1", "delivery_unknown")["changed"] is False
    assert TaskContacts(tmp_path).receipt(task, "r1")["state"] == "delivery_unknown"
    assert store.delivery(task, "r1", "received")["state"] == "received"


@pytest.mark.parametrize("request_id,content", [("../escape", "hello"), ("ok", "x" * 1001), ("ok", " "), ("ok", "hello\x00")])
def test_message_bounds_fail_closed(tmp_path, task, request_id, content):
    with pytest.raises(ValueError):
        TaskContacts(tmp_path).send(task, request_id, content)


def test_reply_reservation_is_not_replayed_after_unknown(tmp_path, task):
    store = TaskContacts(tmp_path)
    store.send(task, "r", "question")
    store.delivery(task, "r", "delivery_unknown")
    store.delivery(task, "r", "received")
    calls = []
    def uncertain(*args):
        calls.append(args)
        raise RuntimeError("lost native acknowledgement")
    with pytest.raises(RuntimeError):
        store.reply(task, "r", "answer", uncertain)
    assert TaskContacts(tmp_path).reply(task, "r", "answer", uncertain)["state"] == "reply_unknown"
    assert len(calls) == 1 and calls[0] == ("agent-1", "session-1", "r", "answer")
    with pytest.raises(ValueError, match="conflict"):
        store.reply(task, "r", "new answer", uncertain)


def test_original_capability_and_local_owner_are_both_required(task):
    checks = []
    service = SimpleNamespace(_require_gateway_enabled=lambda: checks.append("authority"),
        _owned_task=lambda owner, tid: task if owner == "original" and tid == "task-1" else (_ for _ in ()).throw(ValueError("owner")),
        _require_cleanup_ownership=lambda row: checks.append(row["localAuthorityFingerprint"]))
    assert owned_task(service, "original", "task-1") == task
    assert checks == ["authority", "fingerprint"]
    with pytest.raises(ValueError, match="owner"):
        owned_task(service, "foreign", "task-1")


def test_tool_runtime_uses_native_binding_not_claimed_metadata(monkeypatch):
    from core.web.services import agent_directory_service as directory
    from core.web.services.local_assistant import consent
    from tools.launcher_assistant_contact_tools import launcher_assistant_contact_tool
    seen = []
    monkeypatch.setattr(directory, "current_agent_runtime", lambda **kw: seen.append(kw) or {"taskId": "forged"})
    monkeypatch.setattr(consent, "_task_runtime", lambda runtime: None)
    result = json.loads(launcher_assistant_contact_tool("send", "request", "hello"))
    assert result["availability"] == "not_authorized" and result["onlineStatus"] == "unknown"
    assert seen and all(row == {"bound_only": True} for row in seen)


def test_contact_consent_is_task_bound_and_strict(monkeypatch, tmp_path):
    from core.web.services.local_assistant import consent
    runtime = {"runtimeToolSource": "launcher_assistant_task:read_only"}
    monkeypatch.setattr(consent, "_native_launcher", lambda _: False)
    monkeypatch.setattr(consent, "_task_runtime", lambda _: {"taskId": "t", "workspace": tmp_path, "profile": "read_only"})
    assert consent.local_approval_policy(runtime, "launcher_assistant_contact_tool",
        {"operation": "send", "request_id": "r", "content": "question"}, ("always", "execute"), "request_approval")[0] is None
    for args in ({"operation": "send", "request_id": "r", "content": "x" * 1001},
                 {"operation": "send", "request_id": "r", "content": "ok", "target_session": "foreign"},
                 {"operation": "execute"}):
        with pytest.raises(consent.LocalTaskScopeError):
            consent.local_approval_policy(runtime, "launcher_assistant_contact_tool", args, None, "full_access")
    assert valid_tool_call({}) and valid_tool_call({"operation": "receipt", "request_id": "r"})


def test_directory_contact_is_separate_from_native_agent_addressing(monkeypatch):
    from tools import agent_directory_tools as directory
    from tools import launcher_assistant_contact_tools as contact
    monkeypatch.setattr(directory, "_load_agents", lambda: [])
    monkeypatch.setattr(directory, "_load_sessions", lambda: [])
    monkeypatch.setattr(contact, "contact_card", lambda: {"contact": "launcher_assistant", "authorized": False})
    result = json.loads(directory.agent_directory_tool())
    assert result["agents"] == [] and result["totalAgents"] == 0
    assert result["contacts"] == [{"contact": "launcher_assistant", "authorized": False}]


@pytest.mark.asyncio
async def test_authenticated_pull_delivery_and_reply_keep_original_target(tmp_path, task):
    store = TaskContacts(tmp_path)
    store.send(task, "r", "question")
    native_deliveries = []
    class Client:
        async def task_contacts(self, tid, request_id="", operation="list", content=""):
            assert tid == "task-1"
            if operation == "list":
                return store.pending(task)
            if operation == "reply":
                return store.reply(task, request_id, content,
                    lambda *args: native_deliveries.append(args) or {"historyStatus": "appended"})
            return store.delivery(task, request_id, operation)
    class Dispatch:
        def _read(self, did):
            assert did == "d1"
            return {"projectId": "p1", "nativeTaskId": "task-1"}
        def list_dispatches(self):
            return [{"dispatchId": "d1", "nativeTaskId": "task-1"}]
        async def _call(self, pid, operation):
            assert pid == "p1"
            await asyncio.sleep(0)
            return await operation(Client())
    received = []
    owner = AssistantTaskContacts(Dispatch(), "pa", "pa-session",
        deliver=lambda row: received.append(row) or {"historyStatus": "appended"})
    await asyncio.gather(owner.refresh(), owner.refresh())
    assert len(received) == 1 and received[0]["sourceSessionId"] == "session-1"
    assert (await owner.reply("d1", "r", "answer"))["state"] == "replied"
    assert native_deliveries == [("agent-1", "session-1", "r", "answer")]
    assert (await owner.reply("d1", "r", "answer"))["state"] == "replied"
    assert len(native_deliveries) == 1


def test_sdk_refuses_nonlocal_task_and_preserves_original_capability(monkeypatch, tmp_path):
    from core.assistant_runtime.local_project_client import LocalAssistantBackendClient
    from core.external_agent.backend_client import BackendClientError
    client = object.__new__(LocalAssistantBackendClient)
    captured = []
    async def request(*args, **kwargs):
        captured.append((args, kwargs))
        return {"state": "received"}
    async def capability(_):
        return "original-capability", "local"
    monkeypatch.setattr(client, "_cleanup_capability", capability)
    monkeypatch.setattr(client, "_request_json", request)
    asyncio.run(client.task_contacts("task-1", request_id="r", operation="received"))
    assert captured[0][1]["task_capability"] == "original-capability"
    assert captured[0][0] == ("POST", "/api/v1/external-agent/tasks/task-1/contacts/r/delivery")
    async def foreign(_):
        return "foreign", "external"
    monkeypatch.setattr(client, "_cleanup_capability", foreign)
    with pytest.raises(BackendClientError, match="original Launcher task"):
        asyncio.run(client.task_contacts("task-1"))


def test_reply_rejects_missing_or_foreign_original_session(monkeypatch):
    from core.web.services import session_service
    monkeypatch.setattr(session_service, "get_session_detail", lambda *a, **kw: {"agentId": "foreign"})
    with pytest.raises(ValueError, match="target_unavailable"):
        deliver_reply("agent-1", "session-1", "r", "hello")


def test_contact_actions_have_closed_schema_and_original_task_scope(monkeypatch):
    from core.assistant_runtime import actions
    from core.assistant_runtime.management_scopes import plan_project_scopes
    monkeypatch.setattr(actions, "_binding", (object(), object(), None))
    schema = actions.execute_action("describe", {"action": "contact_reply"})["parameters"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"dispatch_id", "request_id", "content"}
    assert plan_project_scopes(["contact_requests", "contact_reply"]) == {"contact_requests": [], "contact_reply": []}


def test_private_http_requires_launcher_and_original_task_and_rejects_target_override(monkeypatch, tmp_path, task):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.web.routes import local_assistant_tasks as route
    from core.web.services.external_agent.service import ExternalAgentAccessError
    from core.web.services.local_assistant import contact
    store = TaskContacts(tmp_path / "contacts")
    store.send(task, "r", "question")
    def owned(owner, task_id):
        if owner != "original" or task_id != task["taskId"]:
            raise ExternalAgentAccessError("not found", code="TASK_NOT_FOUND")
        return task
    service = SimpleNamespace(project_root=tmp_path, _require_gateway_enabled=lambda: None,
        _owned_task=owned, _require_cleanup_ownership=lambda _: None)
    monkeypatch.setattr(route.external_agent, "_require_control", lambda _: None)
    monkeypatch.setattr(route, "verify_launcher_authority", lambda token: token == "launcher")
    monkeypatch.setattr(route, "local_service", lambda: service)
    monkeypatch.setattr(contact, "contacts_for_project", lambda _: store)
    delivered = []
    monkeypatch.setattr(contact, "deliver_reply", lambda *args: delivered.append(args) or {"historyStatus": "appended"})
    app = FastAPI()
    app.include_router(route.router, prefix="/api")
    client = TestClient(app)
    base = "/api/local-assistant/v1/external-agent/tasks/task-1/contacts"
    assert client.get(base).status_code == 403
    headers = {"X-Vibelution-Management-Subject": "launcher-local", "X-Vibelution-Management-Capability": "launcher",
               route.external_agent.TASK_CAPABILITY_HEADER: "foreign"}
    assert client.get(base, headers=headers).status_code == 404
    headers[route.external_agent.TASK_CAPABILITY_HEADER] = "original"
    page = client.get(base, headers=headers)
    assert page.status_code == 200 and page.json()["contacts"][0]["state"] == "undelivered"
    for state in ("delivery_unknown", "received"):
        assert client.post(base + "/r/delivery", headers=headers, json={"state": state}).status_code == 200
    assert client.post(base + "/r/reply", headers=headers, json={"content": "answer", "target_session": "foreign"}).status_code == 422
    reply = client.post(base + "/r/reply", headers=headers, json={"content": "answer"})
    assert reply.status_code == 200 and reply.json()["state"] == "replied"
    assert delivered == [("agent-1", "session-1", "r", "answer")]


def test_question_and_reply_land_in_exact_native_sessions(tmp_path, monkeypatch):
    from core.agent_kernel import service as kernel
    from core.infrastructure import developer_sandbox, native_runtime
    from core.web.services import agent_directory_service as directory, session_service as sessions
    from core.assistant_runtime import native
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "data"))
    for module in (kernel, directory, sessions, developer_sandbox):
        monkeypatch.setattr(module, "PROJECT_ROOT", project)
    worker = directory.create_agent_instance(display_name="Contact worker")
    assistant = directory.create_agent_instance(display_name="Contact assistant")
    unrelated = directory.create_agent_instance(display_name="Unrelated")
    worker_session = sessions.ensure_agent_direct_session(agent_id=worker["agentId"])["id"]
    assistant_session = sessions.ensure_agent_direct_session(agent_id=assistant["agentId"])["id"]
    unrelated_session = sessions.ensure_agent_direct_session(agent_id=unrelated["agentId"])["id"]
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    monkeypatch.setattr(native, "_STARTED", True)
    monkeypatch.setattr(native, "_QUIESCING", False)
    monkeypatch.setattr(native, "_AGENT_ID", assistant["agentId"])
    monkeypatch.setattr(native, "_SESSION_ID", assistant_session)
    task = {"taskId": "native-task", "agentId": worker["agentId"], "sessionId": worker_session,
            "localAuthorityFingerprint": "isolated-native-proof"}
    store = TaskContacts(tmp_path / "envelopes")
    store.send(task, "native-request", "CONTACT_QUESTION_NATIVE_731")
    request = store.pending(task)["contacts"][0]
    owner = AssistantTaskContacts(None, assistant["agentId"], assistant_session)
    store.delivery(task, "native-request", "delivery_unknown")
    delivered = owner._native_delivery({**request, "projectId": "isolated-project", "dispatchId": "isolated-dispatch"})
    assert delivered["targetSessionId"] == assistant_session and delivered["historyStatus"] == "appended"
    store.delivery(task, "native-request", "received")
    assert "CONTACT_QUESTION_NATIVE_731" in json.dumps(sessions.get_session_detail(assistant_session), ensure_ascii=False)
    receipt = store.reply(task, "native-request", "CONTACT_REPLY_NATIVE_812", deliver_reply)
    assert receipt["state"] == "replied"
    worker_detail = json.dumps(sessions.get_session_detail(worker_session), ensure_ascii=False)
    other_detail = json.dumps(sessions.get_session_detail(unrelated_session), ensure_ascii=False)
    assert "CONTACT_REPLY_NATIVE_812" in worker_detail
    assert "CONTACT_REPLY_NATIVE_812" not in other_detail and "CONTACT_QUESTION_NATIVE_731" not in other_detail
