import type { AIBacktestParameterKey, AIBacktestParams } from "../../api/types/financialBacktests";

export type AIBacktestParameterOption = {
  id: AIBacktestParameterKey;
  label: { zh: string; en: string };
  min: number;
  max: number;
  step: number;
  choices?: readonly number[];
};

export const AI_BACKTEST_PARAMETER_OPTIONS: readonly AIBacktestParameterOption[] = [
  { id: "maxPositionPct", label: { zh: "持仓上限（%）", en: "Position cap (%)" }, min: 0, max: 100, step: 1 },
  { id: "decisionInterval", label: { zh: "决策间隔（交易日）", en: "Decision interval (sessions)" }, min: 1, max: 20, step: 1, choices: [1, 5, 20] },
  { id: "commissionBps", label: { zh: "佣金（bps）", en: "Commission (bps)" }, min: 0, max: 100, step: 0.1 },
  { id: "minimumCommission", label: { zh: "最低佣金（元）", en: "Minimum commission (CNY)" }, min: 0, max: 10_000, step: 0.1 },
  { id: "slippageBps", label: { zh: "滑点（bps）", en: "Slippage (bps)" }, min: 0, max: 100, step: 0.1 },
  { id: "maxParticipationPct", label: { zh: "成交量参与率（%）", en: "Volume participation cap (%)" }, min: 0.1, max: 100, step: 0.1 },
];

export function readAIBacktestParameterValue(
  params: AIBacktestParams | null | undefined,
  key: AIBacktestParameterKey,
): number | null {
  const value = params?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function formatAIBacktestParameterValue(value: number | null | undefined, zh: boolean): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString(zh ? "zh-CN" : "en-US", { maximumFractionDigits: 3 })
    : "—";
}
