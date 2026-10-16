"""Bounded auto-selection contract + conservative concurrency elevation.

Retired-scope note: the autoSelectCandidates executor path, the G12
calibration store and the G12-store-backed concurrency elevation were
removed with the T8 auto-advance machine (challenge cup archived; the
ladder never activated).  What stays under test here:

- the ``candidateSelection`` contract on ``AutoAdvancePolicyV2`` (default
  ``maxSelected=2``, ``digest_proposal_order`` rule, floor of 2, unknown
  rules rejected) — the contract module itself is still the frozen
  authority for policy documents;
- concurrency elevation at the contract level and the conservative
  batch-side default: above-default concurrency for the real-125 plan is
  allowed only when the real-12 batch itself fully succeeded; the retired
  G12 calibration-pilot evidence path no longer exists.

All discussion content is stubbed; no real model, network, or research
activity is involved.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from core.research.competition.real_control_batch import (
    RealBatchError,
    validate_real_concurrency,
)
from core.research.workflow.contracts import (
    CANDIDATE_SELECTION_DEFAULT_MAX,
    CANDIDATE_SELECTION_RULE_DIGEST_ORDER,
)
from core.web.services.team_workflow import challenge_cup_real_batch as real_batch

from tests._support.team_workflow.helpers import _use_tmp_project_root

_QUESTION_ID = "SCI-096"


def _policy_payload(
    *,
    candidate_selection: dict | None = None,
) -> dict:
    """An approved + active policy document (contract-level fixture only)."""

    from core.research.workflow.contracts import (
        AUTO_ADVANCE_CAPABILITIES,
        compute_policy_content_hash,
    )

    capabilities = {name: True for name in sorted(AUTO_ADVANCE_CAPABILITIES)}
    calibration_gate = {
        "confusionMatrix": {
            "axes": ["autoAdvanceDecision", "humanReviewDecision"]
        },
        "kappaWithCI": {
            "measure": "cohens_kappa",
            "minimumKappa": 0.75,
            "confidenceInterval": "95_percent",
        },
        "stratifiedBy": ["risk_class", "catalog_domain"],
        "falseAutoApproveUpperBound": {
            "method": "wilson",
            "side": "one_sided_upper",
        },
        "sequentialSamplingDeclaration": {
            "mode": "fixed_n_then_sequential_extension",
            "declaredBeforeUnblinding": True,
        },
        "notAPermanentDelegation": True,
    }
    payload = {
        "schemaVersion": "1.0.0",
        "policyId": "cc-auto-select-contract-test",
        "version": "2.0.0-approved.1",
        "status": "approved",
        "executionMode": "active",
        "createdAt": "2026-09-02T00:00:00+08:00",
        "capabilities": capabilities,
        "maxRevisionRounds": 2,
        "maxRevisionRoundsAdjustableTo": 1,
        "allowedRiskClasses": ["low_risk_standard"],
        "effectiveFromCheckpoint": None,
        "drainMode": "none",
        "uiPresets": None,
        "calibrationGate": calibration_gate,
        "supersedes": {"policyId": "cc-auto-advance-policy-001"},
        "activationRequires": (
            "explicit approval recorded against policyId + version + contentHash"
        ),
        "approval": {
            "requiredApprovers": ["competition_owner"],
            "approvedBy": ["operator"],
            "frozenAt": "2026-09-02T00:00:00+08:00",
            "contentHash": None,
            "contentHashRule": (
                "sha256 over canonical JSON (sort_keys=True, separators=(',',':'), "
                "ensure_ascii=False) with contentHash set to null; uppercase hex"
            ),
        },
    }
    if candidate_selection is not None:
        payload["candidateSelection"] = candidate_selection
    payload["approval"]["contentHash"] = compute_policy_content_hash(payload)
    return payload


# ---------------------------------------------------------------------------
# A: candidateSelection contract (frozen policy-document semantics)


def test_candidate_selection_contract_defaults_floor_and_rules() -> None:
    from core.research.workflow.contracts import AutoAdvancePolicyV2

    # Absent -> frozen default (keeps existing documents valid).
    policy = AutoAdvancePolicyV2.from_dict(_policy_payload(), stage="activation")
    assert policy.candidateSelection == {
        "maxSelected": CANDIDATE_SELECTION_DEFAULT_MAX,
        "selectionRule": CANDIDATE_SELECTION_RULE_DIGEST_ORDER,
    }
    # Explicit values pass through.
    policy = AutoAdvancePolicyV2.from_dict(
        _policy_payload(candidate_selection={"maxSelected": 5}),
        stage="activation",
    )
    assert policy.candidateSelection["maxSelected"] == 5
    # Floor: below 2 breaks the review comparable-pair gate -> rejected.
    from core.research.workflow.contracts.automation_policy import (
        AutomationPolicyValidationError,
    )

    with pytest.raises(AutomationPolicyValidationError) as excinfo:
        AutoAdvancePolicyV2.from_dict(
            _policy_payload(candidate_selection={"maxSelected": 1}),
            stage="activation",
        )
    assert any(
        item["field"] == "candidateSelection.maxSelected"
        for item in excinfo.value.errors
    )
    with pytest.raises(AutomationPolicyValidationError) as excinfo:
        AutoAdvancePolicyV2.from_dict(
            _policy_payload(
                candidate_selection={
                    "maxSelected": 3,
                    "selectionRule": "editorial_pick",
                }
            ),
            stage="activation",
        )
    assert any(
        item["field"] == "candidateSelection.selectionRule"
        for item in excinfo.value.errors
    )


# ---------------------------------------------------------------------------
# B: concurrency elevation — conservative default after the G12 cut


def test_real_concurrency_bounds_at_contract_level() -> None:
    assert validate_real_concurrency(2, above_default_allowed=False) == 2
    with pytest.raises(RealBatchError):
        validate_real_concurrency(3, above_default_allowed=False)
    with pytest.raises(RealBatchError):
        validate_real_concurrency(4, above_default_allowed=False)
    assert validate_real_concurrency(3, above_default_allowed=True) == 3
    assert validate_real_concurrency(4, above_default_allowed=True) == 4
    with pytest.raises(RealBatchError):
        validate_real_concurrency(5, above_default_allowed=True)


@pytest.fixture
def conservative_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated project root so elevation reads no real team workspace."""

    _use_tmp_project_root(tmp_path, monkeypatch)
    return tmp_path


def test_concurrency_elevation_is_conservative_without_completed_real12(
    conservative_env,
) -> None:
    """Only a fully succeeded real-12 batch may lift the G125 cap anymore.

    The retired G12 calibration-pilot evidence path (policy executor +
    G12 store) is gone: with no completed real-12 batch the elevation
    stays fail-closed and G125 starts fall back to the frozen default.
    """

    team_id = "team-conservative"
    # Plan restriction unchanged: only the real-125 plan may elevate.
    assert real_batch._concurrency_elevation_allowed(team_id, "G12") is False
    assert real_batch._concurrency_elevation_allowed(team_id, "G5") is False
    # No completed real-12 evidence on disk -> conservative default.
    assert real_batch._concurrency_elevation_allowed(team_id, "G125") is False
    # Validated against the frozen contract: above-default stays rejected.
    with pytest.raises(RealBatchError):
        validate_real_concurrency(3, above_default_allowed=False)
