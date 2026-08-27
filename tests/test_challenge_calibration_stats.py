"""Numerical correctness tests for the G12 calibration statistics layer.

Every expected constant below is either (a) a hand-derived closed form
(the derivation is written out in the comment next to it) or (b) computed
by an independent method inside this file (binomial-tail bisection for
Beta quantiles -- no shared code path with the continued-fraction
implementation under test). Pure computation, no network.
"""

from __future__ import annotations

import math
from math import comb

import pytest

from core.research.competition.calibration_stats import (
    CalibrationStatsError,
    ConfusionMatrix,
    activation_gate_assessment,
    beta_quantile,
    build_confusion_matrix,
    cohens_kappa_with_ci,
    false_auto_approve_upper_bound,
    kappa_tier,
    regularized_incomplete_beta,
    stratum_report,
)

Z95_ONE_SIDED = 1.6448536269514715  # Phi^-1(0.95), stdlib statistics.NormalDist


def _record(
    auto: str,
    human: str,
    risk_class: str = "low",
    domain: str = "physics",
) -> dict[str, str]:
    return {
        "autoDecision": auto,
        "humanDecision": human,
        "riskClass": risk_class,
        "domain": domain,
    }


def _batch_12_with_one_failure() -> list[dict[str, str]]:
    """G12 pilot shape: 12 low-risk items, 1 false auto approve."""
    records = [_record("auto_approve", "approve") for _ in range(11)]
    records.append(_record("auto_approve", "escalate"))
    return records


# ---------------------------------------------------------------------------
# Confusion matrix aggregation
# ---------------------------------------------------------------------------


def test_confusion_matrix_counts_positive_class_escalate() -> None:
    records = [
        _record("auto_approve", "approve"),
        _record("auto_approve", "escalate"),  # false auto approve (critical)
        _record("auto_escalate", "approve"),  # false escalate
        _record("auto_escalate", "escalate"),
    ]
    matrix = build_confusion_matrix(records)
    assert matrix == ConfusionMatrix(
        true_positives=1, false_positives=1, false_negatives=1, true_negatives=1
    )
    assert matrix.false_auto_approve_count == 1
    assert matrix.false_escalate_count == 1
    assert matrix.total == 4
    assert matrix.prevalence == pytest.approx(0.5)
    assert matrix.observed_agreement == pytest.approx(0.5)


def test_confusion_matrix_accepts_snake_case_aliases() -> None:
    matrix = build_confusion_matrix(
        [
            {
                "auto_decision": "auto_approve",
                "human_decision": "approve",
                "risk_class": "low",
                "domain": "chemistry",
            }
        ]
    )
    assert matrix.true_negatives == 1


def test_confusion_matrix_fails_closed_on_unknown_or_missing_fields() -> None:
    with pytest.raises(CalibrationStatsError, match="autoDecision"):
        build_confusion_matrix([_record("maybe_auto", "approve")])
    with pytest.raises(CalibrationStatsError, match="humanDecision"):
        build_confusion_matrix([_record("auto_approve", "maybe_escalate")])
    with pytest.raises(CalibrationStatsError, match="risk_class"):
        build_confusion_matrix(
            [{"autoDecision": "auto_approve", "humanDecision": "approve"}]
        )


def test_normalize_risk_class_aliases() -> None:
    from core.research.competition.calibration_stats import normalize_risk_class

    assert normalize_risk_class("low_risk") == "low"
    assert normalize_risk_class("HIGH-RISK") == "high"
    assert normalize_risk_class("medium") == "medium"


# ---------------------------------------------------------------------------
# Cohen's kappa: literature / hand-derived reference values
# ---------------------------------------------------------------------------


