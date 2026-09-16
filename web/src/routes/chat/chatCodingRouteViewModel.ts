import { isFetchJsonHttpError } from "../../api/client";
import type { TranslationKey } from "../../i18n/dictionary";

export type ResizableSide = "left" | "right";

const RESIZE_HANDLE_WIDTH = 10;
export const MIN_LEFT_PANEL_WIDTH = 260;
export const MAX_LEFT_PANEL_WIDTH = 560;
export const MIN_RIGHT_PANEL_WIDTH = 200;
export const MAX_RIGHT_PANEL_WIDTH = 520;
const TARGET_CENTER_PANE_WIDTH = 800;

export function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function getDesiredCenterWidth(layoutWidth: number) {
  const usableWidth = Math.max(0, layoutWidth - RESIZE_HANDLE_WIDTH * 2);
  return Math.min(
    TARGET_CENTER_PANE_WIDTH,
    Math.max(0, usableWidth - MIN_LEFT_PANEL_WIDTH - MIN_RIGHT_PANEL_WIDTH),
  );
}

export function normalizePanelWidths(layoutWidth: number, leftWidth: number, rightWidth: number) {
  const usableWidth = Math.max(0, layoutWidth - RESIZE_HANDLE_WIDTH * 2);
  const availableForPanels = Math.max(
    MIN_LEFT_PANEL_WIDTH + MIN_RIGHT_PANEL_WIDTH,
    usableWidth - getDesiredCenterWidth(layoutWidth),
  );

  let nextLeft = clamp(leftWidth, MIN_LEFT_PANEL_WIDTH, MAX_LEFT_PANEL_WIDTH);
  let nextRight = clamp(rightWidth, MIN_RIGHT_PANEL_WIDTH, MAX_RIGHT_PANEL_WIDTH);
  let overflow = nextLeft + nextRight - availableForPanels;

  if (overflow > 0) {
    const rightSlack = nextRight - MIN_RIGHT_PANEL_WIDTH;
    const leftSlack = nextLeft - MIN_LEFT_PANEL_WIDTH;

    if (rightSlack >= leftSlack) {
      const reduceRight = Math.min(overflow, rightSlack);
      nextRight -= reduceRight;
      overflow -= reduceRight;

      const reduceLeft = Math.min(overflow, nextLeft - MIN_LEFT_PANEL_WIDTH);
      nextLeft -= reduceLeft;
    } else {
      const reduceLeft = Math.min(overflow, leftSlack);
      nextLeft -= reduceLeft;
      overflow -= reduceLeft;

      const reduceRight = Math.min(overflow, nextRight - MIN_RIGHT_PANEL_WIDTH);
      nextRight -= reduceRight;
    }
  }

  return {
    leftPanelWidth: Math.round(nextLeft),
    rightPanelWidth: Math.round(nextRight),
  };
}

export function getResizeBounds(side: ResizableSide, layoutWidth: number, siblingWidth: number) {
  const usableWidth = Math.max(0, layoutWidth - RESIZE_HANDLE_WIDTH * 2);
  const maxWidth = usableWidth - getDesiredCenterWidth(layoutWidth) - siblingWidth;

  if (side === "left") {
    return {
      min: MIN_LEFT_PANEL_WIDTH,
      max: Math.max(MIN_LEFT_PANEL_WIDTH, Math.min(MAX_LEFT_PANEL_WIDTH, maxWidth)),
    };
  }

  return {
    min: MIN_RIGHT_PANEL_WIDTH,
    max: Math.max(MIN_RIGHT_PANEL_WIDTH, Math.min(MAX_RIGHT_PANEL_WIDTH, maxWidth)),
  };
}

export function describeChatRouteError(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) {
    return `${fallback}: ${error.message}`;
  }
  return fallback;
}

export type ChatSubmitErrorKind =
  | "turn_in_progress"
  | "auth_failed"
  | "rate_limited"
  | "upstream_unavailable"
  | "network"
  | "request_rejected";

/** Chat dictionary keys for each submit failure category. */
export const CHAT_SUBMIT_ERROR_KIND_KEYS: Record<ChatSubmitErrorKind, TranslationKey> = {
  turn_in_progress: "composerErrorTurnInProgress",
  auth_failed: "composerErrorAuthFailed",
  rate_limited: "composerErrorRateLimited",
  upstream_unavailable: "composerErrorUpstreamUnavailable",
  network: "composerErrorNetwork",
  request_rejected: "composerErrorRequestRejected",
};

/**
 * Classify a direct turn-submit failure by HTTP status / transport kind so
 * the composer shows one human "what happened / what next" line instead of
 * the raw error message. Unknown errors return "" (caller keeps its human
 * fallback; the raw error stays in telemetry/runtime logs).
 */
