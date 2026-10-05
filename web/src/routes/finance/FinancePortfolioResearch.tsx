import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Sparkles } from "lucide-react";
import { isFinancialPaperAccountNotOpened } from "../../api/financialPaper";
import {
  fetchFinancialPortfolioResearch,
  financialPortfolioKeys,
  type FinancialPortfolioCorrelation,
  type FinancialPortfolioPosition,
  type FinancialPortfolioResearch as PortfolioResearchData,
} from "../../api/financialPortfolio";
import type { FinancialAssistant } from "../../api/financialAssistant";
import type { StockIdentity } from "../../api/types/financialMarket";
import { VButton, VDenseTable, VMetricStrip, VStateSurface, VSurface, type VDenseTableColumn } from "../../components/vui";
import styles from "./FinancePortfolioResearch.styles";

export type FinancePortfolioResearchProps = {
  assistant: FinancialAssistant;
  zh: boolean;
  onSelectStock: (stock: StockIdentity) => void;
  onResearchPrompt: (text: string) => void;
  onOpenAccount?: () => void;
};

function formatYuan(value: string | null, zh: boolean): string {
  if (value === null || value === "") return "—";
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "—";
  return new Intl.NumberFormat(zh ? "zh-CN" : "en-US", {
    style: "currency",
    currency: "CNY",
    maximumFractionDigits: 2,
  }).format(amount);
}

function formatPercent(value: string | null): string {
  if (value === null) return "—";
  const amount = Number(value);
  return Number.isFinite(amount) ? `${amount.toFixed(2)}%` : "—";
}

function formatCorrelation(value: number): string {
  return `${value > 0 ? "+" : ""}${value.toFixed(3)}`;
}

function formatTimestamp(value: string, zh: boolean): string {
  if (!value) return zh ? "无报价时间" : "Quote time unavailable";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString(zh ? "zh-CN" : "en-US", { hour12: false, timeZone: "Asia/Shanghai" });
}

function valuationStatusText(position: FinancialPortfolioPosition, zh: boolean): string {
  if (position.valuationStatus === "fresh") return zh ? "报价有效" : "Mark current";
  if (position.valuationStatus === "stale") return zh ? "沿用旧报价" : "Using stale mark";
  return zh ? "估值缺失" : "Mark unavailable";
}

function positionStatusText(position: FinancialPortfolioPosition, zh: boolean): string {
  if (position.returnSeriesStatus === "available") return zh ? "日线已读" : "Daily series loaded";
  if (position.returnSeriesStatus === "unavailable") return zh ? "日线不可用" : "Daily series unavailable";
  if (position.returnSeriesStatus === "deadline") return zh ? "超出本次时限" : "Deadline reached";
  if (position.returnSeriesStatus === "capacity_skipped") return zh ? "并发繁忙，已跳过" : "Skipped at capacity";
  if (position.returnSeriesStatus === "limit_skipped") return zh ? "超出分析上限" : "Outside analysis limit";
  return zh ? "估值缺失" : "No usable mark";
}

function buildPositionPrompt(position: FinancialPortfolioPosition, zh: boolean): string {
  const header = zh
    ? `研究我的模拟持仓：${position.name}（${position.ticker}，${position.symbol}）。`
    : `Research my simulated holding: ${position.name} (${position.ticker}, ${position.symbol}).`;
  const details = zh
    ? `账本数量 ${position.quantity} 股；估值 ${formatYuan(position.marketValueYuan, true)}；最新标记价 ${formatYuan(position.markPriceYuan, true)}；账户权重 ${formatPercent(position.weightPercent)}；未实现盈亏 ${formatYuan(position.unrealizedPnlYuan, true)}。报价 ${position.quoteTimestamp || "缺失"}，采集于 ${position.quoteFetchedAt || "缺失"}，来源 ${position.source} ${position.sourceUrl}。`
    : `Ledger quantity ${position.quantity} shares; marked value ${formatYuan(position.marketValueYuan, false)}; mark price ${formatYuan(position.markPriceYuan, false)}; account weight ${formatPercent(position.weightPercent)}; unrealized P&L ${formatYuan(position.unrealizedPnlYuan, false)}. Quote time ${position.quoteTimestamp || "missing"}, fetched ${position.quoteFetchedAt || "missing"}; source ${position.source} ${position.sourceUrl}.`;
  const instruction = zh
    ? "先核验当前行情、公告和财报证据，区分事实与判断，指出持仓集中风险与数据缺口；不要把模拟账本当成真实账户，不下单、不承诺收益。"
    : "First verify current quote, announcement, and financial-statement evidence. Separate facts from judgments, note concentration risk and missing data, and do not treat the simulation ledger as a real account, place orders, or promise returns.";
  return `${header}\n${details}\n${instruction}`;
}