def test_kappa_matches_hand_derived_textbook_examples() -> None:
    # Matrix (Wikipedia "Cohen's kappa" worked example, rater A rows):
    # [[20, 5], [10, 15]] -> p0 = 35/50 = 0.70,
    # pe = (25*30 + 25*20)/50^2 = 0.50, kappa = (0.70-0.50)/(1-0.50) = 0.40.
    matrix = build_confusion_matrix(
        [_record("auto_escalate", "escalate")] * 20
        + [_record("auto_escalate", "approve")] * 5
        + [_record("auto_approve", "escalate")] * 10
        + [_record("auto_approve", "approve")] * 15
    )
    result = cohens_kappa_with_ci(matrix)
    assert result.defined
    assert result.kappa == pytest.approx((0.70 - 0.50) / (1 - 0.50))
    assert result.kappa == pytest.approx(0.4, abs=1e-12)
    assert result.observed_agreement == pytest.approx(0.70)
    assert result.expected_agreement == pytest.approx(0.50)
    assert not result.prevalence_paradox_suspected
    assert result.tier == kappa_tier(0.4) == "below_gate"

    # Hand-derived second example: [[50, 10], [20, 20]] ->
    # p0 = 70/100 = 0.70, pe = (60*70 + 40*30)/100^2 = 0.54,
    # kappa = (0.70 - 0.54)/(1 - 0.54) = 0.16/0.46.
    matrix2 = build_confusion_matrix(
        [_record("auto_escalate", "escalate")] * 50
        + [_record("auto_escalate", "approve")] * 10
        + [_record("auto_approve", "escalate")] * 20
        + [_record("auto_approve", "approve")] * 20
    )
    result2 = cohens_kappa_with_ci(matrix2)
    assert result2.kappa == pytest.approx((0.70 - 0.54) / (1 - 0.54))
    assert result2.kappa == pytest.approx(0.3478260869565216, abs=1e-12)


def test_kappa_ci_matches_hand_computed_fleiss_interval() -> None:
    # Same [[20, 5], [10, 15]] example; Fleiss (1971) fixed-pe SE:
    # SE = sqrt(0.7 * 0.3 / (50 * (1 - 0.5)^2)) = sqrt(0.0168)
    #    = 0.12961481396815722,
    # 95% CI = 0.4 -/+ 1.9599639845400536 * SE
    #        = [0.14595963275955265, 0.6540403672404471].
    matrix = build_confusion_matrix(
        [_record("auto_escalate", "escalate")] * 20
        + [_record("auto_escalate", "approve")] * 5
        + [_record("auto_approve", "escalate")] * 10
        + [_record("auto_approve", "approve")] * 15
    )
    result = cohens_kappa_with_ci(matrix, confidence=0.95)
    se = math.sqrt(0.7 * 0.3 / (50 * 0.25))
    assert result.ci_low == pytest.approx(0.4 - 1.9599639845400536 * se)
    assert result.ci_high == pytest.approx(0.4 + 1.9599639845400536 * se)
    assert result.ci_low == pytest.approx(0.14595963275955265, abs=1e-12)
    assert result.ci_high == pytest.approx(0.6540403672404471, abs=1e-12)


def test_kappa_boundary_cases_are_defined_without_division_errors() -> None:
    # Perfect agreement with balanced marginals: p0 = 1, pe = 0.5 -> kappa = 1.
    perfect = build_confusion_matrix(
        [_record("auto_escalate", "escalate")] * 20
        + [_record("auto_approve", "approve")] * 20
    )
    result = cohens_kappa_with_ci(perfect)
    assert result.defined
    assert result.kappa == pytest.approx(1.0)
    assert result.ci_low == pytest.approx(1.0)
    assert result.ci_high == pytest.approx(1.0)
    assert result.tier == "strong"

    # Complete disagreement: p0 = 0, pe = 0.5 -> kappa = -1.
    disagree = build_confusion_matrix(
        [_record("auto_escalate", "approve")] * 20
        + [_record("auto_approve", "escalate")] * 20
    )
    result_neg = cohens_kappa_with_ci(disagree)
    assert result_neg.defined
    assert result_neg.kappa == pytest.approx(-1.0)
    assert result_neg.tier == "below_gate"


def test_kappa_undefined_on_zero_variance_marginals() -> None:
    # Single cell only: pe == 1 -> kappa would divide by zero; must report
    # defined=False instead of crashing, and read as "not approvable".
    degenerate = build_confusion_matrix(
        [_record("auto_approve", "approve")] * 12
    )
    result = cohens_kappa_with_ci(degenerate)
    assert not result.defined
    assert result.kappa is None
    assert result.ci_low is None and result.ci_high is None
    assert result.tier == "undefined"
    assert "undefined" in result.note

    empty = cohens_kappa_with_ci(build_confusion_matrix([]))
    assert not empty.defined