export function classifyChatSubmitErrorKind(error: unknown): ChatSubmitErrorKind | "" {
  if (isFetchJsonHttpError(error)) {
    const status = Number(error.status) || 0;
    if (status === 409) {
      return "turn_in_progress";
    }
    if (status === 401 || status === 403) {
      return "auth_failed";
    }
    if (status === 429) {
      return "rate_limited";
    }
    if (status >= 500) {
      return "upstream_unavailable";
    }
    if (status >= 400) {
      return "request_rejected";
    }
    return "";
  }
  // A failed fetch surfaces as TypeError("Failed to fetch") / network wording.
  if (error instanceof TypeError) {
    return "network";
  }
  return "";
}

/**
 * Human composer text for a submit failure: classified category copy when
 * the error is recognizable, otherwise the caller's localized fallback. The
 * raw error is never concatenated — it is already reported to telemetry and
 * runtime logs by the submit mutation's error path.
 */
export function describeChatSubmitError(
  error: unknown,
  t: (key: TranslationKey) => string,
  fallback: string,
) {
  const kind = classifyChatSubmitErrorKind(error);
  return kind ? t(CHAT_SUBMIT_ERROR_KIND_KEYS[kind]) : fallback;
}

function comparableErrorText(value: unknown) {
  return String(value ?? "").replace(/\s+/g, " ").trim().toLowerCase();
}

export function shouldSuppressComposerErrorForTurnError(
  composerError: string,
  latestTurnErrorMessage: string,
  turnError: { message?: unknown; errorType?: unknown } | null | undefined,
) {
  const composer = comparableErrorText(composerError);
  const latestMessage = comparableErrorText(latestTurnErrorMessage);
  const turnErrorMessage = comparableErrorText(turnError?.message);
  const turnErrorType = comparableErrorText(turnError?.errorType);
  if (!composer || !latestMessage) {
    return false;
  }
  return (
    (turnErrorMessage && (composer.includes(turnErrorMessage) || turnErrorMessage.includes(composer)))
    || composer.includes(latestMessage)
    || latestMessage.includes(composer)
    || (turnErrorType && composer.includes(turnErrorType))
  );
}

export function isRunningPhase(value: string | null | undefined) {
  const phase = String(value ?? "").trim().toLowerCase();
  return ["queued", "running", "thinking", "tooling", "answering", "planning", "reading", "editing", "verifying"].includes(phase);
}

export function isStoppingPhase(value: string | null | undefined) {
  const phase = String(value ?? "").trim().toLowerCase();
  return phase === "stopping";
}

export function isBusyPhase(value: string | null | undefined) {
  const phase = String(value ?? "").trim().toLowerCase();
  return isRunningPhase(phase) || phase === "stopping";
}

export function formatTokenSpeedValue(tokensPerSecond: number | null | undefined) {
  if (typeof tokensPerSecond !== "number" || !Number.isFinite(tokensPerSecond) || tokensPerSecond <= 0) {
    return "";
  }
  return tokensPerSecond < 1 ? "<1 t/s" : `${Math.round(tokensPerSecond)} t/s`;
}

export function formatChatRuntimeMismatchLine(options: {
  otherRunningSessionIds: Iterable<string>;
  resolveSessionLabel: (sessionId: string) => string;
  lang: "zh" | "en";
}) {
  const others = Array.from(options.otherRunningSessionIds, (sessionId) => String(sessionId || "").trim())
    .filter(Boolean);
  if (others.length === 0) {
    return "";
  }
  if (others.length === 1) {
    const label = String(options.resolveSessionLabel(others[0]) || "").trim() || others[0];
    return options.lang === "zh"
      ? `运行器正在处理：${label}`
      : `Runtime is processing: ${label}`;
  }
  return options.lang === "zh"
    ? `另有 ${others.length} 个会话在运行`
    : `${others.length} other sessions are running`;
}

export function runtimeMatchesSelectedChatSession(options: {
  selectedSessionId: string | null | undefined;
  activeRuntimeSessionId: string | null | undefined;
  activeWorkSessionIds: Iterable<string>;
}) {
  const selectedSessionId = String(options.selectedSessionId || "").trim();
  if (!selectedSessionId) {
    return false;
  }
  const activeRuntimeSessionId = String(options.activeRuntimeSessionId || "").trim();
  if (activeRuntimeSessionId === selectedSessionId) {
    return true;
  }
  return Array.from(options.activeWorkSessionIds).some(
    (sessionId) => String(sessionId || "").trim() === selectedSessionId,
  );
}

export function chatStreamPerformanceNowMs() {
  return typeof performance === "undefined" ? Date.now() : performance.now();
}
