/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { VuiProvider } from "../../components/vui";
import { ChallengeCupSingleActionPreviewApp } from "./index";
import { ACTION_SCENES, type ActionSceneId, type GuardStateId } from "./model";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("Challenge Cup single-action preview", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(async () => {
    if (root) await act(async () => root?.unmount());
    container?.remove();
    root = null;
    container = null;
  });

  async function mountPreview(scene: ActionSceneId, guard: GuardStateId = "ready") {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <VuiProvider>
          <ChallengeCupSingleActionPreviewApp initialSceneId={scene} initialGuard={guard} />
        </VuiProvider>,
      );
    });
    return container;
  }

  function inspector(host: HTMLElement) {
    return host.querySelector('[data-testid="current-task-inspector"]') as HTMLElement;
  }

  function buttonByText(host: HTMLElement, text: string) {
    return Array.from(host.querySelectorAll("button")).find((button) => button.textContent?.trim() === text);
  }

  it("defines the six review states requested for the preview", () => {
    expect(ACTION_SCENES.map((scene) => scene.id)).toEqual([
      "not_started",
      "awaiting_confirmation",
      "running",
      "recoverable",
      "blocked",
      "history",
    ]);
  });

  it.each([
    ["not_started", "开始实验", 1],
    ["awaiting_confirmation", "确认并继续", 1],
    ["running", "", 0],
    ["recoverable", "重试搜集", 1],
    ["blocked", "", 0],
    ["history", "返回当前任务", 1],
  ] as const)("keeps %s at zero or one footer action", async (sceneId, label, actionCount) => {
    const host = await mountPreview(sceneId);
    const task = inspector(host);
    expect(task.querySelectorAll('[data-footer-action="true"]')).toHaveLength(actionCount);
    expect(task.querySelector("footer")?.getAttribute("data-action-count")).toBe(String(actionCount));
    if (label) expect(task.textContent).toContain(label);
  });

  it("shows launch settings as a disclosure without adding a second footer action", async () => {
    const host = await mountPreview("not_started");
    const task = inspector(host);
    expect(task.textContent).toContain("选择研究题目");
    expect(task.textContent).not.toContain("Token 上限");
    expect(task.textContent).not.toContain("取消");
    await act(async () => buttonByText(task, "调整上限")?.click());
    expect(task.textContent).toContain("Token 上限");
    expect(task.querySelectorAll('[data-footer-action="true"]')).toHaveLength(1);
  });

  it("renders recovery from the formal snapshot and never leaks the launch form", async () => {
    const host = await mountPreview("recoverable");
    const task = inspector(host);
    expect(task.textContent).toContain("重试搜集");
    expect(task.textContent).toContain("5 条证据已保留");
    expect(task.textContent).not.toContain("选择研究题目");
    expect(task.textContent).not.toContain("开始实验");
    expect(task.querySelectorAll('[data-progress-action="true"]')).toHaveLength(1);
  });

  it.each(["loading", "scope_mismatch"] as const)("hides stale actions while guard=%s", async (guard) => {
    const host = await mountPreview("recoverable", guard);
    const task = inspector(host);
    expect(task.querySelectorAll('[data-footer-action="true"]')).toHaveLength(0);
    expect(task.textContent).not.toContain("重试搜集");
    expect(task.textContent).not.toContain("开始实验");
    expect(task.textContent).toContain("操作已隐藏");
  });

  it("keeps history read-only and returns to the authoritative current task", async () => {
    const host = await mountPreview("history");
    const task = inspector(host);
    expect(task.textContent).toContain("历史节点只读");
    expect(task.textContent).not.toContain("重试搜集");
    await act(async () => buttonByText(task, "返回当前任务")?.click());
    const currentTask = inspector(host);
    expect(currentTask.textContent).toContain("资料补充需要处理");
    expect(currentTask.textContent).toContain("重试搜集");
  });
});
