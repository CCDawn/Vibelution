import importlib.util
from pathlib import Path


_MODULE_PATH = Path(__file__).parents[1] / "core" / "web" / "services" / "team_workflow" / "challenge_program.py"
_SPEC = importlib.util.spec_from_file_location("challenge_program_projection_contract", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
build_challenge_program_projection = _MODULE.build_challenge_program_projection


def _legacy_accepted_case() -> dict:
    return {
        "stage2": {
            "status": "frozen",
            "activeDesignPlanId": "exp_revision13",
            "frozenDesignRevision": 13,
        },
        "stage3": {
            "status": "accepted_for_writeup",
            "activeIterationId": "loop_fashion_mnist",
            "bestCandidateId": "candidate_revision4",
            "bestValidatedResultId": "benchmark_revision4",
            "bestValidatedPlanId": "exp_revision4",
        },
    }


def test_program_projection_does_not_promote_accepted_legacy_case_to_program_completion():
    projection = build_challenge_program_projection(
        legacy_lifecycle=_legacy_accepted_case(),
        public_config={"llm": {"providers": {}}},
        official_model_evidence=[],
    )

    assert projection["program"]["officialQuestionCount"] == 125
    assert projection["stage1ComplianceReadiness"]["status"] == "blocked"
    assert "dashscope_qwen_provider_missing" in projection["stage1ComplianceReadiness"]["blockers"]
    stage2 = projection["stage2BatchGovernance"]
    assert stage2["status"] == "blocked_by_stage1"
    assert stage2["questionCount"] == 125
    assert stage2["completedQuestionCount"] == 0
    assert stage2["batchSize"] == 5
    assert stage2["batchCount"] == 25
    assert stage2["completedBatchCount"] == 0
    assert stage2["failedOrBlockedCountedAsComplete"] is False
    assert stage2["aggregateScoreAllowed"] is False
    stage3 = projection["stage3DeepResearchDelivery"]
    assert stage3["status"] == "partial"
    assert stage3["representativeCaseCount"] == 1
    assert stage3["requiredRepresentativeCaseCount"] == 3
    assert stage3["projectCompleted"] is False
    assert stage3["caseRecords"][0]["internalStatus"] == "accepted_for_writeup"
    assert stage3["caseRecords"][0]["projectCompletionStatus"] == "case_only"
    assert projection["compatibility"]["acceptedForWriteupMeansProgramComplete"] is False
    assert projection["compatibility"]["historyRewritten"] is False


def test_configured_dashscope_and_real_call_evidence_only_clear_their_own_blockers():
    projection = build_challenge_program_projection(
        legacy_lifecycle={"stage2": {}, "stage3": {}},
        public_config={
            "llm": {
                "providers": {
                    "dashscope_main": {
                        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                        "credential_ref": "env:DASHSCOPE_API_KEY",
                        "models": {"qwen3.6-plus": {"upstream_id": "qwen3.6-plus"}},
                    }
                }
            }
        },
        official_model_evidence=[
            {
                "evidenceId": "model-evidence-real-1",
                "modelProvider": "dashscope",
                "modelId": "qwen3.6-plus",
                "evidenceKind": "invocation_log",
                "status": "recorded",
            }
        ],
    )

    stage1 = projection["stage1ComplianceReadiness"]
    assert stage1["dashscopeQwenProvider"]["configured"] is True
    assert stage1["officialModelCallEvidence"]["count"] == 1
    assert "dashscope_qwen_provider_missing" not in stage1["blockers"]
    assert "dashscope_qwen_call_evidence_missing" not in stage1["blockers"]
    assert stage1["blockers"] == ["real_single_question_sample_missing", "five_question_trial_missing"]
    assert stage1["status"] == "blocked"


def test_program_projection_reports_no_deep_case_when_legacy_iteration_never_started():
    projection = build_challenge_program_projection(
        legacy_lifecycle={"stage2": {"status": "draft"}, "stage3": {"status": "not_started"}},
        public_config={"llm": {"providers": {}}},
        official_model_evidence=[],
    )

    assert projection["stage3DeepResearchDelivery"]["status"] == "not_started"
    assert projection["stage3DeepResearchDelivery"]["caseRecords"] == []
