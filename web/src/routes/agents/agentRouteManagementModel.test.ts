import { describe, expect, it } from "vitest";

import type { AgentConfigWorkspaceAgent } from "../../api/types";
import {
  buildAgentManagementBrief,
  buildManagementFilterGroups,
  buildVisibleAgentColumns,
  groupSectionId,
  managementFilterMatches,
  normalizeAgentConfigPane,
} from "./agentRouteManagementModel";

const copy = {
  managementModelPrompt: "模型",
  managementTools: "工具",
  managementWorkspace: "工作区",
  managementRuntime: "运行时",
  managementIdentity: "身份",
  managementTask: "任务",
  managementMembership: "归属",
  nextSetupModelPrompt: "补模型",
  nextSetupModelPromptHint: "hint",
  nextSetupIdentity: "补身份",
  nextSetupIdentityHint: "hint",
  nextSetupTask: "补任务",
  nextSetupTaskHint: "hint",
  nextSetupTools: "补工具",
  nextSetupToolsHint: "hint",
  nextSetupWorkspace: "补工作区",
  nextSetupWorkspaceHint: "hint",
  nextSetupMembership: "补归属",
  nextSetupMembershipHint: "hint",
  nextHandleInbox: "处理收件箱",
  nextHandleInboxHint: "hint",
  managementFilterMissingPersona: "缺人物",
  managementFilterMissingPersonaHint: "hint",
  managementFilterMissingTask: "缺任务",
  managementFilterMissingTaskHint: "hint",
  managementFilterMissingTools: "缺工具",
  managementFilterMissingToolsHint: "hint",
  managementFilterNoTeam: "无团队",
  managementFilterNoTeamHint: "hint",
  managementFilterPendingInbox: "待收件",
  managementFilterPendingInboxHint: "hint",
  managementFilterMaintenance: "需维护",
  managementFilterMaintenanceHint: "hint",
  activeAgents: "可用",
  groupLabels: {},
  groupDescriptions: {},
  statusReminderShort: "提醒",
  healthIssueShort: "问题",
  sessionAgentColumn: "会话",
  sessionAgentColumnHint: "hint",
  nonSessionAgentColumn: "非会话",
  nonSessionAgentColumnHint: "hint",
  teamAgentColumnHint: "团队",
} as const;

describe("agentRouteManagementModel", () => {
  it("scores work-session management brief and setup filters", () => {
    const agent = {
      agentId: "a1",
      status: "active",
      agentBoundary: { type: "work_session", requiresPersonaProfile: "false", requiresTaskProfile: "false", requiresTeamMembership: "false" },
      llmBindings: { dialogue: { modelId: "m1" } },
      promptTemplateId: "p1",
      toolPolicy: { allowedTools: ["read"] },
      workspacePath: "w",
      runtimeStatus: { state: "idle" },
      agentInboxPendingCount: 1,
      references: [],
      health: [{ severity: "warning" }],
    } as unknown as AgentConfigWorkspaceAgent;

    const brief = buildAgentManagementBrief(agent, copy as never, "zh");
    expect(brief.total).toBe(4);
    expect(brief.actions.some((item) => item.id === "inbox")).toBe(true);
    expect(managementFilterMatches(agent, "setup:inbox")).toBe(true);
    expect(managementFilterMatches(agent, "setup:maintenance")).toBe(true);

    const groups = buildManagementFilterGroups([agent], copy as never);
    expect(groups.find((group) => group.id === "setup:inbox")?.count).toBe(1);
  });

  it("builds visible columns and normalizes pane ids", () => {
    const agents = [
      {
        agentId: "s1",
        agentBoundary: { type: "work_session" },
      },
      {
        agentId: "t1",
        agentBoundary: { type: "team_role" },
      },
    ] as AgentConfigWorkspaceAgent[];
    const columns = buildVisibleAgentColumns(agents, copy as never, [
      { id: "teamA", label: "Team A", section: "team_index", agentIds: ["t1"], description: "" },
    ] as never);
    expect(columns.map((column) => column.id)).toContain("session_agents");
    expect(columns.some((column) => column.id.startsWith("team_agents:"))).toBe(true);
    expect(normalizeAgentConfigPane("config")).toBe("config");
    expect(normalizeAgentConfigPane("nope")).toBe("overview");
    expect(groupSectionId({ section: "team_index" } as never)).toBe("team_index");
  });
});
