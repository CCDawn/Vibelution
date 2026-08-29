"""Storage-level guard for the Team Agent binding SSOT boundary."""

from __future__ import annotations

import json

from core.research.workflow.models import AgentBindingLayers
from core.web.services.team_workflow.research_runtime.binding_config import (
    WorkflowBindingConfigStore,
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
