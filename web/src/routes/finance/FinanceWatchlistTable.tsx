import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, X } from "lucide-react";
import { fetchFinancialMarketQuotes, financialResearchKeys } from "../../api/financialResearch";
import type { StockIdentity, StockQuote } from "../../api/financialMarket";
import { VButton, VDenseTable, VSelect, VStateSurface, VSurface, type VDenseTableColumn } from "../../components/vui";
import styles from "./FinanceMarketExplorer.styles";

type SortField = "changePercent" | "turnoverYuan" | "volumeLots" | "price" | "peRatio" | "totalMarketCapYuan";
type WatchRow = { stock: StockIdentity; quote: StockQuote | null; error: string | null };

const WATCHLIST_SORTS: Array<{ id: SortField; label: string }> = [
  { id: "changePercent", label: "涨跌幅" }, { id: "turnoverYuan", label: "成交额" },
  { id: "volumeLots", label: "成交量" }, { id: "totalMarketCapYuan", label: "总市值" },
  { id: "peRatio", label: "市盈率" }, { id: "price", label: "最新价" },
];

function valueText(value: number | null | undefined, digits = 2): string {
  return value === null || value === undefined || !Number.isFinite(value) ? "—" : value.toLocaleString("zh-CN", { maximumFractionDigits: digits });
}

function moneyText(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return Math.abs(value) >= 100_000_000 ? `${valueText(value / 100_000_000)} 亿` : `${valueText(value)} 元`;
}

function quoteChange(row: WatchRow): string {
  if (row.quote === null) return "—";
  const change = row.quote.changePercent;
  return `${change > 0 ? "+" : ""}${valueText(change)}%`;
}

function fetchedTime(value?: string): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString("zh-CN", { hour12: false });
}

