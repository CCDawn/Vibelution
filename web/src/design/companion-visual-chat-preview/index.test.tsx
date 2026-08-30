/** @vitest-environment happy-dom */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { VuiProvider } from "../../components/vui";
import { CompanionVisualChatPreviewApp } from "./index";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function setNativeValue(element: HTMLTextAreaElement, value: string) {
  const descriptor = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value");
  descriptor?.set?.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("companion visual chat preview", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => root?.unmount());
    }
    container?.remove();
    root = null;
    container = null;
  });

  async function mountPreview() {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <VuiProvider>
          <CompanionVisualChatPreviewApp />
        </VuiProvider>,
      );
    });
    return container;
  }

  it("keeps production conversation plumbing out of the isolated preview", () => {
    const source = readFileSync(resolve(import.meta.dirname, "index.tsx"), "utf8");
    expect(source).not.toContain("ConversationStore");
    expect(source).not.toContain("EventSource");
    expect(source).not.toContain("fetchVirtualHuman");
    expect(source).not.toContain("完全访问权限");
    expect(source).not.toContain("Qwen");
    expect(source).not.toContain("Token");
  });

  it("shows one companion-only typing row with the person avatar", async () => {
    const host = await mountPreview();
    expect(host.querySelectorAll('[data-testid="companion-typing-row"]').length).toBe(0);
    const typingButton = Array.from(host.querySelectorAll("button")).find((button) => button.textContent === "正在输入");
    await act(async () => typingButton?.click());
    const typingRows = host.querySelectorAll('[data-testid="companion-typing-row"]');
    expect(typingRows.length).toBe(1);
    expect(typingRows[0].textContent).toContain("正在输入…");
    expect(typingRows[0].querySelector('img[alt="洛天依"]')).toBeTruthy();
  });

  it("switches the visual life snapshot between now, today, and memory", async () => {
    const host = await mountPreview();
    expect(host.querySelector('[data-testid="life-panel-now"]')).toBeTruthy();
    const today = Array.from(host.querySelectorAll<HTMLButtonElement>('[role="tab"]')).find((button) => button.textContent?.trim() === "今天");
    expect(today).toBeTruthy();
    await act(async () => today?.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
    expect(host.querySelector('[data-testid="life-panel-today"]')?.textContent).toContain("晨间练声");
    const memory = Array.from(host.querySelectorAll<HTMLButtonElement>('[role="tab"]')).find((button) => button.textContent?.trim() === "记忆");
    expect(memory).toBeTruthy();
    await act(async () => memory?.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
    expect(host.querySelector('[data-testid="life-panel-memory"]')?.textContent).toContain("一起挑中的旧唱片");
  });

  it("collapses the dense life rail into a visual shortcut strip", async () => {
    const host = await mountPreview();
    const collapse = host.querySelector<HTMLButtonElement>('button[aria-label="收起生活快照"]');
    await act(async () => collapse?.click());
    expect(host.querySelector('aside[aria-label="生活快照已收起"]')).toBeTruthy();
    expect(host.querySelector('button[aria-label="查看记忆"]')).toBeTruthy();
    expect(host.querySelector('[data-testid="life-panel-now"]')).toBeNull();
  });

  it("lets a user send while the companion is active and moves to typing", async () => {
    const host = await mountPreview();
    const textarea = host.querySelector<HTMLTextAreaElement>('textarea[aria-label="发送消息"]');
    expect(textarea).toBeTruthy();
    await act(async () => {
      setNativeValue(textarea!, "等雨小一点，我们再聊。\n");
      textarea!.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    });
    expect(host.textContent).toContain("等雨小一点，我们再聊。");
    expect(host.querySelectorAll('[data-testid="companion-typing-row"]').length).toBe(1);
  });
});
