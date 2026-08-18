import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { queryKeys } from "../../../api/queryKeys";
import type { AgentConfigWorkspaceAgent } from "../../../api/types";
import type { WorkflowRunRecord } from "../../../api/researchWorkflow";
import type { EffectiveAgentBinding } from "../../../api/types/researchWorkflow";
import { ResearchAgentBindingPanel } from "./ResearchAgentBindingPanel";

const BINDINGS: EffectiveAgentBinding[] = [
  { nodeId: "source_finding", roleKey: "source_finder", agentId: "agent-finder", resolvedFrom: "workflow_default" },
  { nodeId: "source_extraction", roleKey: "source_extractor", agentId: "", resolvedFrom: "unbound" },
  { nodeId: "hypothesis_design", roleKey: "experiment_planner", agentId: "agent-planner", resolvedFrom: "workflow_default" },
];

function makeRun(): WorkflowRunRecord {
  return {
    runId: "run-1",
    workflowId: "challenge-cup-research",
    workflowVersionId: "wv-x",
    status: "waiting_human",
    bindingSnapshots: [
      { snapshotId: "s1", nodeId: "source_finding", agentId: "agent-finder", roleKey: "source_finder", resolvedFrom: "workflow_default" },
    ],
    sessionBindings: {
      source_finding: {
        bindingId: "b1",
        sessionId: "sess-1",
        taskId: "t1",
        turnId: "u1",
        status: "bound",
      },
    },
    events: [],
    humanTasks: [],
    handoffs: [],
  } as unknown as WorkflowRunRecord;
}

function renderPanel(teamId = "research-team", run: WorkflowRunRecord | null = makeRun(), bindings: EffectiveAgentBinding[] | null = BINDINGS) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  queryClient.setQueryData<AgentConfigWorkspaceAgent[]>(queryKeys.agentSummary(false), [
    {
      agentId: "agent-finder",
      llmBindings: { dialogue: { modelId: "qwen-plus" } },
    } as AgentConfigWorkspaceAgent,
    {
      agentId: "agent-planner",
      llmBindings: { dialogue: { modelId: "deepseek-v3" } },
    } as AgentConfigWorkspaceAgent,
  ]);
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ResearchAgentBindingPanel teamId={teamId} run={run} effectiveBindings={bindings} lang="zh" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ResearchAgentBindingPanel", () => {
  it("shows only role, model and actionable status", () => {
    const markup = renderPanel();
    expect(markup).toContain("职责");
    expect(markup).toContain("模型");
    expect(markup).toContain("状态");
    expect(markup).toContain("资料寻找");
    expect(markup).toContain("qwen-plus");
    expect(markup).toContain("deepseek-v3");
    expect(markup).toContain("可用");
    expect(markup).toContain("未配置");
    expect(markup).not.toContain("agent-finder");
    expect(markup).not.toContain("团队/工作流默认");
    expect(markup).not.toContain("会话已绑定");
  });

  it("keeps rows keyboard-activatable without a visible action column", () => {
    const markup = renderPanel();
    expect(markup).toContain('tabindex="0"');
    expect(markup).not.toContain("Agent 记忆");
    expect(markup).not.toContain("pane=config");
  });

  it("keeps unbound roles visibly unconfigured", () => {
    const markup = renderPanel();
    expect(markup).toContain("未配置");
    expect(markup).toContain("—");
  });

  it("renders nothing without a team", () => {
    const markup = renderToStaticMarkup(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <ResearchAgentBindingPanel teamId="" run={null} effectiveBindings={null} lang="zh" />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(markup).toBe("");
  });
});
