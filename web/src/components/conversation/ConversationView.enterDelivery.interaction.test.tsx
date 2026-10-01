/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { dictionary } from "../../i18n/dictionary";
import { queryKeys } from "../../api/queryKeys";
import { ConversationView } from "./ConversationView";

vi.mock("./LazyConversationMarkdownRenderer", async () => {
  const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
  return { LazyConversationMarkdownRenderer: ConversationMarkdownRenderer };
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function typeIntoTextarea(textarea: HTMLTextAreaElement, value: string, caretIndex?: number) {
  const nativeValueSetter = Object.getOwnPropertyDescriptor(
    HTMLTextAreaElement.prototype,
    "value",
  )?.set;
  nativeValueSetter?.call(textarea, value);
  const caret = caretIndex ?? value.length;
  textarea.setSelectionRange(caret, caret);
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("composer Enter delivery (ZCode opposite follow-up delivery)", () => {
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

  async function renderEnterDeliveryComposer(options: {
    actionMode: "send" | "stop";
    onSafeGuidance?: () => void;
    onSubmit: () => void;
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
            sessionId="session-enter-delivery"
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
            composerActionMode={options.actionMode}
            onComposerChange={setValue}
            onSubmit={() => {
              options.onSubmit();
              setValue("");
            }}
            onSafeGuidance={options.onSafeGuidance}
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

  function pressEnter(textarea: HTMLTextAreaElement, modifiers: { ctrl?: boolean; meta?: boolean } = {}) {
    textarea.dispatchEvent(new KeyboardEvent("keydown", {
      key: "Enter",
      ctrlKey: modifiers.ctrl ?? false,
      metaKey: modifiers.meta ?? false,
      bubbles: true,
      cancelable: true,
    }));
  }

  it("queues on bare Enter and steers immediately on Ctrl/⌘+Enter while a turn runs", async () => {
    const onSubmit = vi.fn();
    const onSafeGuidance = vi.fn();
    const textarea = await renderEnterDeliveryComposer({
      actionMode: "stop",
      onSubmit,
      onSafeGuidance,
    });

    typeIntoTextarea(textarea, "追加一条");
    await act(async () => {
      pressEnter(textarea);
    });
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSafeGuidance).not.toHaveBeenCalled();

    typeIntoTextarea(textarea, "立刻引导");
    await act(async () => {
      pressEnter(textarea, { ctrl: true });
    });
    expect(onSafeGuidance).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledTimes(1);

    typeIntoTextarea(textarea, "再来一条");
    await act(async () => {
      pressEnter(textarea, { meta: true });
    });
    expect(onSafeGuidance).toHaveBeenCalledTimes(2);
  });

  it("keeps idle behavior: bare Enter sends, Ctrl/⌘+Enter does nothing", async () => {
    const onSubmit = vi.fn();
    const onSafeGuidance = vi.fn();
    const textarea = await renderEnterDeliveryComposer({
      actionMode: "send",
      onSubmit,
      onSafeGuidance,
    });

    typeIntoTextarea(textarea, "正常发送");
    await act(async () => {
      pressEnter(textarea);
    });
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSafeGuidance).not.toHaveBeenCalled();

    typeIntoTextarea(textarea, "修饰键不发送");
    await act(async () => {
      pressEnter(textarea, { ctrl: true });
    });
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSafeGuidance).not.toHaveBeenCalled();
  });

  it("falls the Ctrl+Enter flip back to queueing when the draft rides attachments or references", async () => {
    const onSubmit = vi.fn();
    const onSafeGuidance = vi.fn();
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
            sessionId="session-enter-delivery-refs"
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
            composerActionMode="stop"
            composerReferences={[{
              referenceId: "ref-1",
              kind: "session",
              sessionId: "other-session",
              title: "参考会话",
            }]}
            onComposerChange={setValue}
            onSubmit={() => {
              onSubmit();
              setValue("");
            }}
            onSafeGuidance={onSafeGuidance}
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

    typeIntoTextarea(textarea, "带引用的引导");
    await act(async () => {
      pressEnter(textarea, { ctrl: true });
    });
    // Guidance cannot carry references, so the flip queues instead.
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSafeGuidance).not.toHaveBeenCalled();
  });

  it("labels the primary control with the keyboard contract per state", async () => {
    const onSubmit = vi.fn();
    const textarea = await renderEnterDeliveryComposer({
      actionMode: "send",
      onSubmit,
    });
    const idleHint = Array.from(container?.querySelectorAll<HTMLButtonElement>("button[title]") ?? [])
      .map((button) => button.getAttribute("title") ?? "")
      .find((title) => title.includes("Enter"));
    expect(idleHint).toBe(dictionary.zh.composerSendEnterHint);

    // Re-render in stop mode: with a draft the queue primary names both deliveries.
    const stopGuidance = vi.fn();
    const stopSubmit = vi.fn();
    const busyTextarea = await renderEnterDeliveryComposer({
      actionMode: "stop",
      onSubmit: stopSubmit,
      onSafeGuidance: stopGuidance,
    });
    typeIntoTextarea(busyTextarea, "排队中的草稿");
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    const busyHint = Array.from(container?.querySelectorAll<HTMLButtonElement>("button[title]") ?? [])
      .map((button) => button.getAttribute("title") ?? "")
      .find((title) => title.includes("Enter") && title.includes("立刻引导"));
    expect(busyHint).toBe(dictionary.zh.composerQueueSteerEnterHint);
  });
});
