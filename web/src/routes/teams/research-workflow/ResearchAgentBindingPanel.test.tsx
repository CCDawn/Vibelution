import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

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
  return renderToStaticMarkup(
    <MemoryRouter>
      <ResearchAgentBindingPanel teamId={teamId} run={run} effectiveBindings={bindings} lang="zh" />
    </MemoryRouter>,
  );
}

describe("ResearchAgentBindingPanel", () => {
  it("shows role, agent, binding source and session state per card", () => {
    const markup = renderPanel();
    expect(markup).toContain("资料寻找");
    expect(markup).toContain("agent-finder");
    expect(markup).toContain("团队/工作流默认");
    expect(markup).toContain("会话已绑定");
    expect(markup).toContain("未绑定");
  });

  it("links to the agent config entry with the stable agentId", () => {
    const markup = renderPanel();
    expect(markup).toContain("pane=config");
    expect(markup).toContain("agent=agent-finder");
  });

  it("keeps unbound roles unbound with no per-agent config link", () => {
    const markup = renderPanel();
    expect(markup).toContain("未绑定");
    expect(markup).not.toContain("agent=agent-extractor");
    // Bound card still links to its own agent config.
    expect(markup).toContain("agent=agent-finder");
  });

  it("renders nothing without a team", () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter>
        <ResearchAgentBindingPanel teamId="" run={null} effectiveBindings={null} lang="zh" />
      </MemoryRouter>,
    );
    expect(markup).toBe("");
  });
});
