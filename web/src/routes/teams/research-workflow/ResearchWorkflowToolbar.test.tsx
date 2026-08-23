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
  label: "SCI-096 · 假说待生成",
  description: "What are the coding principles embedded in neuronal spike trains?",
};

const BASE_PROPS = {
  identity: {
    questionId: "SCI-096",
    title: "What are the coding principles embedded in neuronal spike trains?",
    hypothesisSummary: "假说待生成",
  },
  runStatus: "",
  experimentOptions: [] as ExperimentSwitchOption[],
  panel: "node",
  onSelectExperiment: () => {},
  onOpenPanel: () => {},
} satisfies Partial<React.ComponentProps<typeof ResearchWorkflowToolbar>>;

describe("ResearchWorkflowToolbar", () => {
  it("keeps the toolbar read-only before a workflow starts and puts hypothesis plus number in the switcher", () => {
    const empty = renderToolbar({
      ...BASE_PROPS,
      runId: "",
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);
    expect(empty).not.toContain("选择题目开始研究");
    expect(empty).not.toContain('data-variant="primary"');
    expect(empty).toContain("SCI-096 · 假说待生成");
    expect(empty).toContain("题目进度");
    expect(empty).not.toContain("状态");
    expect(empty).not.toContain("科研团队");
    expect(empty).not.toContain("切换假说");
    expect(empty).not.toContain("切换实验");
    expect(empty).not.toContain("下一步");
    expect(empty).not.toContain('data-vui="research-next-action"');

    const running = renderToolbar({
      ...BASE_PROPS,
      runId: "run-5e4fbe6e18f2",
      runStatus: "waiting_human",
      experimentOptions: [{ ...EXPERIMENT, label: "SCI-096 · 1 条假说待评审" }],
      identity: {
        questionId: "SCI-096",
        title: "What are the coding principles embedded in neuronal spike trains?",
        hypothesisSummary: "1 条假说待评审",
      },
      navigationLabel: "前往确认候选",
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);
    expect(running).toContain("假说准备 · 1/5");
    expect(running).not.toContain("第 1/5 步");
    expect(running).toContain("切换实验");
    expect(running).not.toContain("切换假说");
    expect(running).toContain("SCI-096 · 1 条假说待评审");
    expect(running).not.toContain('data-vui="status-chip"');
    expect(running).not.toContain("waiting_human");
    expect(running).not.toContain("第 1 次运行");
    expect(running).not.toContain("实时");
    expect(running).not.toContain("下一步：资料寻找");
    expect(running).not.toContain("资料寻找 · 0/16");
    expect(running).not.toContain('data-vui="research-next-action"');
    expect(running).not.toContain("当前节点");
  });

  it("keeps details and secondary current-task navigation without a run mutation", () => {
    const running = renderToolbar({
      ...BASE_PROPS,
      runId: "run-5e4fbe6e18f2",
      runStatus: "running",
      experimentOptions: [EXPERIMENT],
      panel: "launch",
      navigationLabel: "前往假说选择",
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
      onNavigateCurrent: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);
    expect(running).not.toContain("新建运行");
    expect(running).toContain("切换实验");
    expect(running).toContain("运行记录");
    expect(running).toContain("定位当前任务");
    expect(running).not.toContain("前往假说选择");
    expect(running).toContain('data-variant="secondary"');
    expect(running).not.toContain('data-variant="primary"');
    expect(running).toContain("假说准备 · 2/5");
  });

  it("renders English chrome when the shell language is en", () => {
    const running = renderToolbar({
      ...BASE_PROPS,
      runId: "run-1",
      runStatus: "running",
      experimentOptions: [{ ...EXPERIMENT, runId: "run-1" }],
      panel: "timeline",
      navigationLabel: "前往评审讨论",
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
      onNavigateCurrent: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>, "en");
    expect(running).toContain("History");
    expect(running).toContain("Progress");
    expect(running).toContain("Hypothesis prep · 3/5");
    expect(running).not.toContain("Status");
    expect(running).not.toContain("Timeline");
    expect(running).toContain("Switch experiment");
    expect(running).not.toContain("Switch hypothesis");
    expect(running).not.toContain("Reconnecting");
    expect(running).toContain("Locate current task");
  });

  it("uses fixed navigation copy as a secondary action when a run exists", () => {
    const running = renderToolbar({
      ...BASE_PROPS,
      runId: "run-5e4fbe6e18f2",
      runStatus: "running",
      experimentOptions: [EXPERIMENT],
      navigationLabel: "前往确认候选",
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
      onNavigateCurrent: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);
    expect(running).toContain("定位当前任务");
    expect(running).not.toContain("前往确认候选");
    expect(running).toContain('data-variant="secondary"');
    expect(running).not.toContain('data-variant="primary"');
    expect(running).toContain("题目进度");
    expect(running).toContain("运行记录");
    expect(running).not.toContain("生成纪要");
    expect(running).not.toContain("确认并结束本轮");
  });

  it("keeps the current task action when the hypothesis workflow is active without a formal run id", () => {
    const active = renderToolbar({
      ...BASE_PROPS,
      runId: "",
      workflowActive: true,
      navigationLabel: "查看评审讨论",
      onNavigateCurrent: vi.fn(),
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);

    expect(active).toContain("定位当前任务");
    expect(active).not.toContain("查看评审讨论");
    expect(active).toContain('data-vui="research-workflow-phase"');
    expect(active).not.toContain("选择题目开始研究");
  });

  it("disables current-task navigation when its callback is not ready", () => {
    const blocked = renderToolbar({
      ...BASE_PROPS,
      runId: "",
      workflowActive: true,
      atCurrentTask: false,
      navigationLabel: "前往团队评审",
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);

    expect(blocked).toContain("定位当前任务");
    expect(blocked).not.toContain("前往团队评审");
    expect(blocked).toContain("disabled");
    expect(blocked).toContain("aria-disabled=\"true\"");
    expect(blocked).toContain("当前任务导航尚未准备好，请稍后重试");
  });

  it("keeps the question archive as its own read-only inspector view", () => {
    const archive = renderToolbar({
      ...BASE_PROPS,
      runId: "",
      workflowActive: true,
      panel: "question",
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);

    expect(archive).toContain("题目档案");
    expect(archive).not.toContain('aria-selected="true">题目进度');
  });

  it("shows the canonical formal stage and runtime node", () => {
    const running = renderToolbar({
      ...BASE_PROPS,
      runId: "run-5e4fbe6e18f2",
      runStatus: "running",
      experimentOptions: [EXPERIMENT],
      navigationLabel: "前往协议设计",
      runtimeCurrentNodeIds: ["protocol_design"],
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
      onNavigateCurrent: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);
    expect(running).toContain("实验设计 · 协议设计");
    expect(running).not.toContain("假说准备");
    expect(running).toContain("定位当前任务");
    expect(running).not.toContain("前往协议设计");
  });

  it("keeps hypothesis preparation ahead of convergence even when runtime starts at source finding", () => {
    const beforeConvergence = renderToolbar({
      ...BASE_PROPS,
      runId: "run-5e4fbe6e18f2",
      runStatus: "running",
      experimentOptions: [EXPERIMENT],
      navigationLabel: "前往候选生成",
      runtimeCurrentNodeIds: ["source_finding"],
      formalRuntimeActive: false,
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);
    expect(beforeConvergence).toContain("假说准备 · 1/5");
    expect(beforeConvergence).not.toContain("资料搜集 · 资料寻找");

    const afterConvergence = renderToolbar({
      ...BASE_PROPS,
      runId: "run-5e4fbe6e18f2",
      runStatus: "running",
      experimentOptions: [EXPERIMENT],
      navigationLabel: "前往协议设计",
      runtimeCurrentNodeIds: ["protocol_design"],
      formalRuntimeActive: true,
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);
    expect(afterConvergence).toContain("实验设计 · 协议设计");
  });

  it("shows the completed hypothesis-first loop when convergence has no formal runtime node", () => {
    const converged = renderToolbar({
      ...BASE_PROPS,
      runId: "",
      workflowActive: true,
      navigationLabel: "查看假说收敛",
      runtimeCurrentNodeIds: [],
      formalRuntimeActive: true,
      nextActionStage: "converged",
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
      onNavigateCurrent: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);

    expect(converged).toContain("假说先行闭环已完成");
    expect(converged).not.toContain("假说准备 · 5/5");
  });

  it("prefers the formal runtime node over convergence copy when one is available", () => {
    const running = renderToolbar({
      ...BASE_PROPS,
      runId: "run-5e4fbe6e18f2",
      runStatus: "running",
      experimentOptions: [EXPERIMENT],
      navigationLabel: "查看假说收敛",
      runtimeCurrentNodeIds: ["source_finding"],
      formalRuntimeActive: true,
      nextActionStage: "converged",
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
      onNavigateCurrent: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);

    expect(running).toContain("资料搜集 · 资料寻找");
    expect(running).not.toContain("假说先行闭环已完成");
    expect(running).not.toContain("假说准备 · 5/5");
  });

  it("uses an English node label when the shell language is en", () => {
    const running = renderToolbar({
      ...BASE_PROPS,
      runId: "run-5e4fbe6e18f2",
      runStatus: "running",
      experimentOptions: [EXPERIMENT],
      navigationLabel: "前往协议设计",
      runtimeCurrentNodeIds: ["protocol_design"],
      formalRuntimeActive: true,
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>, "en");
    expect(running).toContain('data-vui="research-workflow-phase">Experiment design · Protocol design');
  });

  it("says no experiment is selected when chrome identity is missing", () => {
    const empty = renderToolbar({
      ...BASE_PROPS,
      identity: null,
      runId: "",
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);
    expect(empty).toContain("尚未选择实验");
  });

  it("maps the five user-facing phases without exposing internal run states", () => {
    expect(researchWorkflowPhase("前往候选生成")).toMatchObject({ step: 1, zh: "候选形成" });
    expect(researchWorkflowPhase("前往假说选择")).toMatchObject({ step: 2, zh: "假说选择" });
    expect(researchWorkflowPhase("前往下一轮讨论")).toMatchObject({ step: 3, zh: "团队评审" });
    expect(researchWorkflowPhase("查看资料搜集")).toMatchObject({ step: 4, zh: "资料搜集" });
    expect(researchWorkflowPhase("前往假说收敛")).toMatchObject({ step: 5, zh: "假说收敛" });
  });

  it("uses a two-row compact layout below 1280 while retaining details and navigation", () => {
    const markup = renderToolbar({
      ...BASE_PROPS,
      runId: "run-5e4fbe6e18f2",
      runStatus: "running",
      experimentOptions: [EXPERIMENT],
      panel: "node",
      navigationLabel: "前往确认候选",
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
      onNavigateCurrent: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);

    expect(markup).toContain("xl:max-w-[24rem]");
    expect(markup).toContain("ms-auto");
    expect(markup).toContain("flex-nowrap");
    expect(markup).toContain("overflow-hidden");
    expect(markup).toContain("flex-col");
    expect(markup).toContain("xl:flex-row");
    expect(markup).toContain("overflow-x-auto");
    expect(markup.match(/overflow-x-auto/g)?.length ?? 0).toBeGreaterThanOrEqual(2);
    expect(markup).toContain("data-vui=\"tabs\"");
    expect(markup).toContain("定位当前任务");
    expect(markup).not.toContain("前往确认候选");
    expect(markup).not.toContain('data-variant="primary"');
    expect(markup).toContain("data-vui=\"research-workflow-phase\"");
    expect(markup).not.toContain("grid-cols-[minmax(10rem,1fr)");
    expect(markup).not.toContain("grid-cols-[minmax(12rem,1fr)");
    expect(markup).not.toContain("md:ms-auto");
    const rootClass = markup.match(/data-vui="toolbar"[^>]*class="([^"]*)"/)?.[1] ?? "";
    expect(rootClass).not.toContain("flex-wrap");
  });

  it("keeps details reachable on narrow layouts without exposing a launch action", () => {
    const empty = renderToolbar({
      ...BASE_PROPS,
      runId: "",
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);

    expect(empty).not.toContain("选择题目开始研究");
    expect(empty).toContain("题目进度");
    expect(empty).toContain("成员与讨论");
    expect(empty).toContain("假说待生成");
    expect(empty).toContain("flex-nowrap");
    const emptyRootClass = empty.match(/data-vui="toolbar"[^>]*class="([^"]*)"/)?.[1] ?? "";
    expect(emptyRootClass).not.toContain("flex-wrap");
    expect(empty).toContain("xl:max-w-[24rem]");
    expect(empty).toContain("overflow-hidden");
    expect(empty).toContain("overflow-x-auto");
  });

  it("exposes team communication and evidence graph entry points", () => {
    const markup = renderToolbar({
      ...BASE_PROPS,
      runId: "run-5e4fbe6e18f2",
      panel: "evidence",
      onOpenTeamCommunication: vi.fn(),
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);

    expect(markup).toContain("团队沟通");
    expect(markup).toContain("证据图谱");
    expect(markup).toContain('data-testid="research-open-team-communication"');
  });

  it("keeps a leading team switcher in the context row", () => {
    const markup = renderToolbar({
      ...BASE_PROPS,
      runId: "",
      leading: <span data-testid="team-leading">挑战杯ai科研团队</span>,
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);
    expect(markup).toContain("挑战杯ai科研团队");
    expect(markup).not.toContain("选择题目开始研究");
    expect(markup).toContain("flex-nowrap");
  });
});
