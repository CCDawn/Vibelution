"""Existing native evidence is observed; no task is accepted, woken or replayed."""
import hashlib
import json
from pathlib import Path

import pytest

from core.assistant_runtime import legacy_correlation as owner
from core.assistant_runtime.legacy_handoff import preview_legacy_handoff


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def source(tmp_path, *, completed=False, business_completed=False, consumed=True, run=True):
    project = tmp_path / "project"
    workspace = tmp_path / "data/workspace"
    project.mkdir()
    registry = workspace / "agents/agents.json"
    agents = [{"agentId": "pa", "directSessionId": "pa-session", "roleKey": "personal_assistant", "status": "active",
               "metadata": {"personalAssistantProfile": "personal_assistant_v1"}, "toolPolicy": {}},
              {"agentId": "target", "directSessionId": "target-session", "status": "active", "metadata": {}}]
    write_json(registry, {"agents": agents})
    inbox = workspace / "agents/target/events/agent_inbox_messages.jsonl"
    dispatch = {"messageId": "dispatch", "eventId": "dispatch", "sourceAgentId": "pa", "targetAgentId": "target",
                "sourceSessionId": "pa-session", "targetSessionId": "target-session", "kind": "agent_direct_message",
                "status": "consumed" if consumed else "pending", "metadata": {}, "content": "PRIVATE_DISPATCH"}
    if consumed:
        dispatch.update(consumedBySessionId="target-session", consumedByTurnId="turn-real")
    write_rows(inbox, [dispatch])
    pa_inbox = workspace / "agents/pa/events/agent_inbox_messages.jsonl"
    receipt = {"messageId": "reply", "eventId": "reply", "sourceAgentId": "target", "targetAgentId": "pa",
               "sourceSessionId": "target-session", "targetSessionId": "pa-session", "status": "pending", "kind": "agent_inbox_reply",
               "metadata": {"replyToMessageId": "dispatch", "sourceTurnId": "turn-real"}, "content": "PRIVATE_REPLY"}
    if business_completed:
        receipt["metadata"]["personalAssistantTask"] = {"schemaVersion": 1, "dispatchMessageId": "dispatch",
                "status": "completed", "evidenceRefs": ["evidence:result"]}
    write_rows(pa_inbox, [receipt] if business_completed else [])
    journal = workspace / "sessions/target-session/turn_journal.jsonl"
    metadata = {"kind": "agent_inbox_message", "messageId": "dispatch", "sourceAgentId": "pa",
                "sourceSessionId": "pa-session", "targetAgentId": "target", "targetSessionId": "target-session", "turnId": "turn-real"}
    events = [{"schemaVersion": 2, "eventId": "started", "sessionId": "target-session", "turnId": "turn-real",
               "sequence": 1, "eventType": "turn_started", "payload": {"agentId": "target"}},
              {"schemaVersion": 2, "eventId": "input", "sessionId": "target-session", "turnId": "turn-real",
               "sequence": 2, "eventType": "user_message", "payload": {"content": "PRIVATE_PROMPT", "metadata": metadata}}]
    if completed:
        events.append({"schemaVersion": 1, "eventId": "done", "sessionId": "target-session", "turnId": "turn-real",
                       "sequence": 3, "eventType": "turn_completed", "payload": {}})
    write_rows(journal, events)
    runtime = tmp_path / "native-runtime"
    runtime.mkdir()
    snapshot = runtime / "runtime-manager/work_runs/chat_turn/runs/turn-real.json"
    if run:
        write_json(snapshot, {"runId": "turn-real", "runKind": "chat_turn", "sessionId": "target-session",
                              "agentId": "target", "status": "running", "userMessage": "PRIVATE_RUN_PROMPT"})
    args = dict(project_root=project, workspace=workspace, project_id="project", instance_id="instance", assistant_agent_id="pa")
    return dict(args=args, registry=registry, inbox=inbox, pa_inbox=pa_inbox, journal=journal, runtime=runtime, run=snapshot)


def preview(fixture):
    result = preview_legacy_handoff(**fixture["args"])
    assert result["previewComplete"], result["issues"]
    return result


def correlate(fixture, value=None, **kwargs):
    return owner.correlate_legacy_dispatches(value or preview(fixture), workspace=fixture["args"]["workspace"],
                                           runtime_root=fixture["runtime"], **kwargs)


def item(report):
    return report["dispatches"][0]


