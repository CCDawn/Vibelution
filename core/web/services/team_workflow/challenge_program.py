"""Challenge Cup program-level projections.

``build_challenge_program_projection`` is the readonly legacy compatibility
projection over the append-only experiment lifecycle.  It must never be
promoted to completion of the whole 125-question competition program.

``build_competition_program_projection`` is the active typed v2 projection
driven by the tracked Program 2.2.0 and FullCatalogPolicy 1.2.0 resources.
Only schemaVersion=2 approved and submission-eligible question results count
toward the formal 125-question completion contract.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from core.research.competition.resources import (
    CATALOG_ID,
    CATALOG_QUESTION_COUNT,
    CATALOG_SHA256,
    CORE_BEHAVIOR_HASH,
    CORE_POLICY_HASH,
    CompetitionResourceError,
    load_competition_program_core,
    load_full_catalog_execution_core,
    load_science_question_catalog,
    validate_competition_program_core,
    validate_full_catalog_execution_core,
    validate_question_catalog,
)


PROGRAM_TITLE = "面向前沿科学问题的AI假设生成与研究计划设计平台"
OFFICIAL_PROBLEM_ID = "XH-202619"
OFFICIAL_QUESTION_COUNT = 125
BATCH_SIZE = 5
MVP_GOLDEN_SAMPLE_COUNT = 1
MVP_GOLDEN_SAMPLE_QUESTION_ID = "SCI-096"
MVP_TRIAL_QUESTION_COUNT = 3
MVP_TOTAL_QUESTION_COUNT = MVP_GOLDEN_SAMPLE_COUNT + MVP_TRIAL_QUESTION_COUNT
REQUIRED_REPRESENTATIVE_CASES = 3
COMPATIBILITY_CASE_REGISTRY_KIND = "challenge_program_representative_cases"
DOCUMENTED_CASE_STATUSES = {"accepted_for_writeup", "validated", "promoted"}
SUBMISSION_READINESS_SCHEMA_VERSION = 1

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
    mvp_trial_question_ids = [
        question_id
        for question_id in validated_question_ids
        if question_id != MVP_GOLDEN_SAMPLE_QUESTION_ID
    ][:MVP_TRIAL_QUESTION_COUNT]
    mvp_question_ids = [MVP_GOLDEN_SAMPLE_QUESTION_ID, *mvp_trial_question_ids]
    validated_result_by_question_id = {
        str(item.get("questionId") or ""): item
        for item in validated_question_results
        if str(item.get("questionId") or "")
    }
    human_review_approved_question_ids = [
        question_id for question_id in mvp_question_ids if question_id in completed_question_ids
    ]
    human_review_pending_question_ids: list[str] = []
    human_review_revision_required_question_ids: list[str] = []
    human_review_rejected_question_ids: list[str] = []
    for question_id in mvp_question_ids:
        if question_id in human_review_approved_question_ids:
            continue
        review_status = str((validated_result_by_question_id.get(question_id) or {}).get("status") or "")
        if review_status == "needs_revision":
            human_review_revision_required_question_ids.append(question_id)
        elif review_status == "rejected":
            human_review_rejected_question_ids.append(question_id)
        else:
            human_review_pending_question_ids.append(question_id)
    all_mvp_questions_human_approved = (
        len(human_review_approved_question_ids) == MVP_TOTAL_QUESTION_COUNT
    )
    golden_sample_candidate_count = int(MVP_GOLDEN_SAMPLE_QUESTION_ID in validated_question_ids)
    mvp_trial_completed = len(mvp_trial_question_ids)
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
    stage1_blockers: list[str] = []
    if not provider["configured"]:
        stage1_blockers.append("dashscope_qwen_provider_missing")
    if call_evidence["count"] == 0:
        stage1_blockers.append("dashscope_qwen_call_evidence_missing")
    if golden_sample_completed < MVP_GOLDEN_SAMPLE_COUNT:
        stage1_blockers.append("mvp_golden_sample_not_approved")
    if mvp_trial_completed < MVP_TRIAL_QUESTION_COUNT:
        stage1_blockers.append("mvp_three_trial_questions_missing")
    if (
        golden_sample_candidate_count >= MVP_GOLDEN_SAMPLE_COUNT
        and mvp_trial_completed >= MVP_TRIAL_QUESTION_COUNT
        and not all_mvp_questions_human_approved
    ):
        if human_review_revision_required_question_ids or human_review_rejected_question_ids:
            stage1_blockers.append("mvp_human_review_revision_required")
        else:
            stage1_blockers.append("mvp_human_review_incomplete")

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
            "completionDefinition": "one_golden_sample_and_three_trial_questions_pass_mvp_gates",
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
                "required": MVP_TRIAL_QUESTION_COUNT,
                "completed": mvp_trial_completed,
                "realCallsRequired": True,
                "completedQuestionIds": mvp_trial_question_ids,
                "outcomeCounts": dict(run_summary.get("validatedOutcomeCounts") or {}),
            },
            "mvpManifest": {
                "requiredQuestionCount": MVP_TOTAL_QUESTION_COUNT,
                "completedQuestionCount": golden_sample_completed + mvp_trial_completed,
                "goldenSampleQuestionId": MVP_GOLDEN_SAMPLE_QUESTION_ID,
                "trialQuestionIds": mvp_trial_question_ids,
                # Compatibility alias for clients shipped before the MVP vocabulary was finalized.
                "testQuestionIds": mvp_trial_question_ids,
                "scaleUpDeferred": True,
            },
            "humanReview": {
                "requiredQuestionCount": MVP_TOTAL_QUESTION_COUNT,
                "approvedQuestionCount": len(human_review_approved_question_ids),
                "approvedQuestionIds": human_review_approved_question_ids,
                "pendingQuestionIds": human_review_pending_question_ids,
                "revisionRequiredQuestionIds": human_review_revision_required_question_ids,
                "rejectedQuestionIds": human_review_rejected_question_ids,
                "allQuestionsApproved": all_mvp_questions_human_approved,
            },
            "independentEvaluationDimensions": list(INDEPENDENT_EVALUATION_DIMENSIONS),
            "aggregateScoreAllowed": False,
            "humanGates": list(HUMAN_GATES),
            "acceptance": {
                "schemaValidation": latest_validation.get("schemaValidation") == "passed",
                "citationValidation": latest_validation.get("citationValidation") == "passed",
                "minimumHypothesisCount": 2,
                "allSevenDimensionsReviewed": latest_semantic.get("allSevenDimensionsReviewed") is True,
                "allFourHumanGatesApproved": all_mvp_questions_human_approved,
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


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def build_competition_program_projection(
    *,
    question_run_summary: dict[str, Any] | None = None,
    program_core: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the active typed v2 program projection from frozen tracked resources.

    Only schemaVersion=2, human-approved, submission-eligible question results
    contribute to the formal 125-question completion contract.  Legacy
    question/case counts never affect active completion.
    """
    try:
        program = (
            validate_competition_program_core(program_core)
            if isinstance(program_core, dict)
            else load_competition_program_core()
        )
        execution = (
            validate_full_catalog_execution_core(policy)
            if isinstance(policy, dict)
            else load_full_catalog_execution_core()
        )
        question_catalog = (
            validate_question_catalog(catalog)
            if isinstance(catalog, dict)
            else load_science_question_catalog()
        )
    except CompetitionResourceError as exc:
        raise CompetitionResourceError(f"Active competition projection requires frozen tracked resources: {exc}") from exc

    run_summary = question_run_summary if isinstance(question_run_summary, dict) else {}
    approved_question_ids = sorted(
        {
            str(question_id)
            for question_id in run_summary.get("completedQuestionIds") or []
            if str(question_id)
        }
    )
    approved_question_set = set(approved_question_ids)
    approved_deep_experiment_question_set = {
        str(question_id)
        for question_id in run_summary.get("approvedDeepExperimentQuestionIds") or []
        if str(question_id)
    }
    catalog_question_ids = {
        str(item.get("id") or "")
        for item in question_catalog.get("questions", [])
        if isinstance(item, dict)
    }
    full_result_set_complete = (
        len(approved_question_set) >= CATALOG_QUESTION_COUNT
        and len(catalog_question_ids) == CATALOG_QUESTION_COUNT
        and catalog_question_ids <= approved_question_set
    )
    program_program = _mapping(program.get("program"))
    dimensions = list(program_program.get("dimensions") or [])
    deep_experiments = [
        _mapping(item)
        for item in program.get("requiredDeepExperiments") or []
        if isinstance(item, dict)
    ]
    deep_experiment_records: list[dict[str, Any]] = []
    for experiment in deep_experiments:
        question_id = _text(experiment.get("questionId"))
        deep_experiment_records.append(
            {
                "experimentId": _text(experiment.get("experimentId")),
                "questionId": question_id,
                "name": _text(experiment.get("name")),
                "themeId": _text(experiment.get("themeId")),
                "campaignId": _text(experiment.get("campaignId")),
                "required": experiment.get("required") is True,
                "questionResultApproved": question_id in approved_question_set,
                "approved": (
                    question_id in approved_question_set
                    and question_id in approved_deep_experiment_question_set
                ),
            }
        )
    all_deep_experiments_approved = bool(deep_experiment_records) and all(
        item["required"] and item["approved"] for item in deep_experiment_records
    )
    completion_contract = _mapping(program.get("completionContract"))
    program_completed = full_result_set_complete and all_deep_experiments_approved
    approved_count = len(approved_question_set)
    submission_snapshot = _mapping(execution.get("directionSubmissionRequirementSnapshot"))
    return {
        "schemaVersion": 2,
        "contractVersion": _text(program.get("contractVersion")),
        "contractId": _text(program.get("contractId")),
        "status": _text(program.get("status")),
        "program": {
            "problemId": _text(program_program.get("problemId")),
            "title": _text(program_program.get("workingTitle")),
            "track": _text(program_program.get("track")),
            "direction": _text(program_program.get("direction")),
            "dimensions": list(dimensions),
            "directionMode": "a_plus_b",
            "foundationModelFamily": _text(program_program.get("foundationModelFamily")),
            "officialQuestionCount": CATALOG_QUESTION_COUNT,
            "catalogId": CATALOG_ID,
            "catalogSha256": CATALOG_SHA256,
            "questionSchemaVersion": 2,
            "completed": program_completed,
        },
        "directions": [
            {
                "directionId": direction_id,
                "name": _text(dimensions[index]) if index < len(dimensions) else "",
                "required": True,
                "role": role,
            }
            for index, (direction_id, role) in enumerate(
                (
                    ("A", "full_catalog_hypothesis_and_research_plan"),
                    ("B", "deep_experiment_planning_and_feedback"),
                )
            )
        ],
        "programContract": {
            "version": _text(program.get("contractVersion")),
            "coreBehaviorHash": CORE_BEHAVIOR_HASH,
        },
        "fullCatalogPolicy": {
            "version": _text(execution.get("version")),
            "corePolicyHash": CORE_POLICY_HASH,
        },
        "questionSchema": {
            "activeVersion": 2,
            "readOnlyVersions": [1],
            "migrationMode": "dual_version_reader_append_only_no_auto_promotion",
        },
        "fullCatalogResultSet": {
            "questionCount": CATALOG_QUESTION_COUNT,
            "requiredApprovedQuestionCount": CATALOG_QUESTION_COUNT,
            "approvedQuestionCount": approved_count,
            "approvedQuestionIds": approved_question_ids,
            "missingQuestionCount": max(0, CATALOG_QUESTION_COUNT - approved_count),
            "complete": full_result_set_complete,
        },
        "questionCatalog": {
            "catalogId": CATALOG_ID,
            "catalogSha256": CATALOG_SHA256,
            "questionCount": CATALOG_QUESTION_COUNT,
            "questions": [
                {
                    "questionId": _text(item.get("id")),
                    "domain": _text(item.get("domain")),
                    "questionEn": _text(item.get("question_en")),
                }
                for item in question_catalog.get("questions", [])
                if isinstance(item, dict)
            ],
        },
        "requiredDeepExperiments": deep_experiment_records,
        "allRequiredDeepExperimentsApproved": all_deep_experiments_approved,
        "independentThemeBoundaries": {
            "separateThemes": len({item["themeId"] for item in deep_experiment_records if item["themeId"]})
            == len([item for item in deep_experiment_records if item["themeId"]]),
            "separateCampaigns": len({item["campaignId"] for item in deep_experiment_records if item["campaignId"]})
            == len([item for item in deep_experiment_records if item["campaignId"]]),
            "crossExperimentScientificEvidenceReuse": "forbidden",
        },
        "completion": {
            "programRule": _text(completion_contract.get("programRule")),
            "fullCatalogResultSetRequired": completion_contract.get("fullCatalogResultSetRequired"),
            "allRequiredDeepExperimentsRequired": completion_contract.get("allRequiredDeepExperimentsRequired"),
            "projectCompletedDerivedOnly": completion_contract.get("projectCompletedDerivedOnly") is True,
            "legacyQuestionCountsAffectCompletion": False,
            "legacyRepresentativeCaseCountsAffectCompletion": False,
            "completed": program_completed,
        },
        "directionSubmissionRequirement": {
            "captured": submission_snapshot.get("captured") is True,
            "officialPageObservedState": _text(submission_snapshot.get("officialPageObservedState")),
            "blocksSubmissionReady": submission_snapshot.get("blocksSubmissionReady") is True,
        },
        "legacyProjection": {
            "mode": "read_only",
            "schemaVersion": 1,
            "affectsCompletion": False,
            "deprecated": True,
        },
        "isolationPolicy": {
            "separateThemeContracts": _mapping(program.get("isolationPolicy")).get("separateThemeContracts") is True,
            "separateCampaigns": _mapping(program.get("isolationPolicy")).get("separateCampaigns") is True,
            "separateTeams": _mapping(program.get("isolationPolicy")).get("separateTeams") is True,
        },
    }


