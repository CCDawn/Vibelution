"""Challenge Cup program-level three-stage projection.

The experiment lifecycle remains an append-only compatibility source for one
representative deep-research case.  It must never be promoted to the completion
state of the whole 125-question competition program.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


PROGRAM_TITLE = "面向前沿科学问题的AI假设生成与研究计划设计平台"
OFFICIAL_PROBLEM_ID = "XH-202619"
OFFICIAL_QUESTION_COUNT = 125
BATCH_SIZE = 5
MVP_GOLDEN_SAMPLE_COUNT = 1
MVP_GOLDEN_SAMPLE_QUESTION_ID = "SCI-096"
MVP_TEST_QUESTION_COUNT = 3
MVP_TOTAL_QUESTION_COUNT = MVP_GOLDEN_SAMPLE_COUNT + MVP_TEST_QUESTION_COUNT
REQUIRED_REPRESENTATIVE_CASES = 3
COMPATIBILITY_CASE_REGISTRY_KIND = "challenge_program_representative_cases"
DOCUMENTED_CASE_STATUSES = {"accepted_for_writeup", "validated", "promoted"}

INDEPENDENT_EVALUATION_DIMENSIONS = [
    "evidence_support",
    "factual_accuracy",
    "novelty",
    "falsifiability",
    "plan_feasibility",
    "risk_and_ethics",
    "counterexample_coverage",
]

HUMAN_GATES = [
    "H1_problem_understanding",
    "H2_hypothesis_selection",
    "H3_research_plan",
    "H4_external_output",
]


def _credential_declared(provider: dict[str, Any]) -> bool:
    return any(
        bool(provider.get(field))
        for field in ("credential_ref", "credentialRef", "api_key", "apiKey", "api_key_env", "apiKeyEnv")
    )


def _dashscope_qwen_configuration(public_config: dict[str, Any]) -> dict[str, Any]:
    llm = public_config.get("llm") if isinstance(public_config.get("llm"), dict) else {}
    providers = llm.get("providers") if isinstance(llm.get("providers"), dict) else {}
    configured_models: list[str] = []
    configured_providers: list[str] = []
    for provider_id, raw_provider in providers.items():
        if not isinstance(raw_provider, dict):
            continue
        base_url = str(raw_provider.get("base_url") or raw_provider.get("baseUrl") or "")
        host = (urlparse(base_url).hostname or "").lower()
        provider_kind = str(raw_provider.get("kind") or raw_provider.get("provider_kind") or "").lower()
        is_dashscope = "dashscope.aliyuncs.com" in host or provider_kind in {"aliyun", "dashscope", "bailian"}
        if not is_dashscope or not _credential_declared(raw_provider):
            continue
        models = raw_provider.get("models") if isinstance(raw_provider.get("models"), dict) else {}
        qwen_models = [
            str(model_id)
            for model_id, model in models.items()
            if "qwen" in " ".join(
                [
                    str(model_id),
                    str((model or {}).get("model") if isinstance(model, dict) else ""),
                    str((model or {}).get("upstream_id") if isinstance(model, dict) else ""),
                ]
            ).lower()
        ]
        if not qwen_models:
            continue
        configured_providers.append(str(provider_id))
        configured_models.extend(f"{provider_id}/{model_id}" for model_id in qwen_models)
    return {
        "configured": bool(configured_models),
        "providerIds": configured_providers,
        "modelRefs": configured_models,
    }


def _official_dashscope_evidence(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    accepted: list[dict[str, Any]] = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        provider = str(item.get("modelProvider") or "").lower()
        if not any(token in provider for token in ("dashscope", "bailian", "aliyun", "百炼")):
            continue
        if str(item.get("status") or "").lower() == "derived_from_candidate_store":
            continue
        accepted.append(item)
    return {
        "count": len(accepted),
        "evidenceIds": [str(item.get("evidenceId") or "") for item in accepted if item.get("evidenceId")],
    }


def _legacy_case_records(legacy_lifecycle: dict[str, Any]) -> list[dict[str, Any]]:
    stage2 = legacy_lifecycle.get("stage2") if isinstance(legacy_lifecycle.get("stage2"), dict) else {}
    stage3 = legacy_lifecycle.get("stage3") if isinstance(legacy_lifecycle.get("stage3"), dict) else {}
    has_case = any(
        bool(stage3.get(field))
        for field in ("status", "activeIterationId", "bestCandidateId", "bestValidatedResultId", "bestValidatedPlanId")
    ) and str(stage3.get("status") or "") != "not_started"
    if not has_case:
        return []
    return [
        {
            "caseId": "fashion_mnist_predictive_coding",
            "title": "FashionMNIST 预测编码工程案例",
            "role": "representative_execution_and_revision_evidence",
            "internalStatus": str(stage3.get("status") or "not_started"),
            "projectCompletionStatus": "case_only",
            "legacyDesignPlanId": str(stage2.get("activeDesignPlanId") or ""),
            "legacyDesignRevision": int(stage2.get("frozenDesignRevision") or 0),
            "activeIterationId": str(stage3.get("activeIterationId") or ""),
            "bestCandidateId": str(stage3.get("bestCandidateId") or ""),
            "bestValidatedResultId": str(stage3.get("bestValidatedResultId") or ""),
            "bestValidatedPlanId": str(stage3.get("bestValidatedPlanId") or ""),
            "claimBoundary": "engineering evidence on FashionMNIST and declared mask conditions; not biological neural truth",
        }
    ]


def _documented_case_records(registry: dict[str, Any]) -> list[dict[str, Any]]:
    if (
        int(registry.get("schemaVersion") or 0) != 1
        or str(registry.get("registryKind") or "") != COMPATIBILITY_CASE_REGISTRY_KIND
    ):
        return []
    records: list[dict[str, Any]] = []
    for raw_case in registry.get("cases") if isinstance(registry.get("cases"), list) else []:
        if not isinstance(raw_case, dict):
            continue
        evidence_refs = [
            str(ref).strip()
            for ref in raw_case.get("evidenceRefs")
            if str(ref).strip()
        ] if isinstance(raw_case.get("evidenceRefs"), list) else []
        internal_status = str(raw_case.get("internalStatus") or "").strip()
        if (
            not str(raw_case.get("caseId") or "").strip()
            or not str(raw_case.get("title") or "").strip()
            or internal_status not in DOCUMENTED_CASE_STATUSES
            or str(raw_case.get("projectCompletionStatus") or "") != "case_only"
            or str(raw_case.get("evidenceStatus") or "") != "documented_program_fact"
            or not evidence_refs
            or not str(raw_case.get("claimBoundary") or "").strip()
        ):
            continue
        records.append(
            {
                "caseId": str(raw_case["caseId"]).strip(),
                "title": str(raw_case["title"]).strip(),
                "role": str(raw_case.get("role") or "representative_execution_and_revision_evidence"),
                "internalStatus": internal_status,
                "projectCompletionStatus": "case_only",
                "legacyDesignPlanId": str(raw_case.get("legacyDesignPlanId") or ""),
                "legacyDesignRevision": int(raw_case.get("legacyDesignRevision") or 0),
                "activeIterationId": str(raw_case.get("activeIterationId") or ""),
                "bestCandidateId": str(raw_case.get("bestCandidateId") or ""),
                "bestValidatedResultId": str(raw_case.get("bestValidatedResultId") or ""),
                "bestValidatedPlanId": str(raw_case.get("bestValidatedPlanId") or ""),
                "claimBoundary": str(raw_case["claimBoundary"]).strip(),
                "evidenceStatus": "documented_program_fact",
                "evidenceRefs": evidence_refs,
            }
        )
    return records


def build_challenge_program_projection(
    *,
    legacy_lifecycle: dict[str, Any],
    public_config: dict[str, Any],
    official_model_evidence: list[dict[str, Any]],
    compatibility_case_registry: dict[str, Any] | None = None,
    question_run_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a read-only program projection without rewriting legacy history."""

    provider = _dashscope_qwen_configuration(public_config)
    call_evidence = _official_dashscope_evidence(official_model_evidence)
    run_summary = question_run_summary if isinstance(question_run_summary, dict) else {}
    completed_question_ids = [
        str(question_id)
        for question_id in run_summary.get("completedQuestionIds") or []
        if str(question_id)
    ]
    validated_question_ids = [
        str(question_id)
        for question_id in run_summary.get("validatedQuestionIds") or []
        if str(question_id)
    ]
    validated_question_results = [
        item
        for item in run_summary.get("validatedQuestionResults") or []
        if isinstance(item, dict)
    ]
    golden_sample_completed = int(MVP_GOLDEN_SAMPLE_QUESTION_ID in completed_question_ids)
    mvp_test_question_ids = [
        question_id
        for question_id in validated_question_ids
        if question_id != MVP_GOLDEN_SAMPLE_QUESTION_ID
    ][:MVP_TEST_QUESTION_COUNT]
    golden_sample_candidate_count = int(MVP_GOLDEN_SAMPLE_QUESTION_ID in validated_question_ids)
    mvp_test_completed = len(mvp_test_question_ids)
    latest_candidate = run_summary.get("latestCandidate") if isinstance(run_summary.get("latestCandidate"), dict) else {}
    golden_sample_candidate = next(
        (
            item
            for item in validated_question_results
            if str(item.get("questionId") or "") == MVP_GOLDEN_SAMPLE_QUESTION_ID
        ),
        latest_candidate if str(latest_candidate.get("questionId") or "") == MVP_GOLDEN_SAMPLE_QUESTION_ID else {},
    )
    latest_validation = (
        golden_sample_candidate.get("validation")
        if isinstance(golden_sample_candidate.get("validation"), dict)
        else {}
    )
    latest_semantic = (
        latest_validation.get("semantic") if isinstance(latest_validation.get("semantic"), dict) else {}
    )
    latest_gates = (
        golden_sample_candidate.get("humanGates")
        if isinstance(golden_sample_candidate.get("humanGates"), dict)
        else {}
    )
    stage1_blockers: list[str] = []
    if not provider["configured"]:
        stage1_blockers.append("dashscope_qwen_provider_missing")
    if call_evidence["count"] == 0:
        stage1_blockers.append("dashscope_qwen_call_evidence_missing")
    if golden_sample_completed < MVP_GOLDEN_SAMPLE_COUNT:
        stage1_blockers.append("mvp_golden_sample_not_approved")
    if mvp_test_completed < MVP_TEST_QUESTION_COUNT:
        stage1_blockers.append("mvp_three_question_test_missing")

    case_records = _legacy_case_records(legacy_lifecycle)
    case_recovery_source = "legacy_lifecycle" if case_records else "none"
    if not case_records and isinstance(compatibility_case_registry, dict):
        case_records = _documented_case_records(compatibility_case_registry)
        if case_records:
            case_recovery_source = "tracked_program_case_registry"
    representative_case_count = len(case_records)
    stage3_status = "partial" if representative_case_count else "not_started"

    return {
        "schemaVersion": 1,
        "migrationMode": "program_projection_over_append_only_legacy_history",
        "program": {
            "title": PROGRAM_TITLE,
            "officialProblemId": OFFICIAL_PROBLEM_ID,
            "track": "赛道一 / 方向一 / A 科学假设生成与研究计划设计",
            "officialQuestionCount": OFFICIAL_QUESTION_COUNT,
            "deliveryMode": "mvp",
            "immediateQuestionCount": MVP_TOTAL_QUESTION_COUNT,
            "directionBRole": "representative_deep_validation_only",
            "completed": False,
        },
        "stage1ComplianceReadiness": {
            "status": "blocked" if stage1_blockers else "completed",
            "completionDefinition": "one_golden_sample_and_three_test_questions_pass_mvp_gates",
            "blockers": stage1_blockers,
            "dashscopeQwenProvider": provider,
            "officialModelCallEvidence": call_evidence,
            "singleQuestionSample": {
                "required": MVP_GOLDEN_SAMPLE_COUNT,
                "candidateCount": golden_sample_candidate_count,
                "completed": golden_sample_completed,
                "questionId": MVP_GOLDEN_SAMPLE_QUESTION_ID,
                "realCallsRequired": True,
                "latestCandidate": golden_sample_candidate or None,
            },
            "trialRun": {
                "required": MVP_TEST_QUESTION_COUNT,
                "completed": mvp_test_completed,
                "realCallsRequired": True,
                "completedQuestionIds": mvp_test_question_ids,
                "outcomeCounts": dict(run_summary.get("validatedOutcomeCounts") or {}),
            },
            "mvpManifest": {
                "requiredQuestionCount": MVP_TOTAL_QUESTION_COUNT,
                "completedQuestionCount": golden_sample_completed + mvp_test_completed,
                "goldenSampleQuestionId": MVP_GOLDEN_SAMPLE_QUESTION_ID,
                "testQuestionIds": mvp_test_question_ids,
                "scaleUpDeferred": True,
            },
            "independentEvaluationDimensions": list(INDEPENDENT_EVALUATION_DIMENSIONS),
            "aggregateScoreAllowed": False,
            "humanGates": list(HUMAN_GATES),
            "acceptance": {
                "schemaValidation": latest_validation.get("schemaValidation") == "passed",
                "citationValidation": latest_validation.get("citationValidation") == "passed",
                "minimumHypothesisCount": 2,
                "allSevenDimensionsReviewed": latest_semantic.get("allSevenDimensionsReviewed") is True,
                "allFourHumanGatesApproved": latest_gates.get("allApproved") is True,
                "researchPlanPresent": latest_semantic.get("researchPlanPresent") is True,
                "feedbackRevisionCount": int(latest_semantic.get("feedbackRevisionCount") or 0),
            },
        },
        "stage2BatchGovernance": {
            "status": "blocked_by_stage1" if stage1_blockers else "deferred_after_mvp",
            "completionDefinition": "all_125_questions_schema_valid_traceable_and_audited",
            "questionCount": OFFICIAL_QUESTION_COUNT,
            "completedQuestionCount": 0,
            "batchSize": BATCH_SIZE,
            "batchCount": OFFICIAL_QUESTION_COUNT // BATCH_SIZE,
            "completedBatchCount": 0,
            "failedOrBlockedCountedAsComplete": False,
            "aggregateScoreAllowed": False,
            "pipeline": [
                "problem_understanding",
                "evidence_retrieval",
                "multiple_hypothesis_generation",
                "seven_dimension_review",
                "human_selection",
                "research_plan",
                "feedback_revision",
            ],
            "ledger": {"initialized": False, "manifestHashVerified": False, "citationAuditComplete": False},
        },
        "stage3DeepResearchDelivery": {
            "status": stage3_status,
            "completionDefinition": "three_cross_disciplinary_cases_and_competition_delivery_package_complete",
            "representativeCaseCount": representative_case_count,
            "requiredRepresentativeCaseCount": REQUIRED_REPRESENTATIVE_CASES,
            "caseRecords": case_records,
            "delivery": {
                "causalRevisionTraceCount": representative_case_count,
                "requiredCausalRevisionTraceCount": REQUIRED_REPRESENTATIVE_CASES,
                "queryApiReady": False,
                "interactiveFrontendReady": False,
                "pdfWithinTwentyPagesReady": False,
                "all125ResultsPackageReady": False,
                "citationAndReproductionPackageReady": False,
                "dashscopeCallProofReady": call_evidence["count"] > 0,
            },
            "projectCompleted": False,
        },
        "compatibility": {
            "legacyLifecycleProjectionPreserved": True,
            "legacyStage2DesignStatus": str((legacy_lifecycle.get("stage2") or {}).get("status") or "not_started"),
            "legacyStage3CaseStatus": str((legacy_lifecycle.get("stage3") or {}).get("status") or "not_started"),
            "acceptedForWriteupMeansProgramComplete": False,
            "appendOnlyEvidencePreserved": True,
            "historyRewritten": False,
            "caseRecoverySource": case_recovery_source,
        },
    }
