import { ACTIVITY_CONTRACT } from "../api/generated/activityContract";
import { activityPhase, normalizeActivityValue } from "./sessionActivityState";

const contract = ACTIVITY_CONTRACT.workRun;
function lookup(table: Readonly<Record<string, string>>, key: string) {
  return Object.prototype.hasOwnProperty.call(table, key) ? table[key] : "";
}

export type WorkRunActivitySource = {
  status?: string;
  currentPhase?: string;
  phase?: string;
  runtimeStatus?: string;
  terminalReason?: string;
  finishedAt?: string;
  endedAt?: string;
};

/** Heterogeneous WorkRuns retain a stricter safety policy than live ownership. */
export function resolveWorkRunActivity(source: WorkRunActivitySource) {
  const rawStatus = contract.statusFields.map((field) => normalizeActivityValue(source[field])).find(Boolean) || "";
  const outcome = lookup(contract.outcomes, rawStatus);
  let execution = lookup(contract.executions, rawStatus)
    || (activityPhase(rawStatus) ? "running" : outcome ? "settled" : (contract.resting as readonly string[]).includes(rawStatus) ? "idle" : "unknown");
  const ended = Boolean(source.finishedAt?.trim() || source.endedAt?.trim());
  if (ended) execution = "settled";
  const blocksLifecycle = !(ended || outcome || (contract.resting as readonly string[]).includes(rawStatus));
  const phase = blocksLifecycle && execution !== "unknown"
    ? [source.currentPhase, source.phase, rawStatus].map(activityPhase).find(Boolean) || ""
    : "";
  const reason = outcome
    ? [source.terminalReason, source.runtimeStatus].map(normalizeActivityValue)
      .find((value) => lookup(contract.outcomes, value) === outcome) || rawStatus
    : "";
  return { execution, phase, outcome, reason, rawStatus, blocksLifecycle };
}

export function workRunHasExecution(source: WorkRunActivitySource) {
  return (contract.policy.ownedExecutions as readonly string[]).includes(resolveWorkRunActivity(source).execution);
}

export function workRunStatusLabel(source: WorkRunActivitySource, lang: "zh" | "en") {
  const state = resolveWorkRunActivity(source);
  const value = state.outcome || state.execution;
  return lang === "zh" ? lookup(contract.labels, value) || contract.labels.unknown : lookup(contract.labelsEn, value) || contract.labelsEn.unknown;
}
