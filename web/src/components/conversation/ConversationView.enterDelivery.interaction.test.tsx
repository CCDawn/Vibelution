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
    onInterruptGuidance?: () => void;
    onSubmit: () => void;
    onOpenSideChat?: (prompt: string, autoSend: boolean) => void;
    withReference?: boolean;
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
            composerReferences={options.withReference ? [{
              referenceId: "side-ref",
              kind: "session",
              sessionId: "other-session",
              title: "保留的主会话引用",
            }] : undefined}
            onComposerChange={setValue}
            onSubmit={() => {
              options.onSubmit();
              setValue("");
            }}
            onSafeGuidance={options.onSafeGuidance}
            onInterruptGuidance={options.onInterruptGuidance}
            onOpenSideChat={options.onOpenSideChat}
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

  it.each([
    { actionMode: "send" as const, delivery: "enter", steer: false },
    { actionMode: "stop" as const, delivery: "enter", steer: true },
    { actionMode: "stop" as const, delivery: "enter", steer: false },
    { actionMode: "stop" as const, delivery: "button", steer: true },
    { actionMode: "stop" as const, delivery: "enter", steer: true, withReference: true },
  ])("routes /side to the right rail in $actionMode mode via $delivery (steer=$steer)", async ({ actionMode, delivery, steer, withReference }) => {
    const onSubmit = vi.fn();
    const onSafeGuidance = vi.fn();
    const onOpenSideChat = vi.fn();
    const textarea = await renderEnterDeliveryComposer({
      actionMode,
      onSubmit,
      onSafeGuidance: steer ? onSafeGuidance : undefined,
      onOpenSideChat,
      withReference,
    });
    await act(async () => typeIntoTextarea(textarea, "/side 查一下配置"));
    await act(async () => {
      if (delivery === "enter") {
        pressEnter(textarea);
      } else {
        const primaryButton = container?.querySelector<HTMLButtonElement>('[data-testid="composer-primary-action"]');
        expect(primaryButton).toBeTruthy();
        primaryButton?.click();
      }
    });
    expect(onOpenSideChat).toHaveBeenCalledWith("查一下配置", true);
    expect(onSubmit).not.toHaveBeenCalled();
    expect(onSafeGuidance).not.toHaveBeenCalled();
    expect(textarea.value).toBe("");
    if (withReference) {
      // Side commands carry text, as in idle mode; parent payload stays in its composer.
      expect(container?.textContent).toContain("保留的主会话引用");
    }
  });

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

  it("routes the interrupt guidance menu action only to its handler", async () => {
    const onSubmit = vi.fn();
    const onSafeGuidance = vi.fn();
    const onInterruptGuidance = vi.fn();
    const textarea = await renderEnterDeliveryComposer({
      actionMode: "stop",
      onSubmit,
      onSafeGuidance,
      onInterruptGuidance,
    });

    typeIntoTextarea(textarea, "停下这轮，改问预算");
    const menuTrigger = container?.querySelector<HTMLButtonElement>('button[aria-label="添加与更多操作"]');
    expect(menuTrigger).toBeTruthy();
    await act(async () => menuTrigger?.dispatchEvent(new KeyboardEvent("keydown", {
      key: "ArrowDown", bubbles: true, cancelable: true,
    })));
    const interruptButton = [...document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')]
      .find(button => button.textContent === dictionary.zh.interruptGuidance);
    expect(interruptButton).toBeTruthy();
    expect(interruptButton?.getAttribute("title")).toBe(dictionary.zh.interruptGuidanceHint);
    await act(async () => interruptButton?.click());
    expect(onInterruptGuidance).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();
    expect(onSafeGuidance).not.toHaveBeenCalled();

    // An empty draft restores the single primary stop control.
    await act(async () => {
      typeIntoTextarea(textarea, "");
    });
    expect(container?.querySelector('[data-composer-action="stop"]')).toBeTruthy();
    expect(container?.querySelector('[data-testid="composer-interrupt-guidance"]')).toBeNull();
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

  it("names the single icon action for idle send and running guidance", async () => {
    const onSubmit = vi.fn();
    const textarea = await renderEnterDeliveryComposer({
      actionMode: "send",
      onSubmit,
    });
    expect(container?.querySelector('[data-testid="composer-primary-action"]')?.getAttribute("aria-label"))
      .toBe(dictionary.zh.send);

    await act(async () => root?.unmount());
    container?.remove();
    // A running text draft uses the same guidance delivery as Enter.
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
    const primary = container?.querySelector<HTMLButtonElement>('[data-testid="composer-primary-action"]');
    expect(primary?.getAttribute("aria-label")).toBe(dictionary.zh.safeGuidance);
    expect(primary?.getAttribute("data-composer-action")).toBe("steer");
  });
});
