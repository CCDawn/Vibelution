from __future__ import annotations

import pytest

from core.web.services import agent_directory_service
from tests.test_agent_config_workspace_service import _use_tmp_project_root


def test_replace_agent_llm_bindings_if_current_updates_under_current_timestamp(
    tmp_path, monkeypatch
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="CAS Agent",
        llm_bindings={"dialogue": {"modelId": "ai-pixel/old"}},
    )
    recorded = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded.append((args, kwargs)),
    )
    secret = "raw-binding-secret"

    updated = agent_directory_service.replace_agent_llm_bindings_if_current(
        agent["agentId"],
        expected_updated_at=agent["updatedAt"],
        llm_bindings={"dialogue": {"modelId": secret}},
    )

    assert updated["updatedAt"] != agent["updatedAt"]
    assert updated["llmBindings"]["dialogue"]["modelId"] == secret
    assert (
        agent_directory_service.get_agent(agent["agentId"])["updatedAt"]
        == updated["updatedAt"]
    )
    assert recorded[0][1]["fields"]["bindingSlots"] == ["dialogue"]
    assert secret not in str(recorded)


def test_replace_agent_llm_bindings_if_current_rejects_stale_timestamp_without_overwrite(
    tmp_path, monkeypatch
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="CAS Agent",
        llm_bindings={"dialogue": {"modelId": "ai-pixel/old"}},
    )
    concurrent = agent_directory_service.update_agent_instance(
        agent["agentId"],
        llm_bindings={"dialogue": {"modelId": "ai-pixel/concurrent"}},
    )

    with pytest.raises(agent_directory_service.AgentStateConflictError):
        agent_directory_service.replace_agent_llm_bindings_if_current(
            agent["agentId"],
            expected_updated_at=agent["updatedAt"],
            llm_bindings={"dialogue": {"modelId": "ai-pixel/gpt-5.6-luna"}},
        )

    current = agent_directory_service.get_agent(agent["agentId"])
    assert current["updatedAt"] == concurrent["updatedAt"]
    assert current["llmBindings"]["dialogue"]["modelId"] == "ai-pixel/concurrent"
