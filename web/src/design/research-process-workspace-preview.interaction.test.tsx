/** @vitest-environment happy-dom */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { VuiProvider } from "../components/vui";
import { ResearchProcessWorkspacePreviewApp } from "./research-process-workspace-preview";
import { PREVIEW_SCENES, sceneById } from "./researchProcessWorkspacePreviewModel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("research workflow three-pane preview", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(async () => {
    if (root) await act(async () => root?.unmount());
    container?.remove();
    document.body.style.overflow = "";
    root = null;
    container = null;
  });

  async function mountPreview(props: React.ComponentProps<typeof ResearchProcessWorkspacePreviewApp> = {}) {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(<VuiProvider><ResearchProcessWorkspacePreviewApp {...props} /></VuiProvider>);
    });
    return container;
  }

  function buttonByText(host: HTMLElement, text: string) {
    return Array.from(host.querySelectorAll("button")).find((button) => button.textContent?.trim() === text);
  }

  it("keeps the product Tailwind utility entry in the preview import chain", () => {
    const source = readFileSync(resolve(import.meta.dirname, "research-process-workspace-preview.tsx"), "utf8");
    const tokens = source.indexOf('"./tokens.css"');
    const tailwind = source.indexOf('"./tailwind.css"');
    const provider = source.indexOf('"./vui-provider-theme.css"');
    expect(tokens).toBeGreaterThan(-1);
    expect(tailwind).toBeGreaterThan(tokens);
    expect(provider).toBeGreaterThan(tailwind);
  });

  it("renders rail, canvas and current-task inspector from one scene", async () => {
    const host = await mountPreview();
    expect(host.querySelector('[data-testid="stage-rail"]')).toBeTruthy();
    expect(host.querySelector('[data-testid="workflow-canvas"]')).toBeTruthy();
    expect(host.querySelector('[data-testid="task-inspector"]')).toBeTruthy();
    expect(host.querySelector('[data-testid="workflow-node-hf_meeting"]')?.getAttribute("data-current")).toBe("true");
    expect(host.textContent).toContain("第 1 轮评审正在整理");
    expect(host.textContent).toContain("这就是原来的“正在生成纪要”");
  });

  it("covers every preview gate state with an explicit explanation", () => {
    const ids = PREVIEW_SCENES.map((scene) => scene.id);
    expect(ids).toEqual(expect.arrayContaining([
      "generation", "candidate_approval", "selection", "review_processing",
      "review_approval", "collection", "recovery", "blocked", "archive",
    ]));
    for (const scene of PREVIEW_SCENES) {
      expect(scene.title.trim()).not.toBe("");
      expect(scene.summary.trim()).not.toBe("");
      expect(scene.nextExpectation.trim()).not.toBe("");
    }
  });

  it("keeps currentTask separate while a historical node is selected", async () => {
    const host = await mountPreview({ initialSceneId: "review_approval" });
    const historyNode = host.querySelector('[data-testid="workflow-node-question"]') as HTMLButtonElement;
    await act(async () => historyNode.click());
    expect(historyNode.getAttribute("data-selected")).toBe("true");
    expect(host.querySelector('[data-testid="workflow-node-hf_meeting"]')?.getAttribute("data-current")).toBe("true");
    expect(host.querySelector('[data-testid="task-inspector"]')?.textContent).toContain("历史回顾 · 只读");
    expect(host.querySelector('[data-testid="task-inspector"]')?.textContent).not.toContain("确认并结束本轮");

    await act(async () => buttonByText(host, "返回当前任务")?.click());
    expect(host.querySelector('[data-testid="task-inspector"]')?.textContent).toContain("当前任务 · 唯一操作面");
    expect(host.querySelector('[data-testid="task-inspector"]')?.textContent).toContain("确认并结束本轮");
  });

  it("opens responsive drawers and returns focus after Escape", async () => {
    const host = await mountPreview({ initialViewport: "compact" });
    const trigger = buttonByText(host, "当前任务") as HTMLButtonElement;
    await act(async () => trigger.click());
    expect(host.querySelector('[data-testid="inspector-drawer"]')).toBeTruthy();
    expect(host.querySelector('[role="dialog"]')?.getAttribute("aria-modal")).toBe("true");
    expect(document.body.style.overflow).toBe("hidden");
    await act(async () => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
    expect(host.querySelector('[data-testid="inspector-drawer"]')).toBeNull();
    expect(document.activeElement).toBe(trigger);
    expect(document.body.style.overflow).toBe("");
  });

  it("keeps the selection CTA disabled with a machine-readable reason when empty", async () => {
    const host = await mountPreview({ initialSceneId: "selection" });
    const checkboxes = Array.from(host.querySelectorAll('[aria-label^="选择假说"]')) as HTMLButtonElement[];
    expect(checkboxes).toHaveLength(3);
    for (const checkbox of checkboxes) await act(async () => checkbox.click());
    const submit = buttonByText(host, "记录选择并开启评审") as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    expect(sceneById("selection").disabledReason).toBe("至少选择 1 条假说后才能开启评审");
    expect(submit.outerHTML).toContain("disabled");
  });

  it("uses a wide archive surface without mounting a narrow task inspector", async () => {
    const host = await mountPreview({ initialSceneId: "archive" });
    expect(host.querySelector('[data-testid="research-archive"]')).toBeTruthy();
    expect(host.querySelector('[data-testid="task-inspector"]')).toBeNull();
    expect(host.textContent).toContain("题目、假说版本、评审结论、证据来源和交接记录");
  });
});
