"""Read-only market screening, batched quotes and cited stock research routes."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from core.web.services import financial_research_service as service

router = APIRouter(tags=["financial-research"])


class StockIdentityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    ticker: str
    name: str
    market: str
    marketCode: Literal["CN", "HK", "US"] | None = None
    currency: Literal["CNY", "HKD", "USD"] | None = None
    marketTimeZone: Literal["Asia/Shanghai", "Asia/Hong_Kong", "America/New_York"] | None = None


class MarketQuoteResponse(StockIdentityResponse):
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


class QuoteBatchItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    quote: MarketQuoteResponse | None
    error: str | None


class QuoteBatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    sourceUrl: str
    fetchedAt: str
    items: list[QuoteBatchItemResponse]


class MarketScreenStockResponse(StockIdentityResponse):
    price: float | None
    previousClose: float | None
    open: float | None
    high: float | None
    low: float | None
    change: float | None
    changePercent: float | None
    volumeLots: float | None
    turnoverYuan: float | None
    peRatio: float | None
    pbRatio: float | None
    totalMarketCapYuan: float | None
    timestamp: str | None
    timeOfDay: str | None


class MarketScreenCoverageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    providerTotal: int
    loaded: int
    complete: bool
    failedPages: list[int]
    invalidRows: int
    duplicateRows: int
    totalFiltered: int


class MarketScreenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    sourceUrl: str
    fetchedAt: str
    dataDate: str | None
    dataTime: str | None
    cacheKey: str
    cacheSeconds: int
    coverage: MarketScreenCoverageResponse
    resultScope: Literal["provider_universe", "loaded_subset"]
    sortBy: Literal["changePercent", "turnoverYuan", "price", "volumeLots", "peRatio", "pbRatio"]
    direction: Literal["asc", "desc"]
    page: int
    pageSize: int
    items: list[MarketScreenStockResponse]
    notice: str


class NewsItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    publishedAt: str | None
    publisher: str
    url: str | None


class AnnouncementResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    publishedAt: str | None
    noticeDate: str | None
    url: str
    articleCode: str


class ResearchMetricResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    label: str
    value: float | None
    unit: str
    reportDate: str | None
    publishedAt: str | None


class NewsFacetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["available", "unavailable"]
    source: str
    sourceUrl: str
    fetchedAt: str
    error: str | None

    items: list[NewsItemResponse]


class AnnouncementsFacetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["available", "unavailable"]
    source: str
    sourceUrl: str
    fetchedAt: str
    error: str | None
    items: list[AnnouncementResponse]


class ResearchFundamentalsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["available", "unavailable"]
    source: str
    sourceUrl: str
    fetchedAt: str
    reportDate: str | None
    publishedAt: str | None
    error: str | None
    items: list[ResearchMetricResponse]


class StockResearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stock: StockIdentityResponse
    news: NewsFacetResponse
    announcements: AnnouncementsFacetResponse
    fundamentals: ResearchFundamentalsResponse


@router.get("/financial-market/quotes", response_model=QuoteBatchResponse)
def financial_market_quotes(
    symbols: str = Query(min_length=1, max_length=600),
) -> dict:
    values = [value.strip() for value in symbols.split(",")]
    if len(values) > 50:
        raise HTTPException(status_code=422, detail="一次最多查询 50 只股票")
    try:
        return service.batch_quotes(values)
    except service.FinancialResearchInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/financial-market/screen", response_model=MarketScreenResponse)
def financial_market_screen(
    minPrice: float | None = Query(default=None, ge=0, le=100_000_000),
    maxPrice: float | None = Query(default=None, ge=0, le=100_000_000),
    minChangePercent: float | None = Query(default=None, ge=-100, le=10_000),
    maxChangePercent: float | None = Query(default=None, ge=-100, le=10_000),
    minPe: float | None = Query(default=None, ge=-10_000, le=100_000),
    maxPe: float | None = Query(default=None, ge=-10_000, le=100_000),
    minVolumeLots: float | None = Query(default=None, ge=0, le=1_000_000_000_000_000),
    minPb: float | None = Query(default=None, ge=-10_000, le=100_000),
    maxPb: float | None = Query(default=None, ge=-10_000, le=100_000),
    minTurnoverYuan: float | None = Query(default=None, ge=0, le=1e15),
    maxTurnoverYuan: float | None = Query(default=None, ge=0, le=1e15),
    sortBy: Literal[
        "changePercent", "turnoverYuan", "price", "volumeLots", "peRatio", "pbRatio"
    ] = "changePercent",
    direction: Literal["asc", "desc"] = "desc",
    page: int = Query(default=1, ge=1, le=100_000),
    pageSize: int = Query(default=50, ge=1, le=100),
) -> dict:
    try:
        return service.screen_stocks(
            min_price=minPrice,
            max_price=maxPrice,
            min_change_percent=minChangePercent,
            max_change_percent=maxChangePercent,
            min_pe=minPe,
            max_pe=maxPe,
            min_volume_lots=minVolumeLots,
            min_pb=minPb,
            max_pb=maxPb,
            min_turnover_yuan=minTurnoverYuan,
            max_turnover_yuan=maxTurnoverYuan,
            sort_by=sortBy,
            direction=direction,
            page=page,
            page_size=pageSize,
        )
    except service.FinancialResearchInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.FinancialResearchDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/financial-market/stocks/{symbol}/research", response_model=StockResearchResponse
)
def financial_stock_research(symbol: str) -> dict:
    try:
        return service.stock_research(symbol)
    except service.FinancialResearchInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


__all__ = ["router"]
