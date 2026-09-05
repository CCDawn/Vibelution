"""Strict Challenge Cup scientific semantics for the 3.0.0 workflow.

The models deliberately reject V1/V2 aliases.  They describe orthogonal facts;
they do not infer a single overall ``status`` or repair persisted payloads.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


ExecutionStatus = Literal[
    "not_started",
    "scheduled",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
]
WaitReason = Literal["human_input", "system_work", "dependency", "retry_backoff"]


class ActivityExecution(_StrictModel):
    status: ExecutionStatus
    waitReason: WaitReason | None = None
    failureReasonCode: str | None = None
    cancelledByAgentRef: str | None = None
    terminationReasonCode: str | None = None
    deadlineRef: str | None = None

    @model_validator(mode="after")
    def validate_status_details(self) -> ActivityExecution:
        if self.waitReason is not None and self.status != "running":
            raise ValueError("waitReason is valid only while execution is running")
        if self.status == "failed" and not self.failureReasonCode:
            raise ValueError("failed execution requires failureReasonCode")
        if self.status == "cancelled" and not (
            self.cancelledByAgentRef and self.terminationReasonCode
        ):
            raise ValueError(
                "cancelled execution requires cancelledByAgentRef and terminationReasonCode"
            )
        if self.status == "timed_out" and not self.deadlineRef:
            raise ValueError("timed_out execution requires deadlineRef")
        if self.status != "failed" and self.failureReasonCode is not None:
            raise ValueError("failureReasonCode is valid only for failed execution")
        if self.status != "cancelled" and (
            self.cancelledByAgentRef is not None
            or self.terminationReasonCode is not None
        ):
            raise ValueError("cancellation details are valid only for cancelled execution")
        if self.status != "timed_out" and self.deadlineRef is not None:
            raise ValueError("deadlineRef is valid only for timed_out execution")
        return self


class ActivityResult(_StrictModel):
    completeness: Literal["not_produced", "complete", "partial", "empty"]
    artifactRefs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_artifacts(self) -> ActivityResult:
        if any(not ref.strip() for ref in self.artifactRefs):
            raise ValueError("artifactRefs must contain non-empty canonical refs")
        if self.completeness in {"not_produced", "empty"} and self.artifactRefs:
            raise ValueError(f"{self.completeness} result cannot contain artifactRefs")
        if self.completeness in {"complete", "partial"} and not self.artifactRefs:
            raise ValueError(f"{self.completeness} result requires artifactRefs")
        return self


class Provenance(_StrictModel):
    recordId: str = Field(min_length=1)
    subjectRef: str = Field(min_length=1)
    generatedByActivityRef: str = Field(min_length=1)
    associatedAgentRef: str = Field(min_length=1)
    agentType: Literal["person", "software_agent"]
    role: Literal["reviewer", "adjudicator", "policy_executor", "gate_evaluator"]
    planRef: str | None = None
    usedEvidenceRefs: tuple[str, ...]
    generatedAt: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_qualified_association(self) -> Provenance:
        if self.agentType == "software_agent" and self.role == "adjudicator":
            raise ValueError("software_agent cannot claim person adjudicator authority")
        if self.agentType == "person" and self.role in {
            "policy_executor",
            "gate_evaluator",
        }:
            raise ValueError("person cannot claim automated policy or gate role")
        if self.role in {"policy_executor", "gate_evaluator"} and not self.planRef:
            raise ValueError(f"{self.role} requires planRef")
        if self.associatedAgentRef.lower().startswith(("policy-", "gate-", "plan-")):
            raise ValueError("a Plan reference cannot be used as associatedAgentRef")
        if self.planRef and self.associatedAgentRef == self.planRef:
            raise ValueError("Agent and Plan must be distinct references")
        if any(not ref.strip() for ref in self.usedEvidenceRefs):
            raise ValueError("usedEvidenceRefs must contain non-empty refs")
        return self


class Assessment(_StrictModel):
    state: Literal["not_started", "running", "completed"]
    evidencePosition: Literal[
        "supported", "contradicted", "mixed", "insufficient"
    ] | None = None
    workflowDisposition: Literal["advance", "revise", "escalate", "stop"] | None = None
    reasonCode: str | None = None
    returnToNodeId: str | None = None
    revisionScope: str | None = None
    bestSoFarRef: str | None = None
    unresolvedClaimRefs: tuple[str, ...] = ()
    provenance: Provenance | None = None

    @model_validator(mode="after")
    def validate_assessment(self) -> Assessment:
        decision_fields_present = any(
            value is not None
            for value in (
                self.evidencePosition,
                self.workflowDisposition,
                self.reasonCode,
                self.returnToNodeId,
                self.revisionScope,
                self.bestSoFarRef,
                self.provenance,
            )
        ) or bool(self.unresolvedClaimRefs)
        if self.state != "completed":
            if decision_fields_present:
                raise ValueError("unfinished assessment cannot contain a decision")
            return self
        if not (self.evidencePosition and self.workflowDisposition and self.provenance):
            raise ValueError(
                "completed assessment requires evidencePosition, workflowDisposition, and provenance"
            )
        if self.workflowDisposition != "advance" and not self.reasonCode:
            raise ValueError("non-advance disposition requires reasonCode")
        if self.workflowDisposition == "advance" and self.reasonCode is not None:
            raise ValueError("advance disposition cannot contain reasonCode")
        if self.workflowDisposition == "revise" and not (
            self.returnToNodeId and self.revisionScope
        ):
            raise ValueError("revise requires returnToNodeId and revisionScope")
        if self.workflowDisposition != "revise" and (
            self.returnToNodeId is not None or self.revisionScope is not None
        ):
            raise ValueError(
                "returnToNodeId and revisionScope are valid only for revise"
            )
        if self.workflowDisposition != "escalate" and (
            self.bestSoFarRef is not None or self.unresolvedClaimRefs
        ):
            raise ValueError(
                "bestSoFarRef and unresolvedClaimRefs are valid only for escalate"
            )
        if self.reasonCode == "review_budget_exhausted":
            if self.evidencePosition not in {"insufficient", "mixed"}:
                raise ValueError(
                    "review budget exhaustion requires insufficient or mixed evidence"
                )
            if self.workflowDisposition != "escalate":
                raise ValueError("review budget exhaustion must escalate")
            if not self.bestSoFarRef or not self.unresolvedClaimRefs:
                raise ValueError(
                    "review budget exhaustion requires bestSoFarRef and unresolvedClaimRefs"
                )
        return self


class EvidenceReview(_StrictModel):
    state: Literal["not_started", "running", "completed"]
    admissibility: Literal[
        "accepted", "revision_required", "rejected", "not_assessable"
    ] | None = None
    evidenceRef: str = Field(min_length=1)
    reasonCode: str | None = None

    @model_validator(mode="after")
    def validate_review(self) -> EvidenceReview:
        if self.state == "completed" and self.admissibility is None:
            raise ValueError("completed evidence review requires admissibility")
        if self.state != "completed" and (
            self.admissibility is not None or self.reasonCode is not None
        ):
            raise ValueError(
                "unfinished evidence review cannot set admissibility or reasonCode"
            )
        if self.state == "completed" and self.admissibility == "accepted":
            if self.reasonCode is not None:
                raise ValueError("accepted evidence cannot contain reasonCode")
        elif self.state == "completed" and not self.reasonCode:
            raise ValueError("non-accepted evidence review requires reasonCode")
        return self


class EvidenceRelation(_StrictModel):
    type: Literal["supports", "refutes", "qualifies", "disputes"]
    claimRef: str = Field(min_length=1)
    evidenceRef: str = Field(min_length=1)


class CommandReceiptV3(_StrictModel):
    receiptRef: str = Field(min_length=1)
    authorization: Literal["accepted", "rejected"]
    executionStatus: Literal["succeeded", "failed", "not_started"]
    effect: Literal["applied", "no_change", "unknown"]
    idempotency: Literal["original", "replay"]
    originalReceiptRef: str | None = None
    reasonCode: str | None = None

    @model_validator(mode="after")
    def validate_receipt(self) -> CommandReceiptV3:
        if self.authorization == "rejected":
            if self.executionStatus != "not_started" or self.effect != "no_change":
                raise ValueError(
                    "rejected command must be not_started with no_change effect"
                )
            if not self.reasonCode:
                raise ValueError("rejected command requires reasonCode")
        if self.executionStatus == "not_started" and self.effect != "no_change":
            raise ValueError("not_started command cannot have an effect")
        if self.executionStatus == "failed" and self.effect == "applied":
            raise ValueError("failed command cannot claim an applied effect")
        if self.effect == "unknown" and self.executionStatus != "failed":
            raise ValueError("unknown effect is allowed only after failed execution")
        if self.idempotency == "replay":
            if not self.originalReceiptRef:
                raise ValueError("replay requires originalReceiptRef")
            if (
                self.authorization != "accepted"
                or self.executionStatus != "succeeded"
                or self.effect != "no_change"
            ):
                raise ValueError(
                    "replay must return accepted/succeeded/no_change semantics"
                )
        elif self.originalReceiptRef is not None:
            raise ValueError("originalReceiptRef is valid only for replay")
        return self


class HandoffPayload(_StrictModel):
    materializationStatus: Literal["not_started", "succeeded", "failed"]
    artifactRef: str | None = None
    reasonCode: str | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> HandoffPayload:
        if self.materializationStatus == "succeeded" and not self.artifactRef:
            raise ValueError("succeeded payload materialization requires artifactRef")
        if self.materializationStatus != "succeeded" and self.artifactRef is not None:
            raise ValueError("artifactRef is valid only for succeeded materialization")
        if self.materializationStatus == "failed" and not self.reasonCode:
            raise ValueError("failed payload materialization requires reasonCode")
        if self.materializationStatus != "failed" and self.reasonCode is not None:
            raise ValueError(
                "payload reasonCode is valid only for failed materialization"
            )
        return self


class HandoffDispatch(_StrictModel):
    executionStatus: Literal["not_started", "succeeded", "failed"]
    receiptRef: str | None = None
    reasonCode: str | None = None

    @model_validator(mode="after")
    def validate_dispatch(self) -> HandoffDispatch:
        if self.executionStatus == "succeeded" and not self.receiptRef:
            raise ValueError("succeeded dispatch requires receiptRef")
        if self.executionStatus != "succeeded" and self.receiptRef is not None:
            raise ValueError("receiptRef is valid only for succeeded dispatch")
        if self.executionStatus == "failed" and not self.reasonCode:
            raise ValueError("failed dispatch requires reasonCode")
        if self.executionStatus != "failed" and self.reasonCode is not None:
            raise ValueError(
                "dispatch reasonCode is valid only for failed execution"
            )
        return self


class HandoffConsumer(_StrictModel):
    status: Literal["not_started", "acknowledged", "rejected"]
    activityRef: str | None = None
    reasonCode: str | None = None

    @model_validator(mode="after")
    def validate_consumer(self) -> HandoffConsumer:
        if self.status in {"acknowledged", "rejected"} and not self.activityRef:
            raise ValueError(f"{self.status} consumer requires activityRef")
        if self.status == "not_started" and self.activityRef is not None:
            raise ValueError("not_started consumer cannot have activityRef")
        if self.status == "rejected" and not self.reasonCode:
            raise ValueError("rejected consumer requires reasonCode")
        if self.status != "rejected" and self.reasonCode is not None:
            raise ValueError("consumer reasonCode is valid only for rejected status")
        return self


class Handoff(_StrictModel):
    payload: HandoffPayload
    dispatch: HandoffDispatch
    consumer: HandoffConsumer
    applicability: Literal["applicable", "not_applicable"] = "applicable"

    @model_validator(mode="after")
    def validate_sequence(self) -> Handoff:
        if self.dispatch.executionStatus != "not_started" and (
            self.payload.materializationStatus != "succeeded"
        ):
            raise ValueError("dispatch cannot start before payload materialization")
        if self.consumer.status != "not_started" and (
            self.dispatch.executionStatus != "succeeded"
        ):
            raise ValueError("consumer cannot respond before dispatch succeeds")
        if self.applicability == "not_applicable" and (
            self.payload.materializationStatus != "not_started"
            or self.dispatch.executionStatus != "not_started"
            or self.consumer.status != "not_started"
        ):
            raise ValueError("not_applicable handoff must keep all three stages not_started")
        return self

    @computed_field
    @property
    def complete(self) -> bool:
        return (
            self.applicability == "applicable"
            and self.payload.materializationStatus == "succeeded"
            and self.dispatch.executionStatus == "succeeded"
            and self.consumer.status == "acknowledged"
        )


class RecordLifecycle(_StrictModel):
    availability: Literal["active", "archived"]
    revisionOfRef: str | None = None
    replacedByRef: str | None = None
    invalidatedAt: str | None = None

class ScientificSemanticRecord(_StrictModel):
    execution: ActivityExecution | None = None
    result: ActivityResult | None = None
    assessment: Assessment | None = None
    evidenceReviews: tuple[EvidenceReview, ...] = ()
    evidenceRelations: tuple[EvidenceRelation, ...] = ()
    commandReceipt: CommandReceiptV3 | None = None
    handoff: Handoff | None = None
    record: RecordLifecycle | None = None

    @model_validator(mode="after")
    def validate_cross_object_invariants(self) -> ScientificSemanticRecord:
        if self.execution and self.result:
            if self.execution.status == "succeeded" and (
                self.result.completeness == "not_produced"
            ):
                raise ValueError(
                    "succeeded execution must explicitly report complete, partial, or empty result"
                )
            if self.execution.status == "failed" and self.result.completeness not in {
                "not_produced",
                "partial",
            }:
                raise ValueError(
                    "failed execution result must be not_produced or partial"
                )
            if self.execution.status not in {
                "succeeded",
                "failed",
                "cancelled",
                "timed_out",
            } and self.result.completeness in {"complete", "empty"}:
                raise ValueError("non-terminal execution cannot have a terminal result")
        if (
            self.execution
            and self.execution.status in {"failed", "cancelled", "timed_out"}
            and self.assessment
            and self.assessment.state == "completed"
        ):
            raise ValueError(
                "execution termination cannot be projected as a scientific assessment"
            )
        if (
            self.assessment
            and self.assessment.state == "completed"
            and self.assessment.evidencePosition == "supported"
            and self.assessment.workflowDisposition == "advance"
        ):
            provenance = self.assessment.provenance
            used_refs = set(provenance.usedEvidenceRefs if provenance else ())
            accepted_refs = {
                review.evidenceRef
                for review in self.evidenceReviews
                if review.state == "completed" and review.admissibility == "accepted"
            }
            supporting_refs = {
                relation.evidenceRef
                for relation in self.evidenceRelations
                if relation.type == "supports"
            }
            if not used_refs or not used_refs.issubset(accepted_refs & supporting_refs):
                raise ValueError(
                    "supported advance requires accepted, claim-scoped supporting evidence"
                )
        return self


__all__ = [
    "ActivityExecution",
    "ActivityResult",
    "Assessment",
    "CommandReceiptV3",
    "EvidenceRelation",
    "EvidenceReview",
    "Handoff",
    "HandoffConsumer",
    "HandoffDispatch",
    "HandoffPayload",
    "Provenance",
    "RecordLifecycle",
    "ScientificSemanticRecord",
]
