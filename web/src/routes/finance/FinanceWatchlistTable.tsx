import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Pencil, RefreshCw, X } from "lucide-react";
import { fetchFinancialMarketQuotes, financialResearchKeys } from "../../api/financialResearch";
import type { StockIdentity, StockQuote } from "../../api/financialMarket";
import { VButton, VDenseTable, VInput, VSelect, VStateSurface, VSurface, type VDenseTableColumn } from "../../components/vui";
import styles from "./FinanceMarketExplorer.styles";
import editStyles from "./FinanceWatchlistTable.styles";
import { quoteAmount, quoteCurrency, quoteVolume, stockMarketCode } from "./financeMarketDisplay";

type SortField = "changePercent" | "turnover" | "volume" | "price" | "peRatio" | "marketCap";
type WatchStock = StockIdentity & { tags?: string[]; note?: string };
type WatchRow = { stock: WatchStock; quote: StockQuote | null; error: string | null };

const WATCHLIST_SORTS: Array<{ id: SortField; label: string }> = [
  { id: "changePercent", label: "涨跌幅" }, { id: "turnover", label: "成交额" },
  { id: "volume", label: "成交股数" }, { id: "marketCap", label: "总市值" },
  { id: "peRatio", label: "市盈率" }, { id: "price", label: "最新价" },
];

function valueText(value: number | null | undefined, digits = 2): string {
  return value === null || value === undefined || !Number.isFinite(value) ? "—" : value.toLocaleString("zh-CN", { maximumFractionDigits: digits });
}

function quoteChange(row: WatchRow): string {
  if (row.quote === null) return "—";
  const change = row.quote.changePercent;
  return `${change > 0 ? "+" : ""}${valueText(change)}%`;
}

function sourceTimestamp(value?: string): string {
  return value?.trim() || "—";
}

