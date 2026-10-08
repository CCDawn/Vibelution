import styles from "./FinanceStockOverview.styles";
import type { UseQueryResult } from "@tanstack/react-query";
import { RefreshCw, Star, TrendingDown, TrendingUp } from "lucide-react";
import type { StockIdentity, StockPeriod, StockSnapshot } from "../../api/financialMarket";
import { VButton, VChip, VIconButton, VSkeleton, VStateSurface, VSurface } from "../../components/vui";
import { FinanceStockChart } from "./FinanceStockChart";
import { quoteNumber } from "./stockResearchModel";
import { quoteAmount, quoteCurrency } from "./financeMarketDisplay";

export function FinanceStockHeader({ stock, query, starred, onToggleStar, zh, compact = false }: { stock: StockIdentity; query: UseQueryResult<StockSnapshot, Error>; starred: boolean; onToggleStar: () => void; zh: boolean; compact?: boolean }) {
  const quote = query.data?.stock;
  const rising = (quote?.change ?? 0) >= 0;
  const time = quote?.timestamp?.trim() || "—";
  const provider = query.data?.source || (zh ? "公开行情" : "Public quotes");
  const fetchTime = query.data?.fetchedAt?.trim() || "—";
  const price = <div className={[compact ? styles.compactPriceRow : styles.priceRow, quote ? rising ? styles.rising : styles.falling : styles.unavailable].join(" ")}>
    <strong className={compact ? styles.compactPrice : styles.price}>{quoteNumber(quote?.price)}</strong>{quote ? <span className={styles.quoteState}>{quoteCurrency(quote, zh)}</span> : null}
    {quote ? <span className={compact ? styles.compactChange : styles.change}>{rising ? <TrendingUp size={16} /> : <TrendingDown size={16} />}{quote.change >= 0 ? "+" : ""}{quoteNumber(quote.change)}<span className={styles.changePercent}>{quote.changePercent >= 0 ? "+" : ""}{quoteNumber(quote.changePercent)}%</span></span> : <span className={styles.quoteState}>{query.isPending ? (zh ? "行情加载中" : "Loading quotes") : (zh ? "行情不可用" : "Quote unavailable")}</span>}
  </div>;
  const provenance = `${provider} · ${zh ? "可能延迟" : "May be delayed"} · ${zh ? "行情时点" : "Quote time"} ${time} · ${zh ? "上次成功抓取" : "Last successful fetch"} ${fetchTime}`;
  return <div className={compact ? styles.compactHeader : styles.header} data-finance-stock-header data-density={compact ? "compact" : "normal"}>
    <div className={styles.heading}>
      <div className={styles.identity}><h1 className={compact ? styles.compactName : styles.name} title={quote?.name || stock.name}>{quote?.name || stock.name}</h1><span className={styles.ticker}>{stock.ticker}</span><VChip>{quote?.market || stock.market}</VChip></div>
      {compact ? price : null}
      <div className={styles.actions}><VButton variant="ghost" icon={<Star size={15} fill={starred ? "currentColor" : "none"} />} aria-pressed={starred} onPress={onToggleStar}>{starred ? (zh ? "已自选" : "Following") : (zh ? "加入自选" : "Follow")}</VButton><VIconButton label={zh ? "刷新行情" : "Refresh quotes"} icon={<RefreshCw size={15} />} isDisabled={query.isFetching} onPress={() => void query.refetch()} /></div>
    </div>
    {compact ? <div className={styles.compactProvider} title={provenance}>{provenance}</div> : <div className={styles.priceHeading}>
      {price}
      <div className={styles.provider}>
        <div>{provider} · {zh ? "可能延迟" : "May be delayed"}</div>
        <div>{zh ? "行情时点" : "Quote time"} {time}</div>
        <div>{zh ? "上次成功抓取" : "Last successful fetch"} {fetchTime}</div>
      </div>
    </div>}
    {query.error && query.data ? <VStateSurface className={styles.refreshWarning} tone="error" density="compact" title={zh ? "刷新失败，当前仍显示上次成功获取的行情" : "Refresh failed; showing the last successfully fetched quotes"} actions={<VButton isDisabled={query.isFetching} onPress={() => void query.refetch()}>{zh ? "重试" : "Retry"}</VButton>}>{query.error.message}</VStateSurface> : null}
    {!compact ? <dl className={styles.facts}>
      {[
        { label: zh ? "今开" : "Open", values: [quoteNumber(quote?.open)] },
        { label: zh ? "最高 / 最低" : "High / Low", values: [quoteNumber(quote?.high), "/", quoteNumber(quote?.low)] },
        { label: zh ? "成交额" : "Turnover", values: [quoteAmount(quote, "turnover", zh)] },
        { label: zh ? "总市值" : "Market cap", values: [quoteAmount(quote, "marketCap", zh)] },
        { label: zh ? "市盈率" : "PE", values: [quoteNumber(quote?.peRatio)] },
        { label: zh ? "市净率" : "PB", values: [quoteNumber(quote?.pbRatio)] },
      ].map(({ label, values }) => (
        <div key={label} className={styles.fact}>
          <dt className={styles.factLabel}>{label}</dt>
          <dd className={styles.factValues}>
            {values.map((value, index) => <span key={index} className={styles.number}>{value}</span>)}
          </dd>
        </div>
      ))}
    </dl> : null}
  </div>;
}
export function FinanceMarketPanel({ query, period, onPeriodChange, zh }: { query: UseQueryResult<StockSnapshot, Error>; period: StockPeriod; onPeriodChange: (period: StockPeriod) => void; zh: boolean }) {
  if (query.isPending) return <VSurface tone="panel" padding="normal" className={styles.loadingPanel} aria-busy="true"><span className={styles.chartTitle}>{zh ? "价格走势" : "Price chart"}</span><div className={styles.loadingSkeleton}><VSkeleton /><VSkeleton /><VSkeleton /></div></VSurface>;
  if (query.isError && !query.data) return <VStateSurface tone="error" title={zh ? "行情加载失败" : "Quotes unavailable"} actions={<VButton onPress={() => void query.refetch()}>{zh ? "重试" : "Retry"}</VButton>}>{query.error.message}</VStateSurface>;
  if (!query.data?.candles.length) return <VStateSurface tone={query.data?.candleError ? "error" : "empty"} title={zh ? "暂无 K 线数据" : "No chart data"} actions={<VButton onPress={() => void query.refetch()}>{zh ? "重试" : "Retry"}</VButton>}>{query.data?.candleError || undefined}</VStateSurface>;
  return <FinanceStockChart key={`${query.data.stock.symbol}:${period}`} candles={query.data.candles} period={period} onPeriodChange={onPeriodChange} zh={zh} currency={query.data.stock.currency} adjustment={query.data.adjustment} />;
}
