/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { TeamResearchProjectAgentTask } from "../../../api/types";
import { ResearchProjectAgentTaskPanel } from "./ResearchProjectAgentTaskPanel";
import panelSource from "./ResearchProjectAgentTaskPanel.tsx?raw";

function task(overrides: Partial<TeamResearchProjectAgentTask> = {}): TeamResearchProjectAgentTask {
  return {
    schemaVersion: 1,
    taskId: "task-design",
    idempotencyKey: "key-design",
    taskKind: "experiment_design",
    taskTitle: "设计可执行实验方案",
    teamId: "team-a",
    researchProjectId: "project-a",
    experimentName: "神经预测编码实验",
    targetRef: "",
    agentId: "agent-planner",
    teamRole: "experiment_planner",
    roleKey: "challenge_cup_experiment_planner",
    roleLabel: "实验规划",
    sessionId: "session-design",
    sessionTitle: "神经预测编码实验｜实验规划",
    sessionAttempt: 1,
    sessionCreated: true,
    retryOfSessionId: "",
    retrySourceTaskId: "",
    formalRetry: false,
    status: "running",
    turn: {
      accepted: true,
      turnId: "turn-design",
      status: "accepted",
      acceptedAt: "2026-07-27T00:00:00Z",
    },
    resultRefs: [],
    failureCode: "",
    returnTo: "/teams?team=team-a",
    returnLabel: "返回实验设计",
    createdAt: "2026-07-27T00:00:00Z",
    updatedAt: "2026-07-27T00:00:00Z",
    chatRoute: "/chat?session=session-design",
    ...overrides,
  };
}

describe("ResearchProjectAgentTaskPanel", () => {
  it("shows a compact responsibility, status, and action row while session detail is hover-only", () => {
    const markup = renderToStaticMarkup(
      <ResearchProjectAgentTaskPanel
        stage="experiment"
        activeProjectId="project-a"
        tasks={[task()]}
        isLoading={false}
        isStarting={false}
        onStartTask={async () => undefined}
      />,
    );

    expect(markup).toContain("实验规划");
    expect(markup).toContain("运行中");
    expect(markup).toContain('data-vui="status-chip"');
    expect(markup).toContain('data-tone="accent"');
    expect(markup).toContain("继续会话");
    expect(markup).toContain("实验证据");
    expect(markup).not.toContain("神经预测编码实验｜实验规划");
    expect(markup).not.toContain("第 1 次");
    expect(panelSource).toContain("VTooltip");
    expect(panelSource).not.toContain("description:");
    expect(panelSource).not.toContain('status === "completed") return "success"');
  });

  it("only exposes a formal retry for a terminal failed task", () => {
    const failedMarkup = renderToStaticMarkup(
      <ResearchProjectAgentTaskPanel
        stage="experiment"
        activeProjectId="project-a"
        tasks={[task({ status: "failed", failureCode: "turn_submit_error" })]}
        isLoading={false}
        isStarting={false}
        onStartTask={async () => undefined}
      />,
    );
    const runningMarkup = renderToStaticMarkup(
      <ResearchProjectAgentTaskPanel
        stage="experiment"
        activeProjectId="project-a"
        tasks={[task()]}
        isLoading={false}
        isStarting={false}
        onStartTask={async () => undefined}
      />,
    );

    expect(failedMarkup).toContain("正式重试");
    expect(runningMarkup).not.toContain("正式重试");
    expect(panelSource).toContain("retryTaskId");
    expect(panelSource).toContain("formalRetry: true");
    expect(panelSource).toContain("VStatusChip");
  });

  it("keeps Stage 3 responsibilities separate and blocks starts without an active project", () => {
    const markup = renderToStaticMarkup(
      <ResearchProjectAgentTaskPanel
        stage="iteration"
        activeProjectId=""
        tasks={[]}
        isLoading={false}
        isStarting={false}
        onStartTask={async () => undefined}
      />,
    );

    expect(markup).toContain("迭代决策");
    expect(markup).toContain("版本治理");
    expect(markup).toContain("请先选择研究项目");
    expect(markup).toContain("disabled");
  });

  it("surfaces an inline error when starting a task fails instead of swallowing it", async () => {
    expect(panelSource).not.toContain(".catch(() => undefined)");

    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(
        <ResearchProjectAgentTaskPanel
          stage="experiment"
          activeProjectId="project-a"
          tasks={[]}
          isLoading={false}
          isStarting={false}
          onStartTask={async () => {
            throw new Error("backend unavailable");
          }}
        />,
      );
    });

    const startButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent?.includes("启动任务"));
    expect(startButton).toBeTruthy();
    await act(async () => {
      startButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain("操作未完成");

    await act(async () => {
      root.unmount();
    });
    container.remove();
  });
});
