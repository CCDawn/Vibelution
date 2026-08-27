"""Fail-closed tests for the preview-only automation policy contracts (R0.3).

The embedded ``HUMAN_REVIEW_POLICY_V2_REFERENCE_JSON`` pins the challenge-cup
reference document exactly as recorded in the 2026-08-28 decision record; its
declared contentHash (AF4C8647...D47F8F) proves the hash rule used here is
byte-identical to the policy JSON convention.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from core.research.workflow.contracts.automation_policy import (
    AUTO_ADVANCE_CAPABILITIES,
    AutoAdvancePolicyV2,
    AutomationPolicyValidationError,
    HumanReviewPolicyV2,
    compute_policy_content_hash,
)
from core.web.services.team_workflow.research_runtime import (
    automation_policy_service as service,
)

HUMAN_REVIEW_POLICY_V2_REFERENCE_JSON = r"""
{
  "schemaVersion": "1.0.0",
  "policyId": "cc-human-review-policy-002",
  "version": "2.0.0-candidate.1",
  "status": "candidate_pending_approval",
  "createdAt": "2026-08-26T13:02:49+08:00",
  "contractRef": "../../03-工程合同/2026-08-25-125题零点击假说生成与自动评审完整实施方案.md",
  "implementationPlanRef": "../../03-工程合同/2026-08-25-挑战杯链路自动化改造实施方案.md",
  "supersedes": {
    "policyId": "cc-full-catalog-execution-policy-001",
    "supersededFields": [
      "reviewPolicy.humanReviewAllSpecialtyQuestions",
      "capacityAndBudgetAuthorization.minimumUniqueStandardQuestionsForHumanReview"
    ],
    "effectiveOnlyAfter": "this policy approved AND frozen with contentHash; before that the 36-question baseline remains binding"
  },
  "gateCalibration": {
    "G1": "included_in_G12_cumulative_sample",
    "G5": "included_in_G12_cumulative_sample",
    "G12": "review_all_12"
  },
  "postG12LowRiskSampling": {
    "rollingDriftSentinels": 3,
    "selection": "seeded_stratified_random",
    "stratificationAxes": [
      "catalog_domain",
      "risk_class",
      "run_phase"
    ],
    "sentinelsDrawnFrom": "second_half_of_G125",
    "sentinelFailureAction": "pause_batch_and_recalibrate"
  },
  "mandatoryExceptionReview": [
    "medical_or_ethics_high_risk",
    "unresolved_core_claim",
    "citation_or_receipt_failure",
    "reviewer_disagreement_above_threshold",
    "diversity_collapse",
    "auto_revision_exhausted",
    "scope_or_cross_question_contamination",
    "suspicious_score_or_fabrication_signal"
  ],
  "exceptionReviewCap": "none_risk_and_exception_questions_reviewed_in_full",
  "specialtyReviewRule": "risk_triggered_only_no_class_wide_review",
  "deepExperimentReview": "all",
  "finalApproval": "manifest_level",
  "calibrationMetrics": {
    "agreementMeasure": "cohens_kappa",
    "unitOfAnalysis": "per_question_auto_advance_decision",
    "machineDecisionSource": "system_policy AUTO_ADVANCE vs NEEDS_HUMAN from convergence gate",
    "humanDecisionSource": "G12 human full review approve / reject per question",
    "falseAutoApproveDefinition": "machine AUTO_ADVANCE while human review finds core claim unsupported, contradicted, or fabrication signal",
    "activationThreshold": {
      "kappaGte": 0.75,
      "falseAutoApproveEq": 0,
      "unlocks": "autoAdvanceLevel L1 (full auto)"
    },
    "provisionalThreshold": {
      "kappaRange": [
        0.6,
        0.75
      ],
      "unlocks": "autoAdvanceLevel L2 only, recalibrate before L1"
    },
    "stopThreshold": {
      "kappaBelow": 0.6,
      "action": "stop_revise_policy_rerun_G12"
    },
    "rawAccuracyExplicitlyInsufficient": true
  },
  "humanEffortBudget": {
    "fixedWork": [
      "H0_policy_authorization_once",
      "G12_calibration_workbench",
      "G125_capacity_authorization_once",
      "three_drift_sentinels",
      "final_manifest_approval_once"
    ],
    "targetPlannedHours": "2_to_4",
    "exceptionHours": "proportional_to_real_exception_count_not_capped"
  },
  "approval": {
    "verbalDirectionApproval": {
      "receivedAt": "2026-08-25",
      "scope": "decision_5_direction_only_not_activation"
    },
    "activationRequires": "explicit approval recorded against this policyId + version + contentHash",
    "requiredApprovers": [
      "competition_owner"
    ],
    "approvedBy": [],
    "frozenAt": null,
    "contentHash": "AF4C86479CB9ABE13BBFD517850298A9CA395D58354B851C2076D01354D47F8F",
    "contentHashRule": "sha256 over canonical JSON (sort_keys=True, separators=(',',':'), ensure_ascii=False) with contentHash set to null; uppercase hex"
  }
}
"""

HUMAN_REVIEW_V2_DECLARED_HASH = (
    "AF4C86479CB9ABE13BBFD517850298A9CA395D58354B851C2076D01354D47F8F"
)


def _auto_advance_v2_payload() -> dict:
    """A valid capability-matrix AutoAdvancePolicyV2 candidate (all off)."""

    return {
        "schemaVersion": "1.0.0",
        "policyId": "cc-auto-advance-policy-002",
        "version": "2.0.0-candidate.1",
        "status": "candidate",
        "executionMode": "shadow",
        "createdAt": "2026-08-28T00:00:00+08:00",
        "capabilities": {
            "autoAdvanceBatchGate": False,
            "autoCloseMeetingRound": False,
            "autoConvergeQuestion": False,
            "autoSelectCandidates": False,
            "autoStartEvidenceRepair": False,
        },
        "maxRevisionRounds": 2,
        "maxRevisionRoundsAdjustableTo": 1,
        "allowedRiskClasses": ["low_risk_standard"],
        "effectiveFromCheckpoint": None,
        "drainMode": "none",
        "uiPresets": {
            "L3": {
                "displayOnly": True,
                "label": "per_round_confirmation",
                "description": "identical to the pre-transform manual flow",
                "displayCapabilities": [],
            },
            "L2": {
                "displayOnly": True,
                "label": "stage_gates_only",
                "description": "in-question auto advance when hard gates pass",
                "displayCapabilities": [
                    "autoCloseMeetingRound",
                    "autoSelectCandidates",
                    "autoStartEvidenceRepair",
                    "autoConvergeQuestion",
                ],
            },
            "L1": {
                "displayOnly": True,
                "label": "full_auto",
                "description": "in-question and between-batch auto advance",
                "displayCapabilities": sorted(AUTO_ADVANCE_CAPABILITIES),
            },
        },
        "calibrationGate": {
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
        },
        "supersedes": {
            "policyId": "cc-auto-advance-policy-001",
            "supersededFields": ["autoAdvanceLevel"],
        },
        "activationRequires": (
            "explicit approval recorded against policyId + version + "
            "contentHash; a hash change starts a new checkpoint generation"
        ),
        "approval": {
            "requiredApprovers": ["competition_owner"],
            "approvedBy": [],
            "frozenAt": None,
            "contentHash": None,
            "contentHashRule": (
                "sha256 over canonical JSON (sort_keys=True, "
                "separators=(',',':'), ensure_ascii=False) with contentHash "
                "set to null; uppercase hex"
            ),
        },
    }


def _human_review_v2_payload() -> dict:
    """A valid HumanReviewPolicyV2 candidate matching the decision-#5 mirror."""

    reference = json.loads(HUMAN_REVIEW_POLICY_V2_REFERENCE_JSON)
    reference["status"] = "candidate"
    return reference