function buildPortfolioPrompt(data: PortfolioResearchData, zh: boolean): string {
  const positions = data.positions.map((position) =>
    `${position.name} (${position.ticker}/${position.symbol}): ${position.quantity} shares; value ${formatYuan(position.marketValueYuan, zh)}; weight ${formatPercent(position.weightPercent)}; unrealized P&L ${formatYuan(position.unrealizedPnlYuan, zh)}; valuation ${position.valuationStatus}; quote ${position.quoteTimestamp || "missing"} from ${position.source}.`,
  );
  const pairs = data.correlations.map((pair) =>
    `${pair.firstName} (${pair.firstSymbol}) / ${pair.secondName} (${pair.secondSymbol}): Pearson ${formatCorrelation(pair.correlation)}, ${pair.observations} common sessions (${pair.startDate} to ${pair.endDate}).`,
  );
  const heading = zh ? "请对以下模拟持仓做组合诊断。" : "Review the following simulated portfolio.";
  const account = zh
    ? `净资产快照 ${formatYuan(data.summary.equityYuan, true)}；现金 ${formatYuan(data.summary.cashYuan, true)}；持仓市值 ${formatYuan(data.summary.marketValueYuan, true)}；现金权重 ${formatPercent(data.summary.cashWeightPercent)}；最大单股权重 ${formatPercent(data.summary.maxPositionWeightPercent)}；前三大持仓权重 ${formatPercent(data.summary.topThreeWeightPercent)}。估值完整：${data.summary.valuationComplete ? "是" : "否"}。`
    : `Snapshot equity ${formatYuan(data.summary.equityYuan, false)}; cash ${formatYuan(data.summary.cashYuan, false)}; holdings value ${formatYuan(data.summary.marketValueYuan, false)}; cash weight ${formatPercent(data.summary.cashWeightPercent)}; largest holding ${formatPercent(data.summary.maxPositionWeightPercent)}; top-three weight ${formatPercent(data.summary.topThreeWeightPercent)}. Valuation complete: ${data.summary.valuationComplete ? "yes" : "no"}.`;
  const correlation = zh
    ? `相关性来自 ${data.source} 前复权日收益，采样 ${data.coverage.minimumCorrelationObservations} 个共同交易日为最低门槛；${data.summary.correlationPairCount} 组可用、${data.summary.insufficientCorrelationPairCount} 组样本不足、${data.summary.unavailableCorrelationPairCount} 组行情不可用。`
    : `Correlations use ${data.source} forward-adjusted daily returns with a minimum of ${data.coverage.minimumCorrelationObservations} common sessions; ${data.summary.correlationPairCount} pairs are available, ${data.summary.insufficientCorrelationPairCount} have too few samples, and ${data.summary.unavailableCorrelationPairCount} are unavailable.`;
  const scope = zh
    ? `行情快照生成于 ${data.generatedAt}。本次读取 ${data.coverage.selectedPositionCount} / ${data.coverage.eligiblePositionCount} 只可估值持仓，另有 ${data.coverage.budgetSkippedPositionCount} 只超出研究预算。`
    : `Snapshot generated ${data.generatedAt}. This run selected ${data.coverage.selectedPositionCount} of ${data.coverage.eligiblePositionCount} valued holdings; ${data.coverage.budgetSkippedPositionCount} exceeded the analysis budget.`;
  const instruction = zh
    ? "检查仓位集中、真实共同样本的联动风险、报价时效和估值缺口。明确哪些结论受数据预算或缺失影响；所有结论标明事实/推断，不给保证收益或自动交易指令。"
    : "Assess position concentration, co-movement from actual overlapping samples, quote freshness, and valuation gaps. State where missing data or the analysis budget limits conclusions; label facts and inferences and do not promise returns or issue automatic trade instructions.";
  return [heading, account, scope, correlation, "持仓：", positions.join("\n"), "可用相关性样本：", pairs.length ? pairs.join("\n") : zh ? "没有达到样本门槛的配对。" : "No pairs met the sample threshold.", `来源与口径：${data.source} ${data.sourceUrl}；${data.adjustment} ${data.period}；${data.notice}`, instruction].join("\n\n");
}

