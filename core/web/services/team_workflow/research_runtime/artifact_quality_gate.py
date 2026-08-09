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
