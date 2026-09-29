/** @vitest-environment happy-dom */
import React, { act, createRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ConversationFindBar, type ConversationFindBarLabels } from "./ConversationFindBar";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const labels: ConversationFindBarLabels = {
  title: "在对话中查找",
  placeholder: "查找用户、回答与思考…",
  matchCountAria: (current, total) => `命中 ${current} / 共 ${total}`,
  previous: "上一个命中",
  next: "下一个命中",
  close: "关闭查找（Esc）",
};

describe("ConversationFindBar", () => {
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

  async function renderBar(props: Partial<Parameters<typeof ConversationFindBar>[0]> = {}) {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <ConversationFindBar
          labels={labels}
          value=""
          onValueChange={() => undefined}
          matchCount={0}
          activeIndex={-1}
          onPrevious={() => undefined}
          onNext={() => undefined}
          onClose={() => undefined}
          {...props}
        />,
      );
    });
    return container;
  }

  function pressKey(input: HTMLInputElement, key: string, options: KeyboardEventInit = {}) {
    input.dispatchEvent(new KeyboardEvent("keydown", {
      key,
      bubbles: true,
      cancelable: true,
      ...options,
    }));
  }

  it("shows 0/0 on zero matches and keeps the input enabled", async () => {
    const rendered = await renderBar({ value: "不存在的词" });
    const count = rendered.querySelector('[data-conversation-find-count="true"]');
    expect(count?.textContent).toBe("0/0");
    const input = rendered.querySelector<HTMLInputElement>('input[data-conversation-find-input="true"]');
    expect(input).not.toBeNull();
    expect(input?.disabled).toBe(false);
    expect(input?.getAttribute("placeholder")).toBe(labels.placeholder);
    expect(rendered.querySelector('[data-conversation-find-previous="true"]')?.hasAttribute("disabled")).toBe(true);
    expect(rendered.querySelector('[data-conversation-find-next="true"]')?.hasAttribute("disabled")).toBe(true);
  });

  it("shows the one-based current position and total", async () => {
    const rendered = await renderBar({ matchCount: 5, activeIndex: 1 });
    expect(rendered.querySelector('[data-conversation-find-count="true"]')?.textContent).toBe("2/5");
    expect(rendered.querySelector('[data-conversation-find-count="true"]')?.getAttribute("aria-label"))
      .toBe("命中 2 / 共 5");
    expect(rendered.querySelector('[data-conversation-find-previous="true"]')?.hasAttribute("disabled")).toBe(false);
    expect(rendered.querySelector('[data-conversation-find-next="true"]')?.hasAttribute("disabled")).toBe(false);
  });

  it("navigates with Enter / Shift+Enter and closes with Escape", async () => {
    const onPrevious = vi.fn();
    const onNext = vi.fn();
    const onClose = vi.fn();
    const rendered = await renderBar({ onPrevious, onNext, onClose });
    const input = rendered.querySelector<HTMLInputElement>('input[data-conversation-find-input="true"]');
    if (!input) {
      throw new Error("find input not mounted");
    }

    await act(async () => {
      pressKey(input, "Enter");
    });
    expect(onNext).toHaveBeenCalledTimes(1);
    expect(onPrevious).not.toHaveBeenCalled();

    await act(async () => {
      pressKey(input, "Enter", { shiftKey: true });
    });
    expect(onPrevious).toHaveBeenCalledTimes(1);

    await act(async () => {
      const event = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
      input.dispatchEvent(event);
    });
    expect(onClose).toHaveBeenCalledTimes(1);

    // IME 组合中的 Enter/Escape 不触发导航/关闭。
    await act(async () => {
      pressKey(input, "Enter", { isComposing: true });
      pressKey(input, "Escape", { isComposing: true });
    });
    expect(onNext).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("reports typed values through onValueChange and forwards the input ref", async () => {
    const onValueChange = vi.fn();
    const inputRef = createRef<HTMLInputElement>();
    const rendered = await renderBar({ onValueChange, inputRef });
    const input = rendered.querySelector<HTMLInputElement>('input[data-conversation-find-input="true"]');
    if (!input) {
      throw new Error("find input not mounted");
    }
    expect(inputRef.current).toBe(input);
    // 受控输入必须走原型原生 setter：直接赋值会同步 React 的值跟踪器，
    // 让随后的 input 事件被去重、onChange 不触发。
    const nativeValueSetter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )?.set;
    nativeValueSetter?.call(input, "needle");
    await act(async () => {
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    // VInput 走受控 onChange：happy-dom 里 input 事件触发 React onChange。
    expect(onValueChange).toHaveBeenCalledWith("needle");
  });
});
