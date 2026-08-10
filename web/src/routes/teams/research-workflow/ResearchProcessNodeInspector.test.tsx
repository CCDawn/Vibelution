import React from "react";
import { renderToStaticMarkup as renderReactMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { ResearchWorkflowNodeDetail } from "../../../api/types/researchWorkflow";
import { ResearchProcessNodeInspector } from "./ResearchProcessNodeInspector";
import { getNodeAdapter } from "./nodeAdapterModel";

function renderToStaticMarkup(node: React.ReactNode) {
  return renderReactMarkup(<MemoryRouter>{node}</MemoryRouter>);
}

function makeDetail(
  overrides: Partial<ResearchWorkflowNodeDetail> = {},
): ResearchWorkflowNodeDetail {
  return {
    runId: "run-1",
    nodeId: "source_finding",
    actorKind: "agent",
    primaryRoleKey: "source_finder",
    label: "资料寻找",
    bindingSnapshot: { agentId: "agent-1", roleKey: "source_finder", resolvedFrom: "workflow_default", displayName: "Finder Agent" },
    sessionBinding: null,
    chatDeepLink: null,
    sessionAnchorDegraded: true,
    runtimeCurrent: false,
    status: "waiting_human",
    nodeAttempt: 1,
    blockedReason: "",
    artifacts: {},
    executionEnvelope: null,
    taskLease: null,
    qualityGateEvaluation: null,
    artifactManifests: [],
    artifactReuseCount: 0,
    commands: [
      { command: "start_agent_task", available: true, reason: "" },
      { command: "open_session", available: true, reason: "" },
    ],
    ...overrides,
  };
}

describe("ResearchProcessNodeInspector command rendering", () => {
  it("renders binding info (agent name, role, source) and node attempt", () => {
    const detail = makeDetail({ nodeAttempt: 2 });
    const markup = renderToStaticMarkup(
      <ResearchProcessNodeInspector
        nodeId="source_finding"
        adapter={getNodeAdapter("source_finding")}
        detail={detail}
        handoffs={[]}
        handoffPending={false}
        busy={false}
        onCommand={vi.fn()}
      />,
    );
    expect(markup).toContain("Finder Agent");
    expect(markup).toContain("agent-1");
    expect(markup).toContain("团队/工作流默认");
    expect(markup).toContain("第 2 次尝试");
    expect(markup).not.toContain("source_finder");
  });

  it("renders backend-declared available commands as buttons", () => {
    const onCommand = vi.fn();
    const markup = renderToStaticMarkup(
      <ResearchProcessNodeInspector
        nodeId="source_finding"
        adapter={getNodeAdapter("source_finding")}
        detail={makeDetail()}
        handoffPending={false}
        busy={false}
        onCommand={onCommand}
      />,
    );
    expect(markup).toContain("启动 Agent 任务");
  });

  it("renders the remediation action only when the backend declares it", () => {
    const markup = renderToStaticMarkup(
      <ResearchProcessNodeInspector
        nodeId="source_extraction"
        adapter={getNodeAdapter("source_extraction")}
        detail={makeDetail({
          nodeId: "source_extraction",
          label: "资料提炼",
          commands: [
            {
              command: "fork_evidence_remediation",
              available: true,
              reason: "",
              idempotencyKey: "fork-evidence-remediation:nr-extraction-a3",
              payload: {
                evidenceGapCandidateIds: ["candidate-a"],
                scopeCandidateIds: ["candidate-a"],
              },
            },
          ],
        })}
        handoffPending={false}
        busy={false}
        onCommand={vi.fn()}
      />,
    );
    expect(markup).toContain("创建证据补救运行");
  });

  it("disables commands the backend reports unavailable with the reason", () => {
    const detail = makeDetail({
      commands: [
        { command: "start_agent_task", available: false, reason: "节点尚未绑定 Agent，先完成绑定" },
        { command: "run_smoke", available: false, reason: "缺少 projectId" },
      ],
    });
    const markup = renderToStaticMarkup(
      <ResearchProcessNodeInspector
        nodeId="source_finding"
        adapter={getNodeAdapter("source_finding")}
        detail={detail}
        handoffPending={false}
        busy={false}
        onCommand={vi.fn()}
      />,
    );
    expect(markup).toContain('disabled');
    expect(markup).toContain("节点尚未绑定 Agent，先完成绑定");
  });

  it("does not render commands the backend did not declare (no fake buttons)", () => {
    const detail = makeDetail({ commands: [] });
    const markup = renderToStaticMarkup(
      <ResearchProcessNodeInspector
        nodeId="source_finding"
        adapter={getNodeAdapter("source_finding")}
        detail={detail}
        handoffPending={false}
        busy={false}
        onCommand={vi.fn()}
      />,
    );
    expect(markup).not.toContain("启动 Agent 任务");
  });

  it("renders open_session as a link only when the exact anchor is complete", () => {
    const bound = makeDetail({
      sessionAnchorDegraded: false,
      chatDeepLink: "/chat?session=s1&focusTask=t1&focusTurn=u1&returnTo=/teams",
      sessionBinding: { bindingId: "b1", runId: "run-1", nodeId: "source_finding", nodeRunId: "nr-1", nodeAttempt: 1, agentId: "agent-1", roleKey: "source_finder", sessionId: "s1", sessionAttempt: 1, taskId: "t1", turnId: "u1", checkpointId: "", status: "bound", boundAt: "" },
    });
    const linkMarkup = renderToStaticMarkup(
      <ResearchProcessNodeInspector
        nodeId="source_finding"
        adapter={getNodeAdapter("source_finding")}
        detail={bound}
        handoffPending={false}
        busy={false}
        onCommand={vi.fn()}
      />,
    );
    expect(linkMarkup).toContain('href="/chat?session=s1');

    const degraded = makeDetail({ sessionAnchorDegraded: true, chatDeepLink: null });
    const disabledMarkup = renderToStaticMarkup(
      <ResearchProcessNodeInspector
        nodeId="source_finding"
        adapter={getNodeAdapter("source_finding")}
        detail={degraded}
        handoffPending={false}
        busy={false}
        onCommand={vi.fn()}
      />,
    );
    expect(disabledMarkup).not.toContain('href="/chat?session=s1');
    expect(disabledMarkup).toContain('disabled');
  });

  it("shows handoff pending and blocked reason when present", () => {
    const detail = makeDetail({ blockedReason: "knowledge_package_rejected" });
    const markup = renderToStaticMarkup(
      <ResearchProcessNodeInspector
        nodeId="source_finding"
        adapter={getNodeAdapter("source_finding")}
        detail={detail}
        handoffPending
        busy={false}
        onCommand={vi.fn()}
      />,
    );
    expect(markup).toContain("等待人工");
    expect(markup).toContain("knowledge_package_rejected");
  });

  it("shows lease, quality gate and artifact reuse from node detail", () => {
    const detail = makeDetail({
      executionEnvelope: { status: "running" },
      taskLease: { status: "running", leaseOwner: "worker-1" },
      qualityGateEvaluation: { status: "passed" },
      artifactManifests: [{ artifactId: "artifact-1" }],
      artifactReuseCount: 1,
    });
    const markup = renderToStaticMarkup(
      <ResearchProcessNodeInspector
        nodeId="source_finding"
        adapter={getNodeAdapter("source_finding")}
        detail={detail}
        handoffPending={false}
        busy={false}
        onCommand={vi.fn()}
      />,
    );
    expect(markup).toContain("运行治理");
    expect(markup).toContain("worker-1");
    expect(markup).toContain("passed");
    expect(markup).toContain("复用命中");
  });

  it("shows an empty state when no node is selected", () => {
    const markup = renderToStaticMarkup(
      <ResearchProcessNodeInspector
        nodeId={null}
        adapter={null}
        detail={null}
        handoffPending={false}
        busy={false}
        onCommand={vi.fn()}
      />,
    );
    expect(markup).toContain("选择流程节点");
  });

  it("does not render a legacy stage drawer entry", () => {
    const markup = renderToStaticMarkup(
      <ResearchProcessNodeInspector
        nodeId="hypothesis_design"
        adapter={getNodeAdapter("hypothesis_design")}
        detail={makeDetail({ nodeId: "hypothesis_design", label: "假设设计" })}
        handoffPending={false}
        busy={false}
        onCommand={vi.fn()}
      />,
    );
    expect(markup).not.toContain("打开实验设计面板");
  });
});
