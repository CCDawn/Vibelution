import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../../api/queryKeys";
import type { ExperimentSwitchOption } from "./researchExperimentSwitchModel";
import { ResearchWorkflowToolbar } from "./ResearchWorkflowToolbar";

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
    expect(empty).toContain("状态");
    expect(empty).not.toContain("科研团队");
    expect(empty).not.toContain("切换假说");
    expect(empty).not.toContain("切换实验");
    expect(empty).not.toContain("下一步");
    expect(empty).not.toContain('data-vui="research-next-action"');

    const running = renderToolbar({
      ...BASE_PROPS,
      runId: "run-5e4fbe6e18f2",
      runStatus: "waiting_human",
      experimentOptions: [{ ...EXPERIMENT, label: "SCI-096 · 假说 hyp-a" }],
      identity: {
        questionId: "SCI-096",
        title: "What are the coding principles embedded in neuronal spike trains?",
        hypothesisSummary: "假说 hyp-a",
      },
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);
    expect(running).toContain("等待确认");
    expect(running).toContain("切换实验");
    expect(running).not.toContain("切换假说");
    expect(running).toContain("SCI-096 · 假说 hyp-a");
    expect(running).toContain('data-vui="status-chip"');
    expect(running).not.toContain("waiting_human");
    expect(running).not.toContain("第 1 次运行");
    expect(running).not.toContain("实时");
    expect(running).not.toContain("下一步：资料寻找");
    expect(running).not.toContain("资料寻找 · 0/16");
    expect(running).not.toContain('data-vui="research-next-action"');
    expect(running).not.toContain("当前节点");
  });

  it("keeps the create-run entry reachable while a run is selected", () => {
    const running = renderToolbar({
      ...BASE_PROPS,
      runId: "run-5e4fbe6e18f2",
      runStatus: "running",
      experimentOptions: [EXPERIMENT],
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);
    expect(running).toContain("新建运行");
    expect(running).toContain("切换实验");
    expect(running).toContain("前往当前任务");
  });

  it("renders English chrome when the shell language is en", () => {
    const running = renderToolbar({
      ...BASE_PROPS,
      runId: "run-1",
      runStatus: "running",
      experimentOptions: [{ ...EXPERIMENT, runId: "run-1" }],
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>, "en");
    expect(running).toContain("New run");
    expect(running).toContain("Status");
    expect(running).toContain("Timeline");
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
    expect(running).toContain("新建运行");
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
});
