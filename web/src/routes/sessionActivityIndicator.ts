/**
 * Shared left-rail / tab activity indicators.
 *
 * Green spinner  = session in progress
 * Yellow spinner = needs approval
 * Red light      = error
 * Blue light     = unread message; clears after read, without claiming success
 * No indicator   = idle / already read
 *
 * `ready` is a persisted resting state, not a successful Turn verdict or an
 * unread event. Historical ready sessions stay idle until a previously read
 * session gets a new completion identity (last preview / turn status), not a
 * recency timestamp tick.
 */

import {
  activityExecution, activityOutcome, isActivityResting, resolveSessionActivity,
} from "./sessionActivityState";

// `completed` is the legacy unread-reply indicator, not a successful Turn verdict.
export type SessionActivityTone = "running" | "approval" | "error" | "completed" | "none";

const SEEN_STORAGE_KEY = "vibelution.session-activity-seen.v1";

type SeenMap = Record<string, string | string[]>;
const MAX_SEEN_STAMPS_PER_SESSION = 12;

function activityStorage() {
  try {
    return globalThis.localStorage;
  } catch {
    return undefined;
  }
}

function readSeenMap(): SeenMap {
  const storage = activityStorage();
  if (!storage) {
    return {};
  }
  try {
    const raw = storage.getItem(SEEN_STORAGE_KEY);
    if (!raw) {
      return {};
    }
    const parsed = JSON.parse(raw) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as SeenMap
      : {};
  } catch {
    return {};
  }
}

function writeSeenMap(map: SeenMap): boolean {
  const storage = activityStorage();
  if (!storage) {
    return false;
  }
  try {
    storage.setItem(SEEN_STORAGE_KEY, JSON.stringify(map));
    return true;
  } catch {
    // ignore quota / private mode; callers must not report a persisted mutation
    return false;
  }
}

type SessionActivityStampSource = {
  id?: string;
  taskSummary?: string;
  lastTurnStatus?: string;
  terminalReason?: string;
  updatedAt?: string;
  lastActive?: string;
};

function seenStampsFor(map: SeenMap, sessionId: string) {
  const raw = map[sessionId];
  if (typeof raw === "string") {
    const stamp = raw.trim();
    return stamp ? [stamp] : [];
  }
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.map((value) => String(value || "").trim()).filter(Boolean);
}

/**
 * Unread identity for a completion. Recency (`updatedAt` / `lastActive`) is
 * intentionally ignored: persist, title, and detail-merge rewrite those clocks
 * without a new turn the operator has not already seen.
 */
export function sessionActivityStamp(session: SessionActivityStampSource) {
  return String(
    session.taskSummary
    || session.lastTurnStatus
    || session.terminalReason
    || session.id
    || "",
  ).trim();
}

export function markSessionActivitySeen(sessionId: string, stamp: string) {
  const id = String(sessionId || "").trim();
  const activityStamp = String(stamp || "").trim();
  if (!id || !activityStamp) {
    return false;
  }
  const map = readSeenMap();
  const stamps = seenStampsFor(map, id);
  if (stamps.includes(activityStamp)) {
    return false;
  }
  const next = [...stamps, activityStamp];
  if (next.length > MAX_SEEN_STAMPS_PER_SESSION) {
    next.splice(0, next.length - MAX_SEEN_STAMPS_PER_SESSION);
  }
  map[id] = next;
  return writeSeenMap(map);
}

export function markSessionActivitySnapshotsSeen(
  sessionId: string,
  snapshots: Array<SessionActivityStampSource | null | undefined>,
) {
  let wrote = false;
  for (const snapshot of snapshots) {
    if (!snapshot) {
      continue;
    }
    if (markSessionActivitySeen(sessionId, sessionActivityStamp({
      id: sessionId,
      taskSummary: snapshot.taskSummary,
      lastTurnStatus: snapshot.lastTurnStatus,
      terminalReason: snapshot.terminalReason,
    }))) {
      wrote = true;
    }
  }
  return wrote;
}

export function isSessionActivitySeen(sessionId: string, stamp: string) {
  const id = String(sessionId || "").trim();
  const activityStamp = String(stamp || "").trim();
  if (!id || !activityStamp) {
    // Without a stable id/stamp we cannot mark as read; keep completed visible.
    return false;
  }
  return seenStampsFor(readSeenMap(), id).includes(activityStamp);
}

