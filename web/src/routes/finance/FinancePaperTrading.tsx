import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDownToLine, ArrowUpFromLine, CalendarDays, CircleAlert, RefreshCw, Sparkles, Wallet } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import { fetchFinancialStock, financialMarketKeys } from "../../api/financialMarket";
import {
  fetchFinancialPaperAccount,
  fetchFinancialPaperReview,
  financialPaperKeys,
  isFinancialPaperAccountNotOpened,
  openFinancialPaperAccount,
  submitFinancialPaperOrder,
} from "../../api/financialPaper";
import type { FinancialAssistant } from "../../api/financialAssistant";
import type { StockIdentity } from "../../api/types/financialMarket";
import type { PaperAccountSnapshot, PaperOrder, PaperPosition, PaperReviewDay, PaperSide } from "../../api/types/financialPaper";
import { VButton, VChip, VDenseTable, VInput, VMetricStrip, VSelect, VSkeleton, VStateSurface, VSurface } from "../../components/vui";
import styles from "./FinancePaperTrading.styles";

export type FinancePaperTradingMode = "account" | "review";

export type FinancePaperTradingProps = {
  assistant: FinancialAssistant;
  stock: StockIdentity;
  zh: boolean;
  mode: FinancePaperTradingMode;
  onResearchPrompt: (text: string) => void;
};

const RECENT_ORDER_LIMIT = 50;
const weekdayLabels = ["一", "二", "三", "四", "五", "六", "日"];

function beijingMonthNow(): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
  }).formatToParts(new Date());
  const year = parts.find((part) => part.type === "year")?.value ?? "2026";
  const month = parts.find((part) => part.type === "month")?.value ?? "01";
  return `${year}-${month}`;
}

function newClientOrderId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (char) => {
    const value = Math.floor(Math.random() * 16);
    return (char === "x" ? value : (value & 0x3) | 0x8).toString(16);
  });
}

