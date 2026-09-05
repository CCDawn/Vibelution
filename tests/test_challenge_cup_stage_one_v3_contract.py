from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.research.workflow.contracts.challenge_cup_stage_one_v3 import (
    ActivityExecution,
    ActivityResult,
    Assessment,
    CommandReceiptV3,
    EvidenceRelation,
    EvidenceReview,
    Handoff,
    HandoffConsumer,
    HandoffDispatch,
    HandoffPayload,
    Provenance,
    RecordLifecycle,
    ScientificSemanticRecord,
)


def _provenance(**overrides: object) -> Provenance:
    payload: dict[str, object] = {
        "recordId": "assessment-1",
        "subjectRef": "hypothesis-1@r1",
        "generatedByActivityRef": "activity-review-1",
        "associatedAgentRef": "agent-reviewer-1",
        "agentType": "software_agent",
        "role": "policy_executor",
        "planRef": "policy-stage-one@3.0.0",
        "usedEvidenceRefs": ["evidence-1@sha256:abc"],
        "generatedAt": "2026-09-05T00:00:00Z",
    }
    payload.update(overrides)
    return Provenance.model_validate(payload)


def test_execution_rejects_completed_and_requires_terminal_reason_fields() -> None:
    with pytest.raises(ValidationError):
        ActivityExecution.model_validate({"status": "completed"})
    with pytest.raises(ValidationError):
        ActivityExecution.model_validate({"status": "failed"})
    with pytest.raises(ValidationError):
        ActivityExecution.model_validate({"status": "cancelled"})
    with pytest.raises(ValidationError):
        ActivityExecution.model_validate({"status": "timed_out"})

    assert ActivityExecution.model_validate(
        {"status": "failed", "failureReasonCode": "provider_error"}
    ).status == "failed"
    assert ActivityExecution.model_validate(
        {
            "status": "cancelled",
            "cancelledByAgentRef": "person-1",
            "terminationReasonCode": "operator_cancelled",
        }
    ).status == "cancelled"
    assert ActivityExecution.model_validate(
        {"status": "timed_out", "deadlineRef": "deadline-1"}
    ).status == "timed_out"


def test_result_allows_succeeded_empty_but_rejects_failed_empty() -> None:
    empty = ScientificSemanticRecord(
        execution=ActivityExecution(status="succeeded"),
        result=ActivityResult(completeness="empty", artifactRefs=[]),
    )
    assert empty.result.completeness == "empty"

    with pytest.raises(ValidationError):
        ScientificSemanticRecord(
            execution=ActivityExecution(
                status="failed", failureReasonCode="provider_error"
            ),
            result=ActivityResult(completeness="empty", artifactRefs=[]),
        )


@pytest.mark.parametrize("position", ["insufficient", "mixed"])
def test_review_budget_exhaustion_is_insufficient_or_mixed_escalate_only(
    position: str,
) -> None:
    record = ScientificSemanticRecord(
        execution=ActivityExecution(status="succeeded"),
        assessment=Assessment(
            state="completed",
            evidencePosition=position,
            workflowDisposition="escalate",
            reasonCode="review_budget_exhausted",
            bestSoFarRef="hypothesis-1@r3",
            unresolvedClaimRefs=["claim-2"],
            provenance=_provenance(),
        ),
    )
    assert record.assessment.workflowDisposition == "escalate"

    with pytest.raises(ValidationError):
        Assessment(
            state="completed",
            evidencePosition="supported",
            workflowDisposition="advance",
            reasonCode="review_budget_exhausted",
            provenance=_provenance(),
        )


def test_provenance_separates_agent_type_role_plan_and_evidence_refs() -> None:
    with pytest.raises(ValidationError):
        _provenance(agentType="software_agent", role="adjudicator")
    with pytest.raises(ValidationError):
        _provenance(role="policy_executor", planRef=None)
    with pytest.raises(ValidationError):
        _provenance(associatedAgentRef="policy-stage-one@3.0.0")

    person = _provenance(
        associatedAgentRef="person-operator-1",
        agentType="person",
        role="adjudicator",
        planRef="exception-policy@1",
    )
    assert person.agentType == "person"


def test_accepted_evidence_does_not_imply_supports_and_relation_requires_exact_claim() -> None:
    review = EvidenceReview(
        state="completed", admissibility="accepted", evidenceRef="evidence-1"
    )
    assert review.admissibility == "accepted"
    with pytest.raises(ValidationError):
        EvidenceRelation(type="supports", evidenceRef="evidence-1", claimRef="")
    relation = EvidenceRelation(
        type="refutes", evidenceRef="evidence-1", claimRef="claim-1"
    )
    assert relation.type == "refutes"


