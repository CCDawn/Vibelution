import importlib.util
import json
from pathlib import Path


_MODULE_PATH = Path(__file__).parents[1] / "core" / "web" / "services" / "team_workflow" / "challenge_program.py"
_SPEC = importlib.util.spec_from_file_location("challenge_program_projection_contract", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
build_challenge_program_projection = _MODULE.build_challenge_program_projection
_COMPATIBILITY_CASE_REGISTRY = json.loads(
    (Path(__file__).parents[1] / "挑战杯" / "data" / "representative_deep_cases.json").read_text(encoding="utf-8")
)


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
    assert stage1["blockers"] == [
        "mvp_golden_sample_not_approved",
        "mvp_three_trial_questions_missing",
    ]
    assert stage1["status"] == "blocked"


def test_valid_but_unapproved_candidate_does_not_complete_golden_sample():
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
                "status": "registered",
            }
        ],
        question_run_summary={
            "validCandidateCount": 1,
            "validatedQuestionCount": 1,
            "validatedQuestionIds": ["SCI-096"],
            "completedCount": 0,
            "completedQuestionIds": [],
            "latestCandidate": {"questionId": "SCI-096", "status": "review_required"},
        },
    )

    stage1 = projection["stage1ComplianceReadiness"]
    assert stage1["blockers"] == [
        "mvp_golden_sample_not_approved",
        "mvp_three_trial_questions_missing",
    ]
    assert stage1["singleQuestionSample"]["candidateCount"] == 1
    assert stage1["singleQuestionSample"]["completed"] == 0
    assert stage1["singleQuestionSample"]["latestCandidate"]["questionId"] == "SCI-096"


def test_machine_validated_trials_keep_mvp_blocked_when_human_review_requests_revision():
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
                "status": "registered",
            }
        ],
        question_run_summary={
            "validCandidateCount": 4,
            "validatedQuestionCount": 4,
            "validatedQuestionIds": ["SCI-031", "SCI-096", "SCI-097", "SCI-118"],
            "validatedOutcomeCounts": {"approved": 1, "needs_revision": 3},
            "validatedQuestionResults": [
                {
                    "questionId": "SCI-096",
                    "runId": "stage1-sci-096-v3",
                    "status": "approved",
                    "validation": {
                        "schemaValidation": "passed",
                        "citationValidation": "passed",
                        "semantic": {
                            "allSevenDimensionsReviewed": True,
                            "researchPlanPresent": True,
                            "feedbackRevisionCount": 1,
                        },
                    },
                    "humanGates": {"allApproved": True},
                },
                *[
                    {
                        "questionId": question_id,
                        "runId": f"mvp-test-{question_id.lower()}-v1",
                        "status": "needs_revision",
                        "validation": {
                            "schemaValidation": "passed",
                            "citationValidation": "passed",
                            "semantic": {
                                "allSevenDimensionsReviewed": True,
                                "researchPlanPresent": True,
                                "feedbackRevisionCount": 1,
                            },
                        },
                        "humanGates": {"allApproved": False},
                    }
                    for question_id in ("SCI-031", "SCI-097", "SCI-118")
                ],
            ],
            "completedCount": 1,
            "completedQuestionIds": ["SCI-096"],
            "latestCandidate": {
                "questionId": "SCI-118",
                "status": "approved",
                "validation": {
                    "schemaValidation": "passed",
                    "citationValidation": "passed",
                    "semantic": {
                        "allSevenDimensionsReviewed": True,
                        "researchPlanPresent": True,
                        "feedbackRevisionCount": 1,
                    },
                },
                "humanGates": {"allApproved": True},
            },
        },
    )

    stage1 = projection["stage1ComplianceReadiness"]
    assert projection["program"]["deliveryMode"] == "mvp"
    assert projection["program"]["immediateQuestionCount"] == 4
    assert stage1["status"] == "blocked"
    assert stage1["blockers"] == ["mvp_human_review_revision_required"]
    assert stage1["singleQuestionSample"]["completed"] == 1
    assert stage1["acceptance"]["allFourHumanGatesApproved"] is False
    assert stage1["humanReview"] == {
        "requiredQuestionCount": 4,
        "approvedQuestionCount": 1,
        "approvedQuestionIds": ["SCI-096"],
        "pendingQuestionIds": [],
        "revisionRequiredQuestionIds": ["SCI-031", "SCI-097", "SCI-118"],
        "rejectedQuestionIds": [],
        "allQuestionsApproved": False,
    }
    assert stage1["trialRun"] == {
        "required": 3,
        "completed": 3,
        "realCallsRequired": True,
        "completedQuestionIds": ["SCI-031", "SCI-097", "SCI-118"],
        "outcomeCounts": {"approved": 1, "needs_revision": 3},
    }
    assert stage1["mvpManifest"] == {
        "requiredQuestionCount": 4,
        "completedQuestionCount": 4,
        "goldenSampleQuestionId": "SCI-096",
        "trialQuestionIds": ["SCI-031", "SCI-097", "SCI-118"],
        "testQuestionIds": ["SCI-031", "SCI-097", "SCI-118"],
        "scaleUpDeferred": True,
    }
    assert projection["stage2BatchGovernance"]["completedQuestionCount"] == 0
    assert projection["stage2BatchGovernance"]["status"] == "blocked_by_stage1"
    assert projection["program"]["completed"] is False


