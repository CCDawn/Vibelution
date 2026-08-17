"""Contract-layer tests for the Challenge Cup D02 scope batch.

Verifies the four first-class contracts are exported from the contracts
package and that a formal scope fails closed when any identity field is
missing.
"""

from __future__ import annotations

import pytest

from core.research.workflow import contracts
from core.research.workflow.contracts import (
    CampaignActivationStatus,
    ContractValidationError,
    PlatformFlowReadinessReport,
    ResearchCampaignActivation,
    ResearchScopeEnvelope,
    ScopeMode,
    ThemeContract,
    ThemeContractStatus,
    scope_hash_for,
    scope_identity_seed,
)
from core.web.routes.team_workflows.experiment_models import (
    PlatformFlowReadinessResponse,
    PrivateMemoryMigrationResponse,
    ResearchCampaignActivationResponse,
    ResearchScopeEnvelopeResponse,
    ThemeContractResponse,
)

FORMAL_SCOPE_FIELDS = ("program", "theme", "campaign", "question", "branch", "workflow")


def test_route_response_models_mirror_contract_surface() -> None:
    envelope = ResearchScopeEnvelopeResponse(**_valid_envelope())
    assert envelope.mode == "formal"
    assert envelope.scopeHash == "a" * 64

    activation = ResearchCampaignActivationResponse(
        programId="XH-202619",
        themeId="cc-gpu-operator-001",
        campaignId="cc-campaign-gpu-operator-001",
        status="active",
        activatedBy="operator",
        activatedAt="2026-08-17T00:00:00+00:00",
        activationRef="research-campaign://manual",
        scopeHash="a" * 64,
        activationHash="b" * 64,
    )
    assert activation.status == "active"
    assert len(activation.activationHash) == 64

    report = PlatformFlowReadinessResponse(
        themeActivated=True,
        realCampaignAllowed=True,
        formalArtifactReadWriteAllowed=True,
    )
    assert report.realCampaignAllowed is True
    assert report.formalArtifactReadWriteAllowed is True

    migration = PrivateMemoryMigrationResponse(
        candidateCount=1,
        candidates=[{"candidateId": "m1"}],
    )
    assert migration.candidateCount == 1

    theme = ThemeContractResponse(themeId="dev-theme-001", status="dev")
    assert theme.themeId == "dev-theme-001"
    assert theme.status == "dev"


def test_four_first_class_contracts_are_exported_from_package() -> None:
    assert contracts.ThemeContract is ThemeContract
    assert contracts.ResearchCampaignActivation is ResearchCampaignActivation
    assert contracts.ResearchScopeEnvelope is ResearchScopeEnvelope
    assert contracts.PlatformFlowReadinessReport is PlatformFlowReadinessReport
    assert contracts.REQUIRED_SCOPE_FIELDS == FORMAL_SCOPE_FIELDS


def _valid_envelope() -> dict:
    return {
        "program": "XH-202619",
        "theme": "cc-gpu-operator-001",
        "campaign": "cc-campaign-gpu-operator-001",
        "question": "SCI-091",
        "branch": "main",
        "workflow": "hypothesis_and_plan",
        "agentId": "agent-alpha",
        "mode": "formal",
        "scopeHash": "a" * 64,
        "artifactLocator": f"research-artifact://XH-202619/cc-gpu-operator-001/cc-campaign-gpu-operator-001/main/SCI-091/{'a' * 64}",
        "ledgerRoot": f"research-ledger://XH-202619/cc-gpu-operator-001/cc-campaign-gpu-operator-001/{'a' * 64}",
        "cacheKey": f"scope:{'a' * 64}:main:agent-alpha",
    }


def test_formal_scope_fails_closed_when_any_identity_field_is_missing() -> None:
    envelope = _valid_envelope()
    for field in FORMAL_SCOPE_FIELDS:
        broken = {key: value for key, value in envelope.items() if key != field}
        with pytest.raises(ContractValidationError, match=field):
            ResearchScopeEnvelope.from_dict(broken)
        empty = {**envelope, field: "   "}
        with pytest.raises(ContractValidationError, match=field):
            ResearchScopeEnvelope.from_dict(empty)
    parsed = ResearchScopeEnvelope.from_dict(envelope)
    assert parsed.mode is ScopeMode.FORMAL
    assert parsed.to_dict() == envelope


def test_scope_hash_is_stable_and_sensitive_to_theme_and_campaign() -> None:
    common = {
        "question": "SCI-091",
        "branch": "main",
        "workflow": "hypothesis_and_plan",
        "agent_id": "agent-alpha",
        "mode": "formal",
    }
    first = scope_hash_for(
        program="XH-202619",
        theme="cc-gpu-operator-001",
        campaign="cc-campaign-gpu-operator-001",
        **common,
    )
    repeated = scope_hash_for(
        program="XH-202619",
        theme="cc-gpu-operator-001",
        campaign="cc-campaign-gpu-operator-001",
        **common,
    )
    other_theme = scope_hash_for(
        program="XH-202619",
        theme="cc-neural-information-001",
        campaign="cc-campaign-neural-spike-001",
        **common,
    )
    other_campaign = scope_hash_for(
        program="XH-202619",
        theme="cc-gpu-operator-001",
        campaign="cc-campaign-other-001",
        **common,
    )
    assert first == repeated
    assert len(first) == 64
    assert first != other_theme
    assert first != other_campaign