export function hasPriorSessionActivitySeen(sessionId: string) {
  const id = String(sessionId || "").trim();
  if (!id) {
    return false;
  }
  return seenStampsFor(readSeenMap(), id).length > 0;
}

/** Resting state, independent of the previous Turn's result. */
export function sessionIsIdleRestingStatus(value: string | null | undefined) {
  return isActivityResting(value);
}

export function sessionIsErrorStatus(value: string | null | undefined) {
  return activityOutcome(value) === "failed";
}

export function sessionIsRunningStatus(value: string | null | undefined) {
  return Boolean(activityExecution(value));
}

export function sessionIsCompletedStatus(value: string | null | undefined) {
  // Compatibility API used by unread/history filters; it means settled, not success.
  const outcome = activityOutcome(value);
  return value?.trim().toLowerCase() === "ready" || Boolean(outcome && outcome !== "failed");
}

export function sessionStatusCandidates(
  session: {
    childStatus?: string;
    currentPhase?: string;
    status?: string;
    lastTurnStatus?: string;
    sessionKind?: string;
  },
) {
  // Compatibility export: callers receive one resolved current interpretation,
  // rather than independently combining current and historical fields again.
  return [sessionPrimaryStatus(session)].filter(Boolean);
}

export function sessionPrimaryStatus(
  session: {
    childStatus?: string;
    currentPhase?: string;
    status?: string;
    lastTurnStatus?: string;
    sessionKind?: string;
  },
) {
  const state = resolveSessionActivity(session);
  return state.phase || (activityExecution(state.execution) ? state.execution : state.reason || state.rawStatus);
}

export function resolveSessionActivityTone(
  session: {
    id?: string;
    childStatus?: string;
    currentPhase?: string;
    status?: string;
    lastTurnStatus?: string;
    terminalReason?: string;
    sessionKind?: string;
    taskSummary?: string;
    updatedAt?: string;
    lastActive?: string;
    agentInboxPendingCount?: number;
  },
  options?: {
    needsApproval?: boolean;
    /** True when runtime reports an active chat_turn for this session. */
    isRuntimeRunning?: boolean;
    /** When true, completed activity is treated as already read. */
    isActive?: boolean;
  },
): SessionActivityTone {
  if (options?.needsApproval) {
    return "approval";
  }
  const state = resolveSessionActivity(session, { runtimeRunning: options?.isRuntimeRunning });
  if (activityExecution(state.execution)) {
    return "running";
  }
  if (state.outcome === "failed") {
    return "error";
  }
  const inboxPending = Number(session.agentInboxPendingCount || 0) > 0;
  if (state.execution === "settled" || (state.execution === "idle" && state.rawStatus === "ready") || inboxPending) {
    if (options?.isActive) {
      return "none";
    }
    const sessionId = String(session.id || "");
    const stamp = sessionActivityStamp(session);
    if (isSessionActivitySeen(sessionId, stamp)) {
      return "none";
    }
    if (!inboxPending && state.execution === "idle" && !hasPriorSessionActivitySeen(sessionId)) {
      return "none";
    }
    return "completed";
  }
  return "none";
}

/** Aggregate for an Agent row: approval > error > running > completed > none. */
export function resolveAgentActivityTone(
  tones: readonly SessionActivityTone[],
): SessionActivityTone {
  if (tones.some((tone) => tone === "approval")) {
    return "approval";
  }
  if (tones.some((tone) => tone === "error")) {
    return "error";
  }
  if (tones.some((tone) => tone === "running")) {
    return "running";
  }
  if (tones.some((tone) => tone === "completed")) {
    return "completed";
  }
  return "none";
}

export function sessionActivityLabel(tone: SessionActivityTone, lang: "zh" | "en") {
  if (tone === "running") {
    return lang === "zh" ? "会话进行" : "In session";
  }
  if (tone === "approval") {
    return lang === "zh" ? "需审批" : "Approval";
  }
  if (tone === "error") {
    return lang === "zh" ? "出错" : "Error";
  }
  if (tone === "completed") {
    return lang === "zh" ? "有新消息" : "Unread message";
  }
  return "";
}
