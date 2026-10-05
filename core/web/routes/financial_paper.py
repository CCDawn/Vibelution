"""Typed, isolated paper-account API for financial Agents."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.web.services import financial_market_service as market
from core.web.services import financial_paper_service as paper
from core.web.services.agent_directory_service import (
    AgentDirectoryError,
    AgentNotFoundError,
    AgentStateConflictError,
)
from core.web.services.runtime_scene_service import record_runtime_scene_event_quietly

router = APIRouter(tags=["financial-paper"])
_EMPTY_ACCOUNT_OPEN_BODY = Body(default=None)


class PaperFeePolicyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    commissionRate: str
    minimumCommissionYuan: str
    sellStampDutyRate: str
    transferFeeIncluded: bool
    description: str


class PaperPositionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    ticker: str
    name: str
    market: str
    quantity: int
    availableQuantity: int
    frozenQuantity: int
    averageCostYuan: str
    costBasisYuan: str
    markPriceYuan: str | None
    marketValueYuan: str | None
    unrealizedPnlYuan: str | None
    valuationStatus: Literal["fresh", "stale", "unavailable"]
    quoteTimestamp: str
    quoteDate: str
    quoteFetchedAt: str
    source: str
    sourceUrl: str


class PaperOrderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    orderId: str
    clientOrderId: str
    symbol: str
    ticker: str
    name: str
    market: str
    side: Literal["buy", "sell"]
    quantity: int
    priceYuan: str
    grossAmountYuan: str
    commissionYuan: str
    stampDutyYuan: str
    totalFeeYuan: str
    cashChangeYuan: str
    realizedPnlYuan: str
    reason: str
    createdAt: str
    beijingDate: str
    quoteSource: str
    quoteSourceUrl: str
    quoteTimestamp: str
    quoteDate: str
    quoteFetchedAt: str
    priceNotice: str


class PaperAccountResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agentId: str
    accountId: str
    openedAt: str
    initialCashYuan: str
    cashYuan: str
    marketValueYuan: str
    equityYuan: str
    realizedPnlYuan: str
    unrealizedPnlYuan: str
    totalPnlYuan: str
    totalFeesYuan: str
    valuationStatus: Literal["fresh", "partial"]
    valuationNotice: str
    positions: list[PaperPositionResponse]
    orders: list[PaperOrderResponse]
    ordersTotal: int
    ordersLimit: int
    ordersTruncated: bool
    feePolicy: PaperFeePolicyResponse
    tPlusOneRule: str
    simulationOnly: Literal[True]


class PaperAccountOpenRequest(BaseModel):
    """Strict empty object: virtual balance is always fixed by the server."""

    model_config = ConfigDict(extra="forbid")


class PaperOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    clientOrderId: UUID
    symbol: str = Field(min_length=6, max_length=8)
    side: Literal["buy", "sell"]
    quantity: int = Field(ge=100, le=1_000_000, multiple_of=100)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def reason_must_contain_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("请填写模拟交易理由")
        return value.strip()


class PaperReviewSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    totalTradeCount: int
    buyCount: int
    sellCount: int
    winningSellCount: int
    allTimeRealizedPnlYuan: str
    allTimeFeesYuan: str
    monthTradeCount: int
    monthRealizedPnlYuan: str
    monthFeesYuan: str


class PaperReviewDayResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: str
    tradeCount: int
    buyCount: int
    sellCount: int
    buyAmountYuan: str
    sellAmountYuan: str
    feesYuan: str
    realizedPnlYuan: str


class PaperReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account: PaperAccountResponse
    month: str
    days: list[PaperReviewDayResponse]
    summary: PaperReviewSummaryResponse
    feePolicy: PaperFeePolicyResponse
    tPlusOneRule: str
    simulationOnly: Literal[True]


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, paper.AccountNotOpenedError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(
        exc,
        (
            AgentStateConflictError,
            paper.PaperAccountConflictError,
            paper.IdempotencyConflictError,
        ),
    ):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, AgentNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, market.MarketDataError):
        return HTTPException(status_code=502, detail=str(exc))
    if isinstance(exc, (paper.FinancialPaperError, AgentDirectoryError)):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail="模拟账本暂时不可用")


@router.get("/financial-paper/{agentId}", response_model=PaperAccountResponse)
def financial_paper_account(
    agentId: str,
    orderLimit: int = Query(default=50, ge=1, le=200),
) -> dict:
    try:
        return paper.get_account_snapshot(agentId, order_limit=orderLimit)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/financial-paper/{agentId}/account", response_model=PaperAccountResponse)
def financial_paper_account_open(
    agentId: str,
    _payload: PaperAccountOpenRequest | None = _EMPTY_ACCOUNT_OPEN_BODY,
) -> dict:
    try:
        return paper.open_account(agentId)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/financial-paper/{agentId}/orders", response_model=PaperAccountResponse)
def financial_paper_order(agentId: str, payload: PaperOrderRequest) -> dict:
    try:
        return paper.submit_order(
            agentId,
            client_order_id=str(payload.clientOrderId),
            symbol=payload.symbol,
            side=payload.side,
            quantity=payload.quantity,
            reason=payload.reason,
        )
    except Exception as exc:
        record_runtime_scene_event_quietly(
            "finance",
            "paper_order",
            "finance.paper_order.rejected",
            outcome="rejected",
            level="warning",
            fields={
                "agentId": agentId[:80],
                "clientOrderId": str(payload.clientOrderId),
                "reason": type(exc).__name__,
                "simulationOnly": True,
            },
        )
        raise _http_error(exc) from exc


@router.get("/financial-paper/{agentId}/review", response_model=PaperReviewResponse)
def financial_paper_review(
    agentId: str,
    month: str = Query(
        min_length=7, max_length=7, pattern=r"^\d{4}-(?:0[1-9]|1[0-2])$"
    ),
) -> dict:
    try:
        return paper.get_review_snapshot(agentId, month=month)
    except Exception as exc:
        raise _http_error(exc) from exc
