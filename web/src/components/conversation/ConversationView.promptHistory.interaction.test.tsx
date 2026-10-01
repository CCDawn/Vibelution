/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { dictionary } from "../../i18n/dictionary";
import { queryKeys } from "../../api/queryKeys";
import {
  PROMPT_HISTORY_STORAGE_KEY,
  appendStoredPromptHistoryEntry,
} from "./conversationPromptHistory";
import { ConversationView } from "./ConversationView";

vi.mock("./LazyConversationMarkdownRenderer", async () => {
  const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
  return { LazyConversationMarkdownRenderer: ConversationMarkdownRenderer };
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

afterEach(() => {
  window.localStorage.removeItem(PROMPT_HISTORY_STORAGE_KEY);
});

describe("composer prompt history interaction", () => {
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

  async function renderPromptHistoryComposer(options: { seededHistory?: string[] } = {}) {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    queryClient.setQueryData(queryKeys.configPublic(), { language: "zh" });
    queryClient.setQueryData(["i18n", "dictionary-domains", "core,chat"], dictionary);

    for (const entry of options.seededHistory ?? []) {
      appendStoredPromptHistoryEntry(entry);
    }

    function Harness() {
      const [value, setValue] = useState("");
      return (
        <QueryClientProvider client={queryClient}>
          <ConversationView
            sessionId="session-prompt-history"
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
            composerActionMode="send"
            onComposerChange={setValue}
            onAddComposerReference={() => undefined}
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
    textarea.focus();
    return textarea;
  }

  function pressArrow(textarea: HTMLTextAreaElement, key: "ArrowUp" | "ArrowDown", composing = false) {
    textarea.dispatchEvent(new KeyboardEvent("keydown", {
      key,
      isComposing: composing,
      bubbles: true,
      cancelable: true,
    }));
  }

  function typeIntoTextarea(textarea: HTMLTextAreaElement, value: string, caretIndex: number) {
    const nativeValueSetter = Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )?.set;
    nativeValueSetter?.call(textarea, value);
    textarea.setSelectionRange(caretIndex, caretIndex);
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  }

  it("recalls the most recent prompt with ArrowUp on an empty draft", async () => {
    const textarea = await renderPromptHistoryComposer({
      seededHistory: ["older prompt", "newer prompt"],
    });

    await act(async () => {
      pressArrow(textarea, "ArrowUp");
    });
    expect(textarea.value).toBe("newer prompt");

    await act(async () => {
      pressArrow(textarea, "ArrowUp");
    });
    expect(textarea.value).toBe("older prompt");
  });

  it("walks forward with ArrowDown and restores the empty draft past the newest", async () => {
    const textarea = await renderPromptHistoryComposer({
      seededHistory: ["older prompt", "newer prompt"],
    });

    await act(async () => {
      pressArrow(textarea, "ArrowUp");
    });
    expect(textarea.value).toBe("newer prompt");
    await act(async () => {
      pressArrow(textarea, "ArrowUp");
    });
    expect(textarea.value).toBe("older prompt");
    await act(async () => {
      pressArrow(textarea, "ArrowDown");
    });
    expect(textarea.value).toBe("newer prompt");
    await act(async () => {
      pressArrow(textarea, "ArrowDown");
    });
    // Back past the newest entry: the stashed (empty) draft is restored.
    expect(textarea.value).toBe("");
  });

  it("does not take over when the draft is non-empty", async () => {
    const textarea = await renderPromptHistoryComposer({
      seededHistory: ["recall-me"],
    });

    await act(async () => {
      typeIntoTextarea(textarea, "draft in progress", 17);
    });
    await act(async () => {
      pressArrow(textarea, "ArrowUp");
    });
    expect(textarea.value).toBe("draft in progress");
  });

  it("does not take over during IME composition", async () => {
    const textarea = await renderPromptHistoryComposer({
      seededHistory: ["recall-me"],
    });

    await act(async () => {
      pressArrow(textarea, "ArrowUp", true);
    });
    expect(textarea.value).toBe("");
  });

  it("exits the browse mode when the user edits the recalled prompt", async () => {
    const textarea = await renderPromptHistoryComposer({
      seededHistory: ["first", "second"],
    });

    await act(async () => {
      pressArrow(textarea, "ArrowUp");
    });
    expect(textarea.value).toBe("second");

    // A manual edit leaves the browse mode, so ArrowUp no longer navigates.
    await act(async () => {
      typeIntoTextarea(textarea, "second!", 7);
    });
    await act(async () => {
      pressArrow(textarea, "ArrowUp");
    });
    expect(textarea.value).toBe("second!");
  });
});
