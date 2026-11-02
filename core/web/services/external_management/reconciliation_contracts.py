"""Bounded reconciliation metadata without request bodies or native replay."""
from typing import Literal
from pydantic import Field, field_validator, model_validator
from .runtime_contracts import RuntimeClosed, RuntimeUntrusted

PUBLIC_REFERENCE_FIELDS = frozenset({"kind", "resource_id", "session_id", "team_id", "flow_id", "run_id", "node_id", "task_id",
    "agent_id", "knowledge_base_id", "target_agent_id", "checkpoint_id"})


class ReconciliationQuery(RuntimeClosed):
    action: str = Field(pattern=r"^[a-z][a-z_]{0,79}$")
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")


class ReconciliationResponse(RuntimeUntrusted):
    action: str = Field(pattern=r"^[a-z][a-z_]{0,79}$")
    requestId: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")
    state: Literal["confirmed", "requires_review", "unavailable"]
    evidence: Literal["native_outcome", "research_ledger", "flow_start_identity", "management_receipt", "none"]
    code: Literal["NATIVE_OUTCOME_CONFIRMED", "NATIVE_OUTCOME_REQUIRES_REVIEW", "NATIVE_OUTCOME_UNAVAILABLE", "MANAGEMENT_RECEIPT_CONFIRMED"]
    verified: bool
    requiresReview: bool
    target: dict[str, str] = Field(max_length=12)

    @field_validator("target")
    @classmethod
    def metadata_only(cls, value):
        if set(value) - PUBLIC_REFERENCE_FIELDS or any(not item or len(item) > 320 or any(ord(c) < 32 for c in item) for item in value.values()):
            raise ValueError("Only bounded object references are public")
        return value

    @model_validator(mode="after")
    def coherent_proof(self):
        confirmed = self.state == "confirmed"
        if (self.verified != confirmed or self.requiresReview == confirmed
                or confirmed != (self.evidence != "none")
                or confirmed != (self.code in {"NATIVE_OUTCOME_CONFIRMED", "MANAGEMENT_RECEIPT_CONFIRMED"})):
            raise ValueError("Reconciliation cannot claim an unproved result")
        return self
