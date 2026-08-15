/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { VuiProvider } from "../components/vui";
import { ComposerFollowupQueuePreviewApp } from "./composer-followup-queue-preview";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function setNativeValue(element: HTMLTextAreaElement, value: string) {
  const proto = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value");
  proto?.set?.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("composer follow-up queue preview loop", () => {
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

  async function mountPreview() {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <VuiProvider>
          <ComposerFollowupQueuePreviewApp />
        </VuiProvider>,
      );
    });
    return container;
  }

  it("queues typed Enter, steers on empty Enter, and keeps that steer as its own user turn", async () => {
    const host = await mountPreview();
    const textarea = host.querySelector<HTMLTextAreaElement>('textarea[aria-label="发送消息"]');
    expect(textarea).toBeTruthy();

    await act(async () => {
      setNativeValue(textarea!, "先不要改测试，只汇报改了哪些文件。");
      textarea!.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    });

    expect(host.querySelector('[aria-label="待发送队列"]')?.textContent).toContain("排队 1");
    expect(host.querySelector('[aria-label="待发送队列"]')?.textContent).toContain("先不要改测试，只汇报改了哪些文件。");
    expect(Array.from(host.querySelectorAll("button")).some((button) => button.textContent === "立刻引导")).toBe(true);

    await act(async () => {
      textarea!.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    });

    const steerBadges = Array.from(host.querySelectorAll("span")).filter((node) => node.textContent === "引导");
    expect(steerBadges.length).toBe(1);
    expect(host.textContent).toContain("立刻引导，已新增独立消息");
    expect(host.querySelector('[aria-label="待发送队列"]')).toBeNull();
    expect(host.textContent).toContain("把登录页改成暗色，并补上失败提示。");
  });

  it("withdraws a queued item and flushes remaining items when the current turn ends", async () => {
    const host = await mountPreview();

    await act(async () => {
      const twoButton = Array.from(host.querySelectorAll("button")).find((button) => button.textContent === "已排队 2 条");
      twoButton?.click();
    });

    expect(host.textContent).toContain("排队 1");
    expect(host.textContent).toContain("排队 2");
    expect(host.textContent).toContain("登录失败时用中文提示，不要弹英文。");

    await act(async () => {
      const withdraw = host.querySelector<HTMLButtonElement>('button[aria-label="撤回这条排队"]');
      withdraw?.click();
    });

    const queueAfterWithdraw = host.querySelector('[aria-label="待发送队列"]');
    expect(host.textContent).toContain("已撤回：先不要改测试，只汇报改了哪些文件。");
    expect(queueAfterWithdraw?.textContent).toContain("排队 1");
    expect(queueAfterWithdraw?.textContent).not.toContain("排队 2");
    expect(queueAfterWithdraw?.textContent).toContain("登录失败时用中文提示，不要弹英文。");

    await act(async () => {
      const finish = Array.from(host.querySelectorAll("button")).find((button) => button.textContent === "结束当前轮");
      finish?.click();
    });

    expect(host.textContent).toContain("当前轮结束，自动发出 1 条普通用户消息");
    expect(host.querySelector('[aria-label="待发送队列"]')).toBeNull();
    expect(host.textContent).toContain("登录失败时用中文提示，不要弹英文。");
    expect(Array.from(host.querySelectorAll("span")).some((node) => node.textContent === "引导")).toBe(false);
  });

  it("edits a queued item in place before it is sent", async () => {
    const host = await mountPreview();

    await act(async () => {
      const oneButton = Array.from(host.querySelectorAll("button")).find((button) => button.textContent === "已排队 1 条");
      oneButton?.click();
    });

    await act(async () => {
      host.querySelector<HTMLButtonElement>('button[aria-label="修改这条排队"]')?.click();
    });
    const editor = host.querySelector<HTMLTextAreaElement>('textarea[aria-label="修改排队 1"]');
    expect(editor).toBeTruthy();

    await act(async () => {
      setNativeValue(editor!, "先不要改测试，只汇报改了哪些文件。");
      const save = Array.from(host.querySelectorAll("button")).find((button) => button.textContent === "保存");
      save?.click();
    });

    expect(host.textContent).toContain("已修改排队：先不要改测试，只汇报改了哪些文件。");
    expect(host.querySelector('[aria-label="待发送队列"]')?.textContent).toContain("先不要改测试，只汇报改了哪些文件。");
  });
});
