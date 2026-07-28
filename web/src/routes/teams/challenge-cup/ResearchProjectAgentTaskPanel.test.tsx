import React from "react";
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
  it("shows fixed Agent responsibility, flat session title, attempt, and active state", () => {
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
    expect(markup).toContain("神经预测编码实验｜实验规划");
    expect(markup).toContain("第 1 次");
    expect(markup).toContain("运行中");
    expect(markup).toContain("继续会话");
    expect(markup).toContain("实验证据");
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
});
