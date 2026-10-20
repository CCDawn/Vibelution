"""Bounded public advisor DTOs; commands never accept server-owned plan fields."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .investment import InvestmentProfile


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class WorkspaceStock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=24)
    ticker: str = Field(min_length=1, max_length=24)
    name: str = Field(min_length=1, max_length=60)
    market: str = Field(min_length=1, max_length=30)


class ManualPosition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=160)
    stock: WorkspaceStock
    quantity: float = Field(gt=0, le=1e12, allow_inf_nan=False)
    costPrice: float = Field(gt=0, le=1e8, allow_inf_nan=False)
    currency: Literal["CNY", "HKD", "USD"]
    note: str = Field(default="", max_length=500)


class InvestmentOrder(StrictModel):
    symbol: str = Field(min_length=1, max_length=24)
    side: Literal["buy", "sell"]
    quantity: int = Field(gt=0, le=1_000_000_000)


class PlanDraft(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    rationale: str = Field(min_length=1, max_length=2000)
    orders: list[InvestmentOrder] = Field(max_length=20)
    reviewAfter: str | None = Field(default=None, max_length=80)

    @field_validator("reviewAfter")
    @classmethod
    def valid_review_time(cls, value):
        if value is not None:
            from datetime import datetime

            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("reviewAfter 必须带时区")
        return value


class PlanSource(StrictModel):
    sessionId: str = Field(min_length=1, max_length=160)
    turnId: str = Field(min_length=1, max_length=160)


class InvestmentPlan(PlanDraft):
    id: str = Field(min_length=1, max_length=160)
    status: Literal["proposed", "adopted", "executed", "invalidated"]
    createdAt: str = Field(min_length=1, max_length=80)
    updatedAt: str = Field(min_length=1, max_length=80)
    source: PlanSource
    stateFingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    needsReview: bool = False


class ProfileProposal(StrictModel):
    kind: Literal["profile"]
    baseFingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile: InvestmentProfile


class PlanProposal(StrictModel):
    kind: Literal["plan"]
    baseFingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan: PlanDraft


Proposal = Annotated[ProfileProposal | PlanProposal, Field(discriminator="kind")]


class ProposalResponse(StrictModel):
    proposal: Proposal | None


class ConfirmProposal(StrictModel):
    action: Literal["confirm_proposal"]
    expectedRevision: int = Field(ge=0)
    sessionId: str = Field(min_length=1, max_length=160)
    turnId: str = Field(min_length=1, max_length=160)


class PlanCommand(StrictModel):
    action: Literal["adopt", "invalidate"]
    expectedRevision: int = Field(ge=0)
    planId: str = Field(min_length=1, max_length=160)


class ActualPosition(ManualPosition):
    """New execution commands stay strict without changing legacy PATCH parsing."""
    quantity: float = Field(gt=0, le=1e12, allow_inf_nan=False, strict=True)
    costPrice: float = Field(gt=0, le=1e8, allow_inf_nan=False, strict=True)
    currency: Literal["CNY"]

    @field_validator("quantity")
    @classmethod
    def whole_shares(cls, value):
        if not value.is_integer():
            raise ValueError("实际持仓股数必须是整数")
        return value


class ExecutePlan(StrictModel):
    action: Literal["execute"]
    expectedRevision: int = Field(ge=0)
    planId: str = Field(min_length=1, max_length=160)
    actualCashCny: float = Field(ge=0, le=1e8, allow_inf_nan=False)
    actualPositions: list[ActualPosition] = Field(max_length=50)


AdvisorCommand = Annotated[ConfirmProposal | PlanCommand | ExecutePlan, Field(discriminator="action")]


class PlanCheckRequest(StrictModel):
    planId: str = Field(min_length=1, max_length=160)


class CheckedOrder(StrictModel):
    symbol: str
    side: Literal["buy", "sell"]
    quantity: int
    priceCny: float
    quoteAsOf: str
    quoteSource: str | None
    notionalCny: float
    feesCny: float
    cashDeltaCny: float
    positionAfterQuantity: int
    positionAfterPct: float


class PlanCheckResponse(BaseModel):
    passed: bool
    blockers: list[str]
    warnings: list[str]
    cashAfterCny: float | None
    feesCny: float
    orders: list[CheckedOrder]
