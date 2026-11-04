/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { dictionary } from "../../i18n/dictionary";
import { queryKeys } from "../../api/queryKeys";
import { ConversationView } from "./ConversationView";
import type { SessionMessageCurationAction, SessionMessageCurationMutationResponse } from "../../api/types";

vi.mock("./LazyConversationMarkdownRenderer", async () => {
  const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
  return { LazyConversationMarkdownRenderer: ConversationMarkdownRenderer };
});

// happy-dom has no layout, so react-virtual never materializes history rows.
// Enumerate every row so the curation action rail mounts like the SSR tests.
vi.mock("@tanstack/react-virtual", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-virtual")>();
  return {
    ...actual,
    useVirtualizer: (options: { count?: number; estimateSize?: () => number; getItemKey?: (index: number) => string } & Record<string, unknown>) => {
      const size = () => (typeof options.estimateSize === "function" ? options.estimateSize() : 0);
      const items = Array.from({ length: options.count ?? 0 }, (_, index) => ({
        index,
        key: options.getItemKey?.(index) ?? String(index),
        size: size(),
        start: index * size(),
        end: (index + 1) * size(),
        lane: 0,
      }));
      return {
        options,
        getVirtualItems: () => items,
        getTotalSize: () => items.reduce((sum, item) => sum + item.size, 0),
        measureElement: () => undefined,
        scrollToIndex: () => undefined,
        resizeItem: () => undefined,
        getVirtualItemForOffset: () => items[0] ?? null,
        scrollRect: undefined,
      };
    },
  };
});

const setCuration = vi.fn<
  (sessionId: string, messageId: string, action: SessionMessageCurationAction) => Promise<SessionMessageCurationMutationResponse>
>();
vi.mock("../../api/chat", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/chat")>();
  return {
    ...actual,
    fetchSessionMessageCuration: vi.fn(async () => ({ items: [] })),
    setSessionMessageCuration: (sessionId: string, messageId: string, action: SessionMessageCurationAction) =>
      setCuration(sessionId, messageId, action),
  };
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const ASSISTANT_MESSAGE = {
  id: "message-curation-1",
  role: "assistant",
  content: "答案正文",
  timestamp: "2026-05-22T00:01:00Z",
  turnId: "turn-1",
  status: "completed",
  nodeId: "node-curation-1",
  turnItems: [
    {
      id: "message-curation-1-item-answer",
      itemId: "message-curation-1-item-answer",
      sessionId: "session-curation",
      turnId: "turn-1",
      version: 3,
      revision: 1,
      sequence: 1,
      type: "agent_message",
      phase: "final_answer",
      text: "答案正文",
      status: "completed",
      terminal: true,
    },
  ],
} as unknown as import("../../api/types").ConversationMessage;

describe("message curation feedback (excerpt granularity comms)", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root?.unmount();
      });
    }
    container?.remove();
    root = null;
    container = null;
    setCuration.mockReset();
  });

  async function renderCurationComposer() {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    queryClient.setQueryData(queryKeys.configPublic(), { language: "zh" });
    queryClient.setQueryData(["i18n", "dictionary-domains", "core,chat"], dictionary);

    function Harness() {
      const [value, setValue] = useState("");
      return (
        <QueryClientProvider client={queryClient}>
          <ConversationView
            sessionId="session-curation"
            title="Session"
            phase="ready"
            messages={[ASSISTANT_MESSAGE]}
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
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    return container;
  }

  function includeButton(): HTMLButtonElement {
    const button = Array.from(container?.querySelectorAll<HTMLButtonElement>("button") ?? [])
      .find((candidate) => (candidate.getAttribute("aria-label") ?? "").includes("片段"));
    if (!button) throw new Error("curation include button not mounted");
    return button;
  }

  it("announces excerpt-granularity tooltips before the first click", () => {
    // The tooltip must say what gets curated: the excerpt from the session
    // start through this message, not a single message.
    expect(dictionary.zh.addToDataset).toContain("片段");
    expect(dictionary.zh.addToDataset).toContain("会话开头至此消息");
    expect(dictionary.zh.excludeFromDataset).toContain("会话开头至此消息");
    expect(dictionary.en.addToDataset).toContain("conversation start through this message");
  });

  it("shows the backend excerpt summary as a persistent dismissible notice", async () => {
    await renderCurationComposer();
    setCuration.mockResolvedValue({
      sessionId: "session-curation",
      messageId: "message-curation-1",
      action: "include",
      status: "included",
      candidateId: "candidate-1",
      caseId: "candidate-1",
      modelId: "model-1",
      datasetName: "positive",
      summary: "已把这条消息所在的片段纳入正例数据集。",
    });
    await act(async () => {
      includeButton().click();
    });
    const notice = () => container?.querySelector<HTMLElement>("[data-conversation-curation-feedback]");
    expect(notice()).not.toBeNull();
    expect(notice()?.textContent).toContain("已把这条消息所在的片段纳入正例数据集。");
    // Persistent: no 3-second auto-dismiss pass removes the summary.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 40));
    });
    expect(notice()).not.toBeNull();
    // Dismissible through the explicit close control.
    const dismiss = container?.querySelector<HTMLButtonElement>('[aria-label="关闭提示"]');
    expect(dismiss).not.toBeNull();
    await act(async () => {
      dismiss?.click();
    });
    expect(notice()).toBeNull();
  });

  it("keeps the 409 conflict guidance visible with the review-workspace hint", async () => {
    await renderCurationComposer();
    const conflictError = Object.assign(
      new Error("这条消息所在的片段已进入另一侧数据集（或已丢弃），不能重复策展。"),
      { status: 409, code: null, details: null, name: "FetchJsonHttpError" },
    );
    setCuration.mockRejectedValue(conflictError);
    await act(async () => {
      includeButton().click();
    });
    const notice = () => container?.querySelector<HTMLElement>("[data-conversation-curation-feedback]");
    expect(notice()).not.toBeNull();
    expect(notice()?.textContent).toContain("不能重复策展");
    expect(notice()?.textContent).toContain("review 工作区");
    // The failed decision rolls the optimistic flip back, so the include
    // button stays available for a retry attempt.
    expect(setCuration).toHaveBeenCalledTimes(1);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 40));
    });
    expect(notice()).not.toBeNull();
  });
});
