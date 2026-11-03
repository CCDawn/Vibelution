"""Recover this request's native evidence without replaying its mutation."""
from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.web.services.external_management import platform_actions
from core.web.services.external_management.contracts import ACTION_MODELS
from core.web.services.external_management.service import ManagementError, ManagementService, TargetIdentity
from core.web.services.external_management.store import digest
from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
from tests.test_launcher_assistant_runtime_operations import env, research
from tests.test_team_knowledge_service import isolate_developer_sandbox_config, knowledge_env


def receipts():
    return importlib.import_module("core.web.services.external_management.operation_receipts")


class Native:
    def __init__(self, project):
        self.project_root = project
        self.calls = 0

    def runtime_command(self, parameters, marker):
        self.calls += 1
        return {"operation": {"kind": "runtime_task", "resourceId": parameters["resource_id"], "status": "stopping",
            "revision": "new-revision", "agentId": "", "sessionId": "", "teamId": "", "flowId": "",
            "commands": [], "progressFingerprint": "a" * 64}, "command": "stop", "accepted": True,
            "stopRequested": True, "revisionCheck": "preflight_only", "untrustedContent": True}


def parameters(**changes):
    return ACTION_MODELS["runtime_command"].model_validate({"kind": "runtime_task", "resource_id": "task-a",
        "command": "stop", "expected_revision": "old-revision", **changes}).model_dump()


def marker(params, *, key="a" * 64, subject="ops-" + "b" * 32):
    return {"subjectType": "operator", "subjectId": subject, "requestKey": key,
            "requestFingerprint": digest(params)}


@pytest.fixture
def owner(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    native = Native(project)
    outcome = receipts().NativeOutcomeStore(tmp_path / "outcomes", project_root=project)
    native.operation_receipts = lambda: outcome
    return SimpleNamespace(native=native, outcome=outcome)


def test_native_success_ack_is_durable_before_outer_return_and_read_only_reconcilable(owner):
    params = parameters()
    proof = marker(params)
    result = platform_actions.execute(owner.native, "runtime_command", params, proof)
    assert "progressFingerprint" not in result["operation"]
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in owner.outcome.root.rglob("*") if p.is_file()}
    confirmed = platform_actions.reconcile(owner.native, "runtime_command", params, proof)
    assert confirmed["state"] == "confirmed" and confirmed["evidence"] == "native_outcome"
    assert confirmed["result"] == result
    assert owner.native.calls == 1
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in owner.outcome.root.rglob("*") if p.is_file()} == before


def authorized(root, native):
    binding = {"projectId": "reconcile-project", "instanceId": "reconcile-instance"}
    service = ManagementService(root, identity=lambda: TargetIdentity(binding, "reconcile-authority"), native=native)
    grant = service.bind({"client_id": "reconcile-client", "expected_binding": binding, "scopes": ["agents:read"]})
    credentials = grant["subject_id"], grant["subject_capability"]
    service.invoke(*credentials, "authorization_upgrade", {"request_id": "grant-runtime", "expected_binding": binding,
        "parameters": {"expected_scopes": ["agents:read"], "add_scopes": ["operations:control"]}})
    return service, credentials, binding


def test_lost_outer_ack_recovers_after_management_service_reconstruction_with_one_native_call(owner, tmp_path, monkeypatch):
    from core.web.services.external_management import service as management_module
    service, credentials, binding = authorized(tmp_path / "management", owner.native)
    execute = management_module.execute_platform_action

    def lose_ack(*args, **kwargs):
        execute(*args, **kwargs)
        raise OSError("Native response was lost before outer receipt commit")

    monkeypatch.setattr(management_module, "execute_platform_action", lose_ack)
    envelope = {"request_id": "one-original-id", "expected_binding": binding, "parameters": parameters()}
    first = service.invoke(*credentials, "runtime_command", envelope)
    assert first["status"] == "unknown" and first["verified"] is False
    restarted = ManagementService(service.root, identity=service.identity, native=owner.native)
    recovered = restarted.receipt(*credentials, "runtime_command", envelope["request_id"])
    assert recovered["status"] == "completed" and recovered["verified"] is True
    assert restarted.invoke(*credentials, "runtime_command", envelope) == recovered
    assert owner.native.calls == 1


