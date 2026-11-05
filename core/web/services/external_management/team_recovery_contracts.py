"""Additive Team recovery views; existing runtime command wire stays closed."""
import unicodedata
from typing import Literal

from pydantic import Field, field_validator

from .runtime_contracts import RuntimeClosed, RuntimeUntrusted, _ID, _OPTIONAL_ID

RecoveryStatus = Literal["tracking", "retrying", "repairing", "awaiting_deployment",
    "awaiting_replay_decision", "replaying", "resolved", "blocked", "cancelled"]


class TeamRecoveryQuery(RuntimeClosed):
    team_id: str = Field(pattern=_ID, max_length=96)
    flow_id: str = Field(pattern=_ID, max_length=96)
    run_id: str = Field(pattern=_ID, max_length=96)


class TeamRecoveryConfirmDeployment(TeamRecoveryQuery):
    expected_revision: str = Field(pattern=r"^[0-9]{1,19}$")
    evidence_ref: str = Field(min_length=1, max_length=500)

    @field_validator("evidence_ref")
    @classmethod
    def explicit_evidence(cls, value):
        if not value.strip() or any(unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for char in value):
            raise ValueError("An explicit, displayable deployment evidence reference is required")
        return value


class TeamRecoveryMetadata(RuntimeClosed):
    issueId: str = Field(pattern=_ID)
    nodeId: str = Field(pattern=_ID)
    status: RecoveryStatus
    reason: str = Field(default="", pattern=r"^[A-Za-z0-9_-]{0,159}$")
    failureCount: int = Field(ge=0, le=2**63 - 1)
    repairAttempts: int = Field(ge=0, le=2**63 - 1)
    repairRunId: str = Field(default="", pattern=_OPTIONAL_ID)
    codeRepairRunId: str = Field(default="", pattern=_OPTIONAL_ID)
    evidenceCount: int = Field(ge=0, le=20)
    evidenceDigest: str = Field(pattern=r"^[a-f0-9]{64}$")


class TeamRecoveryResponse(RuntimeUntrusted):
    teamId: str = Field(pattern=_ID)
    flowId: str = Field(pattern=_ID)
    runId: str = Field(pattern=_ID)
    revision: str = Field(pattern=r"^[0-9]{1,19}$")
    runStatus: Literal["running", "waiting", "completed", "failed", "stopped"]
    recovery: TeamRecoveryMetadata | None
    commands: list[Literal["confirm_deployment"]] = Field(max_length=1)
    businessAcceptance: Literal["not_evaluated"] = "not_evaluated"


class TeamRecoveryDeploymentResponse(TeamRecoveryResponse):
    command: Literal["confirm_deployment"]
    accepted: Literal[True]
    evidenceDigest: str = Field(pattern=r"^[a-f0-9]{64}$")
    revisionCheck: Literal["native_cas"]
