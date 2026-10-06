"""Typed financial entry routes; native services remain lifecycle authorities."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from core.web.services import financial_assistant_service as service
from core.web.services import financial_market_service as market
from core.web.services.agent_directory_service import (
    AgentDirectoryError,
    AgentStateConflictError,
)

router = APIRouter(tags=["financial-assistant"])


class FinancialAssistantResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agentId: str
    agentCode: str
    displayName: str
    status: str
    setupStatus: str
    directSessionId: str
    directSessionArchived: bool = False
    knowledgeBaseId: str
    knowledgeReadable: bool
    modelStatus: str
    reportStatus: str
    marketDataStatus: str
    marketToolStatus: Literal["assigned", "upgrade_available", "not_assigned"] = (
        "not_assigned"
    )
    newsDelegationStatus: str
    privateLedgerStatus: str
    tradingEnabled: bool


class FinancialAssistantCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    displayName: str = Field(default="炒股智能体", min_length=1, max_length=80)


class FinancialAssistantCreateResponse(BaseModel):
    created: bool
    assistant: FinancialAssistantResponse


@router.get("/financial-assistants", response_model=list[FinancialAssistantResponse])
def financial_assistant_list() -> list[dict]:
    return service.list_financial_assistants()


@router.post("/financial-assistants", response_model=FinancialAssistantCreateResponse)
def financial_assistant_create(payload: FinancialAssistantCreateRequest) -> dict:
    try:
        return service.create_financial_assistant(payload.displayName)
    except AgentStateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AgentDirectoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class StockIdentityResponse(BaseModel):
    symbol: str
    ticker: str
    name: str
    market: str
    marketCode: Literal["CN", "HK", "US"] | None = None
    currency: Literal["CNY", "HKD", "USD"] | None = None
    marketTimeZone: Literal["Asia/Shanghai", "Asia/Hong_Kong", "America/New_York"] | None = None


class StockQuoteResponse(StockIdentityResponse):
    price: float
    priceUnit: Literal["CNY/share", "HKD/share", "USD/share"] | None = None
    previousClose: float
    open: float
    high: float
    low: float
    change: float
    changePercent: float
    volume: float | None = None
    volumeUnit: Literal["shares"] | None = None
    volumeLots: float | None
    turnover: float | None = None
    turnoverYuan: float | None
    peRatio: float | None
    pbRatio: float | None
    marketCap: float | None = None
    totalMarketCapYuan: float | None
    timestamp: str


class StockCandleResponse(BaseModel):
    date: str
    open: float
    close: float
    high: float
    low: float
    volume: float | None = None
    volumeUnit: Literal["shares"] | None = None
    volumeLots: float | None


class StockSnapshotResponse(BaseModel):
    stock: StockQuoteResponse
    candles: list[StockCandleResponse]
    period: Literal["day", "week", "month"]
    adjustment: Literal["qfq", "raw"]
    source: str
    sourceUrl: str
    fetchedAt: str
    candleError: str
    notice: str


@router.get("/financial-market/search", response_model=list[StockIdentityResponse])
def financial_market_search(
    query: str = Query(default="", max_length=40, pattern=r"^[\w\s.*\-]*$"),
    market_code: Literal["CN", "HK", "US"] = Query(default="CN", alias="market"),
) -> list[dict]:
    try:
        return market.search_stocks(query, market_code)
    except market.StockNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except market.MarketDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/financial-market/stocks/{symbol}", response_model=StockSnapshotResponse)
def financial_market_stock(
    symbol: str, period: Literal["day", "week", "month"] = "day"
) -> dict:
    try:
        market.normalize_symbol(symbol)
    except market.MarketDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        return market.get_stock_snapshot(symbol, period)
    except market.StockNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except market.MarketDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
