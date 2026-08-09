"""Bounded parallel research task bundle contract."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._validation import (
    ContractValidationError,
    require_int,
    require_list,
    require_mapping,
    require_text,
)


@dataclass(frozen=True, slots=True)
class ResearchSubtask:
    subtaskId: str
    role: str
    acceptanceContract: dict[str, Any]
    budgetReservationRef: str
    deadlineAt: str
    status: str
    taskId: str
    sessionId: str
    outputArtifactRefs: tuple[str, ...]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ResearchSubtask:
        return cls(
            subtaskId=require_text(payload, "subtaskId"),
            role=require_text(payload, "role"),
            acceptanceContract=require_mapping(payload, "acceptanceContract"),
            budgetReservationRef=require_text(payload, "budgetReservationRef"),
            deadlineAt=require_text(payload, "deadlineAt"),
            status=require_text(payload, "status"),
            taskId=str(payload.get("taskId") or "").strip(),
            sessionId=str(payload.get("sessionId") or "").strip(),
            outputArtifactRefs=tuple(
                str(item) for item in require_list(payload, "outputArtifactRefs")
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "subtaskId": self.subtaskId,
            "role": self.role,
            "acceptanceContract": copy.deepcopy(self.acceptanceContract),
            "budgetReservationRef": self.budgetReservationRef,
            "deadlineAt": self.deadlineAt,
            "status": self.status,
            "taskId": self.taskId,
            "sessionId": self.sessionId,
            "outputArtifactRefs": list(self.outputArtifactRefs),
        }


@dataclass(frozen=True, slots=True)
class ResearchTaskBundle:
    bundleId: str
    runId: str
    parentNodeRunId: str
    objective: str
    inputArtifactRefs: tuple[str, ...]
    subtasks: tuple[ResearchSubtask, ...]
    maxConcurrency: int
    aggregationContract: dict[str, Any]
    status: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ResearchTaskBundle:
        raw_subtasks = require_list(payload, "subtasks", non_empty=True)
        subtasks = tuple(ResearchSubtask.from_dict(item) for item in raw_subtasks)
        max_concurrency = require_int(payload, "maxConcurrency", minimum=1)
        if max_concurrency > len(subtasks):
            raise ContractValidationError("maxConcurrency cannot exceed subtask count")
        if len({item.subtaskId for item in subtasks}) != len(subtasks):
            raise ContractValidationError("subtaskId values must be unique")
        return cls(
            bundleId=require_text(payload, "bundleId"),
            runId=require_text(payload, "runId"),
            parentNodeRunId=require_text(payload, "parentNodeRunId"),
            objective=require_text(payload, "objective"),
            inputArtifactRefs=tuple(
                str(item) for item in require_list(payload, "inputArtifactRefs")
            ),
            subtasks=subtasks,
            maxConcurrency=max_concurrency,
            aggregationContract=require_mapping(payload, "aggregationContract"),
            status=require_text(payload, "status"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundleId": self.bundleId,
            "runId": self.runId,
            "parentNodeRunId": self.parentNodeRunId,
            "objective": self.objective,
            "inputArtifactRefs": list(self.inputArtifactRefs),
            "subtasks": [item.to_dict() for item in self.subtasks],
            "maxConcurrency": self.maxConcurrency,
            "aggregationContract": copy.deepcopy(self.aggregationContract),
            "status": self.status,
        }
