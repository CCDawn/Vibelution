"""R4.4: audit sample manifest contracts + deterministic sampling service.

Covers the frozen decision-#5/#13 review carriers: G12 calibration pilot
manifests, G125 sequential batches, the three rolling drift sentinels drawn
from the second half of G125 low-risk questions, and the one-way
manifest-level approval state machine.  Pure contracts + derivation only;
no execution, no approval side effects.
"""

from __future__ import annotations

import pytest

from core.research.workflow.contracts import ContractValidationError
from core.research.workflow.contracts.audit_sampling import (
    DRIFT_SENTINEL_COUNT,
    AuditSampleManifest,
    DriftSentinelSelection,
    SampleKind,
    audit_sample_manifest_hash,
)
from core.web.services.team_workflow.research_runtime.audit_sampling_service import (
    DEFAULT_G125_BATCH_SIZE,
    LOW_RISK_CLASS,
    AuditSamplingError,
    assert_policy_binding,
    bind_sentinel_selection_to_manifest,
    draw_g125_batch,
    generate_full_review_manifest,
    generate_g125_batch_manifest,
    generate_g12_calibration_manifest,
    sampling_matrix,
    second_half_question_ids,
    select_drift_sentinels,
)

GENERATED_AT = "2026-08-28T12:00:00+08:00"


def _policy(content_hash: str = "a" * 64) -> dict:
    return {
        "policyId": "cc-human-review-policy-002",
        "version": "2.0.0-candidate.1",
        "contentHash": content_hash,
    }


def _g12_pool() -> list[dict]:
    risks = ["low_risk_standard", "medium_risk_standard", "high_risk_specialty"]
    domains = ["neuroscience", "physics"]
    return [
        {
            "questionId": f"SCI-{index + 1:03d}",
            "riskClass": risks[index % 3],
            "catalogDomain": domains[index % 2],
        }
        for index in range(12)
    ]


def _sequential_pool(size: int = 13) -> list[dict]:
    return [
        {
            "questionId": f"B{index + 1:02d}",
            "riskClass": LOW_RISK_CLASS,
            "catalogDomain": "biology",
        }
        for index in range(size)
    ]


def _sentinel_pool() -> list[dict]:
    pool: list[dict] = []
    for index in range(1, 21):
        question_id = f"Q{index:02d}"
        if index <= 2:
            risk = LOW_RISK_CLASS  # first-half low risk: never sentinel-eligible
        elif index == 12:
            risk = "medium_risk_standard"  # second half but not low risk
        elif index <= 10:
            risk = "medium_risk_standard" if index % 2 == 0 else "high_risk_specialty"
        else:
            risk = LOW_RISK_CLASS
        pool.append(
            {
                "questionId": question_id,
                "riskClass": risk,
                "catalogDomain": "physics" if index % 2 else "biology",
            }
        )
    return pool


def _remaining(pool: list[dict], drawn: tuple[str, ...]) -> list[dict]:
    return [entry for entry in pool if entry["questionId"] not in set(drawn)]


def test_same_seed_reproduces_identical_manifests() -> None:
    policy = _policy()
    first = generate_g125_batch_manifest(
        pool=_sequential_pool(),
        policy=policy,
        seed="seed-audit-1",
        batch_index=1,
        generated_at=GENERATED_AT,
    )
    second = generate_g125_batch_manifest(
        pool=_sequential_pool(),
        policy=policy,
        seed="seed-audit-1",
        batch_index=1,
        generated_at=GENERATED_AT,
    )
    assert first == second
    assert first.manifestHash == second.manifestHash
    assert first.manifestHash == audit_sample_manifest_hash(first)
    assert AuditSampleManifest.from_dict(first.to_dict()) == first

    other_seed = generate_g125_batch_manifest(
        pool=_sequential_pool(),
        policy=policy,
        seed="seed-audit-2",
        batch_index=1,
        generated_at=GENERATED_AT,
    )
    assert other_seed.questionIds != first.questionIds

    g12_first = generate_g12_calibration_manifest(
        pool=_g12_pool(), policy=policy, seed="seed-g12", generated_at=GENERATED_AT
    )
    g12_second = generate_g12_calibration_manifest(
        pool=_g12_pool(), policy=policy, seed="seed-g12", generated_at=GENERATED_AT
    )
    assert g12_first == g12_second
    assert g12_first.gate == "G12"
    assert set(g12_first.questionIds) == {
        entry["questionId"] for entry in _g12_pool()
    }
    assert all(
        g12_first.sampleKinds[question_id] is SampleKind.G12_CALIBRATION
        for question_id in g12_first.questionIds
    )
    assert set(g12_first.strata) == {"risk_class", "catalog_domain"}