def test_command_receipt_distinguishes_rejected_failed_applied_and_replay() -> None:
    rejected = CommandReceiptV3(
        receiptRef="receipt-1",
        authorization="rejected",
        executionStatus="not_started",
        effect="no_change",
        idempotency="original",
        reasonCode="not_authorized",
    )
    assert rejected.effect == "no_change"

    with pytest.raises(ValidationError):
        CommandReceiptV3(
            receiptRef="receipt-2",
            authorization="rejected",
            executionStatus="succeeded",
            effect="applied",
            idempotency="original",
        )
    with pytest.raises(ValidationError):
        CommandReceiptV3(
            receiptRef="receipt-3",
            authorization="accepted",
            executionStatus="succeeded",
            effect="no_change",
            idempotency="replay",
        )

    replay = CommandReceiptV3(
        receiptRef="receipt-3",
        authorization="accepted",
        executionStatus="succeeded",
        effect="no_change",
        idempotency="replay",
        originalReceiptRef="receipt-2",
    )
    assert replay.originalReceiptRef == "receipt-2"


def test_handoff_is_complete_only_after_payload_dispatch_and_consumer_ack() -> None:
    pending = Handoff(
        payload=HandoffPayload(
            materializationStatus="succeeded", artifactRef="artifact-1"
        ),
        dispatch=HandoffDispatch(executionStatus="succeeded", receiptRef="dispatch-1"),
        consumer=HandoffConsumer(status="not_started"),
    )
    assert pending.complete is False

    complete = pending.model_copy(
        update={
            "consumer": HandoffConsumer(
                status="acknowledged", activityRef="consumer-activity-1"
            )
        }
    )
    assert complete.complete is True


def test_archiving_and_replacing_record_never_rewrites_scientific_facts() -> None:
    failed = ScientificSemanticRecord(
        execution=ActivityExecution(
            status="failed", failureReasonCode="provider_error"
        ),
        record=RecordLifecycle(
            availability="archived", replacedByRef="activity-2"
        ),
    )
    assert failed.execution.status == "failed"
    assert failed.record.availability == "archived"

    with pytest.raises(ValidationError):
        RecordLifecycle.model_validate(
            {"availability": "active", "retentionState": "superseded"}
        )


def test_supported_advance_requires_accepted_evidence_and_complete_provenance() -> None:
    with pytest.raises(ValidationError):
        ScientificSemanticRecord(
            execution=ActivityExecution(status="succeeded"),
            assessment=Assessment(
                state="completed",
                evidencePosition="supported",
                workflowDisposition="advance",
                provenance=_provenance(usedEvidenceRefs=[]),
            ),
            evidenceReviews=[
                EvidenceReview(
                    state="completed",
                    admissibility="undetermined",
                    evidenceRef="evidence-1@sha256:abc",
                )
            ],
            evidenceRelations=[
                EvidenceRelation(
                    type="supports",
                    evidenceRef="evidence-1@sha256:abc",
                    claimRef="claim-1",
                )
            ],
        )


def test_failed_execution_cannot_be_projected_as_scientific_stop() -> None:
    with pytest.raises(ValidationError):
        ScientificSemanticRecord(
            execution=ActivityExecution(
                status="failed", failureReasonCode="provider_error"
            ),
            assessment=Assessment(
                state="completed",
                evidencePosition="contradicted",
                workflowDisposition="stop",
                reasonCode="execution_failed",
                provenance=_provenance(),
            ),
        )


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (ActivityExecution, {"status": "succeeded", "outcome": "accepted"}),
        (
            Assessment,
            {
                "state": "completed",
                "evidencePosition": "supported",
                "workflowDisposition": "advance",
                "decisionOrigin": "human",
                "provenance": _provenance().model_dump(by_alias=True),
            },
        ),
        (
            CommandReceiptV3,
            {
                "receiptRef": "r1",
                "authorization": "accepted",
                "executionStatus": "succeeded",
                "effect": "applied",
                "idempotency": "original",
                "operationOutcome": "success",
            },
        ),
        (
            Handoff,
            {
                "payload": {"materializationStatus": "not_started"},
                "dispatch": {"executionStatus": "not_started"},
                "consumer": {"status": "not_started"},
                "handoffStatus": "pending",
            },
        ),
    ],
)
def test_v3_contract_rejects_every_legacy_authority_field(
    model: type, payload: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)
