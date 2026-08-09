"""Validate structured research artifacts before a NodeRun may advance."""

from __future__ import annotations

import uuid
from typing import Any

from core.research.workflow.contracts import (
    CompetitionEvaluationSnapshot,
    ContractValidationError,
    ExperimentCampaign,
    HypothesisPortfolio,
)
from core.research.workflow.iteration_decisions import (
    IterationDecisionKind,
    check_rerun_budget,
    parse_decision_kind,
    validate_decision_payload,
)

from .node_execution_support import iso, utc_now


class ArtifactQualityError(ValueError):
    def __init__(self, message: str, *, code: str = "quality_gate_failed"):
        super().__init__(message)
        self.code = code


def _payload_for_kind(
    manifests: list[dict[str, Any]],
    payloads: dict[str, Any],
    kind: str,
) -> dict[str, Any]:
    manifest = next(
        (
            item
            for item in manifests
            if str(item.get("artifactId") or "").split(":", 1)[0] == kind
        ),
        None,
    )
    if manifest is None:
        raise ArtifactQualityError(f"required artifact kind is missing: {kind}")
    artifact_id = str(manifest["artifactId"])
    payload = payloads.get(artifact_id)
    if not isinstance(payload, dict):
        raise ArtifactQualityError(
            f"structured artifact payload is missing: {artifact_id}"
        )
    return dict(payload)


