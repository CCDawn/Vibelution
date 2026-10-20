import type { ConversationMessage } from "../../api/types";
import type { FinancialInvestmentProfile } from "../../api/types/financialPreferences";

/** Only a discovery hint; the server reads and validates the canonical native Turn. */
export function latestAdvisorProposalTurn(messages: readonly ConversationMessage[]) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.role !== "assistant" || message.status !== "completed" || !message.turnId) continue;
    if (message.turnItems?.some(item => item.type === "agent_message" && item.phase === "final_answer" && item.status === "completed" && /```investment-proposal\s/.test(item.text))) return message.turnId;
  }
  return null;
}

export function investmentConditionRows(profile: FinancialInvestmentProfile | null | undefined, zh: boolean) {
  const unknown = zh ? "未确认" : "Unknown";
  const number = (value: number | null | undefined, suffix = "") => value == null ? unknown : `${value.toLocaleString(zh ? "zh-CN" : "en-US")}${suffix}`;
  return [
    [zh ? "投资预算" : "Budget", number(profile?.budgetCny, " CNY")],
    [zh ? "可用现金" : "Available cash", number(profile?.availableCashCny, " CNY")],
    [zh ? "预计持有" : "Horizon", number(profile?.horizonMonths, zh ? " 个月" : " months")],
    [zh ? "可以继续持有" : "Flexible horizon", profile?.flexibleHorizon == null ? unknown : profile.flexibleHorizon ? (zh ? "是" : "Yes") : (zh ? "否" : "No")],
    [zh ? "最大可接受亏损" : "Loss tolerance", number(profile?.maxLossCny, " CNY")],
    [zh ? "保留现金" : "Cash reserve", number(profile?.cashReserveCny, " CNY")],
    [zh ? "单股仓位上限" : "Single-stock cap", number(profile?.maxPositionPct, "%")],
    [zh ? "持仓状态" : "Holdings", profile?.holdingsStatus === "none" ? (zh ? "已确认空仓" : "Confirmed empty") : profile?.holdingsStatus === "recorded" ? (zh ? "使用手动持仓" : "Manual holdings") : unknown],
  ];
}

export const ADVISOR_PLAN_PROMPT = "请根据本轮最新投资条件、可用现金和已确认持仓，复核当前投资方案。先说明缺少的条件；条件充分时给出适合预算的待确认方案、依据和下次复核时间。不要假定我已经买入或卖出。";

export function advisorCheckText(text: string) {
  const labels: Record<string, string> = { budgetCny: "投资预算", availableCashCny: "可用现金", cashReserveCny: "保留现金", maxPositionPct: "单股仓位上限", maxLossCny: "最大可接受亏损" };
  return text.replace(/budgetCny|availableCashCny|cashReserveCny|maxPositionPct|maxLossCny/g, key => labels[key]);
}
