import type { UseQueryResult } from "@tanstack/react-query";
import { RefreshCw, Star, TrendingDown, TrendingUp } from "lucide-react";
import type { StockIdentity, StockPeriod, StockSnapshot } from "../../api/financialMarket";
import { VButton, VChip, VIconButton, VSkeleton, VStateSurface, VSurface } from "../../components/vui";
import { FinanceStockChart } from "./FinanceStockChart";
import { quoteNumber, yuanAmount } from "./stockResearchModel";

export function FinanceStockHeader({ stock, query, starred, onToggleStar, zh }: { stock: StockIdentity; query: UseQueryResult<StockSnapshot, Error>; starred: boolean; onToggleStar: () => void; zh: boolean }) {
  const quote = query.data?.stock;
  const rising = (quote?.change ?? 0) >= 0;
  const time = quote?.timestamp ? new Date(quote.timestamp).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }) : "—";
  return <div className="shrink-0 border-b border-[var(--vui-border-subtle)] px-6 pt-5 pb-4" data-finance-stock-header>
    <div className="flex items-center justify-between gap-4">
      <div className="flex min-w-0 items-center gap-3"><h1 className="m-0 text-xl font-semibold truncate">{quote?.name || stock.name}</h1><span className="text-sm font-mono text-[var(--fg-tertiary)]">{stock.ticker}</span><VChip>{quote?.market || stock.market}</VChip></div>
      <div className="flex items-center gap-2"><VButton variant="ghost" icon={<Star size={15} fill={starred ? "currentColor" : "none"} />} aria-pressed={starred} onPress={onToggleStar}>{starred ? (zh ? "已自选" : "Following") : (zh ? "加入自选" : "Follow")}</VButton><VIconButton label={zh ? "刷新行情" : "Refresh quotes"} icon={<RefreshCw size={15} />} isDisabled={query.isFetching} onPress={() => void query.refetch()} /></div>
    </div>
    <div className="flex items-end justify-between gap-5 mt-3">
      <div className={`flex items-end gap-4 tabular-nums ${quote ? rising ? "text-[var(--state-error)]" : "text-[var(--state-success)]" : "text-[var(--fg-tertiary)]"}`}>
        <strong className="text-3xl tracking-tight font-semibold">{quoteNumber(quote?.price)}</strong>
        {quote ? <span className="flex items-center gap-1 pb-1 text-sm">{rising ? <TrendingUp size={16} /> : <TrendingDown size={16} />}{quote.change >= 0 ? "+" : ""}{quoteNumber(quote.change)}<span className="ml-2">{quote.changePercent >= 0 ? "+" : ""}{quoteNumber(quote.changePercent)}%</span></span> : <span className="pb-1 text-xs">{query.isPending ? (zh ? "行情加载中" : "Loading quotes") : (zh ? "行情不可用" : "Quote unavailable")}</span>}
      </div>
      <div className="text-right text-xs leading-5 text-[var(--fg-tertiary)]"><div>{query.data?.source || (zh ? "公开行情" : "Public quotes")} · {zh ? "可能延迟" : "May be delayed"}</div><div>{zh ? "行情时点" : "Quote time"} {time}</div></div>
    </div>
    <dl className="grid grid-cols-6 gap-4 mt-4 mb-0 text-xs tabular-nums">
      {[
        { label: zh ? "今开" : "Open", values: [quoteNumber(quote?.open)] },
        { label: zh ? "最高 / 最低" : "High / Low", values: [quoteNumber(quote?.high), "/", quoteNumber(quote?.low)] },
        { label: zh ? "成交额" : "Turnover", values: [yuanAmount(quote?.turnoverYuan)] },
        { label: zh ? "总市值" : "Market cap", values: [yuanAmount(quote?.totalMarketCapYuan)] },
        { label: zh ? "市盈率" : "PE", values: [quoteNumber(quote?.peRatio)] },
        { label: zh ? "市净率" : "PB", values: [quoteNumber(quote?.pbRatio)] },
      ].map(({ label, values }) => (
        <div key={label} className="min-w-0">
          <dt className="text-[var(--fg-tertiary)] mb-1.5">{label}</dt>
          <dd className="m-0 flex flex-wrap gap-x-1 gap-y-1 font-medium text-[var(--fg-primary)]">
            {values.map((value, index) => <span key={index} className="whitespace-nowrap">{value}</span>)}
          </dd>
        </div>
      ))}
    </dl>
  </div>;
}
export function FinanceMarketPanel({ query, period, onPeriodChange, zh }: { query: UseQueryResult<StockSnapshot, Error>; period: StockPeriod; onPeriodChange: (period: StockPeriod) => void; zh: boolean }) {
  if (query.isPending) return <VSurface tone="panel" padding="normal" className="min-h-[370px] border border-[var(--vui-border-subtle)] rounded-lg" aria-busy="true"><span className="text-sm">{zh ? "价格走势" : "Price chart"}</span><div className="grid gap-6 pt-8"><VSkeleton /><VSkeleton /><VSkeleton /></div></VSurface>;
  if (query.isError) return <VStateSurface tone="error" title={zh ? "行情加载失败" : "Quotes unavailable"} actions={<VButton onPress={() => void query.refetch()}>{zh ? "重试" : "Retry"}</VButton>}>{query.error.message}</VStateSurface>;
  if (!query.data?.candles.length) return <VStateSurface tone={query.data?.candleError ? "error" : "empty"} title={zh ? "暂无 K 线数据" : "No chart data"} actions={<VButton onPress={() => void query.refetch()}>{zh ? "重试" : "Retry"}</VButton>}>{query.data?.candleError || undefined}</VStateSurface>;
  return <FinanceStockChart candles={query.data.candles} period={period} onPeriodChange={onPeriodChange} zh={zh} />;
}
