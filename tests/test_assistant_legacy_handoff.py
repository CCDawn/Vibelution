"""Legacy observations never admit or replay native work."""
import hashlib
import json
from pathlib import Path

import pytest

from core.assistant_runtime.legacy_handoff import preview_legacy_handoff


def fixture(tmp_path):
    workspace = tmp_path / "data/workspace"
    registry = workspace / "agents/agents.json"
    registry.parent.mkdir(parents=True)
    agents = [{"agentId": "pa", "directSessionId": "pa-session", "roleKey": "personal_assistant",
        "status": "active", "metadata": {"personalAssistantProfile": "personal_assistant_v1"}},
        {"agentId": "worker", "directSessionId": "worker-session", "status": "archived"}]
    registry.write_text(json.dumps({"agents": agents}), encoding="utf-8")
    dispatch = {"messageId": "dispatch-1", "sourceAgentId": "pa", "targetAgentId": "worker",
        "targetSessionId": "worker-session", "status": "consumed", "summary": "PRIVATE_PROSE",
        "metadata": {"sourceSessionId": "pa-session"}}
    receipt = {"messageId": "receipt-1", "sourceAgentId": "worker", "targetAgentId": "pa",
        "targetSessionId": "pa-session", "status": "pending", "summary": "PRIVATE_RECEIPT",
        "metadata": {"sourceSessionId": "worker-session", "replyToMessageId": "dispatch-1",
            "personalAssistantTask": {"schemaVersion": 1, "dispatchMessageId": "dispatch-1",
                "status": "completed", "evidenceRefs": ["PRIVATE_EVIDENCE"]}}}
    for aid, rows in (("pa", []), ("worker", [dispatch])):
        write(workspace, aid, rows)
    return workspace, registry, agents, dispatch, receipt


def write(workspace, aid, rows):
    path = workspace / "agents" / aid / "events/agent_inbox_messages.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def preview(tmp_path, workspace, **kwargs):
    return preview_legacy_handoff(project_root=tmp_path, workspace=workspace,
        project_id="project", instance_id="instance", assistant_agent_id="pa", **kwargs)


