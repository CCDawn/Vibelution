"""Regression contracts for the research Agent configuration SSOT.

Research prompt markdown files are content assets.  They must not be joined to
another live ``agents.json`` that can own an Agent's identity, model, prompt
binding, or activation state.  The Agent Directory is the only live source for
those fields; mode bindings may select an ``agentId`` but may not copy config.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from core.research import agent_runner as agent_runner_module
from core.research import theme_discovery as theme_discovery_module
from core.research.agent_runner import LLMResearchAgentRunner
from core.research.providers import DeterministicResearchSearchProvider
from core.research.theme_discovery import ResearchThemeDiscoveryService
from core.web.services import (
    agent_directory_service,
    agent_mode_binding_service,
    prompt_template_service,
    research_service,
    session_service,
)


class _LegacyResearchWorkspace:
    """Small workspace double that exposes the retired source deliberately."""

    def __init__(self, project_root: Path, legacy_config: dict[str, Any]) -> None:
        self.project_root = project_root
        self.root = project_root / "workspace"
        self.legacy_config = copy.deepcopy(legacy_config)
        self.legacy_write_calls: list[dict[str, Any]] = []
        self.prompt_contents: dict[str, str] = {}

    def research_prompts_dir(self) -> Path:
        return self.root / "prompts" / "research"

    def get_research_prompt_path(self, filename: str) -> Path:
        return self.research_prompts_dir() / filename

    def get_research_agent_config_path(self) -> Path:
        return self.research_prompts_dir() / "agents.json"

    def get_research_flow_canvas_path(self) -> Path:
        return self.research_prompts_dir() / "flow_canvas.json"

    def read_research_agent_config(self) -> dict[str, Any]:
        return copy.deepcopy(self.legacy_config)

    def write_research_agent_config(self, data: dict[str, Any]) -> bool:
        self.legacy_write_calls.append(copy.deepcopy(data))
        path = self.get_research_agent_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return True

    def write_research_prompt(self, filename: str, content: str) -> bool:
        path = self.get_research_prompt_path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.prompt_contents[filename] = content
        return True

    def read_research_prompt(self, filename: str) -> str:
        path = self.get_research_prompt_path(filename)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return self.prompt_contents.get(filename, "")

    def read_research_flow_canvas(self) -> dict[str, Any]:
        path = self.get_research_flow_canvas_path()
        if not path.exists():
            return {"nodes": [], "edges": []}
        return json.loads(path.read_text(encoding="utf-8"))

    def write_research_flow_canvas(self, data: dict[str, Any]) -> bool:
        path = self.get_research_flow_canvas_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return True


def _wire_workspace(
    workspace: _LegacyResearchWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Point every relevant facade at one isolated project root."""

    monkeypatch.setattr(research_service, "get_workspace", lambda: workspace)
    monkeypatch.setattr(agent_runner_module, "get_workspace", lambda: workspace)
    monkeypatch.setattr(theme_discovery_module, "get_workspace", lambda: workspace)
    for service in (
        agent_directory_service,
        agent_mode_binding_service,
        prompt_template_service,
        session_service,
    ):
        monkeypatch.setattr(service, "PROJECT_ROOT", workspace.project_root)


def _legacy_config() -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "agents": [
            {
                "key": "broad",
                "label": "旧配置广搜 Agent",
                "promptFilename": "legacy.md",
                "templateId": "research_broad_explorer",
                "profileId": "legacy-profile",
                "agentId": "legacy-agent-id",
                "agentInstanceId": "legacy-agent-id",
                "activationSource": "manual_config",
                "enabled": True,
            }
        ],
    }


def _seed_directory_agent() -> dict[str, Any]:
    return agent_directory_service.create_agent_instance(
        display_name="Directory 广搜 Agent",
        llm_bindings={"dialogue": {"modelId": "directory-model"}},
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-directory-broad",
        metadata={
            "researchAgentKey": "broad",
            "researchTemplateId": "research_broad_explorer",
            "researchPromptFilename": "broad.md",
            "configSurface": "agent_config",
        },
    )