def build_challenge_submission_readiness(
    *,
    team_id: str,
    competition_program_projection: dict[str, Any],
) -> dict[str, Any]:
    """Build the single user-facing Challenge Cup submission readiness view.

    The projection is deliberately conservative: only the canonical program
    result counts can make the two computational packages ready.  The PDF,
    video, API and source-code submission artifacts have no tracked canonical
    package receipt yet, so they stay blocked/optional instead of being
    inferred from repository paths or implementation routes.
    """
    projection = _mapping(competition_program_projection)
    program = _mapping(projection.get("program"))
    result_set = _mapping(projection.get("fullCatalogResultSet"))
    deep_experiments = [
        item for item in projection.get("requiredDeepExperiments") or []
        if isinstance(item, dict)
    ]
    approved_count = int(result_set.get("approvedQuestionCount") or 0)
    required_count = int(result_set.get("requiredApprovedQuestionCount") or CATALOG_QUESTION_COUNT)
    full_catalog_ready = result_set.get("complete") is True
    approved_question_ids = {
        _text(item)
        for item in result_set.get("approvedQuestionIds") or []
        if _text(item)
    }
    catalog_questions = _mapping(projection.get("questionCatalog")).get("questions") or []
    first_missing_question_id = next(
        (
            _text(item.get("questionId"))
            for item in catalog_questions
            if isinstance(item, dict)
            and _text(item.get("questionId"))
            and _text(item.get("questionId")) not in approved_question_ids
        ),
        "",
    )
    approved_deep_count = sum(1 for item in deep_experiments if item.get("approved") is True)
    required_deep_count = sum(1 for item in deep_experiments if item.get("required") is True)
    first_missing_deep_question_id = next(
        (
            _text(item.get("questionId"))
            for item in deep_experiments
            if item.get("required") is True and item.get("approved") is not True and _text(item.get("questionId"))
        ),
        "",
    )
    deep_ready = bool(deep_experiments) and all(
        item.get("required") is True and item.get("approved") is True
        for item in deep_experiments
    )
    direction_requirement = _mapping(projection.get("directionSubmissionRequirement"))
    artifacts = [
        {
            "key": "full_catalog_results",
            "label": "125 题结果包",
            "required": True,
            "status": "ready" if full_catalog_ready else "blocked",
            "detail": f"{approved_count}/{required_count} 题已通过提交门。",
            "blocker": "full_catalog_results_incomplete" if not full_catalog_ready else "",
            "primaryAction": {
                "kind": "repair" if not full_catalog_ready else "export",
                "target": "full-catalog-results",
                "label": "修复缺失结果" if not full_catalog_ready else "导出结果包",
                **({"questionId": first_missing_question_id} if first_missing_question_id else {}),
            },
        },
        {
            "key": "deep_experiment_suite",
            "label": "两个深实验包",
            "required": True,
            "status": "ready" if deep_ready else "blocked",
            "detail": f"{approved_deep_count}/{required_deep_count or 2} 个独立深实验已通过提交门。",
            "blocker": "deep_experiment_suite_incomplete" if not deep_ready else "",
            "primaryAction": {
                "kind": "repair" if not deep_ready else "export",
                "target": "deep-experiment-suite",
                "label": "修复深实验" if not deep_ready else "导出深实验包",
                **({"questionId": first_missing_deep_question_id} if first_missing_deep_question_id else {}),
            },
        },
        {
            "key": "technical_proposal_pdf",
            "label": "20 页以内技术方案 PDF",
            "required": True,
            "status": "blocked",
            "detail": "尚无服务端确认的 PDF 提交包收据。",
            "blocker": "technical_proposal_pdf_not_packaged",
            "primaryAction": {
                "kind": "inspect",
                "target": "submission-package",
                "label": "检查交付材料",
            },
        },
        {
            "key": "demo_video",
            "label": "10 分钟以内演示视频",
            "required": False,
            "status": "optional",
            "detail": "可选附件尚无服务端确认收据。",
            "blocker": "",
            "primaryAction": {
                "kind": "inspect",
                "target": "submission-package",
                "label": "检查交付材料",
            },
        },
        {
            "key": "test_api",
            "label": "稳定测试 API",
            "required": True,
            "status": "blocked",
            "detail": "尚无可提交 API 入口与演练收据。",
            "blocker": "test_api_not_packaged",
            "primaryAction": {
                "kind": "inspect",
                "target": "submission-package",
                "label": "检查交付材料",
            },
        },
        {
            "key": "source_code",
            "label": "源码与复现说明",
            "required": True,
            "status": "blocked",
            "detail": "尚无干净克隆复现与源码提交包收据。",
            "blocker": "source_code_not_packaged",
            "primaryAction": {
                "kind": "inspect",
                "target": "submission-package",
                "label": "检查交付材料",
            },
        },
    ]
    blockers = [
        {
            "code": artifact["blocker"],
            "label": artifact["label"],
            "action": artifact["primaryAction"],
        }
        for artifact in artifacts
        if artifact["required"] and artifact["status"] == "blocked"
    ]
    if direction_requirement.get("blocksSubmissionReady") is True:
        blockers.append(
            {
                "code": "submission_direction_requirements_not_captured",
                "label": "方向专属提交要求",
                "action": {
                    "kind": "repair",
                    "target": "submission-requirements",
                    "label": "重新核对提交要求",
                },
            }
        )
    required_artifacts = [artifact for artifact in artifacts if artifact["required"]]
    ready_count = sum(1 for artifact in required_artifacts if artifact["status"] == "ready")
    return {
        "schemaVersion": SUBMISSION_READINESS_SCHEMA_VERSION,
        "teamId": str(team_id),
        "status": "ready" if not blockers else "blocked",
        "readyCount": ready_count,
        "requiredCount": len(required_artifacts),
        "blockerCount": len(blockers),
        "artifacts": artifacts,
        "blockers": blockers,
        "programSummary": {
            "title": _text(program.get("title")),
            "questionCount": required_count,
            "approvedQuestionCount": approved_count,
            "deepExperimentCount": required_deep_count or 2,
            "approvedDeepExperimentCount": approved_deep_count,
        },
    }
