/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { dictionary } from "../../i18n/dictionary";
import { queryKeys } from "../../api/queryKeys";
import type { ConversationMessage } from "../../api/types";
import type { ConversationSelectionLike, ConversationSelectionRangeLike, ConversationSelectionRect } from "./conversationTextSelection";
import { ConversationView } from "./ConversationView";

vi.mock("./LazyConversationMarkdownRenderer", async () => {
  const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
  return { LazyConversationMarkdownRenderer: ConversationMarkdownRenderer };
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const ANSWER_TEXT = "这是可以被划选的原文";

function assistantMessage(): ConversationMessage {
  return {
    id: "message-assistant-1",
    role: "assistant",
    content: ANSWER_TEXT,
    timestamp: "2026-05-22T00:01:00Z",
    turnId: "turn-1",
    status: "completed",
    nodeId: "node-assistant-1",
    turnItems: [
      {
        id: "message-assistant-1-item-answer",
        itemId: "message-assistant-1-item-answer",
        sessionId: "session-selection-quote",
        turnId: "turn-1",
        version: 3,
        revision: 1,
        sequence: 1,
        type: "agent_message",
        phase: "final_answer",
        text: ANSWER_TEXT,
        status: "completed",
        terminal: true,
      },
    ],
  } as unknown as ConversationMessage;
}

/**
 * In-flight turn: renders through the live-tail (static) segment, so the row
 * wrapper exists in happy-dom where the virtualized history window does not.
 */
function streamingAssistantMessage(): ConversationMessage {
  return {
    id: "message-assistant-1",
    role: "assistant",
    content: ANSWER_TEXT,
    timestamp: "2026-05-22T00:01:00Z",
    turnId: "turn-1",
    status: "running",
    nodeId: "node-assistant-1",
    turnItems: [
      {
        id: "message-assistant-1-item-answer",
        itemId: "message-assistant-1-item-answer",
        sessionId: "session-selection-quote",
        turnId: "turn-1",
        version: 3,
        revision: 1,
        sequence: 1,
        type: "agent_message",
        phase: "final_answer",
        text: ANSWER_TEXT,
        status: "running",
        terminal: false,
      },
    ],
  } as unknown as ConversationMessage;
}

function fakeRect(partial: Partial<ConversationSelectionRect>): ConversationSelectionRect {
  return { top: 0, left: 0, width: 0, height: 0, bottom: 0, right: 0, ...partial };
}

function fakeSelection(node: Node, rect: ConversationSelectionRect, text = ANSWER_TEXT): Selection {
  const range: ConversationSelectionRangeLike = {
    startContainer: node,
    endContainer: node,
    getBoundingClientRect: () => rect,
  };
  const selection: ConversationSelectionLike = {
    rangeCount: 1,
    isCollapsed: false,
    toString: () => text,
    getRangeAt: (index: number) => (index === 0 ? range : range),
  };
  return selection as unknown as Selection;
}

async function flushSelectionFrames() {
  // rAF-coalesced evaluation + React state settle.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 40));
  });
}

