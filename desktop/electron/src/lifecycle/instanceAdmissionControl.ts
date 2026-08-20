export const ADMISSION_BURST = 3;
export const ADMISSION_WINDOW_MS = 10_000;
export const COOLDOWN_INITIAL_MS = 10_000;
export const COOLDOWN_CAP_MS = 300_000;
export const MAIN_INSTANCE_ID = "main";
export const RATE_LIMITED_CODE = "rate_limited";
export const CRASH_LOOP_BACKOFF_CODE = "crash_loop_backoff";
export const RATE_LIMITED_EVENT = "launcher.admission.rate_limited";
export const COOLDOWN_EVENT = "launcher.admission.cooldown";

export const START_LIKE_OPERATIONS = new Set([
  "start",
  "restart",
  "rebuild-and-start",
  "open"
]);

export type AdmissionCode = "" | typeof RATE_LIMITED_CODE | typeof CRASH_LOOP_BACKOFF_CODE;

export type AdmissionRecord = {
  startTimestampsMs: number[];
  consecutiveFailures: number;
  cooldownUntilMs: number;
};

export type AdmissionDecision = {
  admitted: boolean;
  code: AdmissionCode;
  retryAfterMs: number;
  message: string;
  eventName?: typeof RATE_LIMITED_EVENT | typeof COOLDOWN_EVENT;
};

export class AdmissionDeniedError extends Error {
  readonly code: typeof RATE_LIMITED_CODE | typeof CRASH_LOOP_BACKOFF_CODE;
  readonly retryAfterMs: number;
  readonly instanceId: string;
  readonly eventName: typeof RATE_LIMITED_EVENT | typeof COOLDOWN_EVENT;

  constructor(input: {
    instanceId: string;
    code: typeof RATE_LIMITED_CODE | typeof CRASH_LOOP_BACKOFF_CODE;
    retryAfterMs: number;
    message: string;
    eventName: typeof RATE_LIMITED_EVENT | typeof COOLDOWN_EVENT;
  }) {
    super(input.message);
    this.name = "AdmissionDeniedError";
    this.instanceId = input.instanceId;
    this.code = input.code;
    this.retryAfterMs = input.retryAfterMs;
    this.eventName = input.eventName;
  }
}

export function emptyAdmissionRecord(): AdmissionRecord {
  return {
    startTimestampsMs: [],
    consecutiveFailures: 0,
    cooldownUntilMs: 0
  };
}

export function isStartLikeOperation(operation: string): boolean {
  return START_LIKE_OPERATIONS.has(String(operation || "").trim().toLowerCase());
}

export function cooldownDelayMs(consecutiveFailures: number): number {
  const failures = Math.max(0, Math.trunc(consecutiveFailures));
  if (failures <= 0) {
    return 0;
  }
  const raw = COOLDOWN_INITIAL_MS * 2 ** (failures - 1);
  return Math.min(COOLDOWN_CAP_MS, raw);
}

export function remainingMs(untilMs: number, nowMs: number): number {
  return Math.max(0, Math.trunc(untilMs) - Math.trunc(nowMs));
}

export function pruneStartTimestamps(timestamps: number[], nowMs: number, windowMs = ADMISSION_WINDOW_MS): number[] {
  const floor = Math.trunc(nowMs) - windowMs;
  return timestamps.filter((stamp) => Number.isFinite(stamp) && stamp > floor).map((stamp) => Math.trunc(stamp));
}

export function formatAdmissionMessage(code: AdmissionCode, retryAfterMs: number): string {
  const seconds = Math.max(1, Math.ceil(Math.max(0, retryAfterMs) / 1000));
  if (code === RATE_LIMITED_CODE) {
    return `启动过于频繁，请 ${seconds} 秒后再试。`;
  }
  if (code === CRASH_LOOP_BACKOFF_CODE) {
    return `连续启动失败，冷却中，请 ${seconds} 秒后再试。`;
  }
  return "";
}

export function decideAdmission(
  record: AdmissionRecord,
  nowMs: number,
  operation = "start"
): AdmissionDecision {
  if (!isStartLikeOperation(operation)) {
    return { admitted: true, code: "", retryAfterMs: 0, message: "" };
  }
  const cooldownLeft = remainingMs(record.cooldownUntilMs, nowMs);
  if (cooldownLeft > 0) {
    return {
      admitted: false,
      code: CRASH_LOOP_BACKOFF_CODE,
      retryAfterMs: cooldownLeft,
      message: formatAdmissionMessage(CRASH_LOOP_BACKOFF_CODE, cooldownLeft),
      eventName: COOLDOWN_EVENT
    };
  }
  const recent = pruneStartTimestamps(record.startTimestampsMs, nowMs);
  if (recent.length >= ADMISSION_BURST) {
    const oldest = Math.min(...recent);
    const retryAfterMs = remainingMs(oldest + ADMISSION_WINDOW_MS, nowMs) || ADMISSION_WINDOW_MS;
    return {
      admitted: false,
      code: RATE_LIMITED_CODE,
      retryAfterMs,
      message: formatAdmissionMessage(RATE_LIMITED_CODE, retryAfterMs),
      eventName: RATE_LIMITED_EVENT
    };
  }
  return { admitted: true, code: "", retryAfterMs: 0, message: "" };
}

export function recordAdmittedStart(record: AdmissionRecord, nowMs: number): AdmissionRecord {
  const startTimestampsMs = pruneStartTimestamps([...record.startTimestampsMs, Math.trunc(nowMs)], nowMs);
  return {
    ...record,
    startTimestampsMs,
    cooldownUntilMs: remainingMs(record.cooldownUntilMs, nowMs) > 0 ? record.cooldownUntilMs : 0
  };
}

export function recordAdmissionFailure(record: AdmissionRecord, nowMs: number): AdmissionRecord {
  const consecutiveFailures = Math.max(0, Math.trunc(record.consecutiveFailures)) + 1;
  return {
    ...record,
    consecutiveFailures,
    cooldownUntilMs: Math.trunc(nowMs) + cooldownDelayMs(consecutiveFailures)
  };
}

export function recordAdmissionSuccess(record: AdmissionRecord): AdmissionRecord {
  return {
    ...record,
    consecutiveFailures: 0,
    cooldownUntilMs: 0
  };
}

export function deniedLifecycleResult(input: {
  operation: string;
  instanceId?: string;
  decision: AdmissionDecision;
}): {
  schemaVersion: 1;
  accepted: false;
  operation: string;
  instanceId?: string;
  code: AdmissionCode;
  message: string;
  retryAfterMs: number;
} {
  return {
    schemaVersion: 1,
    accepted: false,
    operation: input.operation,
    ...(input.instanceId ? { instanceId: input.instanceId } : {}),
    code: input.decision.code,
    message: input.decision.message,
    retryAfterMs: input.decision.retryAfterMs
  };
}
