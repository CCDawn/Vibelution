// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  composerInputHasCompetingFocus,
  scheduleComposerFocusAttempts,
  tryFocusComposerInput,
} from "./conversationComposerFocusSchedule";

describe("conversationComposerFocusSchedule", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("detects competing focus from a connected non-textarea control", () => {
    const textarea = document.createElement("textarea");
    const button = document.createElement("button");
    document.body.append(textarea, button);
    button.focus();

    expect(composerInputHasCompetingFocus(textarea)).toBe(true);

    textarea.remove();
    button.remove();
  });

  it("retries focus after competing control releases focus", () => {
    vi.useFakeTimers();
    const textarea = document.createElement("textarea");
    const button = document.createElement("button");
    document.body.append(textarea, button);
    button.focus();

    const onSuccess = vi.fn();
    const cancel = scheduleComposerFocusAttempts({
      getInput: () => textarea,
      isDisabled: () => false,
      onSuccess,
      retryDelaysMs: [0, 10, 10, 10],
      maxAttempts: 4,
    });

    vi.advanceTimersByTime(0);
    expect(onSuccess).not.toHaveBeenCalled();

    button.remove();
    vi.runAllTimers();
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(document.activeElement).toBe(textarea);

    cancel();
    textarea.remove();
    vi.useRealTimers();
  });

  it("defers focus while disabled and restores on the disabled edge", () => {
    vi.useFakeTimers();
    const textarea = document.createElement("textarea");
    document.body.append(textarea);

    let disabled = true;
    const onSuccess = vi.fn();
    scheduleComposerFocusAttempts({
      getInput: () => textarea,
      isDisabled: () => disabled,
      onSuccess,
      retryDelaysMs: [0, 10, 20],
      maxAttempts: 3,
    });

    vi.runAllTimers();
    expect(onSuccess).not.toHaveBeenCalled();

    disabled = false;
    scheduleComposerFocusAttempts({
      getInput: () => textarea,
      isDisabled: () => disabled,
      onSuccess,
      retryDelaysMs: [0],
      maxAttempts: 1,
    });
    vi.runAllTimers();
    expect(onSuccess).toHaveBeenCalledTimes(1);

    textarea.remove();
    vi.useRealTimers();
  });

  it("does not focus a disabled textarea", () => {
    const textarea = document.createElement("textarea");
    textarea.disabled = true;
    document.body.append(textarea);

    expect(tryFocusComposerInput(textarea)).toBe(false);

    textarea.remove();
  });
});
