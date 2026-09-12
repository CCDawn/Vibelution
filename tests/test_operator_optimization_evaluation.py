import pytest
from pydantic import ValidationError

from core.research.operator_optimization.evaluation import evaluate_measurement, workload_hash
from core.research.operator_optimization.measurement import MeasurementProtocol, OperatorMeasurement
from core.research.workflow.contracts._canonical import sha256_hex


def observation(*, candidate_ms=0.8, split="tuning"):
    protocol = MeasurementProtocol(protocolId="p1", split=split, pairs=10, bootstrapSamples=1000,
        cases=[dict(caseId="shape1", rows=128, columns=512, dtype="float32", seed=0)])
    measurement = OperatorMeasurement(
        measurementId="m1", optimizationCampaignId="c1", runId="r1",
        protocolHash=sha256_hex(protocol.model_dump(mode="json")), workloadHash=workload_hash(protocol),
        environmentHash="a" * 64, baselineSourceHash="b" * 64, parentSourceHash="c" * 64,
        candidateSourceHash="d" * 64, deviceName="Test fixture GPU", status="succeeded", gpuSeconds=3,
        cases=[dict(caseId="shape1", correctnessPassed=True, maxAbsoluteError=0,
            timings=[dict(baselineMs=1.2, parentMs=1, candidateMs=candidate_ms)] * 10)],
    )
    return protocol, measurement


def evaluate(protocol, measurement):
    return evaluate_measurement(protocol, measurement, expected_environment_hash="a" * 64,
        expected_baseline_hash="b" * 64, expected_parent_hash="c" * 64)


def test_improvement_uses_raw_pairs_and_reports_both_comparisons():
    protocol, measurement = observation()
    result = evaluate(protocol, measurement)
    assert result["promote"]
    assert result["comparisons"]["parent"]["geometricSpeedup"] == pytest.approx(1.25)
    assert result["comparisons"]["baseline"]["geometricSpeedup"] == pytest.approx(1.5)
    assert result == evaluate(protocol, measurement)


@pytest.mark.parametrize("change,reason", [
    ({"environmentHash": "0" * 64}, "environmentHash_mismatch"),
    ({"status": "failed", "failureReason": "compiler failure"}, "failed"),
    ({"cases": ()}, "workload_case_set_mismatch"),
])
def test_incomparable_and_failed_trials_never_receive_performance_scores(change, reason):
    protocol, measurement = observation()
    result = evaluate(protocol, measurement.model_copy(update=change))
    assert not result["comparable"] and not result["promote"]
    assert reason in result["reasons"]
    assert "comparisons" not in result


def test_holdout_cannot_promote_and_regressions_are_retained():
    assert not evaluate(*observation(split="holdout"))["promote"]
    result = evaluate(*observation(candidate_ms=1.1))
    assert result["comparable"] and not result["promote"]
    assert "shape_regression" in result["reasons"]


def test_invalid_nonfinite_and_cpu_measurements_are_rejected():
    _, measurement = observation()
    for change in ({"gpuSeconds": float("nan")}, {"deviceKind": "cpu"}):
        with pytest.raises(ValidationError):
            OperatorMeasurement.model_validate({**measurement.model_dump(), **change})


def test_correctness_failure_prevents_promotion_even_when_fast():
    protocol, measurement = observation(candidate_ms=.1)
    case = measurement.cases[0].model_copy(update={"correctnessPassed": False})
    result = evaluate(protocol, measurement.model_copy(update={"cases": (case,)}))
    assert not result["promote"]
    assert "correctness_failed:shape1" in result["reasons"]
