"""Parameter PATCH must release the session lock without unrelated registry repair."""

from __future__ import annotations

import copy
import threading
from types import SimpleNamespace

import pytest

from core.web.services import session_service
from core.llm.agent_model_parameters import resolve_agent_model_parameters
from tests.test_agent_compression_policy_update import _warm_agent
from tests.test_agent_config_workspace_service import agent_directory_service, client
from tests.test_agent_model_parameters import _configure_model_library


def _session_agent(tmp_path, monkeypatch):
    agent = _warm_agent(tmp_path, monkeypatch)
    _configure_model_library(monkeypatch)
    agent_directory_service.update_agent_instance(
        agent["agentId"], llm_bindings={"dialogue": {"modelId": "dialogue-model"}},
    )
    agent = agent_directory_service.get_agent(agent["agentId"])
    monkeypatch.setattr(session_service, "_ensure_session_conversation_record", lambda *_a, **_k: True)
    monkeypatch.setattr(session_service, "_ensure_session_mutable", lambda *_a, **_k: {})
    monkeypatch.setattr(session_service, "_session_agent_id_snapshot", lambda *_a: agent["agentId"])
    choice = {"modelId": "dialogue-model", "modelRef": "dialogue-model", "reasoningEffortValues": ["low", "high"]}
    monkeypatch.setattr(session_service, "_session_fixed_model_choice", lambda *_a: choice)
    monkeypatch.setattr(session_service, "_session_llm_model_choices", lambda: [choice])
    monkeypatch.setattr(session_service, "_conversation_agent_dialogue_context_window_payload", lambda _cfg, value: {
        "limit": resolve_agent_model_parameters(value["_agent"], "dialogue-model")["context_window"],
        "maxLimit": 64000,
    })
    monkeypatch.setattr(session_service, "_resolve_session_agent_llm", lambda value, *_a: SimpleNamespace(
        reasoning_effort_requested=value.get("metadata", {}).get("llmReasoningEffort", {}).get("dialogue", "low"),
    ))
    return agent


def _patch(kind, agent):
    if kind == "model":
        return client.patch("/api/sessions/session-parameters/model-parameters", json={
            "expectedAgentId": agent["agentId"], "expectedModelRef": "dialogue-model",
            "expectedConfigRevision": agent["configRevision"],
            "contextWindow": 32768, "reasoningEffort": "high",
        })
    return client.patch("/api/sessions/session-parameters/budget-parameters", json={
        "revision": agent["configRevision"], "maxCallsPerTurn": 17,
    })


@pytest.mark.parametrize("kind", ["model", "budget"])
def test_parameter_patch_and_concurrent_session_read_skip_unrelated_repair(tmp_path, monkeypatch, kind):
    agent = _session_agent(tmp_path, monkeypatch)
    entered, release, done, read_done = (threading.Event() for _ in range(4))
    real_repair = agent_directory_service.repair_agent_directory
    observed = {}

    def blocked_repair():
        entered.set()
        assert release.wait(15), "repair watchdog expired"
        return real_repair()

    monkeypatch.setattr(agent_directory_service, "repair_agent_directory", blocked_repair)

    def update():
        try:
            observed["response"] = _patch(kind, agent)
        except BaseException as exc:
            observed["error"] = exc
        finally:
            done.set()

    def read():
        try:
            observed["view"] = session_service.get_session_budget_parameters_view("session-parameters")
            observed["lookup"] = session_service._agent_lookup_for_conversations().get(agent["agentId"])
        except BaseException as exc:
            observed["readError"] = exc
        finally:
            read_done.set()

    writer, reader = threading.Thread(target=update, daemon=True), threading.Thread(target=read, daemon=True)
    writer.start()
    try:
        completed = done.wait(3)
        reader.start()
        readable = read_done.wait(3)
        repaired = entered.is_set()
    finally:
        release.set()
        writer.join(10)
        if reader.ident is not None:
            reader.join(10)
    assert completed, f"{kind} PATCH waited for unrelated full registry repair"
    assert readable, "session read waited for parameter repair"
    assert not repaired
    assert "error" not in observed and "readError" not in observed
    response = observed["response"]
    assert response.status_code == 200, response.json()
    result = response.json()
    assert result["configRevision" if kind == "model" else "revision"] == agent["configRevision"] + 1
    assert observed["view"]["revision"] == agent["configRevision"] + 1
    assert observed["lookup"]["agentId"] == agent["agentId"]
    if kind == "model":
        assert result["contextWindow"] == 32768
        assert result["currentReasoningEffort"] == "high"
    else:
        assert result["maxCallsPerTurn"] == 17