def test_matching_current_state_from_another_request_is_not_causal_proof(owner):
    params = parameters()
    platform_actions.execute(owner.native, "runtime_command", params, marker(params))
    other = platform_actions.reconcile(owner.native, "runtime_command", params, marker(params, key="c" * 64))
    assert other["state"] == "requires_review" and other["result"] is None
    assert owner.native.calls == 1


@pytest.mark.parametrize("change", ["parameters", "subject", "project"])
def test_outcome_cannot_be_rebound_to_changed_identity_or_parameters(owner, tmp_path, change):
    params = parameters()
    proof = marker(params)
    platform_actions.execute(owner.native, "runtime_command", params, proof)
    if change == "parameters":
        params = parameters(resource_id="different-task")
        proof = marker(params)
    elif change == "subject":
        proof = marker(params, subject="ops-" + "d" * 32)
    else:
        owner.native.project_root = tmp_path / "other-project"
        owner.native.project_root.mkdir()
    response = platform_actions.reconcile(owner.native, "runtime_command", params, proof)
    assert response["state"] != "confirmed" and response["result"] is None
    assert owner.native.calls == 1


def test_corrupt_native_outcome_is_unavailable_and_never_replayed(owner):
    params = parameters()
    proof = marker(params)
    platform_actions.execute(owner.native, "runtime_command", params, proof)
    records = list(owner.outcome.root.rglob("*.json"))
    assert len(records) == 1
    records[0].write_text('{"status":"completed","result":{"SECRET":"forged"}}', encoding="utf-8")
    response = platform_actions.reconcile(owner.native, "runtime_command", params, proof)
    assert response["state"] == "unavailable" and response["result"] is None
    assert owner.native.calls == 1


def test_fake_native_without_explicit_proof_owner_cannot_create_a_product_store(tmp_path):
    native = Native(tmp_path / "not-created-project")
    params = parameters()
    result = platform_actions.execute(native, "runtime_command", params, marker(params))
    assert result["accepted"] is True
    assert platform_actions.reconcile(native, "runtime_command", params, marker(params))["state"] == "requires_review"
    assert not native.project_root.exists()


def test_unknown_inside_native_owner_has_no_outcome_and_requires_review(owner, monkeypatch):
    params = parameters()
    proof = marker(params)

    def lost_inside(*args):
        owner.native.calls += 1
        raise OSError("Native owner may have committed but returned no proof")

    monkeypatch.setattr(owner.native, "runtime_command", lost_inside)
    with pytest.raises(OSError):
        platform_actions.execute(owner.native, "runtime_command", params, proof)
    response = platform_actions.reconcile(owner.native, "runtime_command", params, proof)
    assert response["state"] == "requires_review" and response["result"] is None
    assert owner.native.calls == 1


