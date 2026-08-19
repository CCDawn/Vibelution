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
  label: "SCI-096 · 尚未选择假说",
  description: "What are the coding principles embedded in neuronal spike trains?",
};

const BASE_PROPS = {
  identity: {
    questionId: "SCI-096",
    title: "What are the coding principles embedded in neuronal spike trains?",
    hypothesisSummary: "尚未选择假说",
  },
  runStatus: "",
  experimentOptions: [] as ExperimentSwitchOption[],
  panel: "node",
  createDisabled: false,
  onSelectExperiment: () => {},
  onOpenPanel: () => {},
} satisfies Partial<React.ComponentProps<typeof ResearchWorkflowToolbar>>;

describe("ResearchWorkflowToolbar", () => {
  it("keeps create-run available and puts hypothesis plus number in the switcher", () => {
    const empty = renderToolbar({
      ...BASE_PROPS,
      runId: "",
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);
    expect(empty).toContain("创建运行");
    expect(empty).toContain("SCI-096 · 尚未选择假说");
    expect(empty).toContain("查看详情");
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
      experimentOptions: [{ ...EXPERIMENT, label: "SCI-096 · 已选 1 个假说" }],
      identity: {
        questionId: "SCI-096",
        title: "What are the coding principles embedded in neuronal spike trains?",
        hypothesisSummary: "已选 1 个假说",
      },
      navigationLabel: "前往确认候选",
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);
    expect(running).toContain("第 1/5 步 · 候选形成");
    expect(running).toContain("切换实验");
    expect(running).not.toContain("切换假说");
    expect(running).toContain("SCI-096 · 已选 1 个假说");
    expect(running).not.toContain('data-vui="status-chip"');
    expect(running).not.toContain("waiting_human");
    expect(running).not.toContain("第 1 次运行");
    expect(running).not.toContain("实时");
    expect(running).not.toContain("下一步：资料寻找");
    expect(running).not.toContain("资料寻找 · 0/16");
    expect(running).not.toContain('data-vui="research-next-action"');
    expect(running).not.toContain("当前节点");
  });

  it("moves new-run into the details selector while keeping one primary task action", () => {
    const running = renderToolbar({
      ...BASE_PROPS,
      runId: "run-5e4fbe6e18f2",
      runStatus: "running",
      experimentOptions: [EXPERIMENT],
      panel: "launch",
      navigationLabel: "前往假说选择",
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);
    expect(running).toContain("新建运行");
    expect(running).toContain("切换实验");
    expect(running).toContain("前往假说选择");
    expect(running).toContain("第 2/5 步 · 假说选择");
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
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>, "en");
    expect(running).toContain("Run history");
    expect(running).toContain("Step 3/5 · Team review");
    expect(running).not.toContain("Status");
    expect(running).not.toContain("Timeline");
    expect(running).toContain("Switch experiment");
    expect(running).not.toContain("Switch hypothesis");
    expect(running).not.toContain("Reconnecting");
  });

  it("uses navigation copy as the primary action when a run exists", () => {
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
    expect(running).toContain("前往确认候选");
    expect(running).toContain("查看详情");
    expect(running).not.toContain("新建运行");
    expect(running).not.toContain("生成纪要");
    expect(running).not.toContain("确认并结束本轮");
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

  it("keeps the toolbar compact with a capped switcher and retains details plus primary action", () => {
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

    expect(markup).toContain("max-w-[24rem]");
    expect(markup).toContain("md:ms-auto");
    expect(markup).toContain("查看详情");
    expect(markup).toContain("前往确认候选");
    expect(markup).toContain("data-vui=\"research-workflow-phase\"");
    expect(markup).not.toContain("grid-cols-[minmax(10rem,1fr)");
    expect(markup).not.toContain("grid-cols-[minmax(12rem,1fr)");
  });

  it("keeps the details and create-run action on narrow layouts when no run exists", () => {
    const empty = renderToolbar({
      ...BASE_PROPS,
      runId: "",
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);

    expect(empty).toContain("创建运行");
    expect(empty).toContain("查看详情");
    expect(empty).toContain("尚未选择假说");
    expect(empty).toContain("flex-wrap");
    expect(empty).toContain("max-w-[24rem]");
  });
});