def disk(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("completed,business", [(False, False), (True, False), (True, True)])
def test_native_turn_run_and_business_status_are_separate_read_only_facts(tmp_path, completed, business):
    fixture = source(tmp_path, completed=completed, business_completed=business)
    before = disk(tmp_path)
    result = correlate(fixture)
    assert disk(tmp_path) == before
    row = item(result)
    assert result["correlationComplete"] and row["nativeCorrelation"] == "correlated"
    assert row["nativeTurnId"] == row["nativeRunId"] == "turn-real"
    assert row["nativeTaskId"] is None and not row["canRedispatch"]
    assert row["nativeTurnStatus"] == ("completed" if completed else "running")
    assert (row["businessTaskStatus"] == "completed") is business
    assert not result["readyForCutover"] and not result["sourceQuiesced"]
    assert all(value not in json.dumps(result) for value in ("PRIVATE_", str(tmp_path), "file:///"))


def test_no_runtime_root_or_actual_snapshot_means_no_invented_run(tmp_path):
    fixture = source(tmp_path, run=False)
    result = correlate(fixture)
    assert item(result)["nativeTurnId"] == "turn-real" and item(result)["nativeRunId"] is None
    assert item(result)["nativeRunReason"] == "native_run_missing"
    result = owner.correlate_legacy_dispatches(preview(fixture), workspace=fixture["args"]["workspace"])
    assert item(result)["nativeRunId"] is None and item(result)["nativeRunReason"] == "runtime_root_not_supplied"


def test_accepted_journal_without_consume_receipt_is_never_redispatched(tmp_path):
    fixture = source(tmp_path, consumed=False)
    row = item(correlate(fixture))
    assert row["nativeCorrelation"] == "unresolved" and row["reason"] == "consume_receipt_missing"
    assert row["nativeTurnId"] == "turn-real" and row["nativeTaskId"] is None
    assert row["canRedispatch"] is False


@pytest.mark.parametrize("field,value", [("consumedBySessionId", "other"), ("consumedByTurnId", "wrong"),
                                         ("consumedByTurnId", ""), ("status", "pending")])
def test_wrong_consumption_never_binds_a_new_or_unrelated_turn(tmp_path, field, value):
    fixture = source(tmp_path)
    rows = read_rows(fixture["inbox"])
    rows[0][field] = value
    write_rows(fixture["inbox"], rows)
    row = item(correlate(fixture))
    assert row["reason"] == "consumed_identity_mismatch" and row["nativeTurnId"] is None


@pytest.mark.parametrize("field,value", [("messageId", "other"), ("sourceAgentId", "other"),
    ("targetAgentId", "other"), ("sourceSessionId", "other"), ("targetSessionId", "other"), ("turnId", "other")])
def test_journal_identity_requires_exact_routing(tmp_path, field, value):
    fixture = source(tmp_path)
    rows = read_rows(fixture["journal"])
    rows[1]["payload"]["metadata"][field] = value
    write_rows(fixture["journal"], rows)
    row = item(correlate(fixture))
    assert row["nativeCorrelation"] == "unresolved" and row["nativeTurnId"] is None
    assert row["reason"] in {"journal_dispatch_missing", "journal_dispatch_routing_mismatch"}


def test_native_started_event_proves_target_ownership(tmp_path):
    fixture = source(tmp_path)
    rows = read_rows(fixture["journal"])
    rows[0]["payload"]["agentId"] = "other"
    write_rows(fixture["journal"], rows)
    assert item(correlate(fixture))["reason"] == "journal_turn_owner_unproven"


def test_receipt_source_turn_must_cross_check_native_proof(tmp_path):
    fixture = source(tmp_path, business_completed=True)
    rows = read_rows(fixture["pa_inbox"])
    rows[0]["metadata"]["sourceTurnId"] = "wrong-turn"
    write_rows(fixture["pa_inbox"], rows)
    row = item(correlate(fixture))
    assert row["reason"] == "receipt_turn_mismatch" and row["nativeTurnId"] is None


@pytest.mark.parametrize("field,value", [("runId", "other"), ("sessionId", "other"), ("agentId", "other"), ("runKind", "kernel")])
def test_native_run_is_read_and_identity_checked(tmp_path, field, value):
    fixture = source(tmp_path)
    run = json.loads(fixture["run"].read_text(encoding="utf-8"))
    run[field] = value
    write_json(fixture["run"], run)
    row = item(correlate(fixture))
    assert row["nativeRunId"] is None and row["reason"] == "native_run_identity_mismatch"


@pytest.mark.parametrize("duplicate", ["input", "started", "event_id"])
def test_duplicate_native_proof_is_not_silently_selected(tmp_path, duplicate):
    fixture = source(tmp_path)
    rows = read_rows(fixture["journal"])
    extra = dict(rows[1] if duplicate != "started" else rows[0])
    extra["sequence"] = 3
    if duplicate != "event_id": extra["eventId"] = "extra"
    rows.append(extra)
    write_rows(fixture["journal"], rows)
    row = item(correlate(fixture))
    assert row["nativeTurnId"] is None and row["nativeCorrelation"] == "unresolved"


def test_kernel_success_and_forged_preview_business_completion_do_not_complete_execution(tmp_path):
    fixture = source(tmp_path)
    write_json(fixture["args"]["workspace"] / "kernel/index.json", {"tasksById": {"dispatch": {"status": "succeeded"}}})
    value = preview(fixture)
    value["dispatches"][0]["taskStatus"] = "completed"
    value["dispatches"][0]["nativeTaskId"] = "dispatch"
    row = item(correlate(fixture, value))
    assert row["nativeTurnStatus"] == "running" and row["businessTaskStatus"] != "completed"
    assert row["nativeTaskId"] is None


@pytest.mark.parametrize("which", ["registry", "inbox", "pa_inbox"])
def test_stale_preview_authorities_are_reopened_and_hash_checked(tmp_path, which):
    fixture = source(tmp_path)
    value = preview(fixture)
    fixture[which].write_bytes(fixture[which].read_bytes() + b" ")
    result = correlate(fixture, value)
    assert not result["correlationComplete"] and item(result)["nativeTurnId"] is None
    assert result["issues"] == [{"code": "preview_source_changed"}]


def test_preview_success_cannot_select_unknown_targets_or_arbitrary_paths(tmp_path):
    fixture = source(tmp_path)
    value = preview(fixture)
    value["dispatches"][0]["targetAgentId"] = "unknown"
    assert item(correlate(fixture, value))["reason"] == "dispatch_identity_mismatch"
    result = correlate(fixture, inbox_paths={"target": tmp_path / "outside/inbox.jsonl"})
    assert result["issues"] == [{"code": "external_inbox_mapping_unsupported"}]


def test_trusted_internal_mapping_still_requires_bound_inbox_fingerprint(tmp_path):
    fixture = source(tmp_path)
    value = preview(fixture)
    mapped = fixture["args"]["workspace"] / "custom/target/events/agent_inbox_messages.jsonl"
    mapped.parent.mkdir(parents=True)
    mapped.write_bytes(fixture["inbox"].read_bytes())
    assert item(correlate(fixture, value, inbox_paths={"target": mapped}))["nativeTurnId"] == "turn-real"
    mapped.write_text("{}\n", encoding="utf-8")
    assert correlate(fixture, value, inbox_paths={"target": mapped})["issues"] == [{"code": "preview_source_changed"}]


def test_linked_journal_is_rejected_without_reading_its_body(tmp_path):
    fixture = source(tmp_path)
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes(fixture["journal"].read_bytes())
    fixture["journal"].unlink()
    try:
        fixture["journal"].symlink_to(outside)
    except OSError:
        pytest.skip("native symlink privilege unavailable")
    assert item(correlate(fixture))["reason"] == "linked_source"


@pytest.mark.parametrize("budget", [{"max_files": 1}, {"max_file_bytes": 4}, {"max_total_bytes": 4},
                                     {"max_rows": 1}, {"max_line_bytes": 4}])
def test_bounded_sources_never_yield_a_completed_correlation(tmp_path, budget):
    fixture = source(tmp_path)
    result = correlate(fixture, **budget)
    assert not result["correlationComplete"] and item(result)["nativeTurnId"] is None


def test_source_change_after_journal_scan_invalidates_all_associations(tmp_path, monkeypatch):
    fixture = source(tmp_path)
    original = owner.read_stable_file
    changed = False
    def changing(path, *args, **kwargs):
        nonlocal changed
        result = original(path, *args, **kwargs)
        if path == fixture["run"] and not changed:
            changed = True
            fixture["journal"].write_bytes(fixture["journal"].read_bytes() + b" ")
        return result
    monkeypatch.setattr(owner, "read_stable_file", changing)
    result = correlate(fixture)
    assert result["issues"] and item(result)["nativeTurnId"] is None


def test_no_execution_service_is_imported_or_called(tmp_path, monkeypatch):
    import builtins
    fixture = source(tmp_path)
    value = preview(fixture)
    original = builtins.__import__
    def importing(name, *args, **kwargs):
        assert name not in {"core.web.services.session_service", "core.web.services.agent_directory_service",
                            "core.web.services.external_agent.service", "core.web.services.session.submit"}
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", importing)
    assert correlate(fixture, value)["correlationComplete"]


def test_unsupported_journal_schema_is_unresolved(tmp_path):
    fixture = source(tmp_path)
    events = read_rows(fixture["journal"])
    events[0]["schemaVersion"] = 3
    write_rows(fixture["journal"], events)
    assert item(correlate(fixture))["reason"] == "journal_identity_invalid"


def test_linked_runtime_root_is_rejected(tmp_path):
    fixture = source(tmp_path)
    link = tmp_path / "runtime-link"
    try:
        link.symlink_to(fixture["runtime"], target_is_directory=True)
    except OSError:
        pytest.skip("native symlink privilege unavailable")
    result = owner.correlate_legacy_dispatches(preview(fixture), workspace=fixture["args"]["workspace"], runtime_root=link)
    assert result["issues"] == [{"code": "linked_source"}] and item(result)["nativeTurnId"] is None
