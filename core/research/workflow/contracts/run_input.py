"""Frozen input contract for a WorkflowRun."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._validation import (
    ContractValidationError,
    canonical_sha256,
    require_keys,
    require_list,
    require_mapping,
    require_text,
)

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
            snapshotHash=snapshot_hash,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
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
            "snapshotHash": self.snapshotHash,
        }