def _with_hash(payload: dict) -> dict:
    frozen = deepcopy(payload)
    frozen["approval"]["contentHash"] = compute_policy_content_hash(frozen)
    return frozen


def _tampered(payload: dict, mutate) -> dict:
    """Apply a mutation and re-freeze the hash (structural checks only)."""

    mutated = deepcopy(payload)
    mutate(mutated)
    return _with_hash(mutated)


def _error_codes(exc: AutomationPolicyValidationError) -> set[str]:
    return {item["code"] for item in exc.errors}


# ---------------------------------------------------------------------------
# content hash rule
# ---------------------------------------------------------------------------


def test_reference_human_review_v2_hash_reproduces_declared_hash() -> None:
    payload = json.loads(HUMAN_REVIEW_POLICY_V2_REFERENCE_JSON)

    assert payload["approval"]["contentHash"] == HUMAN_REVIEW_V2_DECLARED_HASH

    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).replace(
        '"contentHash":"' + HUMAN_REVIEW_V2_DECLARED_HASH + '"',
        '"contentHash":null',
    )
    expected = (
        hashlib.sha256(canonical.encode("utf-8")).hexdigest().upper()
    )
    assert compute_policy_content_hash(payload) == expected
    assert compute_policy_content_hash(payload) == HUMAN_REVIEW_V2_DECLARED_HASH


