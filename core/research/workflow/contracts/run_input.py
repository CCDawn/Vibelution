"""Frozen input contract for a WorkflowRun."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from core.research.competition.result_set import CatalogScope, ResultSetContractError

from ._validation import (
    ContractValidationError,
    canonical_sha256,
    require_keys,
    require_list,
    require_mapping,
    require_text,
)
from .research_scope import ResearchScopeEnvelope, scope_hash_for, scope_locators_for

_REQUIRED_FIELDS = (
    "teamId",
    "projectId",
    "questionId",
    "workflowVersionId",
    "researchBriefHash",
    "datasetRefs",
    "metricContract",
    "constraintSnapshot",
    "competitionRuleRef",
    "competitionRuleVersion",
    "trackAndRubricSnapshot",
    "researchObjectiveContract",
    "sourcePolicy",
    "budgetPolicy",
    "stopPolicy",
    "environmentSnapshotRef",
    "modelRoutingPolicy",
    "evaluationContract",
    "agentBindingSnapshot",
    "createdBy",
    "createdAt",
)


def _normalize_research_scope(
    payload: Mapping[str, Any],
    *,
    question_id: str,
) -> dict[str, Any]:
    """Validate the immutable server-derived scope and its locators."""

    raw = require_mapping(payload, "researchScopeEnvelope")
    try:
        parsed = ResearchScopeEnvelope.from_dict(raw)
    except ContractValidationError as exc:
        raise ContractValidationError(
            f"researchScopeEnvelope is malformed: {exc}"
        ) from exc
    if parsed.question != question_id:
        raise ContractValidationError(
            "researchScopeEnvelope.question must match questionId"
        )
    expected_hash = scope_hash_for(
        program=parsed.program,
        theme=parsed.theme,
        campaign=parsed.campaign,
        question=parsed.question,
        branch=parsed.branch,
        workflow=parsed.workflow,
        agent_id=parsed.agentId,
        mode=parsed.mode.value,
    )
    if parsed.scopeHash != expected_hash:
        raise ContractValidationError(
            "researchScopeEnvelope.scopeHash does not match its identity"
        )
    expected_locators = scope_locators_for(
        program=parsed.program,
        theme=parsed.theme,
        campaign=parsed.campaign,
        question=parsed.question,
        branch=parsed.branch,
        agent_id=parsed.agentId,
        scope_hash=parsed.scopeHash,
    )
    for field, expected in expected_locators.items():
        if getattr(parsed, field) != expected:
            raise ContractValidationError(
                f"researchScopeEnvelope.{field} does not match its identity"
            )
    return parsed.to_dict()


def _normalize_catalog_scope(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Require the exact scope of the tracked 125-question catalog."""

    raw = require_mapping(payload, "catalogScope")
    try:
        parsed = CatalogScope.from_dict(raw)
        expected = CatalogScope.from_tracked_resources()
    except (ResultSetContractError, TypeError, ValueError, KeyError) as exc:
        raise ContractValidationError(f"catalogScope is malformed: {exc}") from exc
    if parsed != expected:
        raise ContractValidationError(
            "catalogScope must exactly match the tracked competition catalog"
        )
    return parsed.to_dict()


