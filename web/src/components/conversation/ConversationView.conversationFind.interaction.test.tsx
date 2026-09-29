/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../api/queryKeys";
import type { ConversationMessage } from "../../api/types";
import { dictionary } from "../../i18n/dictionary";
import { ConversationView } from "./ConversationView";

vi.mock("./LazyConversationMarkdownRenderer", async () => {
  const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
  return { LazyConversationMarkdownRenderer: ConversationMarkdownRenderer };
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function userMessage(id: string, content: string): ConversationMessage {
  return {
    id,
    role: "user",
    timestamp: "2026-09-29T10:00:00Z",
    content,
  };
}

function assistantMessage(id: string, text: string): ConversationMessage {
  return {
    id,
    role: "assistant",
    timestamp: "2026-09-29T10:00:05Z",
    turnId: `${id}-turn`,
    status: "completed",
    turnItems: [
      {
        id: `${id}-reasoning`,
        itemId: `${id}-reasoning`,
        version: 3 as const,
        sessionId: "session-find",
        turnId: `${id}-turn`,
        type: "reasoning" as const,
        status: "completed" as const,
        revision: 1,
        sequence: 0,
        text: `thinking about the ${text}`,
      },
      {
        id: `${id}-answer`,
        itemId: `${id}-answer`,
        version: 3 as const,
        sessionId: "session-find",
        turnId: `${id}-turn`,
        type: "agent_message" as const,
        phase: "final_answer" as const,
        status: "completed" as const,
        revision: 1,
        sequence: 1,
        text: `the answer mentions ${text}.`,
      },
    ],
  };
}

function findBar(container: HTMLElement): HTMLElement | null {
  return container.querySelector('[data-conversation-find-bar="true"]');
}

function findInput(container: HTMLElement): HTMLInputElement {
  const input = container.querySelector<HTMLInputElement>('input[data-conversation-find-input="true"]');
  if (!input) {
    throw new Error("find input not mounted");
  }
  return input;
}

function findCount(container: HTMLElement): string {
  return container.querySelector('[data-conversation-find-count="true"]')?.textContent ?? "";
}

function typeIntoInput(input: HTMLInputElement, value: string) {
  const nativeValueSetter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )?.set;
  nativeValueSetter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

function pressKey(target: HTMLElement, key: string, options: KeyboardEventInit = {}) {
  target.dispatchEvent(new KeyboardEvent("keydown", {
    key,
    bubbles: true,
    cancelable: true,
    ...options,
  }));
}

async function flushDebounce() {
  // Find 查询防抖 150ms；等待一拍让 settled 查询驱动索引重建。
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 220));
  });
}

