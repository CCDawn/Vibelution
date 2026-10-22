"""Compression parameter writes must not restart unrelated registry repair."""

from __future__ import annotations

import threading
import json

import pytest

from core.web.services import agent_config_change_service, session_service
from tests.test_agent_config_workspace_service import (
    _use_tmp_project_root,
    agent_directory_service,
    client,
)


def _warm_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Compression parameters")
    agent_directory_service.update_agent_instance(agent["agentId"], display_name="Compression parameters")
    return agent_directory_service.get_agent(agent["agentId"])


def _parameters(agent):
    return {
        "expectedConfigRevision": agent["configRevision"],
        "contextCompressionPolicy": {
            "mode": "custom", "enabled": True, "policyVersion": 3,
            "maxTokenLimit": 128000, "compressionTriggerTokenLimit": 20000,
            "postCompressionTargetTokenLimit": 12000,
        },
    }


def test_compression_patch_and_session_lookup_skip_unrelated_repair(tmp_path, monkeypatch):
    agent = _warm_agent(tmp_path, monkeypatch)
    repair_entered = threading.Event()
    release_repair = threading.Event()
    patch_finished = threading.Event()
    read_finished = threading.Event()
    observed = {}
    real_repair = agent_directory_service.repair_agent_directory

    def blocked_unrelated_repair():
        repair_entered.set()
        assert release_repair.wait(10), "test watchdog: repair was never released"
        return real_repair()

    monkeypatch.setattr(agent_directory_service, "repair_agent_directory", blocked_unrelated_repair)

    def update():
        try:
            observed["patch"] = client.patch(f"/api/agents/{agent['agentId']}", json=_parameters(agent))
        except BaseException as exc:
            observed["patchError"] = exc
        finally:
            patch_finished.set()

    def read_session_agent():
        try:
            # This is the Agent lookup used by ordinary session projection.
            observed["lookup"] = session_service._agent_lookup_for_conversations().get(agent["agentId"])
        except BaseException as exc:
            observed["readError"] = exc
        finally:
            read_finished.set()

    patch_thread = threading.Thread(target=update, daemon=True)
    read_thread = threading.Thread(target=read_session_agent, daemon=True)
    patch_thread.start()
    try:
        # A watchdog, not a latency benchmark: repair stays blocked throughout.
        patch_completed_without_repair = patch_finished.wait(3)
        read_thread.start()
        read_completed_without_repair = read_finished.wait(3)
        entered = repair_entered.is_set()
    finally:
        release_repair.set()
        patch_thread.join(10)
        if read_thread.ident is not None:
            read_thread.join(10)
    assert patch_completed_without_repair, "PATCH waited for unrelated full registry repair"
    assert read_completed_without_repair, "session projection waited for the parameter update's repair"
    assert not entered
    assert "patchError" not in observed and "readError" not in observed
    response = observed["patch"]
    assert response.status_code == 200, response.json()
    updated = response.json()
    assert updated["configRevision"] == agent["configRevision"] + 1
    assert updated["configHash"] != agent["configHash"]
    assert updated["publishedConfigChange"]["changedFields"] == ["contextCompressionPolicy"]
    assert observed["lookup"]["agentId"] == agent["agentId"]
    read_back = client.get(f"/api/agents/{agent['agentId']}").json()
    assert read_back["configRevision"] == updated["configRevision"]
    assert read_back["contextCompressionPolicy"]["postCompressionTargetTokenLimit"] == 12000


def test_compression_update_retains_cas_and_snapshot_isolation(tmp_path, monkeypatch):
    agent = _warm_agent(tmp_path, monkeypatch)
    updated = agent_directory_service.update_agent_instance(
        agent["agentId"], context_compression_policy=_parameters(agent)["contextCompressionPolicy"],
        expected_config_revision=agent["configRevision"],
    )
    cached = agent_directory_service._REPAIRED_STATE_CACHE
    assert cached is not None, "canonical parameter write discarded its validated snapshot"
    updated["contextCompressionPolicy"]["postCompressionTargetTokenLimit"] = 1
    current = agent_directory_service.get_agent(agent["agentId"])
    assert current["contextCompressionPolicy"]["postCompressionTargetTokenLimit"] == 12000
    before_disk = agent_directory_service.registry_path().read_bytes()
    with pytest.raises(agent_directory_service.AgentStateConflictError):
        agent_directory_service.update_agent_instance(
            agent["agentId"], context_compression_policy=_parameters(agent)["contextCompressionPolicy"],
            expected_config_revision=agent["configRevision"],
        )
    assert agent_directory_service.registry_path().read_bytes() == before_disk
    assert agent_directory_service._REPAIRED_STATE_CACHE is cached


