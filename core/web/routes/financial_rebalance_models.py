"""Additive JSON contracts for research-linked paper portfolio proposals."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class RebalancePolicy(_StrictModel):
    maxPositionPct: float = Field(default=30, ge=1, le=100, strict=True)
    minCashPct: float = Field(default=10, ge=0, le=100, strict=True)
    maxTurnoverPct: float = Field(default=100, ge=0, le=200, strict=True)
    maxQuoteAgeHours: float = Field(default=72, ge=1, le=168, strict=True)


class RebalanceReportRef(_StrictModel):
    sessionId: str = Field(min_length=1, max_length=160)
    turnId: str = Field(min_length=1, max_length=160)


class RebalanceSource(RebalanceReportRef):
    contentHash: str


class RebalanceTarget(_StrictModel):
    symbol: str = Field(min_length=1, max_length=16)
    weightPct: float = Field(ge=0, le=100, strict=True)
    reason: str = Field(min_length=1, max_length=500)


class RebalanceCreateRequest(_StrictModel):
    clientRequestId: UUID
    symbols: list[str] = Field(min_length=1, max_length=10)
    reports: list[RebalanceReportRef] = Field(min_length=1, max_length=5)
    instruction: str = Field(min_length=1, max_length=2000)
    policy: RebalancePolicy = Field(default_factory=RebalancePolicy)


class RebalancePreviewRequest(_StrictModel):
    targets: list[RebalanceTarget] = Field(min_length=1, max_length=20)
    policy: RebalancePolicy


class RebalanceApproveRequest(_StrictModel):
    planHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmSimulation: Literal[True]


class RebalanceCheck(_StrictModel):
    code: str
    label: str
    passed: bool
    detail: str


class RebalanceOrder(_StrictModel):
    symbol: str
    name: str
    side: Literal["buy", "sell"]
    quantity: int = Field(ge=100)
    priceYuan: str
    grossAmountYuan: str
    feeYuan: str
    reason: str


class RebalanceMetrics(_StrictModel):
    equityYuan: str
    cashAfterYuan: str
    turnoverPct: str
    feesYuan: str


class RebalanceExecution(_StrictModel):
    batchId: str
    executedAt: str


class RebalanceProposal(_StrictModel):
    proposalId: str
    agentId: str
    status: Literal["generating", "ready", "blocked", "failed", "executed"]
    createdAt: str
    expiresAt: str
    modelId: str
    reportRefs: list[RebalanceSource]
    targets: list[RebalanceTarget]
    summaryReason: str
    riskChecks: list[RebalanceCheck]
    orders: list[RebalanceOrder]
    metrics: RebalanceMetrics
    policy: RebalancePolicy
    planHash: str
    error: str | None
    execution: RebalanceExecution | None


class RebalanceProposalPage(_StrictModel):
    items: list[RebalanceProposal]
