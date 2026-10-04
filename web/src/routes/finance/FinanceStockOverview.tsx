import styles from "./FinanceStockOverview.styles";
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
  return <div className={styles.header} data-finance-stock-header>
    <div className={styles.heading}>
      <div className={styles.identity}><h1 className={styles.name}>{quote?.name || stock.name}</h1><span className={styles.ticker}>{stock.ticker}</span><VChip>{quote?.market || stock.market}</VChip></div>
      <div className={styles.actions}><VButton variant="ghost" icon={<Star size={15} fill={starred ? "currentColor" : "none"} />} aria-pressed={starred} onPress={onToggleStar}>{starred ? (zh ? "已自选" : "Following") : (zh ? "加入自选" : "Follow")}</VButton><VIconButton label={zh ? "刷新行情" : "Refresh quotes"} icon={<RefreshCw size={15} />} isDisabled={query.isFetching} onPress={() => void query.refetch()} /></div>
    </div>
    <div className={styles.priceHeading}>
      <div className={[styles.priceRow, quote ? rising ? styles.rising : styles.falling : styles.unavailable].join(" ")}>
        <strong className={styles.price}>{quoteNumber(quote?.price)}</strong>
        {quote ? <span className={styles.change}>{rising ? <TrendingUp size={16} /> : <TrendingDown size={16} />}{quote.change >= 0 ? "+" : ""}{quoteNumber(quote.change)}<span className={styles.changePercent}>{quote.changePercent >= 0 ? "+" : ""}{quoteNumber(quote.changePercent)}%</span></span> : <span className={styles.quoteState}>{query.isPending ? (zh ? "行情加载中" : "Loading quotes") : (zh ? "行情不可用" : "Quote unavailable")}</span>}
      </div>
      <div className={styles.provider}><div>{query.data?.source || (zh ? "公开行情" : "Public quotes")} · {zh ? "可能延迟" : "May be delayed"}</div><div>{zh ? "行情时点" : "Quote time"} {time}</div></div>
    </div>
    <dl className={styles.facts}>
      {[
        { label: zh ? "今开" : "Open", values: [quoteNumber(quote?.open)] },
        { label: zh ? "最高 / 最低" : "High / Low", values: [quoteNumber(quote?.high), "/", quoteNumber(quote?.low)] },
        { label: zh ? "成交额" : "Turnover", values: [yuanAmount(quote?.turnoverYuan)] },
        { label: zh ? "总市值" : "Market cap", values: [yuanAmount(quote?.totalMarketCapYuan)] },
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
    </dl>
  </div>;
}
export function FinanceMarketPanel({ query, period, onPeriodChange, zh }: { query: UseQueryResult<StockSnapshot, Error>; period: StockPeriod; onPeriodChange: (period: StockPeriod) => void; zh: boolean }) {
  if (query.isPending) return <VSurface tone="panel" padding="normal" className={styles.loadingPanel} aria-busy="true"><span className={styles.chartTitle}>{zh ? "价格走势" : "Price chart"}</span><div className={styles.loadingSkeleton}><VSkeleton /><VSkeleton /><VSkeleton /></div></VSurface>;
  if (query.isError) return <VStateSurface tone="error" title={zh ? "行情加载失败" : "Quotes unavailable"} actions={<VButton onPress={() => void query.refetch()}>{zh ? "重试" : "Retry"}</VButton>}>{query.error.message}</VStateSurface>;
  if (!query.data?.candles.length) return <VStateSurface tone={query.data?.candleError ? "error" : "empty"} title={zh ? "暂无 K 线数据" : "No chart data"} actions={<VButton onPress={() => void query.refetch()}>{zh ? "重试" : "Retry"}</VButton>}>{query.data?.candleError || undefined}</VStateSurface>;
  return <FinanceStockChart candles={query.data.candles} period={period} onPeriodChange={onPeriodChange} zh={zh} />;
}