export function FinanceWatchlistTable({
  watchlist,
  onSelectStock,
  onRemoveStock,
  onEditStock,
  pending = false,
  zh,
}: {
  watchlist: WatchStock[];
  onSelectStock: (stock: StockIdentity) => void;
  onRemoveStock: (stock: StockIdentity) => void;
  onEditStock?: (symbol: string, tags: string[], note: string) => Promise<unknown>;
  pending?: boolean;
  zh: boolean;
}) {
  const [sortBy, setSortBy] = useState<SortField>("changePercent");
  const [marketFilter, setMarketFilter] = useState("all"), [tagFilter, setTagFilter] = useState("all");
  const [editing, setEditing] = useState<WatchStock | null>(null), [tags, setTags] = useState(""), [note, setNote] = useState(""), [saveError, setSaveError] = useState("");
  const filtered = useMemo(() => watchlist.filter((stock) => (marketFilter === "all" || stockMarketCode(stock) === marketFilter) && (tagFilter === "all" || stock.tags?.includes(tagFilter))), [watchlist, marketFilter, tagFilter]);
  const mixedCurrencies = new Set(filtered.map(stockMarketCode)).size > 1;
  const effectiveSort = mixedCurrencies && ["turnover", "marketCap", "price"].includes(sortBy) ? "changePercent" : sortBy;
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
    function sortValue(quote: StockQuote | null) {
      if (!quote) return null;
      if (effectiveSort === "turnover") return quote.turnover ?? quote.turnoverYuan;
      if (effectiveSort === "marketCap") return quote.marketCap ?? quote.totalMarketCapYuan;
      if (effectiveSort === "volume") return quote.volume ?? (quote.volumeLots == null ? null : quote.volumeLots * 100);
      return quote[effectiveSort];
    }
    return filtered.map((stock): WatchRow => {
      const result = quotes.get(stock.symbol);
      return { stock, quote: result?.quote ?? null, error: result?.error ?? null };
    }).sort((left, right) => {
      const a = sortValue(left.quote) ?? null;
      const b = sortValue(right.quote) ?? null;
      if (a === null && b !== null) return 1;
      if (a !== null && b === null) return -1;
      return a === null || b === null ? left.stock.ticker.localeCompare(right.stock.ticker) : b - a;
    });
  }, [query.data, effectiveSort, filtered]);

  const columns = useMemo<VDenseTableColumn<WatchRow>[]>(() => [
    {
      id: "stock", header: zh ? "股票" : "Stock", fill: true, minWidth: 130,
      render: ({ stock, quote, error }) => <VButton variant="ghost" className={styles.stockButton} onPress={() => onSelectStock(stock)}>
        <span className={styles.stockCell}>
          <strong className={styles.stockName}>{stock.name}</strong>
          <span className={styles.ticker}>{stock.ticker} · {stock.market}</span>
          {quote?.timestamp ? <time className={editStyles.quoteTimestamp} dateTime={quote.timestamp}>{quote.timestamp}</time> : null}
          {error ? <span className={editStyles.quoteError} role="status">{error}</span> : null}
        </span>
      </VButton>,
    },
    { id: "price", header: zh ? "现价" : "Price", width: 108, align: "right", render: ({ quote }) => <span className={styles.number}>{quote ? `${valueText(quote.price, 3)} ${quoteCurrency(quote, zh)}` : "—"}</span> },
    {
      id: "change", header: zh ? "涨跌幅" : "Change", width: 86, align: "right",
      render: (row) => <span className={!row.quote ? styles.nullValue : (row.quote.changePercent >= 0 ? styles.positive : styles.negative)}>{quoteChange(row)}</span>,
    },
    { id: "volume", header: zh ? "成交量" : "Volume", width: 108, align: "right", render: ({ quote }) => <span className={styles.number}>{quoteVolume(quote, zh)}</span> },
    { id: "turnover", header: zh ? "成交额" : "Turnover", width: 116, align: "right", render: ({ quote }) => <span className={styles.number}>{quoteAmount(quote, "turnover", zh)}</span> },
    { id: "pe", header: "PE", width: 66, align: "right", render: ({ quote }) => <span className={styles.number}>{valueText(quote?.peRatio)}</span> },
    { id: "marketCap", header: zh ? "总市值" : "Market cap", width: 116, align: "right", render: ({ quote }) => <span className={styles.number}>{quoteAmount(quote, "marketCap", zh)}</span> },
    { id: "tags", header: zh ? "标签 / 备注" : "Tags / note", width: 140, render: ({ stock }) => { const row = watchlist.find((item) => item.symbol === stock.symbol); return <span className={editStyles.tags} title={row?.note}>{row?.tags?.join(" · ") || "—"}{row?.note ? ` · ${row.note}` : ""}</span>; } },
    {
      id: "action", header: zh ? "操作" : "Action", width: onEditStock ? 104 : 72,
      render: ({ stock }) => <span className={editStyles.buttons}>{onEditStock ? <VButton density="compact" variant="ghost" aria-label={`${zh ? "编辑" : "Edit"} ${stock.name}`} onPress={() => { const row = watchlist.find((item) => item.symbol === stock.symbol) ?? stock; setEditing(row); setTags(row.tags?.join(", ") ?? ""); setNote(row.note ?? ""); setSaveError(""); }} icon={<Pencil size={13} />} /> : null}<VButton density="compact" variant="ghost" isDisabled={pending} aria-label={`${zh ? "移除" : "Remove"} ${stock.name}`} onPress={() => onRemoveStock(stock)} icon={<X size={13} />}>{zh ? "移除" : "Remove"}</VButton></span>,
    },
  ], [onRemoveStock, onSelectStock, onEditStock, watchlist, pending, zh]);

  if (watchlist.length === 0) return <VStateSurface tone="empty" title={zh ? "暂无自选股票" : "No stocks in watchlist"}>{zh ? "从行情筛选或股票页添加关注。" : "Add stocks from the market screen or stock page."}</VStateSurface>;
  if (query.isPending) return <VStateSurface tone="loading" busy title={zh ? "正在更新自选行情" : "Loading watchlist quotes"} />;
  if (query.isError && !query.data) return <VStateSurface tone="error" title={zh ? "自选行情加载失败" : "Watchlist quotes unavailable"} actions={<VButton onPress={() => void query.refetch()}>{zh ? "重试" : "Retry"}</VButton>}>{query.error.message}</VStateSurface>;

  const failed = rows.filter((row) => !row.quote).length;
  return <div className={styles.root}>
    <div className={styles.heading}>
      <div className={styles.actionGroup}>
        <label className={styles.field}>{zh ? "市场" : "Market"}<VSelect aria-label={zh ? "自选市场" : "Watchlist market"} selectedKey={marketFilter} options={[{ id: "all", label: zh ? "全部市场" : "All markets" }, { id: "CN", label: "A股" }, { id: "HK", label: "港股" }, { id: "US", label: "美股" }]} onSelectionChange={(key) => setMarketFilter(String(key))} /></label>
        <label className={styles.field}>{zh ? "标签" : "Tag"}<VSelect aria-label={zh ? "自选标签" : "Watchlist tag"} selectedKey={tagFilter} options={[{ id: "all", label: zh ? "全部标签" : "All tags" }, ...[...new Set(watchlist.flatMap((row) => row.tags ?? []))].map((tag) => ({ id: tag, label: tag }))]} onSelectionChange={(key) => setTagFilter(String(key))} /></label>
        <label className={styles.field}>{zh ? "排序" : "Sort"}<VSelect aria-label={zh ? "自选排序字段" : "Watchlist sort"} selectedKey={effectiveSort} options={WATCHLIST_SORTS.filter((item) => !mixedCurrencies || !["turnover", "marketCap", "price"].includes(item.id)).map((item) => ({ ...item, label: zh ? item.label : item.id }))} onSelectionChange={(key) => setSortBy(String(key) as SortField)} /></label>
        <span className={styles.meta}>{query.data?.source ?? ""} · {zh ? `上次成功抓取 ${sourceTimestamp(query.data?.fetchedAt)} · 每分钟刷新` : `Last successful fetch ${sourceTimestamp(query.data?.fetchedAt)} · Refreshes every minute`}</span>
      </div>
      <VButton variant="secondary" icon={<RefreshCw size={14} />} isDisabled={query.isFetching} onPress={() => void query.refetch()}>{zh ? "刷新行情" : "Refresh quotes"}</VButton>
    </div>
    {query.error ? <VStateSurface tone="error" density="compact" title={zh ? "刷新失败，当前显示上次成功获取的数据" : "Refresh failed; showing the last successfully fetched data"} actions={<VButton isDisabled={query.isFetching} onPress={() => void query.refetch()}>{zh ? "重试" : "Retry"}</VButton>}>{query.error.message}</VStateSurface> : null}
    {editing && onEditStock ? <VSurface tone="panel" padding="normal" className={editStyles.editor} ariaLabel={zh ? `编辑 ${editing.name}` : `Edit ${editing.name}`}><label className={editStyles.field}>{zh ? "标签（逗号分隔）" : "Tags (comma separated)"}<VInput aria-label={zh ? "股票标签" : "Stock tags"} value={tags} maxLength={309} onChange={(event) => setTags(event.target.value)} /></label><label className={editStyles.field}>{zh ? "备注" : "Note"}<VInput aria-label={zh ? "股票备注" : "Stock note"} value={note} maxLength={500} onChange={(event) => setNote(event.target.value)} /></label><span className={editStyles.buttons}><VButton isDisabled={pending} onPress={() => { const parsed = [...new Set(tags.split(/[,，]/).map((tag) => tag.trim()).filter(Boolean))]; if (parsed.length > 10 || parsed.some((tag) => tag.length > 30)) { setSaveError(zh ? "最多10个标签，每个30字" : "At most 10 tags, 30 characters each"); return; } void onEditStock(editing.symbol, parsed, note).then(() => setEditing(null)).catch((error: unknown) => setSaveError(error instanceof Error ? error.message : "保存失败")); }}>{zh ? "保存" : "Save"}</VButton><VButton variant="ghost" onPress={() => setEditing(null)}>{zh ? "取消" : "Cancel"}</VButton></span></VSurface> : null}
    {saveError ? <VStateSurface density="compact" tone="error" title={saveError} /> : null}
    {failed ? <VSurface tone="row" className={styles.meta} role="status">{zh ? `${failed} 只股票暂无有效行情，空值已保留。` : `${failed} stocks have no valid quote; values remain empty.`}</VSurface> : null}
    <div className={styles.tableWrap}><VDenseTable ariaLabel={zh ? "自选股票实时行情" : "Watchlist live quotes"} columns={columns} rows={rows} getRowKey={(row) => row.stock.symbol} resizable emptyText={zh ? "暂无股票" : "No stocks"} /></div>
  </div>;
}
