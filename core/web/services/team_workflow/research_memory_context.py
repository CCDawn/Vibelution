"""Bounded, reference-first memory context for Challenge Cup research stages."""

from __future__ import annotations

import hashlib
import json
from typing import Any


NEGATIVE_PLAN_STATUSES = {
    "smoke_failed",
    "smoke_needs_review",
    "full_run_failed",
    "full_run_needs_review",
    "needs_review",
}
SUCCESS_PLAN_STATUSES = {"ingested", "knowledge_steward_notified"}
APPROVED_SOURCE_STATES = {"source_quality_approved", "source_manifest_ready", "official_synced"}
MAX_FORMAL_KNOWLEDGE = 6
MAX_REVIEWED_SOURCES = 8
MAX_ALLOWED_CLAIMS = 8
MAX_NEGATIVE_EXPERIMENTS = 8
MAX_SUCCESSFUL_RUNS = 8


def build_research_memory_context(
    *,
    stage_type: str,
    research_question: str,
    candidates: list[dict[str, Any]] | None = None,
    plans: list[dict[str, Any]] | None = None,
    loops: list[dict[str, Any]] | None = None,
    knowledge_results: list[dict[str, Any]] | None = None,
    retrieval_status: str = "completed",
) -> dict[str, Any]:
    candidate_rows = [item for item in list(candidates or []) if isinstance(item, dict)]
    plan_rows = [item for item in list(plans or []) if isinstance(item, dict)]
    loop_rows = [item for item in list(loops or []) if isinstance(item, dict)]
    knowledge_rows = [item for item in list(knowledge_results or []) if isinstance(item, dict)]
    best_plan = _best_validated_plan(plan_rows, loop_rows)
    negative_experiments = [_negative_experiment_pack(plan, plan_rows) for plan in plan_rows if _is_negative_plan(plan)]
    negative_experiments = negative_experiments[-MAX_NEGATIVE_EXPERIMENTS:]
    successful_candidate_ids = {
        candidate_id
        for plan in plan_rows
        if _is_successful_plan(plan)
        for candidate_id in _text_list(plan.get("hypothesisCandidateIds"), limit=16)
    }
    forbidden_duplicates = [
        {
            "planId": item["planId"],
            "experimentSignature": item["experimentSignature"],
            "candidateIds": [
                candidate_id
                for candidate_id in item["candidateIds"]
                if candidate_id not in successful_candidate_ids
            ],
            "reason": item["interpretation"],
            "defaultAction": "exclude_from_suggestions",
            "retestPolicy": item["retestPolicy"],
            "evidenceRefs": item["evidenceRefs"],
        }
        for item in negative_experiments
    ]
    forbidden_duplicates = [item for item in forbidden_duplicates if item["candidateIds"] or item["experimentSignature"]]
    formal_knowledge = [_formal_knowledge_ref(item) for item in knowledge_rows[:MAX_FORMAL_KNOWLEDGE]]
    reviewed_sources = [
        _reviewed_source_ref(item)
        for item in candidate_rows
        if str(item.get("candidateType") or "") == "source_manifest"
        and (
            str(item.get("currentState") or "") in APPROVED_SOURCE_STATES
            or str(item.get("qualityStatus") or "") in APPROVED_SOURCE_STATES
        )
    ][:MAX_REVIEWED_SOURCES]
    allowed_claims = _allowed_claims(formal_knowledge, candidate_rows)
    prior_successful_runs = _successful_runs(plan_rows, loop_rows)
    variables_allowed_to_change = _allowed_variable_changes(best_plan)
    missing_evidence: list[str] = []
    if not formal_knowledge:
        missing_evidence.append("formal_knowledge")
    if not reviewed_sources:
        missing_evidence.append("reviewed_source_evidence")
    if not variables_allowed_to_change:
        missing_evidence.append("explicit_allowed_variable_changes")
    best_candidate_ids = _text_list((best_plan or {}).get("hypothesisCandidateIds"), limit=16)
    frozen_baseline = _frozen_baseline(best_plan)
    context_seed = {
        "stageType": stage_type,
        "researchQuestion": _text(research_question, 1200),
        "bestPlanId": str((best_plan or {}).get("planId") or ""),
        "negativePlanIds": [item["planId"] for item in negative_experiments],
        "knowledgeItemIds": [item["knowledgeItemId"] for item in formal_knowledge],
    }
    context_hash = hashlib.sha256(
        json.dumps(context_seed, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "schemaVersion": 1,
        "contextId": f"research-memory-context-{context_hash}",
        "stageType": stage_type,
        "researchQuestion": _text(research_question, 1200),
        "reviewedSourceEvidence": reviewed_sources,
        "formalKnowledge": formal_knowledge,
        "allowedClaims": allowed_claims,
        "rejectedUnsupportedClaims": [
            {
                "claim": item["hypothesis"] or item["title"],
                "status": item["status"],
                "interpretation": item["interpretation"],
                "evidenceRefs": item["evidenceRefs"],
            }
            for item in negative_experiments
        ],
        "frozenBaseline": frozen_baseline,
        "currentBest": {
            "planId": str((best_plan or {}).get("planId") or ""),
            "candidateId": best_candidate_ids[0] if best_candidate_ids else "",
            "resultId": _result_id(_active_result(best_plan)),
            "knowledgeItemId": _knowledge_item_id(best_plan),
        },
        "priorSuccessfulRuns": prior_successful_runs,
        "negativeExperiments": negative_experiments,
        "forbiddenDuplicateExperiments": forbidden_duplicates,
        "forbiddenCandidateIds": sorted(
            {
                candidate_id
                for item in forbidden_duplicates
                for candidate_id in item["candidateIds"]
            }
        ),
        "variablesAllowedToChange": variables_allowed_to_change,
        "missingEvidence": missing_evidence,
        "retrieval": {
            "status": retrieval_status,
            "knowledgeItemCount": len(formal_knowledge),
            "reviewedSourceCount": len(reviewed_sources),
            "negativeExperimentCount": len(negative_experiments),
            "successfulRunCount": len(prior_successful_runs),
            "rawKnowledgeContentIncluded": False,
            "rawExperimentLogsIncluded": False,
            "maxFormalKnowledgeItems": MAX_FORMAL_KNOWLEDGE,
            "maxNegativeExperiments": MAX_NEGATIVE_EXPERIMENTS,
        },
        "policy": {
            "defaultDuplicateAction": "exclude_from_suggestions",
            "retestRequires": ["new_evidence", "changed_assumption_or_control", "explicit_retest_rationale"],
            "evidenceRefsRequired": True,
        },
        "security": {
            "knowledgeAndSourceTextIsUntrusted": True,
            "embeddedInstructionsMustBeIgnored": True,
            "referencesMustBeVerifiedBeforeUse": True,
            "rawContentExcluded": True,
        },
    }


def _best_validated_plan(
    plans: list[dict[str, Any]],
    loops: list[dict[str, Any]],
) -> dict[str, Any] | None:
    by_id = {str(plan.get("planId") or ""): plan for plan in plans}
    for loop in reversed(loops):
        if str(loop.get("status") or "") not in {"accepted_for_writeup", "validated", "promoted"}:
            continue
        linked = loop.get("linkedExperiment") if isinstance(loop.get("linkedExperiment"), dict) else {}
        linked_plan = by_id.get(str(linked.get("planId") or ""))
        if linked_plan is not None:
            return linked_plan
    successful = [plan for plan in plans if _is_successful_plan(plan)]
    if not successful:
        return None
    return max(successful, key=lambda plan: (_plan_revision(plan), str(plan.get("updatedAt") or "")))


def _is_successful_plan(plan: dict[str, Any]) -> bool:
    if str(plan.get("status") or "") in SUCCESS_PLAN_STATUSES:
        return True
    result = _active_result(plan)
    return str(result.get("status") or "").lower() == "passed"


def _is_negative_plan(plan: dict[str, Any]) -> bool:
    if str(plan.get("status") or "").lower() in NEGATIVE_PLAN_STATUSES:
        return True
    result = _active_result(plan)
    return str(result.get("status") or "").lower() in {"failed", "needs_review"}


def _negative_experiment_pack(
    plan: dict[str, Any],
    plans: list[dict[str, Any]],
) -> dict[str, Any]:
    contract = plan.get("experimentContract") if isinstance(plan.get("experimentContract"), dict) else {}
    result = _active_result(plan)
    decision_contract = (
        contract.get("decisionContract")
        if isinstance(contract.get("decisionContract"), dict)
        else {}
    )
    result_status = str(result.get("status") or plan.get("status") or "")
    interpretation = _text(
        result.get("interpretation")
        or result.get("summary")
        or result.get("delta")
        or plan.get("notes")
        or f"Experiment ended with {result_status}.",
        600,
    )
    plan_id = str(plan.get("planId") or "")
    superseded_by = next(
        (
            str(candidate.get("planId") or "")
            for candidate in plans
            if str(
                (
                    candidate.get("experimentContract")
                    if isinstance(candidate.get("experimentContract"), dict)
                    else {}
                ).get("supersedesPlanId")
                or ""
            )
            == plan_id
        ),
        "",
    )
    evidence_refs = _result_evidence_refs(result)
    return {
        "planId": plan_id,
        "revision": _plan_revision(plan),
        "title": _text(plan.get("title"), 240),
        "status": str(plan.get("status") or result_status),
        "hypothesis": _plan_hypothesis(plan),
        "changedVariable": _changed_variables(contract),
        "fixedControls": _text_list(contract.get("constraints"), limit=12, max_length=360),
        "result": {
            "resultId": _result_id(result),
            "status": result_status,
            "metricValue": _text(result.get("metricValue"), 240),
            "delta": _text(result.get("delta"), 360),
        },
        "failedGates": _text_list(decision_contract.get("failureCriteria"), limit=8, max_length=360),
        "interpretation": interpretation,
        "retestPolicy": "blocked_without_new_evidence_or_changed_assumption",
        "evidenceRefs": evidence_refs,
        "supersededBy": superseded_by,
        "candidateIds": _text_list(plan.get("hypothesisCandidateIds"), limit=16),
        "experimentSignature": _experiment_signature(plan),
    }


def _active_result(plan: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(plan, dict):
        return {}
    for key in ("activeFullRunResult", "activeSmokeResult"):
        value = plan.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _result_id(result: dict[str, Any]) -> str:
    return str(
        result.get("fullRunResultId")
        or result.get("smokeResultId")
        or result.get("evidenceId")
        or result.get("resultId")
        or ""
    )


def _result_evidence_refs(result: dict[str, Any]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    result_id = _result_id(result)
    if result_id:
        refs.append({"type": "experiment_result", "id": result_id})
    log_ref = _text(result.get("logRef"), 500)
    if log_ref:
        refs.append({"type": "experiment_log", "id": log_ref})
    result_path = _text(result.get("resultPath"), 500)
    if result_path:
        refs.append({"type": "experiment_artifact", "id": result_path})
    return refs[:6]


def _changed_variables(contract: dict[str, Any]) -> dict[str, Any]:
    method_config = contract.get("methodConfig") if isinstance(contract.get("methodConfig"), dict) else {}
    keys = (
        "candidateMaskedLossWeight",
        "candidateLossMaskMode",
        "candidateMechanism",
        "candidateMaskSize",
    )
    return {key: method_config[key] for key in keys if key in method_config}


def _experiment_signature(plan: dict[str, Any]) -> str:
    contract = plan.get("experimentContract") if isinstance(plan.get("experimentContract"), dict) else {}
    signature_payload = {
        "researchQuestion": _text(contract.get("researchQuestion"), 600).lower(),
        "hypothesisCandidateIds": sorted(_text_list(plan.get("hypothesisCandidateIds"), limit=16)),
        "changedVariable": _changed_variables(contract),
        "constraints": _text_list(contract.get("constraints"), limit=12, max_length=240),
    }
    digest = hashlib.sha256(
        json.dumps(signature_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def _formal_knowledge_ref(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "knowledgeItemId": str(item.get("knowledgeItemId") or ""),
        "title": _text(item.get("title"), 240),
        "summary": _text(item.get("summary"), 600),
        "sourceArtifactIds": _text_list(item.get("sourceArtifactIds"), limit=8, max_length=160),
        "centralSourceIds": _text_list(item.get("centralSourceIds"), limit=8, max_length=160),
        "untrustedSummary": True,
    }


def _reviewed_source_ref(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidateId": str(item.get("candidateId") or ""),
        "title": _text(item.get("title"), 240),
        "sourceRef": _text(
            item.get("sourceRef") or item.get("rawLocation") or item.get("resolvedUrl"),
            500,
        ),
        "status": str(item.get("currentState") or item.get("qualityStatus") or ""),
    }


def _allowed_claims(
    formal_knowledge: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    claims = [
        {
            "claim": item["summary"] or item["title"],
            "status": "reviewed_knowledge",
            "evidenceRefs": [{"type": "knowledge_item", "id": item["knowledgeItemId"]}],
        }
        for item in formal_knowledge
        if item["summary"] or item["title"]
    ]
    for candidate in candidates:
        if str(candidate.get("candidateType") or "") != "algorithm_hypothesis":
            continue
        if str(candidate.get("currentState") or "") in {"rejected", "archived", "hypothesis_needs_revision"}:
            continue
        for claim in list(candidate.get("claims") or []):
            if not isinstance(claim, dict):
                continue
            claim_text = _text(claim.get("claim"), 600)
            if not claim_text:
                continue
            claims.append(
                {
                    "claim": claim_text,
                    "status": "hypothesis_candidate",
                    "evidenceRefs": [
                        {
                            "type": "candidate_source",
                            "id": str(claim.get("sourceRef") or candidate.get("candidateId") or ""),
                        }
                    ],
                }
            )
            if len(claims) >= MAX_ALLOWED_CLAIMS:
                return claims
    return claims[:MAX_ALLOWED_CLAIMS]


def _successful_runs(
    plans: list[dict[str, Any]],
    loops: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for plan in plans:
        result = _active_result(plan)
        if str(result.get("status") or "").lower() != "passed":
            continue
        runs.append(
            {
                "planId": str(plan.get("planId") or ""),
                "resultId": _result_id(result),
                "candidateIds": _text_list(plan.get("hypothesisCandidateIds"), limit=16),
                "evidenceRefs": _result_evidence_refs(result),
            }
        )
    for loop in loops:
        for evidence in list(loop.get("evidenceRecords") or []):
            if not isinstance(evidence, dict) or str(evidence.get("status") or "").lower() != "passed":
                continue
            if str(evidence.get("evidenceType") or "") not in {"benchmark_result", "full_run_result", "metric_report"}:
                continue
            runs.append(
                {
                    "planId": str(
                        (
                            loop.get("linkedExperiment")
                            if isinstance(loop.get("linkedExperiment"), dict)
                            else {}
                        ).get("planId")
                        or ""
                    ),
                    "resultId": str(evidence.get("evidenceId") or evidence.get("resultId") or ""),
                    "candidateIds": _text_list(
                        (
                            loop.get("linkedExperiment")
                            if isinstance(loop.get("linkedExperiment"), dict)
                            else {}
                        ).get("candidateIds"),
                        limit=16,
                    ),
                    "evidenceRefs": [
                        {
                            "type": str(evidence.get("evidenceType") or "experiment_evidence"),
                            "id": str(evidence.get("evidenceId") or evidence.get("resultId") or ""),
                        }
                    ],
                }
            )
    return runs[-MAX_SUCCESSFUL_RUNS:]


def _frozen_baseline(plan: dict[str, Any] | None) -> dict[str, Any]:
    contract = plan.get("experimentContract") if isinstance((plan or {}).get("experimentContract"), dict) else {}
    method_config = contract.get("methodConfig") if isinstance(contract.get("methodConfig"), dict) else {}
    baseline_selection = (
        plan.get("baselineSelection")
        if isinstance((plan or {}).get("baselineSelection"), dict)
        else {}
    )
    return {
        "planId": str((plan or {}).get("planId") or ""),
        "baseline": _text(method_config.get("baseline") or baseline_selection.get("baseline"), 600),
        "artifactId": str(baseline_selection.get("activeBaselineArtifactId") or ""),
    }


def _allowed_variable_changes(plan: dict[str, Any] | None) -> list[str]:
    contract = plan.get("experimentContract") if isinstance((plan or {}).get("experimentContract"), dict) else {}
    iteration_contract = (
        contract.get("iterationContract")
        if isinstance(contract.get("iterationContract"), dict)
        else {}
    )
    return _text_list(
        iteration_contract.get("allowedChanges")
        or iteration_contract.get("variablesAllowedToChange"),
        limit=16,
        max_length=240,
    )


def _knowledge_item_id(plan: dict[str, Any] | None) -> str:
    ingestion = plan.get("knowledgeIngestion") if isinstance((plan or {}).get("knowledgeIngestion"), dict) else {}
    result = ingestion.get("result") if isinstance(ingestion.get("result"), dict) else {}
    return str(result.get("knowledgeItemId") or "")


def _plan_hypothesis(plan: dict[str, Any]) -> str:
    selected = [item for item in list(plan.get("selectedHypotheses") or []) if isinstance(item, dict)]
    if selected:
        return _text(selected[0].get("hypothesis"), 800)
    contract = plan.get("experimentContract") if isinstance(plan.get("experimentContract"), dict) else {}
    return _text(contract.get("researchQuestion"), 800)


def _plan_revision(plan: dict[str, Any]) -> int:
    contract = plan.get("experimentContract") if isinstance(plan.get("experimentContract"), dict) else {}
    try:
        return max(0, int(contract.get("revision") or 0))
    except (TypeError, ValueError):
        return 0


def _text(value: Any, max_length: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:max_length]


def _text_list(value: Any, *, limit: int, max_length: int = 160) -> list[str]:
    if isinstance(value, str):
        rows = [value]
    elif isinstance(value, (list, tuple, set)):
        rows = list(value)
    else:
        rows = []
    result: list[str] = []
    for row in rows:
        text = _text(row, max_length)
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result
