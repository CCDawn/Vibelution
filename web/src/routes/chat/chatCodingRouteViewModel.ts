export type ResizableSide = "left" | "right";

const RESIZE_HANDLE_WIDTH = 10;
const MIN_LEFT_PANEL_WIDTH = 260;
const MAX_LEFT_PANEL_WIDTH = 560;
const MIN_RIGHT_PANEL_WIDTH = 200;
const MAX_RIGHT_PANEL_WIDTH = 520;
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

export function chatStreamPerformanceNowMs() {
  return typeof performance === "undefined" ? Date.now() : performance.now();
}