def test_auto_advance_hash_is_uppercase_canonical_and_nulls_content_hash() -> None:
    payload = _with_hash(_auto_advance_v2_payload())
    declared = payload["approval"]["contentHash"]

    assert len(declared) == 64
    assert declared == declared.upper()
    assert declared == compute_policy_content_hash(payload)

    without_hash = deepcopy(payload)
    without_hash["approval"]["contentHash"] = None
    canonical = json.dumps(
        without_hash, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    assert (
        hashlib.sha256(canonical.encode("utf-8")).hexdigest().upper() == declared
    )


# ---------------------------------------------------------------------------
# AutoAdvancePolicyV2
# ---------------------------------------------------------------------------


def test_valid_auto_advance_v2_candidate_passes_validation_and_roundtrips() -> None:
    payload = _with_hash(_auto_advance_v2_payload())

    policy = AutoAdvancePolicyV2.from_dict(payload)

    assert policy.policyId == "cc-auto-advance-policy-002"
    assert policy.status == "candidate"
    assert policy.executionMode == "shadow"
    assert policy.capabilities == {
        "autoAdvanceBatchGate": False,
        "autoCloseMeetingRound": False,
        "autoConvergeQuestion": False,
        "autoSelectCandidates": False,
        "autoStartEvidenceRepair": False,
    }
    assert policy.maxRevisionRounds == 2
    assert policy.maxRevisionRoundsAdjustableTo == 1
    assert policy.drainMode == "none"
    assert policy.effectiveFromCheckpoint is None
    assert policy.enabled_capabilities == ()
    assert policy.declaredContentHash == payload["approval"]["contentHash"]

    parsed = AutoAdvancePolicyV2.from_dict(json.loads(json.dumps(payload)))
    assert parsed == policy


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p["capabilities"].__setitem__("autoConvergeQuestion", True),
        lambda p: p.__setitem__("maxRevisionRounds", 3),
        lambda p: p.__setitem__("drainMode", "requested"),
        lambda p: p.__setitem__(
            "effectiveFromCheckpoint", "checkpoint-run-41-node-g12"
        ),
        lambda p: p["supersedes"].__setitem__("policyId", "other-policy"),
    ],
    ids=[
        "capability_switch",
        "max_revision_rounds",
        "drain_mode",
        "effective_from_checkpoint",
        "supersedes",
    ],
)
def test_tampered_auto_advance_field_fails_hash_verification(mutate) -> None:
    payload = _with_hash(_auto_advance_v2_payload())
    mutate(payload)
    # the hash is NOT recomputed after the mutation

    with pytest.raises(AutomationPolicyValidationError) as excinfo:
        AutoAdvancePolicyV2.from_dict(payload)

    assert "content_hash_mismatch" in _error_codes(excinfo.value)


