import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, ChartPie, ClipboardList, FileText, History, LayoutDashboard, RefreshCw, Search, Wallet } from "lucide-react";
import { fetchFinancialMarketQuotes, financialResearchKeys } from "../../api/financialResearch";
import { fetchFinancialResearchBatches, fetchFinancialResearchSchedules } from "../../api/financialJobs";
import { queryKeys } from "../../api/queryKeys";
import type { FinancialAssistant } from "../../api/financialAssistant";
import type { FinancialMarketQuoteResult } from "../../api/types/financialResearch";
import type { SessionSummary } from "../../api/types";
import type { StockIdentity } from "../../api/financialMarket";
import {
  VButton,
  VChip,
  VDenseTable,
  VMetricStrip,
  VStateSurface,
  VSurface,
  VSkeleton,
  type VDenseTableColumn,
} from "../../components/vui";
import { ACTIVE_FINANCIAL_BATCH_STATUSES } from "./financialJobModel";
import { quoteCurrency } from "./financeMarketDisplay";
import { researchRecordStatus } from "./stockResearchModel";
import styles from "./FinanceDashboard.styles";

export type FinanceDashboardArea = "workspace" | "screen" | "reports" | "tasks" | "account" | "portfolio" | "review";

export type FinanceDashboardProps = {
  assistant: FinancialAssistant;
  watchlist: StockIdentity[];
  recentResearch: SessionSummary[];
  onNavigate: (area: FinanceDashboardArea) => void;
  onSelectStock: (stock: StockIdentity) => void;
  onOpenResearch: (record: SessionSummary) => void;
  onRefresh?: () => void | Promise<void>;
  zh: boolean;
};

type QuoteRow = { stock: StockIdentity; result: FinancialMarketQuoteResult | null };

function formatNumber(value: number | null | undefined, digits = 2, zh = true): string {
  return value === null || value === undefined || !Number.isFinite(value)
    ? "—"
    : value.toLocaleString(zh ? "zh-CN" : "en-US", { maximumFractionDigits: digits });
}