function formatYuan(value: string | null | undefined, zh: boolean): string {
  if (value === null || value === undefined || value === "") return "—";
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "—";
  return new Intl.NumberFormat(zh ? "zh-CN" : "en-US", {
    style: "currency",
    currency: "CNY",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

function signedTone(value: string | null | undefined): string {
  const amount = Number(value);
  if (!Number.isFinite(amount) || amount === 0) return styles.neutral;
  return amount > 0 ? styles.positive : styles.negative;
}

function estimatePaperTrade(priceYuan: number, quantity: number, side: PaperSide) {
  if (!Number.isFinite(priceYuan) || !Number.isSafeInteger(quantity) || quantity < 1) return null;
  const priceFen = Math.round(priceYuan * 100);
  const grossFen = priceFen * quantity;
  const commissionFen = Math.max(Math.round(grossFen * 0.0003), 500);
  const stampFen = side === "sell" ? Math.round(grossFen * 0.0005) : 0;
  const feesFen = commissionFen + stampFen;
  const cashImpactFen = side === "buy" ? -(grossFen + feesFen) : grossFen - feesFen;
  return {
    gross: (grossFen / 100).toFixed(2),
    fees: (feesFen / 100).toFixed(2),
    cashImpact: (cashImpactFen / 100).toFixed(2),
  };
}

function errorText(error: unknown, zh: boolean): string {
  if (error instanceof Error && error.message) return error.message;
  return zh ? "操作失败，请重试" : "The request failed. Try again.";
}

function monthDayCount(month: string): number {
  const [year, monthNumber] = month.split("-").map(Number);
  return new Date(Date.UTC(year, monthNumber, 0)).getUTCDate();
}

function monthOffsetMonday(month: string): number {
  const [year, monthNumber] = month.split("-").map(Number);
  return (new Date(Date.UTC(year, monthNumber - 1, 1)).getUTCDay() + 6) % 7;
}

function dailyMap(days: PaperReviewDay[]) {
  return new Map(days.map((day) => [Number(day.date.slice(-2)), day]));
}

function buildReviewPrompt(
  snapshot: PaperAccountSnapshot,
  zh: boolean,
  month?: string,
  days: PaperReviewDay[] = [],
  activeQuote?: { symbol: string; name: string; price: number; timestamp: string; source: string; fetchedAt: string },
): string {
  const positionLines = snapshot.positions.map((position) =>
    `${position.name} (${position.symbol}): ${position.quantity} shares, sellable ${position.availableQuantity}, cost ${formatYuan(position.costBasisYuan, zh)}, marked value ${formatYuan(position.marketValueYuan, zh)}, unrealized P&L ${formatYuan(position.unrealizedPnlYuan, zh)}; ${position.source} quote time ${position.quoteTimestamp || "missing"}, fetched ${position.quoteFetchedAt || "missing"}, status ${position.valuationStatus}`,
  );
  const orderLines = snapshot.orders.slice(0, 20).map((order) => formatOrderForPrompt(order));
  const dayLines = days.map((day) => `${day.date}: ${day.tradeCount} trades, buys ${formatYuan(day.buyAmountYuan, zh)}, sells ${formatYuan(day.sellAmountYuan, zh)}, fees ${formatYuan(day.feesYuan, zh)}, realized P&L ${formatYuan(day.realizedPnlYuan, zh)}`);
  const activeQuoteLine = activeQuote
    ? zh
      ? `当前查看 ${activeQuote.name}（${activeQuote.symbol}）：腾讯报价 ${formatYuan(String(activeQuote.price), true)}，报价时间 ${activeQuote.timestamp}，获取时间 ${activeQuote.fetchedAt}。`
      : `Selected ${activeQuote.name} (${activeQuote.symbol}): ${activeQuote.source} quote ${formatYuan(String(activeQuote.price), false)}, quote time ${activeQuote.timestamp}, fetched ${activeQuote.fetchedAt}.`
    : "";
  if (!zh) {
    return [
      `Review this Vibelution paper ledger${month ? ` for ${month}` : ""}. Use only the recorded ledger and timestamped public quotes; do not present virtual returns as real investment results.`,
      `Account ${snapshot.accountId}; opened ${snapshot.openedAt}; initial virtual cash ${formatYuan(snapshot.initialCashYuan, false)}.`,
      `${snapshot.ordersTotal} ledger trades; cash ${formatYuan(snapshot.cashYuan, false)}; marked holdings ${formatYuan(snapshot.marketValueYuan, false)}; equity ${formatYuan(snapshot.equityYuan, false)}; realized P&L ${formatYuan(snapshot.realizedPnlYuan, false)}; unrealized P&L ${formatYuan(snapshot.unrealizedPnlYuan, false)}; total fees ${formatYuan(snapshot.totalFeesYuan, false)}.`,
      `Valuation ${snapshot.valuationStatus}: ${snapshot.valuationNotice}`,
      `Fee policy: ${snapshot.feePolicy.description}`,
      `Sell rule: ${snapshot.tPlusOneRule}`,
      activeQuoteLine,
      positionLines.length ? `Current positions:\n${positionLines.join("\n")}` : "There are no open positions.",
      orderLines.length ? `Latest returned orders (up to ${orderLines.length}; full count above):\n${orderLines.join("\n")}` : "No order rows are in this response window.",
      month ? `Actual trade-day summary for ${month}:\n${dayLines.length ? dayLines.join("\n") : "No ledger trades this month."}` : "",
      "Separate realized P&L, unrealized P&L, fee impact, and quote times. State evidence gaps; do not infer missing prices or issue real trade instructions.",
    ].filter(Boolean).join("\n\n");
  }
  return [
    `请基于以下 Vibelution 模拟账本${month ? `复盘 ${month}` : "做交易复盘"}。只分析账本和标明时点的公开行情，不把虚拟收益描述为真实投资结果。`,
    `账户 ${snapshot.accountId}；开设时间 ${snapshot.openedAt}；虚拟初始资金 ${formatYuan(snapshot.initialCashYuan, true)}。`,
    `全量 ${snapshot.ordersTotal} 笔；现金 ${formatYuan(snapshot.cashYuan, true)}；持仓估值 ${formatYuan(snapshot.marketValueYuan, true)}；净资产 ${formatYuan(snapshot.equityYuan, true)}；已实现盈亏 ${formatYuan(snapshot.realizedPnlYuan, true)}；未实现盈亏 ${formatYuan(snapshot.unrealizedPnlYuan, true)}；累计费用 ${formatYuan(snapshot.totalFeesYuan, true)}。`,
    `估值状态 ${snapshot.valuationStatus}：${snapshot.valuationNotice}`,
    `费用口径：${snapshot.feePolicy.description}`,
    `卖出规则：${snapshot.tPlusOneRule}`,
    activeQuoteLine,
    positionLines.length ? `当前持仓：\n${positionLines.join("\n")}` : "当前没有持仓。",
    orderLines.length ? `最近返回记录（最多 ${orderLines.length} 笔；上方为账本总笔数）：\n${orderLines.join("\n")}` : "当前返回窗口没有交易记录。",
    month ? `${month} 实际交易日：\n${dayLines.length ? dayLines.join("\n") : "本月没有账本交易。"}` : "",
    "请区分已实现盈亏、未实现盈亏、费用影响和报价时点；说明证据不足处，不推测缺失价格，不发出真实交易指令。",
  ].filter(Boolean).join("\n\n");
}

function formatOrderForPrompt(order: PaperOrder): string {
  return `${order.beijingDate} ${order.side === "buy" ? "买入" : "卖出"} ${order.name}（${order.symbol}）${order.quantity} 股，报价 ${order.priceYuan} 元，费用 ${order.totalFeeYuan} 元，已实现盈亏 ${order.side === "sell" ? order.realizedPnlYuan : "未实现"}；${order.reason}；行情时间 ${order.quoteTimestamp}，获取时间 ${order.quoteFetchedAt}`;
}

function makeOrderColumns(zh: boolean) {
  return [
    { id: "time", header: zh ? "时间 / 股票" : "Date / stock", width: 148, minWidth: 118, render: (row: PaperOrder) => <span title={`${row.createdAt} · ${row.name}`}>{row.beijingDate} · {row.name}</span> },
    { id: "side", header: zh ? "方向 / 数量" : "Side / shares", width: 112, minWidth: 92, render: (row: PaperOrder) => <span className={row.side === "buy" ? styles.positive : styles.negative}>{row.side === "buy" ? (zh ? "买入" : "Buy") : (zh ? "卖出" : "Sell")} {row.quantity}</span> },
    { id: "price", header: zh ? "报价" : "Quote", width: 96, minWidth: 80, align: "right" as const, render: (row: PaperOrder) => formatYuan(row.priceYuan, zh) },
    { id: "fees", header: zh ? "费用" : "Fees", width: 88, minWidth: 74, align: "right" as const, render: (row: PaperOrder) => formatYuan(row.totalFeeYuan, zh) },
    { id: "realized", header: zh ? "已实现 / 理由" : "Realized / reason", fill: true, minWidth: 160, truncate: false, render: (row: PaperOrder) => <span title={row.reason}><strong className={row.side === "sell" ? signedTone(row.realizedPnlYuan) : styles.neutral}>{row.side === "sell" ? formatYuan(row.realizedPnlYuan, zh) : "—"}</strong><small className={styles.orderReason}>{row.reason}</small></span> },
  ];
}

export function FinancePaperTrading({ assistant, stock, zh, mode, onResearchPrompt }: FinancePaperTradingProps) {
  const queryClient = useQueryClient();
  const [month, setMonth] = useState(beijingMonthNow);
  const [side, setSide] = useState<PaperSide>("buy");
  const [quantity, setQuantity] = useState("100");
  const [reason, setReason] = useState("");
  const [orderError, setOrderError] = useState("");
  const openGate = useRef(false);
  const submitGate = useRef(false);
  const pendingOrder = useRef<{ fingerprint: string; clientOrderId: string } | null>(null);

  const accountQuery = useQuery({
    queryKey: financialPaperKeys.account(assistant.agentId),
    queryFn: ({ signal }) => fetchFinancialPaperAccount(assistant.agentId, { signal, orderLimit: RECENT_ORDER_LIMIT }),
    enabled: mode === "account",
    staleTime: 20_000,
    retry: false,
  });
  const reviewQuery = useQuery({
    queryKey: financialPaperKeys.review(assistant.agentId, month),
    queryFn: ({ signal }) => fetchFinancialPaperReview(assistant.agentId, month, { signal }),
    enabled: mode === "review",
    staleTime: 20_000,
    retry: false,
  });
  const quoteQuery = useQuery({
    queryKey: financialMarketKeys.stock(stock.symbol, "day"),
    queryFn: ({ signal }) => fetchFinancialStock(stock.symbol, "day", { signal }),
    enabled: mode === "account" && Boolean(stock.symbol),
    staleTime: 30_000,
    retry: false,
  });
  const openMutation = useMutation({
    mutationFn: () => openFinancialPaperAccount(assistant.agentId),
    onSuccess: (value) => {
      queryClient.setQueryData(financialPaperKeys.account(assistant.agentId), value);
      void queryClient.invalidateQueries({ queryKey: ["financial-paper", assistant.agentId, "review"] });
    },
  });
  const orderMutation = useMutation({
    mutationFn: (payload: Parameters<typeof submitFinancialPaperOrder>[1]) => submitFinancialPaperOrder(assistant.agentId, payload),
    onSuccess: (value) => {
      queryClient.setQueryData(financialPaperKeys.account(assistant.agentId), value);
      void queryClient.invalidateQueries({ queryKey: ["financial-paper", assistant.agentId, "review"] });
      setOrderError("");
      pendingOrder.current = null;
    },
  });

  const account = mode === "account" ? accountQuery.data : reviewQuery.data?.account;
  const query = mode === "account" ? accountQuery : reviewQuery;
  const review = mode === "review" ? reviewQuery.data : undefined;
  const currentQuote = quoteQuery.data?.stock;
  const orderShares = Number(quantity);
  const tradeEstimate = currentQuote ? estimatePaperTrade(currentQuote.price, orderShares, side) : null;
  const orderDisabled = !account || !stock.symbol || !reason.trim() || !Number.isSafeInteger(orderShares) || orderShares < 100 || orderShares > 1_000_000 || orderShares % 100 !== 0 || orderMutation.isPending;

  async function openAccount() {
    if (openGate.current || openMutation.isPending) return;
    openGate.current = true;
    try {
      await openMutation.mutateAsync();
    } catch {
      // The mutation error remains visible in the operation panel below.
    } finally {
      openGate.current = false;
    }
  }

  async function submitOrder(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    if (submitGate.current || orderDisabled) return;
    const numericQuantity = Number(quantity);
    if (!Number.isSafeInteger(numericQuantity) || numericQuantity > 1_000_000) {
      setOrderError(zh ? "股数须为 100 的整数倍，且不超过 1,000,000 股" : "Shares must be a 100-share lot up to 1,000,000.");
      return;
    }
    const intent = { symbol: stock.symbol, side, quantity: numericQuantity, reason: reason.trim() };
    const fingerprint = JSON.stringify(intent);
    if (pendingOrder.current?.fingerprint !== fingerprint) {
      pendingOrder.current = { fingerprint, clientOrderId: newClientOrderId() };
    }
    submitGate.current = true;
    setOrderError("");
    try {
      await orderMutation.mutateAsync({ ...intent, clientOrderId: pendingOrder.current.clientOrderId });
      setReason("");
    } catch (error) {
      setOrderError(errorText(error, zh));
      // The response may have been lost after the server committed. Re-read the
      // account while retaining the same idempotency key for a safe retry.
      void queryClient.invalidateQueries({ queryKey: financialPaperKeys.account(assistant.agentId) });
    } finally {
      submitGate.current = false;
    }
  }

  function requestReview() {
    if (!account) return;
    onResearchPrompt(buildReviewPrompt(
      account,
      zh,
      review?.month,
      review?.days ?? [],
      currentQuote && quoteQuery.data ? {
        symbol: currentQuote.symbol,
        name: currentQuote.name,
        price: currentQuote.price,
        timestamp: currentQuote.timestamp,
        source: quoteQuery.data.source,
        fetchedAt: quoteQuery.data.fetchedAt,
      } : undefined,
    ));
  }

  if (query.isPending && !account) {
    return <div className={styles.loading}><VStateSurface tone="loading" busy title={zh ? "正在读取模拟账本" : "Loading paper ledger"} /><VSurface tone="panel" className={styles.loadingSurface}><VSkeleton className={styles.loadingSkeleton} /></VSurface></div>;
  }
  if (isFinancialPaperAccountNotOpened(query.error)) {
    return <div className={styles.root}>
      <div className={styles.heading}><div className={styles.titleGroup}><Wallet size={15} /><h2 className={styles.title}>{zh ? "模拟账户" : "Paper account"}</h2></div><VChip tone="warning">{zh ? "仅虚拟资金" : "Virtual funds only"}</VChip></div>
      <VStateSurface tone="empty" title={zh ? "尚未开设模拟账户" : "No paper account yet"}>
        {zh ? "开设后写入 100 万元虚拟初始资金；不会连接券商或真实账户。" : "Opening creates ¥1,000,000 in virtual cash. No broker or real account is connected."}
        <div className={styles.openAction}><VButton variant="primary" isPending={openMutation.isPending} isDisabled={openMutation.isPending} onPress={() => void openAccount()}>{zh ? "开设模拟账户" : "Open paper account"}</VButton></div>
      </VStateSurface>
      {openMutation.error ? <VStateSurface tone="error" density="compact" title={errorText(openMutation.error, zh)} actions={<VButton onPress={() => void openAccount()}>{zh ? "重试" : "Retry"}</VButton>} /> : null}
    </div>;
  }
  if (query.error && !account) {
    return <VStateSurface tone="error" title={zh ? "模拟账本读取失败" : "Could not read paper ledger"} actions={<VButton onPress={() => void query.refetch()}>{zh ? "重试" : "Retry"}</VButton>}>{errorText(query.error, zh)}</VStateSurface>;
  }
  if (!account) return null;

  const metricValues = [
    { id: "equity", label: zh ? "净资产" : "Equity", value: formatYuan(account.equityYuan, zh), detail: account.valuationNotice },
    { id: "cash", label: zh ? "可用现金" : "Cash", value: formatYuan(account.cashYuan, zh) },
    { id: "market", label: zh ? "持仓估值" : "Market value", value: formatYuan(account.marketValueYuan, zh) },
    { id: "pnl", label: zh ? "总盈亏" : "Total P&L", value: formatYuan(account.totalPnlYuan, zh), tone: Number(account.totalPnlYuan) >= 0 ? "success" as const : "danger" as const },
  ];

  return <div className={styles.root} data-paper-mode={mode}>
    <div className={styles.heading}>
      <div className={styles.titleGroup}>
        {mode === "account" ? <Wallet size={15} /> : <CalendarDays size={15} />}
        <h2 className={styles.title}>{mode === "account" ? (zh ? "模拟账户" : "Paper account") : (zh ? "模拟复盘" : "Paper review")}</h2>
        <VChip tone="warning">{zh ? "仅模拟" : "Simulation only"}</VChip>
      </div>
      <div className={styles.headerActions}>
        <VButton variant="ghost" density="compact" isDisabled={query.isFetching} onPress={() => void query.refetch()} icon={<RefreshCw size={13} />}>{zh ? "刷新" : "Refresh"}</VButton>
        <VButton variant="secondary" density="compact" onPress={requestReview} icon={<Sparkles size={13} />}>{zh ? "AI 复盘" : "AI review"}</VButton>
      </div>
    </div>

    <VMetricStrip ariaLabel={zh ? "模拟账户净值" : "Paper account value"} metrics={metricValues} status={{ label: account.valuationStatus === "fresh" ? (zh ? "报价已更新" : "Quotes current") : (zh ? "含过期报价" : "Stale quote used"), tone: account.valuationStatus === "fresh" ? "success" : "warning", title: account.valuationNotice }} />

    {query.error ? <VStateSurface tone="error" density="compact" title={zh ? "账本刷新失败，当前显示上次成功读取的数据" : "Refresh failed; showing the last successfully loaded ledger"} actions={<VButton onPress={() => void query.refetch()}>{zh ? "重试" : "Retry"}</VButton>}>{errorText(query.error, zh)}</VStateSurface> : null}

    {account.valuationStatus !== "fresh" ? <p className={styles.warning}><CircleAlert size={13} className={styles.warningIcon} />{account.valuationNotice}</p> : null}

    {mode === "account" ? <>
      <section className={styles.section} aria-label={zh ? "模拟下单" : "Paper order"}>
        <h3 className={styles.sectionHeading}><span>{zh ? `模拟交易 · ${stock.name}（${stock.ticker}）` : `Paper order · ${stock.name} (${stock.ticker})`}</span><span>{currentQuote ? <span className={styles.quotePrice}>{formatYuan(String(currentQuote.price), zh)}</span> : (zh ? "报价不可用" : "Quote unavailable")}</span></h3>
        <form className={styles.controls} onSubmit={(event) => void submitOrder(event)}>
          <label className={styles.field}>{zh ? "交易方向" : "Side"}
            <VSelect selectedKey={side} onSelectionChange={(key) => setSide(String(key) as PaperSide)} aria-label={zh ? "交易方向" : "Side"} options={[{ id: "buy", label: zh ? "买入" : "Buy" }, { id: "sell", label: zh ? "卖出" : "Sell" }]} />
          </label>
          <label className={styles.field}>{zh ? "股数" : "Shares"}
            <VInput type="number" inputMode="numeric" min={100} max={1_000_000} step={100} value={quantity} className={styles.input} aria-label={zh ? "模拟交易股数" : "Paper order shares"} onChange={(event) => setQuantity(event.target.value)} />
          </label>
          <label className={styles.field}>{zh ? "理由" : "Reason"}
            <VInput value={reason} maxLength={500} className={styles.input} aria-label={zh ? "模拟交易理由" : "Paper order reason"} placeholder={zh ? "记录本次模拟决策" : "Record the simulated decision"} onChange={(event) => setReason(event.target.value)} />
          </label>
          <span className={styles.field} aria-label={zh ? "服务端报价" : "Server quote"}>
            <span>{zh ? "腾讯报价" : "Tencent quote"}</span>
            <span className={styles.quotePrice}>{currentQuote ? `${formatYuan(String(currentQuote.price), zh)} · ${currentQuote.timestamp}` : (zh ? "等待报价" : "Waiting for quote")}</span>
          </span>
          <VButton type="submit" variant={side === "buy" ? "primary" : "danger"} isPending={orderMutation.isPending} isDisabled={orderDisabled || !currentQuote} icon={side === "buy" ? <ArrowDownToLine size={14} /> : <ArrowUpFromLine size={14} />}>
            {orderMutation.isPending ? (zh ? "正在记账" : "Recording") : side === "buy" ? (zh ? "模拟买入" : "Paper buy") : (zh ? "模拟卖出" : "Paper sell")}
          </VButton>
        </form>
        <div className={styles.orderMeta}>
          {tradeEstimate ? <span>{zh ? "预估成交额" : "Est. amount"} {formatYuan(tradeEstimate.gross, zh)} · {zh ? "预估费用" : "Est. fees"} {formatYuan(tradeEstimate.fees, zh)} · {zh ? "现金变化" : "Cash change"} {formatYuan(tradeEstimate.cashImpact, zh)} · {zh ? "成交采用服务端最新报价" : "Execution uses the server quote"}</span> : null}
          <span>{account.feePolicy.description}</span>
          <span>{account.tPlusOneRule}</span>
          {currentQuote ? <span>{quoteQuery.data?.source} · {zh ? "报价日" : "Quote date"} {currentQuote.timestamp.slice(0, 10)} · {zh ? "获取" : "Fetched"} {quoteQuery.data?.fetchedAt}</span> : null}
        </div>
        {quoteQuery.error ? <p className={styles.warning}>{errorText(quoteQuery.error, zh)}</p> : null}
        {orderError ? <p className={styles.orderError} role="alert">{orderError}</p> : null}
      </section>

      <section className={styles.section}>
        <h3 className={styles.sectionHeading}>{zh ? `持仓 · ${account.positions.length} 只` : `Positions · ${account.positions.length}`}</h3>
        <VDenseTable<PaperPosition>
          ariaLabel={zh ? "模拟账户持仓" : "Paper account positions"}
          columns={[
            { id: "stock", header: zh ? "股票" : "Stock", fill: true, minWidth: 140, render: (row) => `${row.name} ${row.symbol}` },
            { id: "quantity", header: zh ? "持有 / 可卖" : "Held / sellable", width: 118, minWidth: 104, align: "right", render: (row) => `${row.quantity} / ${row.availableQuantity}` },
            { id: "cost", header: zh ? "持仓成本" : "Cost", width: 112, minWidth: 98, align: "right", render: (row) => formatYuan(row.costBasisYuan, zh) },
            { id: "mark", header: zh ? "报价 / 市值" : "Quote / value", width: 156, minWidth: 140, align: "right", render: (row) => <span title={`${row.source} ${row.quoteTimestamp} · ${row.quoteFetchedAt}`}>{formatYuan(row.markPriceYuan, zh)} / {formatYuan(row.marketValueYuan, zh)}{row.valuationStatus !== "fresh" ? " *" : ""}</span> },
            { id: "pnl", header: zh ? "未实现盈亏" : "Unrealized", width: 116, minWidth: 100, align: "right", render: (row) => <span className={signedTone(row.unrealizedPnlYuan)}>{formatYuan(row.unrealizedPnlYuan, zh)}</span> },
          ]}
          rows={account.positions}
          getRowKey={(row) => row.symbol}
          emptyText={zh ? "暂无持仓" : "No positions"}
        />
        {account.positions.some((position) => position.frozenQuantity > 0) ? <p className={styles.helper}>{zh ? "可卖数量按北京时间自然日计算；买入当日持仓被冻结。" : "Sellable shares follow Beijing calendar days; shares bought today remain frozen."}</p> : null}
      </section>

      <section className={styles.section}>
        <h3 className={styles.sectionHeading}>
          <span>{zh ? `最近交易（${Math.min(RECENT_ORDER_LIMIT, account.ordersTotal)} / ${account.ordersTotal} 笔）` : `Recent trades (${Math.min(RECENT_ORDER_LIMIT, account.ordersTotal)} / ${account.ordersTotal})`}</span>
          <span className={styles.subtitle}>{zh ? `累计费用 ${formatYuan(account.totalFeesYuan, zh)}` : `Total fees ${formatYuan(account.totalFeesYuan, zh)}`}</span>
        </h3>
        <VDenseTable<PaperOrder> ariaLabel={zh ? "模拟交易记录" : "Paper trade log"} columns={makeOrderColumns(zh)} rows={account.orders} getRowKey={(row) => row.orderId} emptyText={zh ? "暂无模拟交易记录" : "No paper trades"} />
        {account.ordersTruncated ? <p className={styles.helper}>{zh ? "列表显示最近 50 笔；复盘汇总仍按完整账本计算。" : "This list shows the latest 50; review totals use the full ledger."}</p> : null}
      </section>
    </> : <>
      <div className={styles.calendarToolbar}>
        <h3 className={styles.sectionHeading}><span>{zh ? "交易日历" : "Trading calendar"}</span></h3>
        <label className={styles.field}>{zh ? "月份" : "Month"}<VInput type="month" value={month} className={styles.input} aria-label={zh ? "复盘月份" : "Review month"} onChange={(event) => setMonth(event.target.value || beijingMonthNow())} /></label>
      </div>
      {review ? <>
        <VMetricStrip ariaLabel={zh ? "账本复盘统计" : "Ledger review statistics"} metrics={[
          { id: "month-trades", label: zh ? "本月交易" : "Month trades", value: String(review.summary.monthTradeCount) },
          { id: "month-pnl", label: zh ? "本月已实现" : "Month realized", value: formatYuan(review.summary.monthRealizedPnlYuan, zh), tone: Number(review.summary.monthRealizedPnlYuan) >= 0 ? "success" : "danger" },
          { id: "all-realized", label: zh ? "全量已实现" : "All-time realized", value: formatYuan(review.summary.allTimeRealizedPnlYuan, zh), tone: Number(review.summary.allTimeRealizedPnlYuan) >= 0 ? "success" : "danger" },
          { id: "fees", label: zh ? "全量费用" : "All-time fees", value: formatYuan(review.summary.allTimeFeesYuan, zh) },
        ]} />
        <div className={styles.calendar} role="grid" aria-label={`${month}${zh ? "交易日历" : " trading calendar"}`}>
          {weekdayLabels.map((label) => <span key={`weekday-${label}`} role="columnheader" className={styles.weekday}>{zh ? label : ["M", "T", "W", "T", "F", "S", "S"][weekdayLabels.indexOf(label)]}</span>)}
          {Array.from({ length: monthOffsetMonday(month) }, (_, index) => <span key={`blank-${index}`} aria-hidden="true" className={styles.blankDay} />)}
          {Array.from({ length: monthDayCount(month) }, (_, index) => {
            const dayNumber = index + 1;
            const day = dailyMap(review.days).get(dayNumber);
            const pnl = day?.realizedPnlYuan;
            return <span key={dayNumber} role="gridcell" aria-label={day ? `${day.date} ${day.tradeCount} ${zh ? "笔交易" : "trades"} ${formatYuan(pnl, zh)}` : `${month}-${String(dayNumber).padStart(2, "0")}`} className={styles.calendarDay}>
              <strong className={styles.calendarDate}>{dayNumber}</strong>
              {day ? <><small className={styles.calendarTrades}>{day.tradeCount}{zh ? " 笔" : " trades"} · {zh ? "费" : "fee"} {formatYuan(day.feesYuan, zh)}</small><small className={`${styles.calendarResult} ${signedTone(pnl)}`}>{zh ? "已实现" : "Realized"} {formatYuan(pnl, zh)}</small></> : null}
            </span>;
          })}
        </div>
        <VDenseTable<PaperReviewDay>
          ariaLabel={zh ? "本月实际交易日复盘" : "Actual trade day review"}
          columns={[
            { id: "date", header: zh ? "交易日" : "Trade day", width: 116, minWidth: 100, render: (row) => row.date },
            { id: "count", header: zh ? "笔数" : "Trades", width: 76, minWidth: 64, align: "right", render: (row) => row.tradeCount },
            { id: "buy", header: zh ? "买入" : "Buys", width: 116, minWidth: 100, align: "right", render: (row) => formatYuan(row.buyAmountYuan, zh) },
            { id: "sell", header: zh ? "卖出" : "Sells", width: 116, minWidth: 100, align: "right", render: (row) => formatYuan(row.sellAmountYuan, zh) },
            { id: "fees", header: zh ? "费用" : "Fees", width: 96, minWidth: 82, align: "right", render: (row) => formatYuan(row.feesYuan, zh) },
            { id: "realized", header: zh ? "已实现盈亏" : "Realized P&L", width: 132, minWidth: 116, align: "right", render: (row) => <span className={signedTone(row.realizedPnlYuan)}>{formatYuan(row.realizedPnlYuan, zh)}</span> },
          ]}
          rows={review.days}
          getRowKey={(row) => row.date}
          emptyText={zh ? "本月没有真实账本交易日" : "No trade days in this ledger month"}
        />
        <p className={styles.helper}>{zh ? "本页按账本实际订单汇总交易日；未生成没有历史行情依据的净值曲线。" : "Days are grouped from actual ledger orders. No equity curve is generated without historical quote evidence."}</p>
      </> : null}
    </>}
  </div>;
}