def test_kappa_flags_prevalence_paradox_on_skewed_marginals() -> None:
    # [[90, 2], [3, 5]]: p0 = 0.95, pe = (92*93 + 7*8)/100^2 = 0.8612 >= 0.8,
    # kappa = (0.95 - 0.8612)/(1 - 0.8612) = 0.63976945... yet agreement is
    # near perfect -- the classic prevalence paradox setup.
    skewed = build_confusion_matrix(
        [_record("auto_escalate", "escalate")] * 90
        + [_record("auto_escalate", "approve")] * 2
        + [_record("auto_approve", "escalate")] * 3
        + [_record("auto_approve", "approve")] * 5
    )
    result = cohens_kappa_with_ci(skewed)
    assert result.kappa == pytest.approx(
        (0.95 - 0.8612) / (1 - 0.8612), abs=1e-12
    )
    assert result.prevalence_paradox_suspected
    assert "prevalence paradox" in result.note

    balanced = cohens_kappa_with_ci(
        build_confusion_matrix(
            [_record("auto_escalate", "escalate")] * 20
            + [_record("auto_approve", "approve")] * 20
        )
    )
    assert not balanced.prevalence_paradox_suspected


def test_kappa_tier_thresholds() -> None:
    assert kappa_tier(0.75) == "strong"
    assert kappa_tier(0.749) == "acceptable"
    assert kappa_tier(0.6) == "acceptable"
    assert kappa_tier(0.599) == "below_gate"
    assert kappa_tier(None) == "undefined"


# ---------------------------------------------------------------------------
# One-sided upper bounds: Wilson closed forms and Beta-binomial references
# ---------------------------------------------------------------------------


class TestWilsonUpperBound:
    """Wilson one-sided upper bound vs hand-derived closed-form values.

    Closed form (z = Phi^-1(confidence), phat = x/n):
        u = (phat + z^2/(2n) + z*sqrt(phat(1-phat)/n + z^2/(4n^2)))
            / (1 + z^2/n)
    with z = 1.6448536269514715 for one-sided 95%.
    """

    def test_zero_failures_matches_identity(self) -> None:
        # For x = 0 the closed form collapses to z^2/(n + z^2):
        # 2.7055434540954 / (12 + 2.7055434540954) = 0.18398119474747684.
        bound = false_auto_approve_upper_bound(12, 0, method="wilson")
        assert bound == pytest.approx(Z95_ONE_SIDED**2 / (12 + Z95_ONE_SIDED**2))
        assert bound == pytest.approx(0.18398119474747684, abs=1e-12)
        # 0/12 also via the collapsed identity at n=60 scale sanity:
        assert false_auto_approve_upper_bound(60, 0, method="wilson") == (
            pytest.approx(Z95_ONE_SIDED**2 / (60 + Z95_ONE_SIDED**2))
        )

    def test_one_of_twelve(self) -> None:
        # x=1, n=12: phat=1/12, radicand = (1/12)(11/12) + z^2/4
        #   = 0.916666... + 0.676385863523851 = 1.593052530190518,
        # sqrt = 1.2621620...; u = (0.0833333 + 0.1127310 + 1.6448536*1.2621620)
        #   / 1.2254620 = 0.30116827943986885.
        bound = false_auto_approve_upper_bound(12, 1, method="wilson")
        assert bound == pytest.approx(0.30116827943986885, abs=1e-12)
        assert bound > 1 / 12  # a bound below the point estimate is impossible

    def test_three_of_sixty(self) -> None:
        # x=3, n=60: phat=0.05, radicand = 0.05*0.95/60 + z^2/4
        #   = 0.00079166... + 0.676385863523851 = 0.6771775301905179,
        # u = (0.05 + 0.02254619... + 1.6448536*0.822907...) / 1.0450923...
        #   = 0.11867513258726377.
        bound = false_auto_approve_upper_bound(60, 3, method="wilson")
        assert bound == pytest.approx(0.11867513258726377, abs=1e-12)

    def test_other_confidence_levels(self) -> None:
        # One-sided 99%: z = 2.3263478740408408 for 1/12 -> 0.4141230008320505.
        bound = false_auto_approve_upper_bound(12, 1, confidence=0.99)
        assert bound == pytest.approx(0.4141230008320505, abs=1e-12)
        # Sanity: a tighter confidence level gives a tighter (smaller) bound.
        assert (
            false_auto_approve_upper_bound(12, 1, confidence=0.90)
            < false_auto_approve_upper_bound(12, 1, confidence=0.95)
        )