function formatChange(value: number | null | undefined, zh: boolean): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${formatNumber(value, 2, zh)}%`;
}

function formatUpdatedAt(value: string, zh: boolean): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? (zh ? "时间未知" : "Time unavailable")
    : date.toLocaleTimeString(zh ? "zh-CN" : "en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function statusLabel(assistant: FinancialAssistant, zh: boolean): { label: string; tone: "neutral" | "success" | "warning" } {
  if (assistant.status !== "active") return { label: zh ? "助手未启用" : "Assistant inactive", tone: "warning" };
  if (assistant.setupStatus !== "ready") return { label: zh ? "配置待完成" : "Setup incomplete", tone: "warning" };
  if (assistant.modelStatus === "configured_unverified") return { label: zh ? "模型已配置 · 待验证" : "Model configured · unverified", tone: "neutral" };
  return { label: zh ? "模型未配置" : "Model not configured", tone: "warning" };
}

function sessionTone(record: SessionSummary): "neutral" | "success" | "warning" {
  const status = researchRecordStatus(record, false);
  if (["Failed", "Stopped", "Needs continuation"].includes(status)) return "warning";
  if (status === "Completed") return "success";
  return "neutral";
}

export function FinanceDashboard({
  assistant,
  watchlist,
  recentResearch,
  onNavigate,
  onSelectStock,
  onOpenResearch,
  onRefresh,
  zh,
}: FinanceDashboardProps) {
  const symbols = useMemo(() => watchlist.map((stock) => stock.symbol).slice(0, 50), [watchlist]);
  const quotes = useQuery({
    queryKey: financialResearchKeys.quotes(symbols),
    queryFn: ({ signal }) => fetchFinancialMarketQuotes(symbols, { signal }),
    enabled: symbols.length > 0,
    staleTime: 30_000,
    retry: false,
  });
  const batches = useQuery({
    queryKey: queryKeys.financialResearchBatches(assistant.agentId),
    queryFn: async ({ signal }) => {
      const result = await fetchFinancialResearchBatches(assistant.agentId, { signal });
      if (result.assistantAgentId !== assistant.agentId || result.batches.some((item) => item.assistantAgentId !== assistant.agentId)) {
        throw new Error(zh ? "批次归属不匹配，请刷新" : "Batch owner mismatch; refresh");
      }
      return result;
    },
    enabled: Boolean(assistant.agentId),
    staleTime: 3_000,
    retry: false,
  });
  const schedules = useQuery({
    queryKey: queryKeys.financialResearchSchedules(assistant.agentId),
    queryFn: async ({ signal }) => {
      const result = await fetchFinancialResearchSchedules(assistant.agentId, { signal });
      if (result.assistantAgentId !== assistant.agentId || result.schedules.some((item) => item.assistantAgentId !== assistant.agentId)) {
        throw new Error(zh ? "计划归属不匹配，请刷新" : "Schedule owner mismatch; refresh");
      }
      return result;
    },
    enabled: Boolean(assistant.agentId),
    staleTime: 10_000,
    retry: false,
  });

  const quoteBySymbol = new Map((quotes.data?.items ?? []).map((item) => [item.symbol, item]));
  const quoteRows: QuoteRow[] = watchlist.slice(0, 50).map((stock) => ({ stock, result: quoteBySymbol.get(stock.symbol) ?? null }));
  const batchRows = batches.data?.batches ?? [];
  const runningBatches = batchRows.filter((batch) => ACTIVE_FINANCIAL_BATCH_STATUSES.has(batch.status)).length;
  const enabledSchedules = (schedules.data?.schedules ?? []).filter((item) => item.enabled && item.execution.kind !== "now").length;
  const assistantState = statusLabel(assistant, zh);

  const quoteColumns = useMemo<VDenseTableColumn<QuoteRow>[]>(() => [
    {
      id: "stock", header: zh ? "股票" : "Stock", fill: true, minWidth: 140,
      render: (row) => <VButton variant="ghost" className={styles.stockButton} onPress={() => { onSelectStock(row.stock); onNavigate("workspace"); }}>
        <span className={styles.stockIdentity}><strong>{row.stock.name}</strong><small>{row.stock.ticker} · {row.stock.market}</small></span>
      </VButton>,
    },
    { id: "price", header: zh ? "最新价" : "Price", width: 94, align: "right", render: (row) => row.result?.quote ? <span className={styles.number}>{formatNumber(row.result.quote.price, 3, zh)} {quoteCurrency(row.result.quote, zh)}</span> : <span className={styles.number}>—</span> },
    {
      id: "change", header: zh ? "涨跌幅" : "Change", width: 98, align: "right",
      render: (row) => {
        const change = row.result?.quote?.changePercent;
        const tone = change === null || change === undefined ? styles.muted : change >= 0 ? styles.rise : styles.fall;
        return <span className={`${styles.number} ${tone}`}>{formatChange(change, zh)}</span>;
      },
    },
    { id: "pe", header: "PE", width: 78, align: "right", render: (row) => <span className={styles.number}>{formatNumber(row.result?.quote?.peRatio, 2, zh)}</span> },
  ], [onNavigate, onSelectStock, zh]);

  async function refresh() {
    await Promise.allSettled([
      quotes.refetch(), batches.refetch(), schedules.refetch(), Promise.resolve(onRefresh?.()),
    ]);
  }

  return <main className={styles.page} data-finance-dashboard>
    <div className={styles.heading}>
      <h1>{zh ? "市场概览" : "Market overview"}</h1>
      <VButton variant="ghost" icon={<RefreshCw size={14} />} isPending={quotes.isFetching || batches.isFetching || schedules.isFetching} onPress={() => void refresh()}>{zh ? "刷新" : "Refresh"}</VButton>
    </div>
    <div className={styles.grid}>
      <section className={styles.mainColumn} aria-label={zh ? "自选行情和最近研究" : "Watchlist and recent research"}>
        <VSurface className={styles.panel} padding="normal" ariaLabel={zh ? "自选行情" : "Watchlist quotes"}>
          <div className={styles.panelHeading}><h2>{zh ? "自选行情" : "Watchlist"}</h2><span>{watchlist.length}</span></div>
          {!watchlist.length ? <VStateSurface density="compact" tone="empty" title={zh ? "暂无自选股票" : "No stocks followed"}>{zh ? "在股票研究中搜索并关注股票。" : "Search and follow stocks from research."}</VStateSurface>
            : quotes.isError ? <VStateSurface density="compact" tone="error" title={zh ? "自选行情暂不可用" : "Quotes unavailable"} actions={<VButton onPress={() => void quotes.refetch()}>{zh ? "重试" : "Retry"}</VButton>} />
              : quotes.isPending ? <div className={styles.skeleton} aria-label={zh ? "加载自选行情" : "Loading watchlist quotes"}><VSkeleton /><VSkeleton /><VSkeleton /></div>
                : <>
                  <div className={styles.tableWrap}><VDenseTable ariaLabel={zh ? "自选股票行情" : "Watchlist market quotes"} columns={quoteColumns} rows={quoteRows} getRowKey={(row) => row.stock.symbol} resizable emptyText={zh ? "暂无行情" : "No quotes"} /></div>
                  <div className={styles.quoteFooter}><span>{quotes.data?.source ?? ""} · {quotes.data ? formatUpdatedAt(quotes.data.fetchedAt, zh) : "—"}</span><VButton variant="ghost" onPress={() => onNavigate("screen")}>{zh ? "智能选股" : "Stock screener"}</VButton></div>
                </>}
        </VSurface>
        <VSurface className={styles.panel} padding="normal" ariaLabel={zh ? "最近研究" : "Recent research"}>
          <div className={styles.panelHeading}><h2>{zh ? "最近研究" : "Recent research"}</h2><VButton variant="ghost" onPress={() => onNavigate("reports")}>{zh ? "全部" : "All"}</VButton></div>
          {!recentResearch.length ? <VStateSurface density="compact" tone="empty" title={zh ? "暂无研究记录" : "No research yet"}>{zh ? "发起股票研究后，记录会显示在这里。" : "Start a stock study to see it here."}</VStateSurface>
            : <div className={styles.recentList}>{recentResearch.slice(0, 5).map((record) => <VButton key={record.id} variant="ghost" contentLayout="plain" className={styles.recentRow} onPress={() => onOpenResearch(record)}>
              <span className={styles.recentTitle}><strong>{record.title || record.taskSummary || (zh ? "股票研究" : "Stock research")}</strong><small>{record.lastActive || record.updatedAt}</small></span>
              <VChip tone={sessionTone(record)}>{researchRecordStatus(record, zh)}</VChip>
            </VButton>)}</div>}
        </VSurface>
      </section>
      <aside className={styles.sideColumn} aria-label={zh ? "助手状态和快捷入口" : "Assistant status and shortcuts"}>
        <VSurface className={styles.panel} padding="normal" ariaLabel={zh ? "智能体状态" : "Assistant status"}>
          <div className={styles.panelHeading}><h2>{zh ? "炒股智能体" : "Stock assistant"}</h2><VChip tone={assistantState.tone}>{assistantState.label}</VChip></div>
          <div className={styles.statusRows}>
            <span>{zh ? "行情" : "Quotes"}<strong>{assistant.marketDataStatus === "public_quotes" ? (zh ? "公开行情" : "Public data") : (zh ? "不可用" : "Unavailable")}</strong></span>
            <span>{zh ? "研究资料" : "Research sources"}<strong>{assistant.knowledgeReadable ? (zh ? "可读取" : "Readable") : (zh ? "不可用" : "Unavailable")}</strong></span>
            <span>{zh ? "外部财报库" : "External filings library"}<strong>{assistant.reportStatus === "configured" ? (zh ? "已配置" : "Configured") : (zh ? "未接入" : "Not connected")}</strong></span>
          </div>
        </VSurface>
        <VSurface className={styles.panel} padding="normal" ariaLabel={zh ? "批次和计划" : "Research jobs"}>
          <div className={styles.panelHeading}><h2>{zh ? "研究任务" : "Research jobs"}</h2><Activity size={15} aria-hidden="true" /></div>
          {batches.isError || schedules.isError ? <VStateSurface density="compact" tone="error" title={zh ? "任务状态不可用" : "Job status unavailable"} actions={<VButton onPress={() => void refresh()}>{zh ? "重试" : "Retry"}</VButton>} />
            : batches.isPending || schedules.isPending ? <div className={styles.skeleton} aria-label={zh ? "读取任务状态" : "Loading job status"}><VSkeleton /><VSkeleton /></div>
              : <VMetricStrip ariaLabel={zh ? "批次与定时计划" : "Batches and schedules"} metrics={[
                { id: "active-batches", label: zh ? "进行中批次" : "Active batches", value: String(runningBatches) },
                { id: "enabled-schedules", label: zh ? "启用计划" : "Enabled schedules", value: String(enabledSchedules) },
              ]} />}
          <div className={styles.shortcuts}>
            <VButton variant="secondary" icon={<LayoutDashboard size={14} />} onPress={() => onNavigate("workspace")}>{zh ? "股票研究" : "Stock research"}</VButton>
            <VButton variant="secondary" icon={<Search size={14} />} onPress={() => onNavigate("screen")}>{zh ? "智能选股" : "Stock screener"}</VButton>
            <VButton variant="secondary" icon={<FileText size={14} />} onPress={() => onNavigate("reports")}>{zh ? "报告中心" : "Reports"}</VButton>
            <VButton variant="secondary" icon={<ClipboardList size={14} />} onPress={() => onNavigate("tasks")}>{zh ? "研究任务" : "Research tasks"}</VButton>
            <VButton variant="secondary" icon={<Wallet size={14} />} onPress={() => onNavigate("account")}>{zh ? "模拟账户" : "Paper account"}</VButton>
            <VButton variant="secondary" icon={<ChartPie size={14} />} onPress={() => onNavigate("portfolio")}>{zh ? "组合研究" : "Portfolio research"}</VButton>
            <VButton variant="secondary" icon={<History size={14} />} onPress={() => onNavigate("review")}>{zh ? "交易复盘" : "Trading review"}</VButton>
          </div>
        </VSurface>
      </aside>
    </div>
  </main>;
}
