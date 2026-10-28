"""Main-only short-lived transport; native lifecycle remains Electron's owner."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from core.assistant_runtime.actions import bind_actions, execute_action, unbind_actions
from core.assistant_runtime.host import create_app


TOKEN = "private-main-control-test-generation-token"
HEADERS = {"Authorization": "Bearer " + TOKEN}
REQUEST = {"projectId": "p:main", "operation": "restart", "requestId": "request-1"}


class Dispatch:
    def __init__(self):
        self.projects = ["p:main"]

    def project_ids(self):
        return tuple(self.projects)

    async def heartbeat(self):
        pass


class Native:
    def bootstrap(self):
        return {"assistant": {"agentId": "a", "directSessionId": "s"}}

    def shutdown(self):
        pass


def broker(service=None, **kwargs):
    from core.assistant_runtime.main_control import MainControlBroker
    kwargs.setdefault("claim_seconds", 0.02)
    return MainControlBroker((service or Dispatch()).project_ids, **kwargs)


def result(request=REQUEST, **changes):
    return {"schemaVersion": 1, **request, "state": "completed", "code": "accepted", "accepted": True, **changes}


@pytest.mark.anyio
async def test_timeout_and_late_settle_do_not_replay_a_claimed_command():
    owner = broker(timeout_seconds=0.02)
    task = asyncio.create_task(owner.invoke("project_lifecycle", REQUEST))
    wire = await owner.claim()
    assert wire["schemaVersion"] == 1
    delivery = wire["request"]
    assert delivery.keys() == {"deliveryId", "action", "projectId", "operation", "requestId"}
    assert len(delivery["deliveryId"]) == 32 and set(delivery["deliveryId"]) <= set("0123456789abcdef")
    assert await task == {
        "schemaVersion": 1, **REQUEST, "state": "unknown", "code": "control_unavailable"}
    assert owner.settle(delivery["deliveryId"], result()) is False
    assert await owner.claim() == {"schemaVersion": 1, "request": None}
    owner.close()


@pytest.mark.anyio
async def test_governed_action_and_project_permissions_precede_queue_admission():
    service = Dispatch()
    owner = broker(service)
    bind_actions(service, asyncio.get_running_loop(), main_control=owner)
    try:
        args = {"project_id": "p:main", "operation": "restart", "request_id": "request-1"}
        denied = await asyncio.to_thread(execute_action, "project_lifecycle", args, runtime={"agentId": "a"})
        assert denied == {"ok": False, "status": "approval_required", "action": "project_lifecycle", "tool": "personal_assistant_manage_tool"}
        assert await owner.claim() == {"schemaVersion": 1, "request": None}
        with pytest.raises(ValueError, match="authorized"):
            await owner.invoke("project_lifecycle", {**REQUEST, "projectId": "p:other"})
        assert await owner.claim() == {"schemaVersion": 1, "request": None}
    finally:
        owner.close()
        unbind_actions(service)


@pytest.mark.anyio
async def test_history_import_uses_approved_native_turn_and_never_accepts_model_paths():
    service = Dispatch()
    owner = broker(service, claim_seconds=2)
    bind_actions(service, asyncio.get_running_loop(), main_control=owner)
    args = {"project_id": "p:main", "preview_id": "a" * 64}
    runtime = {"agentId": "a", "sessionId": "s", "turnId": "turn-1"}
    try:
        denied = await asyncio.to_thread(execute_action, "history_import", args, runtime=runtime)
        assert denied["status"] == "approval_required"
        with pytest.raises(ValueError):
            await asyncio.to_thread(execute_action, "history_import", {**args, "approved": True}, runtime=runtime, governed=True)
        task = asyncio.create_task(asyncio.to_thread(execute_action, "history_import", args, runtime=runtime, governed=True))
        wire = (await owner.claim())["request"]
        assert wire["action"] == "history_import" and wire["turnId"] == "turn-1"
        assert wire["previewId"] == args["preview_id"] and 0 < wire["timeoutMs"] <= 120000
        result = {"schemaVersion": 1, "projectId": "p:main", "previewId": args["preview_id"],
                  "state": "published", "code": "imported", "historyCount": 1, "readyForCutover": False}
        assert owner.settle(wire["deliveryId"], result)
        assert await task == result
    finally:
        owner.close()
        unbind_actions(service)


@pytest.mark.anyio
async def test_initial_migration_requires_negotiated_capability_and_governed_closed_parameters(monkeypatch):
    from core.assistant_runtime.main_control import initial_migration_id
    service = Dispatch()
    disabled = broker(service)
    bind_actions(service, asyncio.get_running_loop(), main_control=disabled)
    args = {"project_id": "p:main", "preview_id": "a" * 64, "category": "personal"}
    runtime = {"agentId": "a", "sessionId": "s", "turnId": "turn-1"}
    try:
        with pytest.raises(ValueError):
            await asyncio.to_thread(execute_action, "initial_migration_queue", args, runtime=runtime, governed=True)
        assert await disabled.claim() == {"schemaVersion": 1, "request": None}
    finally:
        disabled.close(); unbind_actions(service)
    owner = broker(service, claim_seconds=2, initial_migration_enabled=True)
    bind_actions(service, asyncio.get_running_loop(), main_control=owner)
    try:
        assert (await asyncio.to_thread(execute_action, "initial_migration_queue", args, runtime=runtime))["status"] == "approval_required"
        monkeypatch.setenv("AGENT_LLM__PROFILES__PRIMARY__MODEL", "private-override")
        with pytest.raises(ValueError, match="configuration unavailable"):
            await asyncio.to_thread(execute_action, "initial_migration_queue", args, runtime=runtime, governed=True)
        assert await owner.claim() == {"schemaVersion": 1, "request": None}
        monkeypatch.setenv("AGENT_LLM__PROFILES__PRIMARY__MODEL", " ")
        for forbidden in ({"approved": True}, {"sourcePath": "C:/secret"}, {"agent_id": "other"}):
            with pytest.raises(ValueError):
                await asyncio.to_thread(execute_action, "initial_migration_queue", {**args, **forbidden}, runtime=runtime, governed=True)
        task = asyncio.create_task(asyncio.to_thread(execute_action, "initial_migration_queue", args, runtime=runtime, governed=True))
        wire = (await owner.claim())["request"]
        operation_id = initial_migration_id("p:main", args["preview_id"], "personal")
        assert initial_migration_id("p:main", "b" * 64, "personal") == operation_id
        assert wire["operationId"] == operation_id and wire["turnId"] == "turn-1"
        bound = {key: wire[key] for key in ("projectId", "previewId", "turnId", "category", "operationId")}
        monkeypatch.setenv("AGENT_LLM__PROFILES__PRIMARY__MODEL", "private-override")
        assert not owner.initial_delivery(wire["deliveryId"], bound, admit=True)
        monkeypatch.setenv("AGENT_LLM__PROFILES__PRIMARY__MODEL", " ")
        queued = {"schemaVersion": 1, "projectId": "p:main", "previewId": args["preview_id"],
                  "category": "personal", "operationId": operation_id, "state": "queued", "code": "queued", "readyForCutover": False}
        with pytest.raises(ValueError, match="not prepared"):
            owner.settle(wire["deliveryId"], queued)
        owner.cancel_history_imports("turn-1")
        outcome = await task
        assert outcome["state"] == "unknown" and outcome["operationId"] == operation_id
        assert not owner.settle(wire["deliveryId"], queued)
    finally:
        owner.close(); unbind_actions(service)


@pytest.mark.anyio
async def test_delivery_id_collision_never_replaces_an_existing_request(monkeypatch):
    import core.assistant_runtime.main_control as control
    service = Dispatch()
    owner = broker(service, claim_seconds=2, initial_migration_enabled=True)
    args = {"projectId": "p:main", "previewId": "a" * 64, "turnId": "turn-1", "category": "personal",
            "operationId": control.initial_migration_id("p:main", "", "personal")}
    monkeypatch.setattr(control.secrets, "token_hex", lambda _size: "a" * 32)
    try:
        first = asyncio.create_task(owner.invoke("initial_migration_queue", args, turn_id="turn-1"))
        wire = (await owner.claim())["request"]
        second = await owner.invoke("initial_migration_queue", args, turn_id="turn-1")
        assert second["state"] == "unknown"
        assert wire["deliveryId"] in owner._pending
        assert owner.begin_initial_drain(wire["deliveryId"], args["operationId"]) == (True, None)
        assert (await first)["state"] == "unknown"
    finally:
        owner.close()


@pytest.mark.anyio
async def test_initial_drain_fences_expired_unadmitted_delivery():
    from core.assistant_runtime.main_control import initial_migration_id
    service = Dispatch()
    owner = broker(service, claim_seconds=2, initial_migration_enabled=True)
    args = {"projectId": "p:main", "previewId": "a" * 64, "turnId": "turn-1", "category": "personal",
            "operationId": initial_migration_id("p:main", "", "personal")}
    try:
        task = asyncio.create_task(owner.invoke("initial_migration_queue", args, turn_id="turn-1"))
        wire = (await owner.claim())["request"]
        delivery = wire["deliveryId"]
        owner._pending[delivery].deadline = 0
        owner._expire()
        assert (await task)["state"] == "unknown"
        assert owner.begin_initial_drain(delivery, args["operationId"]) == (True, None)
        assert owner.begin_initial_drain(delivery, "initial-" + "f" * 40) == (False, None)
        assert not owner.initial_delivery(delivery, args, admit=True)
        owner._initial_issued_ids.update({f"{i:032x}": ("initial-" + "b" * 40, "b" * 64) for i in range(4096)})
        assert (await owner.invoke("initial_migration_queue", args, turn_id="turn-1"))["state"] == "unknown"
        assert owner.begin_initial_drain(delivery, args["operationId"]) == (True, None)
    finally:
        owner.close()


@pytest.mark.anyio
async def test_initial_migration_receipt_is_read_only_closed_and_capability_gated():
    from core.assistant_runtime.main_control import initial_migration_id
    service = Dispatch()
    args = {"project_id": "p:main", "category": "personal"}
    disabled = broker(service)
    bind_actions(service, asyncio.get_running_loop(), main_control=disabled)
    try:
        listing = await asyncio.to_thread(execute_action, "index", {"query": "initial_migration_receipt"})
        assert listing["total"] == 0
        with pytest.raises(ValueError):
            await asyncio.to_thread(execute_action, "initial_migration_receipt", args)
        with pytest.raises(ValueError):
            await disabled.invoke("initial_migration_receipt", {"projectId": "p:main", "category": "personal",
                "operationId": initial_migration_id("p:main", "", "personal")})
    finally:
        disabled.close(); unbind_actions(service)

    owner = broker(service, claim_seconds=2, initial_migration_enabled=True)
    bind_actions(service, asyncio.get_running_loop(), main_control=owner)
    try:
        description = await asyncio.to_thread(execute_action, "describe", {"action": "initial_migration_receipt"})
        assert description["governed"] is False
        assert set(description["parameters"]["properties"]) == {"project_id", "category"}
        for extra in ({"operation_id": "other"}, {"sourcePath": "C:/private"}, {"approved": True}):
            with pytest.raises(ValueError):
                await asyncio.to_thread(execute_action, "initial_migration_receipt", {**args, **extra})
        with pytest.raises(ValueError, match="authorized"):
            await asyncio.to_thread(execute_action, "initial_migration_receipt", {**args, "project_id": "p:other"})
        operation_id = initial_migration_id("p:main", "", "personal")
        for state in ("queued", "completed", "partial", "unknown", "not_found"):
            # The ordinary read tool is sufficient; no governed flag or Turn is supplied.
            task = asyncio.create_task(asyncio.to_thread(execute_action, "initial_migration_receipt", args))
            wire = (await owner.claim())["request"]
            assert set(wire) == {"deliveryId", "action", "projectId", "category", "operationId"}
            assert {k: wire[k] for k in ("action", "projectId", "category", "operationId")} == {
                "action": "initial_migration_receipt", "projectId": "p:main", "category": "personal", "operationId": operation_id}
            response = {"schemaVersion": 1, "projectId": "p:main", "category": "personal", "operationId": operation_id,
                        "state": state, "code": state, "readyForCutover": False}
            for invalid in ({**response, "sourcePath": "C:/private"}, {**response, "operationId": "initial-" + "f" * 40},
                            {**response, "state": "completed", "code": "claimed"}, {**response, "readyForCutover": True}):
                with pytest.raises(ValueError):
                    owner.settle(wire["deliveryId"], invalid)
            assert owner.settle(wire["deliveryId"], response)
            assert await task == response
    finally:
        owner.close(); unbind_actions(service)


@pytest.mark.anyio
async def test_initial_migration_receipt_timeout_stays_unknown_after_claim():
    from core.assistant_runtime.main_control import initial_migration_id
    owner = broker(timeout_seconds=0.02, initial_migration_enabled=True)
    request = {"projectId": "p:main", "category": "knowledge",
               "operationId": initial_migration_id("p:main", "", "knowledge")}
    task = asyncio.create_task(owner.invoke("initial_migration_receipt", request))
    claimed = (await owner.claim())["request"]
    outcome = await task
    assert outcome == {"schemaVersion": 1, **request, "state": "unknown", "code": "unknown", "readyForCutover": False}
    assert not owner.settle(claimed["deliveryId"], {**outcome, "state": "completed", "code": "completed"})
    owner.close()


@pytest.mark.anyio
async def test_initial_migration_receipt_reaches_existing_read_tool(monkeypatch):
    from core.infrastructure import native_runtime
    from core.assistant_runtime.main_control import initial_migration_id
    from tools import personal_assistant_tools
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    monkeypatch.setattr(personal_assistant_tools, "_identity", lambda: {"agentId": "a", "sessionId": "s"})
    service = Dispatch()
    owner = broker(service, claim_seconds=2, initial_migration_enabled=True)
    bind_actions(service, asyncio.get_running_loop(), main_control=owner)
    try:
        args = {"project_id": "p:main", "category": "knowledge"}
        pending = asyncio.create_task(asyncio.to_thread(personal_assistant_tools.personal_assistant_action_tool,
                                                        "initial_migration_receipt", args))
        wire = (await owner.claim())["request"]
        expected = {"schemaVersion": 1, "projectId": "p:main", "category": "knowledge",
                    "operationId": initial_migration_id("p:main", "", "knowledge"),
                    "state": "unknown", "code": "unknown", "readyForCutover": False}
        assert owner.settle(wire["deliveryId"], expected)
        assert json.loads(await pending) == {"source": "launcher-assistant", "untrustedContent": True, **expected}
    finally:
        owner.close(); unbind_actions(service)


@pytest.mark.anyio
async def test_history_turn_stop_does_not_report_a_claimed_import_as_cancelled():
    owner = broker(claim_seconds=2)
    request = {"projectId": "p:main", "previewId": "a" * 64, "turnId": "turn-1"}
    task = asyncio.create_task(owner.invoke("history_import", request, turn_id="turn-1"))
    claimed = (await owner.claim())["request"]
    owner.cancel_history_imports("turn-1")
    result = await task
    assert result["state"] == "unknown" and result["code"] == "unknown"
    assert not owner.settle(claimed["deliveryId"], {"schemaVersion": 1, "projectId": "p:main",
        "previewId": "a" * 64, "state": "published", "code": "imported", "historyCount": 1,
        "readyForCutover": False})
    owner.close()


@pytest.mark.anyio
async def test_affairs_sync_requires_native_governance_and_preserves_unknown_receipt_id():
    from core.assistant_runtime.main_control import affairs_migration_id
    service = Dispatch()
    owner = broker(service, claim_seconds=2)
    bind_actions(service, asyncio.get_running_loop(), main_control=owner)
    args = {"project_id": "p:main", "preview_id": "b" * 64}
    runtime = {"agentId": "a", "sessionId": "s", "turnId": "turn-1"}
    try:
        assert (await asyncio.to_thread(execute_action, "affairs_sync", args, runtime=runtime))["status"] == "approval_required"
        with pytest.raises(ValueError):
            await asyncio.to_thread(execute_action, "affairs_sync", {**args, "approved": True}, runtime=runtime, governed=True)
        task = asyncio.create_task(asyncio.to_thread(execute_action, "affairs_sync", args, runtime=runtime, governed=True))
        wire = (await owner.claim())["request"]
        assert wire["action"] == "affairs_sync" and wire["turnId"] == "turn-1"
        owner.cancel_history_imports("turn-1")
        result = await task
        assert result["state"] == "unknown" and not result["readyForCutover"]
        assert result["migrationId"] == affairs_migration_id("p:main", args["preview_id"])
        assert not owner.settle(wire["deliveryId"], result)
        task = asyncio.create_task(asyncio.to_thread(execute_action, "affairs_sync", args, runtime=runtime, governed=True))
        wire = (await owner.claim())["request"]
        completed = {**result, "state": "complete", "code": "synchronized", "appliedCount": 1, "conflictCount": 0}
        with pytest.raises(ValueError):
            owner.settle(wire["deliveryId"], {**completed, "conflictCount": True})
        with pytest.raises(ValueError):
            owner.settle(wire["deliveryId"], {**completed, "path": "C:/forged"})
        assert owner.settle(wire["deliveryId"], completed)
        assert await task == completed
        original_id = "affairs-" + "f" * 40
        recover_args = {**args, "recover_sync_id": original_id}
        recovery = asyncio.create_task(asyncio.to_thread(execute_action, "affairs_sync", recover_args, runtime=runtime, governed=True))
        recovered_wire = (await owner.claim())["request"]
        assert recovered_wire["recoverSyncId"] == original_id
        owner.cancel_history_imports("turn-1")
        assert (await recovery)["migrationId"] == original_id
        with pytest.raises(ValueError):
            await asyncio.to_thread(execute_action, "history_import", recover_args, runtime=runtime, governed=True)
    finally:
        owner.close()
        unbind_actions(service)


@pytest.mark.anyio
async def test_episodic_sync_requires_approval_and_preserves_original_recovery_id():
    from core.assistant_runtime.main_control import episodic_migration_id
    service = Dispatch()
    owner = broker(service, claim_seconds=2)
    bind_actions(service, asyncio.get_running_loop(), main_control=owner)
    args = {"project_id": "p:main", "preview_id": "b" * 64}
    runtime = {"agentId": "a", "sessionId": "s", "turnId": "turn-1"}
    try:
        assert (await asyncio.to_thread(execute_action, "episodic_sync", args, runtime=runtime))["status"] == "approval_required"
        with pytest.raises(ValueError):
            await asyncio.to_thread(execute_action, "episodic_sync", {**args, "path": "C:/secret"}, runtime=runtime, governed=True)
        task = asyncio.create_task(asyncio.to_thread(execute_action, "episodic_sync", args, runtime=runtime, governed=True))
        wire = (await owner.claim())["request"]
        assert wire["action"] == "episodic_sync" and wire["turnId"] == "turn-1"
        owner.cancel_history_imports("turn-1")
        unknown = await task
        assert unknown["state"] == "unknown" and unknown["migrationId"] == episodic_migration_id("p:main", args["preview_id"])
        original = "episodic-" + "f" * 40
        recovery = asyncio.create_task(asyncio.to_thread(execute_action, "episodic_sync", {**args, "recover_sync_id": original}, runtime=runtime, governed=True))
        wire = (await owner.claim())["request"]
        assert wire["recoverSyncId"] == original
        owner.cancel_history_imports("turn-1")
        assert (await recovery)["migrationId"] == original
        resolution_args = {**args, "resolve_sync_id": original, "review_token": "c" * 64}
        with pytest.raises(ValueError):
            await asyncio.to_thread(execute_action, "episodic_sync", {**args, "resolve_sync_id": original}, runtime=runtime, governed=True)
        resolution = asyncio.create_task(asyncio.to_thread(execute_action, "episodic_sync", resolution_args, runtime=runtime, governed=True))
        wire = (await owner.claim())["request"]
        assert wire["resolveSyncId"] == original and wire["reviewToken"] == "c" * 64
        resolved = {"schemaVersion": 1, "projectId": args["project_id"], "previewId": args["preview_id"],
            "migrationId": episodic_migration_id(args["project_id"], args["preview_id"]),
            "state": "complete", "code": "resolved", "appliedCount": 0, "conflictCount": 0, "readyForCutover": False}
        assert owner.settle(wire["deliveryId"], resolved) and await resolution == resolved
    finally:
        owner.close()
        unbind_actions(service)


@pytest.mark.anyio
async def test_existing_native_manage_tool_is_the_only_approval_elevation(monkeypatch):
    from core.infrastructure import native_runtime
    from tools import personal_assistant_tools

    service = Dispatch()
    owner = broker(service, claim_seconds=2)
    identities = []

    def identity():
        identities.append("native")
        return {"agentId": "a", "sessionId": "s"}

    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    monkeypatch.setattr(personal_assistant_tools, "_identity", identity)
    bind_actions(service, asyncio.get_running_loop(), main_control=owner)
    args = {"project_id": "p:main", "operation": "restart", "request_id": "request-1"}
    try:
        raw = await asyncio.to_thread(personal_assistant_tools.personal_assistant_action_tool, "project_lifecycle", args)
        assert json.loads(raw)["status"] == "approval_required"
        assert await owner.claim() == {"schemaVersion": 1, "request": None}
        forged = await asyncio.to_thread(personal_assistant_tools.personal_assistant_action_tool,
                                        "project_lifecycle", {**args, "governed": True})
        assert "approval_required" not in forged and "schema" in forged
        pending = asyncio.create_task(asyncio.to_thread(personal_assistant_tools.personal_assistant_manage_tool,
                                                      "project_lifecycle", json.dumps(args)))
        delivery = (await owner.claim())["request"]
        assert owner.settle(delivery["deliveryId"], result())
        assert json.loads(await pending) == {"source": "launcher-assistant", "untrustedContent": True, **result()}
        assert identities == ["native", "native", "native"]

        def invalid_identity():
            raise ValueError("native identity refused")

        monkeypatch.setattr(personal_assistant_tools, "_identity", invalid_identity)
        refused = await asyncio.to_thread(personal_assistant_tools.personal_assistant_manage_tool,
                                         "project_lifecycle", json.dumps(args))
        assert "native identity refused" in refused
        assert await owner.claim() == {"schemaVersion": 1, "request": None}
    finally:
        owner.close()
        unbind_actions(service)


@pytest.mark.parametrize("action", ["project_status", "project_lifecycle", "project_lifecycle_receipt"])
def test_execute_action_crosses_private_http_claim_settle_without_model(action):
    service = Dispatch()
    owner = broker(service, claim_seconds=2)
    app = create_app(native=Native(), token=TOKEN, dispatch=service, main_control=owner)
    with ThreadPoolExecutor() as worker, TestClient(app, base_url="http://127.0.0.1", headers=HEADERS) as client:
        assert client.get("/health").json()["mainControlVersion"] == 1
        args = {"project_id": "p:main"} if action == "project_status" else {
            "project_id": "p:main", "operation": "restart", "request_id": "request-1"}
        expected = ({"schemaVersion": 1, "projectId": "p:main", "operation": "status", "accepted": True,
                     "code": "status", "status": {"state": "running", "activeWorkCount": 0}}
                    if action == "project_status" else result())
        pending = worker.submit(execute_action, action, args,
            runtime={"agentId": "a"}, governed=True)
        delivery = client.get("/api/assistant/main-control/next").json()["request"]
        assert delivery["action"] == action
        assert delivery.get("requestId") == (None if action == "project_status" else "request-1")
        # Main cannot expand its result into arbitrary authority or raw errors.
        invalid = client.post("/api/assistant/main-control/settle", json={
            "schemaVersion": 1, "deliveryId": delivery["deliveryId"], "result": {**expected, "message": "PRIVATE_ERROR"}})
        assert invalid.status_code == 422 and "PRIVATE_ERROR" not in invalid.text and not pending.done()
        settled = client.post("/api/assistant/main-control/settle", json={
            "schemaVersion": 1, "deliveryId": delivery["deliveryId"], "result": expected})
        assert settled.json() == {"schemaVersion": 1, "accepted": True}
        assert pending.result(timeout=2) == expected


def test_legacy_host_has_no_capability_or_main_control_routes():
    with TestClient(create_app(native=Native(), token=TOKEN), base_url="http://127.0.0.1", headers=HEADERS) as client:
        assert client.get("/health").json() == {"status": "ok", "role": "launcher_assistant", "protocolVersion": 1}
        assert client.get("/api/assistant/main-control/next").status_code == 404
        assert client.post("/api/assistant/main-control/settle", json={}).status_code == 404


@pytest.mark.anyio
@pytest.mark.parametrize("action,payload", [
    ("project_status", {"projectId": "p:main", "operation": "start"}),
    ("project_status", {"projectId": "p:main", "operation": "status", "requestId": "x"}),
    ("project_lifecycle", {"projectId": "p:main", "operation": "status", "requestId": "x"}),
    ("project_lifecycle", {"projectId": "p:main", "operation": "restart"}),
    ("project_lifecycle_receipt", {**REQUEST, "force": True}),
    ("project_lifecycle", {**REQUEST, "workspaceRoot": "C:\\private"}),
    ("project_lifecycle", {**REQUEST, "url": "http://127.0.0.1"}),
    ("project_lifecycle", {**REQUEST, "requestId": "data:payload"}),
    ("project_lifecycle", {**REQUEST, "requestId": "file:secret"}),
    ("project_lifecycle", {**REQUEST, "requestId": "x" * 129}),
    ("project_lifecycle", {**REQUEST, "projectId": "x" * 161}),
    ("project_lifecycle", {**REQUEST, "projectId": "C:\\private"}),
    ("project_lifecycle", {**REQUEST, "projectId": "../other"}),
    ("project_lifecycle", {**REQUEST, "projectId": 1}),
    ("project_lifecycle", {**REQUEST, "operation": True}),
    ("project_lifecycle", {**REQUEST, "requestId": True}),
    ("lifecycle", REQUEST), ("project_lifecycle", []),
])
async def test_broker_rejects_extra_authority_and_invalid_identity_before_admission(action, payload):
    owner = broker()
    with pytest.raises(ValueError):
        await owner.invoke(action, payload)
    assert await owner.claim() == {"schemaVersion": 1, "request": None}
    owner.close()


@pytest.mark.anyio
async def test_current_permission_is_rechecked_at_claim_and_settle():
    service = Dispatch()
    owner = broker(service)
    first = asyncio.create_task(owner.invoke("project_lifecycle", REQUEST))
    await asyncio.sleep(0)
    service.projects.clear()
    assert await owner.claim() == {"schemaVersion": 1, "request": None}
    assert (await first)["code"] == "project_unavailable"
    service.projects.append("p:main")
    second = asyncio.create_task(owner.invoke("project_lifecycle", REQUEST))
    delivery = (await owner.claim())["request"]
    service.projects.clear()
    assert owner.settle(delivery["deliveryId"], result()) is False
    assert (await second)["code"] == "project_unavailable"
    service.projects.append("p:main")
    assert owner.settle(delivery["deliveryId"], result()) is False
    assert await owner.claim() == {"schemaVersion": 1, "request": None}
    owner.close()


@pytest.mark.anyio
async def test_out_of_order_and_duplicate_settlements_keep_original_request_identity():
    owner = broker()
    other = {**REQUEST, "requestId": "second", "operation": "stop"}
    first = asyncio.create_task(owner.invoke("project_lifecycle", REQUEST))
    first_delivery = (await owner.claim())["request"]
    second = asyncio.create_task(owner.invoke("project_lifecycle_receipt", other))
    second_delivery = (await owner.claim())["request"]
    assert second_delivery["action"] == "project_lifecycle_receipt"
    with pytest.raises(ValueError):
        owner.settle(first_delivery["deliveryId"], result(other))
    assert not first.done()
    assert owner.settle(second_delivery["deliveryId"], result(other, state="queued", code="restart_queued"))
    assert (await second)["requestId"] == "second" and not first.done()
    assert owner.settle(first_delivery["deliveryId"], result())
    assert await first == result()
    assert owner.settle(first_delivery["deliveryId"], result()) is False
    owner.close()


@pytest.mark.anyio
async def test_pending_budget_timeout_cancellation_and_close_release_transport_only():
    owner = broker(timeout_seconds=0.02, max_pending=1)
    first = asyncio.create_task(owner.invoke("project_lifecycle", REQUEST))
    await asyncio.sleep(0)
    assert (await owner.invoke("project_lifecycle", {**REQUEST, "requestId": "busy"}))["code"] == "control_busy"
    assert (await first)["code"] == "control_unavailable"
    # The expired, unclaimed row must not fill the bounded queue.
    second = asyncio.create_task(owner.invoke("project_lifecycle", {**REQUEST, "requestId": "live"}))
    delivery = (await owner.claim())["request"]
    assert delivery["requestId"] == "live"
    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second
    assert owner.settle(delivery["deliveryId"], result({**REQUEST, "requestId": "live"})) is False
    final = asyncio.create_task(owner.invoke("project_lifecycle_receipt", REQUEST))
    await owner.claim()
    waiters = [asyncio.create_task(owner.claim()) for _ in range(3)]
    owner.close()
    assert (await final)["code"] == "control_unavailable"
    assert await asyncio.wait_for(asyncio.gather(*waiters), 0.2) == [{"schemaVersion": 1, "request": None}] * 3
    assert (await owner.invoke("project_lifecycle", REQUEST))["code"] == "control_unavailable"
    owner.close()


@pytest.mark.anyio
@pytest.mark.parametrize("changes", [
    {"schemaVersion": True}, {"schemaVersion": 2}, {"accepted": 1},
    {"code": "C:\\secret\\error.log"}, {"code": "unknown_arbitrary_error"},
    {"state": "running"}, {"state": 1}, {"message": "raw credential error"},
    {"url": "http://127.0.0.1"}, {"status": {"state": "running"}},
    {"projectId": "other"}, {"requestId": "other"}, {"operation": "start"},
    {"state": "completed", "accepted": False}, {"state": "completed", "code": "project_unavailable"},
    {"state": "queued", "code": "accepted"},
])
async def test_write_result_is_closed_and_invalid_settle_cannot_consume_delivery(changes):
    owner = broker()
    pending = asyncio.create_task(owner.invoke("project_lifecycle", REQUEST))
    delivery = (await owner.claim())["request"]
    with pytest.raises(ValueError):
        owner.settle(delivery["deliveryId"], result(**changes))
    assert not pending.done()
    assert owner.settle(delivery["deliveryId"], result())
    assert await pending == result()
    owner.close()


@pytest.mark.anyio
async def test_status_projection_is_closed_copied_and_times_out_without_write_state():
    request = {"projectId": "p:main", "operation": "status"}
    owner = broker(timeout_seconds=0.1)
    pending = asyncio.create_task(owner.invoke("project_status", request))
    delivery = (await owner.claim())["request"]
    assert "requestId" not in delivery
    public = {"schemaVersion": 1, **request, "accepted": True, "code": "status", "status": {"state": "running", "activeWorkCount": 2}}
    for projection in ({"state": "bad"}, {"state": "running", "activeWorkCount": True},
                       {"state": "running", "activeWorkCount": -1}, {"state": "running", "activeWorkCount": 2**53},
                       {"state": "running", "activeWorkCount": 0.5}, {"state": "running", "path": "secret"}):
        with pytest.raises(ValueError):
            owner.settle(delivery["deliveryId"], {**public, "status": projection})
    assert owner.settle(delivery["deliveryId"], public)
    public["status"]["state"] = "stopped"
    assert (await pending)["status"] == {"state": "running", "activeWorkCount": 2}
    assert await owner.invoke("project_status", request) == {"schemaVersion": 1, **request, "accepted": False, "code": "status_unavailable"}
    owner.close()


def test_private_http_rejects_browser_stale_host_extra_fields_and_unbounded_body():
    owner = broker()
    with TestClient(create_app(native=Native(), token=TOKEN, main_control=owner), base_url="http://127.0.0.1", headers=HEADERS) as client:
        path = "/api/assistant/main-control/next"
        assert client.get(path, headers={"Authorization": "Bearer stale-generation"}).status_code == 401
        assert client.get(path, headers={"Origin": "http://127.0.0.1"}).status_code == 403
        assert client.get(path, headers={"Host": "other.invalid"}).status_code == 403
        assert client.get(path + "?projectId=p:main").status_code == 422
        assert client.request("GET", path, json={"projectId": "p:main"}).status_code == 422
        settle = "/api/assistant/main-control/settle"
        payload = {"schemaVersion": 1, "deliveryId": "f" * 32, "result": result()}
        assert client.post(settle, json=payload).json() == {"schemaVersion": 1, "accepted": False}
        for invalid in ({**payload, "schemaVersion": True}, {**payload, "root": "C:\\secret"},
                        {**payload, "deliveryId": "not-an-id"}, {**payload, "result": []}, [], None):
            response = client.post(settle, content=json.dumps(invalid))
            assert response.status_code == 422 and "secret" not in response.text
        assert client.post(settle + "?force=true", json=payload).status_code == 422
        assert client.post(settle, content=b" " * 4097).status_code == 413
        assert client.post(settle, content=iter([b" " * 2048, b" " * 2049])).status_code == 413
        assert client.post(settle, content='{"schemaVersion":1,"schemaVersion":1,"deliveryId":"' + "f" * 32 + '","result":{}}').status_code == 422


def test_shutdown_closes_broker_before_native_drain():
    owner = broker()
    calls = []
    original = owner.close

    def close():
        calls.append("broker")
        original()

    owner.close = close

    class Draining(Native):
        def shutdown(self):
            assert calls == ["broker"]
            calls.append("native")

    with TestClient(create_app(native=Draining(), token=TOKEN, main_control=owner)):
        pass
    assert calls == ["broker", "native"]


def test_shutdown_releases_real_synchronous_tool_waiter_before_native_drain():
    service = Dispatch()
    owner = broker(service, claim_seconds=2)
    with ThreadPoolExecutor() as worker:
        class Waiting(Native):
            def bootstrap(self):
                self.pending = worker.submit(execute_action, "project_lifecycle", {
                    "project_id": "p:main", "operation": "restart", "request_id": "request-1"}, governed=True)
                return super().bootstrap()

            def shutdown(self):
                assert self.pending.result(timeout=1) == {
                    "schemaVersion": 1, **REQUEST, "state": "unknown", "code": "control_unavailable"}

        with TestClient(create_app(native=Waiting(), token=TOKEN, dispatch=service, main_control=owner),
                        base_url="http://127.0.0.1", headers=HEADERS) as client:
            assert client.get("/api/assistant/main-control/next").json()["request"]["requestId"] == "request-1"


@pytest.mark.parametrize("flag", [None, "", "0", "true", "1"])
def test_script_only_constructs_optional_broker_from_consumed_main_flag(tmp_path, monkeypatch, flag):
    import os
    import types

    import uvicorn
    from core.assistant_runtime import host
    from core.assistant_runtime.main_control import MainControlBroker
    from scripts import assistant_host

    environment = {**os.environ, "VIBELUTION_ASSISTANT_TOKEN": TOKEN}
    environment.pop("VIBELUTION_ASSISTANT_MAIN_CONTROL", None)
    if flag is not None:
        environment["VIBELUTION_ASSISTANT_MAIN_CONTROL"] = flag
    monkeypatch.setattr(assistant_host, "os", types.SimpleNamespace(environ=environment, getpid=os.getpid, name=os.name))
    monkeypatch.setattr(assistant_host, "_namespace_windows_import_paths", lambda: None)
    monkeypatch.setattr(assistant_host, "_seed_tokenizer_cache", lambda _: None)
    monkeypatch.setattr(assistant_host.sys, "argv", ["assistant_host.py", "--profile-root", str(tmp_path / "profile"),
        "--runtime-dir", str(tmp_path / "runtime"), "--instance-id", "private-generation"])
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return object()

    class Server:
        should_exit = False

        def __init__(self, config):
            pass

        def run(self, sockets):
            assert len(sockets) == 1
            assert "VIBELUTION_ASSISTANT_MAIN_CONTROL" not in environment
            assert "VIBELUTION_ASSISTANT_TOKEN" not in environment
            captured["on_ready"]()

    monkeypatch.setattr(host, "create_app", create)
    monkeypatch.setattr(uvicorn, "Config", lambda *args, **kwargs: object())
    monkeypatch.setattr(uvicorn, "Server", Server)
    assistant_host.main()
    assert isinstance(captured["main_control"], MainControlBroker) is (flag == "1")
    assert captured["dispatch"].project_ids() == ()
    assert not (tmp_path / "runtime/ready.json").exists()
    if captured["main_control"] is not None:
        captured["main_control"].close()


@pytest.mark.anyio
async def test_optional_main_actions_have_full_discoverable_contracts_within_tool_budget():
    from tests.test_assistant_runtime_actions import _through_native_model_budget

    service = Dispatch()
    owner = broker(service)
    bind_actions(service, asyncio.get_running_loop(), main_control=owner)
    try:
        names = {"project_status", "project_lifecycle", "project_lifecycle_receipt"}
        page = execute_action("index", {"query": "project_"})
        assert {row["action"] for row in page["actions"]} >= names
        assert {row["action"] for row in page["actions"] if row["action"] in names and row["governed"]} == {"project_lifecycle"}
        for name in names:
            contract = execute_action("describe", {"action": name})
            schema = contract["parameters"]
            assert schema["additionalProperties"] is False
            assert set(schema["properties"]) == ({"project_id"} if name == "project_status" else {"project_id", "operation", "request_id"})
            if name != "project_status":
                assert schema["properties"]["operation"]["enum"] == ["start", "stop", "restart"]
                assert schema["properties"]["request_id"]["maxLength"] == 128
                assert "unknown" in contract["description"] and "queued" in contract["description"]
            assert contract["governed"] is (name == "project_lifecycle")
            _raw, outcome, facts, _rendered = _through_native_model_budget(contract)
            assert outcome is None and not facts.truncated
        for offset in range(execute_action("index", {})["total"] + 1):
            _raw, outcome, facts, _rendered = _through_native_model_budget(execute_action("index", {"offset": offset}))
            assert outcome is None and not facts.truncated
    finally:
        owner.close()
        unbind_actions(service)
    bind_actions(service, asyncio.get_running_loop())
    try:
        assert execute_action("index", {"query": "project_lifecycle"})["actions"] == []
        for name in names:
            with pytest.raises(ValueError, match="Unknown Launcher action"):
                execute_action("describe", {"action": name})
    finally:
        unbind_actions(service)
