"""Storage-level guard for the Team Agent binding SSOT boundary."""

from __future__ import annotations

import json

import pytest

from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.research.workflow.models import AgentBindingLayers
from core.web.services.team_workflow.research_runtime.binding_config import (
    BindingConfigValidationError,
    WorkflowBindingConfigStore,
)
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowError,
    ResearchWorkflowRuntimeService,
)


def test_team_scoped_binding_store_never_persists_workflow_defaults(tmp_path) -> None:
    store = WorkflowBindingConfigStore(tmp_path)
    layers = AgentBindingLayers(
        workflowDefaults={"source_finder": "stale-config-agent"},
        stageOverrides={"knowledge_collection": {"source_finder": "stage-agent"}},
        nodeOverrides={"source_finding": "node-agent"},
    )

    saved = store.save("challenge-cup", "research-team", layers)
    raw = json.loads(
        (tmp_path / "binding_config" / "challenge-cup--research-team.json").read_text(
            encoding="utf-8"
        )
    )

    assert saved["workflowDefaults"] == {}
    assert raw["workflowDefaults"] == {}
    loaded = store.load("challenge-cup", "research-team")
    assert loaded.workflowDefaults == {}
    assert loaded.stageOverrides == layers.stageOverrides
    assert loaded.nodeOverrides == layers.nodeOverrides


def test_unscoped_binding_store_retains_legacy_workflow_defaults(tmp_path) -> None:
    store = WorkflowBindingConfigStore(tmp_path)
    layers = AgentBindingLayers(workflowDefaults={"source_finder": "legacy-agent"})

    store.save("challenge-cup", "", layers)

    assert store.load("challenge-cup", "").workflowDefaults == layers.workflowDefaults


@pytest.mark.parametrize(
    ("layers", "team_id"),
    [
        (
            AgentBindingLayers(
                workflowDefaults={
                    "source_finder": {"agentId": "agent-1", "llmBindings": {}}
                }
            ),
            "research-team",
        ),
        (
            AgentBindingLayers(
                stageOverrides={
                    "knowledge_collection": {"source_finder": ["agent-1"]}
                }
            ),
            "research-team",
        ),
        (
            AgentBindingLayers(
                nodeOverrides={"source_finding": {"agentId": "agent-1"}}
            ),
            "research-team",
        ),
    ],
)
def test_binding_store_rejects_non_string_agent_ids_without_writing(
    tmp_path,
    layers,
    team_id,
) -> None:
    store = WorkflowBindingConfigStore(tmp_path)
    target = (
        tmp_path
        / "binding_config"
        / f"challenge-cup--{team_id or 'default'}.json"
    )

    with pytest.raises(BindingConfigValidationError) as exc_info:
        store.save("challenge-cup", team_id, layers)

    assert exc_info.value.code == "invalid_agent_id_type"
    assert not target.exists()


def test_binding_store_fails_closed_when_raw_config_contains_agent_object(tmp_path) -> None:
    store = WorkflowBindingConfigStore(tmp_path)
    target = tmp_path / "binding_config" / "challenge-cup--research-team.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "workflowId": "challenge-cup",
                "teamId": "research-team",
                "workflowDefaults": {},
                "stageOverrides": {},
                "nodeOverrides": {
                    "source_finding": {
                        "agentId": "agent-1",
                        "promptTemplateId": "forbidden-copy",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    assert store.load("challenge-cup", "research-team") == AgentBindingLayers()


@pytest.mark.parametrize(
    "payload",
    [
        {
            "workflowDefaults": {
                "source_finder": {"agentId": "agent-1", "llmBindings": {}}
            }
        },
        {
            "stageOverrides": {
                "knowledge_collection": {"source_finder": ["agent-1"]}
            }
        },
        {"nodeOverrides": {"source_finding": {"agentId": "agent-1"}}},
    ],
)
def test_runtime_binding_api_rejects_non_string_agent_ids(tmp_path, payload) -> None:
    store = WorkflowBindingConfigStore(tmp_path)
    service = object.__new__(ResearchWorkflowRuntimeService)
    service._binding_config = store

    with pytest.raises(ResearchWorkflowError) as exc_info:
        service.put_agent_binding_config(
            CHALLENGE_CUP_WORKFLOW_ID,
            payload,
            team_id="research-team",
        )

    assert exc_info.value.code == "invalid_agent_id_type"
    assert not (
        tmp_path
        / "binding_config"
        / f"{CHALLENGE_CUP_WORKFLOW_ID}--research-team.json"
    ).exists()