class _IndependentBetaQuantile:
    """Binomial-tail bisection: shares no code with the implementation.

    Uses the identity that for integer a, b:
        I_p(a, b) = P(X >= a) for X ~ Bin(a + b - 1, p),
    so the p-quantile of Beta(a, b) is the root of the binomial tail.
    """

    @staticmethod
    def solve(confidence: float, a: int, b: int) -> float:
        nmax = a + b - 1

        def tail(p: float) -> float:
            return sum(
                comb(nmax, k) * p**k * (1 - p) ** (nmax - k)
                for k in range(a, nmax + 1)
            )

        lo, hi = 0.0, 1.0
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if tail(mid) < confidence:
                lo = mid
            else:
                hi = mid
            if hi - lo < 1e-16:
                break
        return 0.5 * (lo + hi)


class TestBetaBinomialUpperBound:
    """Beta(1, 1) prior posterior quantiles vs independent references."""

    def test_zero_failures_closed_form(self) -> None:
        # 0/12 -> posterior Beta(1, 13); CDF is 1 - (1-x)^13, so the 0.95
        # quantile is 1 - 0.05^(1/13) = 0.20581666518655073.
        bound = false_auto_approve_upper_bound(12, 0, method="beta_binomial")
        assert bound == pytest.approx(1 - 0.05 ** (1 / 13), abs=1e-12)
        assert bound == pytest.approx(0.20581666518655073, abs=1e-12)
        # 0/60 -> Beta(1, 61): 1 - 0.05^(1/61) = 0.04792395210660738.
        bound60 = false_auto_approve_upper_bound(60, 0, method="beta_binomial")
        assert bound60 == pytest.approx(1 - 0.05 ** (1 / 61), abs=1e-12)

    def test_matches_independent_binomial_tail_bisection(self) -> None:
        solve = _IndependentBetaQuantile.solve
        # 1/12 -> Beta(2, 12), independent reference 0.31633976476272974.
        bound_1_12 = false_auto_approve_upper_bound(12, 1, method="beta_binomial")
        assert bound_1_12 == pytest.approx(solve(0.95, 2, 12), abs=1e-12)
        assert bound_1_12 == pytest.approx(0.31633976476272974, abs=1e-10)
        # 3/60 -> Beta(4, 58), independent reference 0.12223140113067374.
        bound_3_60 = false_auto_approve_upper_bound(60, 3, method="beta_binomial")
        assert bound_3_60 == pytest.approx(solve(0.95, 4, 58), abs=1e-12)
        assert bound_3_60 == pytest.approx(0.12223140113067374, abs=1e-10)

    def test_more_conservative_than_wilson_on_pilot_samples(self) -> None:
        # With the uniform prior the Beta-binomial bound sits at or above
        # the Wilson bound for these reference cases (documented choice,
        # not a mathematical law).
        for trials, failures in [(12, 0), (12, 1), (60, 3)]:
            wilson = false_auto_approve_upper_bound(trials, failures, "wilson")
            beta = false_auto_approve_upper_bound(
                trials, failures, "beta_binomial"
            )
            assert beta > wilson

    def test_incomplete_beta_matches_closed_forms_and_symmetry(self) -> None:
        # I_x(1, b) = 1 - (1-x)^b exactly.
        assert regularized_incomplete_beta(0.3, 1.0, 7.0) == pytest.approx(
            1 - 0.7**7, abs=1e-12
        )
        # Symmetry: I_x(a, b) + I_(1-x)(b, a) = 1.
        assert regularized_incomplete_beta(0.37, 2.5, 4.5) + (
            regularized_incomplete_beta(0.63, 4.5, 2.5)
        ) == pytest.approx(1.0, abs=1e-12)
        # Beta quantile inverts its own CDF.
        assert beta_quantile(0.95, 1.0, 13.0) == pytest.approx(
            1 - 0.05 ** (1 / 13), abs=1e-12
        )