def test_unknown_capability_switch_is_rejected() -> None:
    payload = _tampered(
        _auto_advance_v2_payload(),
        lambda p: p["capabilities"].__setitem__("autoWriteManifest", True),
    )

    with pytest.raises(AutomationPolicyValidationError) as excinfo:
        AutoAdvancePolicyV2.from_dict(payload)

    assert "unknown_capability" in _error_codes(excinfo.value)
    assert not any("content_hash" in code for code in _error_codes(excinfo.value))


def test_missing_capability_switch_is_rejected() -> None:
    payload = _tampered(
        _auto_advance_v2_payload(),
        lambda p: p["capabilities"].pop("autoAdvanceBatchGate"),
    )

    with pytest.raises(AutomationPolicyValidationError) as excinfo:
        AutoAdvancePolicyV2.from_dict(payload)

    assert "missing_capability" in _error_codes(excinfo.value)


def test_active_execution_mode_is_rejected_in_preview_stage() -> None:
    payload = _tampered(
        _auto_advance_v2_payload(),
        lambda p: p.__setitem__("executionMode", "active"),
    )

    with pytest.raises(AutomationPolicyValidationError) as excinfo:
        AutoAdvancePolicyV2.from_dict(payload, stage="preview")

    assert "active_mode_forbidden_in_preview" in _error_codes(excinfo.value)

    with pytest.raises(service.AutomationPolicyServiceError) as service_error:
        service.validate_auto_advance_policy_v2(payload)
    assert service_error.value.code == "active_mode_forbidden_in_preview"


def test_ui_presets_are_display_only_and_never_change_capabilities() -> None:
    payload = _with_hash(_auto_advance_v2_payload())

    policy = AutoAdvancePolicyV2.from_dict(payload)

    # L1 preset advertises every capability for UI display, yet the persisted
    # capability matrix stays all-off (decision #10: presets are not truth).
    assert policy.uiPresets["L1"]["displayCapabilities"] == sorted(
        AUTO_ADVANCE_CAPABILITIES
    )
    assert set(policy.enabled_capabilities) == set()
    assert all(value is False for value in policy.capabilities.values())

    authoritative = _tampered(
        _auto_advance_v2_payload(),
        lambda p: p["uiPresets"]["L1"].__setitem__(
            "capabilities", dict.fromkeys(sorted(AUTO_ADVANCE_CAPABILITIES), True)
        ),
    )
    with pytest.raises(AutomationPolicyValidationError) as excinfo:
        AutoAdvancePolicyV2.from_dict(authoritative)
    assert "invalid_ui_preset" in _error_codes(excinfo.value)

    missing_flag = _tampered(
        _auto_advance_v2_payload(),
        lambda p: p["uiPresets"]["L1"].pop("displayOnly"),
    )
    with pytest.raises(AutomationPolicyValidationError) as excinfo:
        AutoAdvancePolicyV2.from_dict(missing_flag)
    assert "invalid_ui_preset" in _error_codes(excinfo.value)


@pytest.mark.parametrize(
    "field",
    [
        "confusionMatrix",
        "kappaWithCI",
        "stratifiedBy",
        "falseAutoApproveUpperBound",
        "sequentialSamplingDeclaration",
        "notAPermanentDelegation",
    ],
)
def test_missing_calibration_gate_field_is_rejected(field: str) -> None:
    payload = _tampered(
        _auto_advance_v2_payload(),
        lambda p: p["calibrationGate"].pop(field),
    )

    with pytest.raises(AutomationPolicyValidationError) as excinfo:
        AutoAdvancePolicyV2.from_dict(payload)

    assert "missing_calibration_gate_field" in _error_codes(excinfo.value)


def test_calibration_gate_without_risk_and_domain_stratification_rejected() -> None:
    payload = _tampered(
        _auto_advance_v2_payload(),
        lambda p: p["calibrationGate"].__setitem__("stratifiedBy", ["risk_class"]),
    )

    with pytest.raises(AutomationPolicyValidationError) as excinfo:
        AutoAdvancePolicyV2.from_dict(payload)

    assert "invalid_calibration_gate_field" in _error_codes(excinfo.value)


