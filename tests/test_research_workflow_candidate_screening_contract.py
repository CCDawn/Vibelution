"""R2.3 contract tests: five-axis candidate diversity and draft screening.

Freezes ruling 2026-08-28 item 2 (finalistLimit=3, screen-before-pairwise)
and the zero-click plan's five structural axes plus dedup semantics: axis
vocabulary is closed, homogeneous variants merge behind one representative,
ungrounded drafts never reach pairwise review, and the layer is fully
deterministic.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from core.research.workflow.contracts import (
    CANDIDATE_COUNT_RANGE_MAX,
    CANDIDATE_COUNT_RANGE_MIN,
    CANDIDATE_SCREENING_CONTRACT_VERSION,
    DIVERSITY_AXES,
    MAX_FINALIST_LIMIT,
    CandidateScreeningArtifact,
    CandidateScreeningDraft,
    DiversityAxis,
    HypothesisAxisProfile,
    ScreeningRejectionReason,
    ScreeningThresholds,
)
from core.research.workflow.contracts._validation import ContractValidationError
from core.web.services.team_workflow.research_runtime.candidate_screening import (
    screen_candidate_drafts,
)

_SCOPE = {
    "program": "challenge-cup",
    "theme": "bio",
    "campaign": "2026",
    "question": "q-042",
    "branch": "main",
    "workflow": "hypothesis-first",
}
_IDENTITY = {**_SCOPE, "agentId": "agent-1", "mode": "formal"}


def _axis_profile(**overrides: str) -> dict[str, str]:
    values = {
        "mechanism": "抑制 mTOR 信号通路",
        "intervention": "降低给药剂量",
        "observable": "磷酸化蛋白水平下降",
        "population": "成人 EGFR 突变患者",
        "boundary": "II 期临床试验范围",
    }
    values.update(overrides)
    return values


def _checks(*failed: str) -> list[dict[str, object]]:
    return [
        {
            "thresholdId": threshold_id,
            "passed": threshold_id not in failed,
            "detail": (
                f"record for {threshold_id}"
                if threshold_id not in failed
                else f"{threshold_id} is not satisfied"
            ),
        }
        for threshold_id in ("falsifiable_hypothesis", "failure_condition_stated")
    ]


def _draft(
    candidate_id: str,
    *,
    axis_overrides: dict[str, str] | None = None,
    grounded: bool = True,
    refs: tuple[str, ...] = ("evidence-001",),
    failed_thresholds: tuple[str, ...] = (),
    omit_checks: bool = False,
) -> dict[str, object]:
    return {
        "candidateId": candidate_id,
        "axisProfile": _axis_profile(**(axis_overrides or {})),
        "grounded": grounded,
        "groundingEvidenceRefs": list(refs) if grounded else [],
        "hardThresholdChecks": [] if omit_checks else _checks(*failed_thresholds),
    }


def _screen(drafts, **overrides: object) -> CandidateScreeningArtifact:
    params = {
        "screening_id": "screen-001",
        "question_id": "q-042",
        **_SCOPE,
        "agent_id": _IDENTITY["agentId"],
        "mode": _IDENTITY["mode"],
        "drafts": drafts,
        "screened_by": "system.deterministic_screening",
        "created_at": "2026-08-28T00:00:00Z",
    }
    params.update(overrides)
    return screen_candidate_drafts(**params)


def test_five_axis_vocabulary_is_closed_and_profile_parsing_fails_closed() -> None:
    assert tuple(axis.value for axis in DiversityAxis) == DIVERSITY_AXES
    assert DIVERSITY_AXES == (
        "mechanism",
        "intervention",
        "observable",
        "population",
        "boundary",
    )

    profile = HypothesisAxisProfile.from_dict(_axis_profile())
    assert profile.axis_vector() == tuple(
        _axis_profile()[axis] for axis in DIVERSITY_AXES
    )

    incomplete = _axis_profile()
    del incomplete["population"]
    with pytest.raises(ContractValidationError, match="missing axes"):
        HypothesisAxisProfile.from_dict(incomplete)

    with pytest.raises(ContractValidationError, match="unsupported hypothesis axis"):
        HypothesisAxisProfile.from_dict(_axis_profile(extra_axis="x"))

    with pytest.raises(ContractValidationError, match="non-empty"):
        HypothesisAxisProfile.from_dict(_axis_profile(mechanism="   "))

    draft = _draft("cand-1")
    del draft["axisProfile"]
    with pytest.raises(ContractValidationError):
        CandidateScreeningDraft.from_dict(draft)


def test_homogeneous_axis_profiles_merge_behind_one_representative() -> None:
    artifact = _screen(
        [
            _draft("cand-b", refs=("evidence-001", "evidence-002")),
            _draft("cand-a"),
            # Differs on two axes so it stays a distinct candidate.
            _draft(
                "cand-c",
                axis_overrides={
                    "mechanism": "阻断代谢旁路",
                    "intervention": "联合用药",
                },
            ),
        ]
    )

    assert len(artifact.merges) == 1
    merge = artifact.merges[0]
    assert merge.matchKind.value == "homogeneous"
    assert merge.mergedCandidateIds == ("cand-a",)
    assert len(merge.matchedAxes) == len(DIVERSITY_AXES)

    # Representative keeps the strongest grounding evidence (two refs).
    assert merge.representativeId == "cand-b"
    assert artifact.pairwiseCandidateIds == ("cand-b", "cand-c")

    merged_rejections = [
        rejection
        for rejection in artifact.rejections
        if rejection.candidateId in merge.mergedCandidateIds
    ]
    assert {rejection.reason for rejection in merged_rejections} == {
        ScreeningRejectionReason.HOMOGENEOUS_MERGED
    }
    assert all(
        rejection.mergedIntoCandidateId == "cand-b"
        for rejection in merged_rejections
    )
    # Merged candidates keep their lineage in the snapshot.
    assert len(artifact.candidates) == artifact.draftPoolSize == 3


def test_approximate_merge_is_on_by_default_and_configurable() -> None:
    # cand-b differs only on the population axis (4 of 5 axes equal);
    # cand-c differs on two axes and stays distinct.
    variants = [
        _draft("cand-a"),
        _draft("cand-b", axis_overrides={"population": "老年 EGFR 突变患者"}),
        _draft(
            "cand-c",
            axis_overrides={
                "mechanism": "阻断代谢旁路",
                "intervention": "联合用药",
            },
        ),
    ]

    default_artifact = _screen(variants)
    assert len(default_artifact.merges) == 1
    assert default_artifact.merges[0].matchKind.value == "approximate"
    assert default_artifact.merges[0].mergedCandidateIds == ("cand-b",)
    assert default_artifact.merges[0].representativeId == "cand-a"
    assert default_artifact.thresholds.approximateMatchAxes == 4
    assert default_artifact.merges[0].matchedAxes == (
        DiversityAxis.MECHANISM,
        DiversityAxis.INTERVENTION,
        DiversityAxis.OBSERVABLE,
        DiversityAxis.BOUNDARY,
    )
    assert default_artifact.pairwiseCandidateIds == ("cand-a", "cand-c")

    # Two axes differ from the leader: only 3 of 5 match, below the default
    # 4-axis cut, so nothing merges.
    divergent = [
        _draft("cand-a"),
        _draft(
            "cand-b",
            axis_overrides={
                "population": "老年 EGFR 突变患者",
                "intervention": "联合用药",
            },
        ),
        _draft(
            "cand-c",
            axis_overrides={
                "mechanism": "阻断代谢旁路",
                "boundary": "门诊随访场景",
            },
        ),
    ]
    below_cut = _screen(divergent)
    assert below_cut.merges == ()
    assert below_cut.pairwiseCandidateIds == ("cand-a", "cand-b", "cand-c")

    # Lowering the configured cut to 3 folds the whole set into one cluster.
    relaxed = _screen(
        divergent,
        thresholds=ScreeningThresholds(approximateMatchAxes=3),
    )
    assert len(relaxed.merges) == 1
    assert relaxed.merges[0].matchKind.value == "approximate"
    assert relaxed.merges[0].mergedCandidateIds == ("cand-b", "cand-c")
    assert relaxed.pairwiseCandidateIds == ("cand-a",)

    # Disabling approximate matching keeps wording variants distinct.
    disabled = _screen(
        variants,
        thresholds=ScreeningThresholds(enableApproximateMerge=False),
    )
    assert disabled.merges == ()
    assert disabled.pairwiseCandidateIds == ("cand-a", "cand-b", "cand-c")


def test_ungrounded_drafts_never_reach_pairwise_and_reason_is_recorded() -> None:
    artifact = _screen(
        [
            _draft("cand-good"),
            _draft("cand-bad", grounded=False),
        ]
    )
    assert artifact.pairwiseCandidateIds == ("cand-good",)
    bad_rejection = next(
        rejection
        for rejection in artifact.rejections
        if rejection.candidateId == "cand-bad"
    )
    assert bad_rejection.reason is ScreeningRejectionReason.UNGROUNDED
    assert bad_rejection.detail

    # The contract itself enforces the invariant on any parsed artifact.
    payload = artifact.to_dict()
    payload["pairwiseCandidateIds"] = ["cand-good", "cand-bad"]
    with pytest.raises(ContractValidationError, match="ungrounded"):
        CandidateScreeningArtifact.from_dict(payload)

    # grounded=true without evidence references is malformed.
    with pytest.raises(ContractValidationError, match="groundingEvidenceRef"):
        _screen([_draft("cand-noground", grounded=True, refs=())])


def test_hard_threshold_failures_are_screened_out_with_reason() -> None:
    artifact = _screen(
        [
            _draft("cand-ok"),
            _draft("cand-fail", failed_thresholds=("falsifiable_hypothesis",)),
            _draft("cand-missing", refs=("evidence-009",), omit_checks=True),
        ]
    )
    assert artifact.pairwiseCandidateIds == ("cand-ok",)
    reasons = {
        rejection.candidateId: rejection.reason for rejection in artifact.rejections
    }
    assert reasons["cand-fail"] is ScreeningRejectionReason.HARD_THRESHOLD_FAILED
    # A required threshold with no record counts as failed (fail closed).
    assert reasons["cand-missing"] is ScreeningRejectionReason.HARD_THRESHOLD_FAILED

    payload = artifact.to_dict()
    payload["pairwiseCandidateIds"] = ["cand-ok", "cand-fail"]
    with pytest.raises(ContractValidationError, match="required thresholds"):
        CandidateScreeningArtifact.from_dict(payload)


def test_finalist_limit_is_hard_capped_at_three() -> None:
    assert MAX_FINALIST_LIMIT == 3

    with pytest.raises(ContractValidationError, match="finalistLimit"):
        ScreeningThresholds(finalistLimit=4)

    artifact = _screen([_draft("cand-a")])
    payload = artifact.to_dict()
    payload["finalistLimit"] = 4
    payload["thresholds"]["finalistLimit"] = 4
    with pytest.raises(ContractValidationError, match="finalistLimit"):
        CandidateScreeningArtifact.from_dict(payload)

    # Screening output larger than the limit is rejected.
    overflow = artifact.to_dict()
    overflow["finalistLimit"] = 2
    overflow["thresholds"]["finalistLimit"] = 2
    overflow["draftPoolSize"] = 3
    overflow["candidates"] = [
        _draft("cand-a"),
        _draft("cand-b", axis_overrides={"mechanism": "阻断代谢旁路"}),
        _draft("cand-c", axis_overrides={"intervention": "联合用药"}),
    ]
    overflow["rejections"] = []
    overflow["pairwiseCandidateIds"] = ["cand-a", "cand-b", "cand-c"]
    with pytest.raises(ContractValidationError, match="exceeding finalistLimit"):
        CandidateScreeningArtifact.from_dict(overflow)


def test_representatives_beyond_the_limit_reject_as_finalist_overflow() -> None:
    # Each pair differs on at least two axes so no candidate merges.
    drafts = [
        _draft("cand-a"),
        _draft(
            "cand-b",
            axis_overrides={"mechanism": "阻断代谢旁路", "intervention": "联合用药"},
        ),
        _draft(
            "cand-c",
            axis_overrides={"observable": "生存曲线差异", "population": "老年患者队列"},
        ),
        _draft(
            "cand-d",
            axis_overrides={"boundary": "门诊场景", "mechanism": "调节肠道菌群"},
        ),
    ]
    artifact = _screen(drafts, thresholds=ScreeningThresholds(finalistLimit=2))
    assert artifact.pairwiseCandidateIds == ("cand-a", "cand-b")
    overflow_reasons = {
        rejection.candidateId: rejection.reason
        for rejection in artifact.rejections
        if rejection.reason is ScreeningRejectionReason.FINALIST_OVERFLOW
    }
    assert overflow_reasons == {"cand-c": ScreeningRejectionReason.FINALIST_OVERFLOW, "cand-d": ScreeningRejectionReason.FINALIST_OVERFLOW}


def test_screening_is_deterministic_and_input_order_independent() -> None:
    drafts = [
        _draft("cand-b", refs=("evidence-001", "evidence-002")),
        _draft("cand-a"),
        _draft(
            "cand-c",
            axis_overrides={"mechanism": "阻断代谢旁路"},
            grounded=False,
        ),
    ]
    first = _screen(deepcopy(drafts))
    second = _screen(deepcopy(drafts))
    assert first == second
    assert first.to_dict() == second.to_dict()

    shuffled = list(reversed(deepcopy(drafts)))
    assert _screen(shuffled) == first
    assert _screen(shuffled).to_dict() == first.to_dict()


def test_empty_pool_rejected_and_single_candidate_advances_alone() -> None:
    with pytest.raises(ContractValidationError, match="empty"):
        _screen([])

    single = _screen([_draft("cand-only")])
    assert single.pairwiseCandidateIds == ("cand-only",)
    assert single.rejections == ()
    assert single.draftPoolSize == 1

    only_ungrounded = _screen([_draft("cand-only", grounded=False)])
    assert only_ungrounded.pairwiseCandidateIds == ()
    assert only_ungrounded.rejections[0].reason is ScreeningRejectionReason.UNGROUNDED


def test_artifact_roundtrip_and_complete_rejection_accounting() -> None:
    artifact = _screen(
        [
            _draft("cand-b", refs=("evidence-001", "evidence-002")),
            _draft("cand-a"),
            _draft(
                "cand-c",
                axis_overrides={
                    "mechanism": "阻断代谢旁路",
                    "intervention": "联合用药",
                },
            ),
            _draft("cand-d", grounded=False),
        ]
    )
    assert artifact.contractVersion == CANDIDATE_SCREENING_CONTRACT_VERSION
    assert CandidateScreeningArtifact.from_dict(artifact.to_dict()) == artifact

    # Every candidate is exactly one of pairwise / merged / rejected.
    accounted = set(artifact.pairwiseCandidateIds) | {
        rejection.candidateId for rejection in artifact.rejections
    }
    assert accounted == {candidate.candidateId for candidate in artifact.candidates}
    assert artifact.candidate_by_id("cand-d") is not None
    assert artifact.candidate_by_id("missing") is None
    assert CANDIDATE_COUNT_RANGE_MIN == 2
    assert CANDIDATE_COUNT_RANGE_MAX == 6