def test_scope_identity_seed_excludes_derived_fields() -> None:
    seed = scope_identity_seed(
        program="XH-202619",
        theme="cc-gpu-operator-001",
        campaign="cc-campaign-gpu-operator-001",
        question="SCI-091",
        branch="main",
        workflow="hypothesis_and_plan",
        agent_id="agent-alpha",
        mode="formal",
    )
    assert "scopeHash" not in seed
    assert "artifactLocator" not in seed
    assert "ledgerRoot" not in seed
    assert "cacheKey" not in seed
    assert seed["theme"] == "cc-gpu-operator-001"


def test_theme_contract_status_and_dev_detection() -> None:
    dev = ThemeContract.from_dict(
        {
            "programId": "dev-program",
            "themeId": "dev-theme-001",
            "themeName": "DEV theme",
            "campaignId": "dev-campaign-001",
            "status": "dev",
        }
    )
    assert dev.is_dev_theme() is True
    assert dev.is_activated() is False

    active = ThemeContract.from_dict(
        {
            "programId": "XH-202619",
            "themeId": "cc-gpu-operator-001",
            "themeName": "GPU 算子智能生成实验",
            "campaignId": "cc-campaign-gpu-operator-001",
            "status": "active",
            "activatedAt": "2026-08-17T00:00:00+00:00",
            "activatedBy": "operator",
            "activationRef": "research-campaign://cc-gpu-operator-001",
            "isolationPolicy": {"separateThemeContracts": True},
        }
    )
    assert active.is_dev_theme() is False
    assert active.is_activated() is True
    assert active.status is ThemeContractStatus.ACTIVE

    with pytest.raises(ContractValidationError):
        ThemeContract.from_dict({"programId": "XH-202619", "status": "active"})


def test_activation_contract_requires_hash_bound_fields() -> None:
    partial = {
        "programId": "XH-202619",
        "themeId": "cc-gpu-operator-001",
        "campaignId": "cc-campaign-gpu-operator-001",
        "status": "active",
        "activatedBy": "operator",
        "activatedAt": "2026-08-17T00:00:00+00:00",
        "activationRef": "research-campaign://cc-gpu-operator-001",
        "scopeHash": "a" * 64,
    }
    with pytest.raises(ContractValidationError, match="activationHash"):
        ResearchCampaignActivation.from_dict(partial)

    full = {
        **partial,
        "activationHash": "b" * 64,
    }
    parsed = ResearchCampaignActivation.from_dict(full)
    assert parsed.status is CampaignActivationStatus.ACTIVE
    assert parsed.to_dict() == full

    with pytest.raises(ContractValidationError):
        ResearchCampaignActivation.from_dict({**full, "scopeHash": "not-a-sha256"})


def test_build_activation_payload_is_self_consistent() -> None:
    payload = contracts.build_campaign_activation_payload(
        program_id="XH-202619",
        theme_id="cc-gpu-operator-001",
        campaign_id="cc-campaign-gpu-operator-001",
        activated_by="operator",
        activation_ref="research-campaign://manual",
    )
    parsed = ResearchCampaignActivation.from_dict(payload)
    assert len(payload["activationHash"]) == 64
    assert parsed.scopeHash == contracts.activation_scope_hash(
        program_id="XH-202619",
        theme_id="cc-gpu-operator-001",
        campaign_id="cc-campaign-gpu-operator-001",
    )
    with pytest.raises(ContractValidationError):
        contracts.build_campaign_activation_payload(
            program_id="",
            theme_id="",
            campaign_id="cc-campaign-gpu-operator-001",
            activated_by="operator",
            activation_ref="research-campaign://manual",
        )


def test_platform_readiness_report_contract_round_trips() -> None:
    report = {
        "programId": "XH-202619",
        "themeId": "cc-gpu-operator-001",
        "campaignId": "cc-campaign-gpu-operator-001",
        "themeActivated": False,
        "mode": "platform",
        "devContractTestsAllowed": True,
        "realCampaignAllowed": False,
        "formalArtifactReadWriteAllowed": False,
        "blockers": ["theme_not_activated"],
        "scopeHash": "a" * 64,
        "privateMemoryMigration": [{"candidateId": "m1"}],
        "generatedAt": "2026-08-17T00:00:00+00:00",
    }
    parsed = PlatformFlowReadinessReport.from_dict(report)
    assert parsed.to_dict() == report
    assert parsed.devContractTestsAllowed is True
    assert parsed.realCampaignAllowed is False
    assert parsed.formalArtifactReadWriteAllowed is False