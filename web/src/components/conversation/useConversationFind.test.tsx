// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Virtualizer } from "@tanstack/react-virtual";

import type { ConversationMessage } from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionaryTypes";
import { useConversationFind, type UseConversationFindInput } from "./useConversationFind";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function userMessage(id: string, content: string): ConversationMessage {
  return { id, role: "user", timestamp: "2026-09-29T10:00:00Z", content };
}

function assistantMessage(id: string, reasoning: string, answer: string): ConversationMessage {
  return {
    id,
    role: "assistant",
    timestamp: "2026-09-29T10:00:05Z",
    turnId: `${id}-turn`,
    status: "completed",
    turnItems: [
      {
        id: `${id}-r`, itemId: `${id}-r`, version: 3 as const, sessionId: "session-1",
        turnId: `${id}-turn`, type: "reasoning" as const, status: "completed" as const,
        revision: 1, sequence: 0, text: reasoning,
      },
      {
        id: `${id}-m`, itemId: `${id}-m`, version: 3 as const, sessionId: "session-1",
        turnId: `${id}-turn`, type: "agent_message" as const, phase: "final_answer" as const,
        status: "completed" as const, revision: 1, sequence: 1, text: answer,
      },
    ],
  };
}

const MESSAGES = [
  userMessage("u1", "帮我核对部署流程"),
  assistantMessage("a1", "部署流程包含构建与发布两个阶段", "部署流程如下：先构建再发布。"),
];

function Harness({
  overrides = {},
  onResult,
}: {
  overrides?: Partial<UseConversationFindInput>;
  onResult: (result: ReturnType<typeof useConversationFind>) => void;
}) {
  const timelineRef = React.useRef<HTMLDivElement | null>(null);
  const result = useConversationFind({
    sessionId: "session-1",
    t: (key: TranslationKey) => key,
    historyMessages: MESSAGES,
    liveTailStartIndex: MESSAGES.length,
    timelineRef,
    timelineVirtualizer: { scrollToIndex: vi.fn() } as unknown as Virtualizer<HTMLDivElement, Element>,
    previewImage: null,
    forkDialogMessage: null,
    scrollTimelineToBottom: vi.fn(),
    ...overrides,
  });
  onResult(result);
  return (
    <div ref={result.surfaceRef}>
      <div ref={timelineRef}>
        {MESSAGES.map((message) => (
          <div key={message.id} data-conversation-message-id={message.id}>{message.id}</div>
        ))}
      </div>
    </div>
  );
}

describe("useConversationFind", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => root?.unmount());
    }
    container?.remove();
    root = null;
    container = null;
    vi.useRealTimers();
  });

  async function mount(overrides: Partial<UseConversationFindInput> = {}) {
    const resultRef: { current: ReturnType<typeof useConversationFind> | null } = { current: null };
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(<Harness overrides={overrides} onResult={(result) => { resultRef.current = result; }} />);
    });
    return resultRef;
  }

  function keydown(key: string, target: EventTarget, options: { ctrl?: boolean; composing?: boolean } = {}) {
    const event = new window.KeyboardEvent("keydown", {
      key,
      bubbles: true,
      cancelable: true,
      ctrlKey: Boolean(options.ctrl),
      metaKey: false,
    });
    if (options.composing) {
      Object.defineProperty(event, "isComposing", { value: true });
    }
    target.dispatchEvent(event);
    return event;
  }

  it("opens with Ctrl+F from the body, settles the debounced query, and steps matches", async () => {
    vi.useFakeTimers();
    const resultRef = await mount();
    expect(resultRef.current?.open).toBe(false);

    await act(async () => { keydown("f", document.body, { ctrl: true }); });
    expect(resultRef.current?.open).toBe(true);

    await act(async () => { resultRef.current?.setQuery("部署流程"); });
    await act(async () => { vi.advanceTimersByTime(200); });
    expect(resultRef.current?.matchCount).toBe(3);
    expect(resultRef.current?.activeIndex).toBe(0);

    await act(async () => { resultRef.current?.handleNext(); });
    expect(resultRef.current?.activeIndex).toBe(1);
    await act(async () => { resultRef.current?.handlePrevious(); });
    expect(resultRef.current?.activeIndex).toBe(0);
  });

  it("marks matched rows in the mounted timeline window and jumps through the virtualizer", async () => {
    vi.useFakeTimers();
    const resultRef = await mount();
    await act(async () => { keydown("f", document.body, { ctrl: true }); });
    await act(async () => { resultRef.current?.setQuery("部署流程"); });
    await act(async () => { vi.advanceTimersByTime(200); });
    await act(async () => { await vi.advanceTimersByTimeAsync(50); });

    const timeline = container?.querySelector("[data-conversation-message-id='u1']")?.parentElement;
    expect(timeline?.querySelectorAll("[data-conversation-find-match='true']").length).toBe(2);
    expect(timeline?.querySelector("[data-conversation-find-active='true']")?.getAttribute("data-conversation-message-id")).toBe("u1");
  });

  it("closes on Escape from the transcript but not while a modal overlay owns Escape", async () => {
    vi.useFakeTimers();
    const resultRef = await mount();
    await act(async () => { keydown("f", document.body, { ctrl: true }); });
    expect(resultRef.current?.open).toBe(true);

    await act(async () => { keydown("Escape", document.body); });
    expect(resultRef.current?.open).toBe(false);

    const withOverlay = await mount({
      previewImage: { url: "https://example.test/a.png" } as UseConversationFindInput["previewImage"],
    });
    await act(async () => { keydown("f", document.body, { ctrl: true }); });
    expect(withOverlay.current?.open).toBe(true);
    await act(async () => { keydown("Escape", document.body); });
    expect(withOverlay.current?.open).toBe(true);
  });

  it("ignores Ctrl+F from outside the conversation surface", async () => {
    vi.useFakeTimers();
    const resultRef = await mount();
    const outside = document.createElement("button");
    document.body.appendChild(outside);
    await act(async () => { keydown("f", outside, { ctrl: true }); });
    expect(resultRef.current?.open).toBe(false);
    outside.remove();
  });
});
