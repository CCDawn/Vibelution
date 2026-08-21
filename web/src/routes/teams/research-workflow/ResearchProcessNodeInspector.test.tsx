import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup as renderReactMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { CommandOffer } from "../../../api/types/research-workflow/commands";
import type { ResearchWorkflowNodeDetail } from "../../../api/types/research-workflow/core";
import { ResearchProcessNodeInspector } from "./ResearchProcessNodeInspector";
import { getNodeAdapter } from "./nodeAdapterModel";

function renderToStaticMarkup(node: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, enabled: false } },
  });
  return renderReactMarkup(
    <QueryClientProvider client={client}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

function offer(partial: Partial<CommandOffer> & Pick<CommandOffer, "command" | "label">): CommandOffer {
  return {
    nodeId: "source_finding",
    available: true,
    reasonCode: "ready",
    blockerIds: [],
    idempotencyKey: `offer:${partial.command}`,
    expectedRunVersion: 1,
    payload: {},
    ...partial,
  };
}

function makeDetail(
  overrides: Partial<ResearchWorkflowNodeDetail> = {},
): ResearchWorkflowNodeDetail {
  return {
    runId: "run-1",
    teamId: "research-team",
    nodeId: "source_finding",
    runVersion: 1,
    actorKind: "agent",
    primaryRoleKey: "source_finder",
    label: "资料寻找",
    runtimeCurrent: false,
    status: "waiting_human",
    attempts: [],
    commandOffers: [
      offer({ command: "start_node", label: "启动 资料寻找" }),
    ],
    latestEventSequence: 1,
    generatedAt: "2026-08-12T14:00:00.000Z",
    agentId: "agent-1",
    displayName: "Finder Agent",
    resolvedFrom: "workflow_default",
    sessionAnchorDegraded: true,
    chatDeepLink: null,
    nodeAttempt: 1,
    blockedReason: "",
    ...overrides,
  };
}

function renderInspector(detail: ResearchWorkflowNodeDetail | null, extras: {
  nodeId?: string | null;
  adapter?: ReturnType<typeof getNodeAdapter>;
  handoffPending?: boolean;
  isCurrentTask?: boolean;
  hideStartOffer?: boolean;
  statusBanner?: string | null;
} = {}) {
  return renderToStaticMarkup(
    <ResearchProcessNodeInspector
      teamId="research-team"
      nodeId={extras.nodeId === undefined ? "source_finding" : extras.nodeId}
      adapter={extras.adapter === undefined ? getNodeAdapter("source_finding") : extras.adapter}
      detail={detail}
      effectiveBindings={[]}
      budget={null}
      handoffs={[]}
      handoffPending={Boolean(extras.handoffPending)}
      busy={false}
      isCurrentTask={extras.isCurrentTask}
      onOffer={vi.fn()}
      hideStartOffer={extras.hideStartOffer}
      statusBanner={extras.statusBanner}
    />,
  );
}

describe("ResearchProcessNodeInspector command rendering", () => {
  it("renders agent identity and model/budget ops without internal role keys", () => {
    const markup = renderInspector(makeDetail({ nodeAttempt: 2 }));
    expect(markup).toContain("Finder Agent");
    expect(markup).toContain("agent-1");
    expect(markup).toContain("知识搜集");
    expect(markup).toContain("Tokens");
    expect(markup).toContain('data-testid="node-inspector-model-trigger"');
    expect(markup).not.toContain("source_finder");
    expect(markup).not.toContain("knowledge collection");
    expect(markup).not.toContain("Agent 执行");
    expect(markup).not.toContain("第 2 次尝试");
    expect(markup).not.toContain("团队/工作流默认");
  });

  it("renders backend-declared available CommandOffers as buttons", () => {
    const markup = renderInspector(makeDetail());
    expect(markup).toContain("启动 资料寻找");
  });

  it("keeps historical formal nodes read-only", () => {
    const markup = renderInspector(makeDetail(), { isCurrentTask: false });
    expect(markup).toContain('data-testid="node-inspector-readonly"');
    expect(markup).toContain("历史节点只读");
    expect(markup).not.toContain("启动 资料寻找");
    expect(markup).not.toContain('data-vui="node-commands"');
    expect(markup).toContain('data-testid="node-inspector-model-trigger" disabled');
  });

  it("renders fork_revision from the signed offer label", () => {
    const markup = renderInspector(makeDetail({
      nodeId: "source_extraction",
      label: "资料提炼",
      commandOffers: [
        offer({
          command: "fork_revision",
          nodeId: "source_extraction",
          label: "分叉修订",
          idempotencyKey: "offer:fork",
        }),
      ],
    }), { nodeId: "source_extraction", adapter: getNodeAdapter("source_extraction") });
    expect(markup).toContain("分叉修订");
  });

  it("disables unavailable offers with the backend reason", () => {
    const markup = renderInspector(makeDetail({
      commandOffers: [
        offer({
          command: "start_node",
          label: "启动 资料寻找",
          available: false,
          reasonCode: "节点尚未绑定 Agent，先完成绑定",
          blockerIds: ["unbound"],
        }),
      ],
    }));
    expect(markup).toContain("disabled");
    expect(markup).toContain("节点尚未绑定 Agent，先完成绑定");
  });

  it("does not render commands the backend did not declare (no fake buttons)", () => {
    const markup = renderInspector(makeDetail({ commandOffers: [] }));
    expect(markup).not.toContain("启动 资料寻找");
  });

  it("renders open session as a link only when the exact anchor is complete", () => {
    const linkMarkup = renderInspector(makeDetail({
      sessionAnchorDegraded: false,
      sessionId: "s1",
      taskId: "t1",
      turnId: "u1",
      chatDeepLink: "/chat?session=s1&focusTask=t1&focusTurn=u1&returnTo=/teams",
    }));
    expect(linkMarkup).toContain('href="/chat?session=s1');

    const disabledMarkup = renderInspector(makeDetail({
      sessionAnchorDegraded: true,
      sessionId: "s1",
      chatDeepLink: null,
    }));
    expect(disabledMarkup).not.toContain('href="/chat?session=s1');
  });

  it("renders the real root session and every ordered candidate child session", () => {
    const markup = renderInspector(makeDetail({
      nodeId: "hypothesis_design",
      label: "假说设计",
      rootSession: {
        scopeKind: "workflow_node_root",
        sessionId: "root-session",
        status: "running",
        sessionAttempt: 1,
        chatDeepLink: null,
        sessionAnchorDegraded: true,
      },
      scopedSessions: [
        {
          scopeKind: "workflow_candidate",
          candidateId: "H2",
          selectionId: "selection-1",
          sessionId: "child-H2",
          sessionAttempt: 2,
          taskId: "task-H2",
          status: "running",
          chatDeepLink: "/chat?session=child-H2&focusTask=task-H2",
          fragmentRef: null,
          sessionAnchorDegraded: false,
        },
        {
          scopeKind: "workflow_candidate",
          candidateId: "H1",
          selectionId: "selection-1",
          sessionId: "child-H1",
          sessionAttempt: 1,
          taskId: "task-H1",
          status: "succeeded",
          chatDeepLink: "/chat?session=child-H1&focusTask=task-H1",
          fragmentRef: "fragment:H1",
          sessionAnchorDegraded: false,
        },
      ],
    }), { nodeId: "hypothesis_design", adapter: getNodeAdapter("hypothesis_design") });

    expect(markup).toContain("root-session");
    expect(markup.indexOf("候选 H2")).toBeLessThan(markup.indexOf("候选 H1"));
    expect(markup).toContain("fragment:H1");
    expect(markup).toContain('href="/chat?session=child-H2');
  });

  it("shows handoff pending and blocked reason when present", () => {
    const markup = renderInspector(makeDetail({ blockedReason: "knowledge_package_rejected" }), {
      handoffPending: true,
    });
    expect(markup).toContain("等待人工");
    expect(markup).toContain("knowledge_package_rejected");
  });

  it("shows an empty state when no node is selected", () => {
    const markup = renderInspector(null, { nodeId: null, adapter: null });
    expect(markup).toContain("选择流程节点");
  });

  it("does not render a legacy stage drawer entry", () => {
    const markup = renderInspector(
      makeDetail({ nodeId: "hypothesis_design", label: "假设设计" }),
      { nodeId: "hypothesis_design", adapter: getNodeAdapter("hypothesis_design") },
    );
    expect(markup).not.toContain("打开实验设计面板");
  });

  it("hides start-collection and shows 资料搜集中 when collecting", () => {
    const markup = renderInspector(makeDetail({
      commandOffers: [
        offer({ command: "start_node", label: "启动 资料寻找", available: false, reasonCode: "hypothesis_first_meeting_open" }),
      ],
    }), {
      hideStartOffer: true,
      statusBanner: "资料搜集中",
    });
    expect(markup).toContain("资料搜集中");
    expect(markup).toContain('role="status"');
    expect(markup).not.toContain("启动 资料寻找");
    expect(markup).not.toContain("开始资料搜集");
  });

  it("shows human remediation copy instead of hypothesis_first_meeting_open", () => {
    const markup = renderInspector(makeDetail({
      commandOffers: [
        offer({
          command: "start_node",
          label: "启动 资料寻找",
          available: false,
          reasonCode: "hypothesis_first_meeting_open",
          payload: { remediation_label: "前往闭环首轮假说讨论" },
        }),
      ],
    }));
    expect(markup).toContain("前往闭环首轮假说讨论");
    expect(markup).not.toContain("hypothesis_first_meeting_open");
  });
});