export function FinancePortfolioResearch({ assistant, zh, onSelectStock, onResearchPrompt, onOpenAccount }: FinancePortfolioResearchProps) {
  const query = useQuery({
    queryKey: financialPortfolioKeys.research(assistant.agentId),
    queryFn: ({ signal }) => fetchFinancialPortfolioResearch(assistant.agentId, { signal }),
    staleTime: 30_000,
    retry: false,
  });

  const positionColumns = useMemo<VDenseTableColumn<FinancialPortfolioPosition>[]>(() => [
    {
      id: "stock", header: zh ? "持仓" : "Holding", fill: true, minWidth: 156,
      render: (row) => <VButton variant="ghost" className={styles.stockButton} onPress={() => onSelectStock({ symbol: row.symbol, ticker: row.ticker, name: row.name, market: row.market })}>
        <span className={styles.stockIdentity}><strong>{row.name}</strong><small>{row.ticker} · {row.market}</small><small>{valuationStatusText(row, zh)} · {formatTimestamp(row.quoteTimestamp, zh)}</small></span>
      </VButton>,
    },
    { id: "quantity", header: zh ? "数量" : "Shares", width: 82, minWidth: 72, align: "right", render: (row) => row.quantity.toLocaleString() },
    { id: "value", header: zh ? "市值" : "Value", width: 132, minWidth: 116, align: "right", render: (row) => formatYuan(row.marketValueYuan, zh) },
    { id: "weight", header: zh ? "权重" : "Weight", width: 82, minWidth: 72, align: "right", render: (row) => formatPercent(row.weightPercent) },
    { id: "pnl", header: zh ? "浮动盈亏" : "Unrealized", width: 132, minWidth: 116, align: "right", render: (row) => formatYuan(row.unrealizedPnlYuan, zh) },
    {
      id: "analysis", header: zh ? "日线状态" : "Series", width: 122, minWidth: 108,
      render: (row) => <span className={styles.seriesStatus} title={`${row.source} · ${row.quoteTimestamp || (zh ? "无报价时间" : "Quote time unavailable")}`}>{positionStatusText(row, zh)}</span>,
    },
    {
      id: "research", header: zh ? "操作" : "Actions", width: 112, minWidth: 104,
      render: (row) => <VButton variant="secondary" className={styles.smallButton} onPress={() => onResearchPrompt(buildPositionPrompt(row, zh))}>{zh ? "个股研读" : "Research"}</VButton>,
    },
  ], [onResearchPrompt, onSelectStock, zh]);

  const correlationColumns = useMemo<VDenseTableColumn<FinancialPortfolioCorrelation>[]>(() => [
    {
      id: "pair", header: zh ? "股票配对" : "Pair", fill: true, minWidth: 200,
      render: (row) => <span className={styles.pairNames}>{row.firstName} <small>{row.firstSymbol}</small> · {row.secondName} <small>{row.secondSymbol}</small></span>,
    },
    { id: "coefficient", header: zh ? "Pearson r" : "Pearson r", width: 96, minWidth: 88, align: "right", render: (row) => formatCorrelation(row.correlation) },
    { id: "observations", header: zh ? "共同交易日" : "Sessions", width: 100, minWidth: 90, align: "right", render: (row) => row.observations },
    { id: "period", header: zh ? "样本区间" : "Sample range", width: 194, minWidth: 180, render: (row) => `${row.startDate} — ${row.endDate}` },
  ], [zh]);

  if (query.isPending) {
    return <div className={styles.page}><VStateSurface tone="loading" busy title={zh ? "正在读取模拟组合与日线样本" : "Loading simulated holdings and daily samples"}>{zh ? "只读取模拟账本和有限的公开行情。" : "Reading the paper ledger and a bounded set of public market data."}</VStateSurface></div>;
  }
  if (query.isError && isFinancialPaperAccountNotOpened(query.error)) {
    return <div className={styles.page}><VStateSurface
      tone="empty"
      title={zh ? "尚未开设模拟账户" : "Paper account not opened"}
      actions={onOpenAccount ? <VButton variant="primary" onPress={onOpenAccount}>{zh ? "前往模拟账户" : "Go to paper account"}</VButton> : undefined}
    >{zh ? "组合研究读取模拟账本；请先前往模拟账户查看或开设账户。此页面不会自动创建账户。" : "Portfolio research reads the paper ledger. Go to the paper account to review or open it; this page does not create accounts automatically."}</VStateSurface></div>;
  }
  if (query.isError) {
    return <div className={styles.page}><VStateSurface tone="error" title={zh ? "组合研究暂不可用" : "Portfolio research unavailable"} actions={<VButton onPress={() => void query.refetch()}>{zh ? "重试" : "Retry"}</VButton>}>{query.error.message}</VStateSurface></div>;
  }
  if (!query.data) return null;

  const data = query.data;
  const metrics = [
    { id: "equity", label: zh ? "净资产快照" : "Snapshot equity", value: formatYuan(data.summary.equityYuan, zh) },
    { id: "cash", label: zh ? "现金权重" : "Cash weight", value: formatPercent(data.summary.cashWeightPercent) },
    { id: "largest", label: zh ? "最大单股权重" : "Largest holding", value: formatPercent(data.summary.maxPositionWeightPercent) },
    { id: "top-three", label: zh ? "前三大权重" : "Top-three weight", value: formatPercent(data.summary.topThreeWeightPercent) },
    { id: "correlations", label: zh ? "有效相关性" : "Valid pairs", value: String(data.summary.correlationPairCount) },
  ];

  return <div className={styles.page}>
    <header className={styles.header}>
      <div className={styles.titleGroup}>
        <h2 className={styles.title}>{zh ? "组合研究" : "Portfolio research"}</h2>
        <span className={styles.meta}>{zh ? "模拟账本 · 只读分析" : "Paper ledger · read-only"}</span>
      </div>
      <div className={styles.actions}>
        <span className={styles.meta}>{zh ? `生成于 ${formatTimestamp(data.generatedAt, true)}` : `Generated ${formatTimestamp(data.generatedAt, false)}`}</span>
        <VButton variant="secondary" icon={<RefreshCw size={14} />} isPending={query.isFetching} onPress={() => void query.refetch()}>{zh ? "刷新" : "Refresh"}</VButton>
        <VButton variant="primary" icon={<Sparkles size={14} />} onPress={() => onResearchPrompt(buildPortfolioPrompt(data, zh))}>{zh ? "生成组合诊断草稿" : "Draft portfolio review"}</VButton>
      </div>
    </header>

    <VMetricStrip ariaLabel={zh ? "模拟组合摘要" : "Simulated portfolio summary"} metrics={metrics} />

    {!data.summary.valuationComplete ? <VStateSurface tone="unavailable" density="compact" title={zh ? "估值不完整，组合权重暂不可用" : "Valuation is partial; portfolio weights are unavailable"}>
      {zh ? `已估值 ${data.summary.valuedPositionCount} / ${data.summary.positionCount} 只持仓。缺失估值的仓位不会被当作零值参与权重计算。` : `${data.summary.valuedPositionCount} of ${data.summary.positionCount} holdings are valued. Missing marks are not treated as zero when calculating weights.`}
    </VStateSurface> : null}

    <section className={styles.workspace}>
      <VSurface className={styles.panel}>
        <div className={styles.panelHeader}>
          <h3 className={styles.panelTitle}>{zh ? "模拟持仓" : "Paper holdings"}</h3>
          <span className={styles.meta}>{data.summary.positionCount} {zh ? "只" : "positions"} · {zh ? `已估值 ${data.summary.valuedPositionCount}` : `${data.summary.valuedPositionCount} valued`}</span>
        </div>
        <VDenseTable<FinancialPortfolioPosition>
          ariaLabel={zh ? "模拟持仓及账户权重" : "Simulated holdings and account weights"}
          columns={positionColumns}
          rows={data.positions}
          getRowKey={(row) => row.symbol}
          emptyText={zh ? "模拟账户暂无持仓" : "No open paper positions"}
          resizable
        />
        <p className={styles.helper}>{zh ? "估值时间按每只股票的报价时间展示；个股研读会把持仓快照作为草稿提交到原生会话。" : "Marks retain per-stock quote times. Stock research sends the holding snapshot as a draft to the native Session."}</p>
      </VSurface>

      <VSurface className={styles.panel}>
        <div className={styles.panelHeader}>
          <h3 className={styles.panelTitle}>{zh ? "共同交易日相关性" : "Common-session correlation"}</h3>
          <span className={styles.meta}>{data.coverage.candleLoadedPositionCount} / {data.coverage.eligiblePositionCount} {zh ? "只读到日线" : "series loaded"}</span>
        </div>
        <p className={styles.helper}>{zh ? `以 ${data.source} ${data.adjustment} 日线收盘收益的 Pearson 相关系数计算；至少 ${data.coverage.minimumCorrelationObservations} 个共同交易日才展示。` : `Pearson correlation of ${data.source} ${data.adjustment} daily close returns; pairs require at least ${data.coverage.minimumCorrelationObservations} common sessions.`}</p>
        <VDenseTable<FinancialPortfolioCorrelation>
          ariaLabel={zh ? "样本充分的持仓相关性配对" : "Holding correlation pairs with sufficient samples"}
          columns={correlationColumns}
          rows={data.correlations}
          getRowKey={(row) => `${row.firstSymbol}:${row.secondSymbol}`}
          emptyText={zh ? "暂无达到共同样本门槛的配对" : "No pairs met the common-sample threshold"}
          resizable
        />
        <div className={styles.coverage}>
          <span>{zh ? `样本不足 ${data.summary.insufficientCorrelationPairCount} 组` : `${data.summary.insufficientCorrelationPairCount} pairs with too few samples`}</span>
          <span>{zh ? `行情不可用 ${data.summary.unavailableCorrelationPairCount} 组` : `${data.summary.unavailableCorrelationPairCount} unavailable pairs`}</span>
          <span>{zh ? `预算跳过 ${data.coverage.budgetSkippedPositionCount} 只` : `${data.coverage.budgetSkippedPositionCount} holdings outside budget`}</span>
          <span>{zh ? `超时跳过 ${data.coverage.deadlineSkippedPositionCount} 只` : `${data.coverage.deadlineSkippedPositionCount} skipped at deadline`}</span>
        </div>
        <p className={styles.helper}>{zh ? `相关性分析上限 ${data.coverage.maxAnalyzedPositions} 只持仓，并发读取 ${data.coverage.maxConcurrentFetches} 只，时限 ${data.coverage.deadlineSeconds} 秒。` : `Analysis is capped at ${data.coverage.maxAnalyzedPositions} holdings, ${data.coverage.maxConcurrentFetches} concurrent reads, and ${data.coverage.deadlineSeconds} seconds.`}</p>
      </VSurface>
    </section>

    <footer className={styles.provenance}>
      <span>{data.source} · {data.adjustment} {data.period} · {formatTimestamp(data.generatedAt, zh)}</span>
      <a href={data.sourceUrl} target="_blank" rel="noreferrer">{zh ? "行情来源" : "Market source"}</a>
      <span>{data.notice}</span>
    </footer>
  </div>;
}