def test_compression_update_without_warm_snapshot_still_repairs_on_read(tmp_path, monkeypatch):
    agent = _warm_agent(tmp_path, monkeypatch)
    agent_directory_service._invalidate_repaired_state_cache()
    agent_directory_service.update_agent_instance(
        agent["agentId"], context_compression_policy=_parameters(agent)["contextCompressionPolicy"],
    )
    assert agent_directory_service._REPAIRED_STATE_CACHE is None
    real_repair = agent_directory_service.repair_agent_directory
    calls = []
    monkeypatch.setattr(agent_directory_service, "repair_agent_directory", lambda: calls.append(True) or real_repair())
    current = agent_directory_service.get_agent(agent["agentId"])
    assert len(calls) == 1
    assert current["contextCompressionPolicy"]["postCompressionTargetTokenLimit"] == 12000


def test_external_registry_change_invalidates_refreshed_parameter_snapshot(tmp_path, monkeypatch):
    agent = _warm_agent(tmp_path, monkeypatch)
    agent_directory_service.update_agent_instance(
        agent["agentId"], context_compression_policy=_parameters(agent)["contextCompressionPolicy"],
    )
    path = agent_directory_service.registry_path()
    state = json.loads(path.read_text(encoding="utf-8"))
    stored = agent_directory_service._find_agent(state, agent["agentId"])
    stored["metadata"]["externalChangeProbe"] = "must remain visible"
    path.write_text(json.dumps(state), encoding="utf-8")
    real_repair = agent_directory_service.repair_agent_directory
    calls = []
    monkeypatch.setattr(agent_directory_service, "repair_agent_directory", lambda: calls.append(True) or real_repair())
    current = agent_directory_service.get_agent(agent["agentId"])
    assert len(calls) == 1
    assert current["metadata"]["externalChangeProbe"] == "must remain visible"


@pytest.mark.parametrize("write_kind", ["combined_update", "low_level_save"])
def test_repair_sensitive_changes_keep_full_repair(tmp_path, monkeypatch, write_kind):
    agent = _warm_agent(tmp_path, monkeypatch)
    if write_kind == "combined_update":
        agent_directory_service.update_agent_instance(
            agent["agentId"], context_compression_policy=_parameters(agent)["contextCompressionPolicy"],
            tool_policy_id="default",
        )
    else:
        state = agent_directory_service.load_state()
        agent_directory_service._find_agent(state, agent["agentId"])["toolPolicyId"] = "tool-missing"
        agent_directory_service.save_state(state)
    assert agent_directory_service._REPAIRED_STATE_CACHE is None
    current = agent_directory_service.get_agent(agent["agentId"])
    assert current["toolPolicyId"] != "default"
    assert current["toolPolicyId"] in agent_directory_service.load_state()["toolPolicies"]


def test_compression_update_telemetry_failure_does_not_fail_committed_patch(tmp_path, monkeypatch):
    agent = _warm_agent(tmp_path, monkeypatch)
    original_record = agent_directory_service.record_runtime_scene_event

    def record(*args, **kwargs):
        if args[2] == "agent.compression_parameters.updated":
            raise OSError("scene storage unavailable")
        return original_record(*args, **kwargs)

    monkeypatch.setattr(agent_directory_service, "record_runtime_scene_event", record)
    response = client.patch(f"/api/agents/{agent['agentId']}", json=_parameters(agent))
    assert response.status_code == 200, response.json()
    history = agent_config_change_service.list_agent_config_changes(agent["agentId"])
    assert history["revisions"][0]["changedFields"] == ["contextCompressionPolicy"]


def test_external_write_during_parameter_cache_handoff_is_not_hidden(tmp_path, monkeypatch):
    agent = _warm_agent(tmp_path, monkeypatch)
    real_save = agent_directory_service.save_state

    def save_then_external_write(state):
        payload = real_save(state)
        external = json.loads(agent_directory_service.registry_path().read_text(encoding="utf-8"))
        stored = agent_directory_service._find_agent(external, agent["agentId"])
        stored["contextCompressionPolicy"]["postCompressionTargetTokenLimit"] = 13000
        agent_directory_service.registry_path().write_text(json.dumps(external), encoding="utf-8")
        return payload

    with monkeypatch.context() as handoff:
        handoff.setattr(agent_directory_service, "save_state", save_then_external_write)
        agent_directory_service.update_agent_instance(
            agent["agentId"], context_compression_policy=_parameters(agent)["contextCompressionPolicy"],
        )
        assert agent_directory_service._REPAIRED_STATE_CACHE is None
    current = agent_directory_service.get_agent(agent["agentId"])
    assert current["contextCompressionPolicy"]["postCompressionTargetTokenLimit"] == 13000


def test_parameter_update_records_cache_handoff_without_configuration_body(tmp_path, monkeypatch):
    agent = _warm_agent(tmp_path, monkeypatch)
    recorded = []
    monkeypatch.setattr(agent_directory_service, "record_runtime_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))
    response = client.patch(f"/api/agents/{agent['agentId']}", json=_parameters(agent))
    assert response.status_code == 200
    event = next(kwargs for args, kwargs in recorded if args[2] == "agent.compression_parameters.updated")
    assert event["fields"]["repairedSnapshotRefreshed"] is True
    assert event["fields"]["configRevision"] == response.json()["configRevision"]
    assert event["fields"]["durationMs"] >= 0
    assert "contextCompressionPolicy" not in event["fields"]
