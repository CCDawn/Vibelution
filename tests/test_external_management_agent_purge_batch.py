"""Batch purge admission is all-or-nothing and reuses the single-delete core."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from core.web.services.external_management.contracts import ACTION_MODELS, AgentPurgeBatch, contracts
from core.web.services.external_management.service import ManagementError, ManagementService, TargetIdentity


BINDING = {"projectId": "p", "instanceId": "i"}


class Native:
    """Existing-only preview and purge semantics of the real native gateway."""

    def __init__(self, protected=()):
        self.calls = []
        self.lose = set()
        self.fail = {}
        self.protected = set(protected)
        self.state = {f"agent-{n}": {"agentId": f"agent-{n}", "status": "archived", "configRevision": n}
                      for n in range(1, 7)}

    def read_purge_preview(self, agent_id):
        raw = self.state.get(agent_id)
        if raw is None:
            raise ManagementError("AGENT_UNAVAILABLE", 404)
        if raw.get("status") != "archived":
            raise ManagementError("STATE_CONFLICT", 409)
        if agent_id in self.protected:
            raise ManagementError("AGENT_PROTECTED", 403)
        return deepcopy(raw)

    def read_archive_state(self, agent_id):
        return deepcopy(self.state.get(agent_id))

    def purge(self, parameters, marker):
        agent_id = parameters["agent_id"]
        self.calls.append(agent_id)
        assert self.recorded is not None and self.recorded.exists(), "admission must be durable before any deletion"
        raw = self.state.get(agent_id)
        if raw is None:
            raise ManagementError("AGENT_UNAVAILABLE", 404)
        if raw.get("status") != "archived" or raw["configRevision"] != parameters["expected_config_revision"]:
            raise ManagementError("STATE_CONFLICT", 409)
        if agent_id in self.fail:
            raise self.fail[agent_id]
        del self.state[agent_id]
        if agent_id in self.lose:
            raise TimeoutError("lost native acknowledgement")
        return {"agentId": agent_id, "status": "purged", "cleanupPending": False}


@pytest.fixture
def batch_env(tmp_path):
    root = tmp_path / "management"
    native = Native()
    service = ManagementService(root, identity=lambda: TargetIdentity(BINDING, "root"), native=native)
    grant = service.bind({"client_id": "batch", "expected_binding": BINDING, "scopes": ["agents:read"]})
    service.invoke(grant["subject_id"], grant["subject_capability"], "authorization_upgrade", {
        "request_id": "scope-1", "expected_binding": BINDING,
        "parameters": {"expected_scopes": ["agents:read"], "add_scopes": ["agents:purge"]}})
    native.recorded = root / "requests"
    return service, native, grant


def invoke(env, request_id, purges):
    service, _, grant = env
    return service.invoke(grant["subject_id"], grant["subject_capability"], "agent_purge_batch", {
        "request_id": request_id, "expected_binding": BINDING, "parameters": {"purges": purges}})


def item(agent, revision=None):
    if revision is None:
        tail = agent.rsplit("-", 1)[-1]
        revision = int(tail) if tail.isdigit() else 1
    return {"agent_id": agent, "expected_config_revision": int(revision)}


def test_batch_is_governed_shared_scope_with_explicit_bounded_manifest():
    contract = contracts()["agent_purge_batch"]
    assert contract["governed"] is True and contract["scope"] == "agents:purge"
    assert ACTION_MODELS["agent_purge_batch"].model_json_schema()["properties"]["purges"]["maxItems"] == 50
    assert "50" in contract["description"] and "整批拒绝" in contract["description"]
    assert "通配" in contract["description"]
    assert set(ACTION_MODELS["agent_purge"].model_fields) == {"agent_id", "expected_config_revision"}


def test_batch_bounds_and_explicit_manifest_only():
    assert len(AgentPurgeBatch.model_validate({"purges": [item("agent-1")]}).purges) == 1
    assert len(AgentPurgeBatch.model_validate({"purges": [item(f"agent-{n}") for n in range(1, 51)]}).purges) == 50
    for bad in ([], [item(f"agent-{n}") for n in range(1, 52)],
                [item("agent-1"), item("agent-1")],
                [{"agent_id": "agent-1", "expected_config_revision": "3"}]):
        with pytest.raises(ValidationError):
            AgentPurgeBatch.model_validate({"purges": bad})
    # There is no wildcard or select-all syntax: a glob-looking string is only a
    # literal (nonexistent) agent id and dies in admission like any other miss.
    assert "agent_id" in AgentPurgeBatch.model_validate({"purges": [{"agent_id": "*",
        "expected_config_revision": 1}]}).purges[0].model_dump()


def test_batch_over_limit_is_invalid_input_without_records_or_calls(batch_env):
    service, native, _grant = batch_env
    with pytest.raises(ManagementError, match="INVALID_INPUT") as error:
        invoke(batch_env, "limit-1", [item(f"agent-{n}") for n in range(1, 52)])
    assert error.value.status_code == 422
    assert native.calls == []
    stored = [service.store.read(path) for path in (service.root / "requests").glob("*.json")]
    assert all(record.get("requestId") != "limit-1" for record in stored if record)


def test_batch_any_rejection_blocks_every_deletion_and_reports_each_reason(batch_env):
    service, native, grant = batch_env
    native.state["agent-4"]["status"] = "active"
    before = deepcopy(native.state)
    result = invoke(batch_env, "mixed-1", [item("agent-1"), item("agent-2", 999), item("agent-4"), item("missing")])
    assert result["status"] == "completed" and result["verified"] is True and result["reused"] is False
    assert [(entry["agentId"], entry["outcome"], entry["code"]) for entry in result["purgeBatch"]["results"]] == [
        ("agent-1", "rejected", "BATCH_REJECTED"), ("agent-2", "rejected", "STATE_CONFLICT"),
        ("agent-4", "rejected", "STATE_CONFLICT"), ("missing", "rejected", "AGENT_UNAVAILABLE")]
    assert native.calls == [] and native.state == before
    restarted = ManagementService(service.root, identity=service.identity, native=native)
    assert restarted.receipt(grant["subject_id"], grant["subject_capability"], "agent_purge_batch", "mixed-1") == {
        **result, "reused": True}
    assert native.calls == [] and native.state == before


def test_batch_single_invoke_executes_manifest_with_durable_admission(batch_env):
    service, native, grant = batch_env
    native.lose = set()
    result = invoke(batch_env, "run-1", [item("agent-1"), item("agent-2"), item("agent-3")])
    assert result["status"] == "completed" and result["verified"] is True
    assert [(entry["agentId"], entry["outcome"]) for entry in result["purgeBatch"]["results"]] == [
        ("agent-1", "purged"), ("agent-2", "purged"), ("agent-3", "purged")]
    assert native.calls == ["agent-1", "agent-2", "agent-3"]
    for agent in ("agent-1", "agent-2", "agent-3"):
        assert native.read_archive_state(agent) is None
    replay = invoke(batch_env, "run-1", [item("agent-1"), item("agent-2"), item("agent-3")])
    assert replay == {**result, "reused": True} and native.calls == ["agent-1", "agent-2", "agent-3"]
    with pytest.raises(ManagementError, match="IDEMPOTENCY_CONFLICT"):
        invoke(batch_env, "run-1", [item("agent-1"), item("agent-2")])


def test_batch_midflight_rejection_keeps_surviving_items_and_per_item_receipt(batch_env):
    service, native, grant = batch_env
    def stale(agent_id):
        return agent_id == "agent-2"
    original_preview = native.read_purge_preview
    native.read_purge_preview = lambda agent_id: original_preview(agent_id)
    native.fail = {"agent-2": ManagementError("STATE_CONFLICT", 409)}
    result = invoke(batch_env, "race-1", [item("agent-1"), item("agent-2"), item("agent-3")])
    assert result["status"] == "completed" and result["verified"] is True
    assert [(entry["agentId"], entry["outcome"], entry["code"]) for entry in result["purgeBatch"]["results"]] == [
        ("agent-1", "purged", None), ("agent-2", "rejected", "STATE_CONFLICT"), ("agent-3", "purged", None)]
    assert native.read_archive_state("agent-2")["status"] == "archived"
    restarted = ManagementService(service.root, identity=service.identity, native=native)
    replay = restarted.receipt(grant["subject_id"], grant["subject_capability"], "agent_purge_batch", "race-1")
    assert replay == {**result, "reused": True} and native.calls == ["agent-1", "agent-2", "agent-3"]


def test_batch_unknown_item_keeps_batch_unknown_without_any_replay(batch_env):
    service, native, grant = batch_env
    native.lose = {"agent-2"}
    result = invoke(batch_env, "lost-1", [item("agent-1"), item("agent-2"), item("agent-3")])
    assert result["status"] == "unknown" and result["verified"] is False
    assert result["code"] == "OPERATION_UNCONFIRMED"
    assert [(entry["agentId"], entry["outcome"]) for entry in result["purgeBatch"]["results"]] == [
        ("agent-1", "purged"), ("agent-2", "unknown"), ("agent-3", "purged")]
    for request in (lambda: invoke(batch_env, "lost-1", [item("agent-1"), item("agent-2"), item("agent-3")]),
                    lambda: service.receipt(grant["subject_id"], grant["subject_capability"], "agent_purge_batch", "lost-1")):
        assert request()["status"] == "unknown"
    assert native.calls == ["agent-1", "agent-2", "agent-3"]
    # The lost item may or may not have been deleted; either way the unknown
    # outcome is never re-executed and can never claim verified completion.
    assert native.read_archive_state("agent-1") is None and native.read_archive_state("agent-3") is None


@pytest.mark.parametrize("outcome", ["purged", "rejected", "unknown"])
def test_batch_receipt_reads_durable_progress_while_native_write_is_running(batch_env, outcome):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    service, native, grant = batch_env
    entered, release = Event(), Event()
    original_purge = native.purge
    if outcome == "rejected":
        native.fail["agent-2"] = ManagementError("STATE_CONFLICT", 409)
    elif outcome == "unknown":
        native.lose.add("agent-2")

    def slow_purge(parameters, marker):
        if parameters["agent_id"] == "agent-2":
            entered.set()
            assert release.wait(5), "test must release the paused native writer"
        return original_purge(parameters, marker)

    native.purge = slow_purge
    # A fresh service instance shares only the existing ledger/OS lock. The
    # receipt must not depend on the writer's in-memory state or native locks.
    reader = ManagementService(service.root, identity=service.identity, native=native)
    native_reads = []
    original_read = native.read_archive_state

    def observe_read(agent_id):
        native_reads.append(agent_id)
        return original_read(agent_id)

    native.read_archive_state = observe_read
    purges = [item("agent-1"), item("agent-2"), item("agent-3")]
    with ThreadPoolExecutor(max_workers=4) as pool:
        writer = pool.submit(invoke, batch_env, "slow-1", purges)
        try:
            assert entered.wait(2)
            receipts = [pool.submit(reader.receipt, grant["subject_id"], grant["subject_capability"],
                "agent_purge_batch", "slow-1") for _ in range(3)]
            for future in receipts:
                progress = future.result(timeout=0.5)
                assert progress["status"] == "unknown" and progress["verified"] is False
                assert progress["reused"] is True
                assert [(row["agentId"], row["outcome"]) for row in progress["purgeBatch"]["results"]] == [
                    ("agent-1", "purged")]
            assert native_reads == [], "in-flight receipts must not reconcile through busy native owners"
        finally:
            release.set()
        completed = writer.result(timeout=5)

    final = reader.receipt(grant["subject_id"], grant["subject_capability"], "agent_purge_batch", "slow-1")
    assert final == {**completed, "reused": True}
    assert final["status"] == ("unknown" if outcome == "unknown" else "completed")
    assert final["purgeBatch"]["results"][1]["outcome"] == outcome
    assert invoke(batch_env, "slow-1", purges) == final
    assert native.calls == ["agent-1", "agent-2", "agent-3"]


def test_batch_interrupted_execution_never_resumes_or_claims_completion(tmp_path):
    from core.web.services.external_management.service import ManagementService, TargetIdentity
    native = Native()
    service = ManagementService(tmp_path / "management", identity=lambda: TargetIdentity(BINDING, "root"), native=native)
    grant = service.bind({"client_id": "batch", "expected_binding": BINDING, "scopes": ["agents:read"]})
    service.invoke(grant["subject_id"], grant["subject_capability"], "authorization_upgrade", {
        "request_id": "scope-1", "expected_binding": BINDING,
        "parameters": {"expected_scopes": ["agents:read"], "add_scopes": ["agents:purge"]}})
    native.recorded = tmp_path / "management" / "requests"

    original_purge = native.purge
    def crash_on_second(parameters, marker):
        if len(native.calls) == 1:
            raise RuntimeError("process interrupted mid-batch")
        return original_purge(parameters, marker)
    native.purge = crash_on_second
    # An in-flight crash is a durable unknown intent, never a retryable write.
    result = invoke((service, native, grant), "crash-1", [item("agent-1"), item("agent-2"), item("agent-3")])
    assert result["status"] == "unknown" and [entry["agentId"] for entry in result["purgeBatch"]["results"]] == ["agent-1"]
    restarted = ManagementService(service.root, identity=service.identity, native=native)
    result = restarted.receipt(grant["subject_id"], grant["subject_capability"], "agent_purge_batch", "crash-1")
    assert result["status"] == "unknown" and result["verified"] is False
    assert [entry["agentId"] for entry in result["purgeBatch"]["results"]] == ["agent-1"]
    assert native.calls == ["agent-1"] and native.read_archive_state("agent-1") is None
    assert native.read_archive_state("agent-2")["status"] == "archived"
    assert native.read_archive_state("agent-3")["status"] == "archived"


def test_batch_requires_the_same_explicit_purge_scope(batch_env):
    service, native, _grant = batch_env
    grant = service.bind({"client_id": "reader", "expected_binding": BINDING, "scopes": ["agents:read"]})
    with pytest.raises(ManagementError, match="SCOPE_DENIED"):
        invoke((service, native, grant), "denied-1", [item("agent-1")])
    assert native.calls == [] and native.read_archive_state("agent-1")["status"] == "archived"


def test_batch_operator_transport_returns_whole_batch_receipts(tmp_path, monkeypatch):
    """The generic action route carries the batch manifest receipt as-is."""
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
    from core.web.routes import launcher_assistant_management as route
    from tests.test_external_management_agent_purge_api import PREFIX
    native = Native()
    service = ManagementService(tmp_path / "management", identity=lambda: TargetIdentity(BINDING, "root"), native=native)
    grant = service.bind({"client_id": "batch-client", "expected_binding": BINDING, "scopes": ["agents:read"]})
    service.invoke(grant["subject_id"], grant["subject_capability"], "authorization_upgrade", {
        "request_id": "scope-1", "expected_binding": BINDING,
        "parameters": {"expected_scopes": ["agents:read"], "add_scopes": ["agents:purge"]}})
    native.recorded = tmp_path / "management" / "requests"
    monkeypatch.setattr(route, "_SERVICE", service)
    headers = {CONTROL_TOKEN_HEADER: get_control_token(), route.SUBJECT_HEADER: grant["subject_id"],
        route.CAPABILITY_HEADER: grant["subject_capability"]}
    app = FastAPI()
    app.include_router(route.router)
    with TestClient(app) as client:
        rejected = client.post(PREFIX + "/actions/agent_purge_batch", headers=headers, json={
            "request_id": "api-1", "expected_binding": BINDING,
            "parameters": {"purges": [item("agent-1"), item("missing")]}})
        assert rejected.status_code == 200 and rejected.json()["status"] == "completed"
        assert rejected.json()["purgeBatch"]["results"][1]["code"] == "AGENT_UNAVAILABLE"
        assert native.calls == []
        done = client.post(PREFIX + "/actions/agent_purge_batch", headers=headers, json={
            "request_id": "api-2", "expected_binding": BINDING,
            "parameters": {"purges": [item("agent-1"), item("agent-2")]}})
        assert done.status_code == 200 and done.json()["verified"] is True
        assert [entry["outcome"] for entry in done.json()["purgeBatch"]["results"]] == ["purged", "purged"]
        replayed = client.post(PREFIX + "/actions/agent_purge_batch", headers=headers, json={
            "request_id": "api-2", "expected_binding": BINDING,
            "parameters": {"purges": [item("agent-1"), item("agent-2")]}})
        assert replayed.json()["reused"] is True and native.calls == ["agent-1", "agent-2"]
        over = client.post(PREFIX + "/actions/agent_purge_batch", headers=headers, json={
            "request_id": "api-3", "expected_binding": BINDING,
            "parameters": {"purges": [item(f"agent-{n}") for n in range(1, 52)]}})
        assert over.status_code == 422 and over.json()["detail"]["code"] == "INVALID_INPUT" and native.calls == ["agent-1", "agent-2"]
