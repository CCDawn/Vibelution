"""Deterministic paired numerical evaluation; never substitutes a model score."""
from __future__ import annotations

import math
import random
import statistics

from core.research.workflow.contracts._canonical import sha256_hex

from .measurement import MeasurementProtocol, OperatorMeasurement


def workload_hash(protocol: MeasurementProtocol) -> str:
    return sha256_hex([case.model_dump(mode="json") for case in protocol.cases])


def evaluate_measurement(
    protocol: MeasurementProtocol, measurement: OperatorMeasurement, *,
    expected_environment_hash: str, expected_baseline_hash: str, expected_parent_hash: str,
) -> dict:
    """Compare against both fixed initial baseline and the round's fixed parent.

    Bootstrap paired log ratios within each shape, then weight shapes equally.
    These intervals describe measurement variability in this run; they do not
    establish reproducibility across devices, independent sessions or campaigns.
    """
    reasons = []
    for field, expected in (
        ("protocolHash", sha256_hex(protocol.model_dump(mode="json"))),
        ("workloadHash", workload_hash(protocol)),
        ("environmentHash", expected_environment_hash),
        ("baselineSourceHash", expected_baseline_hash),
        ("parentSourceHash", expected_parent_hash),
    ):
        if getattr(measurement, field) != expected:
            reasons.append(f"{field}_mismatch")
    if measurement.status != "succeeded":
        reasons.append(measurement.status)
    by_case = {case.caseId: case for case in measurement.cases}
    if set(by_case) != {case.caseId for case in protocol.cases}:
        reasons.append("workload_case_set_mismatch")
    for case in measurement.cases:
        if not case.correctnessPassed:
            reasons.append(f"correctness_failed:{case.caseId}")
        if len(case.timings) != protocol.pairs:
            reasons.append(f"incomplete_pairs:{case.caseId}")
    result = {
        "measurementId": measurement.measurementId,
        "measurementHash": sha256_hex(measurement.model_dump(mode="json")),
        "protocolHash": measurement.protocolHash, "split": protocol.split,
        "comparable": not reasons, "promote": False, "reasons": reasons,
        "gpuSeconds": measurement.gpuSeconds, "caseResults": [],
        "uncertaintyScope": "within_run_paired_samples",
    }
    if reasons:
        return result
    log_ratios = {"baseline": [], "parent": []}
    for spec in protocol.cases:
        case = by_case[spec.caseId]
        row = {"caseId": case.caseId, "candidateMedianMs": statistics.median(t.candidateMs for t in case.timings)}
        for comparator, grouped in log_ratios.items():
            logs = [math.log(getattr(t, comparator + "Ms") / t.candidateMs) for t in case.timings]
            grouped.append(logs)
            row[comparator + "Speedup"] = math.exp(statistics.mean(logs))
        result["caseResults"].append(row)
    rng = random.Random(protocol.bootstrapSeed)
    comparisons = {}
    for comparator, grouped in log_ratios.items():
        boot = sorted(math.exp(statistics.mean(
            statistics.mean(rng.choices(logs, k=len(logs))) for logs in grouped
        )) for _ in range(protocol.bootstrapSamples))
        comparisons[comparator] = {
            "geometricSpeedup": math.exp(statistics.mean(statistics.mean(logs) for logs in grouped)),
            "confidence95": [boot[int(len(boot) * .025)], boot[min(len(boot) - 1, int(len(boot) * .975))]],
        }
    result["comparisons"] = comparisons
    if comparisons["parent"]["confidence95"][0] < protocol.minSpeedup:
        reasons.append("improvement_not_established")
    if any(row["parentSpeedup"] < 1 / (1 + protocol.maxCaseRegression) for row in result["caseResults"]):
        reasons.append("shape_regression")
    # Holdout is a report-only terminal validation and cannot select a candidate.
    result["promote"] = not reasons and protocol.split == "tuning"
    return result
