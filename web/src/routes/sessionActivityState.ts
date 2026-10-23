/** Legacy wire fields are decoded here, before any activity policy is applied. */
import { ACTIVITY_CONTRACT } from "../api/generated/activityContract";

const contract = ACTIVITY_CONTRACT.session;
function lookup(table: Readonly<Record<string, string>>, key: string): string {
  return Object.prototype.hasOwnProperty.call(table, key) ? table[key] : "";
}
export type SessionActivitySource = {
  status?: string;
  currentPhase?: string;
  childStatus?: string;
  sessionKind?: string;
  lastTurnStatus?: string;
  terminalReason?: string;
  activeTurnId?: string;
};

export type SessionActivityState = {
  execution: "unknown" | "idle" | "queued" | "running" | "stopping" | "paused" | "settled";
  phase: string;
  outcome: string;
  reason: string;
  rawStatus: string;
};

export function normalizeActivityValue(value: unknown) {
  return String(value ?? "").trim().toLowerCase();
}

export function activityPhase(value: unknown): string {
  const normalized = normalizeActivityValue(value);
  if ((contract.phases as readonly string[]).includes(normalized)) return normalized;
  return lookup(contract.phaseAliases, normalized);
}

export function activityExecution(value: unknown): string {
  return lookup(contract.executions, normalizeActivityValue(value)) || (activityPhase(value) ? "running" : "");
}

export function activityOutcome(value: unknown): string {
  return lookup(contract.outcomes, normalizeActivityValue(value));
}

export function isActivityResting(value: unknown) {
  return (contract.resting as readonly string[]).includes(normalizeActivityValue(value));
}

/** Paused execution still owns the Turn, while producing no active output. */
export function hasExecutionOwnership(value: unknown) {
  return Boolean(activityExecution(value));
}

export function resolveSessionActivity(
  session: SessionActivitySource,
  options?: { runtimeRunning?: boolean; authoritativeRuntime?: boolean },
): SessionActivityState {
  const status = normalizeActivityValue(session.status);
  const legacyPhase = normalizeActivityValue(session.currentPhase);
  const child = session.sessionKind === "child" ? normalizeActivityValue(session.childStatus) : "";
  const current = status || legacyPhase ? [status, legacyPhase].filter(Boolean) : [child].filter(Boolean);
  const phase = [legacyPhase, status, status || legacyPhase ? "" : child].map(activityPhase).find(Boolean) || "";
  const rawStatus = status || legacyPhase || child;
  const result: SessionActivityState = { execution: "unknown", phase: "", outcome: "", reason: "", rawStatus };
  const execution = current.map(activityExecution).find(Boolean);
  if (execution || session.activeTurnId || (options?.runtimeRunning && options.authoritativeRuntime)) {
    return { ...result, execution: (execution || "running") as SessionActivityState["execution"], phase };
  }
  if (rawStatus && !activityOutcome(rawStatus) && !isActivityResting(rawStatus)) return result;
  const reason = normalizeActivityValue(session.terminalReason);
  if (reason && !activityOutcome(reason) && !["ready", "idle", "running"].includes(reason)) return result;
  const terminal = [reason, status, legacyPhase, normalizeActivityValue(session.lastTurnStatus), child].find(activityOutcome);
  if (terminal) return { ...result, execution: "settled", outcome: activityOutcome(terminal), reason: terminal };
  if (options?.runtimeRunning && !current.includes("ready")) return { ...result, execution: "running" };
  if (current.some(isActivityResting)) return { ...result, execution: "idle" };
  return result;
}

/** A resting Session can have no outcome at all. It is never successful by itself. */
export function sessionTerminalStatus(session: SessionActivitySource): string {
  const state = resolveSessionActivity(session);
  if (state.outcome) return state.reason;
  return state.execution === "idle" ? "ready" : "";
}
