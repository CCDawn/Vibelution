/**
 * Shared left-rail / tab activity indicators.
 *
 * Green spinner  = session in progress
 * Yellow spinner = needs approval
 * Red light      = error
 * Blue light     = completed (unread); clears after read
 * No indicator   = idle / already read
 */

export type SessionActivityTone = "running" | "approval" | "error" | "completed" | "none";

const SEEN_STORAGE_KEY = "vibelution.session-activity-seen.v1";

type SeenMap = Record<string, string>;

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

function writeSeenMap(map: SeenMap) {
  const storage = activityStorage();
  if (!storage) {
    return;
  }
  try {
    storage.setItem(SEEN_STORAGE_KEY, JSON.stringify(map));
  } catch {
    // ignore quota / private mode
  }
}

export function sessionActivityStamp(
  session: {
    id?: string;
    updatedAt?: string;
    lastActive?: string;
    lastTurnStatus?: string;
  },
) {
  return String(session.updatedAt || session.lastActive || session.lastTurnStatus || session.id || "").trim();
}

export function markSessionActivitySeen(sessionId: string, stamp: string) {
  const id = String(sessionId || "").trim();
  const activityStamp = String(stamp || "").trim();
  if (!id || !activityStamp) {
    return;
  }
  const map = readSeenMap();
  if (map[id] === activityStamp) {
    return;
  }
  map[id] = activityStamp;
  writeSeenMap(map);
}

export function isSessionActivitySeen(sessionId: string, stamp: string) {
  const id = String(sessionId || "").trim();
  const activityStamp = String(stamp || "").trim();
  if (!id || !activityStamp) {
    // Without a stable id/stamp we cannot mark as read; keep completed visible.
    return false;
  }
  return readSeenMap()[id] === activityStamp;
}

export function sessionIsErrorStatus(value: string | null | undefined) {
  const status = String(value ?? "").trim().toLowerCase();
  return [
    "error",
    "failed",
    "failure",
    "failed_runtime",
    "failed_provider",
    "blocked",
    "danger",
    "crashed",
    "unhealthy",
  ].includes(status);
}

export function sessionIsRunningStatus(value: string | null | undefined) {
  const status = String(value ?? "").trim().toLowerCase();
  return [
    "queued",
    "running",
    "active",
    "thinking",
    "tooling",
    "tool",
    "answering",
    "streaming",
    "checking",
    "planning",
    "reading",
    "editing",
    "verifying",
    "working",
    "in_progress",
    "starting",
    "stopping",
  ].includes(status);
}

export function sessionIsCompletedStatus(value: string | null | undefined) {
  const status = String(value ?? "").trim().toLowerCase();
  return [
    "ready",
    "completed",
    "done",
    "success",
    "succeeded",
    "needs_continue",
    "paused",
    "paused_limit",
    "stopped",
    "stopped_by_user",
    "cancelled",
    "canceled",
    "superseded",
  ].includes(status);
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
  const isChild = String(session.sessionKind ?? "").trim() === "child";
  const ordered = isChild
    ? [session.childStatus, session.currentPhase, session.status, session.lastTurnStatus]
    : [session.currentPhase, session.status, session.lastTurnStatus];
  return ordered.map((value) => String(value ?? "").trim()).filter(Boolean);
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
  return sessionStatusCandidates(session)[0] || "";
}

export function resolveSessionActivityTone(
  session: {
    id?: string;
    childStatus?: string;
    currentPhase?: string;
    status?: string;
    lastTurnStatus?: string;
    sessionKind?: string;
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
  const candidates = sessionStatusCandidates(session);
  // Any field may report the live phase; prefer error/running over a stale primary.
  if (candidates.some((value) => sessionIsErrorStatus(value))) {
    return "error";
  }
  // A real live phase always reports running. The runtime-running flag only
  // covers lagging statuses and must not override a terminal authoritative one.
  if (candidates.some((value) => sessionIsRunningStatus(value))) {
    return "running";
  }
  const status = candidates[0] || "";
  if (options?.isRuntimeRunning && !sessionIsCompletedStatus(status)) {
    return "running";
  }
  if (sessionIsCompletedStatus(status) || Number(session.agentInboxPendingCount || 0) > 0) {
    if (options?.isActive) {
      return "none";
    }
    const stamp = sessionActivityStamp(session);
    if (!isSessionActivitySeen(String(session.id || ""), stamp)) {
      return "completed";
    }
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
    return lang === "zh" ? "已完成" : "Completed";
  }
  return "";
}
