/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ControlsPreview } from "../../preview/frontend-ux-polish/ControlsPreview";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("frontend UX controls preview", () => {
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
    vi.unstubAllGlobals();
  });

  it("shows the Agent model read-only while thinking remains adjustable locally", async () => {
    const fetch = vi.fn(async () => new Response("{}", { status: 403 }));
    vi.stubGlobal("fetch", fetch);
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<ControlsPreview />);
    });

    expect(container.textContent).toContain("所选范围可调用");
    expect(container.textContent).toContain("125");
    expect(container.textContent).toContain("明确允许：0");
    expect(container.textContent).toContain("不是全局注册总数");
    expect(container.querySelector('button[aria-label="思考强度: 高"]')).not.toBeNull();
    expect(container.querySelector('[aria-label="Agent 模型: Luna 5.6"]')).not.toBeNull();
    expect(container.querySelector('button[aria-label="模型: Luna 5.6"]')).toBeNull();
    expect(fetch).not.toHaveBeenCalled();

    const effortTrigger = container.querySelector<HTMLButtonElement>('button[aria-label="思考强度: 高"]');
    await act(async () => {
      effortTrigger?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const lowerEffortOption = Array.from(document.body.querySelectorAll<HTMLButtonElement>('[role="option"]'))
      .find((option) => option.textContent?.includes("低"));
    expect(lowerEffortOption).toBeDefined();
    await act(async () => {
      lowerEffortOption?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(container.querySelector('button[aria-label="思考强度: 低"]')).not.toBeNull();

    const modelDisplay = container.querySelector<HTMLElement>('[aria-label="Agent 模型: Luna 5.6"]');
    await act(async () => {
      modelDisplay?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(document.body.querySelector('[data-vui="conversation-turn-model-menu"]')).toBeNull();
    expect(container.querySelector('[aria-label="Agent 模型: Luna 5.6"]')).not.toBeNull();
    expect(container.querySelector('button[aria-label="思考强度: 低"]')).not.toBeNull();
    expect(fetch).not.toHaveBeenCalled();
  });
});
