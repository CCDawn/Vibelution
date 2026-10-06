import type { StockQuote } from "../../api/financialMarket";
import type { FinancialManualPosition } from "../../api/financialPreferences";
import { stockCurrency } from "./financeMarketDisplay";
import { localResearchDate } from "./stockResearchModel";

export type ManualPositionConflictReason = "changed" | "deleted" | "id_collision";

export class ManualPositionConflictError extends Error {
  constructor(readonly reason: ManualPositionConflictReason) {
    super("manual-position-conflict");
    this.name = "ManualPositionConflictError";
  }
}

const stockIdentityFields = ["symbol", "ticker", "name", "market", "marketCode", "currency", "marketTimeZone"] as const;

function sameManualPosition(left: FinancialManualPosition, right: FinancialManualPosition): boolean {
  return left.id === right.id
    && left.quantity === right.quantity
    && left.costPrice === right.costPrice
    && left.currency === right.currency
    && left.note === right.note
    && stockIdentityFields.every((field) => left.stock[field] === right.stock[field]);
}

/** Apply an edit only to the exact row snapshot the user opened. Other rows from a newer revision are retained. */
export function saveManualPositionChange(
  current: FinancialManualPosition[],
  submitted: FinancialManualPosition,
  baseline: FinancialManualPosition | null,
): FinancialManualPosition[] {
  const index = current.findIndex((row) => row.id === submitted.id);
  if (baseline) {
    if (baseline.id !== submitted.id) throw new ManualPositionConflictError("changed");
    if (index < 0) throw new ManualPositionConflictError("deleted");
    if (!sameManualPosition(current[index], baseline)) throw new ManualPositionConflictError("changed");
    return current.map((row, rowIndex) => rowIndex === index ? submitted : row);
  }
  if (index >= 0) throw new ManualPositionConflictError("id_collision");
  return [...current, submitted];
}

/** Resolve a quote using the same canonical identity and currency rules everywhere in the manual portfolio. */
export function manualPositionQuote(row: FinancialManualPosition, quotes: Map<string, StockQuote>): StockQuote | undefined {
  const quote = quotes.get(row.stock.symbol);
  if (!quote || quote.symbol !== row.stock.symbol) return undefined;
  if (stockCurrency(row.stock) !== row.currency || stockCurrency(quote) !== row.currency) return undefined;
  if (quote.currency && quote.currency !== row.currency) return undefined;
  if (!Number.isFinite(quote.price) || quote.price <= 0) return undefined;
  return quote;
}

export function manualPortfolioTotals(positions: FinancialManualPosition[], quotes: Map<string, StockQuote>) {
  const groups = new Map<string, { currency: string; count: number; marked: number; cost: number; markedCost: number; marketValue: number }>();
  for (const row of positions) {
    const group = groups.get(row.currency) ?? { currency: row.currency, count: 0, marked: 0, cost: 0, markedCost: 0, marketValue: 0 };
    group.count += 1; group.cost += row.quantity * row.costPrice;
    const quote = manualPositionQuote(row, quotes);
    if (quote) { group.marked += 1; group.markedCost += row.quantity * row.costPrice; group.marketValue += row.quantity * quote.price; }
    groups.set(row.currency, group);
  }
  return [...groups.values()];
}

export function manualPortfolioPrompt(positions: FinancialManualPosition[], quotes: Map<string, StockQuote>, fetchedAt: string) {
  const rows = positions.map((row) => {
    const quote = manualPositionQuote(row, quotes);
    return `- ${row.stock.name}（${row.stock.ticker}，${row.stock.market}，${row.stock.symbol}）：${row.quantity}股，成本${row.costPrice} ${row.currency}；报价${quote ? `${quote.price} ${quote.currency ?? row.currency}（${quote.timestamp}）` : "不可用"}。用户备注：${row.note || "无"}`;
  });
  return `请对以下主题开展投资研究：手工持仓组合。分析截至 ${localResearchDate()}。\n\n以下是用户手工记录的持仓，并非券商同步。行情抓取时间：${fetchedAt || "未获取"}。\n${rows.join("\n")}\n\n生成研究报告，分析持仓集中度、行业敞口、风险与需要核实的事实；按币种分别计算，不合并不同币种金额。缺失行情保留为空。只提出研究建议，不执行交易。`;
}
