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

  it("explains the three Stage 1 surfaces from the server projection", async () => {
    const { container, root } = await render(
      <ResearchCurrentTaskInspector
        context={context()}
        stageOne={{
          authority: "challenge_program",
          completionState: "pending",
          formalTopology: {
            workflowId: "challenge-cup-research",
            workflowVersionId: "challenge-cup-research-v3.0.0",
            definitionResolution: "pinned",
            role: "execution_authority",
          },
          hypothesisView: { nodePrefix: "hf_", role: "operator_projection" },
          knowledgeFlow: {
            topology: "child_workflow",
            rolloutMode: "on",
            role: "optional_child_workflow",
          },
        }}
      />,
    );

    const summary = container.querySelector('[data-testid="stage-one-topology-summary"]');
    expect(summary?.textContent).toContain("正式执行图 challenge-cup-research-v3.0.0");
    expect(summary?.textContent).toContain("hf_* 仅为操作投影");
    expect(summary?.textContent).toContain("知识补充为独立子流程");
    expect(summary?.textContent).toContain("Challenge Program 登记为准");

    await act(async () => root.unmount());
  });

  it("keeps header, body, and footer regions mounted while the task is loading", async () => {
    const loading = context();
    loading.currentTask = null;
    loading.loadState = "loading";
    const { container, root } = await render(
      <ResearchCurrentTaskInspector context={loading}>
        <div>启动流程</div>
      </ResearchCurrentTaskInspector>,
    );

    expect(container.querySelector('[data-vui-region="current-task-header"]')).not.toBeNull();
    expect(container.querySelector('[data-vui-region="current-task-body"]')?.textContent).toContain("启动流程");
    expect(container.querySelector('[data-vui-region="current-task-action"]')).not.toBeNull();

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
    expect(container.textContent).toContain("归档记录 · 当前仍是“本轮评审正在整理”");
    expect(container.textContent).not.toContain("历史回顾 · 只读");
    expect(container.textContent).not.toContain("不应显示的写操作");
    expect(container.querySelector('[data-vui-region="current-task-action"]')?.textContent)
      .toBe("返回当前任务");
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

  it("announces dispatch failure assertively and exposes a retry action", async () => {
    const failed = context();
    failed.currentTask = {
      ...failed.currentTask!,
      status: "failed_to_dispatch",
      title: "运行启动失败",
      detail: "运行在派发节点尝试前失败（dispatch_never_started），可以重试启动。",
      commandAction: null,
      retryAction: { label: "重试启动" },
    };
    const onRetry = vi.fn();
    const { container, root } = await render(
      <ResearchCurrentTaskInspector
        context={failed}
        onRetryDispatch={onRetry}
      />,
    );

    expect(container.querySelector('[data-task-status="failed_to_dispatch"]')).not.toBeNull();
    const detail = container.querySelector('[aria-live="assertive"]');
    expect(detail?.getAttribute("role")).toBe("alert");
    expect(detail?.textContent).toContain("dispatch_never_started");
    const retry = Array.from(container.querySelectorAll("button")).find((button) => (
      button.textContent?.includes("重试启动")
    ));
    expect(retry).not.toBeUndefined();
    await act(async () => retry?.click());
    expect(onRetry).toHaveBeenCalledTimes(1);

    await act(async () => root.unmount());
  });
});
