import type { SessionStreamEvent } from "../api/types";

export type SessionAssistantDeltaPayload = Extract<SessionStreamEvent, { type: "assistant_delta" }>;
export type SessionAssistantDeltaDrainReason = "frame" | "close" | "final";
export type SessionAssistantDeltaDrainMode = "smooth" | "catch_up" | "final";

export type QueuedSessionAssistantDelta = {
  payload: SessionAssistantDeltaPayload;
  payloadLength: number;
  receivedAtMs: number;
};

export type SessionAssistantDeltaDrainTelemetry = {
  payloadLength: number;
  turnId: string;
  stage: string;
  contentDeltaLength: number;
  thoughtDeltaLength: number;
  batchSize: number;
  done: boolean;
  oldestReceivedAtMs: number;
  newestReceivedAtMs: number;
  frameScheduledAtMs: number;
};

export type SessionAssistantDeltaDrainResult = {
  reason: SessionAssistantDeltaDrainReason;
  mode: SessionAssistantDeltaDrainMode;
  entries: QueuedSessionAssistantDelta[];
  pendingBefore: number;
  pendingAfter: number;
  batchSize: number;
  oldestQueuedAgeMs: number;
  shouldContinue: boolean;
  telemetry: SessionAssistantDeltaDrainTelemetry;
};

type SessionAssistantDeltaSchedulerOptions = {
  nowMs?: () => number;
};

type SessionAssistantDeltaDrainOptions = {
  frameScheduledAtMs?: number;
};

const ENTER_CATCH_UP_QUEUE_DEPTH = 8;
const ENTER_CATCH_UP_OLDEST_AGE_MS = 120;

export function createSessionAssistantDeltaScheduler(
  options: SessionAssistantDeltaSchedulerOptions = {},
) {
  return new SessionAssistantDeltaScheduler(options);
}

class SessionAssistantDeltaScheduler {
  private readonly nowMs: () => number;
  private queue: QueuedSessionAssistantDelta[] = [];

  constructor(options: SessionAssistantDeltaSchedulerOptions) {
    this.nowMs = options.nowMs ?? Date.now;
  }

  enqueue(payload: SessionAssistantDeltaPayload, payloadLength: number) {
    const receivedAtMs = this.nowMs();
    this.queue.push({ payload, payloadLength, receivedAtMs });
    return {
      receivedAtMs,
      pendingCount: this.queue.length,
      contentDeltaLength: assistantDeltaContentLength(payload),
      thoughtDeltaLength: assistantDeltaThoughtLength(payload),
      done: payload.done,
    };
  }

  drain(
    reason: SessionAssistantDeltaDrainReason,
    options: SessionAssistantDeltaDrainOptions = {},
  ): SessionAssistantDeltaDrainResult {
    const pendingBefore = this.queue.length;
    const nowMs = this.nowMs();
    const oldestQueuedAgeMs = oldestQueuedAge(this.queue, nowMs);
    const mode = reason === "frame" && !this.shouldCatchUp(nowMs) ? "smooth" : reason === "frame" ? "catch_up" : "final";
    const drainCount = mode === "smooth" ? Math.min(1, pendingBefore) : pendingBefore;
    const entries = drainCount > 0 ? this.queue.splice(0, drainCount) : [];
    const pendingAfter = this.queue.length;

    return {
      reason,
      mode,
      entries,
      pendingBefore,
      pendingAfter,
      batchSize: entries.length,
      oldestQueuedAgeMs,
      shouldContinue: pendingAfter > 0,
      telemetry: assistantDeltaDrainTelemetry(entries, options.frameScheduledAtMs ?? 0),
    };
  }

  cancel() {
    this.queue = [];
  }

  get pendingCount() {
    return this.queue.length;
  }

  private shouldCatchUp(nowMs: number) {
    return this.queue.length >= ENTER_CATCH_UP_QUEUE_DEPTH
      || oldestQueuedAge(this.queue, nowMs) >= ENTER_CATCH_UP_OLDEST_AGE_MS;
  }
}

function assistantDeltaDrainTelemetry(
  entries: QueuedSessionAssistantDelta[],
  frameScheduledAtMs: number,
): SessionAssistantDeltaDrainTelemetry {
  const lastPayload = entries[entries.length - 1]?.payload;
  return {
    payloadLength: sum(entries, (entry) => entry.payloadLength),
    turnId: lastPayload?.turnId ?? "",
    stage: lastPayload?.stage ?? "",
    contentDeltaLength: sum(entries, (entry) => assistantDeltaContentLength(entry.payload)),
    thoughtDeltaLength: sum(entries, (entry) => assistantDeltaThoughtLength(entry.payload)),
    batchSize: entries.length,
    done: entries.some((entry) => entry.payload.done),
    oldestReceivedAtMs: entries.length > 0 ? Math.min(...entries.map((entry) => entry.receivedAtMs)) : 0,
    newestReceivedAtMs: entries.length > 0 ? Math.max(...entries.map((entry) => entry.receivedAtMs)) : 0,
    frameScheduledAtMs,
  };
}

function assistantDeltaContentLength(payload: SessionAssistantDeltaPayload) {
  return (payload.contentDelta ?? payload.content ?? "").length;
}

function assistantDeltaThoughtLength(payload: SessionAssistantDeltaPayload) {
  return (payload.thoughtDelta ?? payload.thought ?? "").length;
}

function oldestQueuedAge(queue: QueuedSessionAssistantDelta[], nowMs: number) {
  const oldest = queue[0];
  return oldest ? Math.max(0, nowMs - oldest.receivedAtMs) : 0;
}

function sum<T>(items: T[], mapper: (item: T) => number) {
  return items.reduce((total, item) => total + mapper(item), 0);
}
