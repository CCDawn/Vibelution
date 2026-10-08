"""Read-only portfolio research over an Agent's simulated holdings."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core.web.services import financial_market_service as market
from core.web.services import financial_paper_service as paper
from core.web.services import financial_portfolio_service as service
from core.web.services import financial_rebalance_service as rebalance
from core.web.services import financial_report_service as reports
from core.web.services.agent_directory_service import (
    AgentDirectoryError,
    AgentNotFoundError,
)
from core.web.services.financial_rebalance.risk import RebalanceError

from .financial_rebalance_models import (
    RebalanceApproveRequest,
    RebalanceCreateRequest,
    RebalancePreviewRequest,
    RebalanceProposal,
    RebalanceProposalPage,
)

router = APIRouter(tags=["financial-portfolio"])


def _proposal_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (paper.PaperAccountConflictError, paper.IdempotencyConflictError)):
        code = 409
    elif isinstance(exc, (paper.AccountNotOpenedError, AgentNotFoundError, reports.FinancialReportNotFound)):
        code = 404
    elif isinstance(exc, market.MarketDataError):
        code = 502
    else:
        code = getattr(exc, "status_code", 422)
    return HTTPException(status_code=code, detail=str(exc))


_PROPOSAL_ERRORS = (RebalanceError, paper.FinancialPaperError, AgentDirectoryError, market.MarketDataError, reports.FinancialReportExportError)


@router.get("/financial-portfolios/{agentId}/proposals", response_model=RebalanceProposalPage)
def list_portfolio_proposals(agentId: str) -> dict:
    try:
        return rebalance.list_proposals(agentId)
    except _PROPOSAL_ERRORS as exc:
        raise _proposal_error(exc) from exc


@router.post("/financial-portfolios/{agentId}/proposals", response_model=RebalanceProposal)
def create_portfolio_proposal(agentId: str, payload: RebalanceCreateRequest) -> dict:
    try:
        return rebalance.create_proposal(agentId, payload.model_dump(mode="json"))
    except _PROPOSAL_ERRORS as exc:
        raise _proposal_error(exc) from exc


@router.get("/financial-portfolios/{agentId}/proposals/{proposalId}", response_model=RebalanceProposal)
def get_portfolio_proposal(agentId: str, proposalId: str) -> dict:
    try:
        return rebalance.get_proposal(agentId, proposalId)
    except _PROPOSAL_ERRORS as exc:
        raise _proposal_error(exc) from exc


@router.post("/financial-portfolios/{agentId}/proposals/{proposalId}/preview", response_model=RebalanceProposal)
def preview_portfolio_proposal(agentId: str, proposalId: str, payload: RebalancePreviewRequest) -> dict:
    try:
        return rebalance.preview_proposal(agentId, proposalId, payload.model_dump())
    except _PROPOSAL_ERRORS as exc:
        raise _proposal_error(exc) from exc


@router.post("/financial-portfolios/{agentId}/proposals/{proposalId}/approve", response_model=RebalanceProposal)
def approve_portfolio_proposal(agentId: str, proposalId: str, payload: RebalanceApproveRequest) -> dict:
    try:
        return rebalance.approve_proposal(agentId, proposalId, payload.model_dump())
    except _PROPOSAL_ERRORS as exc:
        raise _proposal_error(exc) from exc


class FinancialPortfolioSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    equityYuan: str | None
    cashYuan: str | None
    marketValueYuan: str | None
    cashWeightPercent: str | None
    positionCount: int = Field(ge=0)
    valuedPositionCount: int = Field(ge=0)
    valuationComplete: bool
    maxPositionWeightPercent: str | None
    topThreeWeightPercent: str | None
    correlationPairCount: int = Field(ge=0)
    highCorrelationPairCount: int = Field(ge=0)
    insufficientCorrelationPairCount: int = Field(ge=0)
    unavailableCorrelationPairCount: int = Field(ge=0)


class FinancialPortfolioPositionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    ticker: str
    name: str
    market: str
    quantity: int = Field(ge=0)
    markPriceYuan: str | None
    marketValueYuan: str | None
    unrealizedPnlYuan: str | None
    weightPercent: str | None
    valuationStatus: Literal["fresh", "stale", "unavailable"]
    quoteTimestamp: str
    quoteFetchedAt: str
    source: str
    sourceUrl: str
    returnSeriesStatus: Literal[
        "available",
        "unavailable",
        "deadline",
        "capacity_skipped",
        "limit_skipped",
        "not_valued",
    ]


class FinancialPortfolioCorrelationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    firstSymbol: str
    firstName: str
    secondSymbol: str
    secondName: str
    correlation: float = Field(ge=-1, le=1)
    observations: int = Field(ge=0)
    startDate: str
    endDate: str


class FinancialPortfolioCoverageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    eligiblePositionCount: int = Field(ge=0)
    selectedPositionCount: int = Field(ge=0)
    candleLoadedPositionCount: int = Field(ge=0)
    candleUnavailablePositionCount: int = Field(ge=0)
    budgetSkippedPositionCount: int = Field(ge=0)
    capacitySkippedPositionCount: int = Field(ge=0)
    deadlineSkippedPositionCount: int = Field(ge=0)
    unvaluedPositionCount: int = Field(ge=0)
    maxAnalyzedPositions: int = Field(ge=0)
    maxConcurrentFetches: int = Field(ge=0)
    deadlineSeconds: float = Field(ge=0)
    minimumCorrelationObservations: int = Field(ge=2)
    analyzedSymbols: list[str]
    budgetSkippedSymbols: list[str]
    unavailableSymbols: list[str]


class FinancialPortfolioResearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agentId: str
    accountId: str
    generatedAt: str
    source: str
    sourceUrl: str
    adjustment: Literal["qfq"]
    period: Literal["day"]
    simulationOnly: Literal[True]
    summary: FinancialPortfolioSummaryResponse
    positions: list[FinancialPortfolioPositionResponse]
    correlations: list[FinancialPortfolioCorrelationResponse]
    coverage: FinancialPortfolioCoverageResponse
    notice: str


@router.get(
    "/financial-portfolios/{agentId}/research",
    response_model=FinancialPortfolioResearchResponse,
)
def financial_portfolio_research(agentId: str) -> dict:
    try:
        return service.get_portfolio_research(agentId)
    except paper.AccountNotOpenedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except market.MarketDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except (paper.FinancialPaperError, AgentDirectoryError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="组合研究暂时不可用") from exc
