"""Platform flow readiness report tests for the Challenge Cup D02 scope batch.

Verifies the DEV/platform-only regime for unactivated themes and the full
formal regime for activated real themes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.contracts import PlatformFlowReadinessReport
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
    monkeypatch.setattr(research_projects, "_record_project_event", lambda *args, **kwargs: None)


def test_unactivated_real_theme_only_allows_dev_platform_contract_tests(tmp_path, monkeypatch) -> None:
    _isolate_store(tmp_path, monkeypatch)

    report = scope_service.platform_flow_readiness(
        "research-team",
        program_id="XH-202619",
        theme_id="cc-gpu-operator-001",
        campaign_id="cc-campaign-gpu-operator-001",
    )

    assert report["themeActivated"] is False
    assert report["mode"] == "platform"
    assert report["devContractTestsAllowed"] is True
    assert report["realCampaignAllowed"] is False
    assert report["formalArtifactReadWriteAllowed"] is False
    assert report["blockers"] == ["theme_not_activated"]
    assert len(report["scopeHash"]) == 64


def test_dev_theme_report_blocks_real_campaign_and_formal_locators(tmp_path, monkeypatch) -> None:
    _isolate_store(tmp_path, monkeypatch)

    report = scope_service.platform_flow_readiness(
        "research-team",
        program_id="dev-program",
        theme_id="dev-theme-001",
        campaign_id="dev-campaign-001",
    )

    assert report["mode"] == "dev"
    assert report["themeActivated"] is False
    assert report["devContractTestsAllowed"] is True
    assert report["realCampaignAllowed"] is False
    assert report["formalArtifactReadWriteAllowed"] is False
    assert "dev_theme_only" in report["blockers"]

    # A DEV theme bound to a real campaign is doubly blocked.
    mixed = scope_service.platform_flow_readiness(
        "research-team",
        program_id="dev-program",
        theme_id="dev-theme-001",
        campaign_id="cc-campaign-gpu-operator-001",
    )
    assert "dev_theme_only" in mixed["blockers"]
    assert "campaign_theme_mismatch" in mixed["blockers"]
    assert mixed["realCampaignAllowed"] is False


def test_activated_theme_allows_real_campaign_and_formal_read_write(tmp_path, monkeypatch) -> None:
    _isolate_store(tmp_path, monkeypatch)
    scope_service.activate_research_campaign(
        "research-team",
        program_id="XH-202619",
        theme_id="cc-gpu-operator-001",
        campaign_id="cc-campaign-gpu-operator-001",
        activated_by="operator",
    )

    report = scope_service.platform_flow_readiness(
        "research-team",
        program_id="XH-202619",
        theme_id="cc-gpu-operator-001",
        campaign_id="cc-campaign-gpu-operator-001",
    )

    assert report["themeActivated"] is True
    assert report["mode"] == "formal"
    assert report["devContractTestsAllowed"] is False
    assert report["realCampaignAllowed"] is True
    assert report["formalArtifactReadWriteAllowed"] is True
    assert report["blockers"] == []


def test_readiness_report_contract_validates_output(tmp_path, monkeypatch) -> None:
    _isolate_store(tmp_path, monkeypatch)
    report = scope_service.platform_flow_readiness(
        "research-team",
        program_id="XH-202619",
        theme_id="cc-gpu-operator-001",
        campaign_id="cc-campaign-gpu-operator-001",
    )
    parsed = PlatformFlowReadinessReport.from_dict(report)
    assert parsed.to_dict() == report
    assert parsed.blockers == ("theme_not_activated",)
    assert parsed.privateMemoryMigration == ()


def test_campaign_mismatch_blocks_formal_flow(tmp_path, monkeypatch) -> None:
    _isolate_store(tmp_path, monkeypatch)
    scope_service.activate_research_campaign(
        "research-team",
        program_id="XH-202619",
        theme_id="cc-gpu-operator-001",
        campaign_id="cc-campaign-gpu-operator-001",
        activated_by="operator",
    )

    report = scope_service.platform_flow_readiness(
        "research-team",
        program_id="XH-202619",
        theme_id="cc-gpu-operator-001",
        campaign_id="cc-campaign-neural-spike-001",
    )

    assert report["themeActivated"] is False
    assert report["mode"] == "platform"
    assert report["realCampaignAllowed"] is False
    assert report["formalArtifactReadWriteAllowed"] is False
    assert report["blockers"] == ["campaign_theme_mismatch"]