def validate_artifact_quality(
    record: dict[str, Any],
    *,
    node_id: str,
    manifests: list[dict[str, Any]],
    payloads: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    details: dict[str, Any] = {}
    records: dict[str, Any] = {}
    try:
        if node_id == "source_finding":
            payload = _payload_for_kind(manifests, payloads, "source_candidate_batch")
            perspectives = list(payload.get("perspectives") or [])
            queries = list(payload.get("queries") or [])
            candidates = list(payload.get("candidateSources") or [])
            if len(perspectives) < 2 or not queries or not candidates:
                raise ArtifactQualityError(
                    "source finding requires at least two perspectives, queries and candidates"
                )
            details = {
                "perspectiveCount": len(perspectives),
                "queryCount": len(queries),
                "candidateCount": len(candidates),
            }
        elif node_id == "source_extraction":
            payload = _payload_for_kind(manifests, payloads, "evidence_card_batch")
            cards = list(payload.get("evidenceCards") or [])
            if not cards or any(
                not isinstance(card, dict)
                or not str(card.get("sourceId") or "")
                or not str(card.get("claim") or "")
                or not isinstance(card.get("citationLocator"), dict)
                or not any(card["citationLocator"].values())
                for card in cards
            ):
                raise ArtifactQualityError(
                    "every evidence card requires sourceId, claim and citationLocator"
                )
            details = {"evidenceCardCount": len(cards)}
        elif node_id == "evidence_relations":
            payload = _payload_for_kind(
                manifests,
                payloads,
                "evidence_relation_graph",
            )
            gaps = list(payload.get("evidenceGaps") or [])
            counter_refs = list(payload.get("counterEvidenceRefs") or [])
            if not gaps or not counter_refs:
                raise ArtifactQualityError(
                    "evidence relations require evidence gaps and counter-evidence"
                )
            details = {
                "evidenceGapCount": len(gaps),
                "counterEvidenceCount": len(counter_refs),
            }
        elif node_id == "hypothesis_design":
            payload = _payload_for_kind(manifests, payloads, "hypothesis_set")
            portfolio = HypothesisPortfolio.from_dict(payload)
            if portfolio.runId != record["runId"]:
                raise ArtifactQualityError("hypothesis portfolio runId mismatch")
            if any(not candidate.counterEvidenceRefs for candidate in portfolio.candidates):
                raise ArtifactQualityError(
                    "every hypothesis candidate requires counter-evidence references"
                )
            current_round = int(payload.get("currentEvolutionRound") or 1)
            if current_round > portfolio.maxEvolutionRounds:
                raise ArtifactQualityError("hypothesis evolution round limit exceeded")
            details = {
                "candidateCount": len(portfolio.candidates),
                "evolutionRound": current_round,
            }
            records["hypothesisPortfolio"] = {
                **portfolio.to_dict(),
                "currentEvolutionRound": current_round,
            }
        elif node_id == "controlled_run":
            payload = _payload_for_kind(manifests, payloads, "run_artifacts")
            campaign = ExperimentCampaign.from_dict(payload)
            if campaign.runId != record["runId"]:
                raise ArtifactQualityError("experiment campaign runId mismatch")
            if campaign.replicationCount < 2:
                raise ArtifactQualityError(
                    "experiment campaign requires at least two replications"
                )
            details = {
                "stage": campaign.stage.value,
                "replicationCount": campaign.replicationCount,
            }
            records["experimentCampaign"] = campaign.to_dict()
        elif node_id == "result_evaluation":
            payload = _payload_for_kind(manifests, payloads, "evaluation_report")
            evaluation = CompetitionEvaluationSnapshot.from_dict(payload)
            if evaluation.runId != record["runId"]:
                raise ArtifactQualityError("competition evaluation runId mismatch")
            contract = dict(
                (record.get("inputSnapshot") or {}).get("evaluationContract") or {}
            )
            minimum_claim = float(contract.get("minimumClaimEvidenceCoverage") or 0)
            if evaluation.claimCoverage < minimum_claim:
                raise ArtifactQualityError(
                    "competition evaluation claim coverage is below the frozen minimum"
                )
            if evaluation.has_blockers:
                raise ArtifactQualityError(
                    "competition evaluation contains blocking warnings"
                )
            details = {
                "claimCoverage": evaluation.claimCoverage,
                "evidenceCoverage": evaluation.evidenceCoverage,
                "experimentCoverage": evaluation.experimentCoverage,
            }
            records["competitionEvaluation"] = evaluation.to_dict()
        elif node_id == "iteration_decision":
            payload = _payload_for_kind(manifests, payloads, "iteration_decision")
            decision = validate_decision_payload(payload)
            if decision.runId != record["runId"]:
                raise ArtifactQualityError("iteration decision runId mismatch")
            if not decision.decisionId or not decision.nodeRunId:
                raise ArtifactQualityError(
                    "iteration decision requires decisionId and nodeRunId"
                )
            if decision.iterationAttempt < 1:
                raise ArtifactQualityError(
                    "iteration decision requires a positive iterationAttempt"
                )
            if not decision.evaluationReportRef:
                raise ArtifactQualityError(
                    "iteration decision requires evaluationReportRef"
                )
            if decision.decisionKind is IterationDecisionKind.RERUN_SAME_PROTOCOL:
                if not decision.frozenProtocolRef:
                    raise ArtifactQualityError(
                        "rerun_same_protocol requires frozenProtocolRef"
                    )
                completed_attempts = len(
                    {
                        int(item.get("attempt") or 0)
                        for item in record.get("nodeRuns") or []
                        if item.get("nodeId") == "controlled_run"
                        and item.get("status") == "succeeded"
                    }
                )
                try:
                    check_rerun_budget(
                        current_attempt=completed_attempts,
                        budget_max=int(record.get("iterationBudgetMax") or 1),
                    )
                except ValueError as exc:
                    raise ArtifactQualityError(
                        str(exc),
                        code="iteration_budget_exhausted",
                    ) from exc
            if decision.decisionKind in {
                IterationDecisionKind.PROMOTE_CANDIDATE,
                IterationDecisionKind.STOP,
            } and not (
                decision.selectedCandidateRef or record.get("officialCandidateRef")
            ):
                raise ArtifactQualityError(
                    "terminal iteration decision requires a selected candidate"
                )
            details = {
                "decisionId": decision.decisionId,
                "decisionKind": decision.decisionKind.value,
                "iterationAttempt": decision.iterationAttempt,
            }
            records["iterationDecision"] = decision.to_dict()
        elif node_id == "version_governance":
            payload = _payload_for_kind(
                manifests,
                payloads,
                "version_governance_record",
            )
            latest_decision = next(
                (
                    dict(item)
                    for item in reversed(record.get("iterationDecisions") or [])
                    if isinstance(item, dict)
                ),
                None,
            )
            if latest_decision is None:
                raise ArtifactQualityError(
                    "version governance requires an iteration decision"
                )
            kind = parse_decision_kind(latest_decision.get("decisionKind"))
            expected_operation = {
                IterationDecisionKind.PROMOTE_CANDIDATE: "promote",
                IterationDecisionKind.ROLLBACK_CANDIDATE: "rollback",
                IterationDecisionKind.STOP: "stop",
            }.get(kind)
            if expected_operation is None:
                raise ArtifactQualityError(
                    "version governance received a non-terminal decision"
                )
            candidate_ref = str(payload.get("candidateRef") or "").strip()
            version_id = str(payload.get("versionId") or "").strip()
            status = str(payload.get("status") or "").strip()
            if payload.get("runId") != record["runId"]:
                raise ArtifactQualityError("version governance runId mismatch")
            if payload.get("decisionId") != latest_decision.get("decisionId"):
                raise ArtifactQualityError("version governance decisionId mismatch")
            if payload.get("operation") != expected_operation:
                raise ArtifactQualityError("version governance operation mismatch")
            expected_candidate = str(
                latest_decision.get("selectedCandidateRef")
                or latest_decision.get("baselineRef")
                or record.get("officialCandidateRef")
                or ""
            )
            if candidate_ref != expected_candidate:
                raise ArtifactQualityError(
                    "version governance candidateRef mismatch"
                )
            if not candidate_ref or not version_id:
                raise ArtifactQualityError(
                    "version governance requires candidateRef and versionId"
                )
            expected_status = "proposed" if expected_operation == "promote" else "official"
            if status != expected_status:
                raise ArtifactQualityError(
                    f"version governance status must be {expected_status}"
                )
            if expected_operation == "stop" and not str(
                payload.get("terminalReason") or ""
            ).strip():
                raise ArtifactQualityError(
                    "stop version governance requires terminalReason"
                )
            details = {
                "versionId": version_id,
                "operation": expected_operation,
                "status": status,
            }
            records["versionGovernance"] = dict(payload)
        else:
            return None, records
    except ContractValidationError as exc:
        raise ArtifactQualityError(str(exc)) from exc

    return (
        {
            "qualityGateId": f"quality-{uuid.uuid4().hex[:12]}",
            "runId": record["runId"],
            "nodeId": node_id,
            "status": "passed",
            "details": details,
            "evaluatedAt": iso(utc_now()),
        },
        records,
    )
