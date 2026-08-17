const DEFAULT_FOCUS_RETRY_DELAYS_MS = [0, 16, 32, 64, 100];

export function composerInputHasCompetingFocus(input: HTMLTextAreaElement | null): boolean {
  if (!input) {
    return false;
  }
  const activeElement = document.activeElement;
  return Boolean(
    activeElement
    && activeElement !== document.body
    && activeElement !== document.documentElement
    && activeElement !== input
    && activeElement.isConnected,
  );
}

export function tryFocusComposerInput(input: HTMLTextAreaElement | null): boolean {
  if (!input || input.disabled) {
    return false;
  }
  input.focus();
  const cursorPosition = input.value.length;
  input.setSelectionRange(cursorPosition, cursorPosition);
  return document.activeElement === input;
}

export type ScheduleComposerFocusAttemptOptions = {
  getInput: () => HTMLTextAreaElement | null;
  isDisabled: () => boolean;
  shouldAbort?: () => boolean;
  onSuccess?: () => void;
  onGiveUp?: () => void;
  maxAttempts?: number;
  retryDelaysMs?: readonly number[];
  /** While disabled, keep polling without consuming retry budget. */
  maxDisabledPolls?: number;
};

/**
 * Retry composer focus across animation frames / short delays so delete handoff
 * and dialog dismiss can finish before the caret lands in the textarea.
 */
export function scheduleComposerFocusAttempts(
  options: ScheduleComposerFocusAttemptOptions,
): () => void {
  const retryDelaysMs = options.retryDelaysMs ?? DEFAULT_FOCUS_RETRY_DELAYS_MS;
  const maxAttempts = Math.min(options.maxAttempts ?? retryDelaysMs.length, retryDelaysMs.length);
  const maxDisabledPolls = Math.max(1, options.maxDisabledPolls ?? 12);
  let cancelled = false;
  let disabledPolls = 0;
  let timeoutId: number | undefined;
  let frameId: number | undefined;

  const clearTimers = () => {
    if (timeoutId !== undefined) {
      window.clearTimeout(timeoutId);
      timeoutId = undefined;
    }
    if (frameId !== undefined) {
      window.cancelAnimationFrame(frameId);
      frameId = undefined;
    }
  };

  const finish = (focused: boolean) => {
    clearTimers();
    if (focused) {
      options.onSuccess?.();
    } else {
      options.onGiveUp?.();
    }
  };

  const attempt = (attemptIndex: number) => {
    if (cancelled || options.shouldAbort?.()) {
      clearTimers();
      return;
    }

    if (options.isDisabled()) {
      disabledPolls += 1;
      if (disabledPolls < maxDisabledPolls) {
        queueAttempt(attemptIndex, 16);
      } else if (attemptIndex + 1 < maxAttempts) {
        queueAttempt(attemptIndex + 1, retryDelaysMs[attemptIndex + 1] ?? 16);
      } else {
        finish(false);
      }
      return;
    }
    disabledPolls = 0;

    const input = options.getInput();
    if (!input) {
      if (attemptIndex + 1 < maxAttempts) {
        queueAttempt(attemptIndex + 1, retryDelaysMs[attemptIndex + 1] ?? 16);
      } else {
        finish(false);
      }
      return;
    }

    if (composerInputHasCompetingFocus(input)) {
      if (attemptIndex + 1 < maxAttempts) {
        queueAttempt(attemptIndex + 1, retryDelaysMs[attemptIndex + 1] ?? 16);
      } else {
        finish(false);
      }
      return;
    }

    if (tryFocusComposerInput(input)) {
      finish(true);
      return;
    }

    if (attemptIndex + 1 < maxAttempts) {
      queueAttempt(attemptIndex + 1, retryDelaysMs[attemptIndex + 1] ?? 16);
    } else {
      finish(false);
    }
  };

  const queueAttempt = (attemptIndex: number, delayMs: number) => {
    clearTimers();
    if (delayMs <= 0) {
      frameId = window.requestAnimationFrame(() => attempt(attemptIndex));
      return;
    }
    timeoutId = window.setTimeout(() => attempt(attemptIndex), delayMs);
  };

  queueAttempt(0, retryDelaysMs[0] ?? 0);

  return () => {
    cancelled = true;
    clearTimers();
  };
}
