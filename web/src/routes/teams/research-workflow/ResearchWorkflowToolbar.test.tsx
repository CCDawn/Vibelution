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
  label: "SCI-096 · 资料寻找 · 0/16 · 等待确认",
  description: "What are the coding principles embedded in neuronal spike trains?",
};

const BASE_PROPS = {
  teamName: "科研团队",
  identity: {
    questionId: "SCI-096",
    title: "What are the coding principles embedded in neuronal spike trains?",
    hypothesisSummary: "尚未选择假说",
  },
  runStatus: "",
  nextAction: "创建运行",
  streamState: "idle",
  experimentOptions: [] as ExperimentSwitchOption[],
  panel: "node",
  hasRuntimeNode: false,
  createDisabled: false,
  onSelectExperiment: () => {},
  onOpenPanel: () => {},
  onJumpToRuntime: () => {},
} satisfies Partial<React.ComponentProps<typeof ResearchWorkflowToolbar>>;

describe("ResearchWorkflowToolbar", () => {
  it("keeps create-run available and shows experiment identity instead of a run id", () => {
    const empty = renderToolbar({
      ...BASE_PROPS,
      runId: "",
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
      onJumpToRuntime: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);
    expect(empty).toContain("创建运行");
    expect(empty).toContain("SCI-096");
    expect(empty).toContain("尚未选择假说");
    expect(empty).toContain("科研团队");
    expect(empty).not.toContain("切换实验");
    expect(empty).not.toContain('data-vui="research-next-action"');

    const running = renderToolbar({
      ...BASE_PROPS,
      runId: "run-5e4fbe6e18f2",
      runStatus: "waiting_human",
      nextAction: "资料寻找",
      streamState: "connected",
      experimentOptions: [EXPERIMENT],
      identity: {
        questionId: "SCI-096",
        title: "What are the coding principles embedded in neuronal spike trains?",
        hypothesisSummary: "假说 hyp-a",
      },
      hasRuntimeNode: true,
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
      onJumpToRuntime: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);
    expect(running).toContain("等待确认");
    expect(running).toContain("实时");
    expect(running).toContain("下一步：资料寻找");
    expect(running).toContain("切换实验");
    expect(running).toContain("SCI-096 · 资料寻找 · 0/16 · 等待确认");
    expect(running).toContain("假说 hyp-a");
    expect(running).not.toContain("waiting_human");
    expect(running).not.toContain("第 1 次运行");
    expect(running).toContain('data-vui="research-next-action"');
    expect(running).not.toContain("当前节点");
  });

  it("keeps the create-run entry reachable while a run is selected", () => {
    const running = renderToolbar({
      ...BASE_PROPS,
      runId: "run-5e4fbe6e18f2",
      runStatus: "running",
      nextAction: "",
      streamState: "connected",
      experimentOptions: [EXPERIMENT],
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
      onJumpToRuntime: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);
    expect(running).toContain("新建运行");
    expect(running).toContain("切换实验");
  });

  it("renders English chrome when the shell language is en", () => {
    const running = renderToolbar({
      ...BASE_PROPS,
      runId: "run-1",
      runStatus: "running",
      nextAction: "",
      streamState: "reconnecting",
      experimentOptions: [{ ...EXPERIMENT, runId: "run-1" }],
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
      onJumpToRuntime: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>, "en");
    expect(running).toContain("New run");
    expect(running).toContain("Reconnecting");
    expect(running).toContain("Timeline");
    expect(running).toContain("Switch experiment");
  });

  it("says no experiment is selected when chrome identity is missing", () => {
    const empty = renderToolbar({
      ...BASE_PROPS,
      identity: null,
      runId: "",
      onSelectExperiment: vi.fn(),
      onOpenPanel: vi.fn(),
      onJumpToRuntime: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);
    expect(empty).toContain("尚未选择实验");
  });
});
