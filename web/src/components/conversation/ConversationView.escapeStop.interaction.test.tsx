/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { dictionary } from "../../i18n/dictionary";
import { queryKeys } from "../../api/queryKeys";
import type { ReferenceTypeaheadOption } from "./conversationReferenceTypeahead";
import { ConversationView } from "./ConversationView";

vi.mock("./LazyConversationMarkdownRenderer", async () => {
  const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
  return { LazyConversationMarkdownRenderer: ConversationMarkdownRenderer };
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function knowledgeOption(id: string, title: string): ReferenceTypeaheadOption {
  return {
    id,
    title,
    meta: "知识库引用",
    reference: {
      referenceId: id,
      kind: "knowledge_item",
      knowledgeBaseId: "kb-1",
      knowledgeItemId: id,
      title,
      createdAt: "2026-01-01T00:00:00Z",
    },
  };
}

const referenceOptions: ReferenceTypeaheadOption[] = [
  knowledgeOption("knowledge-item:arch", "架构笔记"),
];

function typeIntoTextarea(textarea: HTMLTextAreaElement, value: string, caretIndex: number) {
  const nativeValueSetter = Object.getOwnPropertyDescriptor(
    HTMLTextAreaElement.prototype,
    "value",
  )?.set;
  nativeValueSetter?.call(textarea, value);
  textarea.setSelectionRange(caretIndex, caretIndex);
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("composer Escape stop interaction", () => {
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

  async function renderEscapeStopComposer(options: {
    onStop: () => void;
    initialActionMode?: "send" | "stop";
  }) {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    queryClient.setQueryData(queryKeys.configPublic(), { language: "zh" });
    queryClient.setQueryData(["i18n", "dictionary-domains", "core,chat"], dictionary);

    function Harness() {
      const [value, setValue] = useState("");
      // Mirrors the bridge state machine: once stop fires, the session flips
      // out of stop mode (sessionStopping), so a repeat Escape must not stop.
      const [actionMode, setActionMode] = useState<"send" | "stop">(
        options.initialActionMode ?? "stop",
      );
      return (
        <QueryClientProvider client={queryClient}>
          <ConversationView
            sessionId="session-escape-stop"
            title="Session"
            phase="ready"
            messages={[]}
            showHeader={false}
            showSessionOverview={false}
            showComposer
            defaultFileContext="workspace"
            composerValue={value}
            composerPlaceholder=""
            composerDisabled={false}
            composerPending={false}
            composerActionMode={actionMode}
            composerReferenceOptions={referenceOptions}
            onComposerChange={setValue}
            onAddComposerReference={() => undefined}
            onSubmit={() => undefined}
            onStop={() => {
              options.onStop();
              setActionMode("send");
            }}
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
    const textarea = container.querySelector<HTMLTextAreaElement>("textarea");
    if (!textarea) {
      throw new Error("composer textarea not mounted");
    }
    textarea.focus();
    return textarea;
  }

  function pressEscape(textarea: HTMLTextAreaElement) {
    textarea.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
  }

  function listbox(): HTMLElement | null {
    return container?.querySelector('[role="listbox"][aria-label="引用候选"]') ?? null;
  }

  it("stops the running turn from the focused composer and consumes the key once", async () => {
    const onStop = vi.fn();
    const textarea = await renderEscapeStopComposer({ onStop });

    await act(async () => {
      pressEscape(textarea);
    });
    expect(onStop).toHaveBeenCalledTimes(1);

    // Repeat press: stop mode already flipped back to send, so no second stop.
    await act(async () => {
      pressEscape(textarea);
    });
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it("never stops in send mode", async () => {
    const onStop = vi.fn();
    const textarea = await renderEscapeStopComposer({ onStop, initialActionMode: "send" });

    await act(async () => {
      pressEscape(textarea);
    });
    expect(onStop).not.toHaveBeenCalled();
  });

  it("lets a live reference typeahead claim Escape instead of stopping", async () => {
    const onStop = vi.fn();
    const textarea = await renderEscapeStopComposer({ onStop });

    await act(async () => {
      typeIntoTextarea(textarea, "参考 @架", 4);
    });
    expect(listbox()).not.toBeNull();

    await act(async () => {
      pressEscape(textarea);
    });
    expect(listbox()).toBeNull();
    expect(onStop).not.toHaveBeenCalled();

    // With the typeahead closed again, Escape reaches the stop fallback.
    await act(async () => {
      pressEscape(textarea);
    });
    expect(onStop).toHaveBeenCalledTimes(1);
  });
});