def test_all_four_human_approved_questions_complete_mvp_readiness():
    question_ids = ["SCI-031", "SCI-096", "SCI-097", "SCI-118"]
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
                "status": "registered",
            }
        ],
        question_run_summary={
            "validatedQuestionIds": question_ids,
            "validatedOutcomeCounts": {"approved": 4},
            "validatedQuestionResults": [
                {
                    "questionId": question_id,
                    "status": "approved",
                    "validation": {
                        "schemaValidation": "passed",
                        "citationValidation": "passed",
                        "semantic": {
                            "allSevenDimensionsReviewed": True,
                            "researchPlanPresent": True,
                            "feedbackRevisionCount": 1,
                        },
                    },
                    "humanGates": {"allApproved": True},
                }
                for question_id in question_ids
            ],
            "completedQuestionIds": question_ids,
        },
    )

    stage1 = projection["stage1ComplianceReadiness"]
    assert stage1["status"] == "completed"
    assert stage1["blockers"] == []
    assert stage1["acceptance"]["allFourHumanGatesApproved"] is True
    assert stage1["humanReview"]["approvedQuestionCount"] == 4
    assert stage1["humanReview"]["approvedQuestionIds"] == [
        "SCI-096",
        "SCI-031",
        "SCI-097",
        "SCI-118",
    ]
    assert stage1["humanReview"]["allQuestionsApproved"] is True
    assert projection["stage2BatchGovernance"]["status"] == "deferred_after_mvp"


def test_program_projection_reports_no_deep_case_when_legacy_iteration_never_started():
    projection = build_challenge_program_projection(
        legacy_lifecycle={"stage2": {"status": "draft"}, "stage3": {"status": "not_started"}},
        public_config={"llm": {"providers": {}}},
        official_model_evidence=[],
    )

    assert projection["stage3DeepResearchDelivery"]["status"] == "not_started"
    assert projection["stage3DeepResearchDelivery"]["caseRecords"] == []


def test_program_projection_recovers_documented_case_when_operator_history_is_missing():
    projection = build_challenge_program_projection(
        legacy_lifecycle={"stage2": {"status": "not_started"}, "stage3": {"status": "not_started"}},
        public_config={"llm": {"providers": {}}},
        official_model_evidence=[],
        compatibility_case_registry=_COMPATIBILITY_CASE_REGISTRY,
    )

    stage3 = projection["stage3DeepResearchDelivery"]
    assert stage3["status"] == "partial"
    assert stage3["representativeCaseCount"] == 1
    assert stage3["caseRecords"][0]["internalStatus"] == "accepted_for_writeup"
    assert stage3["caseRecords"][0]["evidenceStatus"] == "documented_program_fact"
    assert stage3["caseRecords"][0]["evidenceRefs"] == [
        "挑战杯/README.md#5-当前真实进展",
        ".docs/project-memory/lanes/challenge-cup-research-flow.json",
    ]
    assert projection["compatibility"]["caseRecoverySource"] == "tracked_program_case_registry"
    assert stage3["projectCompleted"] is False


def test_live_legacy_case_takes_precedence_over_documented_compatibility_registry():
    projection = build_challenge_program_projection(
        legacy_lifecycle=_legacy_accepted_case(),
        public_config={"llm": {"providers": {}}},
        official_model_evidence=[],
        compatibility_case_registry={
            "schemaVersion": 1,
            "registryKind": "challenge_program_representative_cases",
            "cases": [
                {
                    "caseId": "fashion_mnist_predictive_coding",
                    "title": "Documented fallback",
                    "internalStatus": "accepted_for_writeup",
                    "projectCompletionStatus": "case_only",
                    "evidenceStatus": "documented_program_fact",
                    "evidenceRefs": ["挑战杯/README.md#5-当前真实进展"],
                    "claimBoundary": "fallback",
                }
            ],
        },
    )

    case = projection["stage3DeepResearchDelivery"]["caseRecords"][0]
    assert case["title"] == "FashionMNIST 预测编码工程案例"
    assert case.get("evidenceStatus") != "documented_program_fact"
    assert projection["compatibility"]["caseRecoverySource"] == "legacy_lifecycle"
