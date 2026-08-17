"""Scope isolation, hash verification, and cross-theme memory migration tests.

Verifies that the same agent/question produces distinct, stable scope hashes,
artifact locators, ledger roots, and cache keys across themes/campaigns, that
scope reads validate against the full scope hash, and that cross-theme private
memory migration only surfaces fully-classified, advisory-only, revalidation
candidates with declared evidence.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.contracts import ContractValidationError
from core.web.services.team_workflow import research_projects
from core.web.services.team_workflow import research_scope as scope_service

GPU_THEME = "cc-gpu-operator-001"
GPU_CAMPAIGN = "cc-campaign-gpu-operator-001"
NEURO_THEME = "cc-neural-information-001"
NEURO_CAMPAIGN = "cc-campaign-neural-spike-001"


def _isolate_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(research_projects.team_service, "get_team", lambda _team_id: {})
    monkeypatch.setattr(research_projects.team_service, "assert_team_exists", lambda _team_id: None)
    monkeypatch.setattr(
        research_projects,
        "team_workspace_root",
        lambda team_id: tmp_path / "teams" / str(team_id),
    )
    monkeypatch.setattr(research_projects, "_record_project_event", lambda *args, **kwargs: None)


def _activate_both_real_themes(team_id: str = "research-team") -> None:
    scope_service.activate_research_campaign(
        team_id,
        program_id="XH-202619",
        theme_id=GPU_THEME,
        campaign_id=GPU_CAMPAIGN,
        activated_by="test",
    )
    scope_service.activate_research_campaign(
        team_id,
        program_id="XH-202619",
        theme_id=NEURO_THEME,
        campaign_id=NEURO_CAMPAIGN,
        activated_by="test",
    )


def _seed(theme: str, campaign: str, **overrides) -> dict:
    payload = {
        "program": "XH-202619",
        "theme": theme,
        "campaign": campaign,
        "question": "SCI-091",
        "branch": "main",
        "workflow": "hypothesis_and_plan",
        "mode": "formal",
    }
    payload.update(overrides)
    return payload


def test_same_agent_question_is_isolated_across_theme_and_campaign(tmp_path, monkeypatch) -> None:
    _isolate_store(tmp_path, monkeypatch)
    _activate_both_real_themes()

    gpu_a = scope_service.resolve_research_scope(
        "research-team",
        agent_id="agent-alpha",
        scope_seed=_seed(GPU_THEME, GPU_CAMPAIGN),
    )
    gpu_b = scope_service.resolve_research_scope(
        "research-team",
        agent_id="agent-alpha",
        scope_seed=_seed(GPU_THEME, GPU_CAMPAIGN),
    )
    neuro = scope_service.resolve_research_scope(
        "research-team",
        agent_id="agent-alpha",
        scope_seed=_seed(NEURO_THEME, NEURO_CAMPAIGN),
    )

    assert gpu_a == gpu_b
    assert gpu_a["scopeHash"] != neuro["scopeHash"]
    assert gpu_a["artifactLocator"] != neuro["artifactLocator"]
    assert gpu_a["ledgerRoot"] != neuro["ledgerRoot"]
    assert gpu_a["cacheKey"] != neuro["cacheKey"]

    assert gpu_a["mode"] == "formal"
    assert gpu_a["scopeHash"] in gpu_a["artifactLocator"]
    assert gpu_a["scopeHash"] in gpu_a["ledgerRoot"]
    assert gpu_a["scopeHash"] in gpu_a["cacheKey"]

    # The same agent/question keeps distinct keys across themes, and the
    # derived locators are stable across repeated derivations.
    assert gpu_b["cacheKey"] == gpu_a["cacheKey"]
    assert neuro["cacheKey"] != gpu_a["cacheKey"]


def test_scope_read_validates_full_hash_and_rejects_tampering(tmp_path, monkeypatch) -> None:
    _isolate_store(tmp_path, monkeypatch)
    _activate_both_real_themes()
    envelope = scope_service.resolve_research_scope(
        "research-team",
        agent_id="agent-alpha",
        scope_seed=_seed(GPU_THEME, GPU_CAMPAIGN),
    )

    assert scope_service.validate_scope_read(envelope) is True

    tampered_hash = {**envelope, "scopeHash": "b" * 64}
    with pytest.raises(scope_service.ResearchScopeHashMismatchError):
        scope_service.validate_scope_read(tampered_hash)

    tampered_identity = {**envelope, "campaign": NEURO_CAMPAIGN}
    with pytest.raises(scope_service.ResearchScopeHashMismatchError):
        scope_service.validate_scope_read(tampered_identity)

    missing_field = {key: value for key, value in envelope.items() if key != "branch"}
    with pytest.raises(ContractValidationError):
        scope_service.validate_scope_read(missing_field)


def test_private_memory_migration_only_returns_advisory_revalidation_candidates(
    tmp_path, monkeypatch
) -> None:
    _isolate_store(tmp_path, monkeypatch)
    _activate_both_real_themes()
    target = scope_service.resolve_research_scope(
        "research-team",
        agent_id="agent-alpha",
        scope_seed=_seed(GPU_THEME, GPU_CAMPAIGN),
    )

    candidates = [
        {
            "candidateId": "m1",
            "classificationStatus": "complete",
            "reusePolicy": "migratable_advisory",
            "evidenceStatus": "declared",
            "needsRevalidation": True,
            "summary": "advisory insight",
            "scopeHash": "c" * 64,
        },
        {
            "candidateId": "m2",
            "classificationStatus": "partial",
            "reusePolicy": "migratable_advisory",
            "evidenceStatus": "declared",
            "needsRevalidation": True,
            "summary": "not fully classified",
        },
        {
            "candidateId": "m3",
            "classificationStatus": "complete",
            "reusePolicy": "reusable",
            "evidenceStatus": "declared",
            "needsRevalidation": True,
            "summary": "reusable but not advisory",
        },
        {
            "candidateId": "m4",
            "classificationStatus": "complete",
            "reusePolicy": "migratable_advisory",
            "evidenceStatus": "",
            "needsRevalidation": True,
            "summary": "evidence not declared",
        },
        {
            "candidateId": "m5",
            "classificationStatus": "complete",
            "reusePolicy": "migratable_advisory",
            "evidenceStatus": "declared",
            "needsRevalidation": False,
            "summary": "already revalidated",
        },
        {
            "candidateId": "m6",
            "classificationStatus": "complete",
            "reusePolicy": "migratable_advisory",
            "evidenceStatus": "declared",
            "needsRevalidation": True,
            "summary": "advisory with embedded prompt",
            "prompt": "injected default prompt",
            "promptText": "more prompt",
            "scientificEvidence": True,
        },
    ]

    result = scope_service.private_memory_migration_candidates(
        target_scope=target,
        candidates=candidates,
    )

    assert result["targetScopeHash"] == target["scopeHash"]
    assert result["candidateCount"] == 2
    assert result["rejectedCount"] == 4
    returned_ids = {item["candidateId"] for item in result["candidates"]}
    assert returned_ids == {"m1", "m6"}

    for candidate in result["candidates"]:
        assert candidate["promptInjected"] is False
        assert candidate["scientificEvidencePromotion"] is False
        assert candidate["advisoryOnly"] is True
        assert candidate["needsRevalidation"] is True
        assert candidate["reusePolicy"] == "migratable_advisory"
        assert "prompt" not in candidate
        assert "promptText" not in candidate
        assert "scientificEvidence" not in candidate

    assert result["policy"]["promptInjection"] == "forbidden"
    assert result["policy"]["scientificEvidencePromotion"] == "forbidden"
    assert result["policy"]["revalidation"] == "required"


def test_scope_resolution_does_not_create_a_second_state_store(tmp_path, monkeypatch) -> None:
    _isolate_store(tmp_path, monkeypatch)
    store_path = tmp_path / "teams" / "research-team" / "research_projects" / "index.json"

    dev_scope = scope_service.resolve_research_scope(
        "research-team",
        agent_id="agent-alpha",
        scope_seed=_seed(
            "dev-theme-001",
            "dev-campaign-001",
            program="dev-program",
            mode="dev",
        ),
    )
    assert dev_scope["mode"] == "dev"
    scope_service.platform_flow_readiness(
        "research-team",
        program_id="dev-program",
        theme_id="dev-theme-001",
        campaign_id="dev-campaign-001",
    )

    # Pure derivation never writes: the single store appears only on activation.
    assert store_path.exists() is False

    scope_service.activate_research_campaign(
        "research-team",
        program_id="XH-202619",
        theme_id=GPU_THEME,
        campaign_id=GPU_CAMPAIGN,
        activated_by="test",
    )
    assert store_path.exists() is True