def test_calibration_gate_bound_method_is_limited_to_frozen_estimators() -> None:
    payload = _tampered(
        _auto_advance_v2_payload(),
        lambda p: p["calibrationGate"]["falseAutoApproveUpperBound"].__setitem__(
            "method", "normal_approximation"
        ),
    )

    with pytest.raises(AutomationPolicyValidationError) as excinfo:
        AutoAdvancePolicyV2.from_dict(payload)

    assert "invalid_calibration_gate_field" in _error_codes(excinfo.value)


@pytest.mark.parametrize("status", ["draft", "candidate_pending_approval", ""])
def test_non_candidate_or_approved_status_is_rejected(status: str) -> None:
    payload = _tampered(
        _auto_advance_v2_payload(),
        lambda p: p.__setitem__("status", status),
    )

    with pytest.raises(AutomationPolicyValidationError) as excinfo:
        AutoAdvancePolicyV2.from_dict(payload)

    assert "unsupported_value" in _error_codes(excinfo.value)


def test_missing_supersedes_is_rejected() -> None:
    payload = _tampered(
        _auto_advance_v2_payload(),
        lambda p: p.pop("supersedes"),
    )

    with pytest.raises(AutomationPolicyValidationError) as excinfo:
        AutoAdvancePolicyV2.from_dict(payload)

    assert "missing_supersedes" in _error_codes(excinfo.value)


def test_unknown_drain_mode_is_rejected() -> None:
    payload = _tampered(
        _auto_advance_v2_payload(),
        lambda p: p.__setitem__("drainMode", "paused"),
    )

    with pytest.raises(AutomationPolicyValidationError) as excinfo:
        AutoAdvancePolicyV2.from_dict(payload)

    assert "unsupported_value" in _error_codes(excinfo.value)


def test_revision_round_bound_is_enforced() -> None:
    payload = _tampered(
        _auto_advance_v2_payload(),
        lambda p: p.__setitem__("maxRevisionRounds", 5),
    )

    with pytest.raises(AutomationPolicyValidationError) as excinfo:
        AutoAdvancePolicyV2.from_dict(payload)

    assert "unsupported_value" in _error_codes(excinfo.value)


# ---------------------------------------------------------------------------
# HumanReviewPolicyV2
# ---------------------------------------------------------------------------


def test_human_review_v2_reference_validates_after_status_normalization() -> None:
    payload = _with_hash(_human_review_v2_payload())

    policy = HumanReviewPolicyV2.from_dict(payload)

    assert policy.rollingDriftSentinels == 3
    assert policy.finalApproval == "manifest_level"
    assert "risk_triggered" in policy.specialtyReviewRule
    assert "auto_revision_exhausted" in policy.mandatoryExceptionReview
    assert (
        policy.calibrationMetrics["agreementMeasure"] == "cohens_kappa"
    )
    assert policy.supersedes["policyId"] == "cc-full-catalog-execution-policy-001"


def test_human_review_v2_rejects_wrong_sentinel_count() -> None:
    payload = _tampered(
        _human_review_v2_payload(),
        lambda p: p["postG12LowRiskSampling"].__setitem__(
            "rollingDriftSentinels", 4
        ),
    )

    with pytest.raises(AutomationPolicyValidationError) as excinfo:
        HumanReviewPolicyV2.from_dict(payload)

    assert "unsupported_value" in _error_codes(excinfo.value)


def test_human_review_v2_rejects_conflicting_sentinel_locations() -> None:
    def _conflict(payload: dict) -> None:
        payload["rollingDriftSentinels"] = 3
        payload["postG12LowRiskSampling"]["rollingDriftSentinels"] = 4

    payload = _tampered(_human_review_v2_payload(), _conflict)

    with pytest.raises(AutomationPolicyValidationError) as excinfo:
        HumanReviewPolicyV2.from_dict(payload)

    assert "conflicting_sentinel_count" in _error_codes(excinfo.value)
    assert "unsupported_value" not in _error_codes(excinfo.value)