export function FinanceWatchlistTable({
  watchlist,
  onSelectStock,
  onRemoveStock,
  zh,
}: {
  watchlist: StockIdentity[];
  onSelectStock: (stock: StockIdentity) => void;
  onRemoveStock: (stock: StockIdentity) => void;
  zh: boolean;
}) {
  const [sortBy, setSortBy] = useState<SortField>("changePercent");
  const symbols = useMemo(() => watchlist.map((stock) => stock.symbol).sort(), [watchlist]);
  const query = useQuery({
    queryKey: financialResearchKeys.quotes(symbols),
    queryFn: ({ signal }) => fetchFinancialMarketQuotes(symbols, { signal }),
    enabled: symbols.length > 0,
    staleTime: 20_000,
    refetchInterval: 60_000,
    retry: false,
  });

  const rows = useMemo(() => {
    const quotes = new Map((query.data?.items ?? []).map((item) => [item.symbol, item]));
    return watchlist.map((stock): WatchRow => {
      const result = quotes.get(stock.symbol);
      return { stock, quote: result?.quote ?? null, error: result?.error ?? null };
    }).sort((left, right) => {
      const a = left.quote?.[sortBy] ?? null;
      const b = right.quote?.[sortBy] ?? null;
      if (a === null && b !== null) return 1;
      if (a !== null && b === null) return -1;
      return a === null || b === null ? left.stock.ticker.localeCompare(right.stock.ticker) : b - a;
    });
  }, [query.data, sortBy, watchlist]);

  const columns = useMemo<VDenseTableColumn<WatchRow>[]>(() => [
    {
      id: "stock", header: zh ? "股票" : "Stock", fill: true, minWidth: 130,
      render: ({ stock }) => <VButton variant="ghost" className={styles.stockButton} onPress={() => onSelectStock(stock)}>
        <span className={styles.stockCell}><strong className={styles.stockName}>{stock.name}</strong><span className={styles.ticker}>{stock.ticker} · {stock.market}</span></span>
      </VButton>,
    },
    { id: "price", header: zh ? "现价" : "Price", width: 78, align: "right", render: ({ quote }) => <span className={styles.number}>{valueText(quote?.price, 3)}</span> },
    {
      id: "change", header: zh ? "涨跌幅" : "Change", width: 86, align: "right",
      render: (row) => <span className={!row.quote ? styles.nullValue : (row.quote.changePercent >= 0 ? styles.positive : styles.negative)}>{quoteChange(row)}</span>,
    },
    { id: "volume", header: zh ? "成交量" : "Volume", width: 88, align: "right", render: ({ quote }) => <span className={styles.number}>{quote ? `${valueText(quote.volumeLots, 0)} 手` : "—"}</span> },
    { id: "turnover", header: zh ? "成交额" : "Turnover", width: 102, align: "right", render: ({ quote }) => <span className={styles.number}>{moneyText(quote?.turnoverYuan)}</span> },
    { id: "pe", header: "PE", width: 66, align: "right", render: ({ quote }) => <span className={styles.number}>{valueText(quote?.peRatio)}</span> },
    { id: "marketCap", header: zh ? "总市值" : "Market cap", width: 100, align: "right", render: ({ quote }) => <span className={styles.number}>{moneyText(quote?.totalMarketCapYuan)}</span> },
    {
      id: "action", header: zh ? "操作" : "Action", width: 72,
      render: ({ stock }) => <VButton density="compact" variant="ghost" aria-label={`${zh ? "移除" : "Remove"} ${stock.name}`} onPress={() => onRemoveStock(stock)} icon={<X size={13} />}>{zh ? "移除" : "Remove"}</VButton>,
    },
  ], [onRemoveStock, onSelectStock, zh]);

  if (watchlist.length === 0) return <VStateSurface tone="empty" title={zh ? "暂无自选股票" : "No stocks in watchlist"}>{zh ? "从行情筛选或股票页添加关注。" : "Add stocks from the market screen or stock page."}</VStateSurface>;
  if (query.isPending) return <VStateSurface tone="loading" busy title={zh ? "正在更新自选行情" : "Loading watchlist quotes"} />;
  if (query.isError) return <VStateSurface tone="error" title={zh ? "自选行情加载失败" : "Watchlist quotes unavailable"} actions={<VButton onPress={() => void query.refetch()}>{zh ? "重试" : "Retry"}</VButton>}>{query.error.message}</VStateSurface>;

  const failed = rows.filter((row) => !row.quote).length;
  return <div className={styles.root}>
    <div className={styles.heading}>
      <div className={styles.actionGroup}>
        <label className={styles.field}>{zh ? "排序" : "Sort"}<VSelect aria-label={zh ? "自选排序字段" : "Watchlist sort"} selectedKey={sortBy} options={WATCHLIST_SORTS.map((item) => ({ ...item, label: zh ? item.label : item.id }))} onSelectionChange={(key) => setSortBy(String(key) as SortField)} /></label>
        <span className={styles.meta}>{query.data?.source ?? ""} · {zh ? `拉取 ${fetchedTime(query.data?.fetchedAt)} · 每分钟刷新` : `Fetched ${fetchedTime(query.data?.fetchedAt)} · Refreshes every minute`}</span>
      </div>
      <VButton variant="secondary" icon={<RefreshCw size={14} />} isDisabled={query.isFetching} onPress={() => void query.refetch()}>{zh ? "刷新行情" : "Refresh quotes"}</VButton>
    </div>
    {failed ? <VSurface tone="row" className={styles.meta} role="status">{zh ? `${failed} 只股票暂无有效行情，空值已保留。` : `${failed} stocks have no valid quote; values remain empty.`}</VSurface> : null}
    <div className={styles.tableWrap}><VDenseTable ariaLabel={zh ? "自选股票实时行情" : "Watchlist live quotes"} columns={columns} rows={rows} getRowKey={(row) => row.stock.symbol} resizable emptyText={zh ? "暂无股票" : "No stocks"} /></div>
  </div>;
}