def test_g125_sequential_batches_cover_pool_without_overlap() -> None:
    policy = _policy()
    pool = _sequential_pool(13)
    assert DEFAULT_G125_BATCH_SIZE == 5

    remaining = list(pool)
    batches: list[tuple[str, ...]] = []
    batch_index = 1
    while remaining:
        manifest = generate_g125_batch_manifest(
            pool=remaining,
            policy=policy,
            seed="seed-batch",
            batch_index=batch_index,
            generated_at=GENERATED_AT,
        )
        assert len(manifest.questionIds) == min(DEFAULT_G125_BATCH_SIZE, len(remaining))
        assert all(
            manifest.sampleKinds[question_id] is SampleKind.G125_SEQUENTIAL
            for question_id in manifest.questionIds
        )
        batches.append(manifest.questionIds)
        remaining = _remaining(remaining, manifest.questionIds)
        batch_index += 1

    assert [len(batch) for batch in batches] == [5, 5, 3]
    assert draw_g125_batch(
        pool=pool, seed="seed-batch", batch_index=1
    ) == batches[0]
    with pytest.raises(AuditSamplingError, match="batch_index"):
        generate_g125_batch_manifest(
            pool=pool,
            policy=policy,
            seed="seed-batch",
            batch_index=0,
            generated_at=GENERATED_AT,
        )
    with pytest.raises(AuditSamplingError, match="empty"):
        generate_g125_batch_manifest(
            pool=[],
            policy=policy,
            seed="seed-batch",
            batch_index=4,
            generated_at=GENERATED_AT,
        )


def test_drift_sentinels_come_from_second_half_low_risk_exactly_three() -> None:
    policy = _policy()
    pool = _sentinel_pool()
    second_half = set(second_half_question_ids(pool))
    assert second_half == {f"Q{index:02d}" for index in range(11, 21)}

    selection = select_drift_sentinels(
        pool=pool, policy=policy, seed="seed-sentinel", generated_at=GENERATED_AT
    )
    again = select_drift_sentinels(
        pool=pool, policy=policy, seed="seed-sentinel", generated_at=GENERATED_AT
    )
    assert selection == again
    assert len(selection.selectedQuestionIds) == DRIFT_SENTINEL_COUNT == 3
    assert set(selection.selectedQuestionIds) <= second_half
    for question_id in selection.selectedQuestionIds:
        entry = next(item for item in pool if item["questionId"] == question_id)
        assert entry["riskClass"] == LOW_RISK_CLASS
    assert set(selection.exclusions) == set(selection.candidatePool) - set(
        selection.selectedQuestionIds
    )
    exclusion_reasons = {
        exclusion.questionId: exclusion.reason for exclusion in selection.preDrawExclusions
    }
    assert exclusion_reasons["Q01"] == "outside_second_half"
    assert exclusion_reasons["Q03"] == "outside_second_half"
    assert exclusion_reasons["Q12"] == "not_low_risk"
    assert DriftSentinelSelection.from_dict(selection.to_dict()) == selection

    other_seed = select_drift_sentinels(
        pool=pool, policy=policy, seed="seed-sentinel-2", generated_at=GENERATED_AT
    )
    assert other_seed.selectedQuestionIds != selection.selectedQuestionIds

    # Questions drawn in the current batch are excluded before the draw.
    batch = draw_g125_batch(
        pool=pool, seed="seed-batch", batch_index=1, batch_size=5
    )
    collision_safe = select_drift_sentinels(
        pool=pool,
        policy=policy,
        seed="seed-sentinel",
        generated_at=GENERATED_AT,
        exclude_question_ids=batch,
    )
    assert not set(collision_safe.selectedQuestionIds) & set(batch)

    # Fewer than three eligible candidates fails closed.
    small_pool = [
        {"questionId": "S01", "riskClass": LOW_RISK_CLASS, "catalogDomain": "physics"},
        {"questionId": "S02", "riskClass": LOW_RISK_CLASS, "catalogDomain": "physics"},
    ]
    with pytest.raises(AuditSamplingError, match="candidate pool"):
        select_drift_sentinels(
            pool=small_pool,
            policy=policy,
            seed="seed-sentinel",
            generated_at=GENERATED_AT,
        )

    # Full composition: batch manifest + bound sentinels.
    batch_manifest = generate_g125_batch_manifest(
        pool=pool,
        policy=policy,
        seed="seed-batch",
        batch_index=1,
        generated_at=GENERATED_AT,
    )
    composed = generate_g125_batch_manifest(
        pool=pool,
        policy=policy,
        seed="seed-batch",
        batch_index=1,
        generated_at=GENERATED_AT,
        sentinel_selection=bind_sentinel_selection_to_manifest(
            collision_safe, manifest_id=batch_manifest.manifestId
        ),
    )
    assert len(composed.drift_sentinel_question_ids()) == 3
    assert not set(composed.drift_sentinel_question_ids()) & set(batch_manifest.questionIds)
    with pytest.raises(AuditSamplingError, match="already sampled"):
        # A batch that drew the WHOLE pool collides with any sentinel draw
        # from the same pool, deterministically.
        colliding = select_drift_sentinels(
            pool=pool, policy=policy, seed="seed-sentinel", generated_at=GENERATED_AT
        )
        generate_g125_batch_manifest(
            pool=pool,
            policy=policy,
            seed="seed-collision",
            batch_index=1,
            batch_size=len(pool),
            generated_at=GENERATED_AT,
            sentinel_selection=colliding,
        )


