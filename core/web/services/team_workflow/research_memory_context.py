"""Bounded, reference-first memory context for Challenge Cup research stages."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from core.web.services.team_workflow.outcome_graph import (
    apply_graph_claim_flags,
    claim_id_for_hypothesis,
    plan_has_outcome_graph,
    project_outcome_memory,
)

_LOGGER = logging.getLogger(__name__)

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
MAX_CLAIM_MAP_ITEMS = 12
MAX_NEGATIVE_EXPERIMENTS = 8
MAX_SUCCESSFUL_RUNS = 8
MAX_REVIEW_DIGEST_ITEMS = 8
MAX_REVIEW_SOURCE_REFS = 16
MAX_REVIEW_DECISIONS = 4
MAX_REVIEW_CANDIDATES = 16
CLAIM_STATUS_ORDER = {
    "qualified": 0,
    "unsupported": 1,
    "rejected": 2,
    "not_established": 3,
}


def build_research_memory_context(
    *,
    stage_type: str,
    research_question: str,
    candidates: list[dict[str, Any]] | None = None,
    plans: list[dict[str, Any]] | None = None,
    loops: list[dict[str, Any]] | None = None,
    knowledge_results: list[dict[str, Any]] | None = None,
    retrieval_status: str = "completed",
    control_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate_rows = [item for item in list(candidates or []) if isinstance(item, dict)]
    plan_rows = [item for item in list(plans or []) if isinstance(item, dict)]
    loop_rows = [item for item in list(loops or []) if isinstance(item, dict)]
    knowledge_rows = [item for item in list(knowledge_results or []) if isinstance(item, dict)]
    best_plan = _best_validated_plan(plan_rows, loop_rows)
    graph_memory = project_outcome_memory(plan_rows)
    heuristic_plans = [plan for plan in plan_rows if not plan_has_outcome_graph(plan)]
    negative_experiments = [
        _negative_experiment_pack(plan, plan_rows)
        for plan in heuristic_plans
        if _is_negative_plan(plan)
    ]
    negative_experiments.extend(list(graph_memory.get("negativeExperiments") or []))
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
    seen_forbidden = {
        (str(item.get("planId") or ""), str(item.get("experimentSignature") or ""))
        for item in forbidden_duplicates
    }
    for item in list(graph_memory.get("forbiddenDuplicateExperiments") or []):
        key = (str(item.get("planId") or ""), str(item.get("experimentSignature") or ""))
        if key in seen_forbidden:
            continue
        candidate_ids = [
            candidate_id
            for candidate_id in list(item.get("candidateIds") or [])
            if candidate_id not in successful_candidate_ids
        ]
        if not candidate_ids and not item.get("experimentSignature"):
            continue
        forbidden_duplicates.append(
            {
                "planId": item.get("planId") or "",
                "experimentSignature": item.get("experimentSignature") or "",
                "candidateIds": candidate_ids,
                "reason": item.get("reason") or item.get("interpretation") or "",
                "defaultAction": "exclude_from_suggestions",
                "retestPolicy": item.get("retestPolicy") or "blocked_without_new_evidence_or_changed_assumption",
                "evidenceRefs": item.get("evidenceRefs") or [],
            }
        )
        seen_forbidden.add(key)
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
    prior_successful_runs = _successful_runs(heuristic_plans, loop_rows)
    seen_success = {
        (str(item.get("planId") or ""), str(item.get("resultId") or ""))
        for item in prior_successful_runs
    }
    for item in list(graph_memory.get("priorSuccessfulRuns") or []):
        key = (str(item.get("planId") or ""), str(item.get("resultId") or ""))
        if key in seen_success:
            continue
        prior_successful_runs.append(item)
        seen_success.add(key)
    prior_successful_runs = prior_successful_runs[-MAX_SUCCESSFUL_RUNS:]
    claim_map = _claim_map(plan_rows, candidate_rows)
    claim_status_counts = {
        status: sum(1 for item in claim_map if item["status"] == status)
        for status in CLAIM_STATUS_ORDER
    }
    allowed_variable_contract = _allowed_variable_contract(
        control_plan if isinstance(control_plan, dict) else best_plan
    )
    variables_allowed_to_change = [
        item["path"]
        for item in allowed_variable_contract["variables"]
    ]
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
        "claimIds": [item["claimId"] for item in claim_map],
        "allowedVariables": variables_allowed_to_change,
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
        "claimMap": claim_map,
        "claimStatusCounts": claim_status_counts,
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
        "allowedVariableContract": allowed_variable_contract,
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


def build_hypothesis_review_context(
    *,
    meeting_round: dict[str, Any],
    digest: dict[str, Any],
    decisions: list[dict[str, Any]] | None = None,
    candidates: list[dict[str, Any]] | None = None,
    prior_round: dict[str, Any] | None = None,
    extra_evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Bounded, reference-first review context for the hypothesis review executor.

    Assembles what the four separated review steps (Reflection / Pairwise /
    Pareto / MetaReview) may see: the closed meeting's digest sections with
    the message evidence trail, the decision records with evidence refs, the
    candidate hypotheses under review, and the previous round's outcome for
    lineage-aware re-review.  Digest and candidate text is untrusted input:
    it is truncated, reference-first, and carries the same security flags as
    the stage memory context.
    """
    meeting = dict(meeting_round) if isinstance(meeting_round, dict) else {}
    digest_row = dict(digest) if isinstance(digest, dict) else {}
    decision_rows = [dict(item) for item in list(decisions or []) if isinstance(item, dict)]
    candidate_rows = [dict(item) for item in list(candidates or []) if isinstance(item, dict)]
    disagreements = [
        {
            "issue": _text(item.get("issue"), 360),
            "positions": _text_list(item.get("positions"), limit=4, max_length=240),
            "unresolvedReason": _text(item.get("unresolvedReason"), 240),
        }
        for item in list(digest_row.get("disagreements") or [])
        if isinstance(item, dict)
    ][:MAX_REVIEW_DIGEST_ITEMS]
    action_items = [
        {
            "ownerRoleId": _text(item.get("ownerRoleId"), 120),
            "action": _text(item.get("action"), 360),
            "dueGate": _text(item.get("dueGate"), 120),
        }
        for item in list(digest_row.get("actionItems") or [])
        if isinstance(item, dict)
    ][:MAX_REVIEW_DIGEST_ITEMS]
    bounded_decisions = [
        {
            "decisionId": str(item.get("decisionId") or ""),
            "decision": str(item.get("decision") or ""),
            "candidateRefs": _text_list(item.get("candidateRefs"), limit=16),
            "evidenceRefs": _text_list(item.get("evidenceRefs"), limit=16, max_length=240),
        }
        for item in decision_rows[:MAX_REVIEW_DECISIONS]
    ]
    bounded_candidates = [
        {
            "candidateId": str(item.get("candidateId") or ""),
            "claim": _text(item.get("claim"), 800),
            "rationale": _text(item.get("rationale"), 600),
            "differenceFromAlternatives": _text(item.get("differenceFromAlternatives"), 600),
            "candidateAuthority": str(item.get("candidateAuthority") or "").strip(),
            "lineageRefs": _text_list(item.get("lineageRefs"), limit=24, max_length=360),
            "testablePrediction": _text(item.get("testablePrediction"), 800),
            "falsifier": _text(item.get("falsifier"), 800),
            "axisProfile": {
                axis: _text(item.get("axisProfile", {}).get(axis), 360)
                for axis in (
                    "mechanism",
                    "intervention",
                    "observable",
                    "population",
                    "boundary",
                )
            }
            if isinstance(item.get("axisProfile"), dict)
            else {},
        }
        for item in candidate_rows[:MAX_REVIEW_CANDIDATES]
        if str(item.get("candidateId") or "").strip()
    ]
    if len(candidate_rows) > MAX_REVIEW_CANDIDATES:
        # Silent truncation would hide both the dropped candidates and the
        # pairwise call-budget growth of the survivors; the exact Stage-1
        # budget (n + n(n-1)/2 + 2) makes the cost visible instead.
        _LOGGER.warning(
            "hypothesis review context truncated candidates from %d to %d "
            "(MAX_REVIEW_CANDIDATES); at %d candidates the exact review call "
            "budget n + n(n-1)/2 + 2 would reach %d calls",
            len(candidate_rows),
            MAX_REVIEW_CANDIDATES,
            MAX_REVIEW_CANDIDATES,
            MAX_REVIEW_CANDIDATES
            + MAX_REVIEW_CANDIDATES * (MAX_REVIEW_CANDIDATES - 1) // 2
            + 2,
        )
    source_refs = _text_list(digest_row.get("sourceMessageRefs"), limit=MAX_REVIEW_SOURCE_REFS, max_length=360)
    merged_refs = list(extra_evidence_refs or [])
    for decision in bounded_decisions:
        merged_refs.extend(decision["evidenceRefs"])
    merged_refs.extend(source_refs)
    evidence_refs: list[str] = []
    for ref in merged_refs:
        if ref and ref not in evidence_refs:
            evidence_refs.append(ref)
        if len(evidence_refs) >= MAX_REVIEW_SOURCE_REFS:
            break
    prior = dict(prior_round) if isinstance(prior_round, dict) else {}
    prior_meta = prior.get("metaReview") if isinstance(prior.get("metaReview"), dict) else {}
    prior_pareto = prior.get("pareto") if isinstance(prior.get("pareto"), dict) else {}
    prior_summary = {}
    if prior:
        prior_summary = {
            "roundId": str(prior.get("roundId") or ""),
            "recommendationCandidateId": str(prior_meta.get("recommendationCandidateId") or ""),
            "accepted": bool(prior_meta.get("accepted")),
            "paretoFrontCandidateIds": _text_list(
                prior_pareto.get("paretoFrontCandidateIds"), limit=16
            ),
        }
    context_seed = {
        "meetingRoundId": str(meeting.get("meetingRoundId") or ""),
        "digestId": str(digest_row.get("digestId") or ""),
        "digestContentHash": str(digest_row.get("contentHash") or ""),
        "candidateIds": [item["candidateId"] for item in bounded_candidates],
        "priorRoundId": prior_summary.get("roundId", ""),
    }
    context_hash = hashlib.sha256(
        json.dumps(context_seed, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "schemaVersion": 1,
        "contextId": f"hypothesis-review-context-{context_hash}",
        "stageType": "hypothesis_review",
        "meetingRoundId": str(meeting.get("meetingRoundId") or ""),
        "meetingType": str(meeting.get("meetingType") or ""),
        "digest": {
            "digestId": str(digest_row.get("digestId") or ""),
            "summary": _text(digest_row.get("summary"), 1200),
            "agendaSummary": _text(digest_row.get("agendaSummary"), 600),
            "agreements": _text_list(digest_row.get("agreements"), limit=MAX_REVIEW_DIGEST_ITEMS, max_length=360),
            "disagreements": disagreements,
            "actionItems": action_items,
            "risks": _text_list(digest_row.get("risks"), limit=MAX_REVIEW_DIGEST_ITEMS, max_length=360),
            "knowledgeCandidates": _text_list(
                digest_row.get("knowledgeCandidates"), limit=MAX_REVIEW_DIGEST_ITEMS, max_length=360
            ),
            "sourceMessageRefs": source_refs,
            "contentHash": str(digest_row.get("contentHash") or ""),
        },
        "decisions": bounded_decisions,
        "evidenceRefs": evidence_refs,
        "candidates": bounded_candidates,
        "priorRound": prior_summary,
        "retrieval": {
            "status": "completed",
            "decisionCount": len(bounded_decisions),
            "candidateCount": len(bounded_candidates),
            "sourceMessageRefCount": len(source_refs),
            "rawRoomMessagesIncluded": False,
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


def _claim_map(
    plans: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    claims_by_key: dict[str, dict[str, Any]] = {}

    def ensure_claim(claim: str) -> dict[str, Any] | None:
        text = _text(claim, 800)
        if not text:
            return None
        normalized = " ".join(text.lower().split())
        claim_id = claim_id_for_hypothesis(text)
        return claims_by_key.setdefault(
            normalized,
            {
                "claimId": claim_id,
                "claim": text,
                "status": "not_established",
                "supportEvidenceRefs": [],
                "counterEvidenceRefs": [],
                "applicableBoundaries": [],
                "sourcePlanIds": [],
                "_qualified": False,
                "_unsupported": False,
                "_explicitlyRejected": False,
            },
        )

    for plan in plans:
        item = ensure_claim(_plan_hypothesis(plan))
        if item is None:
            continue
        plan_id = str(plan.get("planId") or "")
        if plan_id and plan_id not in item["sourcePlanIds"]:
            item["sourcePlanIds"].append(plan_id)
        contract = plan.get("experimentContract") if isinstance(plan.get("experimentContract"), dict) else {}
        item["applicableBoundaries"] = _merge_text_values(
            item["applicableBoundaries"],
            _text_list(contract.get("constraints"), limit=12, max_length=360),
            limit=12,
        )
        result = _active_result(plan)
        evidence_refs = _result_evidence_refs(result)
        plan_status = str(plan.get("status") or "").lower()
        if plan_has_outcome_graph(plan):
            apply_graph_claim_flags(item, plan)
            if plan_status in SUCCESS_PLAN_STATUSES or _knowledge_item_id(plan):
                item["_qualified"] = True
                item["supportEvidenceRefs"] = _merge_evidence_refs(
                    item["supportEvidenceRefs"],
                    _knowledge_evidence_refs(plan),
                )
            elif plan_status in {"rejected", "archived"}:
                item["_explicitlyRejected"] = True
        elif _is_successful_plan(plan):
            item["_qualified"] = True
            item["supportEvidenceRefs"] = _merge_evidence_refs(
                item["supportEvidenceRefs"],
                evidence_refs + _knowledge_evidence_refs(plan),
            )
        elif _is_negative_plan(plan):
            item["_unsupported"] = True
            item["counterEvidenceRefs"] = _merge_evidence_refs(
                item["counterEvidenceRefs"],
                evidence_refs,
            )
        elif plan_status in {"rejected", "archived"}:
            item["_explicitlyRejected"] = True

    for candidate in candidates:
        if str(candidate.get("candidateType") or "") != "algorithm_hypothesis":
            continue
        candidate_state = str(candidate.get("currentState") or "").lower()
        if candidate_state not in {"rejected", "archived", "hypothesis_needs_revision"}:
            continue
        for claim in list(candidate.get("claims") or []):
            if not isinstance(claim, dict):
                continue
            item = ensure_claim(_text(claim.get("claim"), 800))
            if item is None:
                continue
            item["applicableBoundaries"] = _merge_text_values(
                item["applicableBoundaries"],
                _text_list(claim.get("boundaries"), limit=8, max_length=360),
                limit=12,
            )
            item["_explicitlyRejected"] = True

    rows: list[dict[str, Any]] = []
    for item in claims_by_key.values():
        if item["_qualified"]:
            status = "qualified"
        elif item["_explicitlyRejected"]:
            status = "rejected"
        elif item["_unsupported"]:
            status = "unsupported"
        else:
            status = "not_established"
        item["status"] = status
        item.pop("_qualified", None)
        item.pop("_unsupported", None)
        item.pop("_explicitlyRejected", None)
        rows.append(item)
    rows.sort(
        key=lambda item: (
            CLAIM_STATUS_ORDER.get(str(item.get("status") or ""), 99),
            str(item.get("claimId") or ""),
        )
    )
    return rows[:MAX_CLAIM_MAP_ITEMS]


def _merge_evidence_refs(
    existing: list[dict[str, str]],
    incoming: list[dict[str, str]],
) -> list[dict[str, str]]:
    merged = list(existing)
    seen = {
        (str(item.get("type") or ""), str(item.get("id") or ""))
        for item in merged
    }
    for item in incoming:
        key = (str(item.get("type") or ""), str(item.get("id") or ""))
        if not key[1] or key in seen:
            continue
        merged.append({"type": key[0], "id": key[1]})
        seen.add(key)
        if len(merged) >= 8:
            break
    return merged


def _knowledge_evidence_refs(plan: dict[str, Any]) -> list[dict[str, str]]:
    knowledge_item_id = _knowledge_item_id(plan)
    if not knowledge_item_id:
        return []
    return [{"type": "knowledge_item", "id": knowledge_item_id}]


def _merge_text_values(
    existing: list[str],
    incoming: list[str],
    *,
    limit: int,
) -> list[str]:
    merged = list(existing)
    for item in incoming:
        if item and item not in merged:
            merged.append(item)
        if len(merged) >= limit:
            break
    return merged


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


def _allowed_variable_contract(plan: dict[str, Any] | None) -> dict[str, Any]:
    contract = plan.get("experimentContract") if isinstance((plan or {}).get("experimentContract"), dict) else {}
    iteration_contract = (
        contract.get("iterationContract")
        if isinstance(contract.get("iterationContract"), dict)
        else {}
    )
    plan_id = str((plan or {}).get("planId") or "")
    explicit_paths = _text_list(
        iteration_contract.get("allowedChanges")
        or iteration_contract.get("allowedVariableChanges")
        or iteration_contract.get("variablesAllowedToChange"),
        limit=16,
        max_length=240,
    )
    if explicit_paths:
        return {
            "status": "explicit",
            "variables": [
                {
                    "path": path,
                    "source": "iteration_contract",
                    "evidenceRef": plan_id,
                }
                for path in explicit_paths
            ],
            "frozenControls": _text_list(
                iteration_contract.get("frozenControls"),
                limit=24,
                max_length=360,
            )
            or _frozen_controls(contract, explicit_paths),
        }

    derived_paths = _derive_allowed_paths_from_constraints(contract)
    if derived_paths:
        return {
            "status": "derived_from_frozen_constraints",
            "variables": [
                {
                    "path": path,
                    "source": "frozen_constraint",
                    "evidenceRef": plan_id,
                }
                for path in derived_paths
            ],
            "frozenControls": _frozen_controls(contract, derived_paths),
        }
    return {
        "status": "missing",
        "variables": [],
        "frozenControls": _text_list(contract.get("constraints"), limit=12, max_length=360),
    }


def _derive_allowed_paths_from_constraints(contract: dict[str, Any]) -> list[str]:
    method_config = contract.get("methodConfig") if isinstance(contract.get("methodConfig"), dict) else {}
    constraints = _text_list(contract.get("constraints"), limit=12, max_length=360)
    variables: list[str] = []
    patterns = (
        re.compile(r"\bonly\s+([A-Za-z_][\w.-]*)\s+changes?\b", re.IGNORECASE),
        re.compile(r"(?:仅允许|只有|仅)([A-Za-z_][\w.-]*)发生?变化", re.IGNORECASE),
    )
    for constraint in constraints:
        for pattern in patterns:
            match = pattern.search(constraint)
            if match is None:
                continue
            raw_path = match.group(1).strip(" .")
            path = _resolve_method_config_path(method_config, raw_path)
            if path and path not in variables:
                variables.append(path)
            break
        if len(variables) >= 16:
            break
    return variables


def _resolve_method_config_path(
    method_config: dict[str, Any],
    raw_path: str,
) -> str:
    if "." in raw_path:
        return raw_path
    matches: list[str] = []

    def visit(value: Any, prefix: str) -> None:
        if not isinstance(value, dict):
            return
        for key, child in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}"
            if key_text.lower() == raw_path.lower():
                matches.append(path)
            visit(child, path)

    visit(method_config, "methodConfig")
    if len(matches) == 1:
        return matches[0]
    return raw_path


def _frozen_controls(
    contract: dict[str, Any],
    allowed_paths: list[str],
) -> list[str]:
    allowed_tokens = {
        path.rsplit(".", 1)[-1].lower()
        for path in allowed_paths
    }
    controls: list[str] = []
    for constraint in _text_list(contract.get("constraints"), limit=12, max_length=360):
        normalized = constraint.lower()
        if any(
            token in normalized
            and (
                "only" in normalized
                or "仅" in normalized
                or "只有" in normalized
            )
            for token in allowed_tokens
        ):
            continue
        controls.append(constraint)
    return controls


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