describe("ConversationView text selection quote menu", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(async () => {
    vi.restoreAllMocks();
    if (root) {
      await act(async () => {
        root?.unmount();
      });
    }
    container?.remove();
    root = null;
    container = null;
  });

  async function renderSelectionConversation(
    handlers: { onAddComposerReference?: (reference: unknown) => void } = {},
    message: ConversationMessage = assistantMessage(),
  ) {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    queryClient.setQueryData(queryKeys.configPublic(), { language: "zh" });
    queryClient.setQueryData(["i18n", "dictionary-domains", "core,chat"], dictionary);

    function Harness() {
      const [value, setValue] = useState("");
      return (
        <QueryClientProvider client={queryClient}>
          <div data-testid="outside-timeline">外部不可引用文本</div>
          <ConversationView
            sessionId="session-selection-quote"
            title="Session"
            phase="ready"
            messages={[message]}
            showHeader={false}
            showSessionOverview={false}
            showComposer
            defaultFileContext="workspace"
            composerValue={value}
            composerPlaceholder=""
            composerDisabled={false}
            composerPending={false}
            onComposerChange={setValue}
            onSubmit={() => undefined}
            onEditUserMessage={() => undefined}
            onAddComposerReference={handlers.onAddComposerReference}
          />
        </QueryClientProvider>
      );
    }

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(<Harness />);
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    const timeline = container.querySelector(".timeline");
    if (!timeline) {
      throw new Error("timeline not mounted");
    }
    const paragraph = timeline.querySelector("p");
    const targetNode = paragraph?.firstChild ?? timeline;
    return { timeline, targetNode };
  }

  function selectionMenu(): HTMLElement | null {
    return container?.querySelector('[data-conversation-selection-menu="1"]') ?? null;
  }

  it("opens over a timeline selection, quotes into the composer, and focuses the caret", async () => {
    const { timeline, targetNode } = await renderSelectionConversation();
    vi.spyOn(window, "getSelection").mockReturnValue(
      fakeSelection(targetNode, fakeRect({ top: 40, left: 10, width: 80, height: 16, bottom: 56, right: 90 })),
    );

    await act(async () => {
      document.dispatchEvent(new Event("mouseup"));
    });
    await flushSelectionFrames();

    const menu = selectionMenu();
    expect(menu).not.toBeNull();
    expect(menu?.textContent).toContain("引用到输入框");
    expect(menu?.textContent).toContain("复制");

    const quoteButton = menu?.querySelector("button");
    if (!quoteButton) {
      throw new Error("quote button not mounted");
    }
    await act(async () => {
      quoteButton.click();
      await new Promise((resolve) => setTimeout(resolve, 40));
    });

    const textarea = container?.querySelector("textarea");
    expect(textarea?.value).toBe(`> ${ANSWER_TEXT}`);
    expect(document.activeElement).toBe(textarea);
    expect(textarea?.selectionStart).toBe(textarea?.value.length);

    // Selecting again re-opens the menu after the quote consumed the first one.
    vi.spyOn(window, "getSelection").mockReturnValue(
      fakeSelection(targetNode, fakeRect({ top: 40, left: 10, width: 80, height: 16, bottom: 56, right: 90 })),
    );
    await act(async () => {
      document.dispatchEvent(new Event("mouseup"));
    });
    await flushSelectionFrames();
    expect(selectionMenu()).not.toBeNull();
    void timeline;
  });

  it("does not open for selections outside the timeline container", async () => {
    await renderSelectionConversation();
    const outside = container?.querySelector("[data-testid=outside-timeline]");
    const outsideNode = outside?.firstChild ?? document.body;
    vi.spyOn(window, "getSelection").mockReturnValue(
      fakeSelection(outsideNode, fakeRect({ top: 5, left: 5, width: 40, height: 10, bottom: 15, right: 45 })),
    );

    await act(async () => {
      document.dispatchEvent(new Event("mouseup"));
    });
    await flushSelectionFrames();
    expect(selectionMenu()).toBeNull();
  });

  it("attaches a structured message reference from the selection menu", async () => {
    const onAddComposerReference = vi.fn();
    await renderSelectionConversation({ onAddComposerReference }, streamingAssistantMessage());
    // The in-flight row renders through the live-tail segment carrying the
    // owning message id (walker source for the structured reference).
    const messageRow = container?.querySelector('[data-conversation-message-id="message-assistant-1"]');
    if (!messageRow) {
      throw new Error("message row with data-conversation-message-id not mounted");
    }
    vi.spyOn(window, "getSelection").mockReturnValue(
      fakeSelection(messageRow, fakeRect({ top: 40, left: 10, width: 80, height: 16, bottom: 56, right: 90 })),
    );

    await act(async () => {
      document.dispatchEvent(new Event("mouseup"));
    });
    await flushSelectionFrames();

    const menu = selectionMenu();
    expect(menu?.textContent).toContain("作为引用");
    const referenceButton = Array.from(menu?.querySelectorAll("button") ?? []).find(
      (button) => button.textContent?.includes("作为引用"),
    );
    if (!referenceButton) {
      throw new Error("reference button not mounted");
    }
    await act(async () => {
      referenceButton.click();
      await new Promise((resolve) => setTimeout(resolve, 40));
    });

    expect(onAddComposerReference).toHaveBeenCalledTimes(1);
    expect(onAddComposerReference).toHaveBeenCalledWith({
      referenceId: "message:message-assistant-1",
      kind: "message",
      sourceSessionId: "session-selection-quote",
      sourceMessageId: "message-assistant-1",
      quote: ANSWER_TEXT,
      title: ANSWER_TEXT,
      createdAt: expect.any(String),
    });
    // The structured reference never mutates the draft text.
    expect(container?.querySelector("textarea")?.value).toBe("");
    expect(selectionMenu()).toBeNull();
  });

  it("does not offer the reference action when the selection anchor has no message row", async () => {
    const { timeline } = await renderSelectionConversation();
    // Anchor on the timeline element itself: no message row in the ancestor
    // chain, so only quote/copy are offered.
    vi.spyOn(window, "getSelection").mockReturnValue(
      fakeSelection(timeline, fakeRect({ top: 40, left: 10, width: 80, height: 16, bottom: 56, right: 90 })),
    );

    await act(async () => {
      document.dispatchEvent(new Event("mouseup"));
    });
    await flushSelectionFrames();

    const menu = selectionMenu();
    expect(menu).not.toBeNull();
    expect(menu?.textContent).toContain("引用到输入框");
    expect(menu?.textContent).not.toContain("作为引用");
  });

  it("closes on Escape and on timeline scroll", async () => {
    const { timeline } = await renderSelectionConversation();
    const selectionMock = vi.spyOn(window, "getSelection").mockReturnValue(
      fakeSelection(timeline, fakeRect({ top: 40, left: 10, width: 80, height: 16, bottom: 56, right: 90 })),
    );

    await act(async () => {
      document.dispatchEvent(new Event("mouseup"));
    });
    await flushSelectionFrames();
    expect(selectionMenu()).not.toBeNull();

    await act(async () => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(selectionMenu()).toBeNull();

    // The dismissed selection stays dismissed (keyup must not re-open it).
    await act(async () => {
      document.dispatchEvent(new Event("keyup"));
    });
    await flushSelectionFrames();
    expect(selectionMenu()).toBeNull();

    // Clearing the selection (click-away) re-arms the menu; a fresh selection
    // opens it again.
    selectionMock.mockReturnValue(null);
    await act(async () => {
      document.dispatchEvent(new Event("selectionchange"));
    });
    await flushSelectionFrames();
    selectionMock.mockReturnValue(
      fakeSelection(timeline, fakeRect({ top: 60, left: 12, width: 90, height: 18, bottom: 78, right: 102 })),
    );
    await act(async () => {
      document.dispatchEvent(new Event("mouseup"));
    });
    await flushSelectionFrames();
    expect(selectionMenu()).not.toBeNull();

    // A timeline scroll dismisses it.
    await act(async () => {
      timeline.dispatchEvent(new Event("scroll"));
    });
    expect(selectionMenu()).toBeNull();
  });
});
