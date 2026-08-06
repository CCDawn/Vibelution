import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { AgentToolGovernanceRequest } from "../api/types";
import { AgentToolGovernancePanel } from "./AgentToolGovernancePanel";

const request: AgentToolGovernanceRequest = {
  eventId: "event-1",
  requestId: "request-1",
  kind: "tool_policy",
  status: "pending_review",
  targetAgentId: "agent-1",
  targetAgentCode: "research",
  targetAgentName: "研究 Agent",
  proposedByAgentId: "agent-2",
  proposedByAgentCode: "supervisor",
  proposedByAgentName: "监督 Agent",
  policyDelta: { grantTools: ["search"], revokeTools: [], blockTools: [], unblockTools: [] },
  reason: "需要访问研究数据。",
  authority: {},
  riskLevel: "high",
  riskTags: [],
  requiresApproval: true,
  approvalReason: "高风险授权。",
  createdAt: "",
  resolvedAt: "",
  resolvedBy: "",
  resolutionNote: "",
  appliedToolPolicyId: "",
};

describe("AgentToolGovernancePanel", () => {
  it("keeps approval state and actions visible while moving governance detail into focusable disclosure", () => {
    const markup = renderToStaticMarkup(
      <AgentToolGovernancePanel
        copy={{
          toolGovernanceApprove: "批准",
          toolGovernanceEmpty: "暂无申请",
          toolGovernancePending: "待审批",
          toolGovernanceReject: "拒绝",
          toolGovernanceTitle: "工具治理",
        }}
        lang="zh"
        requests={[request]}
        pendingRequestId={null}
        onResolve={() => undefined}
        onConfigure={() => undefined}
      />,
    );

    expect(markup).toContain("待审批");
    expect(markup).toContain("高风险");
    expect(markup).toContain("批准");
    expect(markup).toContain("拒绝");
    expect(markup).toContain('tabindex="0"');
    expect(markup).not.toContain(">授权 1 · 撤销 0 · 禁用 0 · 解除禁用 0<");
    expect(markup).not.toContain(">需要访问研究数据。<");
  });
});
