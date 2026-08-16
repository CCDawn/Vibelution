import { collectBrowserPageSnapshot, postBrowserTelemetry } from "./browserTelemetry";

export const USER_ACTION_SLOW_THRESHOLD_MS = 300;

export type UserActionOutcome = "started" | "succeeded" | "failed" | "blocked" | "observed";

export type UserActionTracker = {
  succeeded: (fields?: Record<string, unknown>) => void;
  failed: (error?: unknown, fields?: Record<string, unknown>) => void;
  blocked: (guardReason: string, fields?: Record<string, unknown>) => void;
};

let operationCounter = 0;

function nextClientOperationId(action: string): string {
  operationCounter += 1;
  return `${action}-${Date.now()}-${operationCounter}`;
}

function nowMonotonicMs(): number {
  if (typeof performance !== "undefined" && typeof performance.now === "function") {
    return performance.now();
  }
  return Date.now();
}

function truncateText(value: string, limit: number): string {
  const text = String(value ?? "");
  if (text.length <= limit) {
    return text;
  }
  return `${text.slice(0, Math.max(0, limit - 3))}...`;
}

function extractErrorFields(error: unknown): Record<string, unknown> {
  if (error instanceof Error) {
    return {
      errorName: error.name,
      errorMessage: truncateText(error.message, 240),
    };
  }
  if (error !== undefined) {
    return { errorMessage: truncateText(String(error), 240) };
  }
  return {};
}

export function isDestructiveUserAction(action: string): boolean {
  const normalized = String(action || "").trim().toLowerCase();
  return (
    normalized.includes("delete")
    || normalized.includes("reset")
    || normalized.includes("revoke")
    || normalized.includes("clear")
  );
}

export function shouldSuppressUserActionTimelineIndex(options: {
  outcome: UserActionOutcome;
  durationMs?: number;
  destructive?: boolean;
  forceTimeline?: boolean;
}): boolean {
  if (options.forceTimeline) {
    return false;
  }
  if (options.outcome === "failed" || options.outcome === "blocked") {
    return false;
  }
  if (options.destructive ?? false) {
    return false;
  }
  const durationMs = options.durationMs ?? 0;
  return durationMs < USER_ACTION_SLOW_THRESHOLD_MS;
}

export function userActionRouteContextFields(): Record<string, unknown> {
  const snapshot = collectBrowserPageSnapshot();
  return {
    pathname: snapshot.pathname ?? "",
    routeSearch: snapshot.search ?? "",
    activeNavHref: snapshot.activeNavHref ?? "",
    pageInstanceId: snapshot.pageInstanceId ?? "",
  };
}

export function userActionEventCode(action: string, phase: UserActionOutcome): string {
  return `browser.user_action.${action}_${phase}`;
}

export function postUserActionTelemetry(
  action: string,
  phase: UserActionOutcome,
  fields: Record<string, unknown> = {},
  level: "info" | "warning" | "error" = "info",
  options: {
    destructive?: boolean;
    durationMs?: number;
    forceTimeline?: boolean;
  } = {},
) {
  const destructive = options.destructive ?? isDestructiveUserAction(action);
  const durationMs = options.durationMs;
  const controlSignal = shouldSuppressUserActionTimelineIndex({
    outcome: phase,
    durationMs,
    destructive,
    forceTimeline: options.forceTimeline,
  });
  postBrowserTelemetry({
    phase: "user_action",
    eventCode: userActionEventCode(action, phase),
    message: `User action ${phase}`,
    level,
    fields: {
      action,
      outcome: phase,
      ...userActionRouteContextFields(),
      ...fields,
      ...(typeof durationMs === "number" ? { durationMs } : {}),
      ...(controlSignal ? { controlSignal: true } : {}),
    },
  });
}

export function startUserAction(
  action: string,
  fields: Record<string, unknown> = {},
  options: { destructive?: boolean } = {},
): UserActionTracker {
  const clientOperationId = nextClientOperationId(action);
  const startedAtMs = nowMonotonicMs();
  const destructive = options.destructive ?? isDestructiveUserAction(action);
  const baseFields = {
    clientOperationId,
    ...fields,
  };

  postUserActionTelemetry(action, "started", baseFields, "info", { destructive });

  const finish = (
    phase: "succeeded" | "failed" | "blocked",
    level: "info" | "warning" | "error",
    extraFields: Record<string, unknown>,
  ) => {
    const durationMs = Math.round(nowMonotonicMs() - startedAtMs);
    postUserActionTelemetry(action, phase, {
      ...baseFields,
      ...extraFields,
    }, level, { destructive, durationMs });
  };

  return {
    succeeded: (extra = {}) => finish("succeeded", "info", extra),
    failed: (error, extra = {}) => finish("failed", "error", { ...extractErrorFields(error), ...extra }),
    blocked: (guardReason, extra = {}) => finish(
      "blocked",
      "warning",
      { guardReason: truncateText(guardReason, 160), ...extra },
    ),
  };
}

export function postUserActionObservation(
  action: string,
  fields: Record<string, unknown> = {},
  options: {
    level?: "info" | "warning";
    destructive?: boolean;
    forceTimeline?: boolean;
  } = {},
) {
  postUserActionTelemetry(action, "observed", fields, options.level ?? "info", {
    destructive: options.destructive,
    forceTimeline: options.forceTimeline,
  });
}

export function resetUserActionTelemetryForTests() {
  operationCounter = 0;
}
