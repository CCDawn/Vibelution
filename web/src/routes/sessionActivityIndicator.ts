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
  activityExecution, activityOutcome, activityOutputActive, isActivityResting, resolveSessionActivity,
} from "./sessionActivityState";

// `completed` is the legacy unread-reply indicator, not a successful Turn verdict.
export type SessionActivityTone = "running" | "stopping" | "paused" | "approval" | "error" | "completed" | "none";

const SEEN_STORAGE_KEY = "vibelution.session-activity-seen.v1";

type SeenMap = Record<string, string | string[]>;
const MAX_SEEN_STAMPS_PER_SESSION = 12;
/**
 * Parsed-map cache. Session rows call `isSessionActivitySeen` and
 * `hasPriorSessionActivitySeen` on every paint; re-parsing the stored map per
 * call dominated keystroke cost (localStorage read + JSON.parse per row).
 * The cache is validated against the raw string so writes from anywhere win.
 */
let seenMapCache: { raw: string; map: SeenMap } | null = null;
/**
 * Tone cache. `resolveSessionActivityTone` runs for every session row on every
 * paint, and a keystroke repaints the workbench. The tone is a pure function of
 * the row snapshot plus the read-stamp state, so the signature cache is exact;
 * `writeSeenMap` clears it because stamps are its only mutable input.
 */
const TONE_CACHE_LIMIT = 600;
const toneCache = new Map<string, SessionActivityTone>();

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
      seenMapCache = null;
      return {};
    }
    if (seenMapCache && seenMapCache.raw === raw) {
      return seenMapCache.map;
    }
    const parsed = JSON.parse(raw) as unknown;
    const map = parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as SeenMap
      : {};
    seenMapCache = { raw, map };
    return map;
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
    const raw = JSON.stringify(map);
    storage.setItem(SEEN_STORAGE_KEY, raw);
    seenMapCache = { raw, map };
    toneCache.clear();
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
  const wrote = writeSeenMap(map);
  if (wrote) {
    // Reading the row retires its live badge: the operator has seen it now.
    clearSessionLiveCompletion(id);
  }
  return wrote;
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

/**
 * Settles this window watched arrive on the index stream.
 *
 * ``hasPriorSessionActivitySeen`` below silences rows nobody has read so a cold
 * start does not paint the whole history as unread. That silence must not cover
 * a completion the server pushed while the operator was looking at another
 * session: that row has never been opened, and the push is the only signal the
 * rail will get. Tracking it separately keeps the two cases apart.
 */
const liveCompletionIds = new Set<string>();
const LIVE_COMPLETION_LIMIT = 200;

export function markSessionLiveCompletion(sessionId: string) {
  const id = String(sessionId || "").trim();
  if (!id || liveCompletionIds.has(id)) {
    return;
  }
  liveCompletionIds.add(id);
  if (liveCompletionIds.size > LIVE_COMPLETION_LIMIT) {
    const oldest = liveCompletionIds.values().next().value;
    if (oldest !== undefined) {
      liveCompletionIds.delete(oldest);
    }
  }
  toneCache.clear();
}

export function clearSessionLiveCompletion(sessionId: string) {
  const id = String(sessionId || "").trim();
  if (!id || !liveCompletionIds.delete(id)) {
    return;
  }
  toneCache.clear();
}

export function hasSessionLiveCompletion(sessionId: string) {
  const id = String(sessionId || "").trim();
  return Boolean(id) && liveCompletionIds.has(id);
}

/** Resting state, independent of the previous Turn's result. */
export function sessionIsIdleRestingStatus(value: string | null | undefined) {
  return isActivityResting(value);
}

export function sessionIsErrorStatus(value: string | null | undefined) {
  return activityOutcome(value) === "failed";
}

export function sessionIsRunningStatus(value: string | null | undefined) {
  return activityOutputActive(value);
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
  return activityOutputActive(state.execution) ? state.phase || state.execution : state.outcome || state.execution;
}

function computeSessionActivityTone(
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
    /** Fresh local optimistic turn: it outranks a resting summary, unlike the
     *  possibly-stale runtime flag above. */
    isOptimisticRunning?: boolean;
    /** When true, completed activity is treated as already read. */
    isActive?: boolean;
  },
): SessionActivityTone {
  if (options?.needsApproval) {
    return "approval";
  }
  // A just-submitted turn is fresher than the summary: the session row
  // still reads ``ready`` until the runtime/summary refresh lands, and the
  // resting short-circuit below would otherwise hide the spinner that whole gap.
  if (options?.isOptimisticRunning) {
    return "running";
  }
  const state = resolveSessionActivity(session, { runtimeRunning: options?.isRuntimeRunning });
  if (state.execution === "paused") {
    return "paused";
  }
  if (state.execution === "stopping") {
    return "stopping";
  }
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
    if (
      !inboxPending
      && state.execution === "idle"
      && !hasPriorSessionActivitySeen(sessionId)
      && !hasSessionLiveCompletion(sessionId)
    ) {
      return "none";
    }
    return "completed";
  }
  return "none";
}

type SessionActivityToneInput = Parameters<typeof computeSessionActivityTone>[0];
type SessionActivityToneOptions = NonNullable<Parameters<typeof computeSessionActivityTone>[1]>;

function toneCacheKey(
  session: SessionActivityToneInput,
  options: SessionActivityToneOptions | undefined,
) {
  return [
    session.id,
    session.childStatus,
    session.currentPhase,
    session.status,
    session.lastTurnStatus,
    session.terminalReason,
    session.sessionKind,
    session.taskSummary,
    session.agentInboxPendingCount,
    options?.needsApproval ? 1 : 0,
    options?.isRuntimeRunning ? 1 : 0,
    options?.isOptimisticRunning ? 1 : 0,
    options?.isActive ? 1 : 0,
    hasSessionLiveCompletion(String(session.id || "")) ? 1 : 0,
  ].join("\u0001");
}

/**
 * Cached tone. Rows re-evaluate on every paint and a keystroke repaints the
 * workbench, so the value is memoised on the snapshot signature.
 */
export function resolveSessionActivityTone(
  session: SessionActivityToneInput,
  options?: SessionActivityToneOptions,
): SessionActivityTone {
  const key = toneCacheKey(session, options);
  const cached = toneCache.get(key);
  if (cached !== undefined) {
    return cached;
  }
  const tone = computeSessionActivityTone(session, options);
  if (toneCache.size >= TONE_CACHE_LIMIT) {
    toneCache.clear();
  }
  toneCache.set(key, tone);
  return tone;
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
  if (tones.some((tone) => tone === "stopping")) {
    return "stopping";
  }
  if (tones.some((tone) => tone === "paused")) {
    return "paused";
  }
  if (tones.some((tone) => tone === "completed")) {
    return "completed";
  }
  return "none";
}

export function sessionActivityLabel(tone: SessionActivityTone, lang: "zh" | "en") {
  if (tone === "stopping") {
    return lang === "zh" ? "停止中" : "Stopping";
  }
  if (tone === "paused") {
    return lang === "zh" ? "已暂停" : "Paused";
  }
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