describe("ConversationView find-in-transcript interaction", () => {
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

  async function renderFindHarness(options: {
    messages: ConversationMessage[];
    onStop?: () => void;
    initialActionMode?: "send" | "stop";
  }) {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    queryClient.setQueryData(queryKeys.configPublic(), { language: "zh" });
    queryClient.setQueryData(["i18n", "dictionary-domains", "core,chat"], dictionary);

    function Harness() {
      const [actionMode, setActionMode] = useState<"send" | "stop">(
        options.initialActionMode ?? "stop",
      );
      return (
        <QueryClientProvider client={queryClient}>
          <ConversationView
            sessionId="session-find"
            title="Session"
            phase="ready"
            messages={options.messages}
            showHeader={false}
            showSessionOverview={false}
            showComposer
            defaultFileContext="workspace"
            composerValue=""
            composerPlaceholder=""
            composerDisabled={false}
            composerPending={false}
            composerActionMode={actionMode}
            onComposerChange={() => undefined}
            onAddComposerReference={() => undefined}
            onSubmit={() => undefined}
            onStop={() => {
              options.onStop?.();
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
    return container;
  }

  function composerTextarea(containerElement: HTMLDivElement): HTMLTextAreaElement {
    const textarea = containerElement.querySelector<HTMLTextAreaElement>("textarea");
    if (!textarea) {
      throw new Error("composer textarea not mounted");
    }
    textarea.focus();
    return textarea;
  }

  it("opens with Ctrl+F from the focused composer and shows the match count", async () => {
    const rendered = await renderFindHarness({
      messages: [userMessage("u1", "deploy the service"), assistantMessage("a1", "deploy")],
    });
    const textarea = composerTextarea(rendered);

    await act(async () => {
      pressKey(textarea, "f", { ctrlKey: true });
    });
    expect(findBar(rendered)).not.toBeNull();

    await act(async () => {
      typeIntoInput(findInput(rendered), "deploy");
    });
    await flushDebounce();
    // user 正文 + assistant reasoning + assistant 正文 = 3 处命中。
    expect(findCount(rendered)).toBe("1/3");
  });

  it("shows 0/0 for a no-hit query and keeps the input usable", async () => {
    const rendered = await renderFindHarness({
      messages: [userMessage("u1", "deploy the service")],
    });
    const textarea = composerTextarea(rendered);

    await act(async () => {
      pressKey(textarea, "f", { ctrlKey: true });
    });
    await act(async () => {
      typeIntoInput(findInput(rendered), "不存在的词");
    });
    await flushDebounce();
    expect(findCount(rendered)).toBe("0/0");
    expect(findInput(rendered).disabled).toBe(false);
  });

  it("navigates with Enter / Shift+Enter and wraps around the match list", async () => {
    const rendered = await renderFindHarness({
      messages: [userMessage("u1", "needle one"), userMessage("u2", "needle two")],
    });
    const textarea = composerTextarea(rendered);

    await act(async () => {
      pressKey(textarea, "f", { ctrlKey: true });
    });
    await act(async () => {
      typeIntoInput(findInput(rendered), "needle");
    });
    await flushDebounce();
    expect(findCount(rendered)).toBe("1/2");

    // Enter → 下一个；到最后再 Enter 环回第一个。
    await act(async () => {
      pressKey(findInput(rendered), "Enter");
    });
    expect(findCount(rendered)).toBe("2/2");
    await act(async () => {
      pressKey(findInput(rendered), "Enter");
    });
    expect(findCount(rendered)).toBe("1/2");

    // Shift+Enter → 上一个；到第一个再按环回最后一个。
    await act(async () => {
      pressKey(findInput(rendered), "Enter", { shiftKey: true });
    });
    expect(findCount(rendered)).toBe("2/2");
  });

  it("closes with Escape before the composer stop semantics and restores stop afterwards", async () => {
    const onStop = vi.fn();
    const rendered = await renderFindHarness({
      messages: [userMessage("u1", "deploy the service"), assistantMessage("a1", "deploy")],
      onStop,
    });
    const textarea = composerTextarea(rendered);

    await act(async () => {
      pressKey(textarea, "f", { ctrlKey: true });
    });
    expect(findBar(rendered)).not.toBeNull();

    // Find 条打开时 Esc 只关查找条，绝不触发停止语义。
    await act(async () => {
      pressKey(textarea, "Escape");
    });
    expect(findBar(rendered)).toBeNull();
    expect(onStop).not.toHaveBeenCalled();

    // 关闭后 Esc 恢复停止语义（现有契约零回归）。
    await act(async () => {
      pressKey(textarea, "Escape");
    });
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it("closes from the find input Escape and clears row marks on close", async () => {
    const rendered = await renderFindHarness({
      messages: [userMessage("u1", "deploy the service")],
    });
    const textarea = composerTextarea(rendered);

    await act(async () => {
      pressKey(textarea, "f", { ctrlKey: true });
    });
    await act(async () => {
      typeIntoInput(findInput(rendered), "deploy");
    });
    await flushDebounce();
    // 命中行打淡标记（行 DOM 在虚拟窗口内才存在；至少输入行自身已挂载）。
    await act(async () => {
      pressKey(findInput(rendered), "Escape");
    });
    expect(findBar(rendered)).toBeNull();
    const marked = rendered.querySelectorAll('[data-conversation-find-match="true"]');
    expect(marked.length).toBe(0);
  });

  it("does not hijack Ctrl+F pressed inside inputs outside the conversation surface", async () => {
    const rendered = await renderFindHarness({
      messages: [userMessage("u1", "deploy the service")],
    });
    const outside = document.createElement("input");
    document.body.appendChild(outside);
    outside.focus();
    await act(async () => {
      pressKey(outside, "f", { ctrlKey: true });
    });
    expect(findBar(rendered)).toBeNull();
    outside.remove();

    // 会话视图 surface 根容器内的 Ctrl+F 正常打开（surface 对自身 contains 成立）。
    const surface = rendered.firstElementChild as HTMLElement | null;
    if (!surface) {
      throw new Error("conversation surface not mounted");
    }
    await act(async () => {
      pressKey(surface, "f", { ctrlKey: true });
    });
    expect(findBar(rendered)).not.toBeNull();
  });
});