@pytest.mark.parametrize("kind,native_kind", [("supervised_run", "supervised"), ("self_evolution_run", "self")])
def test_lost_manager_ack_is_recovered_from_original_native_command_without_current_owner(
        owner, tmp_path, monkeypatch, kind, native_kind):
    from core.runtime_manager import evolution_control
    from tests.test_launcher_assistant_runtime_operations import managed_snapshot
    params = parameters(kind=kind, resource_id="managed-a", command="pause", expected_revision="a" * 64)
    service, credentials, binding = authorized(tmp_path / "management", owner.native)
    saved = {}
    row = managed_snapshot(native_kind, [{"runId": "managed-a", "status": "paused", "pauseRequested": True}])["rows"][0]

    def lose_native_ack(parameters, proof):
        owner.native.calls += 1
        saved[proof["requestKey"]] = {"commandId": "cmd_managed_" + "b" * 64, "state": "completed",
            "operation": row, "accepted": True, "stopRequested": False, "revisionCheck": "native_cas"}
        raise OSError("response lost after original native completion")

    def original_result(project, observed_kind, rid, action, expected, *, request_id):
        assert (project, observed_kind, rid, action, expected) == (
            owner.native.project_root, native_kind, "managed-a", "pause", "a" * 64)
        return saved.get(request_id, {"state": "unknown"})

    monkeypatch.setattr(owner.native, "runtime_command", lose_native_ack)
    monkeypatch.setattr(evolution_control, "read_command_outcome", original_result)
    monkeypatch.setattr(evolution_control, "read_inventory", lambda *a, **kw: pytest.fail("recovery read current manager"))
    monkeypatch.setattr(evolution_control, "command", lambda *a, **kw: pytest.fail("recovery replayed mutation"))
    envelope = {"request_id": "original-manager-command", "expected_binding": binding, "parameters": params}
    first = service.invoke(*credentials, "runtime_command", envelope)
    assert first["status"] == "unknown"
    recovered = service.receipt(*credentials, "runtime_command", envelope["request_id"])
    assert recovered["status"] == "completed" and recovered["operation"]["revisionCheck"] == "native_cas"
    assert recovered["operation"]["operation"]["status"] == "paused"
    assert owner.native.calls == 1
    assert platform_actions.reconcile(owner.native, "runtime_command", params, marker(params, key="f" * 64))["state"] == "requires_review"


def inject_outcome(native, tmp_path, monkeypatch):
    target = receipts().NativeOutcomeStore(tmp_path / "outcomes", project_root=native.project_root)
    monkeypatch.setattr(native, "operation_receipts", lambda: target, raising=False)
    return target


def native_parameters(action, body):
    return ACTION_MODELS[action].model_validate(body).model_dump(
        exclude_unset=action in {"team_update", "agent_tool_policy_update"})


