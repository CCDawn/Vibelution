import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { queryKeys } from "../../../api/queryKeys";
import { ResearchWorkflowToolbar } from "./ResearchWorkflowToolbar";
import type { ResearchWorkflowContext } from "./researchWorkflowContextModel";

function renderToolbar(props: React.ComponentProps<typeof ResearchWorkflowToolbar>, language: "zh" | "en" = "zh") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  queryClient.setQueryData(queryKeys.configPublic(), { language });
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ResearchWorkflowToolbar {...props} />
    </QueryClientProvider>,
  );
}

const context: ResearchWorkflowContext = {
  scope: {key: "SCI-003/run-3", teamId: "research-team", workflowId: "challenge-cup-research", questionId: "SCI-003", runId: "run-3", runVersion: 1},
  loadState: "ready", stages: [],
  currentTask: {key: "task", stage: "problem_understanding", step: "formal_runtime", status: "running", title: "假说设计", detail: "研究进行中", targetNodeId: "hypothesis_design", navigationAction: null, commandAction: null, authority: "formal_runtime"},
  view: {panel: "node", selectedNodeId: "source_finding", selectedIsCurrentTask: false, archiveMode: false},
};
const base = { context, identity: {questionId: "SCI-003", title: "研究题目"}, runId: "run-3", runStatus: "running", experimentOptions: [{questionId: "SCI-003", title: "研究题目", label: "SCI-003 · 研究题目", description: "正式运行"}], panel: "node" as const, onSelectExperiment: vi.fn(), onOpenPanel: vi.fn() };
describe("ResearchWorkflowToolbar unified state", () => {
  it("displays canonical current task even while a historical node is selected", () => {
    const markup = renderToolbar(base);
    expect(markup).toContain("当前任务：假说设计 · 进行中");
    expect(markup).toContain("SCI-003 · 研究题目");
    expect(markup).not.toContain("假说待生成");
    expect(markup).not.toContain("第1/5步");
    expect(markup).toContain("切换研究题目");
  });
  it("preserves read-only navigation and operator action ownership", () => {
    const markup = renderToolbar({...base, onOpenTeamCommunication: vi.fn(), experimentActions: <button>更多操作</button>});
    for (const text of ["流程画布", "题目档案", "团队与讨论", "更多操作"]) expect(markup).toContain(text);
    expect(renderToolbar({...base, identity: null, experimentActions: <button>更多操作</button>})).not.toContain("更多操作");
  });
  it("does not present old current-task state during scope resynchronization", () => {
    const markup = renderToolbar({...base, context: {...context, loadState: "scope_mismatch", currentTask: null}, scopeMismatch: true, statusMessage: "正在切换题目，旧任务已隐藏"});
    expect(markup).not.toContain("假说设计");
    expect(markup).toContain("正在切换题目，旧任务已隐藏");
  });
  it("labels run health separately from the current task", () => {
    const markup = renderToolbar({...base, runStatus: "reconciliation_required"});
    expect(markup).toContain("运行：需要对账");
    expect(markup).toContain("当前任务：假说设计");
  });
});
