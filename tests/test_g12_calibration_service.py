"""Wiring tests for the G12 calibration gate data flow.

Covers the full chain against the real bases: audit sampling manifest ->
judgement records -> calibration bundle -> stratified report + activation
gate assessment -> policy activation advice.  All computation is pure; no
network, no clock, no command execution.
"""

from __future__ import annotations

import pytest

from core.research.competition.calibration_records import (
    G12CalibrationBundle,
    G12JudgementRecord,
)
from core.research.workflow.contracts.automation_policy import (
    AUTO_ADVANCE_CAPABILITIES,
    FALSE_AUTO_APPROVE_BOUND_METHODS,
    AutoAdvancePolicyV2,
    compute_policy_content_hash,
)
from core.research.workflow.contracts.audit_sampling import SampleKind
from core.web.services.team_workflow.research_runtime.audit_sampling_service import (
    generate_g12_calibration_manifest,
    generate_g125_batch_manifest,
)
from core.web.services.team_workflow.research_runtime.automation_policy_service import (
    validate_auto_advance_policy_v2,
)
from core.web.services.team_workflow.research_runtime.g12_calibration_service import (
    ASSESSMENT_STATUS_COMPLETE,
    ASSESSMENT_STATUS_INSUFFICIENT,
    ASSESSMENT_STATUS_PENDING,
    G12CalibrationServiceError,
    assess_bundle,
    calibration_gate_verdict,
    collect_pending_records,
    gate_policy_from_policy,
    policy_activation_advice,
)

POLICY_SNAPSHOT = {
    "policyId": "cc-auto-advance-policy-002",
    "version": "2.0.0-candidate.1",
    "contentHash": "A" * 64,
}


def _pool(count: int = 12, domain: str = "physics") -> list[dict[str, str]]:
    return [
        {
            "questionId": f"q{index:02d}",
            "riskClass": "low",
            "catalogDomain": domain,
        }
        for index in range(1, count + 1)
    ]


def _manifest(count: int = 12):
    return generate_g12_calibration_manifest(
        pool=_pool(count),
        policy=POLICY_SNAPSHOT,
        seed="seed-g12-service",
        generated_at="2026-08-28T00:00:00+08:00",
    )


def _record(
    question_id: str,
    *,
    auto: str = "auto_approve",
    human: str = "approve",
    sample_kind: SampleKind = SampleKind.G12_CALIBRATION,
) -> G12JudgementRecord:
    return G12JudgementRecord(
        questionId=question_id,
        sampleKind=sample_kind,
        autoDecision=auto,
        humanDecision=human,
        riskClass="low",
        domain="physics",
        recordedAt="2026-08-28T01:00:00+08:00",
        evidenceRef=f"review:g12:{question_id}",
    )


def _escalating_records(count: int = 12) -> list[G12JudgementRecord]:
    """2 correct escalations + 10 correct approvals: kappa = 1.0, 0 false approvals."""

    return [
        _record("q01", auto="auto_escalate", human="escalate"),
        _record("q02", auto="auto_escalate", human="escalate"),
    ] + [_record(f"q{index:02d}") for index in range(3, count + 1)]


def _complete_bundle(count: int = 12) -> G12CalibrationBundle:
    return G12CalibrationBundle.build(
        manifest=_manifest(count), records=_escalating_records(count)
    )


