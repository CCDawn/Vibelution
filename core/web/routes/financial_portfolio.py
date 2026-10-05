"""Read-only portfolio research over an Agent's simulated holdings."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core.web.services import financial_market_service as market
from core.web.services import financial_paper_service as paper
from core.web.services import financial_portfolio_service as service
from core.web.services.agent_directory_service import (
    AgentDirectoryError,
    AgentNotFoundError,
)

router = APIRouter(tags=["financial-portfolio"])


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
