"""Campaign activation flow tests for the Challenge Cup D02 scope batch.

Verifies that DEV themes can never be activated as real campaigns, that real
theme activation persists inside the existing research-project store, and that
the legacy research-project API stays compatible while wiring activation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.web.services.team_workflow import research_projects
from core.web.services.team_workflow import research_scope as scope_service


def _isolate_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(research_projects.team_service, "get_team", lambda _team_id: {})
    monkeypatch.setattr(research_projects.team_service, "assert_team_exists", lambda _team_id: None)
    monkeypatch.setattr(
        research_projects,
        "team_workspace_root",
        lambda team_id: tmp_path / "teams" / str(team_id),
    )
    monkeypatch.setattr(
        research_projects,
        "formal_team_workspace_root",
        lambda team_id: tmp_path / "teams" / str(team_id),
    )
    assert research_projects._store_path("research-team").is_relative_to(tmp_path)
    monkeypatch.setattr(research_projects, "_record_project_event", lambda *args, **kwargs: None)


def test_dev_theme_can_never_be_activated_as_real_campaign(tmp_path, monkeypatch) -> None:
    _isolate_store(tmp_path, monkeypatch)

    with pytest.raises(scope_service.ResearchScopeDevThemeNotActivatableError) as exc:
        scope_service.activate_research_campaign(
            "research-team",
            program_id="dev-program",
            theme_id="dev-theme-001",
            campaign_id="dev-campaign-001",
            activated_by="test",
        )
    assert exc.value.code == "dev_theme_not_activatable"

    # A DEV theme bound to a real campaign identifier is also rejected.
    with pytest.raises(scope_service.ResearchScopeDevThemeNotActivatableError) as exc:
        scope_service.activate_research_campaign(
            "research-team",
            program_id="XH-202619",
            theme_id="dev-theme-001",
            campaign_id="cc-campaign-gpu-operator-001",
            activated_by="test",
        )
    assert exc.value.code == "dev_theme_not_activatable"

    # No activation was persisted for the DEV theme.
    assert research_projects.get_theme_activation("research-team", "dev-theme-001") == {}


def test_real_theme_activation_persists_in_existing_store(tmp_path, monkeypatch) -> None:
    _isolate_store(tmp_path, monkeypatch)

    activation = scope_service.activate_research_campaign(
        "research-team",
        program_id="XH-202619",
        theme_id="cc-gpu-operator-001",
        campaign_id="cc-campaign-gpu-operator-001",
        activated_by="operator",
        activation_ref="research-campaign://manual-1",
    )

    assert activation["status"] == "active"
    assert len(activation["scopeHash"]) == 64
    assert len(activation["activationHash"]) == 64
    assert research_projects.get_theme_activation("research-team", "cc-gpu-operator-001") == activation
    assert scope_service.resolve_theme_contract(
        "research-team", theme_id="cc-gpu-operator-001"
    ).is_activated()


def test_real_activation_rejects_campaign_theme_mismatch(tmp_path, monkeypatch) -> None:
    _isolate_store(tmp_path, monkeypatch)

    with pytest.raises(scope_service.ResearchScopeCampaignMismatchError) as exc:
        scope_service.activate_research_campaign(
            "research-team",
            program_id="XH-202619",
            theme_id="cc-gpu-operator-001",
            campaign_id="cc-campaign-neural-spike-001",
            activated_by="operator",
        )
    assert exc.value.code == "campaign_theme_mismatch"

    with pytest.raises(scope_service.ResearchScopeCampaignMismatchError) as exc:
        scope_service.activate_research_campaign(
            "research-team",
            program_id="dev-program",
            theme_id="cc-gpu-operator-001",
            campaign_id="cc-campaign-gpu-operator-001",
            activated_by="operator",
        )
    assert exc.value.code == "campaign_theme_mismatch"


def test_unactivated_real_theme_rejects_formal_scope_but_allows_platform(tmp_path, monkeypatch) -> None:
    _isolate_store(tmp_path, monkeypatch)
    seed = {
        "program": "XH-202619",
        "theme": "cc-gpu-operator-001",
        "campaign": "cc-campaign-gpu-operator-001",
        "question": "SCI-091",
        "branch": "main",
        "workflow": "hypothesis_and_plan",
    }

    with pytest.raises(scope_service.ResearchScopeNotActivatedError) as exc:
        scope_service.resolve_research_scope(
            "research-team",
            agent_id="agent-alpha",
            scope_seed={**seed, "mode": "formal"},
        )
    assert exc.value.code == "theme_not_activated"

    envelope = scope_service.resolve_research_scope(
        "research-team",
        agent_id="agent-alpha",
        scope_seed={**seed, "mode": "platform"},
    )
    assert envelope["mode"] == "platform"
    assert scope_service.validate_scope_read(envelope) is True


def test_project_activation_wires_real_theme_campaign(tmp_path, monkeypatch) -> None:
    _isolate_store(tmp_path, monkeypatch)
    project = research_projects.ensure_challenge_question_project(
        "research-team",
        question_id="SCI-091",
        title="GPU 算子智能生成实验",
        topic="可证伪的 GPU 算子优化边界",
    )
    project_id = project["project"]["projectId"]

    research_projects.activate_research_project("research-team", project_id)

    activation = research_projects.get_theme_activation("research-team", "cc-gpu-operator-001")
    assert activation["status"] == "active"
    assert activation["campaignId"] == "cc-campaign-gpu-operator-001"
    assert activation["themeId"] == "cc-gpu-operator-001"

    stored_project = research_projects.get_research_project("research-team", project_id)
    assert stored_project["themeId"] == "cc-gpu-operator-001"
    assert stored_project["campaignId"] == "cc-campaign-gpu-operator-001"
    assert stored_project["activationRef"]


def test_legacy_project_api_stays_compatible(tmp_path, monkeypatch) -> None:
    _isolate_store(tmp_path, monkeypatch)
    created = research_projects.create_research_project(
        "research-team",
        {"name": "Legacy 项目", "topic": "主题", "experimentMethod": "baseline_comparison"},
    )
    assert created["project"]["projectId"].startswith("research-")

    listing = research_projects.list_research_projects("research-team")
    assert any(item["projectId"] == created["project"]["projectId"] for item in listing["projects"])

    active = research_projects.get_active_research_project("research-team")
    assert active["projectId"] == research_projects.LEGACY_PROJECT_ID
    assert active["name"] == "默认研究项目"
    assert "storageMode" in active

    updated = research_projects.update_research_project(
        "research-team", created["project"]["projectId"], {"name": "Legacy 项目改"}
    )
    assert updated["project"]["name"] == "Legacy 项目改"

    resolved = research_projects.resolve_research_project_workspace_root(
        "research-team", research_projects.LEGACY_PROJECT_ID
    )
    assert resolved == tmp_path / "teams" / "research-team"
    isolated = research_projects.resolve_research_project_workspace_root(
        "research-team", created["project"]["projectId"]
    )
    assert "workspace" in str(isolated)
