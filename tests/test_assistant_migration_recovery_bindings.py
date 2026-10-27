"""Recovery migration observes source authority without transferring it."""
import copy
import json
from pathlib import Path

import pytest

from core.assistant_runtime import migration_recovery_bindings as owner
from core.assistant_runtime.migration_io import MigrationIOError


def flow(binding=True):
    policy = {"repairFlowId": "repair", "directorAgentId": "director", "reviewerAgentId": "reviewer"}
    if binding:
        policy.update(assistantAgentId="assistant", developerAgentId="developer", bindingId="binding-old",
            expiresAt="2099-01-01T00:00:00+00:00", repairFlowRevision=2,
            agentPolicyFingerprints={role: "a" * 64 for role in ("assistant", "director", "developer", "reviewer")})
    return {"id": "flow", "name": "PRIVATE_COMMAND", "description": "PRIVATE_SECRET",
        "revision": 7, "steps": [{"id": "work", "label": "Private", "kind": "agent", "owner": "director",
            "instruction": "PRIVATE_COMMAND"}], "failureRecovery": policy}


def grant(scope="session", status="applied"):
    return {"eventId": "request-1", "requestId": "request-1", "kind": "tool_governance_request",
        "status": status, "grantScope": scope, "targetAgentId": "assistant", "sourceSessionId": "session-1",
        "sourceTurnId": "turn-1" if scope == "turn" else "", "reason": "PRIVATE_GRANT_REASON",
        "policyDelta": {"grantTools": ["PRIVATE_TOOL"]}, "temporaryGrant": {
            "scope": scope, "sessionId": "session-1", "turnId": "turn-1" if scope == "turn" else "",
            "grantTools": ["PRIVATE_TOOL"], "appliedAt": "2026-01-01T00:00:00+00:00"}}


def source(tmp_path):
    workspace = tmp_path / "workspace"
    root = workspace / "teams/team-1/generic-workflows"
    for kind in ("flows", "runs"):
        (root / kind).mkdir(parents=True)
    (root / "flows/flow.json").write_text(json.dumps(flow()), encoding="utf-8")
    run = {"id": "run-1", "teamId": "team-1", "flow": flow(False), "values": {}, "status": "running",
        "current": 0, "revision": 3, "_createFingerprint": "a" * 64, "_taskRosterVersion": 1}
    (root / "runs/run-1.json").write_text(json.dumps(run), encoding="utf-8")
    grants = workspace / "agents/assistant/events/tool_governance_requests.jsonl"
    grants.parent.mkdir(parents=True)
    grants.write_text(json.dumps(grant()) + "\n" + json.dumps(grant("turn", "pending_review")) + "\n", encoding="utf-8")
    return workspace, root, grants


def inspect(workspace, **kwargs):
    kwargs.setdefault("agent_row", {"agentId": "assistant", "workspacePath": "workspace/agents/assistant"})
    kwargs.setdefault("project_root", workspace.parent)
    return owner.inventory_recovery_bindings(workspace=workspace, agent_id="assistant", project_id="project",
        instance_id="instance", **kwargs)