def test_upper_bound_input_validation_fails_closed() -> None:
    with pytest.raises(CalibrationStatsError, match="trials"):
        false_auto_approve_upper_bound(0, 0)
    with pytest.raises(CalibrationStatsError, match="failures"):
        false_auto_approve_upper_bound(12, 13)
    with pytest.raises(CalibrationStatsError, match="failures"):
        false_auto_approve_upper_bound(12, -1)
    with pytest.raises(CalibrationStatsError, match="method"):
        false_auto_approve_upper_bound(12, 0, method="jeffreys")
    with pytest.raises(CalibrationStatsError, match="confidence"):
        false_auto_approve_upper_bound(12, 0, confidence=1.0)


# ---------------------------------------------------------------------------
# Stratified report
# ---------------------------------------------------------------------------


def _diverse_batch() -> list[dict[str, str]]:
    """60 records: low/physics clean, low/chem one miss, high/risky."""
    records: list[dict[str, str]] = []
    records += [
        _record("auto_approve", "approve", "low", "physics") for _ in range(28)
    ]
    records += [_record("auto_escalate", "escalate", "low", "physics") for _ in range(2)]
    records += [
        _record("auto_approve", "approve", "low", "chemistry") for _ in range(14)
    ]
    records += [_record("auto_approve", "escalate", "low", "chemistry")]
    records += [_record("auto_escalate", "escalate", "high", "physics") for _ in range(10)]
    records += [_record("auto_escalate", "escalate", "high", "chemistry") for _ in range(5)]
    return records


def test_stratum_report_cuts_both_axes_and_cross_product() -> None:
    report = stratum_report(_diverse_batch(), min_stratum_n=10)
    assert report.total_sample_size == 60
    assert report.overall.sample_size == 60
    axes = {stratum.axis for stratum in report.strata}
    assert axes == {"risk_class", "domain", "risk_class x domain"}
    risk_values = {s.value for s in report.strata_by_axis("risk_class")}
    assert risk_values == {"low", "high"}
    domain_values = {s.value for s in report.strata_by_axis("domain")}
    assert domain_values == {"physics", "chemistry"}
    cross_values = {s.value for s in report.cross_strata}
    assert cross_values == {
        "low x physics",
        "low x chemistry",
        "high x physics",
        "high x chemistry",
    }
    low_physics = next(
        s
        for s in report.cross_strata
        if s.value == "low x physics"
    )
    assert low_physics.sample_size == 30
    assert low_physics.coverage == "sufficient"
    # 30 items, all auto-approved correctly (28) or correctly escalated
    # (2): zero false auto approves, so the one-sided Wilson upper bound
    # is the zero-failure closed form z^2/(n + z^2) with n=28 trials.
    assert low_physics.upper_bound == pytest.approx(
        Z95_ONE_SIDED**2 / (28 + Z95_ONE_SIDED**2)
    )
    assert low_physics.kappa is not None and low_physics.kappa.defined


def test_stratum_report_marks_underpowered_strata_insufficient() -> None:
    # n=12 pilot: with the default minimum of 30 every stratum is
    # insufficient and no bound is reported (fail open, no crash).
    report = stratum_report(_batch_12_with_one_failure())
    assert report.total_sample_size == 12
    assert report.overall.coverage == "insufficient"
    assert report.overall.upper_bound is None
    assert report.overall.matrix.false_auto_approve_count == 1
    assert report.overall.matrix.false_escalate_count == 0
    assert any(
        "below required minimum" in reason
        for reason in report.overall.insufficient_reasons
    )
    for stratum in report.strata:
        assert stratum.coverage == "insufficient"
        assert stratum.upper_bound is None


def test_stratum_report_sufficient_small_batch_reports_bound() -> None:
    # Same n=12 batch with min_stratum_n=1: bound must be computable and
    # match the direct Wilson call (11 auto-approved trials, 1 failure).
    report = stratum_report(_batch_12_with_one_failure(), min_stratum_n=1)
    overall = report.overall
    assert overall.coverage == "sufficient"
    assert overall.upper_bound == pytest.approx(
        false_auto_approve_upper_bound(12, 1, method="wilson")
    )
    assert overall.kappa is not None and overall.kappa.defined


def test_stratum_report_rejects_invalid_options() -> None:
    with pytest.raises(CalibrationStatsError, match="method"):
        stratum_report(_batch_12_with_one_failure(), method="clopper")
    with pytest.raises(CalibrationStatsError, match="confidence"):
        stratum_report(_batch_12_with_one_failure(), confidence=0.0)
    with pytest.raises(CalibrationStatsError, match="min_stratum_n"):
        stratum_report(_batch_12_with_one_failure(), min_stratum_n=0)