def test_policy_reference_binding_is_fail_closed() -> None:
    policy = _policy()
    manifest = generate_g12_calibration_manifest(
        pool=_g12_pool(), policy=policy, seed="seed-g12", generated_at=GENERATED_AT
    )

    assert_policy_binding(manifest, policy)
    with pytest.raises(AuditSamplingError, match="policy binding"):
        assert_policy_binding(manifest, _policy("b" * 64))
    with pytest.raises(AuditSamplingError, match="policyId"):
        assert_policy_binding(
            manifest, {"policyId": "", "version": "2.0.0-candidate.1", "contentHash": "a" * 64}
        )

    payload = manifest.to_dict()
    payload.pop("policyContentHash")
    with pytest.raises(ContractValidationError, match="policyContentHash"):
        AuditSampleManifest.from_dict(payload)

    payload = manifest.to_dict()
    payload["policyContentHash"] = "not-a-hash"
    with pytest.raises(ContractValidationError):
        AuditSampleManifest.from_dict(payload)

    payload = manifest.to_dict()
    payload["manifestHash"] = "c" * 64
    with pytest.raises(ContractValidationError, match="manifestHash"):
        AuditSampleManifest.from_dict(payload)

    with pytest.raises(AuditSamplingError, match="contentHash"):
        generate_g12_calibration_manifest(
            pool=_g12_pool(),
            policy={"policyId": "p", "version": "1", "contentHash": "nope"},
            seed="seed-g12",
            generated_at=GENERATED_AT,
        )


