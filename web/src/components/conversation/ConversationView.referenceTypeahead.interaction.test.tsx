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
  knowledgeOption("knowledge-item:roadmap", "Roadmap 2026"),
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

describe("composer @ reference type-ahead interaction", () => {
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

  async function renderTypeaheadComposer(options: {
    onAddReference: (referenceId: string) => void;
  }) {
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
            sessionId="session-reference-typeahead"
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
            composerReferenceOptions={referenceOptions}
            onComposerChange={setValue}
            onAddComposerReference={options.onAddReference}
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
    const textarea = container.querySelector<HTMLTextAreaElement>("textarea");
    if (!textarea) {
      throw new Error("composer textarea not mounted");
    }
    return textarea;
  }

  function listbox(): HTMLElement | null {
    return container?.querySelector('[role="listbox"][aria-label="引用候选"]') ?? null;
  }

  it("shows reference candidates with the reference badge while an @ token is live", async () => {
    const onAddReference = vi.fn();
    const textarea = await renderTypeaheadComposer({ onAddReference });

    await act(async () => {
      typeIntoTextarea(textarea, "请引用 @架构", 7);
    });

    const box = listbox();
    expect(box).not.toBeNull();
    expect(box?.textContent).toContain("架构笔记");
    expect(box?.textContent).toContain("引用");
    expect(textarea.getAttribute("aria-expanded")).toBe("true");
    expect(textarea.getAttribute("aria-controls")).toBe(
      "conversation-session-reference-typeahead-reference-suggestions",
    );
  });

  it("filters candidates by the typed fragment and removes the token on select with picker-parity payloads", async () => {
    const onAddReference = vi.fn();
    const textarea = await renderTypeaheadComposer({ onAddReference });

    await act(async () => {
      typeIntoTextarea(textarea, "@road", 5);
    });
    const box = listbox();
    expect(box).not.toBeNull();
    expect(box?.textContent).toContain("Roadmap 2026");
    expect(box?.textContent).not.toContain("架构笔记");

    await act(async () => {
      textarea.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
    });

    expect(onAddReference).toHaveBeenCalledTimes(1);
    expect(onAddReference.mock.calls[0]?.[0]).toEqual(referenceOptions[1]?.reference);
    expect(listbox()).toBeNull();
    // The "@road" fragment is removed from the draft and the caret parks at
    // the removal point once the post-select frame runs.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 40));
    });
    expect(textarea.value).toBe("");
    expect(textarea.selectionStart).toBe(0);
  });

  it("navigates with arrow keys and exposes the active option via aria-activedescendant", async () => {
    const onAddReference = vi.fn();
    const textarea = await renderTypeaheadComposer({ onAddReference });

    await act(async () => {
      typeIntoTextarea(textarea, "@", 1);
    });
    expect(textarea.getAttribute("aria-activedescendant")).toBe(
      "conversation-session-reference-typeahead-reference-suggestions-option-0",
    );

    // The first ArrowDown lands on index 0 (already the clamped default), the
    // second moves to the next option, mirroring slash navigation.
    await act(async () => {
      textarea.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, cancelable: true }));
    });
    expect(textarea.getAttribute("aria-activedescendant")).toBe(
      "conversation-session-reference-typeahead-reference-suggestions-option-0",
    );

    await act(async () => {
      textarea.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, cancelable: true }));
    });
    expect(textarea.getAttribute("aria-activedescendant")).toBe(
      "conversation-session-reference-typeahead-reference-suggestions-option-1",
    );

    await act(async () => {
      textarea.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowUp", bubbles: true, cancelable: true }));
    });
    expect(textarea.getAttribute("aria-activedescendant")).toBe(
      "conversation-session-reference-typeahead-reference-suggestions-option-0",
    );
  });

  it("keeps the list closed during IME composition and re-arms after composition ends", async () => {
    const onAddReference = vi.fn();
    const textarea = await renderTypeaheadComposer({ onAddReference });

    await act(async () => {
      textarea.dispatchEvent(new CompositionEvent("compositionstart", { bubbles: true }));
    });
    await act(async () => {
      // Pinyin/IME intermediates (including "@引用") must not pop the list.
      typeIntoTextarea(textarea, "@引用", 3);
    });
    expect(listbox()).toBeNull();

    await act(async () => {
      textarea.dispatchEvent(new CompositionEvent("compositionend", { bubbles: true }));
    });
    expect(listbox()).not.toBeNull();
    expect(listbox()?.textContent).toContain("架构笔记");
  });

  it("dismisses with Escape and stays inert for email-like @ usage", async () => {
    const onAddReference = vi.fn();
    const textarea = await renderTypeaheadComposer({ onAddReference });

    await act(async () => {
      typeIntoTextarea(textarea, "mail@example", 12);
    });
    expect(listbox()).toBeNull();

    await act(async () => {
      typeIntoTextarea(textarea, "参考 @架构", 5);
    });
    expect(listbox()).not.toBeNull();

    await act(async () => {
      textarea.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
    });
    expect(listbox()).toBeNull();
    expect(onAddReference).not.toHaveBeenCalled();
  });
});