def inventory(folder):
    return {str(path.relative_to(folder)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in folder.rglob("*") if path.is_file()}


def test_native_flow_start_internal_lost_ack_recovers_exact_id_without_restarting(env, tmp_path, monkeypatch):
    from core.web.services.external_management.flow_control import FlowControl
    from core.web.services.team_workflow.generic import service
    from tests.test_assistant_flow_control import save_native
    save_native()
    inject_outcome(env.gateway, tmp_path, monkeypatch)
    params = native_parameters("flow_start", {"team_id": "team-a", "flow_id": "flow-a", "expectedRevision": 1})
    proof = marker(params)
    start, calls = service.start_run, []

    def lose_native_ack(*args, **kwargs):
        calls.append(start(*args, **kwargs))
        raise OSError("Acknowledgement lost after deterministic native admission")

    monkeypatch.setattr(service, "start_run", lose_native_ack)
    with server_operator_scope("real-operator", roles=("operator",)):
        with pytest.raises(ManagementError, match="FLOW_START_UNCONFIRMED"):
            platform_actions.execute(env.gateway, "flow_start", params, proof)
        before = inventory(env.workspace)
        result = platform_actions.reconcile(env.gateway, "flow_start", params, proof)
        assert result["state"] == "confirmed" and result["evidence"] == "flow_start_identity"
        assert result["result"]["runId"] == calls[0]["id"]
        assert inventory(env.workspace) == before
        other_params = {**params, "values": {"forged": "SECRET"}}
        assert platform_actions.reconcile(env.gateway, "flow_start", other_params, marker(other_params))["state"] != "confirmed"
    assert len(calls) == 1 and len(service.list_runs("team-a")["runs"]) == 1


def test_native_flow_save_internal_lost_ack_requires_review_even_when_definition_matches(env, tmp_path, monkeypatch):
    from core.web.services.team_workflow.generic import service
    from tests.test_assistant_flow_control import definition
    inject_outcome(env.gateway, tmp_path, monkeypatch)
    params = native_parameters("flow_save", {"team_id": "team-a", "flow_id": "flow-a", "expectedRevision": 0,
                                             "flow": definition()})
    save, calls = service.save_flow, []

    def lose_native_ack(*args, **kwargs):
        calls.append(save(*args, **kwargs))
        raise OSError("Native owner did not return its success")

    monkeypatch.setattr(service, "save_flow", lose_native_ack)
    with server_operator_scope("real-operator", roles=("operator",)):
        with pytest.raises(ManagementError, match="FLOW_SAVE_UNCONFIRMED"):
            platform_actions.execute(env.gateway, "flow_save", params, marker(params))
        before = inventory(env.workspace)
        outcome = platform_actions.reconcile(env.gateway, "flow_save", params, marker(params))
        assert outcome["state"] == "requires_review" and outcome["result"] is None
        assert inventory(env.workspace) == before
    assert len(calls) == 1 and calls[0]["revision"] == 1


def test_flow_adapter_ack_is_persisted_before_its_return_can_be_lost(env, tmp_path, monkeypatch):
    from core.web.services.external_management.flow_control import FlowControl
    from tests.test_assistant_flow_control import definition
    inject_outcome(env.gateway, tmp_path, monkeypatch)
    params = native_parameters("flow_save", {"team_id": "team-a", "flow_id": "flow-a", "expectedRevision": 0,
                                             "flow": definition()})
    save = FlowControl.save_flow

    def lost_adapter_ack(*args, **kwargs):
        save(*args, **kwargs)
        raise OSError("Adapter boundary acknowledgement lost")

    monkeypatch.setattr(FlowControl, "save_flow", lost_adapter_ack)
    with server_operator_scope("real-operator", roles=("operator",)):
        with pytest.raises(OSError):
            platform_actions.execute(env.gateway, "flow_save", params, marker(params))
        result = platform_actions.reconcile(env.gateway, "flow_save", params, marker(params))
    assert result["state"] == "confirmed" and result["evidence"] == "native_outcome"


def test_team_adapter_ack_is_persisted_before_its_return_can_be_lost(knowledge_env, tmp_path, monkeypatch):
    from core.web.services.external_management.asset_control import AssetControl
    from tests.test_assistant_asset_control import Native as AssetNative
    native = AssetNative()
    inject_outcome(native, tmp_path, monkeypatch)
    team_id = knowledge_env["team"]["teamId"]
    update = AssetControl.update_team
    with server_operator_scope("real-operator", roles=("operator",)):
        before = AssetControl(native).read_team(team_id)
        params = native_parameters("team_update", {"team_id": team_id, "expected_team_fingerprint": before["fingerprint"],
                                                   "updates": {"name": "receipt-owned-name"}})

        def lost_adapter_ack(*args, **kwargs):
            update(*args, **kwargs)
            raise OSError("Asset adapter acknowledgement lost")

        monkeypatch.setattr(AssetControl, "update_team", lost_adapter_ack)
        with pytest.raises(OSError):
            platform_actions.execute(native, "team_update", params, marker(params))
        result = platform_actions.reconcile(native, "team_update", params, marker(params))
    assert result["state"] == "confirmed" and result["evidence"] == "native_outcome"


def test_research_ledger_recovers_internal_lost_ack_without_native_replay(env, research, tmp_path, monkeypatch):
    from tests.test_assistant_research_control import fail_attempt
    inject_outcome(env.gateway, tmp_path, monkeypatch)
    fail_attempt(research)
    params = native_parameters("research_command", {"run_id": "run-test", **research.refs, "command": "retry_node",
        "node_id": "problem_understanding", "expected_revision": "2"})
    submit, calls = research.harness.command_service.submit, []

    def lose_ack(request):
        calls.append(request)
        submit(request)
        raise OSError("Formal Ledger committed before lost acknowledgement")

    monkeypatch.setattr(research.harness.command_service, "submit", lose_ack)
    with server_operator_scope("real-operator", roles=("operator",)):
        with pytest.raises(ManagementError, match="OPERATION_UNCONFIRMED"):
            platform_actions.execute(env.gateway, "research_command", params, marker(params))
        before = research.harness.store.list_events("run-test")
        result = platform_actions.reconcile(env.gateway, "research_command", params, marker(params))
        assert result["state"] == "confirmed" and result["evidence"] == "research_ledger"
        assert research.harness.store.list_events("run-test") == before
        assert result["result"]["receipt"]["requestId"] == marker(params)["requestKey"]
    assert len(calls) == 1 and len(research.harness.store.list_attempts("run-test")) == 2


def research_ack(params, proof):
    return {"operation": {"kind": "research_run", "resourceId": params["run_id"], "teamId": params["team_id"],
        "flowId": params["flow_id"], "status": "running", "revision": "3", "agentId": "", "sessionId": "",
        "commands": ["stop"], "progressFingerprint": None}, "command": params["command"], "accepted": True,
        "revisionCheck": "native_cas", "untrustedContent": True,
        "receipt": {"commandId": "cmd-a", "runId": params["run_id"], "teamId": params["team_id"],
            "flowId": params["flow_id"], "command": params["command"], "requestId": proof["requestKey"],
            "expectedRevision": "2", "acceptedRevision": "3", "nodeId": params["node_id"], "taskId": "",
            "decision": "", "checkpointId": "", "childRunId": ""}}


@pytest.mark.parametrize("field,value", [("runId", "other-run"), ("teamId", "other-team"),
    ("flowId", "other-flow"), ("command", "reconcile_run"), ("requestId", "c" * 64),
    ("expectedRevision", "1"), ("nodeId", "other-node"), ("taskId", "other-task"),
    ("decision", "accept"), ("checkpointId", "forged-checkpoint"), ("extra", "SECRET")])
def test_research_native_outcome_requires_exact_marker_and_semantic_target(owner, field, value):
    params = native_parameters("research_command", {"run_id": "research-a", "team_id": "team-a", "flow_id": "flow-a",
        "command": "retry_node", "node_id": "node-a", "expected_revision": "2"})
    proof = marker(params)
    raw = research_ack(params, proof)
    raw["receipt"][field] = value
    with pytest.raises((ValueError, KeyError)):
        closed = platform_actions.native_result("research_command", raw)
        platform_actions.verify_target("research_command", closed, params, proof)
    assert not owner.outcome.root.exists()


def test_public_receipt_allows_only_the_research_result_field(owner):
    params = native_parameters("research_command", {"run_id": "research-a", "team_id": "team-a", "flow_id": "flow-a",
        "command": "retry_node", "node_id": "node-a", "expected_revision": "2"})
    raw = {"status": "completed", "action": "research_command", "requestId": "outer-id", "verified": True,
           "reused": False, "research": research_ack(params, marker(params))}
    assert platform_actions.public_receipt(raw, "research_command", "outer-id", params)["verified"] is True
    with pytest.raises(ValueError):
        platform_actions.public_receipt({**raw, "operation": Native(owner.native.project_root).runtime_command(parameters(), {})},
                                        "research_command", "outer-id", params)


def test_read_of_missing_proof_does_not_create_store_or_lock(owner):
    params = parameters()
    assert platform_actions.reconcile(owner.native, "runtime_command", params, marker(params))["state"] == "requires_review"
    assert not owner.outcome.root.exists()


def test_public_runtime_command_receipt_preserves_the_old_closed_operation_shape(owner):
    raw = {"status": "completed", "action": "runtime_command", "requestId": "outer-id", "verified": True,
           "reused": False, "operation": owner.native.runtime_command(parameters(), {})}
    result = platform_actions.public_receipt(raw, "runtime_command", "outer-id", parameters())
    assert "progressFingerprint" not in result["operation"]["operation"]