def test_manifest_review_status_is_one_way() -> None:
    policy = _policy()
    manifest = generate_g12_calibration_manifest(
        pool=_g12_pool(), policy=policy, seed="seed-g12", generated_at=GENERATED_AT
    )
    assert manifest.reviewStatus == "pending"
    assert manifest.reviewedBy == "" and manifest.reviewedAt == ""

    approved = manifest.with_review_decision(
        status="approved",
        reviewed_by="competition_owner",
        reviewed_at="2026-08-28T13:00:00+08:00",
    )
    assert approved.reviewStatus == "approved"
    assert approved.reviewedBy == "competition_owner"
    assert approved.manifestHash == audit_sample_manifest_hash(approved)
    assert AuditSampleManifest.from_dict(approved.to_dict()) == approved

    with pytest.raises(ContractValidationError, match="approved or rejected"):
        manifest.with_review_decision(
            status="deferred",
            reviewed_by="competition_owner",
            reviewed_at="2026-08-28T13:00:00+08:00",
        )
    with pytest.raises(ContractValidationError, match="reviewedBy"):
        manifest.with_review_decision(status="approved", reviewed_by="", reviewed_at="x")
    with pytest.raises(ContractValidationError, match="already decided"):
        approved.with_review_decision(
            status="rejected",
            reviewed_by="competition_owner",
            reviewed_at="2026-08-28T14:00:00+08:00",
        )
    with pytest.raises(ContractValidationError, match="already decided"):
        approved.with_review_decision(
            status="approved",
            reviewed_by="competition_owner",
            reviewed_at="2026-08-28T14:00:00+08:00",
        )

    rejected = manifest.with_review_decision(
        status="rejected",
        reviewed_by="competition_owner",
        reviewed_at="2026-08-28T13:00:00+08:00",
    )
    assert rejected.reviewStatus == "rejected"
    with pytest.raises(ContractValidationError, match="already decided"):
        rejected.with_review_decision(
            status="approved",
            reviewed_by="competition_owner",
            reviewed_at="2026-08-28T14:00:00+08:00",
        )

    payload = manifest.to_dict()
    payload["reviewedBy"] = "premature"
    with pytest.raises(ContractValidationError, match="reviewer identity"):
        AuditSampleManifest.from_dict(payload)

    payload = approved.to_dict()
    payload.pop("reviewedBy")
    with pytest.raises(ContractValidationError, match="reviewedBy"):
        AuditSampleManifest.from_dict(payload)


def test_unknown_strata_axes_and_values_are_rejected() -> None:
    policy = _policy()
    manifest = generate_g12_calibration_manifest(
        pool=_g12_pool(), policy=policy, seed="seed-g12", generated_at=GENERATED_AT
    )

    payload = manifest.to_dict()
    payload["strata"] = {"weather": ["sunny"]}
    with pytest.raises(ContractValidationError, match="unknown strata axis"):
        AuditSampleManifest.from_dict(payload)

    payload = manifest.to_dict()
    payload.pop("strata")
    with pytest.raises(ContractValidationError, match="strata"):
        AuditSampleManifest.from_dict(payload)

    payload = manifest.to_dict()
    payload["strata"] = {"run_phase": ["middle_third"]}
    with pytest.raises(ContractValidationError, match="run_phase"):
        AuditSampleManifest.from_dict(payload)

    payload = manifest.to_dict()
    payload["strata"] = {"risk_class": []}
    with pytest.raises(ContractValidationError, match="non-empty"):
        AuditSampleManifest.from_dict(payload)

    service_manifest = generate_g125_batch_manifest(
        pool=[
            {
                "questionId": "R01",
                "riskClass": LOW_RISK_CLASS,
                "catalogDomain": "physics",
                "runPhase": "second_half",
            }
        ],
        policy=policy,
        seed="seed-run",
        batch_index=1,
        batch_size=1,
        generated_at=GENERATED_AT,
    )
    assert service_manifest.strata["run_phase"] == ("second_half",)


