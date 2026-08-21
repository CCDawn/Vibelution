/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ResearchCurrentTaskInspector } from "./ResearchCurrentTaskInspector";
import type { ResearchWorkflowContext } from "./researchWorkflowContextModel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function context(overrides: Partial<ResearchWorkflowContext["view"]> = {}): ResearchWorkflowContext {
  return {
    scope: {
      key: "research-team::challenge-cup-research::SCI-004::run-4",
      teamId: "research-team",
      workflowId: "challenge-cup-research",
      questionId: "SCI-004",
      runId: "run-4",
      runVersion: 1,
    },
    loadState: "ready",
    currentTask: {
      key: "task-1",
      stage: "hypothesis_first",
      step: "review",
      status: "waiting_system",
      title: "本轮评审正在整理",
      detail: "系统正在把讨论整理成保留结论、反对意见和证据缺口；完成后需要你确认。",
      targetNodeId: "hf_meeting_1",
      navigationAction: { targetNodeId: "hf_meeting_1", label: "查看评审讨论" },
      commandAction: null,
      authority: "hypothesis_first",
    },
    stages: [],
    view: {
      panel: "node",
      selectedNodeId: "hf_meeting_1",
      selectedIsCurrentTask: true,
      archiveMode: false,
      ...overrides,
    },
  };
}

async function render(ui: React.ReactElement) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => root.render(ui));
  return { container, root };
}

describe("ResearchCurrentTaskInspector", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("keeps the current command outside the scrollable body", async () => {
    const { container, root } = await render(
      <ResearchCurrentTaskInspector context={context()} footer={<button type="button">确认并结束本轮</button>}>
        <div>评审内容</div>
      </ResearchCurrentTaskInspector>,
    );

    expect(container.querySelector('[data-vui-region="current-task-body"]')?.textContent).toContain("评审内容");
    expect(container.querySelector('[data-vui-region="current-task-action"]')?.textContent).toContain("确认并结束本轮");
    expect(container.querySelector('[role="status"]')?.textContent).toContain("保留结论、反对意见和证据缺口");

    await act(async () => root.unmount());
  });

  it("makes a selected history node read-only and returns focus ownership to the current task", async () => {
    const onReturn = vi.fn();
    const { container, root } = await render(
      <ResearchCurrentTaskInspector
        context={context({ selectedNodeId: "hf_generation", selectedIsCurrentTask: false })}
        footer={<button type="button">不应显示的写操作</button>}
        onReturnCurrentTask={onReturn}
      >
        <div>历史内容</div>
      </ResearchCurrentTaskInspector>,
    );

    expect(container.querySelector('[data-history-mode="true"]')).not.toBeNull();
    expect(container.textContent).toContain("历史回顾 · 只读");
    expect(container.textContent).not.toContain("不应显示的写操作");
    const returnButton = Array.from(container.querySelectorAll("button")).find((button) => (
      button.textContent?.includes("返回当前任务")
    ));
    await act(async () => returnButton?.click());
    expect(onReturn).toHaveBeenCalledTimes(1);

    await act(async () => root.unmount());
  });

  it("announces stale-scope clearing without rendering an old task", async () => {
    const loading = context();
    loading.currentTask = null;
    loading.loadState = "scope_mismatch";
    const { container, root } = await render(<ResearchCurrentTaskInspector context={loading} />);

    expect(container.querySelector('[data-load-state="scope_mismatch"]')).not.toBeNull();
    expect(container.querySelector('[role="status"]')?.textContent).toBe("正在切换题目，旧任务已隐藏");

    await act(async () => root.unmount());
  });
});
