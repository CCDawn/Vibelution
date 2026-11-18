import { mkdirSync, readFileSync, readdirSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { appendSupervisorEventFallback } from "./supervisorEventFallback.js";

export const DEFERRED_RESTART_INTENTS_DIR_NAME = "restart-intents";
export const DEFERRED_RESTART_INTENT_TARGET = "workbench_restart";
export const DEFERRED_RESTART_INTENT_ACTION = "restart_workbench";
export const DEFERRED_RESTART_FULFILLED_BY = "electron_main";

/**
 * The Python runtime-manager daemon that used to consume these intents is not
 * part of the Electron-owned product path (ADR 0009 I6), so Electron main owns
 * fulfilment now. A pending intent is the durable form of "restart when the
 * active work ends"; honour it while that promise is still meaningful, expire
 * it once it is old enough that firing would surprise the operator.
 */
export const DEFERRED_RESTART_INTENT_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

export type DeferredRestartIntent = Record<string, unknown> & {
  intentId: string;
  status: string;
};

export type DeferredRestartFulfillmentOutcome =
  | { status: "none" }
  | { status: "expired"; intentIds: string[] }
  | { status: "blocked"; activeWorkCount: number }
  | { status: "fulfilled"; intentId: string }
  | { status: "requeued"; intentId: string }
  | { status: "failed"; intentId: string; message: string };

export type FulfillDeferredRestartIntentInput = {
  workspaceRoot: string;
  runtimeManagerDir: string;
  listActiveWork: () => readonly unknown[] | Promise<readonly unknown[]>;
  submitRestart: () => Promise<{ accepted: boolean; code?: string; message?: string }>;
  now?: () => number;
  /** Management-only attachment may fulfil new requests without replaying old ones. */
  notBefore?: number;
  /**
   * Operator-initiated restarts must not queue behind running work. The caller
   * decides per intent which requests may interrupt; self-evolution keeps its
   * "restart when idle" promise, everything else runs now.
   */
  interruptActiveWorkFor?: (intent: DeferredRestartIntent) => boolean;
};

type IntentStatus = "pending" | "claimed" | "completed" | "failed" | "expired" | "superseded";

/** Terminal intents keep no durable promise; their settle events are already
 * recorded in the supervisor event fallback, so the files are garbage. */
const TERMINAL_INTENT_STATUSES: ReadonlySet<string> = new Set<IntentStatus>([
  "completed", "failed", "expired", "superseded"
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function deferredRestartIntentsDir(runtimeManagerDir: string): string {
  return join(runtimeManagerDir, DEFERRED_RESTART_INTENTS_DIR_NAME);
}

function deferredRestartIntentPath(runtimeManagerDir: string, intentId: string): string {
  return join(deferredRestartIntentsDir(runtimeManagerDir), `${intentId}.json`);
}

function readDeferredRestartIntent(path: string): DeferredRestartIntent | null {
  try {
    const parsed = JSON.parse(readFileSync(path, "utf8")) as unknown;
    if (!isRecord(parsed)) {
      return null;
    }
    const intentId = String(parsed.intentId || "").trim();
    if (!intentId) {
      return null;
    }
    return { ...parsed, intentId, status: String(parsed.status || "").trim().toLowerCase() };
  } catch {
    return null;
  }
}

function writeDeferredRestartIntent(runtimeManagerDir: string, intent: DeferredRestartIntent): void {
  const target = deferredRestartIntentPath(runtimeManagerDir, intent.intentId);
  const temporary = `${target}.${process.pid}.tmp`;
  try {
    mkdirSync(deferredRestartIntentsDir(runtimeManagerDir), { recursive: true });
    writeFileSync(temporary, `${JSON.stringify(intent, null, 2)}\n`, "utf8");
    renameSync(temporary, target);
  } catch {
    // Intent bookkeeping is crash-recovery assistance; it must never break a
    // lifecycle command or the fulfilment poll.
  }
}

function recordIntentEvent(
  workspaceRoot: string,
  intent: DeferredRestartIntent,
  eventCode: string,
  message: string,
  fields: Record<string, unknown> = {}
): void {
  appendSupervisorEventFallback(workspaceRoot, {
    eventCode,
    message,
    fields: {
      intentId: intent.intentId,
      target: String(intent.target || ""),
      status: String(intent.status || ""),
      attempts: Number(intent.attempts || 0),
      ...fields
    }
  });
}

function settleDeferredRestartIntent(input: {
  workspaceRoot: string;
  runtimeManagerDir: string;
  intent: DeferredRestartIntent;
  status: IntentStatus;
  message?: string;
  eventCode?: string;
  eventMessage?: string;
  extra?: Record<string, unknown>;
  now?: () => number;
}): DeferredRestartIntent {
  const now = input.now ?? Date.now;
  const updated: DeferredRestartIntent = {
    ...input.intent,
    ...(input.extra ?? {}),
    status: input.status,
    updatedAt: new Date(now()).toISOString(),
    ...(input.message ? { message: input.message.slice(0, 500) } : {})
  };
  writeDeferredRestartIntent(input.runtimeManagerDir, updated);
  if (input.eventCode) {
    recordIntentEvent(
      input.workspaceRoot,
      updated,
      input.eventCode,
      input.eventMessage || input.message || input.eventCode,
      input.message ? { message: input.message.slice(0, 240) } : {}
    );
  }
  return updated;
}

export function listDeferredRestartIntents(runtimeManagerDir: string): DeferredRestartIntent[] {
  let names: string[] = [];
  try {
    names = readdirSync(deferredRestartIntentsDir(runtimeManagerDir));
  } catch {
    return [];
  }
  const intents: DeferredRestartIntent[] = [];
  for (const name of names) {
    if (!name.endsWith(".json")) {
      continue;
    }
    const intent = readDeferredRestartIntent(join(deferredRestartIntentsDir(runtimeManagerDir), name));
    if (intent) {
      intents.push(intent);
    }
  }
  return intents.sort((left, right) =>
    String(left.createdAt || "").localeCompare(String(right.createdAt || ""))
  );
}

function pendingIntentIsExpired(intent: DeferredRestartIntent, nowMs: number): boolean {
  const createdAtMs = Date.parse(String(intent.createdAt || ""));
  return Number.isFinite(createdAtMs) && nowMs - createdAtMs > DEFERRED_RESTART_INTENT_MAX_AGE_MS;
}

function intentTargetMatches(intent: DeferredRestartIntent): boolean {
  return String(intent.target || "") === DEFERRED_RESTART_INTENT_TARGET;
}

/**
 * One fulfilment pass for the durable "restart when the active work ends"
 * requests. Mirrors the retired daemon loop: claim the oldest pending intent,
 * execute through the Electron main-line restart, settle the intent either
 * way. Active work still blocks, and an intent that raced into the guard is
 * put back to pending because the restart path queued a fresh one.
 */
export async function fulfillDeferredRestartIntentOnce(
  input: FulfillDeferredRestartIntentInput
): Promise<DeferredRestartFulfillmentOutcome> {
  const now = input.now ?? Date.now;
  const pending = listDeferredRestartIntents(input.runtimeManagerDir).filter(
    (intent) => intent.status === "pending" && intentTargetMatches(intent)
      && (input.notBefore === undefined || Date.parse(String(intent.createdAt || "")) >= input.notBefore)
  );
  const expiredIds: string[] = [];
  const fresh: DeferredRestartIntent[] = [];
  for (const intent of pending) {
    if (pendingIntentIsExpired(intent, now())) {
      settleDeferredRestartIntent({
        workspaceRoot: input.workspaceRoot,
        runtimeManagerDir: input.runtimeManagerDir,
        intent,
        status: "expired",
        message: "Pending deferred restart expired without restarting the workbench.",
        eventCode: "restart.intent.expired",
        now
      });
      expiredIds.push(intent.intentId);
      continue;
    }
    fresh.push(intent);
  }
  const noFreshIntent: DeferredRestartFulfillmentOutcome = expiredIds.length > 0
    ? { status: "expired", intentIds: expiredIds } : { status: "none" };
  const candidate = fresh[0];
  if (!candidate) return noFreshIntent;
  const activeWorkCount = (await input.listActiveWork()).length;
  if (activeWorkCount > 0) {
    if (input.interruptActiveWorkFor?.(candidate) !== true) {
      return { status: "blocked", activeWorkCount };
    }
    // Explicit operator restarts stop the running work instead of waiting. The
    // interrupted turns are recovered by the existing restart reconciliation,
    // so this only records why the work was cut short.
    recordIntentEvent(
      input.workspaceRoot,
      candidate,
      "workbench.restart_intent_force_interrupt",
      `Deferred restart interrupted ${activeWorkCount} active work run(s) at operator request.`,
      { activeWorkCount }
    );
  }
  // A newer lifecycle command can supersede or prune the selected request
  // during the asynchronous work read. Never claim a replacement by accident.
  const intent = listDeferredRestartIntents(input.runtimeManagerDir).find(item => item.intentId === candidate.intentId);
  if (!intent || JSON.stringify(intent) !== JSON.stringify(candidate) || pendingIntentIsExpired(intent, now())) {
    return noFreshIntent;
  }
  const claimed = settleDeferredRestartIntent({
    workspaceRoot: input.workspaceRoot,
    runtimeManagerDir: input.runtimeManagerDir,
    intent,
    status: "claimed",
    eventCode: "restart.intent.claimed",
    eventMessage: "Deferred restart intent claimed by Electron main.",
    extra: {
      attempts: Math.max(0, Number(intent.attempts || 0)) + 1,
      claimedBy: DEFERRED_RESTART_FULFILLED_BY
    },
    now
  });
  const payload = isRecord(intent.payload) ? intent.payload : {};
  if (String(payload.action || "") !== DEFERRED_RESTART_INTENT_ACTION) {
    const message = "Unsupported workbench restart intent action.";
    settleDeferredRestartIntent({
      workspaceRoot: input.workspaceRoot,
      runtimeManagerDir: input.runtimeManagerDir,
      intent: claimed,
      status: "failed",
      message,
      eventCode: "restart.intent.failed",
      now
    });
    recordIntentEvent(input.workspaceRoot, claimed, "workbench.restart_intent_failed", message);
    return { status: "failed", intentId: intent.intentId, message };
  }
  let result: { accepted: boolean; code?: string; message?: string };
  try {
    result = await input.submitRestart();
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : String(error);
    settleDeferredRestartIntent({
      workspaceRoot: input.workspaceRoot,
      runtimeManagerDir: input.runtimeManagerDir,
      intent: claimed,
      status: "failed",
      message,
      eventCode: "restart.intent.failed",
      now
    });
    recordIntentEvent(input.workspaceRoot, claimed, "workbench.restart_intent_failed", message);
    return { status: "failed", intentId: intent.intentId, message };
  }
  if (result.accepted && result.code !== "restart_queued") {
    const message = String(result.message || "Deferred workbench restart fulfilled.");
    settleDeferredRestartIntent({
      workspaceRoot: input.workspaceRoot,
      runtimeManagerDir: input.runtimeManagerDir,
      intent: claimed,
      status: "completed",
      message,
      eventCode: "restart.intent.completed",
      now
    });
    recordIntentEvent(input.workspaceRoot, claimed, "workbench.restart_fulfilled_from_intent", message);
    return { status: "fulfilled", intentId: intent.intentId };
  }
  if (result.code === "restart_queued") {
    // Active work resumed between the idle check and the queued command, so
    // the restart path persisted a fresh intent. Retry this one later; the
    // executed restart supersedes the rest.
    settleDeferredRestartIntent({
      workspaceRoot: input.workspaceRoot,
      runtimeManagerDir: input.runtimeManagerDir,
      intent: claimed,
      status: "pending",
      message: "Active work resumed before the deferred restart executed; request stays queued.",
      now
    });
    return { status: "requeued", intentId: intent.intentId };
  }
  const message = String(result.message || result.code || "deferred restart command was not accepted");
  settleDeferredRestartIntent({
    workspaceRoot: input.workspaceRoot,
    runtimeManagerDir: input.runtimeManagerDir,
    intent: claimed,
    status: "failed",
    message,
    eventCode: "restart.intent.failed",
    now
  });
  recordIntentEvent(input.workspaceRoot, claimed, "workbench.restart_intent_failed", message);
  return { status: "failed", intentId: intent.intentId, message };
}

/**
 * Any executed lifecycle command settles the queued restart requests: the
 * operator already got a (re)start or a stop, so a later idle pass must not
 * restart the product again on an old promise.
 */
export function supersedePendingDeferredRestartIntents(input: {
  workspaceRoot: string;
  runtimeManagerDir: string;
  reason: string;
  now?: () => number;
}): string[] {
  const superseded: string[] = [];
  for (const intent of listDeferredRestartIntents(input.runtimeManagerDir)) {
    if (intent.status !== "pending" || !intentTargetMatches(intent)) {
      continue;
    }
    settleDeferredRestartIntent({
      workspaceRoot: input.workspaceRoot,
      runtimeManagerDir: input.runtimeManagerDir,
      intent,
      status: "superseded",
      message: input.reason,
      eventCode: "restart.intent.superseded",
      now: input.now
    });
    superseded.push(intent.intentId);
  }
  return superseded;
}

/**
 * Every restart rejection persists a fresh pending intent (workbench restart
 * guard), and fulfilment settles them failed/expired/completed/superseded —
 * but nothing removed the settled files, so a restart-happy operator
 * accumulated intents forever. Their settle events are durably recorded in
 * the supervisor event fallback, so the terminal files are garbage collected
 * here; pending/claimed files are never touched.
 */
export function pruneTerminalDeferredRestartIntents(input: {
  runtimeManagerDir: string;
}): string[] {
  const pruned: string[] = [];
  for (const intent of listDeferredRestartIntents(input.runtimeManagerDir)) {
    if (!TERMINAL_INTENT_STATUSES.has(intent.status) || !intentTargetMatches(intent)) {
      continue;
    }
    try {
      unlinkSync(deferredRestartIntentPath(input.runtimeManagerDir, intent.intentId));
      pruned.push(intent.intentId);
    } catch {
      // Best-effort GC: a locked or already-deleted file must not fail the
      // lifecycle command or the fulfilment poll this runs behind.
    }
  }
  return pruned;
}