def _policy_payload(**calibration_gate_overrides) -> dict:
    payload = {
        "schemaVersion": "1.0.0",
        "policyId": "cc-auto-advance-policy-002",
        "version": "2.0.0-candidate.1",
        "status": "candidate_pending_approval",
        "executionMode": "shadow",
        "capabilities": {name: False for name in sorted(AUTO_ADVANCE_CAPABILITIES)},
        "maxRevisionRounds": 2,
        "maxRevisionRoundsAdjustableTo": 1,
        "allowedRiskClasses": ["low"],
        "effectiveFromCheckpoint": None,
        "drainMode": "none",
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
        "supersedes": {"policyId": "cc-auto-advance-policy-001"},
        "activationRequires": (
            "explicit approval recorded against policyId + version + contentHash"
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
    payload["calibrationGate"].update(calibration_gate_overrides)
    payload["approval"]["contentHash"] = compute_policy_content_hash(payload)
    return payload


def _validated_policy(**overrides) -> AutoAdvancePolicyV2:
    return validate_auto_advance_policy_v2(_policy_payload(**overrides))


# ---------------------------------------------------------------------------
# collect_pending_records
# ---------------------------------------------------------------------------


def test_collect_pending_records_projects_full_checklist() -> None:
    projection = collect_pending_records(_manifest())
    assert projection["totalRequired"] == 12
    assert projection["totalRecorded"] == 0
    assert projection["pendingCount"] == 12
    assert projection["status"] == ASSESSMENT_STATUS_PENDING
    assert projection["policyId"] == POLICY_SNAPSHOT["policyId"]
    assert all(
        item["sampleKind"] == "g12_calibration" for item in projection["pending"]
    )
    assert [item["questionId"] for item in projection["pending"]][0] == "q01"


def test_collect_pending_records_subtracts_recorded_questions() -> None:
    records = _escalating_records()
    projection = collect_pending_records(_manifest(), records)
    assert projection["pending"] == []
    assert projection["totalRecorded"] == 12
    assert projection["status"] == ASSESSMENT_STATUS_COMPLETE


def test_collect_pending_records_rejects_wrong_gate_and_foreign_records() -> None:
    g125_manifest = generate_g125_batch_manifest(
        pool=_pool(),
        policy=POLICY_SNAPSHOT,
        seed="seed-g125",
        batch_index=1,
        generated_at="2026-08-28T00:00:00+08:00",
    )
    with pytest.raises(G12CalibrationServiceError, match="G12"):
        collect_pending_records(g125_manifest)
    with pytest.raises(G12CalibrationServiceError, match="sampling scope"):
        collect_pending_records(_manifest(), [_record("q99")])


# ---------------------------------------------------------------------------
# assess_bundle
# ---------------------------------------------------------------------------


def test_assess_bundle_complete_pilot_has_kappa_and_both_bounds() -> None:
    assessment = assess_bundle(_complete_bundle())
    assert assessment.status == ASSESSMENT_STATUS_COMPLETE
    assert assessment.sampleSize == 12
    assert assessment.kappa is not None
    assert assessment.kappa["defined"] is True
    assert assessment.kappa["kappa"] == pytest.approx(1.0)
    assert assessment.kappa["tier"] == "strong"
    matrix = assessment.confusionMatrix
    assert matrix["truePositives"] == 2
    assert matrix["trueNegatives"] == 10
    assert matrix["falseAutoApproveCount"] == 0
    bounds = assessment.falseAutoApproveUpperBounds
    assert set(bounds) == set(FALSE_AUTO_APPROVE_BOUND_METHODS)
    # Independent recompute: one-sided Wilson 95% with 0 failures / 10 trials.
    from statistics import NormalDist

    z = NormalDist().inv_cdf(0.95)
    trials = 10
    expected_wilson = (
        z * z / (2 * trials) + z * (z / (2 * trials))
    ) / (1 + z * z / trials)
    assert bounds["wilson"] == pytest.approx(expected_wilson, rel=1e-9)
    # Beta(1, 11) posterior quantile: closed form 1 - 0.05^(1/11).
    assert bounds["beta_binomial"] == pytest.approx(1 - 0.05 ** (1 / 11), rel=1e-6)
    # Decision #13: the 12-question pilot never approves by default and is
    # never a permanent delegation.
    assert assessment.approvableStrata == ()
    assert assessment.activation is not None
    assert assessment.activation["approved"] is False
    assert assessment.activation["notAPermanentDelegation"] is True
    assert assessment.notPermanentDelegation is True
    assert assessment.stratumReport["totalSampleSize"] == 12
    assert any("permanent delegation" in note for note in assessment.notes)


def test_assess_bundle_pending_on_empty_and_partial_bundles() -> None:
    manifest = _manifest()
    empty = G12CalibrationBundle.build(manifest=manifest, records=[])
    partial = G12CalibrationBundle.build(
        manifest=manifest, records=_escalating_records()[:7]
    )
    for bundle in (empty, partial):
        assessment = assess_bundle(bundle)
        assert assessment.status == ASSESSMENT_STATUS_PENDING
        assert assessment.kappa is None
        assert assessment.confusionMatrix is None
        assert assessment.activation is None
        assert assessment.stratumReport is None
        assert assessment.falseAutoApproveUpperBounds == {}
        assert assessment.notPermanentDelegation is True
    assert "5 of 12" in assess_bundle(partial).notes[0]


def test_assess_bundle_insufficient_when_underpowered() -> None:
    assessment = assess_bundle(_complete_bundle(4), min_stratum_n=30)
    assert assessment.status == ASSESSMENT_STATUS_INSUFFICIENT
    # Kappa is still reported for transparency, but no bound is estimable.
    assert assessment.kappa is not None
    assert assessment.kappa["defined"] is True
    assert assessment.falseAutoApproveUpperBounds == {
        "wilson": None,
        "beta_binomial": None,
    }
    assert assessment.activation["approved"] is False
    assert assessment.approvableStrata == ()


def test_assess_bundle_insufficient_on_degenerate_matrix() -> None:
    manifest = _manifest()
    bundle = G12CalibrationBundle.build(
        manifest=manifest, records=[_record(f"q{index:02d}") for index in range(1, 13)]
    )
    assessment = assess_bundle(bundle)
    assert assessment.status == ASSESSMENT_STATUS_INSUFFICIENT
    assert assessment.kappa is not None
    assert assessment.kappa["defined"] is False
    assert assessment.kappa["tier"] == "undefined"


def test_assess_bundle_approvable_stratum_with_lenient_gate_policy() -> None:
    assessment = assess_bundle(
        _complete_bundle(),
        gate_policy={
            "maxFalseAutoApproveUpperBound": 0.35,
            "minKappa": 0.6,
            "approvableRiskClasses": ["low"],
        },
    )
    assert assessment.status == ASSESSMENT_STATUS_COMPLETE
    assert assessment.approvableStrata == ("low x physics",)
    assert assessment.activation["approved"] is True
    coverage = {
        (row["axis"], row["value"]): row["coverage"]
        for row in assessment.strataCoverage
    }
    assert coverage[("overall", "overall")] == "sufficient"
    assert coverage[("risk_class x domain", "low x physics")] == "sufficient"


def test_assess_bundle_rejects_non_g12_manifest_and_bad_method() -> None:
    g125_manifest = generate_g125_batch_manifest(
        pool=_pool(),
        policy=POLICY_SNAPSHOT,
        seed="seed-g125",
        batch_index=1,
        generated_at="2026-08-28T00:00:00+08:00",
    )
    records = [
        _record(question_id, sample_kind=SampleKind.G125_SEQUENTIAL)
        for question_id in g125_manifest.questionIds
    ]
    bundle = G12CalibrationBundle.build(manifest=g125_manifest, records=records)
    with pytest.raises(G12CalibrationServiceError, match="G12"):
        assess_bundle(bundle)
    with pytest.raises(G12CalibrationServiceError, match="upper bound method"):
        assess_bundle(_complete_bundle(), method="jeffreys")


# ---------------------------------------------------------------------------
# policy activation advice
# ---------------------------------------------------------------------------


def test_gate_policy_from_policy_extracts_declared_thresholds() -> None:
    declared = gate_policy_from_policy(_validated_policy())
    assert declared == {"minKappa": 0.75}
    with_bound = gate_policy_from_policy(
        _validated_policy(maxFalseAutoApproveUpperBound=0.35)
    )
    assert with_bound == {
        "minKappa": 0.75,
        "maxFalseAutoApproveUpperBound": 0.35,
    }


def test_policy_activation_advice_advisable_with_relaxed_declared_bound() -> None:
    policy = _validated_policy(maxFalseAutoApproveUpperBound=0.35)
    assessment = assess_bundle(
        _complete_bundle(), gate_policy=gate_policy_from_policy(policy)
    )
    advice = policy_activation_advice(assessment, policy)
    assert advice["adviceOnly"] is True
    assert advice["executed"] is False
    assert advice["policyId"] == policy.policyId
    assert advice["policyContentHash"] == policy.declaredContentHash
    assert advice["evidenceStatus"] == ASSESSMENT_STATUS_COMPLETE
    assert advice["advisable"] is True
    assert advice["advisableStrata"] == ["low x physics"]
    assert all(check["present"] for check in advice["gateFieldChecks"])
    assert advice["declaredThresholds"]["minimumKappa"] == 0.75
    assert advice["declaredThresholds"]["falseAutoApproveUpperBoundMethod"] == "wilson"
    assert advice["gateEvidence"]["notAPermanentDelegation"] is True
    assert advice["gaps"] == []
    assert any("contentHash" in note for note in advice["notes"])


def test_policy_activation_advice_reports_stratum_gaps_by_default() -> None:
    policy = _validated_policy()
    assessment = assess_bundle(_complete_bundle())
    advice = policy_activation_advice(assessment, policy)
    assert advice["advisable"] is False
    assert advice["advisableStrata"] == []
    gap_codes = {gap["code"] for gap in advice["gaps"]}
    assert gap_codes == {"stratum_not_approvable"}
    gap = advice["gaps"][0]
    assert gap["field"] == "stratum:low x physics"
    assert "exceeds maximum" in gap["message"]


def test_policy_activation_advice_mirrors_contract_on_missing_gate_fields() -> None:
    assessment = assess_bundle(_complete_bundle())
    bare_policy = {
        "policyId": "cc-auto-advance-policy-002",
        "version": "2.0.0-candidate.1",
        "declaredContentHash": "C" * 64,
        "status": "candidate",
        "executionMode": "shadow",
    }
    advice = policy_activation_advice(assessment, bare_policy)
    assert advice["advisable"] is False
    codes = [gap["code"] for gap in advice["gaps"]]
    assert codes[0] == "missing_or_invalid"
    assert codes[1:7] == ["missing_calibration_gate_field"] * 6
    # the default-threshold assessment also carries its stratum gap
    assert "stratum_not_approvable" in codes[7:]
    fields = {gap["field"] for gap in advice["gaps"]}
    assert "calibrationGate" in fields
    assert "calibrationGate.notAPermanentDelegation" in fields


def test_policy_activation_advice_flags_single_missing_gate_field() -> None:
    assessment = assess_bundle(_complete_bundle())
    # A validated AutoAdvancePolicyV2 can never lack a calibrationGate field
    # (the D contract rejects that at load), so the single-missing-field
    # advice semantics are exercised on a raw policy mapping instead.
    gate = _policy_payload()["calibrationGate"]
    del gate["kappaWithCI"]
    partial_policy = {
        "policyId": "cc-auto-advance-policy-002",
        "version": "2.0.0-candidate.1",
        "declaredContentHash": "C" * 64,
        "executionMode": "shadow",
        "calibrationGate": gate,
    }
    advice = policy_activation_advice(assessment, partial_policy)
    field_gaps = [
        gap
        for gap in advice["gaps"]
        if gap["code"] == "missing_calibration_gate_field"
    ]
    assert [gap["field"] for gap in field_gaps] == ["calibrationGate.kappaWithCI"]
    assert field_gaps[0]["message"] == (
        "statistical calibration gate field is required (decision #13)"
    )
    assert advice["advisable"] is False


def test_policy_activation_advice_rejects_active_mode_like_contract() -> None:
    assessment = assess_bundle(_complete_bundle())
    payload = _policy_payload()
    payload["executionMode"] = "active"
    payload["approval"]["contentHash"] = compute_policy_content_hash(payload)
    with pytest.raises(Exception, match="active_mode_forbidden_in_preview"):
        validate_auto_advance_policy_v2(payload)
    active_mapping = {
        "policyId": "cc-auto-advance-policy-002",
        "version": "2.0.0-candidate.1",
        "declaredContentHash": "C" * 64,
        "executionMode": "active",
        "calibrationGate": _policy_payload()["calibrationGate"],
    }
    advice = policy_activation_advice(assessment, active_mapping)
    codes = {gap["code"] for gap in advice["gaps"]}
    assert "active_mode_forbidden_in_preview" in codes
    assert advice["advisable"] is False


def test_policy_activation_advice_reports_pending_evidence() -> None:
    policy = _validated_policy(maxFalseAutoApproveUpperBound=0.35)
    manifest = _manifest()
    bundle = G12CalibrationBundle.build(manifest=manifest, records=[])
    assessment = assess_bundle(bundle)
    advice = policy_activation_advice(assessment, policy)
    assert advice["evidenceStatus"] == ASSESSMENT_STATUS_PENDING
    assert advice["advisable"] is False
    assert any(gap["code"] == "evidence_pending" for gap in advice["gaps"])


# ---------------------------------------------------------------------------
# End to end: manifest -> records -> assessment -> advice
# ---------------------------------------------------------------------------


def test_end_to_end_manifest_to_advice_chain() -> None:
    policy = _validated_policy(maxFalseAutoApproveUpperBound=0.35)
    policy_ref = {
        "policyId": policy.policyId,
        "version": policy.version,
        "contentHash": policy.declaredContentHash,
    }
    manifest = generate_g12_calibration_manifest(
        pool=_pool(),
        policy=policy_ref,
        seed="seed-g12-e2e",
        generated_at="2026-08-28T00:00:00+08:00",
    )
    checklist = collect_pending_records(manifest)
    assert checklist["pendingCount"] == 12
    records = [
        G12JudgementRecord.from_dict(
            {
                "questionId": item["questionId"],
                "sampleKind": item["sampleKind"],
                "autoDecision": "auto_escalate" if item["questionId"] == "q01" else "auto_approve",
                "humanDecision": "escalate" if item["questionId"] == "q01" else "approve",
                "riskClass": "low",
                "domain": "physics",
                "recordedAt": "2026-08-28T01:00:00+08:00",
                "evidenceRef": f"review:g12:{item['questionId']}",
            }
        )
        for item in checklist["pending"]
    ]
    bundle = G12CalibrationBundle.build(manifest=manifest, records=records)
    assert bundle.status == "complete"
    assessment = assess_bundle(bundle, gate_policy=gate_policy_from_policy(policy))
    assert assessment.status == ASSESSMENT_STATUS_COMPLETE
    assert assessment.kappa["tier"] == "strong"
    assert assessment.manifestId == manifest.manifestId
    assert assessment.policyContentHash == policy.declaredContentHash
    advice = policy_activation_advice(assessment, policy)
    assert advice["advisable"] is True
    assert advice["advisableStrata"] == ["low x physics"]
    assert advice["executed"] is False


# ---------------------------------------------------------------------------
# calibration_gate_verdict (executor-facing read-only gate query)
# ---------------------------------------------------------------------------


def test_calibration_gate_verdict_without_bundle_fails_closed() -> None:
    verdict = calibration_gate_verdict(_validated_policy())

    assert verdict["passed"] is False
    assert verdict["reasonCode"] == "calibration_evidence_unavailable"
    assert verdict["status"] == "unavailable"
    assert any("bundle" in reason for reason in verdict["reasons"])


def test_calibration_gate_verdict_pending_bundle_is_not_passed() -> None:
    bundle = G12CalibrationBundle.build(manifest=_manifest(), records=[])

    verdict = calibration_gate_verdict(_validated_policy(), bundle)

    assert verdict["passed"] is False
    assert verdict["reasonCode"] == "evidence_pending"


def test_calibration_gate_verdict_passes_on_complete_agreed_pilot() -> None:
    # The frozen default bound (0.05) mathematically needs a pilot far larger
    # than the 12-question ceiling; declare the bound the pilot can satisfy.
    policy = _validated_policy(maxFalseAutoApproveUpperBound=0.35)
    verdict = calibration_gate_verdict(policy, _complete_bundle())

    assert verdict["passed"] is True
    assert verdict["status"] == "complete"
    assert verdict["reasonCode"] == ""
    assert verdict["evidence"]["kappa"]["kappa"] == pytest.approx(1.0)
    assert verdict["evidence"]["approvableStrata"] == ["low x physics"]
    assert verdict["evidence"]["notAPermanentDelegation"] is True


def test_calibration_gate_verdict_fails_on_degenerate_matrix() -> None:
    # All-auto-approve + all-human-approve: zero variance -> undefined kappa.
    degenerate = [
        _record(f"q{index:02d}") for index in range(1, 13)
    ]
    bundle = G12CalibrationBundle.build(manifest=_manifest(), records=degenerate)

    verdict = calibration_gate_verdict(_validated_policy(), bundle)

    assert verdict["passed"] is False
    assert verdict["status"] == "insufficient"
    assert verdict["reasonCode"] == "evidence_insufficient"
