// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import conversationViewSource from "./ConversationView.tsx?raw";
import {
  useConversationCopyAnswerFeedback,
  type UseConversationCopyAnswerFeedbackInput,
} from "./useConversationCopyAnswerFeedback";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const COPY_ANSWER_FEEDBACK_MS = 1600;

function Harness({
  overrides,
  onResult,
}: {
  overrides: UseConversationCopyAnswerFeedbackInput;
  onResult: (result: ReturnType<typeof useConversationCopyAnswerFeedback>) => void;
}) {
  const result = useConversationCopyAnswerFeedback(overrides);
  onResult(result);
  return null;
}

describe("useConversationCopyAnswerFeedback", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  it("is consumed by ConversationView instead of an inline timer", () => {
    expect(conversationViewSource).toContain("useConversationCopyAnswerFeedback({");
    expect(conversationViewSource).toContain("copyText: copyTextToClipboard");
    expect(conversationViewSource).not.toContain("copyAnswerFeedbackTimerRef");
    expect(conversationViewSource).not.toContain("function handleCopyAnswer");
  });

  afterEach(async () => {
    if (root) {
      await act(async () => root?.unmount());
    }
    container?.remove();
    root = null;
    container = null;
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  async function mount(overrides: UseConversationCopyAnswerFeedbackInput) {
    if (root) {
      await act(async () => root?.unmount());
    }
    container?.remove();
    const resultRef: { current: ReturnType<typeof useConversationCopyAnswerFeedback> | null } = { current: null };
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(<Harness overrides={overrides} onResult={(result) => { resultRef.current = result; }} />);
    });
    return resultRef;
  }

  async function flush() {
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
  }

  it("ignores empty text and leaves the copied id unset", async () => {
    const copyText = vi.fn<(text: string) => Promise<void>>().mockResolvedValue(undefined);
    const resultRef = await mount({ copyText });

    await act(async () => {
      resultRef.current?.handleCopyAnswer("msg-a", "  \n\t ");
    });
    await flush();

    expect(copyText).not.toHaveBeenCalled();
    expect(resultRef.current?.copiedAnswerMessageId).toBe("");
  });

  it("shows the copied id after a successful copy, then clears it after the dwell", async () => {
    vi.useFakeTimers();
    const copyText = vi.fn<(text: string) => Promise<void>>().mockResolvedValue(undefined);
    const resultRef = await mount({ copyText });

    await act(async () => {
      resultRef.current?.handleCopyAnswer("msg-a", "  alpha  ");
    });
    await flush();

    expect(copyText).toHaveBeenCalledTimes(1);
    expect(copyText).toHaveBeenCalledWith("alpha");
    expect(resultRef.current?.copiedAnswerMessageId).toBe("msg-a");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(COPY_ANSWER_FEEDBACK_MS - 1);
    });
    expect(resultRef.current?.copiedAnswerMessageId).toBe("msg-a");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(resultRef.current?.copiedAnswerMessageId).toBe("");
  });

  it("swallows clipboard failure and does not show the copied id", async () => {
    const copyText = vi.fn<(text: string) => Promise<void>>().mockRejectedValue(new Error("denied"));
    const resultRef = await mount({ copyText });

    await act(async () => {
      resultRef.current?.handleCopyAnswer("msg-a", "alpha");
    });
    await flush();

    expect(copyText).toHaveBeenCalledWith("alpha");
    expect(resultRef.current?.copiedAnswerMessageId).toBe("");
  });

  it("resets the dwell when the same message is copied again", async () => {
    vi.useFakeTimers();
    const copyText = vi.fn<(text: string) => Promise<void>>().mockResolvedValue(undefined);
    const resultRef = await mount({ copyText });

    await act(async () => {
      resultRef.current?.handleCopyAnswer("msg-a", "alpha");
    });
    await flush();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(COPY_ANSWER_FEEDBACK_MS - 100);
    });
    await act(async () => {
      resultRef.current?.handleCopyAnswer("msg-a", "alpha again");
    });
    await flush();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    expect(resultRef.current?.copiedAnswerMessageId).toBe("msg-a");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(COPY_ANSWER_FEEDBACK_MS - 100);
    });
    expect(resultRef.current?.copiedAnswerMessageId).toBe("");
  });

  it("keeps a newer copied id when an older feedback timer still fires", async () => {
    const timers = new Map<number, () => void>();
    let nextId = 1;
    vi.spyOn(window, "setTimeout").mockImplementation(((handler: TimerHandler) => {
      const id = nextId;
      nextId += 1;
      timers.set(id, () => {
        if (typeof handler === "function") {
          handler();
        }
      });
      return id;
    }) as typeof window.setTimeout);
    vi.spyOn(window, "clearTimeout").mockImplementation((id) => {
      timers.delete(Number(id));
    });

    const copyText = vi.fn<(text: string) => Promise<void>>().mockResolvedValue(undefined);
    const resultRef = await mount({ copyText });

    await act(async () => {
      resultRef.current?.handleCopyAnswer("msg-a", "alpha");
    });
    await flush();
    const staleTimer = [...timers.values()][0];
    expect(staleTimer).toBeTypeOf("function");

    await act(async () => {
      resultRef.current?.handleCopyAnswer("msg-b", "beta");
    });
    await flush();
    expect(resultRef.current?.copiedAnswerMessageId).toBe("msg-b");
    expect(timers.size).toBe(1);

    await act(async () => {
      staleTimer?.();
    });
    expect(resultRef.current?.copiedAnswerMessageId).toBe("msg-b");

    await act(async () => {
      [...timers.values()][0]?.();
    });
    expect(resultRef.current?.copiedAnswerMessageId).toBe("");
  });

  it("clears a pending feedback timer on unmount", async () => {
    const timers = new Map<number, () => void>();
    let nextId = 1;
    vi.spyOn(window, "setTimeout").mockImplementation(((handler: TimerHandler) => {
      const id = nextId;
      nextId += 1;
      timers.set(id, () => {
        if (typeof handler === "function") {
          handler();
        }
      });
      return id;
    }) as typeof window.setTimeout);
    const clearTimeout = vi.spyOn(window, "clearTimeout").mockImplementation((id) => {
      timers.delete(Number(id));
    });

    const copyText = vi.fn<(text: string) => Promise<void>>().mockResolvedValue(undefined);
    const resultRef = await mount({ copyText });
    await act(async () => {
      resultRef.current?.handleCopyAnswer("msg-a", "alpha");
    });
    await flush();
    expect(timers.size).toBe(1);
    clearTimeout.mockClear();

    await act(async () => root?.unmount());
    root = null;
    expect(clearTimeout).toHaveBeenCalledTimes(1);
    expect(timers.size).toBe(0);
  });
});
