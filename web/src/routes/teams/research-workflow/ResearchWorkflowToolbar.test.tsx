import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../../api/queryKeys";
import type { ExperimentSwitchOption } from "./researchExperimentSwitchModel";
import { ResearchWorkflowToolbar, researchWorkflowPhase } from "./ResearchWorkflowToolbar";

function renderToolbar(props: React.ComponentProps<typeof ResearchWorkflowToolbar>, language: "zh" | "en" = "zh") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  queryClient.setQueryData(queryKeys.configPublic(), { language });
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ResearchWorkflowToolbar {...props} />
    </QueryClientProvider>,
  );
}

const EXPERIMENT: ExperimentSwitchOption = {
  questionId: "SCI-096",
  title: "What are the coding principles embedded in neuronal spike trains?",
  runId: "run-5e4fbe6e18f2",
  currentNodeId: "source_finding",
  label: "SCI-096 · 1 条假说待评审",
  description: "What are the coding principles embedded in neuronal spike trains?",
};

const BASE_PROPS = {
  identity: {
    questionId: "SCI-096",
    title: "What are the coding principles embedded in neuronal spike trains?",
    hypothesisSummary: "1 条假说待评审",
  },
  runId: "run-5e4fbe6e18f2",
  runStatus: "waiting_human",
  experimentOptions: [EXPERIMENT],
  panel: "node",
  onSelectExperiment: vi.fn(),
  onOpenPanel: vi.fn(),
} satisfies React.ComponentProps<typeof ResearchWorkflowToolbar>;

describe("ResearchWorkflowToolbar", () => {
  it("keeps experiment context and compact workspace actions in the visible toolbar", () => {
    const markup = renderToolbar({
      ...BASE_PROPS,
      navigationLabel: "前往确认候选",
      runtimeCurrentNodeIds: ["protocol_design"],
      onNavigateCurrent: vi.fn(),
      onOpenTeamCommunication: vi.fn(),
      experimentActions: <button type="button">更多操作</button>,
    });

    expect(markup).toContain("切换实验");
    expect(markup).toContain("SCI-096 · 1 条假说待评审");
    expect(markup).toContain(">查看<");
    expect(markup).toContain(">更多操作<");
    expect(markup).toContain(">协作<");
    expect(markup).toContain('data-testid="research-open-team-communication"');
    expect(markup).not.toContain('data-variant="primary"');

    for (const removedCopy of [
      "题目进度",
      "运行时间线",
      "实验设计 · 协议设计",
      "定位当前任务",
      "前往确认候选",
      "当前节点",
      "下一步",
      "waiting_human",
    ]) {
      expect(markup).not.toContain(removedCopy);
    }
    expect(markup).not.toContain('data-vui="tabs"');
    expect(markup).not.toContain('data-vui="research-workflow-phase"');
  });

  it("does not expose reset actions without a selected experiment", () => {
    const markup = renderToolbar({
      ...BASE_PROPS,
      identity: null,
      runId: "",
      experimentOptions: [],
      experimentActions: <button type="button">更多操作</button>,
    });

    expect(markup).not.toContain("更多操作");
  });

  it("stays read-only before a workflow starts", () => {
    const markup = renderToolbar({
      ...BASE_PROPS,
      runId: "",
      experimentOptions: [],
      identity: { ...BASE_PROPS.identity, hypothesisSummary: "假说待生成" },
      onOpenTeamCommunication: undefined,
    });

    expect(markup).toContain("SCI-096 · 假说待生成");
    expect(markup).toContain(">查看<");
    expect(markup).not.toContain("选择题目开始研究");
    expect(markup).not.toContain('data-variant="primary"');
  });

  it("uses compact English chrome without restoring phase narration", () => {
    const markup = renderToolbar({
      ...BASE_PROPS,
      onOpenTeamCommunication: vi.fn(),
      runtimeCurrentNodeIds: ["protocol_design"],
    }, "en");

    expect(markup).toContain("Switch experiment");
    expect(markup).toContain(">View<");
    expect(markup).toContain(">Collaborate<");
    expect(markup).not.toContain("Experiment design · Protocol design");
    expect(markup).not.toContain("Locate current task");
  });

  it("keeps the fail-closed scope warning visible", () => {
    const markup = renderToolbar({
      ...BASE_PROPS,
      scopeMismatch: true,
      statusMessage: "正在切换题目，旧任务已隐藏",
    });

    expect(markup).toContain("正在切换题目，旧任务已隐藏");
    expect(markup).toContain('data-vui="status-chip"');
  });

  it("labels formal runtime reconciliation and archived statuses", () => {
    const reconciliation = renderToolbar({
      ...BASE_PROPS,
      runStatus: "reconciliation_required",
    });
    expect(reconciliation).toContain("需要对账");
    expect(reconciliation).toContain('data-testid="research-run-status"');

    const archived = renderToolbar({
      ...BASE_PROPS,
      runStatus: "archived",
    });
    expect(archived).toContain("已归档");
  });

  it("says no experiment is selected when chrome identity is missing", () => {
    const markup = renderToolbar({
      ...BASE_PROPS,
      identity: null,
      runId: "",
      experimentOptions: [],
    });
    expect(markup).toContain("尚未选择实验");
  });

  it("maps the five workflow phases for non-toolbar consumers", () => {
    expect(researchWorkflowPhase("前往候选生成")).toMatchObject({ step: 1, zh: "候选形成" });
    expect(researchWorkflowPhase("前往假说选择")).toMatchObject({ step: 2, zh: "假说选择" });
    expect(researchWorkflowPhase("前往下一轮讨论")).toMatchObject({ step: 3, zh: "团队评审" });
    expect(researchWorkflowPhase("查看资料搜集")).toMatchObject({ step: 4, zh: "资料搜集" });
    expect(researchWorkflowPhase("前往假说收敛")).toMatchObject({ step: 5, zh: "假说收敛" });
  });

  it("derives the workflow phase from structural state, not mutable copy", () => {
    expect(researchWorkflowPhase("前往假说收敛", null, true, "review_running"))
      .toMatchObject({ step: 3, zh: "团队评审" });
    expect(researchWorkflowPhase("前往候选生成", null, true, "selection_required"))
      .toMatchObject({ step: 2, zh: "假说选择" });
    expect(researchWorkflowPhase("", null, true, "collection_recovery"))
      .toMatchObject({ step: 4, zh: "资料搜集" });
    expect(researchWorkflowPhase("", null, true, "converged"))
      .toMatchObject({ step: null, zh: "假说先行闭环已完成" });
  });

  it("keeps context and actions usable in the compact two-row layout", () => {
    const markup = renderToolbar({
      ...BASE_PROPS,
      leading: <span data-testid="team-leading">挑战杯ai科研团队</span>,
      onOpenTeamCommunication: vi.fn(),
    });

    expect(markup).toContain("挑战杯ai科研团队");
    expect(markup).toContain("flex-col");
    expect(markup).toContain("xl:flex-row");
    expect(markup.match(/overflow-x-auto/g)?.length ?? 0).toBeGreaterThanOrEqual(2);
    const rootClass = markup.match(/data-vui="toolbar"[^>]*class="([^"]*)"/)?.[1] ?? "";
    expect(rootClass).not.toContain("flex-wrap");
  });
});
