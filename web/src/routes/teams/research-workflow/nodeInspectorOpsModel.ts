import type { EffectiveAgentBinding, ResearchBudgetLedgerSnapshot } from "../../../api/types/researchWorkflow";
import type { CommandOffer } from "../../../api/types/research-workflow/commands";
import type { VStatusTone } from "../../../components/vui";

export const NODE_INSPECTOR_BUDGET_WARN_PERCENT = 80;

export type NodeInspectorBudgetMeterKey = "tokens" | "toolCalls" | "wallClockSeconds";

export type NodeInspectorBudgetMeter = {
  key: NodeInspectorBudgetMeterKey;
  label: string;
  percent: number;
  detail: string;
  warn: boolean;
};

export type NodeInspectorStatusView = {
  tone: VStatusTone;
  label: string;
};

export type NodeInspectorProviderVisual = "qwen" | "deepseek" | "anthropic" | "other";

const METER_COPY: Array<{ key: NodeInspectorBudgetMeterKey; label: string; emptyDetail: string }> = [
  { key: "tokens", label: "Tokens", emptyDetail: "本阶段 token 已用 / 上限" },
  { key: "toolCalls", label: "工具", emptyDetail: "工具调用已用 / 上限" },
  { key: "wallClockSeconds", label: "时间", emptyDetail: "墙钟时间已用 / 上限" },
];

export function agentDisplayInitial(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "?";
  return Array.from(trimmed)[0] ?? "?";
}

export function providerVisualId(providerId: string): NodeInspectorProviderVisual {
  const value = providerId.trim().toLowerCase();
  if (!value) return "other";
  if (value.includes("deepseek")) return "deepseek";
  if (value.includes("anthropic") || value.includes("claude")) return "anthropic";
  if (value.includes("qwen") || value.includes("dashscope") || value.includes("tongyi") || value.includes("alibaba")) {
    return "qwen";
  }
  return "other";
}

export function ledgerForStage(
  ledgers: ResearchBudgetLedgerSnapshot[] | null | undefined,
  stageId: string,
): ResearchBudgetLedgerSnapshot | null {
  const needle = stageId.trim();
  if (!needle) return null;
  return (ledgers ?? []).find((item) => item.stageId === needle) ?? null;
}

function asCount(value: unknown): number {
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric) || numeric < 0) return 0;
  return numeric;
}

export function budgetMeterPercent(consumed: number, limit: number): number {
  if (limit <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((consumed / limit) * 100)));
}

export function nodeInspectorBudgetMeters(
  ledger: ResearchBudgetLedgerSnapshot | null | undefined,
): NodeInspectorBudgetMeter[] {
  return METER_COPY.map((item) => {
    if (!ledger) {
      return {
        key: item.key,
        label: item.label,
        percent: 0,
        detail: "运行后显示用量",
        warn: false,
      };
    }
    const consumed = asCount(ledger.consumed?.[item.key]);
    const limit = asCount(ledger.limits?.[item.key]);
    const percent = budgetMeterPercent(consumed, limit);
    const detail = limit <= 0
      ? "未设置上限"
      : `${consumed} / ${limit}`;
    return {
      key: item.key,
      label: item.label,
      percent,
      detail: `${item.emptyDetail}：${detail}`,
      warn: percent >= NODE_INSPECTOR_BUDGET_WARN_PERCENT,
    };
  });
}

export function nodeInspectorStatus(input: {
  unbound: boolean;
  runtimeCurrent: boolean;
  status: string | null | undefined;
  budgetWarn: boolean;
}): NodeInspectorStatusView {
  if (input.unbound) {
    return { tone: "neutral", label: "待指定" };
  }
  const status = String(input.status || "").trim().toLowerCase();
  if (input.runtimeCurrent || status === "running" || status === "in_flight") {
    return { tone: "accent", label: "运行中" };
  }
  if (status === "failed") {
    return { tone: "danger", label: "失败" };
  }
  if (status === "succeeded") {
    return { tone: "success", label: "完成" };
  }
  if (status === "blocked") {
    return { tone: "warning", label: "阻塞" };
  }
  if (input.budgetWarn) {
    return { tone: "warning", label: "将尽" };
  }
  return { tone: "success", label: "待运行" };
}

export function mergeNodeOverrideLayer(
  bindings: EffectiveAgentBinding[] | null | undefined,
  nodeId: string,
  agentId: string,
): Record<string, string> {
  const next: Record<string, string> = {};
  for (const binding of bindings ?? []) {
    if (binding.nodeId === nodeId) continue;
    if (binding.resolvedFrom === "node_override" && binding.agentId) {
      next[binding.nodeId] = binding.agentId;
    }
  }
  const trimmed = agentId.trim();
  if (trimmed) next[nodeId] = trimmed;
  return next;
}

export function pickPrimaryCommandOffer(offers: CommandOffer[] | null | undefined): CommandOffer | null {
  const list = offers ?? [];
  const startOffers = list.filter((offer) => offer.command === "start_node");
  const availableStart = startOffers.find((offer) => offer.available);
  if (availableStart) return availableStart;
  if (startOffers[0]) return startOffers[0];
  const retry = list.find((offer) => offer.command === "retry_node" && offer.available)
    ?? list.find((offer) => offer.command === "retry_node");
  return retry ?? null;
}

export function remainingCommandOffers(
  offers: CommandOffer[] | null | undefined,
  primary: CommandOffer | null,
): CommandOffer[] {
  const list = offers ?? [];
  if (!primary) return list;
  return list.filter((offer) => offer.idempotencyKey !== primary.idempotencyKey);
}

export function researchAgentConfigRoute(agentId: string): string | null {
  const trimmed = agentId.trim();
  if (!trimmed) return null;
  return `/agents?pane=config&agent=${encodeURIComponent(trimmed)}`;
}