def test_unknown_kinds_conflicting_kinds_and_missing_seed_fail_closed() -> None:
    policy = _policy()
    manifest = generate_g125_batch_manifest(
        pool=_sequential_pool(5),
        policy=policy,
        seed="seed-kind",
        batch_index=1,
        generated_at=GENERATED_AT,
    )

    payload = manifest.to_dict()
    payload["sampleAssignments"][0]["sampleKind"] = "kind_of_the_day"
    with pytest.raises(ContractValidationError, match="unknown sampleKind"):
        AuditSampleManifest.from_dict(payload)

    payload = manifest.to_dict()
    conflicted = dict(payload["sampleAssignments"][0])
    conflicted["sampleKind"] = SampleKind.DRIFT_SENTINEL.value
    payload["sampleAssignments"] = [
        payload["sampleAssignments"][0],
        conflicted,
        *payload["sampleAssignments"][1:],
    ]
    with pytest.raises(ContractValidationError, match="conflicting sampleKind"):
        AuditSampleManifest.from_dict(payload)

    payload = manifest.to_dict()
    payload["seed"] = ""
    with pytest.raises(ContractValidationError, match="seed"):
        AuditSampleManifest.from_dict(payload)

    payload = manifest.to_dict()
    payload["gate"] = "G999"
    with pytest.raises(ContractValidationError, match="gate"):
        AuditSampleManifest.from_dict(payload)

    base_payload = manifest.to_dict()
    two_sentinel_payload = {
        **base_payload,
        "questionIds": ["X01", "X02", "X03"],
        "sampleAssignments": [
            {"questionId": "X01", "sampleKind": "drift_sentinel"},
            {"questionId": "X02", "sampleKind": "drift_sentinel"},
            {"questionId": "X03", "sampleKind": "g125_sequential"},
        ],
    }
    with pytest.raises(ContractValidationError, match="exactly 3"):
        AuditSampleManifest.from_dict(two_sentinel_payload)

    four_sentinel_payload = {
        **base_payload,
        "questionIds": ["X01", "X02", "X03", "X04"],
        "sampleAssignments": [
            {"questionId": question_id, "sampleKind": "drift_sentinel"}
            for question_id in ("X01", "X02", "X03", "X04")
        ],
    }
    with pytest.raises(ContractValidationError, match="exactly 3"):
        AuditSampleManifest.from_dict(four_sentinel_payload)

    with pytest.raises(ContractValidationError, match="exactly 3"):
        DriftSentinelSelection.from_dict(
            {
                "selectionId": "sel-1",
                "gate": "G125",
                "seed": "s",
                "candidatePool": ["X01", "X02"],
                "secondHalfStartIndex": 0,
                "selectedQuestionIds": ["X01"],
                "exclusions": {"X02": "not_drawn"},
                "preDrawExclusions": [],
                "selectionRuleVersion": "v1",
                "selectedAt": GENERATED_AT,
            }
        )
    with pytest.raises(ContractValidationError, match="candidate pool"):
        DriftSentinelSelection.from_dict(
            {
                "selectionId": "sel-2",
                "gate": "G125",
                "seed": "s",
                "candidatePool": ["X01", "X02", "X03"],
                "secondHalfStartIndex": 0,
                "selectedQuestionIds": ["X01", "X02", "X99"],
                "exclusions": {},
                "preDrawExclusions": [],
                "selectionRuleVersion": "v1",
                "selectedAt": GENERATED_AT,
            }
        )


def test_sampling_matrix_and_full_review_manifests() -> None:
    policy = _policy()
    pool = _g12_pool()
    manifest = generate_g125_batch_manifest(
        pool=pool,
        policy=policy,
        seed="seed-matrix",
        batch_index=1,
        batch_size=5,
        generated_at=GENERATED_AT,
    )
    matrix = sampling_matrix(pool=pool, sampled_question_ids=manifest.questionIds)
    assert matrix["totals"] == {"pool": 12, "sampled": 5}
    assert sum(row["poolCount"] for row in matrix["strataRows"]) == 12
    assert sum(row["sampledCount"] for row in matrix["strataRows"]) == 5
    with pytest.raises(AuditSamplingError, match="come from the pool"):
        sampling_matrix(pool=pool, sampled_question_ids=["NOPE-1"])

    flagged = manifest.questionIds[:2]
    anomaly = generate_full_review_manifest(
        gate="G125",
        pool=pool,
        sample_kind=SampleKind.ANOMALY_FULL_REVIEW,
        policy=policy,
        seed="seed-anomaly",
        generated_at=GENERATED_AT,
        question_ids=flagged,
    )
    assert all(
        anomaly.sampleKinds[question_id] is SampleKind.ANOMALY_FULL_REVIEW
        for question_id in anomaly.questionIds
    )
    risk_manifest = generate_full_review_manifest(
        gate="G5",
        pool=pool,
        sample_kind="risk_triggered_full_review",
        policy=policy,
        seed="seed-risk",
        generated_at=GENERATED_AT,
    )
    assert set(risk_manifest.questionIds) == {entry["questionId"] for entry in pool}
    with pytest.raises(AuditSamplingError, match="only support"):
        generate_full_review_manifest(
            gate="G12",
            pool=pool,
            sample_kind=SampleKind.G12_CALIBRATION,
            policy=policy,
            seed="seed-bad",
            generated_at=GENERATED_AT,
        )
    with pytest.raises(AuditSamplingError, match="come from the given pool"):
        generate_full_review_manifest(
            gate="G125",
            pool=pool,
            sample_kind=SampleKind.ANOMALY_FULL_REVIEW,
            policy=policy,
            seed="seed-anomaly",
            generated_at=GENERATED_AT,
            question_ids=["NOPE-1"],
        )
