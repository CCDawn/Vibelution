"""Explicit binding between a catalog question stage and a formal workflow node.

The catalog package stages (``generation``, ``review`` and ``revision``) are
not the same vocabulary as the formal workflow's stage ids. A receipt may only
cross that boundary when the owning adapter supplies this versioned binding;
callers must never infer it from node names.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ._validation import ContractValidationError


QUESTION_STAGE_BINDING_SCHEMA_VERSION = 1
QUESTION_STAGE_BINDING_POLICY_ID = "challenge-question-stage-binding-v1"
QUESTION_PACKAGE_STAGES = frozenset({"generation", "review", "revision"})


def _required_text(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ContractValidationError(f"{field} must be a non-empty string")
    return normalized


@dataclass(frozen=True, slots=True)
class QuestionStageBinding:
    """The only accepted mapping from a package stage to a formal node turn."""

    question_stage: str
    question_id: str
    question_run_id: str
    workflow_run_id: str
    workflow_id: str
    workflow_version_id: str
    formal_node_id: str
    formal_node_run_id: str
    formal_node_attempt: int
    session_id: str
    task_id: str
    turn_id: str
    mapping_policy_id: str = QUESTION_STAGE_BINDING_POLICY_ID
    schema_version: int = QUESTION_STAGE_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        stage = _required_text(self.question_stage, "questionStage").lower()
        if stage not in QUESTION_PACKAGE_STAGES:
            raise ContractValidationError(
                "questionStage must be generation, review or revision"
            )
        object.__setattr__(self, "question_stage", stage)
        for name, wire_name in (
            ("question_id", "questionId"),
            ("question_run_id", "questionRunId"),
            ("workflow_run_id", "workflowRunId"),
            ("workflow_id", "workflowId"),
            ("workflow_version_id", "workflowVersionId"),
            ("formal_node_id", "formalNodeId"),
            ("formal_node_run_id", "formalNodeRunId"),
            ("session_id", "sessionId"),
            ("task_id", "taskId"),
            ("turn_id", "turnId"),
        ):
            object.__setattr__(self, name, _required_text(getattr(self, name), wire_name))
        if self.schema_version != QUESTION_STAGE_BINDING_SCHEMA_VERSION:
            raise ContractValidationError(
                f"schemaVersion must be {QUESTION_STAGE_BINDING_SCHEMA_VERSION}"
            )
        if self.mapping_policy_id != QUESTION_STAGE_BINDING_POLICY_ID:
            raise ContractValidationError(
                f"mappingPolicyId must be {QUESTION_STAGE_BINDING_POLICY_ID}"
            )
        if isinstance(self.formal_node_attempt, bool) or self.formal_node_attempt < 1:
            raise ContractValidationError("formalNodeAttempt must be >= 1")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "QuestionStageBinding":
        if not isinstance(payload, Mapping):
            raise ContractValidationError("questionStageBinding must be an object")
        try:
            return cls(
                question_stage=payload.get("questionStage"),
                question_id=payload.get("questionId"),
                question_run_id=payload.get("questionRunId"),
                workflow_run_id=payload.get("workflowRunId"),
                workflow_id=payload.get("workflowId"),
                workflow_version_id=payload.get("workflowVersionId"),
                formal_node_id=payload.get("formalNodeId"),
                formal_node_run_id=payload.get("formalNodeRunId"),
                formal_node_attempt=int(payload.get("formalNodeAttempt") or 0),
                session_id=payload.get("sessionId"),
                task_id=payload.get("taskId"),
                turn_id=payload.get("turnId"),
                mapping_policy_id=str(
                    payload.get("mappingPolicyId") or QUESTION_STAGE_BINDING_POLICY_ID
                ),
                schema_version=int(
                    payload.get("schemaVersion") or QUESTION_STAGE_BINDING_SCHEMA_VERSION
                ),
            )
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("questionStageBinding is malformed") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "questionStage": self.question_stage,
            "questionId": self.question_id,
            "questionRunId": self.question_run_id,
            "workflowRunId": self.workflow_run_id,
            "workflowId": self.workflow_id,
            "workflowVersionId": self.workflow_version_id,
            "formalNodeId": self.formal_node_id,
            "formalNodeRunId": self.formal_node_run_id,
            "formalNodeAttempt": self.formal_node_attempt,
            "sessionId": self.session_id,
            "taskId": self.task_id,
            "turnId": self.turn_id,
            "mappingPolicyId": self.mapping_policy_id,
        }


__all__ = [
    "QUESTION_PACKAGE_STAGES",
    "QUESTION_STAGE_BINDING_POLICY_ID",
    "QUESTION_STAGE_BINDING_SCHEMA_VERSION",
    "QuestionStageBinding",
]
