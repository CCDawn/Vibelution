// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { queryKeys } from "../../api/queryKeys";
import { dictionary } from "../../i18n/dictionary";
import { ConversationView } from "./ConversationView";

vi.mock("./LazyConversationMarkdownRenderer", async () => {
  const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
  return { LazyConversationMarkdownRenderer: ConversationMarkdownRenderer };
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function reasoningMessage(status: "running" | "completed"): ConversationMessage {
  return {
    id: "assistant-thought-duration",
    role: "assistant",
    timestamp: "2026-09-11T05:00:00Z",
    turnId: "turn-thought-duration",
    status,
    turnItems: [{
      id: "thought-duration-r1",
      itemId: "thought-duration",
      version: 3,
      sessionId: "session-1",
      turnId: "turn-thought-duration",
      type: "reasoning",
      status,
      revision: 1,
      sequence: 1,
      terminal: status === "completed",
      text: "先确认这个函数的两条来源路径，再看函数体。",
    }],
  } as ConversationMessage;
}

/** Mid-turn settle: the reasoning item finished while the turn keeps running. */
function itemSettledLiveMessage(): ConversationMessage {
  const message = reasoningMessage("running") as ConversationMessage & {
    turnItems: Array<Record<string, unknown>>;
  };
  return {
    ...message,
    turnItems: message.turnItems.map((item) => ({
      ...item,
      status: "completed",
      terminal: true,
    })),
  } as ConversationMessage;
}

describe("thought duration client-clock label", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;
  let setMessages: ((messages: ConversationMessage[]) => void) | null = null;
  let originalGetBoundingClientRect: typeof HTMLElement.prototype.getBoundingClientRect | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root?.unmount();
      });
    }
    container?.remove();
    root = null;
    container = null;
    setMessages = null;
    if (originalGetBoundingClientRect) {
      HTMLElement.prototype.getBoundingClientRect = originalGetBoundingClientRect;
      originalGetBoundingClientRect = null;
    }
    delete (HTMLElement.prototype as { offsetWidth?: unknown }).offsetWidth;
    delete (HTMLElement.prototype as { offsetHeight?: unknown }).offsetHeight;
    vi.useRealTimers();
  });

  /**
   * happy-dom does no layout, so the virtualizer's rect probe (which reads
   * offsetWidth/offsetHeight, per @tanstack/virtual-core getRect) would report
   * a zero viewport and the virtualized history segment would drop every
   * settled row. Stub the offsets to a fixed viewport; the live tail renders
   * statically either way.
   */
  function stubViewportRect() {
    originalGetBoundingClientRect = HTMLElement.prototype.getBoundingClientRect;
    HTMLElement.prototype.getBoundingClientRect = function () {
      return {
        width: 1280,
        height: 900,
        top: 0,
        left: 0,
        bottom: 900,
        right: 1280,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      } as DOMRect;
    };
    Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
      configurable: true,
      get: () => 1280,
    });
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
      configurable: true,
      get: () => 900,
    });
  }

  async function mountThought(initial: ConversationMessage[]) {
    stubViewportRect();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    queryClient.setQueryData(queryKeys.configPublic(), { language: "zh" });
    queryClient.setQueryData(["i18n", "dictionary-domains", "core,chat"], dictionary);

    function Harness() {
      const [messages, setMessagesState] = useState(initial);
      setMessages = setMessagesState;
      return (
        <QueryClientProvider client={queryClient}>
          <ConversationView
            sessionId="session-thought-duration"
            title="Session"
            phase="ready"
            messages={messages}
            showHeader={false}
            showSessionOverview={false}
            showComposer={false}
            processDisplayMode="trace"
            assistantDisplayName="洛天依"
            composerValue=""
            composerPlaceholder=""
            composerDisabled={false}
            composerPending={false}
            defaultFileContext="workspace"
            onComposerChange={() => undefined}
            onSubmit={() => undefined}
            onStop={() => undefined}
            onClear={() => undefined}
            onJumpToLatest={() => undefined}
            onCreateNewSession={() => undefined}
          />
        </QueryClientProvider>
      );
    }

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(<Harness />);
      await vi.advanceTimersByTimeAsync(0);
    });
    return container.querySelector<HTMLButtonElement>(
      'section[data-thought-section] button[aria-expanded="false"]',
    );
  }

  it("ticks per second only while expanded and live, then freezes when the unit settles", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    const header = await mountThought([reasoningMessage("running")]);
    expect(header).not.toBeNull();

    // Collapsed live thought: the clock runs from the first live render, but
    // no ticking label mounts until the unit is expanded.
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    expect(container?.querySelector("[data-thought-duration]")).toBeNull();

    // Expanding opens the per-second tick; the reading covers the whole live
    // window, not just the expanded one.
    await act(async () => {
      header?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await act(async () => {
      vi.advanceTimersByTime(3200);
    });
    const liveLabel = container?.querySelector('[data-thought-duration="live"]');
    expect(liveLabel?.textContent).toContain("8s");

    // Unit settles mid-turn: the label freezes instead of counting further.
    await act(async () => {
      setMessages?.([itemSettledLiveMessage()]);
    });
    const settledLabel = container?.querySelector('[data-thought-duration="settled"]');
    expect(settledLabel?.textContent).toContain("持续了 8 秒");
    expect(container?.textContent).toContain("已思考");
  });

  it("shows the moments label when the live window was shorter than a second", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    const header = await mountThought([reasoningMessage("running")]);
    await act(async () => {
      header?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await act(async () => {
      vi.advanceTimersByTime(400);
    });
    await act(async () => {
      setMessages?.([itemSettledLiveMessage()]);
    });
    expect(container?.querySelector('[data-thought-duration="settled"]')?.textContent)
      .toContain("持续了几秒");
  });

  it("renders no duration for units that arrive already settled", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    await mountThought([reasoningMessage("completed")]);
    await act(async () => {
      vi.advanceTimersByTime(10000);
    });
    // History units collapse into the process disclosure in the browser;
    // open it to reveal the settled thought cell.
    const disclosure = container?.querySelector<HTMLButtonElement>(
      "details[data-codex-process-disclosure] summary",
    );
    await act(async () => {
      disclosure?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(container?.textContent).toContain("已思考");
    // History loads have no honest client-clock duration: nothing renders.
    expect(container?.querySelector("[data-thought-duration]")).toBeNull();
    expect(container?.textContent).not.toContain("持续了");
  });
});
