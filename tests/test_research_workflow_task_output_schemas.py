from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from core.research.workflow.contracts import (
    RESEARCH_TASK_OUTPUT_SCHEMA_SHA256,
    RESEARCH_TASK_OUTPUT_SCHEMA_VERSION,
    HypothesisDesignOutput,
    ProtocolReviewOutput,
    ResultEvaluationOutput,
    canonical_research_task_output_schema_bundle,
    parse_research_task_output,
    research_task_output_schema_sha256,
)


def _common(task_kind: str, *, status: str = "completed") -> dict:
    return {
        "schemaVersion": RESEARCH_TASK_OUTPUT_SCHEMA_VERSION,
        "taskKind": task_kind,
        "status": status,
        "reasoning": "先核对冻结输入、反证和边界，再形成结构化结论。",
        "evidenceRefs": ["evidence://primary-a"],
    }


def test_task_output_schema_bundle_is_strict_and_hash_bound() -> None:
    bundle = canonical_research_task_output_schema_bundle()

    assert set(bundle["schemas"]) == {
        "hypothesis_design",
        "protocol_review",
        "result_evaluation",
    }
    for schema in bundle["schemas"].values():
        assert schema["additionalProperties"] is False
        reasoning_schema = schema["properties"]["reasoning"]
        assert "maxLength" not in reasoning_schema
        assert "needs_more_evidence" in schema["properties"]["status"]["enum"]
    assert (
        research_task_output_schema_sha256(bundle) == RESEARCH_TASK_OUTPUT_SCHEMA_SHA256
    )

    changed = deepcopy(bundle)
    changed["schemas"]["hypothesis_design"]["title"] = "changed"
    assert (
        research_task_output_schema_sha256(changed)
        != RESEARCH_TASK_OUTPUT_SCHEMA_SHA256
    )


def test_hypothesis_design_output_requires_candidates_when_completed() -> None:
    payload = {
        **_common("hypothesis_design"),
        "maxEvolutionRounds": 3,
        "currentEvolutionRound": 1,
        "candidates": [],
    }

    with pytest.raises(ValidationError, match="completed hypothesis_design"):
        HypothesisDesignOutput.model_validate(payload)

    payload["status"] = "needs_more_evidence"
    parsed = HypothesisDesignOutput.model_validate(payload)
    assert parsed.candidates == []


def test_protocol_and_evaluation_outputs_are_exact_task_types() -> None:
    protocol = ProtocolReviewOutput.model_validate(
        {
            **_common("protocol_review"),
            "decision": "changes_requested",
            "blockingIssueCount": 1,
            "openWaivers": 0,
            "checks": {
                "dataset": "pass",
                "baseline": "pass",
                "metric": "pass",
                "seed": "pass",
                "budget": "pass",
                "stopCondition": "fail",
                "smokePlan": "pass",
            },
            "findings": [
                {
                    "code": "missing-stop-threshold",
                    "severity": "blocking",
                    "summary": "停止条件缺少阈值。",
                    "evidenceRefs": ["evidence://protocol-a"],
                }
            ],
        }
    )
    evaluation = ResultEvaluationOutput.model_validate(
        {
            **_common("result_evaluation"),
            "resultClassification": "executed_inconclusive",
            "dimensionScores": [
                {
                    "dimension": "evidence_support",
                    "score": 0.6,
                    "reasoning": "证据方向不一致。",
                    "evidenceRefs": ["evidence://run-a"],
                }
            ],
            "claimCoverage": 0.7,
            "evidenceCoverage": 0.8,
            "experimentCoverage": 0.6,
            "deliverableCoverage": 0.5,
            "blockingWarnings": [],
        }
    )

    assert protocol.taskKind == "protocol_review"
    assert evaluation.taskKind == "result_evaluation"
    with pytest.raises(ValidationError):
        ProtocolReviewOutput.model_validate({**protocol.model_dump(), "extra": True})
    with pytest.raises(ValueError, match="does not match"):
        parse_research_task_output("hypothesis_design", evaluation.model_dump())
