"""Launcher adapters retain the native Team recovery and operator boundaries."""
from copy import deepcopy

import pytest

from tests.test_assistant_platform_watch import dispatch_setup, operation, platform, refresh
from tests.test_launcher_assistant_runtime_operations import env, native_run, write


def test_team_waiting_notifies_once_and_does_not_confirm_or_repeat_after_restart(platform, monkeypatch):
    from core.assistant_runtime import patrol
    from core.web.services.session import proactive
    root, dispatch, watcher = platform
    dispatch.management.rows["team_run"] = [operation("team_run", status="waiting")]
    calls = []
    monkeypatch.setattr(proactive, "submit_session_proactive_turn", lambda **kw: calls.append(kw) or {"accepted": True})
    assert refresh(watcher, 10000) == []
    events = refresh(watcher, 10301)
    assert len(events) == 1 and events[0]["issue"] == "attention_required"
    assert events[0]["status"] == "waiting"
    assert watcher.inspect(events, now=10301)["wake"] == "accepted"
    assert watcher.inspect(refresh(watcher, 10700), now=10700)["wake"] == "none"
    watcher.close()
    restarted = patrol.LauncherPatrol(root, "pa", "session", dispatch)
    assert restarted.inspect(refresh(restarted, 11000), now=11000)["wake"] == "none"
    assert len(calls) == 1


def recovery_run(env, *, status="awaiting_deployment"):
    import json
    path = native_run(env, status="failed", revision=3)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["recovery"] = {"issueId": "issue-a", "nodeId": "human", "status": status,
        "failureCount": 2, "repairAttempts": 1, "repairRunId": "repair-a", "codeRepairRunId": "code-a",
        "reason": "code_integrated_user_deployment_required", "evidenceRefs": ["git:" + "a" * 40],
        "reviewerSessionId": "PRIVATE-session", "reviewerTurnId": "PRIVATE-turn"}
    write(path, raw)
    return path, raw


def test_recovery_metadata_is_read_only_bounded_and_does_not_change_old_wire(env):
    from core.web.services.external_management import runtime_operations as operations
    from core.web.services.external_management import team_recovery_control as recovery
    path, raw = recovery_run(env)
    before = path.read_bytes()
    result = recovery.read(env.gateway, {"team_id": "team-a", "flow_id": "flow-a", "run_id": "run-a"})
    assert result["commands"] == ["confirm_deployment"]
    assert result["recovery"]["status"] == "awaiting_deployment"
    assert result["businessAcceptance"] == "not_evaluated"
    assert "PRIVATE" not in str(result) and "SECRET" not in str(result)
    assert "evidenceRefs" not in result["recovery"]
    assert path.read_bytes() == before
    original = operations._project("team_run", raw)
    assert "recovery" not in original and "confirm_deployment" not in original["commands"]


def test_native_recovery_progress_changes_fingerprint_without_heartbeat(env):
    from core.web.services.external_management.runtime_operations import _progress_fingerprint
    _, raw = recovery_run(env, status="repairing")
    before = _progress_fingerprint("team_run", raw)
    raw["revision"] += 1
    raw["updatedAt"] = "heartbeat"
    assert _progress_fingerprint("team_run", raw) == before
    raw["recovery"]["status"] = "awaiting_deployment"
    assert _progress_fingerprint("team_run", raw) != before


def test_recovery_stage_progress_reopens_only_changed_failed_episode(platform):
    _, dispatch, watcher = platform
    row = operation("team_run", status="failed")
    row["progressFingerprint"] = "1" * 64
    dispatch.management.rows["team_run"] = [row]
    initial = refresh(watcher, 10000)
    assert len(initial) == 1
    assert refresh(watcher, 10100)[0]["eventId"] == initial[0]["eventId"]
    row["progressFingerprint"] = "2" * 64
    changed = refresh(watcher, 10200)
    assert len(changed) == 1 and changed[0]["eventId"] != initial[0]["eventId"]
    assert refresh(watcher, 10300)[0]["eventId"] == changed[0]["eventId"]


def test_deployment_confirmation_uses_exact_owner_native_cas_and_evidence(env, monkeypatch):
    from core.web.services.external_management import team_recovery_control as recovery
    from core.web.services.team_workflow.generic import service
    _, raw = recovery_run(env)
    calls = []
    def command(team, run, payload):
        calls.append((team, run, payload))
        result = deepcopy(raw)
        result["revision"] = 4
        result["recovery"]["status"] = "repairing"
        return result
    monkeypatch.setattr(service, "command_run", command)
    result = recovery.confirm_deployment(env.gateway, {"team_id": "team-a", "flow_id": "flow-a",
        "run_id": "run-a", "expected_revision": "3", "evidence_ref": "deployment:original-restart"})
    assert calls == [("team-a", "run-a", {"action": "confirm_deployment", "expectedRevision": 3,
        "evidenceRef": "deployment:original-restart"})]
    assert result["accepted"] is True and result["recovery"]["status"] == "repairing"
    assert result["businessAcceptance"] == "not_evaluated"


@pytest.mark.parametrize("changes", [{"flow_id": "other"}, {"expected_revision": "2"}, {"evidence_ref": ""},
    {"evidence_ref": "line\nbreak"}, {"force": True}])
def test_invalid_deployment_proof_or_stale_owner_never_calls_native(env, monkeypatch, changes):
    from core.web.services.external_management import team_recovery_control as recovery
    from core.web.services.external_management.service import ManagementError
    from core.web.services.team_workflow.generic import service
    recovery_run(env)
    monkeypatch.setattr(service, "command_run", lambda *a: pytest.fail("invalid deployment reached writer"))
    with pytest.raises(ManagementError):
        recovery.confirm_deployment(env.gateway, {"team_id": "team-a", "flow_id": "flow-a", "run_id": "run-a",
            "expected_revision": "3", "evidence_ref": "deployment:original-restart", **changes})