def test_research_binding_ignores_retired_agents_json_when_directory_has_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale research ``agents.json`` cannot override Directory config."""

    workspace = _LegacyResearchWorkspace(tmp_path, _legacy_config())
    _wire_workspace(workspace, monkeypatch)
    directory_agent = _seed_directory_agent()

    result = research_service.get_research_agent_bindings()
    resolved = next(item for item in result["agents"] if item["key"] == "broad")

    assert resolved["agentId"] == directory_agent["agentId"]
    assert resolved["agentInstanceId"] == directory_agent["agentId"]
    assert resolved["promptTemplateId"] == directory_agent["promptTemplateId"]
    assert resolved["profileId"] != "legacy-profile"
    assert result["configPath"] == str(agent_directory_service.registry_path())


def test_research_binding_save_does_not_recreate_retired_agents_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Saving a research binding has one writer: Agent Directory."""

    workspace = _LegacyResearchWorkspace(tmp_path, {"schemaVersion": 1, "agents": []})
    _wire_workspace(workspace, monkeypatch)
    monkeypatch.setattr(
        research_service,
        "_list_llm_config_options",
        lambda: [{"configId": "primary"}],
    )

    research_service.save_research_agent_binding(
        "broad",
        "research_broad_explorer",
        "primary",
        label="Directory 广搜 Agent",
        prompt_filename="broad.md",
    )

    canonical = next(
        (
            item
            for item in agent_directory_service.list_agents(
                include_archived=False,
                detail="full",
            )
            if str(item.get("roleKey") or "").strip() == "research_broad"
        ),
        None,
    )

    assert canonical is not None
    assert canonical["promptTemplateId"] == "prompt-research-broad"
    assert canonical["llmBindings"]
    assert workspace.legacy_write_calls == []
    assert not workspace.get_research_agent_config_path().exists()


def test_research_runner_uses_directory_agent_when_legacy_file_conflicts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runner profile resolution cannot fall back to a retired config source."""

    workspace = _LegacyResearchWorkspace(tmp_path, _legacy_config())
    _wire_workspace(workspace, monkeypatch)
    directory_agent = _seed_directory_agent()
    monkeypatch.setattr(
        agent_runner_module.agent_mode_binding_service,
        "get_mode_bindings_payload",
        lambda **_kwargs: {"modes": {"research": {"flowBindings": {}, "pool": []}}},
    )

    profile = LLMResearchAgentRunner(
        search_provider=DeterministicResearchSearchProvider()
    )._agent_profile("broad")

    assert profile["agentId"] == directory_agent["agentId"]
    assert profile["promptTemplateId"] == directory_agent["promptTemplateId"]
    assert profile["llmBindings"] == directory_agent["llmBindings"]
    assert profile["promptFilename"] == "broad.md"


def test_theme_discovery_profile_uses_directory_agent_when_legacy_file_conflicts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Research reports must describe the same Directory-owned Agent config."""

    workspace = _LegacyResearchWorkspace(tmp_path, _legacy_config())
    _wire_workspace(workspace, monkeypatch)
    directory_agent = _seed_directory_agent()

    service = object.__new__(ResearchThemeDiscoveryService)
    profile = service._research_agent_template_profile()
    resolved = next(item for item in profile["agents"] if item["key"] == "broad")

    assert resolved["agentId"] == directory_agent["agentId"]
    assert resolved["promptTemplateId"] == directory_agent["promptTemplateId"]
    assert profile["configPath"] == str(agent_directory_service.registry_path())


def test_archiving_research_agent_does_not_tombstone_reusable_prompt_asset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Agent lifecycle and Prompt content lifecycle remain separate."""

    workspace = _LegacyResearchWorkspace(tmp_path, _legacy_config())
    _wire_workspace(workspace, monkeypatch)
    directory_agent = _seed_directory_agent()

    result = research_service.delete_research_agent_binding("broad")

    assert agent_directory_service.get_agent(
        directory_agent["agentId"],
        include_archived=True,
    )["status"] == "archived"
    assert not [item for item in result["agents"] if item["key"] == "broad"]
    assert any(item["key"] == "broad" for item in result["prompts"])
    assert workspace.legacy_write_calls == []
    assert not workspace.get_research_agent_config_path().exists()