def bytes_in(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_saved_and_frozen_legacy_policies_stay_in_source_and_report_is_private(tmp_path):
    workspace, root, _ = source(tmp_path)
    before = bytes_in(tmp_path)
    result = inspect(workspace)
    report = result.report
    assert bytes_in(tmp_path) == before
    assert report["sourceQuiesced"] is False and report["readyForCutover"] is False
    assert report["inventoryComplete"] is True
    assert {(row["type"], row["status"], row["bindingId"], row["flowRevision"], row.get("runRevision"))
            for row in report["bindings"]} == {("saved_flow", "bound", "binding-old", 7, None),
                                               ("frozen_run", "legacy", "", 7, 3)}
    for row in report["bindings"]:
        assert row["disposition"] == "retained_in_source"
        assert row["requires_native_reauthorization"] is True and row["proofStatus"] == "unresolved"
    assert report["temporaryGrants"]["counts"] == {"session": {"applied": 1, "pending_review": 0, "rejected": 0},
        "turn": {"applied": 0, "pending_review": 1, "rejected": 0}}
    assert report["temporaryGrants"]["processGrantsAbsentProven"] is False
    public = json.dumps(report) + repr(result)
    assert not any(text in public for text in ("PRIVATE", str(root), ".json", "session-1", "turn-1", "a" * 64))
    assert len(result.snapshots) == 3 and result.directoryproofs
    owner.verify_recovery_inventory(result)


def test_frozen_bound_policy_is_not_removed_when_saved_flow_is_unbound(tmp_path):
    workspace, root, _ = source(tmp_path)
    saved = flow()
    frozen = {"id": "run-1", "teamId": "team-1", "flow": saved, "values": {}, "status": "waiting", "current": 0, "revision": 4}
    (root / "runs/run-1.json").write_text(json.dumps(frozen), encoding="utf-8")
    saved = copy.deepcopy(saved)
    saved["failureRecovery"] = None
    (root / "flows/flow.json").write_text(json.dumps(saved), encoding="utf-8")
    assert [row["type"] for row in inspect(workspace).report["bindings"]] == ["frozen_run"]


def test_other_assistant_binding_is_not_reported_as_this_agents_handoff(tmp_path):
    workspace, root, _ = source(tmp_path)
    other = flow()
    other["failureRecovery"]["assistantAgentId"] = "other-assistant"
    other["failureRecovery"]["agentPolicyFingerprints"].pop("assistant")
    other["failureRecovery"]["agentPolicyFingerprints"]["other-assistant"] = "b" * 64
    (root / "flows/flow.json").write_text(json.dumps(other), encoding="utf-8")
    rows = inspect(workspace).report["bindings"]
    assert all(row["type"] != "saved_flow" for row in rows)
    assert len(rows) == 1 and rows[0]["type"] == "frozen_run"
    assert rows[0]["sourceRelationship"] == "legacy_unresolved"


def test_binding_referencing_old_assistant_as_workflow_owner_is_retained(tmp_path):
    workspace, root, _ = source(tmp_path)
    other = flow()
    other["failureRecovery"]["assistantAgentId"] = "other-assistant"
    other["failureRecovery"]["agentPolicyFingerprints"]["other-assistant"] = "b" * 64
    other["steps"][0]["owner"] = "assistant"
    (root / "flows/flow.json").write_text(json.dumps(other), encoding="utf-8")
    row = next(row for row in inspect(workspace).report["bindings"] if row["type"] == "saved_flow")
    assert row["sourceRelationship"] == "references_source_assistant"


def test_all_runs_are_observed_beyond_native_default_page_limit(tmp_path):
    workspace, root, _ = source(tmp_path)
    original = json.loads((root / "runs/run-1.json").read_text())
    for number in range(2, 105):
        run = {**original, "id": f"run-{number}"}
        (root / f"runs/run-{number}.json").write_text(json.dumps(run), encoding="utf-8")
    assert len(inspect(workspace).report["bindings"]) == 105


@pytest.mark.parametrize("damage", ["unknown", "unknown_policy", "malformed", "wrong_id", "bool_revision", "unsafe_binding", "unknown_private"])
def test_bad_sources_raise_without_truncated_success(tmp_path, damage):
    workspace, root, _ = source(tmp_path)
    target = root / "flows/flow.json"
    value = flow()
    if damage == "unknown": value["futureAuthorization"] = {}
    if damage == "unknown_policy": value["failureRecovery"]["futureGrant"] = True
    if damage == "wrong_id": value["id"] = "different"
    if damage == "bool_revision": value["revision"] = True
    if damage == "unsafe_binding": value["failureRecovery"]["bindingId"] = "SECRET/path"
    if damage == "unknown_private":
        target = root / "runs/run-1.json"
        value = json.loads(target.read_text())
        value["_newAuthority"] = {}
    target.write_text('{"revision":1,"revision":2}' if damage == "malformed" else json.dumps(value), encoding="utf-8")
    with pytest.raises(MigrationIOError): inspect(workspace)


@pytest.mark.parametrize("budget", [{"max_files": 2}, {"max_file_bytes": 4}, {"max_total_bytes": 4},
    {"max_grant_records": 1}, {"max_files": True}, {"max_files": 10001}])
def test_caps_refuse_instead_of_reporting_partial_inventory(tmp_path, budget):
    workspace, _, _ = source(tmp_path)
    with pytest.raises(MigrationIOError): inspect(workspace, **budget)


def test_missing_sources_are_unresolved_not_proof_of_absent_runtime_authority(tmp_path):
    workspace, root, grants = source(tmp_path)
    grants.unlink()
    (root / "runs/run-1.json").unlink()
    (root / "runs").rmdir()
    result = inspect(workspace)
    assert result.report["inventoryComplete"] is False
    assert result.report["temporaryGrants"]["status"] == "unresolved"
    assert result.report["temporaryGrants"]["processGrantsAbsentProven"] is False
    owner.verify_recovery_inventory(result)
    grants.write_text("", encoding="utf-8")
    with pytest.raises(MigrationIOError): owner.verify_recovery_inventory(result)


@pytest.mark.parametrize("change", ["file", "directory", "new_file"])
def test_private_proofs_reject_later_source_changes(tmp_path, change):
    workspace, root, _ = source(tmp_path)
    result = inspect(workspace)
    if change == "file": (root / "flows/flow.json").write_text("{}", encoding="utf-8")
    if change == "directory": (root / "runs/run-1.json").unlink(); (root / "runs").rmdir()
    if change == "new_file": (root / "flows/new.json").write_text("{}", encoding="utf-8")
    with pytest.raises(MigrationIOError): owner.verify_recovery_inventory(result)


def test_midscan_mutation_is_rejected(tmp_path, monkeypatch):
    workspace, root, _ = source(tmp_path)
    original = owner.read_stable_file
    def changing(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if path == root / "runs/run-1.json": path.write_text("{}", encoding="utf-8")
        return result
    monkeypatch.setattr(owner, "read_stable_file", changing)
    with pytest.raises(MigrationIOError): inspect(workspace)


@pytest.mark.parametrize("damage", ["unknown", "scope", "status", "wrong_agent", "malformed", "nested_unknown"])
def test_grant_records_are_closed_and_strict(tmp_path, damage):
    workspace, _, grants = source(tmp_path)
    value = grant()
    if damage == "unknown": value["futureGrant"] = {}
    if damage == "scope": value["grantScope"] = "global"
    if damage == "status": value["status"] = "SECRET_STATUS"
    if damage == "wrong_agent": value["targetAgentId"] = "other"
    if damage == "nested_unknown": value["temporaryGrant"]["futureGrant"] = {}
    grants.write_text("not-json\n" if damage == "malformed" else json.dumps(value) + "\n", encoding="utf-8")
    with pytest.raises(MigrationIOError): inspect(workspace)


def test_linked_source_is_never_followed(tmp_path):
    workspace, root, _ = source(tmp_path)
    target = root / "flows/flow.json"
    outside = tmp_path / "outside.json"
    target.replace(outside)
    try: target.symlink_to(outside)
    except OSError: pytest.skip("native symlink privilege unavailable")
    with pytest.raises(MigrationIOError): inspect(workspace)


def test_native_private_local_integration_authority_is_observed_without_copying(tmp_path):
    workspace, root, _ = source(tmp_path)
    target = root / "runs/run-1.json"
    value = json.loads(target.read_text())
    value["flow"] = flow()
    value["_codeRepairRequest"] = {"acknowledge": True, "allowedFiles": ["core/PRIVATE_SOURCE.py"],
        "teamId": "team-1", "validForSeconds": 60}
    value["_codeRepairAuthorization"] = {"authorizationId": "local-integration-private", "operatorId": "PRIVATE_OPERATOR",
        "runId": "run-1", "issuedAt": "2026-01-01T00:00:00+00:00", "expiresAt": "2099-01-01T00:00:00+00:00",
        "revoked": False, "allowedFiles": ["core/PRIVATE_SOURCE.py"], "teamId": "team-1", "requestDigest": "b" * 64,
        "roleBindingSource": "recovery_binding_v1", "principals": {role: {"agentId": role, "fingerprint": "c" * 64}
            for role in ("observer", "executor", "reviewer")}}
    value["_codeRepairSource"] = {"teamId": "team-1", "runId": "run-1", "flowId": "flow", "bindingId": "binding-old",
        "issueId": "issue-1", "repairRunId": "repair-1", "sourceAttemptKey": "PRIVATE_ATTEMPT"}
    target.write_text(json.dumps(value), encoding="utf-8")
    before = bytes_in(tmp_path)
    result = inspect(workspace)
    assert len(result.report["bindings"]) == 2 and bytes_in(tmp_path) == before
    assert "PRIVATE" not in json.dumps(result.report)
    value["_codeRepairAuthorization"]["newGrant"] = {}
    target.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(MigrationIOError): inspect(workspace)


def test_missing_teams_and_pa_events_are_never_seeded(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    from core.web.services.team import team_store
    def forbidden(*args, **kwargs):
        pytest.fail("read-only inventory must not call native team root/seed helpers")
    monkeypatch.setattr(team_store, "_teams_root", forbidden)
    before = bytes_in(tmp_path)
    result = inspect(workspace)
    assert result.report["inventoryComplete"] is False and result.report["bindings"] == []
    assert list(workspace.iterdir()) == [] and bytes_in(tmp_path) == before


@pytest.mark.parametrize("field,value", [("agent_id", "../other"), ("agent_id", "a" * 129),
    ("project_id", ""), ("instance_id", "PRIVATE/path"), ("project_id", True)])
def test_source_identity_is_validated_before_any_path_probe(tmp_path, monkeypatch, field, value):
    def forbidden(*args, **kwargs): pytest.fail("invalid identity must fail before filesystem probes")
    monkeypatch.setattr(owner, "check_path", forbidden)
    args = dict(workspace=tmp_path, agent_id="assistant", project_id="project", instance_id="instance")
    args[field] = value
    with pytest.raises(MigrationIOError): owner.inventory_recovery_bindings(**args)


def test_new_file_during_snapshot_revalidation_invalidates_directory_proof(tmp_path, monkeypatch):
    workspace, root, _ = source(tmp_path)
    result = inspect(workspace)
    original = owner.verify_snapshot
    def changed(snapshot):
        original(snapshot)
        if snapshot.path.name == "tool_governance_requests.jsonl":
            (root / "runs/new.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(owner, "verify_snapshot", changed)
    with pytest.raises(MigrationIOError): owner.verify_recovery_inventory(result)


def test_custom_workspace_requires_authorization_and_never_reads_canonical_residual(tmp_path, monkeypatch):
    workspace, _, canonical = source(tmp_path)
    custom = workspace / "agents/custom-assistant/events/tool_governance_requests.jsonl"
    custom.parent.mkdir(parents=True)
    custom.write_text(json.dumps(grant("turn")) + "\n", encoding="utf-8")
    canonical.write_text("PRIVATE_STALE_CANONICAL_NOT_JSON", encoding="utf-8")
    original = owner.read_stable_file
    def guarded(path, *args, **kwargs):
        assert path not in {custom, canonical}, "unapproved logs must not be read"
        return original(path, *args, **kwargs)
    monkeypatch.setattr(owner, "read_stable_file", guarded)
    before = bytes_in(tmp_path)
    result = inspect(workspace, agent_row={"agentId": "assistant", "workspacePath": "workspace/agents/custom-assistant"})
    assert result.report["inventoryComplete"] is False
    assert result.report["temporaryGrants"]["status"] == "unresolved"
    assert result.report["temporaryGrants"]["reason"] == "explicit_governance_path_authorization_required"
    assert all(count == 0 for statuses in result.report["temporaryGrants"]["counts"].values() for count in statuses.values())
    assert bytes_in(tmp_path) == before


def test_authorized_custom_workspace_counts_only_declared_source_not_canonical_residual(tmp_path, monkeypatch):
    workspace, _, canonical = source(tmp_path)
    custom = workspace / "agents/custom-assistant/events/tool_governance_requests.jsonl"
    custom.parent.mkdir(parents=True)
    custom.write_text(json.dumps(grant("turn")) + "\n", encoding="utf-8")
    canonical.write_text("PRIVATE_STALE_CANONICAL_NOT_JSON", encoding="utf-8")
    original = owner.read_stable_file
    def guarded(path, *args, **kwargs):
        assert path != canonical, "registry authority must override canonical residual"
        return original(path, *args, **kwargs)
    monkeypatch.setattr(owner, "read_stable_file", guarded)
    before = bytes_in(tmp_path)
    result = inspect(workspace, agent_row={"agentId": "assistant", "workspacePath": "workspace/agents/custom-assistant"},
        authorized_governance_path=custom)
    assert result.report["inventoryComplete"] is True
    assert result.report["temporaryGrants"]["status"] == "observed"
    assert result.report["temporaryGrants"]["counts"]["turn"]["applied"] == 1
    assert result.report["temporaryGrants"]["counts"]["session"]["applied"] == 0
    assert canonical not in {snapshot.path for snapshot in result.snapshots}
    assert custom in {snapshot.path for snapshot in result.snapshots}
    assert "custom-assistant" not in json.dumps(result.report) and bytes_in(tmp_path) == before
    custom.write_text("", encoding="utf-8")
    with pytest.raises(MigrationIOError): owner.verify_recovery_inventory(result)


@pytest.mark.parametrize("row", [None, {"agentId": "assistant"}, {"agentId": "assistant", "workspacePath": ""}])
def test_missing_registry_workspace_never_falls_back_to_existing_canonical(tmp_path, row):
    workspace, _, canonical = source(tmp_path)
    canonical.write_text("PRIVATE_STALE_CANONICAL_NOT_JSON", encoding="utf-8")
    result = inspect(workspace, agent_row=row)
    assert result.report["inventoryComplete"] is False
    assert result.report["temporaryGrants"]["status"] == "unresolved"
    assert canonical not in {snapshot.path for snapshot in result.snapshots}


def test_custom_authorization_must_match_registry_declared_workspace(tmp_path):
    workspace, _, canonical = source(tmp_path)
    with pytest.raises(MigrationIOError, match="governance_path_authority_mismatch"):
        inspect(workspace, agent_row={"agentId": "assistant", "workspacePath": "workspace/agents/custom-assistant"},
            authorized_governance_path=canonical)