# ---------------------------------------------------------------------------
# Activation gate assessment
# ---------------------------------------------------------------------------


def _passing_policy() -> dict[str, object]:
    return {
        "maxFalseAutoApproveUpperBound": 0.10,
        "minKappa": 0.6,
        "minStratumN": 10,
        "approvableRiskClasses": ["low"],
    }


def test_assessment_approves_only_covered_low_risk_strata() -> None:
    report = stratum_report(_diverse_batch(), min_stratum_n=10)
    assessment = activation_gate_assessment(report, _passing_policy())
    # low x physics is clean and covered; low x chemistry has a false auto
    # approve (1/15 -> Wilson upper ~0.30) so it must stay blocked.
    assert "low x physics" in assessment.approvable_strata
    assert "low x chemistry" not in assessment.approvable_strata
    for verdict in assessment.verdicts:
        if verdict.value == "low x chemistry":
            assert not verdict.approvable
            assert any("upper bound" in reason for reason in verdict.reasons)
        if verdict.risk_class == "high":
            assert not verdict.approvable
            assert any("risk class" in reason for reason in verdict.reasons)
    assert assessment.approved
    assert assessment.not_permanent_delegation is True


def test_assessment_always_marks_not_permanent_delegation() -> None:
    # Decision #13: even a spotless n=12 pilot is never a delegation proof.
    report = stratum_report(_batch_12_with_one_failure(), min_stratum_n=1)
    assessment = activation_gate_assessment(report, _passing_policy())
    assert assessment.not_permanent_delegation is True
    assert assessment.pilot_sample_size == 12
    assert any("permanent delegation" in note for note in assessment.notes)
    assert any("<= 12" in note for note in assessment.notes)


def test_assessment_empty_or_blocked_report_approves_nothing() -> None:
    report = stratum_report([])
    assessment = activation_gate_assessment(report, _passing_policy())
    assert not assessment.approved
    assert assessment.approvable_strata == ()
    assert assessment.not_permanent_delegation is True

    clean_high = [
        _record("auto_approve", "approve", "high", "physics") for _ in range(40)
    ]
    report_high = stratum_report(clean_high, min_stratum_n=10)
    assessment_high = activation_gate_assessment(report_high, _passing_policy())
    assert not assessment_high.approved


def test_assessment_never_uses_aggregate_overall_for_approval() -> None:
    # strataApprovalRule: the overall aggregate is evidence only and must
    # never appear as an approvable unit.
    report = stratum_report(_diverse_batch(), min_stratum_n=10)
    assessment = activation_gate_assessment(report, _passing_policy())
    flat_values = {verdict.value for verdict in assessment.verdicts}
    assert "overall" not in flat_values
    assert all(verdict.axis == "risk_class x domain" for verdict in assessment.verdicts)


def test_assessment_reads_snake_case_policy_keys() -> None:
    report = stratum_report(_diverse_batch(), min_stratum_n=10)
    snake_policy = {
        "max_false_auto_approve_upper_bound": 0.10,
        "min_kappa": 0.6,
        "min_stratum_n": 10,
        "approvable_risk_classes": ["low_risk"],
    }
    assessment = activation_gate_assessment(report, snake_policy)
    assert "low x physics" in assessment.approvable_strata


def test_assessment_defaults_without_policy_keys() -> None:
    report = stratum_report(_diverse_batch(), min_stratum_n=10)
    assessment = activation_gate_assessment(
        report, {"maxFalseAutoApproveUpperBound": 0.10}
    )
    assert "low x physics" in assessment.approvable_strata
    assert assessment.not_permanent_delegation is True


def test_as_dict_round_trip_fields() -> None:
    report = stratum_report(_diverse_batch(), min_stratum_n=10)
    payload = report.as_dict()
    assert payload["totalSampleSize"] == 60
    assert payload["stratifiedBy"] == ["risk_class", "domain"]
    assert payload["overall"]["confusionMatrix"]["falseAutoApproveCount"] == 1
    assessment = activation_gate_assessment(report, _passing_policy()).as_dict()
    assert assessment["notAPermanentDelegation"] is True
    assert assessment["approvableStrata"] == ["low x physics"]