@pytest.mark.parametrize("kind", ["model", "budget"])
def test_parameter_update_keeps_snapshot_isolated_and_cas(tmp_path, monkeypatch, kind):
    agent = _session_agent(tmp_path, monkeypatch)
    accepted = copy.deepcopy(agent)
    response = _patch(kind, agent)
    assert response.status_code == 200, response.json()
    cached = agent_directory_service._REPAIRED_STATE_CACHE
    assert cached is not None
    current = agent_directory_service.get_agent(agent["agentId"])
    key = "llmModelParameters" if kind == "model" else "sessionBudgetParameters"
    current["metadata"][key].clear()
    assert agent_directory_service.get_agent(agent["agentId"])["metadata"][key]
    assert accepted == agent
    disk = agent_directory_service.registry_path().read_bytes()
    assert _patch(kind, agent).status_code == 409
    assert agent_directory_service.registry_path().read_bytes() == disk
    assert agent_directory_service._REPAIRED_STATE_CACHE is cached


@pytest.mark.parametrize(("kind", "changed_key"), [
    ("model", "sessionBudgetParameters"), ("model", "perceptionPolicy"),
    ("budget", "llmModelParameters"), ("budget", "llmReasoningEffort"),
    ("budget", "perceptionPolicy"),
])
def test_parameter_snapshot_rejects_other_metadata_namespaces(tmp_path, monkeypatch, kind, changed_key):
    from core.web.services.agent_directory.parameter_snapshot import save_parameter_update

    agent = _session_agent(tmp_path, monkeypatch)
    with agent_directory_service._STATE_LOCK:
        state = agent_directory_service.load_state()
        current = agent_directory_service._find_agent(state, agent["agentId"])
        previous = copy.deepcopy(current)
        current["metadata"][changed_key] = {"probe": True}
        assert not save_parameter_update(state, current, previous, kind=kind)
        assert agent_directory_service._REPAIRED_STATE_CACHE is None


def test_budget_clear_keeps_warm_snapshot_and_bumps_revision(tmp_path, monkeypatch):
    agent = _session_agent(tmp_path, monkeypatch)
    updated = _patch("budget", agent).json()
    response = client.patch("/api/sessions/session-parameters/budget-parameters", json={
        "revision": updated["revision"], "maxCallsPerTurn": None,
    })
    assert response.status_code == 200, response.json()
    assert response.json() == {"revision": updated["revision"] + 1, "maxCallsPerTurn": None}
    assert agent_directory_service._REPAIRED_STATE_CACHE is not None
    assert "sessionBudgetParameters" not in agent_directory_service.get_agent(agent["agentId"])["metadata"]


@pytest.mark.parametrize("kind", ["model", "budget"])
def test_parameter_update_telemetry_is_bounded_and_best_effort(tmp_path, monkeypatch, kind):
    agent = _session_agent(tmp_path, monkeypatch)
    events = []

    def record(*args, **kwargs):
        if args[2] == f"agent.{kind}_parameters.updated" and "repairedSnapshotRefreshed" in kwargs["fields"]:
            events.append(kwargs["fields"])
            raise OSError("scene storage unavailable")

    monkeypatch.setattr(agent_directory_service, "record_runtime_scene_event", record)
    response = _patch(kind, agent)
    assert response.status_code == 200, response.json()
    assert len(events) == 1
    assert events[0]["repairedSnapshotRefreshed"] is True
    assert events[0]["durationMs"] >= 0
    assert "metadata" not in events[0]