def snapshot(root):
    return {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_preview_late_receipt_restart_and_no_write_or_prose(tmp_path):
    workspace, _, _, _, receipt = fixture(tmp_path)
    before = snapshot(tmp_path)
    first = preview(tmp_path, workspace)
    assert first["previewComplete"] is True
    assert first["dispatches"][0]["taskStatus"] == "running"
    assert snapshot(tmp_path) == before
    write(workspace, "pa", [receipt])
    before = snapshot(tmp_path)
    result = preview(tmp_path, workspace)
    item = result["dispatches"][0]
    assert item["taskStatus"] == "completed"
    assert item["nativeTaskId"] is None and item["nativeCorrelation"] == "unresolved"
    assert item["legacyMessageId"] == "dispatch-1"
    assert item["receipts"] == [{"legacyMessageId": "receipt-1", "taskStatus": "completed", "evidenceCount": 1}]
    assert result["stage"] == "handoff_preview" and result["schemaVersion"] == 1
    assert result["sourceQuiesced"] is False and result["readyForCutover"] is False
    assert result["sourceScope"] == {"projectId": "project", "instanceId": "instance",
        "projectRoot": str(tmp_path.resolve()), "workspace": str(workspace.resolve())}
    assert preview(tmp_path, workspace)["dispatches"] == result["dispatches"]
    assert snapshot(tmp_path) == before
    assert "PRIVATE" not in json.dumps(result)


@pytest.mark.parametrize("conflict", ["dispatch", "receipt"])
def test_conflicting_native_message_and_event_identity_is_not_adopted(tmp_path, conflict):
    workspace, _, _, dispatch, receipt = fixture(tmp_path)
    row = dispatch if conflict == "dispatch" else receipt
    row["eventId"] = "different-native-id"
    write(workspace, "worker", [dispatch])
    write(workspace, "pa", [receipt])
    result = preview(tmp_path, workspace)
    assert result["previewComplete"] is False
    assert any(issue["code"] == "invalid_jsonl" for issue in result["issues"])
    assert all(item["taskStatus"] != "completed" for item in result["dispatches"])


@pytest.mark.parametrize("change", ["agent", "target_agent", "source_session", "target_session", "reply", "report_id", "evidence", "prose"])
def test_invalid_receipt_cannot_complete(tmp_path, change):
    workspace, _, _, _, receipt = fixture(tmp_path)
    if change == "agent": receipt["sourceAgentId"] = "other"
    if change == "target_agent": receipt["targetAgentId"] = "other"
    if change == "source_session": receipt["metadata"]["sourceSessionId"] = "other"
    if change == "target_session": receipt["targetSessionId"] = "other"
    if change == "reply": receipt["metadata"]["replyToMessageId"] = "other"
    if change == "report_id": receipt["metadata"]["personalAssistantTask"]["dispatchMessageId"] = "other"
    if change == "evidence": receipt["metadata"]["personalAssistantTask"]["evidenceRefs"] = []
    if change == "prose": receipt["metadata"].pop("personalAssistantTask")
    write(workspace, "pa", [receipt])
    result = preview(tmp_path, workspace)
    assert result["dispatches"][0]["taskStatus"] != "completed"
    assert result["counts"]["unresolvedReceipts"] == (0 if change == "target_agent" else 1)
    if change == "target_agent":
        assert result["previewComplete"] is False
        assert any(i["code"] == "inbox_target_conflict" for i in result["issues"])


@pytest.mark.parametrize("duplicate", ["dispatch", "receipt"])
def test_duplicate_ids_are_ambiguous(tmp_path, duplicate):
    workspace, _, _, dispatch, receipt = fixture(tmp_path)
    write(workspace, "pa", [receipt, receipt] if duplicate == "receipt" else [receipt])
    if duplicate == "dispatch": write(workspace, "worker", [dispatch, dispatch])
    result = preview(tmp_path, workspace)
    assert result["previewComplete"] is False
    assert all(item["taskStatus"] != "completed" for item in result["dispatches"])
    assert any(issue["code"] == "duplicate_message_id" for issue in result["issues"])


@pytest.mark.parametrize("data,limits,code", [
    (b'{bad}\n', {}, "invalid_jsonl"), (b'{}', {}, "truncated_jsonl"),
    (b'{"x":1,"x":2}\n', {}, "invalid_jsonl"),
    (b'{}\n{}\n', {"max_rows": 1}, "row_limit"),
    (b'{"x":"long"}\n', {"max_line_bytes": 5}, "line_limit"),
    (b'{}\n', {"max_file_bytes": 2}, "file_byte_limit"),
])
def test_bounded_corrupt_or_incomplete_sources(tmp_path, data, limits, code):
    workspace, _, _, _, _ = fixture(tmp_path)
    path = write(workspace, "worker", [])
    path.write_bytes(data)
    result = preview(tmp_path, workspace, **limits)
    assert result["previewComplete"] is False
    assert any(issue["code"] == code for issue in result["issues"])


def test_custom_workspace_is_unsupported_and_missing_is_incomplete(tmp_path):
    workspace, registry, agents, _, _ = fixture(tmp_path)
    agents[1]["workspacePath"] = "workspace/custom/PRIVATE_PATH"
    registry.write_text(json.dumps({"agents": agents}), encoding="utf-8")
    result = preview(tmp_path, workspace)
    assert result["previewComplete"] is False and result["dispatches"] == []
    assert any(i["code"] == "custom_workspace_unsupported" for i in result["issues"])
    assert "PRIVATE_PATH" not in json.dumps(result)
    agents[1].pop("workspacePath")
    registry.write_text(json.dumps({"agents": agents}), encoding="utf-8")
    write(workspace, "worker", []).unlink()
    assert any(i["code"] == "source_missing" for i in preview(tmp_path, workspace)["issues"])


def test_followups_excluded_and_registry_hash_pinned(tmp_path):
    workspace, registry, _, dispatch, _ = fixture(tmp_path)
    write(workspace, "worker", [dispatch, {**dispatch, "messageId": "followup", "kind": "pa_followup"}])
    result = preview(tmp_path, workspace)
    assert len(result["dispatches"]) == 1 and result["counts"]["excludedFollowups"] == 1
    assert result["registrySha256"] == hashlib.sha256(registry.read_bytes()).hexdigest()


def test_linked_inbox_never_reads_target(tmp_path, monkeypatch):
    workspace, _, _, _, _ = fixture(tmp_path)
    path = write(workspace, "worker", [])
    path.unlink()
    outside = tmp_path / "PRIVATE_OUTSIDE"
    outside.write_text("PRIVATE_PROSE", encoding="utf-8")
    try:
        path.symlink_to(outside)
    except OSError:
        pytest.skip("native symlink privilege unavailable")
    original = Path.open
    def opening(node, *args, **kwargs):
        assert node != path and node != outside
        return original(node, *args, **kwargs)
    monkeypatch.setattr(Path, "open", opening)
    result = preview(tmp_path, workspace)
    assert result["previewComplete"] is False
    assert any(i["code"] == "linked_source" for i in result["issues"])
    assert "PRIVATE" not in json.dumps(result)


def test_source_change_after_parsing_invalidates_task_conclusions(tmp_path, monkeypatch):
    from core.assistant_runtime import legacy_handoff as owner
    workspace, _, _, _, receipt = fixture(tmp_path)
    path = write(workspace, "pa", [receipt])
    original = owner._task_report
    def changing(row, dispatch):
        result = original(row, dispatch)
        path.write_bytes(path.read_bytes() + b"\n")
        return result
    monkeypatch.setattr(owner, "_task_report", changing)
    result = preview(tmp_path, workspace)
    assert result["previewComplete"] is False
    assert result["dispatches"][0]["taskStatus"] == "unresolved"
    assert any(i["code"] == "source_changed" for i in result["issues"])


@pytest.mark.parametrize("during_final", [False, True])
def test_open_descriptor_identity_must_match_checked_path(tmp_path, monkeypatch, during_final):
    workspace, _, _, _, receipt = fixture(tmp_path)
    path = write(workspace, "pa", [receipt])
    outside = tmp_path / "PRIVATE_ALTERNATE"
    outside.write_bytes(path.read_bytes())
    original, calls = Path.open, []
    def opening(node, *args, **kwargs):
        if node == path:
            calls.append(node)
            # First scan is the preview itself; inventory's one-byte probe
            # rejects this nonempty source before opening it.
            if len(calls) == (2 if during_final else 1):
                return original(outside, *args, **kwargs)
        return original(node, *args, **kwargs)
    monkeypatch.setattr(Path, "open", opening)
    result = preview(tmp_path, workspace)
    assert result["previewComplete"] is False
    assert any(i["code"] == "source_changed" for i in result["issues"])
    assert all(item["taskStatus"] != "completed" for item in result["dispatches"])


def test_strict_nested_json_and_registry_duplicate_keys(tmp_path):
    workspace, registry, _, dispatch, _ = fixture(tmp_path)
    dispatch["metadata"]["agentToolMetadataJson"] = '{"replyToMessageId":"one","replyToMessageId":"two"}'
    write(workspace, "worker", [dispatch])
    result = preview(tmp_path, workspace)
    assert result["previewComplete"] is False
    assert any(i["code"] == "invalid_jsonl" for i in result["issues"])
    registry.write_bytes(b'{"agents":[],"agents":[]}')
    result = preview(tmp_path, workspace)
    assert result["previewComplete"] is False and result["dispatches"] == []


@pytest.mark.parametrize("limits,code", [({"max_files": 1}, "registry_identity_invalid_or_file_limit"),
    ({"max_total_bytes": 1}, "total_byte_limit")])
def test_global_caps_are_explicit(tmp_path, limits, code):
    workspace, _, _, _, _ = fixture(tmp_path)
    result = preview(tmp_path, workspace, **limits)
    assert result["previewComplete"] is False
    assert any(i["code"] == code for i in result["issues"])


def test_no_repair_or_execution_apis_and_cli_is_additive(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace
    from core.web.services import agent_directory_service, personal_assistant_service
    import scripts.assistant_migration_inventory as cli
    workspace, _, _, _, _ = fixture(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail("read-only preview called a repairing service")
    monkeypatch.setattr(agent_directory_service, "load_state", forbidden)
    monkeypatch.setattr(personal_assistant_service, "profile_agent", forbidden)
    monkeypatch.setattr(cli, "resolve_active_project_storage_paths", lambda root: SimpleNamespace(
        project_root=tmp_path, data=workspace.parent, runtime=tmp_path / "runtime", project_id="project", instance_id="instance"))
    monkeypatch.setattr("sys.argv", ["inventory", "--project", str(tmp_path), "--handoff-preview", "pa"])
    before = snapshot(tmp_path)
    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out)["stage"] == "handoff_preview"
    monkeypatch.setattr("sys.argv", ["inventory", "--project", str(tmp_path)])
    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out)["stage"] == "inventory"
    assert snapshot(tmp_path) == before


def test_canonical_top_level_sessions_and_unrelated_human_messages(tmp_path):
    workspace, _, _, dispatch, receipt = fixture(tmp_path)
    for row in (dispatch, receipt):
        row["sourceSessionId"] = row["metadata"].pop("sourceSessionId")
        row["eventId"] = row["messageId"]
    human = {"messageId": "human-1", "eventId": "human-1", "sourceAgentId": "",
        "sourceSessionId": "", "targetAgentId": "worker", "targetSessionId": "worker-session",
        "kind": "agent_direct_message", "status": "pending", "createdBy": "user",
        "content": "PRIVATE_HUMAN", "metadata": {}}
    write(workspace, "worker", [dispatch, human])
    write(workspace, "pa", [receipt, {**human, "messageId": "human-2", "eventId": "human-2",
        "targetAgentId": "pa", "targetSessionId": "pa-session"}])
    result = preview(tmp_path, workspace)
    assert result["previewComplete"] is True
    assert result["dispatches"][0]["taskStatus"] == "completed"
    assert result["counts"]["unresolvedReceipts"] == 0
    assert "PRIVATE" not in json.dumps(result)
    human.update(messageId="dispatch-1", eventId="dispatch-1")
    write(workspace, "worker", [dispatch, human])
    result = preview(tmp_path, workspace)
    assert result["previewComplete"] is False
    assert any(i["code"] == "duplicate_message_id" for i in result["issues"])


@pytest.mark.parametrize("surface", ["dispatch", "receipt"])
def test_session_conflicts_and_wrong_inbox_cannot_establish_authority(tmp_path, surface):
    workspace, _, _, dispatch, receipt = fixture(tmp_path)
    row = dispatch if surface == "dispatch" else receipt
    row["sourceSessionId"] = "conflicting-session"
    write(workspace, "worker", [dispatch])
    write(workspace, "pa", [receipt])
    assert preview(tmp_path, workspace)["previewComplete"] is False
    row.pop("sourceSessionId")
    row["targetAgentId"] = "pa" if surface == "dispatch" else "worker"
    write(workspace, "worker", [dispatch])
    write(workspace, "pa", [receipt])
    result = preview(tmp_path, workspace)
    assert result["previewComplete"] is False
    assert any(i["code"] == "inbox_target_conflict" for i in result["issues"])


def test_missing_dispatch_session_stays_unresolved_without_current_session_guess(tmp_path):
    workspace, _, _, dispatch, receipt = fixture(tmp_path)
    dispatch["metadata"].pop("sourceSessionId")
    dispatch["sourceSessionId"] = ""
    write(workspace, "worker", [dispatch])
    write(workspace, "pa", [receipt])
    result = preview(tmp_path, workspace)
    assert result["previewComplete"] is False
    assert result["dispatches"][0]["sourceSessionId"] is None
    assert result["dispatches"][0]["taskStatus"] == "unresolved"
    assert result["dispatches"][0]["receipts"] == []


def test_preview_identity_reuse_never_runs_inventory_or_other_source_hashing(tmp_path, monkeypatch):
    from core.assistant_runtime import migration_inventory as inventory
    workspace, _, _, _, _ = fixture(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail("preview reentered filesystem inventory")
    monkeypatch.setattr(inventory, "inventory_sources", forbidden)
    monkeypatch.setattr(inventory, "_hash_file", forbidden)
    result = preview(tmp_path, workspace)
    assert result["previewComplete"] is True
    assert len(result["dispatches"]) == 1
