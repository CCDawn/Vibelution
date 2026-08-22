/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { VuiProvider } from "../components/vui";
import { AgentManagementFocusPreviewApp } from "./agent-management-focus-preview";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("agent management focus preview", () => {
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
          <AgentManagementFocusPreviewApp />
        </VuiProvider>,
      );
    });
    return container;
  }

  function tabButtons(host: HTMLElement): HTMLButtonElement[] {
    return Array.from(host.querySelectorAll<HTMLButtonElement>('[data-vui="primary-tabs"] button'));
  }

  function activateTab(host: HTMLElement, label: string) {
    const trigger = tabButtons(host).find((button) => button.textContent === label);
    if (!trigger) throw new Error(`tab trigger not found: ${label}`);
    trigger.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0, ctrlKey: false }));
  }

  it("switches among the three primary detail views (概览 / 配置 / 活动)", async () => {
    const host = await mountPreview();

    const labels = tabButtons(host).map((button) => button.textContent);
    expect(labels).toEqual(["概览", "配置", "活动"]);
    expect(host.textContent).toContain("有效配置");
    expect(host.textContent).toContain("身份与团队");
    expect(host.textContent).toContain("需要关注");
    expect(host.textContent).toContain("最近活动");
    expect(host.textContent).toContain("运行健康");
    expect(host.textContent).toContain("知识库");
    expect(host.textContent).toContain("Guardrail");
    expect(host.textContent).toContain("记忆清理");

    await act(async () => {
      activateTab(host, "配置");
    });
    expect(host.textContent).toContain("基础信息");
    expect(host.textContent).toContain("角色与提示词");
    expect(host.textContent).toContain("能力与权限");
    expect(host.textContent).toContain("高级设置");

    await act(async () => {
      activateTab(host, "活动");
    });
    expect(host.textContent).toContain("证据提取");
  });

  it("hides row checkboxes by default and reveals them only in bulk mode", async () => {
    const host = await mountPreview();

    const directory = host.querySelector<HTMLElement>('[aria-label="Agent 目录"]');
    expect(directory).toBeTruthy();
    const checkboxSelector = '[data-vui="checkbox"]';
    expect(directory?.querySelectorAll(checkboxSelector).length).toBe(0);

    await act(async () => {
      const bulkButton = Array.from(host.querySelectorAll("button")).find(
        (button) => button.textContent === "批量管理",
      );
      bulkButton?.click();
    });

    expect(directory?.querySelectorAll(checkboxSelector).length).toBeGreaterThan(0);
    expect(host.textContent).toContain("批量管理");

    await act(async () => {
      const exitButton = Array.from(host.querySelectorAll("button")).find(
        (button) => button.textContent === "退出批量管理",
      );
      exitButton?.click();
    });
    expect(directory?.querySelectorAll(checkboxSelector).length).toBe(0);
  });

  it("creates an unsaved state when editing config and discards it via 放弃", async () => {
    const host = await mountPreview();

    await act(async () => {
      activateTab(host, "配置");
    });

    expect(host.querySelector('[data-testid="unsaved-bar"]')).toBeNull();

    const nameInput = host.querySelector<HTMLInputElement>('input[aria-label="名称"]');
    expect(nameInput).toBeTruthy();
    const proto = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
    await act(async () => {
      proto?.set?.call(nameInput, "资料入库 v2");
      nameInput!.dispatchEvent(new Event("input", { bubbles: true }));
    });

    const unsavedBar = host.querySelector('[data-testid="unsaved-bar"]');
    expect(unsavedBar).toBeTruthy();
    expect(unsavedBar?.textContent).toContain("未保存变更 1 处");
    expect(host.textContent).toContain("放弃");
    expect(host.textContent).toContain("审查并保存");

    await act(async () => {
      const discardButton = Array.from(host.querySelectorAll("button")).find(
        (button) => button.textContent === "放弃",
      );
      discardButton?.click();
    });

    expect(host.querySelector('[data-testid="unsaved-bar"]')).toBeNull();
  });

  it("switching agents syncs the entity header without a false unsaved state", async () => {
    const host = await mountPreview();

    const directory = host.querySelector<HTMLElement>('[aria-label="Agent 目录"]');
    const finderButton = Array.from(directory?.querySelectorAll("button") ?? []).find(
      (button) => button.textContent?.includes("白望舒"),
    );
    expect(finderButton).toBeTruthy();
    await act(async () => {
      finderButton?.click();
    });

    const header = host.querySelector('[data-vui="route-header"]');
    expect(header?.querySelector("h1")?.textContent).toBe("白望舒");
    expect(header?.textContent).toContain("source_finder");
    expect(header?.textContent).toContain("挑战杯科研");
    expect(host.textContent).not.toContain("Agent 管理 · 预览");
    expect(host.textContent).toContain("deepseek-v3");
    expect(host.querySelector('[data-testid="unsaved-bar"]')).toBeNull();

    await act(async () => {
      activateTab(host, "配置");
    });
    const nameInput = host.querySelector<HTMLInputElement>('input[aria-label="名称"]');
    expect(nameInput).toBeTruthy();
    const proto = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
    await act(async () => {
      proto?.set?.call(nameInput, "白望舒 v2");
      nameInput!.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(host.querySelector('[data-testid="unsaved-bar"]')?.textContent).toContain("未保存变更 1 处");

    await act(async () => {
      const discardButton = Array.from(host.querySelectorAll("button")).find(
        (button) => button.textContent === "放弃",
      );
      discardButton?.click();
    });
    expect(host.querySelector('[data-testid="unsaved-bar"]')).toBeNull();
  });

  it("opens and closes the single test drawer", async () => {
    const host = await mountPreview();

    expect(host.textContent).toContain("测试");

    await act(async () => {
      const testButton = Array.from(host.querySelectorAll("button")).find(
        (button) => button.textContent === "测试",
      );
      testButton?.click();
    });

    expect(host.textContent).toContain("Mock 测试控件");
    expect(host.textContent).toContain("运行 Mock");

    await act(async () => {
      const closeButton = Array.from(host.querySelectorAll("button")).find(
        (button) => button.getAttribute("aria-label") === "关闭",
      );
      closeButton?.click();
    });

    expect(host.textContent).not.toContain("Mock 测试控件");
  });

  it("reuses the single drawer for change review without a second inspector", async () => {
    const host = await mountPreview();

    await act(async () => {
      activateTab(host, "配置");
    });
    const nameInput = host.querySelector<HTMLInputElement>('input[aria-label="名称"]');
    const proto = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
    await act(async () => {
      proto?.set?.call(nameInput, "资料入库 v2");
      nameInput!.dispatchEvent(new Event("input", { bubbles: true }));
    });

    await act(async () => {
      const reviewButton = Array.from(host.querySelectorAll("button")).find(
        (button) => button.textContent === "审查并保存",
      );
      reviewButton?.click();
    });

    expect(host.textContent).toContain("审查并保存");
    expect(host.textContent).toContain("待确认变更");
    const openInspectors = host.querySelectorAll('[aria-label="测试面板"], [aria-label="变更审查"]');
    expect(openInspectors.length).toBe(1);
  });
});
