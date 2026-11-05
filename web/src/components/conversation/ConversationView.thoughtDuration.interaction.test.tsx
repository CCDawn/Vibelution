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

/** Settled reasoning item carrying canonical stamps: the only honest settled duration. */
function stampedSettledMessage(createdAt: string, updatedAt: string): ConversationMessage {
  const message = reasoningMessage("completed") as ConversationMessage & {
    turnItems: Array<Record<string, unknown>>;
  };
  return {
    ...message,
    turnItems: message.turnItems.map((item) => ({ ...item, createdAt, updatedAt })),
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
    queryClient.setQueryData(queryKeys.sessionMessageCuration("session-thought-duration"), { items: [] });

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
    return thoughtToggle();
  }

  function thoughtToggle() {
    return [...(container?.querySelectorAll<HTMLButtonElement>("button") ?? [])]
      .find(button => button.textContent === "显示思考" || button.textContent === "收起思考");
  }

  async function expandThoughts() {
    const toggle = thoughtToggle();
    expect(toggle).toBeTruthy();
    if (toggle?.getAttribute("aria-expanded") === "false") {
      await act(async () => toggle.click());
      await act(async () => new Promise<void>(resolve => window.requestAnimationFrame(() => resolve())));
    }
    expect(thoughtToggle()?.getAttribute("aria-expanded")).toBe("true");
    for (const thought of container?.querySelectorAll('[data-thought-section]') ?? []) {
      expect(thought.closest('[hidden], [inert], [aria-hidden="true"]')).toBeNull();
    }
  }

  function expectThoughtsHidden() {
    const thoughts = container?.querySelectorAll('[data-thought-section]');
    expect(thoughts?.length).toBeGreaterThan(0);
    for (const thought of thoughts ?? []) {
      expect(thought.closest('[hidden], [inert], [aria-hidden="true"]')).toBeTruthy();
    }
  }

  async function showThoughts() {
    await expandThoughts();
    const thoughts = container?.querySelectorAll('[data-thought-section]');
    expect(thoughts).toHaveLength(1);
    expect(thoughts?.[0].querySelector('[data-thought-scroll-body="true"]')?.textContent)
      .toBe("先确认这个函数的两条来源路径，再看函数体。");
  }

  it("ticks per second only while expanded and live, then freezes when the unit settles", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    const header = await mountThought([reasoningMessage("running")]);
    expect(header).toBeTruthy();
    expect(header?.getAttribute("aria-expanded")).toBe("false");
    expectThoughtsHidden();

    // Collapsed live thought: the clock runs from the first live render, but
    // no ticking label mounts until the unit is expanded.
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    expect(container?.querySelector("[data-thought-duration]")).toBeNull();

    // Expanding opens the per-second tick; the reading covers the whole live
    // window, not just the expanded one.
    await showThoughts();
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
    expect(settledLabel?.textContent).toContain("8s");
    expect(container?.textContent).toContain("已思考");
    await act(async () => vi.advanceTimersByTime(10000));
    expect(container?.querySelector('[data-thought-duration="settled"]')?.textContent).toContain("8s");
  });

  it("shows the moments label when the live window was shorter than a second", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    await mountThought([reasoningMessage("running")]);
    await showThoughts();
    await act(async () => {
      vi.advanceTimersByTime(400);
    });
    await act(async () => {
      setMessages?.([itemSettledLiveMessage()]);
    });
    expect(container?.querySelector('[data-thought-duration="settled"]')?.textContent)
      .toContain("几秒");
  });

  it("renders no duration for units that arrive already settled", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    await mountThought([reasoningMessage("completed")]);
    await act(async () => {
      vi.advanceTimersByTime(10000);
    });
    // The flow hides thoughts until the user asks for them.
    expectThoughtsHidden();
    await showThoughts();
    expect(container?.textContent).toContain("已思考");
    // History loads without canonical stamps have no honest duration: nothing
    // renders — not even a whole-turn number from usageStats.
    expect(container?.querySelector("[data-thought-duration]")).toBeNull();
  });

  it("renders the server-derived duration for settled units carrying canonical stamps", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    await mountThought([stampedSettledMessage(
      "2026-09-11T05:00:00Z",
      "2026-09-11T05:00:12Z",
    )]);
    await act(async () => {
      vi.advanceTimersByTime(10000);
    });
    await showThoughts();
    const settledLabel = container?.querySelector('[data-thought-duration="settled"]');
    expect(settledLabel?.textContent).toContain("12s");
  });

  it("prefers canonical stamps over the client clock once the unit settles", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    await mountThought([reasoningMessage("running")]);
    await showThoughts();
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    // The client clock only saw 5s; the server stamps bracket the true 30s.
    await act(async () => {
      setMessages?.([stampedSettledMessage(
        "2026-09-11T05:00:00Z",
        "2026-09-11T05:00:30Z",
      )]);
    });
    // The user's choice survives the same message moving into history.
    await showThoughts();
    const settledLabel = container?.querySelector('[data-thought-duration="settled"]');
    expect(settledLabel?.textContent).toContain("30s");
  });

  it("ignores clock-skewed stamps instead of showing a negative duration", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    await mountThought([stampedSettledMessage(
      "2026-09-11T05:00:30Z",
      "2026-09-11T05:00:12Z",
    )]);
    await act(async () => {
      vi.advanceTimersByTime(10000);
    });
    await showThoughts();
    expect(container?.querySelector("[data-thought-duration]")).toBeNull();
  });

  it("reveals complete thoughts in order while narration and tools stay visible through toggle and settle", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    const base = reasoningMessage("running");
    const thought = base.turnItems![0];
    const completedText = "已经完成的第一段完整思考。";
    const narrationText = "先读取配置。";
    const answerText = "配置已经核对完成。";
    const mixed: ConversationMessage = { ...base, turnItems: [
      { ...thought, id: "duration-completed-r1", itemId: "duration-completed", sequence: 1,
        status: "completed", terminal: true, text: completedText },
      { ...thought, id: "duration-narration-r1", itemId: "duration-narration", sequence: 2,
        type: "agent_message", phase: "commentary", status: "completed", terminal: true, text: narrationText },
      { ...thought, id: "duration-tool-r1", itemId: "duration-tool", sequence: 3,
        type: "tool_call", callId: "call-duration-tool", toolName: "read_file_tool",
        input: JSON.stringify({ file_path: "configuration.toml" }), output: "已读取配置。",
        status: "completed", terminal: true, text: undefined },
      { ...thought, sequence: 4 },
    ] };
    await mountThought([mixed]);
    const narration = () => container?.querySelector('[data-codex-progress-cell="true"]');
    const tool = () => container?.querySelector('[data-conversation-part-key="duration-tool"]');
    const expectVisibleNarrationAndTool = () => {
      expect(narration()?.textContent).toBe(narrationText);
      expect(narration()?.closest('[hidden], [inert], [aria-hidden="true"]')).toBeNull();
      expect(tool()).toBeTruthy();
      expect(tool()?.closest('[hidden], [inert], [aria-hidden="true"]')).toBeNull();
      expect(tool()?.textContent).toContain("已读取配置。");
    };
    expectThoughtsHidden();
    expectVisibleNarrationAndTool();
    await expandThoughts();
    const thoughts = [...(container?.querySelectorAll('[data-thought-section]') ?? [])];
    expect(thoughts.map(section => section.getAttribute("data-codex-transcript-cell-status"))).toEqual(["completed", "running"]);
    expect(thoughts[0].textContent).toContain("已思考");
    expect(thoughts[0].textContent).not.toContain("思考中");
    expect(thoughts[1].textContent).toContain("思考中");
    expect(thoughts.map(section => section.querySelector('[data-thought-scroll-body="true"]')?.textContent))
      .toEqual([completedText, "先确认这个函数的两条来源路径，再看函数体。"]);
    expect(thoughts[0].compareDocumentPosition(narration()!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(narration()!.compareDocumentPosition(tool()!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(tool()!.compareDocumentPosition(thoughts[1]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await act(async () => thoughtToggle()!.click());
    await act(async () => new Promise<void>(resolve => window.requestAnimationFrame(() => resolve())));
    expectThoughtsHidden();
    expectVisibleNarrationAndTool();

    await act(async () => setMessages?.([{ ...mixed, status: "completed", turnItems: [
      ...mixed.turnItems!.map(item => ({ ...item, status: "completed" as const, terminal: true })),
      { ...thought, id: "duration-answer-r1", itemId: "duration-answer", sequence: 5,
        type: "agent_message", phase: "final_answer", status: "completed", terminal: true, text: answerText },
    ] }]));
    expectThoughtsHidden();
    expectVisibleNarrationAndTool();
    expect(container?.querySelector('[data-codex-final-response="true"]')?.textContent).toBe(answerText);
    await expandThoughts();
    expect(container?.querySelectorAll('[data-thought-section]')).toHaveLength(2);
    expect(container?.textContent?.split(completedText).length).toBe(2);
    expect(container?.textContent?.split(narrationText).length).toBe(2);
    expect(container?.textContent?.split(answerText).length).toBe(2);
    expect(container?.querySelector('[data-thought-section][data-codex-transcript-cell-status="running"]')).toBeNull();
  });
});
