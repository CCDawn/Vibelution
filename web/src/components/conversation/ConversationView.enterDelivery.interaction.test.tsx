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

describe("composer Enter delivery (running Enter sends immediately)", () => {
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

  it("steers immediately on Enter while a turn runs, with or without modifiers", async () => {
    const onSubmit = vi.fn();
    const onSafeGuidance = vi.fn();
    const textarea = await renderEnterDeliveryComposer({
      actionMode: "stop",
      onSubmit,
      onSafeGuidance,
    });

    typeIntoTextarea(textarea, "立刻引导");
    await act(async () => {
      pressEnter(textarea);
    });
    expect(onSafeGuidance).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();

    // Modifier keys no longer flip the delivery (user decision): Ctrl+Enter
    // steers exactly like bare Enter.
    typeIntoTextarea(textarea, "再引导一条");
    await act(async () => {
      pressEnter(textarea, { ctrl: true });
    });
    expect(onSafeGuidance).toHaveBeenCalledTimes(2);
    expect(onSubmit).not.toHaveBeenCalled();

    typeIntoTextarea(textarea, "第三条");
    await act(async () => {
      pressEnter(textarea, { meta: true });
    });
    expect(onSafeGuidance).toHaveBeenCalledTimes(3);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("keeps idle behavior: Enter sends, modifiers included", async () => {
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

    typeIntoTextarea(textarea, "修饰键同样发送");
    await act(async () => {
      pressEnter(textarea, { ctrl: true });
    });
    expect(onSubmit).toHaveBeenCalledTimes(2);
    expect(onSafeGuidance).not.toHaveBeenCalled();
  });

  it("queues on Enter when the draft rides attachments or references", async () => {
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
      pressEnter(textarea);
    });
    // Guidance cannot carry references, so Enter queues instead of steering.
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

    // Re-render in stop mode: with a draft the queue primary points at
    // immediate Enter delivery and names itself as the queue entry.
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
      .find((title) => title.includes("Enter") && title.includes("此按钮加入队列"));
    expect(busyHint).toBe(dictionary.zh.composerQueueSteerEnterHint);
  });
});