def test_human_review_v2_rejects_class_wide_specialty_review() -> None:
    payload = _tampered(
        _human_review_v2_payload(),
        lambda p: p.__setitem__("specialtyReviewRule", "review_all_specialty"),
    )

    with pytest.raises(AutomationPolicyValidationError) as excinfo:
        HumanReviewPolicyV2.from_dict(payload)

    assert "invalid_specialty_rule" in _error_codes(excinfo.value)


def test_human_review_v2_rejects_non_manifest_final_approval() -> None:
    payload = _tampered(
        _human_review_v2_payload(),
        lambda p: p.__setitem__("finalApproval", "per_question"),
    )

    with pytest.raises(AutomationPolicyValidationError) as excinfo:
        HumanReviewPolicyV2.from_dict(payload)

    assert "unsupported_value" in _error_codes(excinfo.value)


def test_human_review_v2_tampered_field_fails_hash_verification() -> None:
    payload = _human_review_v2_payload()
    payload["gateCalibration"]["G12"] = "review_all_12_except_three"

    with pytest.raises(AutomationPolicyValidationError) as excinfo:
        HumanReviewPolicyV2.from_dict(payload)

    assert "content_hash_mismatch" in _error_codes(excinfo.value)


# ---------------------------------------------------------------------------
# service layer
# ---------------------------------------------------------------------------


def test_service_loads_and_previews_auto_advance_policy_from_file(tmp_path: Path) -> None:
    path = tmp_path / "auto_advance_policy_v2.json"
    path.write_text(
        json.dumps(_with_hash(_auto_advance_v2_payload()), ensure_ascii=False),
        encoding="utf-8",
    )

    policy = service.load_auto_advance_policy_v2(path)

    assert policy.executionMode == "shadow"

    preview = service.preview_auto_advance_policy_v2(policy)
    assert preview["previewOnly"] is True
    assert preview["executed"] is False
    assert set(preview["wouldChangeIfActivated"]["capabilityStates"]) == set(
        AUTO_ADVANCE_CAPABILITIES
    )
    assert preview["wouldChangeIfActivated"]["enabledCapabilities"] == []
    assert (
        preview["wouldChangeIfActivated"]["maxRevisionRounds"] == 2
    )
    assert any("checkpoint" in note for note in preview["notes"])


def test_service_preview_snapshot_is_static_structured_description(tmp_path: Path) -> None:
    payload = _tampered(
        _auto_advance_v2_payload(),
        lambda p: p["capabilities"].__setitem__("autoConvergeQuestion", True),
    )
    preview = service.preview_auto_advance_policy_v2(payload)

    assert preview["executed"] is False
    assert preview["wouldChangeIfActivated"]["enabledCapabilities"] == [
        "autoConvergeQuestion"
    ]
    states = preview["wouldChangeIfActivated"]["capabilityStates"]
    assert states["autoConvergeQuestion"]["enabledInPolicy"] is True
    assert states["autoCloseMeetingRound"]["enabledInPolicy"] is False
    assert (
        preview["wouldChangeIfActivated"]["calibrationGateSummary"][
            "notAPermanentDelegation"
        ]
        is True
    )


def test_service_load_missing_file_is_typed_error(tmp_path: Path) -> None:
    with pytest.raises(service.AutomationPolicyServiceError) as excinfo:
        service.load_auto_advance_policy_v2(tmp_path / "missing.json")

    assert excinfo.value.code == "policy_file_missing"


def test_service_load_malformed_json_is_typed_error(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(service.AutomationPolicyServiceError) as excinfo:
        service.load_auto_advance_policy_v2(path)

    assert excinfo.value.code == "policy_json_invalid"


def test_service_hash_mismatch_uses_typed_code(tmp_path: Path) -> None:
    payload = _with_hash(_auto_advance_v2_payload())
    payload["capabilities"]["autoConvergeQuestion"] = True
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(service.AutomationPolicyServiceError) as excinfo:
        service.load_auto_advance_policy_v2(path)

    assert excinfo.value.code == "content_hash_mismatch"
