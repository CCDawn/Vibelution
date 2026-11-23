/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act, useMemo, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { dictionary } from "../../i18n/dictionary";
import { queryKeys } from "../../api/queryKeys";
import { ConversationView } from "./ConversationView";
import { createComposerDraftStore } from "./composerDraftStore";

// happy-dom has no layout: the real virtualizer reports an empty viewport and
// drops every timeline row, including the inline editor under test.
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: (options: { count: number; scrollMargin?: number }) => ({
    options: { ...options, scrollMargin: options.scrollMargin ?? 0 },
    getVirtualItems: () =>
      Array.from({ length: options.count }, (_, index) => ({
        index,
        key: index,
        start: index * 100,
        size: 100,
        end: (index + 1) * 100,
      })),
    getVirtualItemForOffset: (offset: number) => {
      if (!options.count) {
        return undefined;
      }
      const index = Math.max(0, Math.min(options.count - 1, Math.floor(offset / 100)));
      return { index, key: index, start: index * 100, size: 100, end: (index + 1) * 100 };
    },
    getOffsetForIndex: () => 0,
    getTotalSize: () => options.count * 100,
    measureElement: () => undefined,
    measure: () => undefined,
    scrollToIndex: () => undefined,
    scrollToOffset: () => undefined,
    scrollRect: { height: 800, width: 1200 },
  }),
}));

vi.mock("./LazyConversationMarkdownRenderer", async () => {
  const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
  return { LazyConversationMarkdownRenderer: ConversationMarkdownRenderer };
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function typeIntoTextarea(textarea: HTMLTextAreaElement, value: string) {
  const nativeValueSetter = Object.getOwnPropertyDescriptor(
    HTMLTextAreaElement.prototype,
    "value",
  )?.set;
  nativeValueSetter?.call(textarea, value);
  textarea.setSelectionRange(value.length, value.length);
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("inline message edit input", () => {
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
  });

  it("keeps the keystroke when the workbench passes its mounted draft store", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    queryClient.setQueryData(queryKeys.configPublic(), { language: "zh" });
    queryClient.setQueryData(["i18n", "dictionary-domains", "core,chat"], dictionary);

    function Harness() {
      const [value, setValue] = useState("Original prompt");
      const store = useMemo(() => createComposerDraftStore("Original prompt"), []);
      return (
        <QueryClientProvider client={queryClient}>
          <ConversationView
            sessionId="session-inline-edit"
            title="Session"
            phase="ready"
            messages={[
              {
                id: "message-user",
                role: "user",
                content: "Original prompt",
                timestamp: "2026-05-22T00:00:00Z",
              },
            ]}
            showHeader={false}
            showSessionOverview={false}
            showComposer
            defaultFileContext="workspace"
            composerDraftStore={store}
            composerValue={value}
            composerPlaceholder=""
            composerDisabled={false}
            composerPending={false}
            composerActionMode="send"
            editingMessageId="message-user"
            editUserMessageDisabled={false}
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

    let textarea: HTMLTextAreaElement | null = null;
    for (let attempt = 0; attempt < 40 && !textarea; attempt += 1) {
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 50));
      });
      textarea = container.querySelector<HTMLTextAreaElement>(
        '[data-conversation-inline-edit-input="1"]',
      );
    }
    if (!textarea) {
      throw new Error(`inline edit textarea not mounted: ${container.innerHTML.slice(0, 400)}`);
    }

    await act(async () => {
      typeIntoTextarea(textarea as HTMLTextAreaElement, "Original prompt revised");
    });

    expect(textarea.value).toBe("Original prompt revised");
  });

  it("keeps typing while the upstream draft is still waiting on the typing pause", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    queryClient.setQueryData(queryKeys.configPublic(), { language: "zh" });
    queryClient.setQueryData(["i18n", "dictionary-domains", "core,chat"], dictionary);
    function Harness() {
      // Mirrors the workbench: the prop only moves after the 400ms mirror, so
      // keystrokes must survive on the store alone.
      const store = useMemo(() => createComposerDraftStore("Original prompt"), []);
      return (
        <QueryClientProvider client={queryClient}>
          <ConversationView
            sessionId="session-inline-edit"
            title="Session"
            phase="ready"
            messages={[
              {
                id: "message-user",
                role: "user",
                content: "Original prompt",
                timestamp: "2026-05-22T00:00:00Z",
              },
            ]}
            showHeader={false}
            showSessionOverview={false}
            showComposer
            defaultFileContext="workspace"
            composerDraftStore={store}
            composerValue="Original prompt"
            composerPlaceholder=""
            composerDisabled={false}
            composerPending={false}
            composerActionMode="send"
            editingMessageId="message-user"
            editUserMessageDisabled={false}
            onComposerChange={() => undefined}
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
    let textarea: HTMLTextAreaElement | null = null;
    for (let attempt = 0; attempt < 40 && !textarea; attempt += 1) {
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 50));
      });
      textarea = container.querySelector<HTMLTextAreaElement>(
        '[data-conversation-inline-edit-input="1"]',
      );
    }
    if (!textarea) {
      throw new Error(`inline edit textarea not mounted: ${container.innerHTML.slice(0, 400)}`);
    }
    await act(async () => {
      typeIntoTextarea(textarea as HTMLTextAreaElement, "Original prompt revised");
    });
    expect((textarea as HTMLTextAreaElement).value).toBe("Original prompt revised");
    await act(async () => {
      typeIntoTextarea(textarea as HTMLTextAreaElement, "Original prompt revised!");
    });
    expect((textarea as HTMLTextAreaElement).value).toBe("Original prompt revised!");
  });

});
