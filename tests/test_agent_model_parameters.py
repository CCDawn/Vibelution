from __future__ import annotations

import pytest

from core.llm.agent_model_parameters import AgentModelParametersError
from core.web.services import agent_directory_service
from tests.test_agent_llm_runtime import _config_with_agent_models


def _configure_model_library(monkeypatch):
    config = _config_with_agent_models()
    config.llm.model_library["dialogue-model"].update(
        {
            "context_window": 64000,
            "reasoning_effort_values": ["low", "high"],
        }
    )
    config.llm.model_library["summary-model"].update(
        {
            "context_window": 32000,
            "reasoning_effort_values": ["low", "medium"],
        }
    )
    monkeypatch.setattr("config.settings.get_config", lambda: config)
    monkeypatch.setattr("config.get_config", lambda: config)
    return config


def test_agent_model_parameter_write_is_agent_and_model_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _configure_model_library(monkeypatch)
    agent_a = agent_directory_service.create_agent_instance(
        display_name="Model Parameters A",
        llm_bindings={"dialogue": {"modelId": "dialogue-model"}},
        metadata={
            "llmModelParameters": {
                "summary-model": {
                    "contextWindow": 8192,
                    "reasoningEffort": "low",
                }
            }
        },
    )
    agent_b = agent_directory_service.create_agent_instance(
        display_name="Model Parameters B",
        llm_bindings={"dialogue": {"modelId": "dialogue-model"}},
    )

    updated = agent_directory_service.update_agent_model_parameters_if_current(
        agent_a["agentId"],
        expected_model_ref="dialogue-model",
        expected_config_revision=agent_a["configRevision"],
        context_window=32768,
        reasoning_effort="high",
        supported_reasoning_efforts=["low", "high"],
    )

    assert updated["metadata"]["llmModelParameters"] == {
        "summary-model": {"contextWindow": 8192, "reasoningEffort": "low"},
        "dialogue-model": {"contextWindow": 32768, "reasoningEffort": "high"},
    }
    assert updated["metadata"]["llmReasoningEffort"]["dialogue"] == "high"
    assert agent_directory_service.get_agent(agent_b["agentId"])["metadata"].get("llmModelParameters") is None
    assert agent_directory_service.get_agent(agent_a["agentId"])["contextCompressionEffectivePolicy"]["contextWindowLimit"] == 32768
    assert agent_directory_service.get_agent(agent_b["agentId"])["contextCompressionEffectivePolicy"]["contextWindowLimit"] == 64000
    projected = {agent["agentId"]: agent for agent in agent_directory_service.list_agents(detail="config")}
    assert projected[agent_a["agentId"]]["contextCompressionEffectivePolicy"]["contextWindowLimit"] == 32768
    assert projected[agent_b["agentId"]]["contextCompressionEffectivePolicy"]["contextWindowLimit"] == 64000

    with pytest.raises(agent_directory_service.AgentStateConflictError):
        agent_directory_service.update_agent_model_parameters_if_current(
            agent_a["agentId"],
            expected_model_ref="dialogue-model",
            expected_config_revision=agent_a["configRevision"],
            context_window=16384,
            reasoning_effort="low",
            supported_reasoning_efforts=["low", "high"],
        )


@pytest.mark.parametrize(
    ("context_window", "reasoning_effort", "message"),
    [
        (64001, "high", "cannot exceed"),
        (32000, "xhigh", "not supported"),
        (32768.0, "high", "positive integer"),
    ],
)
def test_agent_model_parameter_write_rejects_invalid_values_without_persisting(
    tmp_path,
    monkeypatch,
    context_window,
    reasoning_effort,
    message,
):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _configure_model_library(monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="Invalid Model Parameters",
        llm_bindings={"dialogue": {"modelId": "dialogue-model"}},
    )

    with pytest.raises(AgentModelParametersError, match=message):
        agent_directory_service.update_agent_model_parameters_if_current(
            agent["agentId"],
            expected_model_ref="dialogue-model",
            expected_config_revision=agent["configRevision"],
            context_window=context_window,
            reasoning_effort=reasoning_effort,
            supported_reasoning_efforts=["low", "high"],
        )

    current = agent_directory_service.get_agent(agent["agentId"])
    assert current["configRevision"] == agent["configRevision"]
    assert current["metadata"].get("llmModelParameters") is None
