import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { FinancialManualPosition } from "../../api/financialPreferences";
import { financialMarketKeys, searchFinancialStocks, type StockIdentity, type StockMarketCode, type StockQuote } from "../../api/financialMarket";
import { fetchFinancialMarketQuotes, financialResearchKeys } from "../../api/financialResearch";
import { VButton, VDenseTable, VDialog, VInput, VSelect, VStateSurface, VSurface, type VDenseTableColumn } from "../../components/vui";
import { quoteCurrency, stockCurrency, stockMarketCode } from "./financeMarketDisplay";
import { manualPositionQuote, manualPortfolioPrompt, manualPortfolioTotals, ManualPositionConflictError, saveManualPositionChange } from "./financialManualPortfolioModel";
import { quoteNumber, stockIdentityFromUnknown } from "./stockResearchModel";
import styles from "./FinanceManualPositions.styles";

export function FinanceManualPositions({ positions, stock, onSave, onSelectStock, onResearchPrompt, pending, researchDisabled, zh }: {
  positions: FinancialManualPosition[]; stock: StockIdentity;
  onSave: (change: (current: FinancialManualPosition[]) => FinancialManualPosition[]) => Promise<unknown>;
  onSelectStock: (stock: StockIdentity) => void; onResearchPrompt: (text: string) => void;
  pending: boolean; researchDisabled: boolean; zh: boolean;
}) {
  const symbols = useMemo(() => [...new Set(positions.map((row) => row.stock.symbol))].sort(), [positions]);
  const market = useQuery({ queryKey: financialResearchKeys.quotes(symbols), queryFn: ({ signal }) => fetchFinancialMarketQuotes(symbols, { signal }), enabled: Boolean(symbols.length), staleTime: 30_000, refetchInterval: 60_000, retry: false });
  const quotes = useMemo(() => new Map((market.data?.items ?? []).flatMap((item) => item.quote ? [[item.symbol, item.quote] as const] : [])), [market.data]);
  const totals = manualPortfolioTotals(positions, quotes);
  const [editing, setEditing] = useState<FinancialManualPosition | null>(null), [open, setOpen] = useState(false);
  const [editBaseline, setEditBaseline] = useState<FinancialManualPosition | null>(null);
  const [editorStock, setEditorStock] = useState(stock), [quantity, setQuantity] = useState(""), [cost, setCost] = useState(""), [note, setNote] = useState("");
  const [marketCode, setMarketCode] = useState<StockMarketCode>(stockMarketCode(stock)), [search, setSearch] = useState(""), [query, setQuery] = useState(""), [error, setError] = useState("");
  const saveGate = useRef(false);
  useEffect(() => { const timer = setTimeout(() => setQuery(search.trim()), 250); return () => clearTimeout(timer); }, [search]);
  const lookup = useQuery({ queryKey: financialMarketKeys.search(query, marketCode), queryFn: ({ signal }) => searchFinancialStocks(query, { signal, market: marketCode }), enabled: open && Boolean(query), staleTime: 60_000, retry: false });
  function edit(row: FinancialManualPosition | null) {
    const baseline = row ? { ...row, stock: { ...row.stock } } : null;
    setEditing(baseline); setEditBaseline(baseline); setEditorStock(baseline?.stock ?? stock); setMarketCode(stockMarketCode(baseline?.stock ?? stock)); setQuantity(baseline ? String(baseline.quantity) : ""); setCost(baseline ? String(baseline.costPrice) : ""); setNote(baseline?.note ?? ""); setError(""); setSearch(""); setQuery(""); setOpen(true);
  }
  async function save() {
    if (saveGate.current || pending) return;
    const identity = stockIdentityFromUnknown(editorStock), quantityValue = Number(quantity), costPrice = Number(cost);
    if (!identity || !Number.isFinite(quantityValue) || quantityValue <= 0 || quantityValue > 1e12 || !Number.isFinite(costPrice) || costPrice <= 0 || costPrice > 1e8) { setError(zh ? "数量和成本须为有效正数" : "Quantity and cost must be positive numbers"); return; }
    const row: FinancialManualPosition = { id: editing?.id ?? crypto.randomUUID(), stock: identity, quantity: quantityValue, costPrice, currency: stockCurrency(identity), note };
    saveGate.current = true; setError("");
    try { await onSave((current) => saveManualPositionChange(current, row, editBaseline)); setOpen(false); }
    catch (cause) {
      if (cause instanceof ManualPositionConflictError) {
        const messages = {
          changed: zh ? "这条持仓已在其他窗口修改，当前编辑未保存。请刷新后重新编辑。" : "This holding changed in another window. Your edit was not saved; refresh before editing again.",
          deleted: zh ? "这条持仓已在其他窗口删除，当前编辑未保存。请刷新后重新编辑。" : "This holding was deleted in another window. Your edit was not saved; refresh before editing again.",
          id_collision: zh ? "新增持仓标识已被占用，当前内容未覆盖已有记录。请重新打开表单后再试。" : "The new holding ID is already in use. No existing row was overwritten; reopen the form and try again.",
        };
        setError(messages[cause.reason]);
      } else setError(cause instanceof Error ? cause.message : (zh ? "保存失败" : "Save failed"));
    }
    finally { saveGate.current = false; }
  }
  const priceQuote = (row: FinancialManualPosition): StockQuote | undefined => manualPositionQuote(row, quotes);
  const columns: VDenseTableColumn<FinancialManualPosition>[] = [
    { id: "stock", header: zh ? "股票" : "Stock", fill: true, minWidth: 150, render: (row) => <VButton variant="ghost" className={styles.stock} onPress={() => onSelectStock(row.stock)}><span className={styles.identity}><strong>{row.stock.name}</strong><small>{row.stock.ticker} · {row.currency}</small></span></VButton> },
    { id: "quantity", header: zh ? "股数" : "Shares", width: 85, align: "right", render: (row) => <span className={styles.number}>{quoteNumber(row.quantity, 4)}</span> },
    { id: "cost", header: zh ? "成本价" : "Cost", width: 95, align: "right", render: (row) => <span className={styles.number}>{quoteNumber(row.costPrice, 3)} {row.currency}</span> },
    { id: "price", header: zh ? "现价" : "Quote", width: 98, align: "right", render: (row) => { const quote = priceQuote(row); return <span className={styles.number}>{quote ? `${quoteNumber(quote.price, 3)} ${quoteCurrency(quote, zh)}` : "—"}</span>; } },
    { id: "value", header: zh ? "市值" : "Market value", width: 112, align: "right", render: (row) => { const quote = priceQuote(row); return <span className={styles.number}>{quote ? `${quoteNumber(row.quantity * quote.price)} ${row.currency}` : "—"}</span>; } },
    { id: "gain", header: zh ? "浮动盈亏" : "Unrealized P/L", width: 110, align: "right", render: (row) => { const quote = priceQuote(row); return <span className={styles.number}>{quote ? `${quoteNumber(row.quantity * (quote.price - row.costPrice))} ${row.currency}` : "—"}</span>; } },
    { id: "actions", header: zh ? "操作" : "Actions", width: 110, render: (row) => <span className={styles.actions}><VButton density="compact" variant="ghost" isDisabled={pending} onPress={() => edit(row)}>{zh ? "编辑" : "Edit"}</VButton><VButton density="compact" variant="ghost" isDisabled={pending} onPress={() => void onSave((current) => current.filter((item) => item.id !== row.id)).catch((cause: unknown) => setError(cause instanceof Error ? cause.message : "删除失败"))}>{zh ? "移除" : "Remove"}</VButton></span> },
  ];
  return <div className={styles.root}>
    <div className={styles.toolbar}><p className={styles.meta}>{zh ? "手工记录持仓，报价可能延迟。金额按币种分别汇总。" : "Manually recorded holdings; quotes may be delayed. Totals are separated by currency."}</p><span className={styles.actions}><VButton isDisabled={pending || positions.length >= 50} onPress={() => edit(null)}>{zh ? "添加持仓" : "Add holding"}</VButton><VButton variant="secondary" isPending={market.isFetching} isDisabled={!symbols.length} onPress={() => void market.refetch()}>{zh ? "刷新估值" : "Refresh"}</VButton><VButton variant="primary" isDisabled={!positions.length || researchDisabled} onPress={() => onResearchPrompt(manualPortfolioPrompt(positions, quotes, market.data?.fetchedAt ?? ""))}>{zh ? "研究持仓" : "Research holdings"}</VButton></span></div>
    {totals.length ? <div className={styles.metrics}>{totals.map((group) => <VSurface key={group.currency} tone="panel" padding="normal" className={styles.summary}><strong>{group.currency}</strong><span>{zh ? "已估值市值" : "Marked value"} {quoteNumber(group.marketValue)}</span><span>{zh ? "对应浮动盈亏" : "Marked P/L"} {quoteNumber(group.marketValue - group.markedCost)}</span><small>{zh ? `行情覆盖 ${group.marked}/${group.count} · 记录成本 ${quoteNumber(group.cost)}` : `Quote coverage ${group.marked}/${group.count} · Recorded cost ${quoteNumber(group.cost)}`}</small></VSurface>)}</div> : null}
    {market.isError ? <VStateSurface density="compact" tone="error" title={zh ? "估值行情读取失败，持仓记录仍可编辑" : "Quotes unavailable; holdings remain editable"} actions={<VButton onPress={() => void market.refetch()}>{zh ? "重试" : "Retry"}</VButton>}>{market.error.message}</VStateSurface> : null}
    <div className={styles.table}><VDenseTable ariaLabel={zh ? "手工持仓记录" : "Manual holdings"} columns={columns} rows={positions} getRowKey={(row) => row.id} resizable emptyText={zh ? "暂无手工持仓" : "No manual holdings"} /></div>
    {market.data ? <span className={styles.meta}>{market.data.source} · {new Date(market.data.fetchedAt).toLocaleString()} · {zh ? "未获得报价的记录不计入市值和盈亏" : "Unquoted holdings are excluded from marked value and P/L"}</span> : null}
    {error && !open ? <VStateSurface density="compact" tone="error" title={error} /> : null}
    <VDialog open={open} onOpenChange={setOpen} title={zh ? editing ? "编辑持仓" : "添加持仓" : editing ? "Edit holding" : "Add holding"} footer={<VButton variant="primary" isDisabled={pending} onPress={() => void save()}>{zh ? "保存持仓" : "Save holding"}</VButton>}><div className={styles.form}>
      <div className={styles.pair}><label className={styles.field}>{zh ? "市场" : "Market"}<VSelect aria-label={zh ? "持仓股票市场" : "Holding market"} selectedKey={marketCode} options={[{ id: "CN", label: "A股" }, { id: "HK", label: "港股" }, { id: "US", label: "美股" }]} onSelectionChange={(key) => { setMarketCode(String(key) as StockMarketCode); setSearch(""); setQuery(""); }} /></label><label className={styles.field}>{zh ? "查找股票" : "Find stock"}<VInput aria-label={zh ? "持仓股票搜索" : "Holding stock search"} value={search} maxLength={40} placeholder={zh ? "公司 / 代码" : "Company / ticker"} onChange={(event) => setSearch(event.target.value)} /></label></div>
      {query ? lookup.isPending ? <VStateSurface density="compact" tone="loading" busy title={zh ? "查询中" : "Searching"} /> : lookup.isError ? <VStateSurface density="compact" tone="error" title={lookup.error.message} /> : <div className={styles.search}>{lookup.data?.length ? lookup.data.map((item) => <VButton key={item.symbol} variant="ghost" className={styles.result} onPress={() => { setEditorStock(item); setSearch(""); setQuery(""); }}>{item.name} · {item.ticker} · {item.market}</VButton>) : <span className={styles.meta}>{zh ? "没有匹配股票" : "No matches"}</span>}</div> : null}
      <strong>{editorStock.name} · {editorStock.ticker} · {stockCurrency(editorStock)}</strong>
      <div className={styles.pair}><label className={styles.field}>{zh ? "持仓股数" : "Shares"}<VInput type="number" aria-label={zh ? "持仓股数" : "Holding shares"} min={0} step="any" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></label><label className={styles.field}>{zh ? "平均成本价" : "Average cost"}<VInput type="number" aria-label={zh ? "平均成本价" : "Average cost"} min={0} step="any" value={cost} onChange={(event) => setCost(event.target.value)} /></label></div><label className={styles.field}>{zh ? "备注" : "Note"}<VInput aria-label={zh ? "持仓备注" : "Holding note"} value={note} maxLength={500} onChange={(event) => setNote(event.target.value)} /></label>{error ? <VStateSurface density="compact" tone="error" title={error} /> : null}
    </div></VDialog>
  </div>;
}