@dataclass(frozen=True, slots=True)
class WorkflowRunInputSnapshot:
    teamId: str
    projectId: str
    questionId: str
    workflowVersionId: str
    researchBriefHash: str
    datasetRefs: tuple[str, ...]
    metricContract: dict[str, Any]
    constraintSnapshot: dict[str, Any]
    competitionRuleRef: str
    competitionRuleVersion: str
    trackAndRubricSnapshot: dict[str, Any]
    researchObjectiveContract: dict[str, Any]
    sourcePolicy: dict[str, Any]
    budgetPolicy: dict[str, Any]
    stopPolicy: dict[str, Any]
    environmentSnapshotRef: str
    modelRoutingPolicy: dict[str, Any]
    evaluationContract: dict[str, Any]
    agentBindingSnapshot: tuple[dict[str, Any], ...]
    createdBy: str
    createdAt: str
    evidenceRemediationContract: dict[str, Any]
    workflowSessionScopeV3: dict[str, str]
    researchScopeEnvelope: dict[str, Any]
    catalogScope: dict[str, Any]
    snapshotHash: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> WorkflowRunInputSnapshot:
        require_keys(payload, _REQUIRED_FIELDS)
        canonical = {
            "teamId": require_text(payload, "teamId"),
            "projectId": require_text(payload, "projectId"),
            "questionId": require_text(payload, "questionId"),
            "workflowVersionId": require_text(payload, "workflowVersionId"),
            "researchBriefHash": require_text(payload, "researchBriefHash"),
            "datasetRefs": [
                str(item).strip()
                for item in require_list(payload, "datasetRefs")
                if str(item).strip()
            ],
            "metricContract": require_mapping(payload, "metricContract"),
            "constraintSnapshot": require_mapping(
                payload, "constraintSnapshot", non_empty=False
            ),
            "competitionRuleRef": require_text(payload, "competitionRuleRef"),
            "competitionRuleVersion": require_text(payload, "competitionRuleVersion"),
            "trackAndRubricSnapshot": require_mapping(
                payload, "trackAndRubricSnapshot"
            ),
            "researchObjectiveContract": require_mapping(
                payload, "researchObjectiveContract"
            ),
            "sourcePolicy": require_mapping(payload, "sourcePolicy"),
            "budgetPolicy": require_mapping(payload, "budgetPolicy"),
            "stopPolicy": require_mapping(payload, "stopPolicy"),
            "environmentSnapshotRef": require_text(payload, "environmentSnapshotRef"),
            "modelRoutingPolicy": require_mapping(payload, "modelRoutingPolicy"),
            "evaluationContract": require_mapping(payload, "evaluationContract"),
            "agentBindingSnapshot": require_list(
                payload, "agentBindingSnapshot", non_empty=True
            ),
            "createdBy": require_text(payload, "createdBy"),
            "createdAt": require_text(payload, "createdAt"),
        }
        if "evidenceRemediationContract" in payload:
            canonical["evidenceRemediationContract"] = require_mapping(
                payload,
                "evidenceRemediationContract",
            )
        has_research_scope = "researchScopeEnvelope" in payload
        has_catalog_scope = "catalogScope" in payload
        if has_research_scope != has_catalog_scope:
            raise ContractValidationError(
                "researchScopeEnvelope and catalogScope must be provided together"
            )
        if has_research_scope:
            canonical["researchScopeEnvelope"] = _normalize_research_scope(
                payload,
                question_id=canonical["questionId"],
            )
            canonical["catalogScope"] = _normalize_catalog_scope(payload)
        raw_scope_mode = payload.get("workflowSessionScopeV3")
        if raw_scope_mode is None:
            canonical["workflowSessionScopeV3"] = {"hypothesis_design": "off"}
        else:
            scope_mode = require_mapping(payload, "workflowSessionScopeV3")
            hypothesis_design_mode = str(
                scope_mode.get("hypothesis_design") or ""
            ).strip().lower()
            if hypothesis_design_mode not in {"off", "shadow", "on"}:
                raise ContractValidationError(
                    "workflowSessionScopeV3.hypothesis_design must be off, shadow or on"
                )
            canonical["workflowSessionScopeV3"] = {
                "hypothesis_design": hypothesis_design_mode
            }
        if any(
            not isinstance(item, Mapping) for item in canonical["agentBindingSnapshot"]
        ):
            raise ContractValidationError(
                "agentBindingSnapshot entries must be objects"
            )
        snapshot_hash = canonical_sha256(canonical)
        return cls(
            teamId=canonical["teamId"],
            projectId=canonical["projectId"],
            questionId=canonical["questionId"],
            workflowVersionId=canonical["workflowVersionId"],
            researchBriefHash=canonical["researchBriefHash"],
            datasetRefs=tuple(canonical["datasetRefs"]),
            metricContract=canonical["metricContract"],
            constraintSnapshot=canonical["constraintSnapshot"],
            competitionRuleRef=canonical["competitionRuleRef"],
            competitionRuleVersion=canonical["competitionRuleVersion"],
            trackAndRubricSnapshot=canonical["trackAndRubricSnapshot"],
            researchObjectiveContract=canonical["researchObjectiveContract"],
            sourcePolicy=canonical["sourcePolicy"],
            budgetPolicy=canonical["budgetPolicy"],
            stopPolicy=canonical["stopPolicy"],
            environmentSnapshotRef=canonical["environmentSnapshotRef"],
            modelRoutingPolicy=canonical["modelRoutingPolicy"],
            evaluationContract=canonical["evaluationContract"],
            agentBindingSnapshot=tuple(
                copy.deepcopy(canonical["agentBindingSnapshot"])
            ),
            createdBy=canonical["createdBy"],
            createdAt=canonical["createdAt"],
            evidenceRemediationContract=copy.deepcopy(
                canonical.get("evidenceRemediationContract") or {}
            ),
            workflowSessionScopeV3=copy.deepcopy(
                canonical["workflowSessionScopeV3"]
            ),
            researchScopeEnvelope=copy.deepcopy(
                canonical.get("researchScopeEnvelope") or {}
            ),
            catalogScope=copy.deepcopy(canonical.get("catalogScope") or {}),
            snapshotHash=snapshot_hash,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "teamId": self.teamId,
            "projectId": self.projectId,
            "questionId": self.questionId,
            "workflowVersionId": self.workflowVersionId,
            "researchBriefHash": self.researchBriefHash,
            "datasetRefs": list(self.datasetRefs),
            "metricContract": copy.deepcopy(self.metricContract),
            "constraintSnapshot": copy.deepcopy(self.constraintSnapshot),
            "competitionRuleRef": self.competitionRuleRef,
            "competitionRuleVersion": self.competitionRuleVersion,
            "trackAndRubricSnapshot": copy.deepcopy(self.trackAndRubricSnapshot),
            "researchObjectiveContract": copy.deepcopy(self.researchObjectiveContract),
            "sourcePolicy": copy.deepcopy(self.sourcePolicy),
            "budgetPolicy": copy.deepcopy(self.budgetPolicy),
            "stopPolicy": copy.deepcopy(self.stopPolicy),
            "environmentSnapshotRef": self.environmentSnapshotRef,
            "modelRoutingPolicy": copy.deepcopy(self.modelRoutingPolicy),
            "evaluationContract": copy.deepcopy(self.evaluationContract),
            "agentBindingSnapshot": copy.deepcopy(list(self.agentBindingSnapshot)),
            "createdBy": self.createdBy,
            "createdAt": self.createdAt,
            "workflowSessionScopeV3": copy.deepcopy(self.workflowSessionScopeV3),
            "snapshotHash": self.snapshotHash,
        }
        if self.researchScopeEnvelope or self.catalogScope:
            payload["researchScopeEnvelope"] = copy.deepcopy(
                self.researchScopeEnvelope
            )
            payload["catalogScope"] = copy.deepcopy(self.catalogScope)
        if self.evidenceRemediationContract:
            payload["evidenceRemediationContract"] = copy.deepcopy(
                self.evidenceRemediationContract
            )
        return payload
